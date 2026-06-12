"""
Fallback Lua Parser for CodeLens — regex-based extraction.
Extracts functions, tables, requires, and module declarations.
"""

import re
from typing import Dict, List, Any


def parse_lua_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Lua source using regex — extracts functions, tables, requires."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Requires
    for i, line in enumerate(lines, 1):
        # local mod = require("mod") or require("mod")
        m = re.search(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "require", "weight": 1})

    # Functions (named)
    for i, line in enumerate(lines, 1):
        # function foo()
        m = re.match(r'\s*function\s+(\w+(?:[:\.]\w+)*)', line)
        if m:
            name = m.group(1)
            ftype = "method" if (':' in name or '.' in name) else "function"
            nodes.append({"id": f"{rel_path}:{name}", "type": ftype,
                          "name": name, "fn": name.split('.')[-1].split(':')[-1],
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        # local function foo()
        m = re.match(r'\s*local\s+function\s+(\w+)', line)
        if m:
            name = m.group(1)
            nodes.append({"id": f"{rel_path}:{name}", "type": "function",
                          "name": name, "fn": name,
                          "file": rel_path, "line": i, "domain": "backend"})

    # Table declarations (M.key = value or key = {})
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*(\w+)\s*=\s*\{', line)
        if m:
            name = m.group(1)
            # Skip common Lua keywords
            if name in ('local', 'function', 'if', 'for', 'while', 'return', 'do', 'then'):
                continue
            nodes.append({"id": f"{rel_path}:{name}", "type": "table",
                          "name": name, "fn": name,
                          "file": rel_path, "line": i, "domain": "backend"})

    return {"nodes": nodes, "edges": edges}
