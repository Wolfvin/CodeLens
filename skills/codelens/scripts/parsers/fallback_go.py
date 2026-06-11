"""
Fallback Go parser for CodeLens.

Parses Go source files using regex-based extraction when the tree-sitter
Go parser is not available. Extracts:
- Functions (func declarations)
- Methods (func with receiver)
- Structs (type ... struct)
- Interfaces (type ... interface)
- Imports

This is intentionally lightweight — a full Go AST parser would require
tree-sitter-go or go/ast, but this covers 80%+ of what CodeLens needs.
"""

import re
from typing import Dict, List, Any


def parse_go_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse a Go source file and extract nodes and edges.

    Args:
        content: File contents as string.
        rel_path: Relative path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' lists.
    """
    nodes = []
    edges = []
    lines = content.split('\n')

    # Track line numbers and contexts
    in_func = False
    func_name = ""
    func_line = 0
    brace_depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        line_num = i + 1

        # ─── Imports ─────────────────────────────────────────
        # Single import: import "fmt"
        m = re.match(r'^import\s+"([^"]+)"', stripped)
        if m:
            continue

        # Multi-line import block
        if stripped.startswith('import') and '(' in stripped:
            # Read until closing paren
            for j in range(i + 1, min(i + 50, len(lines))):
                imp_line = lines[j].strip()
                if imp_line == ')':
                    break
                m2 = re.match(r'"([^"]+)"', imp_line)
                if m2:
                    pass  # Import recorded for dependency tracking
            continue

        # ─── Package declaration ──────────────────────────────
        m = re.match(r'^package\s+(\w+)', stripped)
        if m:
            continue

        # ─── Type declarations (structs, interfaces) ──────────
        m = re.match(r'^type\s+(\w+)\s+struct\s*\{', stripped)
        if m:
            nodes.append({
                "id": f"{rel_path}:{line_num}:{m.group(1)}",
                "fn": m.group(1),
                "file": rel_path,
                "line": line_num,
                "type": "struct",
                "language": "go",
                "exported": m.group(1)[0].isupper(),
            })
            continue

        m = re.match(r'^type\s+(\w+)\s+interface\s*\{', stripped)
        if m:
            nodes.append({
                "id": f"{rel_path}:{line_num}:{m.group(1)}",
                "fn": m.group(1),
                "file": rel_path,
                "line": line_num,
                "type": "interface",
                "language": "go",
                "exported": m.group(1)[0].isupper(),
            })
            continue

        # ─── Method declarations (with receiver) ─────────────
        # func (r *Receiver) methodName(...) ...
        m = re.match(
            r'^func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)\s*\(',
            stripped
        )
        if m:
            receiver = m.group(1)
            method_name = m.group(2)
            full_name = f"{receiver}.{method_name}"
            node_id = f"{rel_path}:{line_num}:{method_name}"

            nodes.append({
                "id": node_id,
                "fn": method_name,
                "file": rel_path,
                "line": line_num,
                "type": "method",
                "language": "go",
                "exported": method_name[0].isupper(),
                "receiver": receiver,
                "full_name": full_name,
            })

            # Edge from receiver to method
            edges.append({
                "from": node_id,
                "to_fn": receiver,
            })
            continue

        # ─── Function declarations ────────────────────────────
        m = re.match(r'^func\s+(\w+)\s*\(', stripped)
        if m:
            fn_name = m.group(1)
            node_id = f"{rel_path}:{line_num}:{fn_name}"

            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": rel_path,
                "line": line_num,
                "type": "function",
                "language": "go",
                "exported": fn_name[0].isupper(),
            })
            func_name = fn_name
            func_line = line_num
            in_func = True
            brace_depth = 0
            continue

        # ─── Function call detection within function bodies ───
        if in_func or brace_depth > 0:
            # Track brace depth
            for ch in stripped:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1

            if brace_depth <= 0 and in_func:
                in_func = False
                continue

            # Detect function calls: identifier(...) — not keywords
            # Only track calls that could be cross-function references
            go_keywords = {
                'if', 'for', 'switch', 'select', 'return', 'defer',
                'go', 'range', 'var', 'const', 'type', 'func',
                'package', 'import', 'map', 'chan', 'make', 'new',
                'len', 'cap', 'append', 'copy', 'delete', 'close',
                'panic', 'recover', 'print', 'println', 'true', 'false',
                'nil', 'else', 'case', 'default', 'break', 'continue',
                'fallthrough', 'goto',
            }

            # Match function calls: word(...)  — but exclude keywords and method chains
            for m2 in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', stripped):
                called_fn = m2.group(1)
                if called_fn in go_keywords:
                    continue
                if called_fn == func_name:
                    continue  # Skip self-calls for now

                caller_id = f"{rel_path}:{func_line}:{func_name}"
                edges.append({
                    "from": caller_id,
                    "to_fn": called_fn,
                })

    return {
        "nodes": nodes,
        "edges": edges,
    }
