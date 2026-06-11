"""
Fallback C/C++ Parser for CodeLens — regex-based extraction.
Extracts functions, structs, classes, includes, and macros from C/C++ source files
when tree-sitter-c / tree-sitter-cpp is not available.

Supports:
- #include directives (both <system> and "local" headers)
- function definitions and declarations
- struct/enum/class declarations (C++)
- #define macros
- typedef aliases
"""

import re
from typing import Dict, List, Any


def parse_c_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse C/C++ source using regex — extracts functions, structs, includes.

    Args:
        content: File content as string
        rel_path: Relative file path within workspace

    Returns:
        Dict with 'nodes' and 'edges' lists for CodeLens registry.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # ─── #include directives → edges ─────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*#\s*include\s+([<"])([^>"]+)[>"]', line)
        if m:
            bracket = m.group(1)
            included = m.group(2)
            edges.append({
                "from": rel_path,
                "to": included,
                "type": "include",
                "weight": 1,
                "system": bracket == '<',
            })

    # ─── #define macros → nodes ──────────────────────────────
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*#\s*define\s+(\w+)', line)
        if m:
            macro_name = m.group(1)
            # Skip include guards and common non-functional macros
            if macro_name.startswith('_') and macro_name.endswith('_H'):
                continue
            nodes.append({
                "id": f"{rel_path}:{macro_name}",
                "type": "macro",
                "name": macro_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })

    # ─── Function definitions ────────────────────────────────
    # Match: type name(params) {  or  type name(params);
    # Also handles: static inline type name(params)
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Skip comments, preprocessor, empty lines
        if not stripped or stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('#'):
            continue
        # Match function definition/declaration
        m = re.search(
            r'(?:static\s+|inline\s+|extern\s+)*'  # optional qualifiers
            r'(?:const\s+)?'
            r'(?:[\w:*&<>\[\]]+\s+)+'              # return type (possibly templated)
            r'(\w+)\s*'                             # function name
            r'\([^)]*\)'                            # params
            r'\s*(?:\{|;)',                          # body start or declaration end
            stripped,
        )
        if m:
            fn_name = m.group(1)
            # Skip common false positives
            if fn_name in ('if', 'else', 'while', 'for', 'switch', 'return',
                           'sizeof', 'typedef', 'struct', 'enum', 'class',
                           'case', 'break', 'continue'):
                continue
            nodes.append({
                "id": f"{rel_path}:{fn_name}",
                "type": "function",
                "name": fn_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })

    # ─── struct / enum / typedef declarations ────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # struct
        m = re.search(r'\bstruct\s+(\w+)\s*\{', stripped)
        if m:
            nodes.append({
                "id": f"{rel_path}:{m.group(1)}",
                "type": "struct",
                "name": m.group(1),
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            continue

        # enum
        m = re.search(r'\benum\s+(?:class\s+)?(\w+)\s*\{', stripped)
        if m:
            nodes.append({
                "id": f"{rel_path}:{m.group(1)}",
                "type": "enum",
                "name": m.group(1),
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            continue

        # typedef
        m = re.search(r'\btypedef\s+.*\s+(\w+)\s*;', stripped)
        if m:
            alias = m.group(1)
            nodes.append({
                "id": f"{rel_path}:{alias}",
                "type": "typedef",
                "name": alias,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })

    return {"nodes": nodes, "edges": edges}
