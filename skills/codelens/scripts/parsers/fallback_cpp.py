"""Fallback C/C++ parser (when tree-sitter grammars unavailable).

Extracts:
  - Functions (including static, inline, extern, constexpr)
  - Struct/Class declarations with methods
  - Typedefs and type aliases
  - Macro-style function definitions (CLAY, CLAY_LAYOUT, etc.)
  - Function call edges (including method calls via obj.method() and ptr->method())
  - C preprocessor #define macros that look like function definitions
"""

import re
from typing import Dict, List, Any


# Keywords that should NOT be treated as function names
_SKIP_NAMES = frozenset({
    # C keywords
    'if', 'else', 'for', 'while', 'do', 'switch', 'case', 'default',
    'return', 'break', 'continue', 'goto', 'sizeof', 'typeof',
    'struct', 'enum', 'union', 'typedef', 'extern', 'static',
    'const', 'volatile', 'inline', 'register', 'auto', 'signed',
    'unsigned', 'void', 'char', 'short', 'int', 'long', 'float',
    'double', 'bool', 'NULL',
    # C++ keywords
    'class', 'namespace', 'template', 'typename', 'virtual',
    'override', 'final', 'public', 'private', 'protected',
    'new', 'delete', 'try', 'catch', 'throw', 'noexcept',
    'constexpr', 'decltype', 'static_assert', 'alignas', 'alignof',
    'true', 'false', 'nullptr',
    # Common standard library / macros
    'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf',
    'malloc', 'calloc', 'realloc', 'free',
    'memcpy', 'memset', 'memmove', 'memcmp',
    'assert', 'sizeof',
    # Control-flow helpers
    'main',
})


def parse_cpp_fallback(content: str, file_path: str) -> Dict[str, Any]:
    """Regex-based C/C++ parser fallback.

    Handles:
      - Free functions: ``void foo()`` / ``static int bar(int x)``
      - Methods: ``void ClassName::method()``
      - Struct/Class declarations: ``struct Foo {`` / ``class Bar {``
      - C preprocessor function-like macros: ``#define CLAY(x) ...``
      - Function calls and method invocations

    Returns:
        ``{"nodes": [...], "edges": [...]}``
    """
    # Strip comments first to avoid false matches inside comments
    stripped = _strip_comments(content)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    fn_map: Dict[str, str] = {}  # fn_name → node_id

    # ── Phase 1: Extract struct / class declarations ──────────
    current_class: str = ""
    brace_depth = 0
    class_stack: List[str] = []

    # ── Phase 2: Extract function definitions ─────────────────
    lines = stripped.split('\n')

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # --- Track struct/class/namespace scope via braces ---
        # We track opening braces that belong to struct/class blocks
        struct_match = re.search(
            r'\b(?:struct|class)\s+([A-Za-z_]\w*)', line
        )
        if struct_match:
            current_class = struct_match.group(1)
            if '{' in line:
                class_stack.append(current_class)

        # Track brace depth for scope management
        open_braces = line.count('{')
        close_braces = line.count('}')
        brace_depth += open_braces - close_braces
        if brace_depth <= 0:
            brace_depth = 0
            if class_stack:
                class_stack.pop()
                current_class = class_stack[-1] if class_stack else ""

        # --- Extract function definitions ---
        # Pattern: [modifiers] return_type name(... [maybe { on same line])
        # Handles:
        #   void foo() { ... }
        #   static int bar(int x) {
        #   ClassName::method() const {
        #   inline void baz() noexcept {
        #   CLAY_RECTANGLE(id) { ... }   <- macro-style
        fn_match = re.search(
            r'(?:(?:static|inline|extern|constexpr|virtual|override|final|const|unsigned|signed|void|int|long|short|char|float|double|bool|auto|struct\s+\w+|enum\s+\w+|[A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)*(?:\s*[*&])?)\s+)+'
            r'([A-Za-z_]\w*(?:\s*::\s*[A-Za-z_]\w*)?)\s*\(',
            line
        )

        if fn_match:
            name = fn_match.group(1).strip()
            # Remove class prefix if present (e.g., "ClassName::method")
            short_name = name.split('::')[-1] if '::' in name else name
            if short_name not in _SKIP_NAMES and not short_name.startswith('_'):
                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "fn": short_name,
                    "file": file_path,
                    "line": line_num,
                }
                # Add class info if this is a method
                if '::' in name:
                    node_data["method_of"] = name.split('::')[0]
                elif current_class:
                    node_data["method_of"] = current_class
                nodes.append(node_data)
                fn_map[short_name] = node_id

        # --- Extract preprocessor function-like macros ---
        # #define MACRONAME(args) body
        macro_match = re.search(
            r'#define\s+([A-Z][A-Z0-9_]*)\s*\(', line
        )
        if macro_match:
            macro_name = macro_match.group(1)
            if macro_name not in _SKIP_NAMES:
                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "fn": macro_name,
                    "file": file_path,
                    "line": line_num,
                    "is_macro": True,
                }
                nodes.append(node_data)
                fn_map[macro_name] = node_id

        # --- Extract typedef / using aliases ---
        typedef_match = re.search(
            r'\btypedef\s+.*?\s+([A-Za-z_]\w*)\s*;', line
        )
        if not typedef_match:
            typedef_match = re.search(
                r'\busing\s+([A-Za-z_]\w*)\s*=', line
            )
        if typedef_match:
            type_name = typedef_match.group(1)
            if type_name not in _SKIP_NAMES:
                node_id = f"{file_path}:{line_num}"
                nodes.append({
                    "id": node_id,
                    "fn": type_name,
                    "file": file_path,
                    "line": line_num,
                    "is_typedef": True,
                })

    # ── Phase 3: Detect function call edges ───────────────────
    # For each function node, scan its body (approximate: next ~50 lines)
    # for calls to other known functions.
    for node in nodes:
        if node.get("is_typedef"):
            continue

        start_line = node["line"] - 1
        end_line = min(start_line + 60, len(lines))

        # Simple brace-depth tracking to avoid scanning past the end of the
        # function body.  We start at the depth where the function signature
        # was found and stop when we return to that depth after seeing at
        # least one closing brace.
        body_depth = 0
        found_open = False

        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            scan_line = lines[i]

            # Track braces to bound the function body
            body_depth += scan_line.count('{') - scan_line.count('}')
            if scan_line.count('{'):
                found_open = True
            if found_open and body_depth <= 0:
                break  # End of function body

            # Direct calls: identifier(
            for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', scan_line):
                call_name = m.group(1)
                if (call_name not in _SKIP_NAMES
                        and call_name != node["fn"]
                        and not call_name.startswith('_')):
                    edges.append({
                        "from": node["id"],
                        "to_fn": call_name,
                    })

            # Method calls: obj.method( or ptr->method(
            for m in re.finditer(r'(?:\.|->)\s*([A-Za-z_]\w*)\s*\(', scan_line):
                method_name = m.group(1)
                if method_name not in _SKIP_NAMES:
                    edges.append({
                        "from": node["id"],
                        "to_fn": method_name,
                    })

    return {"nodes": nodes, "edges": edges}


def _strip_comments(content: str) -> str:
    """Remove C/C++ comments (both // and /* */) from source code."""
    # Remove single-line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content
