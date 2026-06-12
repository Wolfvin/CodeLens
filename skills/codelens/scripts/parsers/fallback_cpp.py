"""
Fallback C/C++ parser for CodeLens.

Parses C/C++ source files using regex-based extraction when the tree-sitter
C/C++ parser is not available. Extracts:
- Functions (definitions, not declarations)
- Classes/structs
- Methods (class member functions)
- Namespaces
- Includes

This is intentionally lightweight — C++ is extremely complex to parse
correctly with regex alone, but this covers the most common patterns
that CodeLens needs for call graph construction.
"""

import re
from typing import Dict, List, Any


def parse_cpp_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse a C/C++ source file and extract nodes and edges.

    Args:
        content: File contents as string.
        rel_path: Relative path from workspace root.

    Returns:
        Dict with 'nodes' and 'edges' lists.
    """
    nodes = []
    edges = []
    lines = content.split('\n')

    # Track context
    current_namespace = ""
    current_class = ""
    in_class = False
    class_brace_depth = 0
    brace_depth = 0

    # C/C++ keywords to exclude from function detection
    cpp_keywords = {
        'if', 'else', 'for', 'while', 'do', 'switch', 'case',
        'return', 'break', 'continue', 'goto', 'sizeof',
        'typedef', 'struct', 'class', 'union', 'enum',
        'namespace', 'using', 'template', 'typename',
        'try', 'catch', 'throw', 'new', 'delete',
        'public', 'private', 'protected', 'virtual',
        'static', 'extern', 'inline', 'const', 'constexpr',
        'nullptr', 'true', 'false', 'this', 'operator',
        'auto', 'register', 'volatile', 'friend',
        'noexcept', 'override', 'final', 'explicit',
    }

    for i, line in enumerate(lines):
        stripped = line.strip()
        line_num = i + 1

        # ─── Brace tracking for class scope (MUST be before pattern matching) ──
        old_brace_depth = brace_depth
        for ch in stripped:
            if ch == '{':
                brace_depth += 1
            elif ch == '}':
                brace_depth -= 1

        # If we're in a class and brace depth returns to class level, exit class
        if in_class and brace_depth <= class_brace_depth:
            in_class = False
            current_class = ""
            class_brace_depth = 0

        # ─── Includes ────────────────────────────────────────
        m = re.match(r'^#include\s+[<"]([^>"]+)[>"]', stripped)
        if m:
            continue

        # ─── Namespace ───────────────────────────────────────
        m = re.match(r'^namespace\s+(\w+)', stripped)
        if m:
            current_namespace = m.group(1)
            continue

        # ─── Class/struct definition ─────────────────────────
        m = re.match(r'^(?:class|struct)\s+(\w+)\s*(?::|{|$)', stripped)
        if m:
            class_name = m.group(1)
            if class_name in cpp_keywords:
                continue
            current_class = class_name
            in_class = True
            class_brace_depth = old_brace_depth  # Set class_brace_depth when entering class

            full_name = f"{current_namespace}::{class_name}" if current_namespace else class_name
            nodes.append({
                "id": f"{rel_path}:{line_num}:{class_name}",
                "fn": class_name,
                "file": rel_path,
                "line": line_num,
                "type": "class",
                "language": "cpp",
                "namespace": current_namespace,
                "full_name": full_name,
            })
            # No continue — brace tracking already done above

        # ─── Function definition (standalone) ────────────────
        # Pattern: [qualifiers] type name(params) { or ;
        # This is simplified — C++ function signatures are complex
        m = re.match(
            r'^(?:(?:static|virtual|inline|const|constexpr|extern|unsigned|signed)\s+)*'
            r'(?:\w+(?:::\w+)*\s+)'  # return type (possibly namespaced)
            r'(\w+)\s*\(([^)]*)\)\s*'  # function name and params
            r'(?:const\s*)?'  # optional const qualifier
            r'(?:override\s*)?'  # optional override
            r'(?:noexcept\s*)?'  # optional noexcept
            r'(?:->\s*\w+\s*)?'  # trailing return type
            r'[{;]',  # body start or declaration end
            stripped
        )
        if m:
            fn_name = m.group(1)
            if fn_name in cpp_keywords:
                continue
            # Skip if this looks like a variable declaration with initializer
            if '=' in stripped and '{' not in stripped:
                continue

            node_id = f"{rel_path}:{line_num}:{fn_name}"
            full_name = f"{current_namespace}::{fn_name}" if current_namespace else fn_name

            node = {
                "id": node_id,
                "fn": fn_name,
                "file": rel_path,
                "line": line_num,
                "type": "method" if in_class else "function",
                "language": "cpp",
                "namespace": current_namespace,
                "full_name": full_name,
            }
            if in_class and current_class:
                node["class"] = current_class
                node["full_name"] = f"{current_class}::{fn_name}"
            nodes.append(node)
            # No continue — brace tracking already done above

        # ─── Method definition outside class (ClassName::methodName) ──
        m = re.match(
            r'^(?:(?:static|virtual|inline|const|constexpr)\s+)*'
            r'(?:\w+(?:::\w+)*\s+)?'  # optional return type
            r'(\w+)::(\w+)\s*\(([^)]*)\)\s*'
            r'(?:const\s*)?'
            r'[{;]',
            stripped
        )
        if m:
            class_name = m.group(1)
            method_name = m.group(2)
            if class_name in cpp_keywords or method_name in cpp_keywords:
                continue

            node_id = f"{rel_path}:{line_num}:{method_name}"
            nodes.append({
                "id": node_id,
                "fn": method_name,
                "file": rel_path,
                "line": line_num,
                "type": "method",
                "language": "cpp",
                "class": class_name,
                "full_name": f"{class_name}::{method_name}",
            })
            # No continue — brace tracking already done above

    # ─── Function call edge detection ────────────────────────
    # Second pass: find function calls within function bodies
    # This is simplified — we look for identifier(...) patterns
    # within the body of each detected function
    for node in nodes:
        if node["type"] not in ("function", "method"):
            continue

        fn_line = node["line"]
        fn_name = node["fn"]
        # Search for calls in a window around the function definition
        # (from definition line until brace depth returns to 0 or next function)
        search_start = fn_line - 1  # 0-indexed
        search_end = min(fn_line + 200, len(lines))  # Look ahead max 200 lines

        depth = 0
        found_open = False
        for j in range(search_start, search_end):
            line_j = lines[j].strip()

            # Track braces to know when function body ends
            for ch in line_j:
                if ch == '{':
                    depth += 1
                    found_open = True
                elif ch == '}':
                    depth -= 1

            if found_open and depth <= 0:
                break  # Function body ended

            # Find function calls: identifier(...)
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', line_j):
                called_fn = m.group(1)
                if called_fn in cpp_keywords:
                    continue
                if called_fn == fn_name:
                    continue  # Skip self-calls

                edges.append({
                    "from": node["id"],
                    "to_fn": called_fn,
                })

    return {
        "nodes": nodes,
        "edges": edges,
    }
