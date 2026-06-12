"""
Fallback Kotlin Parser for CodeLens — regex-based extraction.
Extracts classes, functions, objects, companion objects, data classes,
sealed classes, extension functions, suspend functions, properties,
imports, and annotations from Kotlin source files.

Kotlin-specific features handled:
- fun (including extension functions: fun Type.name())
- class / data class / sealed class / sealed interface / enum class / annotation class
- object (singleton declarations)
- companion object
- interface
- suspend functions
- val / var (properties)
- typealias
- Kotlin import syntax (no semicolons)
- @Annotations (including Android-specific ones)
- property delegates (by lazy, by viewModels, etc.)
- lambda receivers and context receivers
"""

import re
from typing import Dict, List, Any, Optional


def parse_kotlin_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Kotlin source using regex — extracts Kotlin-specific constructs.

    Args:
        content: File content as string.
        rel_path: Relative file path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' keys.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # ─── Package ────────────────────────────────────────────────
    pkg = ""
    pkg_match = re.search(r'^\s*package\s+([\w.]+)\s*$', content, re.MULTILINE)
    if pkg_match:
        pkg = pkg_match.group(1)

    # ─── Imports ────────────────────────────────────────────────
    _extract_imports(content, rel_path, edges)

    # ─── Type Aliases ───────────────────────────────────────────
    _extract_typealiases(content, rel_path, nodes, pkg)

    # ─── Annotation classes ─────────────────────────────────────
    _extract_annotation_classes(content, rel_path, nodes, pkg)

    # ─── Enum classes ───────────────────────────────────────────
    _extract_enum_classes(content, rel_path, nodes, pkg)

    # ─── Sealed classes/interfaces ──────────────────────────────
    _extract_sealed_classes(content, rel_path, nodes, pkg)

    # ─── Data classes ───────────────────────────────────────────
    _extract_data_classes(content, rel_path, nodes, pkg)

    # ─── Regular classes ────────────────────────────────────────
    _extract_classes(content, rel_path, nodes, pkg)

    # ─── Interfaces ─────────────────────────────────────────────
    _extract_interfaces(content, rel_path, nodes, pkg)

    # ─── Object declarations (singletons) ───────────────────────
    _extract_objects(content, rel_path, nodes, pkg)

    # ─── Companion objects ──────────────────────────────────────
    _extract_companion_objects(content, rel_path, nodes, pkg)

    # ─── Top-level functions (including extension and suspend) ──
    _extract_functions(content, rel_path, nodes, pkg)

    # ─── Top-level properties (val / var) ───────────────────────
    _extract_properties(content, rel_path, nodes, pkg)

    # ─── Android-specific annotations ───────────────────────────
    _extract_android_annotations(content, rel_path, nodes)

    return {"nodes": nodes, "edges": edges}


# ─── Import Extraction ──────────────────────────────────────────

def _extract_imports(content: str, rel_path: str, edges: list):
    """Extract Kotlin import statements (no semicolons required)."""
    for m in re.finditer(r'^\s*import\s+([\w.*]+)(?:\s+as\s+(\w+))?\s*$', content, re.MULTILINE):
        import_path = m.group(1)
        alias = m.group(2)
        edge = {
            "from": rel_path,
            "to": import_path,
            "type": "import",
            "weight": 1,
        }
        if alias:
            edge["alias"] = alias
        edges.append(edge)


# ─── Type Alias Extraction ──────────────────────────────────────

def _extract_typealiases(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract typealias declarations."""
    for m in re.finditer(r'^\s*typealias\s+(\w+)\s*=\s*(.+)$', content, re.MULTILINE):
        name = m.group(1)
        target = m.group(2).strip()
        line_no = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "typealias",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "package": pkg,
            "target_type": target[:100],  # Cap length
        })


# ─── Annotation Class Extraction ────────────────────────────────

def _extract_annotation_classes(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract annotation class declarations."""
    for m in re.finditer(
        r'^\s*(?:public\s+|internal\s+|private\s+)?'
        r'annotation\s+class\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "annotation_class",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
        })


# ─── Enum Class Extraction ──────────────────────────────────────

def _extract_enum_classes(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract enum class declarations with their values."""
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'enum\s+class\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1
        # Extract enum values from the body
        body = _extract_brace_block(content, m.end())
        values = []
        if body:
            for val_m in re.finditer(r'(\w+)\s*(?:[,(\n])', body):
                val = val_m.group(1)
                if val[0].isupper() or val == '_':
                    values.append(val)
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "enum_class",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "values": values[:30],
        })


# ─── Sealed Class Extraction ────────────────────────────────────

def _extract_sealed_classes(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract sealed class and sealed interface declarations."""
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'sealed\s+(class|interface)\s+(\w+)',
        content, re.MULTILINE
    ):
        kind = m.group(1)  # "class" or "interface"
        name = m.group(2)
        line_no = content[:m.start()].count('\n') + 1

        # Check for generic parameters
        generics = ""
        gen_m = re.search(r'<([^>]+)>', content[m.end():m.end() + 50])
        if gen_m:
            generics = gen_m.group(0)

        # Check for inheritance
        inherits = []
        rest = content[m.end():m.end() + 200]
        inherit_m = re.search(r':\s*([^{]+)', rest)
        if inherit_m:
            inherit_str = inherit_m.group(1).strip()
            for part in re.finditer(r'(\w+)', inherit_str):
                parent = part.group(1)
                if parent not in ('constructor', 'this', 'super') and parent != name:
                    inherits.append(parent)

        node_type = "sealed_class" if kind == "class" else "sealed_interface"
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": node_type,
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "generics": generics,
            "inherits": inherits[:5],
        })


# ─── Data Class Extraction ──────────────────────────────────────

def _extract_data_classes(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract data class declarations with their primary constructor properties."""
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'data\s+class\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1

        # Extract primary constructor parameters
        constructor_params = _extract_constructor_params(content, m.end())

        # Check for inheritance
        inherits = []
        rest = content[m.end():m.end() + 200]
        inherit_m = re.search(r'\)\s*:\s*([^{]+)', rest)
        if inherit_m:
            inherit_str = inherit_m.group(1).strip()
            for part in re.finditer(r'(\w+)', inherit_str):
                parent = part.group(1)
                if parent not in ('constructor', 'this', 'super') and parent != name:
                    inherits.append(parent)

        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "data_class",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "properties": constructor_params[:15],
            "inherits": inherits[:5],
        })


# ─── Regular Class Extraction ───────────────────────────────────

def _extract_classes(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract regular class declarations (not data/sealed/enum/annotation)."""
    # Match class declarations but exclude data/sealed/enum/annotation
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'(?:open\s+|abstract\s+)*'
        r'class\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1

        # Skip if this is actually a data/sealed/enum/annotation class
        prefix = content[max(0, m.start() - 30):m.start()]
        if re.search(r'(data|sealed|enum|annotation)\s+$', prefix):
            continue

        # Check for abstract/open
        is_abstract = 'abstract' in prefix.split('class')[0]
        is_open = 'open' in prefix.split('class')[0]

        # Extract primary constructor parameters
        constructor_params = _extract_constructor_params(content, m.end())

        # Check for inheritance
        inherits = []
        rest = content[m.end():m.end() + 300]
        # Look for : after constructor
        inherit_m = re.search(r'\)?\s*:\s*([^{]+)', rest)
        if not inherit_m:
            # No constructor — look for : directly
            inherit_m = re.search(r'\s*:\s*([^{]+)', rest[:100])
        if inherit_m:
            inherit_str = inherit_m.group(1).strip()
            for part in re.finditer(r'(\w+)', inherit_str):
                parent = part.group(1)
                if parent not in ('constructor', 'this', 'super') and parent != name:
                    inherits.append(parent)

        node_type = "abstract_class" if is_abstract else "class"
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": node_type,
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "is_open": is_open,
            "is_abstract": is_abstract,
            "properties": constructor_params[:15],
            "inherits": inherits[:5],
        })


# ─── Interface Extraction ───────────────────────────────────────

def _extract_interfaces(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract interface declarations (not sealed interface)."""
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'interface\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1

        # Skip if this is actually a sealed interface
        prefix = content[max(0, m.start() - 20):m.start()]
        if re.search(r'sealed\s+$', prefix):
            continue

        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "interface",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
        })


# ─── Object (Singleton) Extraction ──────────────────────────────

def _extract_objects(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract object declarations (Kotlin singletons). Excludes companion objects."""
    for m in re.finditer(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'object\s+(\w+)',
        content, re.MULTILINE
    ):
        name = m.group(1)
        line_no = content[:m.start()].count('\n') + 1

        # Skip companion objects
        if name == 'companion':
            continue

        # Check for inheritance
        inherits = []
        rest = content[m.end():m.end() + 200]
        inherit_m = re.search(r':\s*([^{]+)', rest)
        if inherit_m:
            inherit_str = inherit_m.group(1).strip()
            for part in re.finditer(r'(\w+)', inherit_str):
                parent = part.group(1)
                if parent not in ('constructor', 'this', 'super') and parent != name:
                    inherits.append(parent)

        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "object",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "is_singleton": True,
            "inherits": inherits[:5],
        })


# ─── Companion Object Extraction ────────────────────────────────

def _extract_companion_objects(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract companion object declarations."""
    for m in re.finditer(
        r'^\s*companion\s+object(?:\s+(\w+))?\s*\{',
        content, re.MULTILINE
    ):
        name = m.group(1) or "Companion"
        line_no = content[:m.start()].count('\n') + 1
        nodes.append({
            "id": f"{rel_path}:{name}",
            "type": "companion_object",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "package": pkg,
        })


# ─── Function Extraction ────────────────────────────────────────

def _extract_functions(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract top-level and class functions including extension and suspend functions."""
    # Match: fun, suspend fun, inline fun, etc.
    # Also matches extension functions: fun Type.name() or fun Type<T>.name()
    func_pattern = re.compile(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'(?:(?:override|open|abstract|operator|infix|inline|tailrec|external|expect|actual)\s+)*'
        r'(suspend\s+)?'  # suspend modifier
        r'fun\s+'         # fun keyword
        r'(?:<[^>]+>\s*)?'  # optional type parameters
        r'(?:(\w+(?:<[^>]*>)?)\s*\.\s*)?'  # optional receiver type (extension function)
        r'(\w+)\s*\(',    # function name
        re.MULTILINE
    )

    for m in func_pattern.finditer(content):
        is_suspend = bool(m.group(1))
        receiver_type = m.group(2)  # None for regular functions
        func_name = m.group(3)
        line_no = content[:m.start()].count('\n') + 1

        # Skip keywords that could match
        if func_name in ('if', 'else', 'while', 'for', 'when', 'return', 'throw',
                          'class', 'interface', 'object', 'val', 'var'):
            continue

        # Determine function type
        if receiver_type:
            func_type = "extension_function"
        elif is_suspend:
            func_type = "suspend_function"
        else:
            func_type = "function"

        # Check for modifiers
        prefix = content[max(0, m.start() - 50):m.start()]
        is_override = 'override' in prefix.split('fun')[-1] if 'fun' in prefix else False
        is_operator = 'operator' in prefix.split('fun')[-1] if 'fun' in prefix else False

        # Extract parameter types
        params = _extract_function_params(content, m.end())

        # Extract return type
        return_type = _extract_return_type(content, m)

        node = {
            "id": f"{rel_path}:{func_name}",
            "type": func_type,
            "name": func_name,
            "fn": func_name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "is_suspend": is_suspend,
            "is_override": is_override,
            "is_operator": is_operator,
            "params": params[:10],
            "return_type": return_type,
        }

        if receiver_type:
            node["receiver_type"] = receiver_type

        nodes.append(node)


# ─── Property Extraction ────────────────────────────────────────

def _extract_properties(content: str, rel_path: str, nodes: list, pkg: str):
    """Extract top-level val and var properties."""
    prop_pattern = re.compile(
        r'^\s*(?:(?:public|private|protected|internal)\s+)?'
        r'(?:(?:override|open|abstract|const|lateinit)\s+)*'
        r'(val|var)\s+'       # val or var
        r'(\w+)'              # property name
        r'(?:\s*:\s*([^\s=]+))?'  # optional type annotation
        r'(?:\s*=\s*(.+?))?'      # optional initializer
        r'\s*$',
        re.MULTILINE
    )

    for m in prop_pattern.finditer(content):
        mutability = m.group(1)  # "val" or "var"
        name = m.group(2)
        prop_type = m.group(3)
        initializer = m.group(4)
        line_no = content[:m.start()].count('\n') + 1

        # Skip keywords and common false positives
        if name in ('if', 'else', 'while', 'for', 'when', 'return', 'throw',
                     'class', 'interface', 'object', 'fun', 'this', 'super'):
            continue

        # Check for property delegation
        delegate = None
        if initializer and ' by ' in initializer:
            by_match = re.search(r'by\s+(\w+)', initializer)
            if by_match:
                delegate = by_match.group(1)

        node = {
            "id": f"{rel_path}:{name}",
            "type": "property",
            "name": name,
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "domain": "backend",
            "visibility": _extract_visibility(m.group(0)),
            "package": pkg,
            "mutability": mutability,
        }

        if prop_type:
            node["prop_type"] = prop_type.strip()
        if delegate:
            node["delegate"] = delegate
        if initializer:
            # Detect common Android patterns
            init_str = initializer.strip()
            if 'viewModels' in init_str or 'viewModel' in init_str:
                node["android_delegate"] = "viewmodel"
            elif 'lazy' in init_str:
                node["android_delegate"] = "lazy"
            elif 'SharedPreferences' in init_str:
                node["android_delegate"] = "shared_preferences"

        nodes.append(node)


# ─── Android Annotation Extraction ──────────────────────────────

def _extract_android_annotations(content: str, rel_path: str, nodes: list):
    """Extract Android-specific annotations for component detection."""
    android_annotations = {
        '@Inject': 'inject',
        '@Module': 'dagger_module',
        '@Component': 'dagger_component',
        '@Provides': 'dagger_provides',
        '@Singleton': 'dagger_singleton',
        '@ViewModel': 'viewmodel',
        '@HiltViewModel': 'hilt_viewmodel',
        '@AndroidEntryPoint': 'hilt_entrypoint',
        '@EntryPoint': 'hilt_entrypoint',
        '@Worker': 'workmanager_worker',
        '@BindView': 'butterknife_bind',
        '@OnClick': 'butterknife_click',
        '@EBean': 'androidannotations_bean',
        '@EActivity': 'androidannotations_activity',
        '@EService': 'androidannotations_service',
        '@EReceiver': 'androidannotations_receiver',
        '@Composable': 'composable',
    }

    for annotation, annotation_type in android_annotations.items():
        for m in re.finditer(re.escape(annotation), content):
            line_no = content[:m.start()].count('\n') + 1
            # Find the annotated element name
            elem_name = _find_next_element_name(content, m.end())
            nodes.append({
                "id": f"{rel_path}:{annotation_type}:{line_no}",
                "type": "android_annotation",
                "name": annotation,
                "fn": annotation,
                "file": rel_path,
                "line": line_no,
                "domain": "backend",
                "annotation_type": annotation_type,
                "annotated_element": elem_name,
            })


# ─── Helper Functions ───────────────────────────────────────────

def _extract_visibility(prefix: str) -> str:
    """Extract visibility modifier from a code prefix."""
    if 'public' in prefix:
        return "public"
    if 'private' in prefix:
        return "private"
    if 'protected' in prefix:
        return "protected"
    if 'internal' in prefix:
        return "internal"
    return "public"  # Kotlin default is public


def _extract_brace_block(content: str, start: int) -> Optional[str]:
    """Extract a balanced brace block starting from a position after '{'."""
    # Find the opening brace
    brace_pos = content.find('{', start)
    if brace_pos < 0:
        return None

    depth = 0
    pos = brace_pos
    while pos < len(content):
        if content[pos] == '{':
            depth += 1
        elif content[pos] == '}':
            depth -= 1
            if depth == 0:
                return content[brace_pos + 1:pos]
        pos += 1

    return content[brace_pos + 1:]  # Unclosed block


def _extract_constructor_params(content: str, start: int) -> List[Dict[str, str]]:
    """Extract primary constructor parameters from a Kotlin class."""
    params = []

    # Find the opening parenthesis
    paren_pos = content.find('(', start)
    if paren_pos < 0 or paren_pos - start > 10:
        # No primary constructor within reasonable distance
        return params

    # Extract the balanced paren block
    depth = 0
    pos = paren_pos
    end_pos = paren_pos
    while pos < len(content):
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
            if depth == 0:
                end_pos = pos
                break
        pos += 1

    param_str = content[paren_pos + 1:end_pos]

    # Parse individual parameters: val name: Type, var name: Type = default
    for param_m in re.finditer(
        r'(val|var)\s+(\w+)\s*(?::\s*([^\s,=]+))?',
        param_str
    ):
        mutability = param_m.group(1)
        name = param_m.group(2)
        param_type = param_m.group(3)
        param = {"name": name, "mutability": mutability}
        if param_type:
            param["type"] = param_type.strip()
        params.append(param)

    return params


def _extract_function_params(content: str, start: int) -> List[Dict[str, str]]:
    """Extract function parameters."""
    params = []

    # Find opening paren
    paren_pos = content.find('(', start - 1)
    if paren_pos < 0:
        return params

    # Extract balanced paren block
    depth = 0
    pos = paren_pos
    end_pos = paren_pos
    while pos < len(content) and pos < paren_pos + 500:
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
            if depth == 0:
                end_pos = pos
                break
        pos += 1

    param_str = content[paren_pos + 1:end_pos]

    # Parse parameters: name: Type or name: Type = default
    for param_m in re.finditer(
        r'(\w+)\s*:\s*([^\s,=)]+)',
        param_str
    ):
        name = param_m.group(1)
        param_type = param_m.group(2)
        if name in ('val', 'var', 'crossinline', 'noinline', 'reified', 'vararg'):
            continue
        params.append({"name": name, "type": param_type.strip()})

    return params


def _extract_return_type(content: str, match) -> Optional[str]:
    """Extract the return type of a function after the closing paren."""
    # Find the closing paren of the function
    start = match.end()
    depth = 1
    pos = start
    while pos < len(content) and pos < start + 500:
        if content[pos] == '(':
            depth += 1
        elif content[pos] == ')':
            depth -= 1
            if depth == 0:
                # Look for : ReturnType after the closing paren
                rest = content[pos + 1:pos + 60].strip()
                type_match = re.match(r':\s*([^\s{=]+)', rest)
                if type_match:
                    return type_match.group(1).strip()
                break
        pos += 1

    return None


def _find_next_element_name(content: str, offset: int) -> str:
    """Find the next named element (class, function, val, var) after an annotation."""
    remaining = content[offset:offset + 300]
    # Try class
    m = re.search(r'class\s+(\w+)', remaining)
    if m:
        return m.group(1)
    # Try function
    m = re.search(r'fun\s+(\w+)', remaining)
    if m:
        return m.group(1)
    # Try val/var
    m = re.search(r'(?:val|var)\s+(\w+)', remaining)
    if m:
        return m.group(1)
    return "unknown"
