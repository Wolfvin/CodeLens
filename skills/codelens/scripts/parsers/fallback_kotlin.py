"""
Fallback Kotlin Parser for CodeLens — regex-based extraction.
Extracts classes, data classes, sealed classes, objects, companion objects,
interfaces, functions, extension functions, properties, type aliases, imports,
annotations, and function call relationships for edge resolution.

Supports:
  - fun, suspend fun, infix fun, operator fun, inline fun
  - class, data class, sealed class, abstract class, enum class, open class
  - object, companion object
  - interface
  - typealias
  - val/var properties (with custom getters)
  - extension functions: fun Type.name()
  - coroutines: launch{}, async{}, withContext{}, flow{}, channelFlow{}
  - annotations: @Composable, @Inject, @HiltViewModel, @Singleton, etc.
  - import, package
  - implements (:) edges
  - call edges within function bodies
"""

import re
from typing import Dict, List, Any


# ─── Kotlin keywords / builtins to filter from call edges ───────────
_KOTLIN_KEYWORDS = frozenset({
    'if', 'else', 'when', 'for', 'while', 'do', 'try', 'catch', 'finally',
    'return', 'throw', 'break', 'continue', 'class', 'interface', 'object',
    'enum', 'sealed', 'abstract', 'open', 'data', 'inner', 'companion',
    'fun', 'val', 'var', 'const', 'lateinit', 'override', 'private',
    'protected', 'internal', 'public', 'suspend', 'inline', 'noinline',
    'crossinline', 'reified', 'tailrec', 'operator', 'infix', 'typealias',
    'import', 'package', 'as', 'is', 'in', '!in', 'out', 'in', 'where',
    'by', 'constructor', 'init', 'get', 'set', 'field', 'delegate',
    'property', 'receiver', 'param', 'setparam', 'dynamic', 'true',
    'false', 'null', 'this', 'super', 'it', 'also', 'let', 'apply',
    'run', 'with', 'takeIf', 'takeUnless', 'repeat', 'lazy', 'observable',
    'println', 'print', 'assert', 'require', 'check', 'error',
    'todo', 'TODO',
    # Coroutine builders / scope functions we treat as keywords in edges
    'launch', 'async', 'withContext', 'flow', 'channelFlow', 'produce',
    'suspend', 'resume', 'resumeWithException', 'yield',
    # Common standard lib false positives
    'toString', 'equals', 'hashCode', 'copy', 'component1', 'component2',
    'component3', 'component4', 'component5',
})


def parse_kotlin_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Kotlin source using regex — extracts classes, functions, and call edges.

    Args:
        content: File content as string.
        rel_path: Relative file path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' keys.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Collect definitions for edge resolution
    fn_defs: Dict[str, str] = {}      # fn_name → node_id
    type_defs: Dict[str, str] = {}    # type_name → node_id

    # ─── Package ────────────────────────────────────────────────────
    pkg = ""
    for line in lines:
        m = re.match(r'\s*package\s+([\w.]+)\s*', line)
        if m:
            pkg = m.group(1)
            break

    # ─── Imports ────────────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*import\s+([\w.*]+)(?:\s+as\s+(\w+))?\s*', line)
        if m:
            import_path = m.group(1)
            edges.append({
                "from": rel_path,
                "to": import_path,
                "type": "imports",
                "file": rel_path,
                "line": i,
            })

    # ─── Annotations ────────────────────────────────────────────────
    # Collect annotations and associate them with the next declaration.
    # We record them as edges (decorates relationship) and tag nodes.
    _pending_annotations: List[str] = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Match annotations: @Name or @Name(...) or @Name(arg1, arg2)
        for m in re.finditer(r'@(\w+)(?:\s*\([^)]*\))?', stripped):
            annotation_name = m.group(1)
            # Filter out common non-semantic annotations
            if annotation_name in ('Override', 'Deprecated', 'Suppress', 'Suppress',
                                   'SuppressWarnings', 'PublishedApi', 'JvmStatic',
                                   'JvmOverloads', 'JvmField', 'JvmName',
                                   'JvmMultifileClass', 'JvmWildcard', 'Throws'):
                continue
            _pending_annotations.append(annotation_name)

    # ─── Type aliases ───────────────────────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*typealias\s+(\w+)\s*=\s*(.+)', line)
        if m:
            alias_name = m.group(1)
            aliased_type = m.group(2).strip()
            node_id = f"{rel_path}:{i}:{alias_name}"
            nodes.append({
                "id": node_id, "type": "typealias",
                "name": alias_name, "fn": alias_name,
                "file": rel_path, "line": i,
            })
            type_defs[alias_name] = node_id
            # Edge from alias to the aliased type
            base_type = re.match(r'([\w.]+)', aliased_type)
            if base_type:
                edges.append({
                    "from": node_id,
                    "to": base_type.group(1),
                    "type": "aliases",
                    "file": rel_path,
                    "line": i,
                })

    # ─── Classes / Data classes / Sealed classes / Abstract classes /
    #       Enum classes / Open classes / Objects / Companion objects ─

    # Pattern for class-like declarations
    # Handles: [modifiers] (data|sealed|abstract|enum|open|inner)* class Name<...>(...) : ...
    # Also handles: [modifiers] object Name [: ...]
    # Also handles: companion object { ... }
    _RE_CLASS = re.compile(
        r'^\s*'
        r'(?:(?:public|private|protected|internal)\s+)?'  # visibility
        r'(?:(?:data|sealed|abstract|enum|open|inner|expect|actual|value|fun)\s+)*'  # class modifiers
        r'(class|object)\s+'                              # keyword
        r'(\w+)?'                                         # name (optional for companion object)
    )
    _RE_COMPANION = re.compile(r'^\s*companion\s+object\s*(\w+)?\s*[:{]?')

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # ── companion object ────────────────────────────────────
        m = _RE_COMPANION.match(line)
        if m:
            name = m.group(1) or "Companion"
            node_id = f"{rel_path}:{i}:{name}"
            ntype = "companion_object"
            nodes.append({
                "id": node_id, "type": ntype,
                "name": name, "fn": name,
                "file": rel_path, "line": i,
            })
            type_defs[name] = node_id
            # Check for supertype
            m2 = re.search(r':\s*([\w.]+)', line[line.find('companion'):])
            if m2:
                edges.append({
                    "from": node_id,
                    "to": m2.group(1),
                    "type": "implements",
                    "file": rel_path,
                    "line": i,
                })
            continue

        # ── class / object ──────────────────────────────────────
        m = _RE_CLASS.match(line)
        if m:
            keyword = m.group(1)
            name = m.group(2)
            if not name:
                continue

            # Determine the specific type
            ntype = "class"
            if 'data ' in stripped:
                ntype = "data_class"
            elif 'sealed ' in stripped:
                ntype = "sealed_class"
            elif 'abstract ' in stripped:
                ntype = "abstract_class"
            elif 'enum ' in stripped:
                ntype = "enum_class"
            elif keyword == 'object':
                ntype = "object"

            node_id = f"{rel_path}:{i}:{name}"
            nodes.append({
                "id": node_id, "type": ntype,
                "name": name, "fn": name,
                "file": rel_path, "line": i,
            })
            type_defs[name] = node_id

            # Check for supertypes (implements / extends via colon)
            # Kotlin: class Foo : Bar(), Baz
            # Must skip past constructor params (which may contain colons in types)
            # e.g. data class Success(val data: String) : UiState()
            supertypes = _extract_supertypes(line, name)
            for parent in supertypes:
                if parent not in ('Unit', 'Any', 'Nothing'):
                    edges.append({
                        "from": node_id,
                        "to": parent,
                        "type": "implements",
                        "file": rel_path,
                        "line": i,
                    })
            continue

    # ─── Interfaces ─────────────────────────────────────────────────
    _RE_INTERFACE = re.compile(
        r'^\s*'
        r'(?:(?:public|private|protected|internal)\s+)?'
        r'(?:fun\s+)?'  # fun interface (SAM)
        r'interface\s+(\w+)'
    )
    for i, line in enumerate(lines, 1):
        m = _RE_INTERFACE.match(line)
        if m:
            name = m.group(1)
            node_id = f"{rel_path}:{i}:{name}"
            nodes.append({
                "id": node_id, "type": "interface",
                "name": name, "fn": name,
                "file": rel_path, "line": i,
            })
            type_defs[name] = node_id
            # Check for super-interfaces
            m2 = re.search(r':\s*([\w.]+)', line[line.find(name):])
            if m2:
                parent = m2.group(1)
                if parent not in ('Unit', 'Any', 'Nothing'):
                    edges.append({
                        "from": node_id,
                        "to": parent,
                        "type": "implements",
                        "file": rel_path,
                        "line": i,
                    })

    # ─── Functions ──────────────────────────────────────────────────
    # Handles:
    #   fun name(params)
    #   fun <T> name(params)
    #   suspend fun name(params)
    #   fun Type.name(params)          ← extension function
    #   fun Type<T>.name(params)       ← extension with generic receiver
    #   infix fun Type.name(params)
    #   operator fun Type.name(params)
    #   inline fun name(params)
    #   private / protected / internal / public fun name(params)
    #   override fun name(params)
    #   tailrec fun name(params)
    _RE_FUN = re.compile(
        r'^\s*'
        r'(?:(?:public|private|protected|internal)\s+)?'  # visibility
        r'(?:(?:override|open|abstract|final|suspend|inline|noinline|crossinline|'
        r'tailrec|operator|infix|expect|actual|reified|lateinit|external)\s+)*'  # modifiers
        r'fun\s+'                                           # fun keyword
        r'(?:<[^>]+>\s*)?'                                  # optional type params <T>
        r'(?:(\w[\w.<>,\s\[\]]*?)\s*\.\s*)?'               # optional receiver Type. (group 1)
        r'(\w+)'                                            # function name (group 2)
        r'\s*[\(<]'                                         # open paren or type param
    )

    for i, line in enumerate(lines, 1):
        m = _RE_FUN.match(line)
        if not m:
            continue
        receiver = m.group(1)
        fn_name = m.group(2)

        # Skip keywords that look like function names
        if fn_name in _KOTLIN_KEYWORDS:
            continue

        node_id = f"{rel_path}:{i}:{fn_name}"
        ntype = "function"
        display_name = fn_name

        if receiver:
            ntype = "extension_function"
            display_name = f"{receiver.strip()}.{fn_name}"
        elif 'suspend ' in line[:line.find('fun')]:
            ntype = "suspend_function"
        elif 'infix ' in line[:line.find('fun')]:
            ntype = "infix_function"
        elif 'operator ' in line[:line.find('fun')]:
            ntype = "operator_function"

        # Check for annotations on the preceding lines
        annotations = _collect_annotations(lines, i)

        node = {
            "id": node_id,
            "type": ntype,
            "name": display_name,
            "fn": fn_name,
            "file": rel_path,
            "line": i,
        }
        if receiver:
            node["receiver"] = receiver.strip()
        if annotations:
            node["annotations"] = annotations

        nodes.append(node)
        fn_defs[fn_name] = node_id

    # ─── Properties (val/var with custom getters or type annotations) ─
    _RE_PROPERTY = re.compile(
        r'^\s*'
        r'(?:(?:public|private|protected|internal)\s+)?'
        r'(?:(?:override|open|abstract|final|lateinit|const|expect|actual|external)\s+)*'
        r'(val|var)\s+'
        r'(\w+)'                                             # property name
        r'(?:\s*:\s*([\w.<>,\s\[\]?]+))?'                    # optional type
        r'\s*(?:[=]{1}|get\s*\(|$)'                          # assignment, getter, or end
    )
    for i, line in enumerate(lines, 1):
        m = _RE_PROPERTY.match(line)
        if not m:
            continue
        kind = m.group(1)  # val or var
        prop_name = m.group(2)
        prop_type = m.group(3)

        # Skip keywords
        if prop_name in _KOTLIN_KEYWORDS:
            continue

        # Only record properties that have custom getters or explicit types
        # at class/object level (indent <= 4)
        indent = len(line) - len(line.lstrip())
        if indent > 4:
            continue

        # Check for custom getter on same or subsequent lines
        has_getter = bool(re.search(r'\bget\s*\(', line))

        node_id = f"{rel_path}:{i}:{prop_name}"
        ntype = "property"
        if has_getter:
            ntype = "property_getter"
        elif kind == 'const':
            ntype = "constant"

        node = {
            "id": node_id,
            "type": ntype,
            "name": prop_name,
            "fn": prop_name,
            "file": rel_path,
            "line": i,
        }
        if prop_type:
            node["value_type"] = prop_type.strip()
        nodes.append(node)
        fn_defs[prop_name] = node_id

    # ─── Annotations as nodes ───────────────────────────────────────
    # Track notable framework annotations as lightweight nodes
    _NOTABLE_ANNOTATIONS = frozenset({
        'Composable', 'Inject', 'Singleton', 'HiltViewModel', 'AndroidEntryPoint',
        'Module', 'InstallIn', 'Provides', 'Binds', 'EntryPoint',
        'Worker', 'HiltWorker', 'AssistedInject', 'Assisted',
        'Serializable', 'Parcelize', 'Keep', 'Suppress',
    })
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        for m in re.finditer(r'@(\w+)(?:\s*\([^)]*\))?', stripped):
            annotation_name = m.group(1)
            if annotation_name in _NOTABLE_ANNOTATIONS:
                node_id = f"{rel_path}:{i}:@{annotation_name}"
                nodes.append({
                    "id": node_id,
                    "type": "annotation",
                    "name": f"@{annotation_name}",
                    "fn": f"@{annotation_name}",
                    "file": rel_path,
                    "line": i,
                })

    # ─── Function call edges ────────────────────────────────────────
    # Build function→body range map (brace-tracking)
    fn_ranges = []
    current_fn = None
    fn_start = 0
    brace_count = 0

    for i, line in enumerate(lines, 1):
        # Check if this line starts a function
        for node in nodes:
            if (node.get("line") == i and
                node.get("type") in ("function", "extension_function",
                                     "suspend_function", "infix_function",
                                     "operator_function", "property_getter")):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn:
            stripped = line.strip()
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0 and i > fn_start:
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    _RE_METHOD_CALL = re.compile(r'([\w]+)\.([\w]+)\s*\(')
    _RE_SIMPLE_CALL = re.compile(r'(?<!\.)([\w]+)\s*\(')

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])

        # Method calls: obj.method()
        for m in _RE_METHOD_CALL.finditer(body):
            obj = m.group(1)
            method = m.group(2)
            if obj in _KOTLIN_KEYWORDS or method in _KOTLIN_KEYWORDS:
                continue
            if method in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[method],
                    "type": "calls",
                    "file": rel_path,
                    "line": start_line,
                })
            else:
                full_name = f"{obj}.{method}"
                edges.append({
                    "from": fn_id,
                    "to": full_name,
                    "type": "calls",
                    "file": rel_path,
                    "line": start_line,
                })

        # Simple function calls: funcName()
        for m in _RE_SIMPLE_CALL.finditer(body):
            called = m.group(1)
            if called in _KOTLIN_KEYWORDS:
                continue
            if called in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[called],
                    "type": "calls",
                    "file": rel_path,
                    "line": start_line,
                })

    return {"nodes": nodes, "edges": edges}


# ─── Helpers ────────────────────────────────────────────────────────

def _extract_supertypes(line: str, class_name: str) -> List[str]:
    """Extract supertype names from a Kotlin class/object declaration line.

    Skips past the constructor parameter list (which may contain colons in
    type annotations like ``val data: String``) before looking for the
    inheritance colon.

    Example::
        "data class Success(val data: String) : UiState()" -> ["UiState"]
    """
    # Find where the class name starts in the line
    name_pos = line.find(class_name)
    if name_pos == -1:
        return []
    rest = line[name_pos + len(class_name):]

    # Skip optional type parameters <T, U>
    if rest.startswith('<'):
        depth = 0
        idx = 0
        while idx < len(rest):
            if rest[idx] == '<':
                depth += 1
            elif rest[idx] == '>':
                depth -= 1
                if depth == 0:
                    rest = rest[idx + 1:]
                    break
            idx += 1
        else:
            return []

    # Skip constructor parameters (...), accounting for nested parens/angles
    if rest.lstrip().startswith('('):
        rest = rest.lstrip()
        depth = 0
        idx = 0
        while idx < len(rest):
            c = rest[idx]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    rest = rest[idx + 1:]
                    break
            idx += 1
        else:
            return []

    # Now find the inheritance colon and extract supertype names
    supertypes: List[str] = []
    colon_match = re.search(r':\s*', rest)
    if not colon_match:
        return supertypes

    after_colon = rest[colon_match.end():]
    # Extract supertype names — they appear as Name, Name<T>, Name(), Name<T>()
    # Pattern: Name (optionally with <...>) followed by '(' or ',' or end of string
    for m in re.finditer(r'([\w.]+)(?:\s*<[^>]*>)?\s*(?:[\(,]|\s*$)', after_colon):
        sup = m.group(1)
        if sup and sup[0].isupper():
            supertypes.append(sup)

    return supertypes


def _collect_annotations(lines: List[str], target_line: int) -> List[str]:
    """Scan backwards from target_line to collect annotations that precede it.

    Looks at up to 5 lines before the target for @Annotation markers.
    """
    annotations: List[str] = []
    start = max(0, target_line - 6)  # lines is 1-indexed, look back up to 5 lines
    for j in range(start, target_line):
        if j < 1 or j > len(lines):
            continue
        line_text = lines[j - 1] if j - 1 < len(lines) else ""
        for m in re.finditer(r'@(\w+)(?:\s*\([^)]*\))?', line_text.strip()):
            annotation_name = m.group(1)
            annotations.append(annotation_name)
    return annotations
