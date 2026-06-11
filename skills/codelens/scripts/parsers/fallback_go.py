"""
Fallback Go Parser for CodeLens — regex-based extraction.
Extracts functions, methods, types, imports, and package declarations.
"""

import re
from typing import Dict, List, Any


def parse_go_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Go source using regex — extracts functions, types, imports."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Package
    pkg = ""
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*package\s+(\w+)', line)
        if m:
            pkg = m.group(1)
            break

    # Imports (single + grouped)
    in_import_block = False
    for i, line in enumerate(lines, 1):
        if re.match(r'\s*import\s*\(', line):
            in_import_block = True
            continue
        if in_import_block:
            if ')' in line:
                in_import_block = False
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})
            continue
        m = re.match(r'\s*import\s+"([^"]+)"', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})

    # Functions
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Method with receiver
        m = re.match(r'func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}.{m.group(2)}", "type": "method",
                          "name": m.group(2), "fn": m.group(2),
                          "file": rel_path, "line": i, "domain": "backend", "receiver": m.group(1)})
            continue
        # Regular function
        m = re.match(r'func\s+(\w+)', stripped)
        if m:
            fn_name = m.group(1)
            ntype = "function"
            if fn_name == "init": ntype = "init"
            elif fn_name.startswith("Test"): ntype = "test"
            elif fn_name.startswith("Benchmark"): ntype = "benchmark"
            nodes.append({"id": f"{rel_path}:{fn_name}", "type": ntype,
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})

    # Types
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = re.match(r'type\s+(\w+)\s+struct\b', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "struct",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.match(r'type\s+(\w+)\s+interface\b', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "interface",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})

    return {"nodes": nodes, "edges": edges}
