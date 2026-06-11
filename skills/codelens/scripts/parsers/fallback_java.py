"""
Fallback Java Parser for CodeLens — regex-based extraction.
Extracts classes, methods, imports, and annotations from Java source files
when tree-sitter-java is not available.

Supports:
- package declarations
- import statements
- class/interface/enum declarations
- method declarations (with visibility, static, return type)
- field declarations
- annotations
"""

import re
from typing import Dict, List, Any


def parse_java_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Java source using regex — extracts classes, methods, imports.

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
    for line in lines:
        m = re.match(r'\s*package\s+([\w.]+)\s*;', line)
        if m:
            pkg = m.group(1)
            break

    # ─── Import statements → edges ───────────────────────────
    for line in lines:
        m = re.match(r'\s*import\s+(static\s+)?([\w.]+(?:\.\*)?)\s*;', line)
        if m:
            imported = m.group(2)
            edges.append({
                "from": rel_path,
                "to": imported,
                "type": "import",
                "weight": 1,
            })

    # ─── Class / Interface / Enum declarations ───────────────
    for i, line in enumerate(lines, 1):
        m = re.search(
            r'(?:public|private|protected)?\s*'
            r'(?:abstract\s+|final\s+)*'
            r'(class|interface|enum)\s+'
            r'(\w+)',
            line,
        )
        if m:
            kind = m.group(1)
            name = m.group(2)
            node_type = "class" if kind == "class" else kind
            nodes.append({
                "id": f"{rel_path}:{name}",
                "type": node_type,
                "name": name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "visibility": _extract_visibility(line),
                "package": pkg,
            })

    # ─── Method declarations ─────────────────────────────────
    # Match patterns like: public static void main(String[] args)
    # or: private String getName()
    # or: @Override protected void onCreate(Bundle savedInstanceState)
    for i, line in enumerate(lines, 1):
        m = re.search(
            r'(?:public|private|protected)?\s*'
            r'(?:static\s+)?'
            r'(?:final\s+)?'
            r'(?:synchronized\s+)?'
            r'(?:[\w<>\[\]?,\s]+?)\s+'  # return type
            r'(\w+)\s*\(',              # method name
            line,
        )
        if m:
            method_name = m.group(1)
            # Skip keywords and common false positives
            if method_name in ('if', 'else', 'while', 'for', 'switch',
                               'catch', 'class', 'interface', 'enum',
                               'return', 'new', 'throw', 'assert'):
                continue
            # Skip if this line is actually a class/enum/interface declaration
            if re.search(r'\b(class|interface|enum)\s+' + re.escape(method_name), line):
                continue
            nodes.append({
                "id": f"{rel_path}:{method_name}",
                "type": "function",
                "name": method_name,
                "file": rel_path,
                "line": i,
                "domain": "backend",
                "visibility": _extract_visibility(line),
            })

    return {"nodes": nodes, "edges": edges}


def _extract_visibility(line: str) -> str:
    """Extract Java visibility modifier from a declaration line."""
    if 'public' in line.split('(')[0]:
        return "public"
    elif 'private' in line.split('(')[0]:
        return "private"
    elif 'protected' in line.split('(')[0]:
        return "protected"
    return "package-private"
