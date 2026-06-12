"""
Fallback C/C++ Parser for CodeLens — regex-based extraction.
Extracts functions, structs, classes, includes, macros, typedefs,
and function call relationships for edge resolution.
"""

import re
from typing import Dict, List, Any


def parse_c_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse C/C++ source using regex — extracts functions, structs, includes, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Includes
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*#\s*include\s+([<"])([^>"]+)[>"]', line)
        if m:
            edges.append({
                "from": rel_path, "to": m.group(2), "type": "include",
                "weight": 1, "system": m.group(1) == '<',
            })

    # Macros
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*#\s*define\s+(\w+)', line)
        if m:
            name = m.group(1)
            # Skip include guard macros (e.g., _NGX_ATOMIC_H_INCLUDED_, _HEADER_H_)
            if (name.startswith('_') and name.endswith('_')) or \
               re.match(r'^_?[A-Z0-9_]+_H(_INCLUDED_)?$', name) or \
               name.endswith('_H') or name.endswith('_H_') or \
               name.endswith('_INCLUDED') or name.endswith('_INCLUDED_') or \
               name.endswith('_INCLUDED__'):
                continue
            nodes.append({
                "id": f"{rel_path}:{name}", "type": "macro", "name": name, "fn": name,
                "file": rel_path, "line": i, "domain": "backend",
            })

    # Collect function definitions for call resolution
    fn_defs: Dict[str, str] = {}  # fn_name → node_id

    # Functions
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('#'):
            continue
        # Skip lines inside block comments
        m = re.search(r'(?:static\s+|inline\s+|extern\s+)*'
                       r'(?:const\s+)?(?:[\w:*&<>\[\]]+\s+)+'
                       r'(\w+)\s*\([^)]*\)\s*(?:\{|;)', stripped)
        if m:
            fn_name = m.group(1)
            if fn_name in ('if', 'else', 'while', 'for', 'switch', 'return',
                            'sizeof', 'typedef', 'struct', 'enum', 'class',
                            'case', 'break', 'continue', 'namespace',
                            'ifdef', 'ifndef', 'endif', 'define', 'include',
                            'pragma', 'if', 'elif', 'else'):
                continue
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({
                "id": node_id, "type": "function", "name": fn_name, "fn": fn_name,
                "file": rel_path, "line": i, "domain": "backend",
            })
            fn_defs[fn_name] = node_id

    # struct/enum/class
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = re.search(r'\bstruct\s+(\w+)\s*\{', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:{m.group(1)}", "type": "struct",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.search(r'\benum\s+(?:class\s+)?(\w+)\s*\{', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:{m.group(1)}", "type": "enum",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # C++ class
        m = re.search(r'\bclass\s+(\w+)\s*(?::|\{)', stripped)
        if m:
            name = m.group(1)
            if name not in ('public', 'private', 'protected'):
                nodes.append({"id": f"{rel_path}:{i}:{name}", "type": "class",
                              "name": name, "fn": name,
                              "file": rel_path, "line": i, "domain": "backend"})

    # Namespaces
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*namespace\s+(\w+)', line)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:{m.group(1)}", "type": "namespace",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})

    # ─── Function call edges ─────────────────────────────────────
    # For C/C++, we track function bodies via brace counting and extract
    # calls within each function body. This helps resolve "dead code" issues
    # where functions appear unused because no call edges exist.
    #
    # Performance: Skip call edge extraction for very large files (>5000 lines)
    # to avoid slowdowns on massive C++ codebases (e.g., game engines).

    if len(lines) > 5000:
        return {"nodes": nodes, "edges": edges}

    _C_KEYWORDS = frozenset({
        'if', 'else', 'while', 'for', 'switch', 'case', 'return', 'break',
        'continue', 'goto', 'do', 'sizeof', 'typeof', 'alignof', 'offsetof',
        'typedef', 'struct', 'enum', 'class', 'union', 'namespace', 'using',
        'template', 'typename', 'static_cast', 'dynamic_cast', 'reinterpret_cast',
        'const_cast', 'new', 'delete', 'this', 'nullptr', 'NULL', 'true', 'false',
        'auto', 'void', 'int', 'char', 'float', 'double', 'long', 'short',
        'unsigned', 'signed', 'const', 'static', 'extern', 'inline', 'virtual',
        'override', 'final', 'public', 'private', 'protected', 'friend',
        'operator', 'throw', 'try', 'catch', 'noexcept', 'constexpr',
        'assert', 'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf',
        'malloc', 'calloc', 'realloc', 'free', 'memcpy', 'memset', 'memmove',
        'strlen', 'strcmp', 'strncmp', 'strcpy', 'strncpy', 'strcat', 'strncat',
    })

    # Build function → body range map
    fn_ranges = []  # [(node_id, start_line, end_line)]
    brace_count = 0
    current_fn = None
    fn_start = 0

    for i, line in enumerate(lines, 1):
        # Detect function start (already registered in nodes)
        stripped = line.strip()
        for node in nodes:
            if node.get("line") == i and node.get("type") == "function":
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn:
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0 and '{' in ''.join(lines[fn_start-1:i]):
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    # Handle last function
    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    # Match: functionName( and obj->method( and obj.method( and Namespace::function(
    call_pattern = re.compile(
        r'(?:(\w+)\s*(?:->|::|\.))?\s*(\w+)\s*\('
    )

    for fn_id, start_line, end_line in fn_ranges:
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            obj_or_ns = m.group(1) or ""
            fn_name = m.group(2)
            if fn_name in _C_KEYWORDS:
                continue
            if obj_or_ns in _C_KEYWORDS:
                continue
            # Skip standard library patterns
            if obj_or_ns in ('std', 'boost', 'fmt', 'spdlog', 'absl'):
                continue
            if fn_name in fn_defs:
                edges.append({
                    "from": fn_id,
                    "to": fn_defs[fn_name],
                    "to_fn": fn_name,
                    "type": "call",
                    "weight": 1,
                })
            else:
                # Unresolved call — still create edge for cross-file resolution
                edges.append({
                    "from": fn_id,
                    "to_fn": fn_name,
                    "type": "call",
                    "weight": 1,
                })

    return {"nodes": nodes, "edges": edges}
