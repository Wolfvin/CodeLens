"""Fallback Go parser (when tree-sitter grammars unavailable).

Extracts:
  - Functions (func name())
  - Methods (func (receiver) name())
  - Type declarations (type Name struct/interface)
  - Function call edges
  - Package-level var/const declarations
"""

import re
from typing import Dict, List, Any


_SKIP_NAMES = frozenset({
    # Go keywords
    'if', 'else', 'for', 'range', 'switch', 'case', 'default',
    'return', 'break', 'continue', 'goto', 'defer', 'go', 'select',
    'func', 'struct', 'interface', 'map', 'chan', 'package', 'import',
    'type', 'var', 'const',
    # Builtin types and functions
    'true', 'false', 'nil', 'make', 'new', 'len', 'cap', 'append',
    'copy', 'delete', 'close', 'panic', 'recover', 'print', 'println',
    'error', 'string', 'int', 'int8', 'int16', 'int32', 'int64',
    'uint', 'uint8', 'uint16', 'uint32', 'uint64',
    'float32', 'float64', 'complex64', 'complex128',
    'bool', 'byte', 'rune', 'uintptr',
})


def parse_go_fallback(content: str, file_path: str) -> Dict[str, Any]:
    """Regex-based Go parser fallback.

    Handles:
      - Functions: ``func foo()`` / ``func foo(a int, b string) error``
      - Methods: ``func (s *Struct) method()``
      - Type declarations: ``type Foo struct`` / ``type Bar interface``
      - Function calls
      - Method calls: ``obj.method()``

    Returns:
        ``{"nodes": [...], "edges": [...]}``
    """
    # Strip comments
    stripped = _strip_comments(content)

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    fn_map: Dict[str, str] = {}  # fn_name → node_id

    lines = stripped.split('\n')

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()

        # --- Extract func declarations ---
        # Method: func (receiver) methodName(...)
        method_match = re.search(
            r'\bfunc\s+\([^)]+\)\s+([A-Za-z_]\w*)\s*[\(]',
            line
        )
        if method_match:
            name = method_match.group(1)
            if name not in _SKIP_NAMES:
                # Extract receiver type
                recv_match = re.search(
                    r'\bfunc\s+\(\s*\w+\s+(?:\*)?(\w+)\)', line
                )
                receiver_type = recv_match.group(1) if recv_match else ""

                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "fn": name,
                    "file": file_path,
                    "line": line_num,
                }
                if receiver_type:
                    node_data["method_of"] = receiver_type
                nodes.append(node_data)
                fn_map[name] = node_id
                continue  # Don't also match as free function

        # Free function: func name(...)
        fn_match = re.search(
            r'\bfunc\s+([A-Za-z_]\w*)\s*[\(]',
            line
        )
        if fn_match:
            name = fn_match.group(1)
            if name not in _SKIP_NAMES:
                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "fn": name,
                    "file": file_path,
                    "line": line_num,
                }
                nodes.append(node_data)
                fn_map[name] = node_id
                continue

        # --- Type declarations ---
        type_match = re.search(
            r'\btype\s+([A-Za-z_]\w*)\s+(struct|interface)',
            line
        )
        if type_match:
            type_name = type_match.group(1)
            if type_name not in _SKIP_NAMES:
                node_id = f"{file_path}:{line_num}"
                nodes.append({
                    "id": node_id,
                    "fn": type_name,
                    "file": file_path,
                    "line": line_num,
                    "is_type": True,
                    "type_kind": type_match.group(2),
                })

    # ── Phase 2: Detect function call edges ───────────────────
    for node in nodes:
        if node.get("is_type"):
            continue

        start_line = node["line"] - 1
        end_line = min(start_line + 60, len(lines))

        # Track braces to bound the function body
        body_depth = 0
        found_open = False

        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            scan_line = lines[i]

            body_depth += scan_line.count('{') - scan_line.count('}')
            if scan_line.count('{'):
                found_open = True
            if found_open and body_depth <= 0:
                break

            # Direct calls: identifier(
            for m in re.finditer(r'\b([A-Za-z_]\w*)\s*\(', scan_line):
                call_name = m.group(1)
                if (call_name not in _SKIP_NAMES
                        and call_name != node["fn"]):
                    edges.append({
                        "from": node["id"],
                        "to_fn": call_name,
                    })

            # Method calls: obj.method(
            for m in re.finditer(r'\.\s*([A-Za-z_]\w*)\s*\(', scan_line):
                method_name = m.group(1)
                if method_name not in _SKIP_NAMES:
                    edges.append({
                        "from": node["id"],
                        "to_fn": method_name,
                    })

    return {"nodes": nodes, "edges": edges}


def _strip_comments(content: str) -> str:
    """Remove Go comments (both // and /* */) from source code."""
    # Remove single-line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Remove multi-line comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    return content
