"""
Fallback C# Parser for CodeLens — regex-based extraction.
Extracts classes, interfaces, structs, enums, methods, and using statements.
"""

import re
from typing import Dict, List, Any


def parse_csharp_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse C# source using regex — extracts classes, methods, usings."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Using statements
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*using\s+([\w.]+)\s*;', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "using", "weight": 1})

    # Namespace
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*namespace\s+([\w.]+)', line)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(1)}", "type": "namespace",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})

    # class/interface/struct/enum
    for i, line in enumerate(lines, 1):
        m = re.search(r'(?:public|private|protected|internal)?\s*(?:static\s+|sealed\s+|abstract\s+)*'
                       r'(class|interface|struct|enum)\s+(\w+)', line)
        if m:
            nodes.append({"id": f"{rel_path}:{m.group(2)}", "type": m.group(1),
                          "name": m.group(2), "fn": m.group(2),
                          "file": rel_path, "line": i, "domain": "backend"})

    # Methods
    for i, line in enumerate(lines, 1):
        m = re.search(r'(?:public|private|protected|internal)?\s*(?:static\s+|async\s+|override\s+|virtual\s+)*'
                       r'(?:[\w<>\[\]?,\s]+)\s+(\w+)\s*\([^)]*\)', line)
        if m:
            name = m.group(1)
            if name in ('if', 'else', 'while', 'for', 'switch', 'catch', 'class',
                         'interface', 'struct', 'enum', 'return', 'new', 'throw',
                         'using', 'namespace', 'get', 'set'):
                continue
            if re.search(r'\b(class|interface|struct|enum)\s+' + re.escape(name), line):
                continue
            nodes.append({"id": f"{rel_path}:{name}", "type": "function",
                          "name": name, "fn": name,
                          "file": rel_path, "line": i, "domain": "backend"})

    return {"nodes": nodes, "edges": edges}
