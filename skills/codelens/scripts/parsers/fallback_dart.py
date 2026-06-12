"""
Dart/Flutter fallback parser for CodeLens.
Regex-based parser that extracts structural information from Dart source files
without requiring tree-sitter.

Extracts:
- Classes (with methods, fields, constructors)
- Abstract classes
- Mixins
- Enums (with values)
- Extensions
- Typedefs
- Functions (top-level)
- Imports (package:, dart:, relative)
- Flutter-specific patterns:
  - Widgets (StatelessWidget, StatefulWidget, HookConsumerWidget, ConsumerWidget, etc.)
  - Riverpod providers (Provider, StateNotifierProvider, FutureProvider, etc.)
  - AutoRoute / @RoutePage annotations
  - BuildContext usage
  - State classes
"""

import re
from typing import Dict, List, Any, Optional


def parse_dart_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse a Dart file using regex fallback.

    Args:
        content: File content as string.
        rel_path: Relative file path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' keys.
    """
    nodes = []
    edges = []

    lines = content.split('\n')
    line_count = len(lines)

    # ─── Imports ────────────────────────────────────────────────
    _extract_imports(content, rel_path, nodes, edges)

    # ─── Typedefs ───────────────────────────────────────────────
    _extract_typedefs(content, rel_path, nodes, edges)

    # ─── Enums ──────────────────────────────────────────────────
    _extract_enums(content, rel_path, nodes, edges)

    # ─── Mixins ─────────────────────────────────────────────────
    _extract_mixins(content, rel_path, nodes, edges)

    # ─── Extensions ─────────────────────────────────────────────
    _extract_extensions(content, rel_path, nodes, edges)

    # ─── Classes ────────────────────────────────────────────────
    _extract_classes(content, rel_path, nodes, edges)

    # ─── Top-level functions ────────────────────────────────────
    _extract_functions(content, rel_path, nodes, edges)

    # ─── Riverpod providers ─────────────────────────────────────
    _extract_providers(content, rel_path, nodes, edges)

    # ─── Flutter routes ─────────────────────────────────────────
    _extract_routes(content, rel_path, nodes, edges)

    return {
        "nodes": nodes,
        "edges": edges,
    }


# ─── Import patterns ────────────────────────────────────────────

_RE_IMPORT = re.compile(
    r"""import\s+'''
    |import\s+['"]([^'"]+)['"]""", re.VERBOSE
)

_RE_DART_IMPORT = re.compile(r"import\s+['\"]([^'\"]+)['\"]")

_RE_PART = re.compile(r"part\s+['\"]([^'\"]+)['\"]")


def _extract_imports(content: str, rel_path: str, nodes: list, edges: list):
    """Extract import statements."""
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        m = _RE_DART_IMPORT.match(stripped)
        if m:
            import_path = m.group(1)
            edge = {
                "from": f"{rel_path}:{i}:import",
                "to_fn": import_path,
                "resolved": False,
            }
            edges.append(edge)

            # Detect Flutter/Dart framework usage
            if import_path.startswith('package:flutter/'):
                _add_node(nodes, rel_path, i, "_flutter_import", "flutter_import",
                          component=False)
            elif import_path.startswith('dart:'):
                _add_node(nodes, rel_path, i, f"dart:{import_path[5:]}", "dart_import",
                          component=False)


# ─── Typedef patterns ──────────────────────────────────────────

_RE_TYPEDEF = re.compile(
    r"typedef\s+((?:_?\w+\s*=\s*)?)(\w+)\s*="
)


def _extract_typedefs(content: str, rel_path: str, nodes: list, edges: list):
    """Extract typedef declarations."""
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        m = _RE_TYPEDEF.match(stripped)
        if m:
            name = m.group(2)
            _add_node(nodes, rel_path, i, name, "typedef")


# ─── Enum patterns ──────────────────────────────────────────────

_RE_ENUM = re.compile(
    r"enum\s+(\w+)(?:\s+with\s+[\w,\s]+)?(?:\s+implements\s+[\w,\s]+)?\s*\{"
)


def _extract_enums(content: str, rel_path: str, nodes: list, edges: list):
    """Extract enum declarations and their values."""
    for m in _RE_ENUM.finditer(content):
        name = m.group(1)
        # Find the line number
        pos = m.start()
        line_no = content[:pos].count('\n') + 1

        # Extract enum values
        enum_body = _extract_brace_block(content, m.end() - 1)
        values = []
        if enum_body:
            # Simple comma-separated values before first method
            for val_match in re.finditer(r'(\w+)[,\s]', enum_body.split('(')[0] if '(' in enum_body else enum_body):
                val = val_match.group(1)
                if val[0].isupper() or val == '_':
                    values.append(val)

        _add_node(nodes, rel_path, line_no, name, "enum",
                  extra={"values": values[:20]})  # Cap at 20 values


# ─── Mixin patterns ─────────────────────────────────────────────

_RE_MIXIN = re.compile(
    r"mixin\s+(\w+)(?:\s+on\s+[\w<>,\s]+)?(?:\s+implements\s+[\w<>,\s]+)?\s*\{"
)


def _extract_mixins(content: str, rel_path: str, nodes: list, edges: list):
    """Extract mixin declarations."""
    for m in _RE_MIXIN.finditer(content):
        name = m.group(1)
        pos = m.start()
        line_no = content[:pos].count('\n') + 1
        _add_node(nodes, rel_path, line_no, name, "mixin")


# ─── Extension patterns ─────────────────────────────────────────

_RE_EXTENSION = re.compile(
    r"extension\s+(\w+)?\s*(?:on\s+[\w<>,\s\[\]]+)?\s*\{"
)


def _extract_extensions(content: str, rel_path: str, nodes: list, edges: list):
    """Extract extension declarations."""
    for m in _RE_EXTENSION.finditer(content):
        name = m.group(1)
        if not name:
            name = "<anonymous_extension>"
        pos = m.start()
        line_no = content[:pos].count('\n') + 1
        _add_node(nodes, rel_path, line_no, name, "extension")


# ─── Class patterns ─────────────────────────────────────────────

_RE_CLASS = re.compile(
    r"(?:^|\n)"                             # start of line
    r"((?:abstract\s+)?"                    # optional abstract
    r"(?:class|interface)\s+)"              # class/interface keyword
    r"(\w+)"                                # class name
    r"(?:\s*<[^>]+>)?"                      # optional type params <T, V>
    r"(?:\s+extends\s+([\w<>,.\s]+?))?"     # optional extends
    r"(?:\s+with\s+([\w<>,.\s]+?))?"        # optional with (mixins)
    r"(?:\s+implements\s+([\w<>,.\s]+?))?"  # optional implements
    r"\s*(?:\{|$)"                           # opening brace or end of line
)

# Flutter widget base classes
_WIDGET_BASES = frozenset({
    'StatelessWidget', 'StatefulWidget', 'ConsumerWidget',
    'ConsumerStatefulWidget', 'HookConsumerWidget',
    'HookConsumerStatefulWidget', 'HookWidget',
    'StatefulHookWidget', 'InheritedWidget',
    'InheritedModel', 'LeafRenderObjectWidget',
    'SingleChildRenderObjectWidget', 'RenderObjectWidget',
    'StatelessElement', 'StatefulElement',
})

# Dart function call pattern
_RE_FUNC_CALL = re.compile(r'(\w+)\s*\(')

# Method patterns inside classes
_RE_METHOD = re.compile(
    r"(?:^|\n)\s+"
    r"((?:static\s+)?(?:async\s+)?)"          # optional static/async
    r"((?:[\w<>,\s\[\]]+\s+))?"               # return type
    r"(_?\w+)"                                 # method name
    r"\s*\("                                   # opening paren
)

_RE_CONSTRUCTOR = re.compile(
    r"(?:^|\n)\s+"
    r"(\w+)"                                   # class name
    r"(?:\.(\w+))?"                            # optional named constructor
    r"\s*\("
)

_RE_FIELD = re.compile(
    r"(?:^|\n)\s+"
    r"((?:static\s+)?(?:final\s+)?(?:late\s+)?(?:const\s+)?)"  # modifiers
    r"((?:[\w<>,\s\[\]]+\s+))?"               # type
    r"(_?\w+)"                                 # field name
    r"\s*(?:[=;])"
)


def _extract_classes(content: str, rel_path: str, nodes: list, edges: list):
    """Extract class declarations with methods, fields, and Flutter-specific info."""
    for m in _RE_CLASS.finditer(content):
        prefix = m.group(1)  # "abstract class " or "class "
        name = m.group(2)
        extends = m.group(3)
        with_mixins = m.group(4)
        implements = m.group(5)

        pos = m.start()
        line_no = content[:pos].count('\n') + 1

        is_abstract = 'abstract' in prefix

        # Determine if this is a Flutter widget
        is_widget = False
        widget_type = None
        if extends:
            extends_stripped = extends.strip().split('<')[0].strip()
            if extends_stripped in _WIDGET_BASES:
                is_widget = True
                widget_type = extends_stripped
        # Also check with mixins for ConsumerWidget etc.
        if with_mixins:
            for mixin_name in with_mixins.split(','):
                mixin_stripped = mixin_name.strip().split('<')[0].strip()
                if mixin_stripped in _WIDGET_BASES:
                    is_widget = True
                    widget_type = mixin_stripped

        # Check for @RoutePage annotation before class
        has_route_annotation = False
        pre_text = content[:m.start()]
        for pre_line in pre_text.split('\n')[-5:]:
            if '@RoutePage' in pre_line or '@routePage' in pre_line:
                has_route_annotation = True
                break

        # Determine node type
        if is_widget:
            node_type = "flutter_widget"
        elif has_route_annotation:
            node_type = "flutter_route_page"
        elif is_abstract:
            node_type = "abstract_class"
        else:
            node_type = "class"

        extra = {}
        if is_widget and widget_type:
            extra["widget_type"] = widget_type
        if extends:
            extra["extends"] = extends.strip()
        if with_mixins:
            extra["mixins"] = [x.strip() for x in with_mixins.split(',') if x.strip()]
        if implements:
            extra["implements"] = [x.strip() for x in implements.split(',') if x.strip()]
        if has_route_annotation:
            extra["is_route"] = True

        # Extract class body for methods
        class_body = _extract_brace_block(content, content.find('{', m.start()))

        methods = []
        fields = []
        if class_body:
            # Extract constructors
            for cm in _RE_CONSTRUCTOR.finditer(class_body):
                ctor_name = cm.group(1)
                named = cm.group(2)
                if ctor_name == name:
                    method_fn = f"{name}.{named}" if named else name
                    methods.append(method_fn)

            # Extract methods (simplified)
            method_names = set()
            for mm in _RE_METHOD.finditer(class_body):
                mname = mm.group(3)
                # Filter out Dart keywords and common false positives
                if mname not in _DART_KEYWORDS and mname not in method_names:
                    method_names.add(mname)
                    methods.append(mname)

            # Extract fields
            for fm in _RE_FIELD.finditer(class_body):
                fname = fm.group(3)
                if fname not in _DART_KEYWORDS and fname[0] != '_':
                    fields.append(fname)

        extra["methods"] = methods[:50]  # Cap at 50
        extra["fields"] = fields[:30]    # Cap at 30

        node = {
            "id": f"{rel_path}:{line_no}:{name}",
            "fn": name,
            "file": rel_path,
            "line": line_no,
            "type": node_type,
            "component": is_widget,
            "exported": not name.startswith('_'),
        }
        if extra:
            node["extra"] = extra
        nodes.append(node)

        # Create edges for extends/implements
        if extends:
            for ext_name in extends.split(','):
                ext_clean = ext_name.strip().split('<')[0].strip()
                if ext_clean and ext_clean[0].isupper():
                    edges.append({
                        "from": f"{rel_path}:{line_no}:{name}",
                        "to_fn": ext_clean,
                        "resolved": False,
                    })
        if implements:
            for impl_name in implements.split(','):
                impl_clean = impl_name.strip().split('<')[0].strip()
                if impl_clean and impl_clean[0].isupper():
                    edges.append({
                        "from": f"{rel_path}:{line_no}:{name}",
                        "to_fn": impl_clean,
                        "resolved": False,
                    })


# ─── Top-level function patterns ────────────────────────────────

_RE_FUNCTION = re.compile(
    r"(?:^|\n)"
    r"((?:async\s*)?)"                         # optional async
    r"((?:[\w<>,\s\[\]<>\?]+\s+))?"           # return type
    r"(\w+)"                                   # function name
    r"\s*\("                                   # opening paren
    r"(?![^{]*\bclass\b)"                      # not a class declaration
)

_RE_TOP_LEVEL_FUNC = re.compile(
    r"^(?!.*\bclass\b)(?!.*\babstract\b)"
    r"((?:Future|Stream|void|int|double|String|bool|List|Map|Set|dynamic|Object|num|Never|Iterable|Duration|Uri|RegExp|DateTime|Widget|BuildContext|Color|Size|EdgeInsets|Key|ThemeData|TextStyle)\s*<[^>]*>\s+|"
    r"(?:Future|Stream|void|int|double|String|bool|List|Map|Set|dynamic|Object|num|Never|Iterable|Duration|Uri|RegExp|DateTime|Widget|BuildContext|Color|Size|EdgeInsets|Key|ThemeData|TextStyle)\s+|"
    r"\w+\s*\?\s+|"
    r"\w+\s+)"
    r"(\w+)\s*\(",
    re.MULTILINE
)


def _extract_functions(content: str, rel_path: str, nodes: list, edges: list):
    """Extract top-level function declarations."""
    # Find top-level functions (not indented)
    for i, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        # Skip class/enum/mixin/extension declarations
        if any(stripped.startswith(kw) for kw in ('class ', 'abstract ', 'enum ', 'mixin ', 'extension ', 'import ', 'part ', 'library ')):
            continue

        # Match function-like pattern at top level or near-top level
        m = re.match(
            r'((?:static\s+)?(?:async\s+)?'
            r'(?:[\w<>,\s\[\]\?]+\s+)?)'
            r'(\w+)\s*\(',
            stripped
        )
        if m:
            name = m.group(2)
            # Filter out keywords and common false positives
            if name in _DART_KEYWORDS:
                continue
            if name.startswith('_') and len(name) == 1:
                continue
            # Skip if it looks like a method call (inside a class body)
            # Check indentation - top level should have 0-1 levels
            indent = len(line) - len(line.lstrip())
            if indent > 4:  # Deeply indented = inside a method
                continue

            # Skip common false positives
            if name in ('if', 'for', 'while', 'switch', 'catch', 'assert',
                        'return', 'throw', 'new', 'super', 'this', 'print',
                        'await', 'yield', 'try', 'else', 'do'):
                continue

            _add_node(nodes, rel_path, i, name, "function",
                      exported=not name.startswith('_'))

            # Extract function calls within the function for edges
            # (simplified: just look for callable names)


# ─── Riverpod provider patterns ─────────────────────────────────

_RE_PROVIDER = re.compile(
    r"final\s+(\w+Provider)\s*=\s*"
    r"(Provider|StateNotifierProvider|StateProvider|FutureProvider|StreamProvider|"
    r"ChangeNotifierProvider|NotifierProvider|AsyncNotifierProvider|"
    r"Provider\.family|StateNotifierProvider\.family|FutureProvider\.family|"
    r"AutoDisposeProvider|AutoDisposeStateProvider|"
    r"AutoDisposeFutureProvider|AutoDisposeStateNotifierProvider)"
    r"\b"
)

_RE_RIVERPOD_ANNOTATION = re.compile(
    r"@riverpod"
)


def _extract_providers(content: str, rel_path: str, nodes: list, edges: list):
    """Extract Riverpod provider declarations."""
    for m in _RE_PROVIDER.finditer(content):
        name = m.group(1)
        provider_type = m.group(2)
        pos = m.start()
        line_no = content[:pos].count('\n') + 1

        _add_node(nodes, rel_path, line_no, name, "riverpod_provider",
                  extra={"provider_type": provider_type},
                  component=False)

    # Also detect @riverpod annotation (code-generation style)
    for m in _RE_RIVERPOD_ANNOTATION.finditer(content):
        pos = m.start()
        line_no = content[:pos].count('\n') + 1
        # Find the next function/class declaration after the annotation
        remaining = content[m.end():]
        func_match = re.search(r'(\w+)\s*\(', remaining[:200])
        if func_match:
            name = func_match.group(1)
            _add_node(nodes, rel_path, line_no, name, "riverpod_provider",
                      extra={"provider_type": "code_generated"},
                      component=False)


# ─── Flutter route patterns ─────────────────────────────────────

_RE_AUTO_ROUTE = re.compile(
    r"AutoRoute\s*\(\s*page\s*:\s*(\w+)"
)

_RE_GO_ROUTE = re.compile(
    r"GoRoute\s*\(\s*path\s*:\s*['\"]([^'\"]+)['\"]"
)


def _extract_routes(content: str, rel_path: str, nodes: list, edges: list):
    """Extract Flutter route declarations (AutoRoute, GoRoute)."""
    for m in _RE_AUTO_ROUTE.finditer(content):
        page_name = m.group(1)
        pos = m.start()
        line_no = content[:pos].count('\n') + 1

        _add_node(nodes, rel_path, line_no, page_name, "flutter_route",
                  extra={"route_type": "auto_route"},
                  component=False)

    for m in _RE_GO_ROUTE.finditer(content):
        route_path = m.group(1)
        pos = m.start()
        line_no = content[:pos].count('\n') + 1

        _add_node(nodes, rel_path, line_no, route_path, "flutter_route",
                  extra={"route_type": "go_route", "path": route_path},
                  component=False)


# ─── Helper functions ────────────────────────────────────────────

def _add_node(nodes: list, rel_path: str, line: int, name: str,
              node_type: str, exported: bool = True, component: bool = False,
              extra: dict = None):
    """Add a node to the nodes list."""
    node = {
        "id": f"{rel_path}:{line}:{name}",
        "fn": name,
        "file": rel_path,
        "line": line,
        "type": node_type,
        "exported": exported,
        "component": component,
    }
    if extra:
        node["extra"] = extra
    nodes.append(node)


def _extract_brace_block(content: str, start_pos: int) -> Optional[str]:
    """Extract content between matching braces starting from start_pos.

    Args:
        content: Full file content.
        start_pos: Position of the opening brace.

    Returns:
        Content between braces (excluding outer braces), or None.
    """
    if start_pos < 0 or start_pos >= len(content):
        return None

    # Find the opening brace
    brace_pos = content.find('{', start_pos)
    if brace_pos == -1:
        return None

    depth = 0
    in_string = False
    string_char = None
    i = brace_pos

    while i < len(content):
        c = content[i]

        # Handle string literals
        if not in_string:
            if c in ('"', "'", '`'):
                in_string = True
                string_char = c
                # Check for triple-quoted strings
                if content[i:i+3] in ('"""', "'''", '```'):
                    string_char = content[i:i+3]
                    i += 2  # Skip ahead
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return content[brace_pos + 1:i]
        else:
            if c == '\\' and i + 1 < len(content):
                i += 1  # Skip escaped character
            elif (len(string_char) == 1 and c == string_char) or \
                 (len(string_char) == 3 and content[i:i+3] == string_char):
                was_triple = len(string_char) == 3
                in_string = False
                string_char = None
                if was_triple:
                    i += 2

        i += 1

    return None


# Dart reserved keywords that should not be treated as function names
_DART_KEYWORDS = frozenset({
    'abstract', 'as', 'assert', 'async', 'await', 'break', 'case', 'catch',
    'class', 'const', 'continue', 'covariant', 'default', 'deferred', 'do',
    'dynamic', 'else', 'enum', 'export', 'extends', 'extension', 'external',
    'factory', 'false', 'final', 'finally', 'for', 'Function', 'get', 'hide',
    'if', 'implements', 'import', 'in', 'interface', 'is', 'late', 'library',
    'mixin', 'new', 'null', 'on', 'operator', 'part', 'required', 'rethrow',
    'return', 'sealed', 'set', 'show', 'static', 'super', 'switch', 'sync',
    'this', 'throw', 'true', 'try', 'typedef', 'var', 'void', 'while',
    'with', 'yield',
    # Common built-in methods that are false positives
    'print', 'toString', 'hashCode', 'runtimeType', 'noSuchMethod',
    'compareTo', 'build', 'initState', 'dispose', 'setState',
    'createElement', 'mount', 'unmount', 'deactivate', 'didChangeDependencies',
    'didUpdateWidget', 'reassemble', 'setState', 'build',
})
