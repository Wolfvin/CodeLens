"""
Fallback Java/Kotlin Parser for CodeLens — regex-based extraction.
Extracts classes, methods, imports, and annotations from Java/Kotlin source files
when tree-sitter-java is not available.
"""

import re
from typing import Dict, List, Any


def parse_java_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Java source using regex — extracts classes, methods, imports."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Package
    pkg = ""
    for line in lines:
        m = re.match(r'\s*package\s+([\w.]+)\s*;', line)
        if m:
            pkg = m.group(1)
            break

    # Imports
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*import\s+(static\s+)?([\w.]+(?:\.\*)?)\s*;', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(2), "type": "import", "weight": 1})

    # Class/interface/enum
    for i, line in enumerate(lines, 1):
        m = re.search(r'(?:public|private|protected)?\s*(?:abstract\s+|final\s+|data\s+)*'
                       r'(class|interface|enum|object)\s+(\w+)', line)
        if m:
            nodes.append({
                "id": f"{rel_path}:{m.group(2)}", "type": m.group(1),
                "name": m.group(2), "fn": m.group(2),
                "file": rel_path, "line": i, "domain": "backend",
                "visibility": _extract_visibility(line), "package": pkg,
            })

    # Methods
    for i, line in enumerate(lines, 1):
        m = re.search(r'(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?'
                       r'(?:synchronized\s+)?(?:suspend\s+)?'
                       r'(?:[\w<>\[\]?,\s]+?)\s+(\w+)\s*\(', line)
        if m:
            name = m.group(1)
            if name in ('if', 'else', 'while', 'for', 'switch', 'catch', 'class',
                         'interface', 'enum', 'return', 'new', 'throw', 'assert',
                         'fun', 'val', 'var'):
                continue
            if re.search(r'\b(class|interface|enum|object)\s+' + re.escape(name), line):
                continue
            nodes.append({
                "id": f"{rel_path}:{name}", "type": "function", "name": name, "fn": name,
                "file": rel_path, "line": i, "domain": "backend",
                "visibility": _extract_visibility(line),
            })

    return {"nodes": nodes, "edges": edges}


def _extract_visibility(line: str) -> str:
    prefix = line.split('(')[0] if '(' in line else line
    if 'public' in prefix:
        return "public"
    if 'private' in prefix:
        return "private"
    if 'protected' in prefix:
        return "protected"
    return "package-private"
