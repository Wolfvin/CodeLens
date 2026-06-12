"""
Fallback C/C++ Parser for CodeLens — regex-based extraction.
Extracts functions, structs, classes, includes, macros, and typedefs.
"""

import re
from typing import Dict, List, Any


def parse_c_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse C/C++ source using regex — extracts functions, structs, includes."""
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
            if name.startswith('_') and name.endswith('_H'):
                continue
            nodes.append({
                "id": f"{rel_path}:{name}", "type": "macro", "name": name, "fn": name,
                "file": rel_path, "line": i, "domain": "backend",
            })

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
            nodes.append({
                "id": f"{rel_path}:{fn_name}", "type": "function", "name": fn_name, "fn": fn_name,
                "file": rel_path, "line": i, "domain": "backend",
            })

    # struct/enum/class
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = re.search(r'\bstruct\s+(\w+)\s*\{', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "struct",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.search(r'\benum\s+(?:class\s+)?(\w+)\s*\{', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "enum",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # C++ class
        m = re.search(r'\bclass\s+(\w+)\s*(?::|\{)', stripped)
        if m:
            name = m.group(1)
            if name not in ('public', 'private', 'protected'):
                nodes.append({"id": f"{rel_path}:{name}", "type": "class",
                              "name": name, "fn": name,
                              "file": rel_path, "line": i, "domain": "backend"})

    # Namespaces
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*namespace\s+(\w+)', line)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "namespace",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})

    return {"nodes": nodes, "edges": edges}
