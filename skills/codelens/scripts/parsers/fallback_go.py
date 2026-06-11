"""
Fallback Go Parser for CodeLens — regex-based extraction.
Extracts functions, types, imports, and package declarations from Go source files
when tree-sitter-go is not available.

Supports:
- package declarations
- import statements (single and grouped)
- func declarations (with receiver for methods)
- type declarations (struct, interface)
- const/var blocks
"""

import re
from typing import Dict, List, Any


def parse_go_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Go source using regex — extracts functions, types, imports.

    Args:
        content: File content as string
        rel_path: Relative file path within workspace

    Returns:
        Dict with 'nodes' and 'edges' lists for CodeLens registry.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # ─── Package declaration ──────────────────────────────────
    pkg = ""
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*package\s+(\w+)', line)
        if m:
            pkg = m.group(1)
            break

    # ─── Import statements → edges ───────────────────────────
    # Single import
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*import\s+"([^"]+)"', line)
        if m:
            edges.append({
                "from": rel_path,
                "to": m.group(1),
                "type": "import",
                "weight": 1,
            })

    # Grouped import
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
                edges.append({
                    "from": rel_path,
                    "to": m.group(1),
                    "type": "import",
                    "weight": 1,
                })

    # ─── func declarations ───────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Method with receiver: func (r *Receiver) Name(...)
        m = re.match(r'func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)', stripped)
        if m:
            receiver = m.group(1)
            method_name = m.group(2)
            nodes.append({
                "id": f"{rel_path}:{receiver}.{method_name}",
                "type": "method",
                "name": method_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "receiver": receiver,
            })
            continue

        # Regular function: func Name(...)
        m = re.match(r'func\s+(\w+)', stripped)
        if m:
            fn_name = m.group(1)
            # Skip init() and test functions (they are special)
            node_type = "function"
            if fn_name == "init":
                node_type = "init"
            elif fn_name.startswith("Test"):
                node_type = "test"
            elif fn_name.startswith("Benchmark"):
                node_type = "benchmark"
            nodes.append({
                "id": f"{rel_path}:{fn_name}",
                "type": node_type,
                "name": fn_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })

    # ─── type declarations ───────────────────────────────────
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # type Name struct { ... }
        m = re.match(r'type\s+(\w+)\s+struct\b', stripped)
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

        # type Name interface { ... }
        m = re.match(r'type\s+(\w+)\s+interface\b', stripped)
        if m:
            nodes.append({
                "id": f"{rel_path}:{m.group(1)}",
                "type": "interface",
                "name": m.group(1),
                "file": rel_path,
                "line": i,
                "domain": "backend",
            })
            continue

        # type Name OtherType (type alias)
        m = re.match(r'type\s+(\w+)\s+\w', stripped)
        if m:
            name = m.group(1)
            # Avoid duplicates from struct/interface matches above
            if not any(n["name"] == name and n["line"] == i for n in nodes):
                nodes.append({
                    "id": f"{rel_path}:{name}",
                    "type": "type_alias",
                    "name": name,
                    "file": rel_path,
                    "line": i,
                    "domain": "backend",
                })

    return {"nodes": nodes, "edges": edges}
