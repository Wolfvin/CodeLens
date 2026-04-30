"""
JS Backend Parser for CodeLens
Extracts function declarations and function calls from JS non-frontend code.

Detected patterns:
- function processData(input) { ... }
- const processData = (input) => { ... }
- const processData = function(input) { ... }
- processData(myInput)
- utils.processData(myInput)

Rules:
- Method calls tracked with format object.method as one node
- Arrow function assigned to const → treated same as function declaration
- Callback inline (anonymous function) → IGNORED
- Same function name declared in multiple files → flag `duplicate_define`
"""

import re
from typing import Dict, List, Any


def strip_js_comments(content: str) -> str:
    """Remove JS single-line and multi-line comments."""
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    return content


def extract_js_backend_references(content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract function declarations and calls from backend JS content.

    Returns:
        {
            "nodes": [{"id": str, "fn": str, "file": str, "line": int, "async": bool}],
            "edges": [{"from": str, "to": str}]
        }
    """
    cleaned = strip_js_comments(content)
    lines = cleaned.split('\n')

    nodes = []
    edges = []

    # Track declared functions in this file
    declared_fns: Dict[str, str] = {}  # fn_name → node_id

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # --- Function Declarations ---
        # Pattern: function name(...) {
        match = re.search(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\(', stripped)
        if match:
            fn_name = match.group(1)
            node_id = f"{file_path}:{line_num}"
            is_async = 'async' in stripped[:stripped.index('function')]
            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line_num,
                "async": bool(is_async)
            })
            declared_fns[fn_name] = node_id
            continue

        # Pattern: const/let/var name = (...) => { or function(...)
        match = re.search(r'(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function\s*\()', stripped)
        if match:
            fn_name = match.group(1)
            node_id = f"{file_path}:{line_num}"
            is_async = 'async' in stripped[:stripped.index(fn_name)] if fn_name in stripped else False
            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line_num,
                "async": bool(is_async)
            })
            declared_fns[fn_name] = node_id
            continue

        # --- Function Calls ---
        # We only track calls from declared functions in this file
        # Pattern: functionName(args) — but not if it's a declaration
        # Skip if this line is a declaration
        if re.search(r'\bfunction\s+\w+', stripped) or re.search(r'(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|function\s*\()', stripped):
            continue

        # Find the current function context (which declared function this line belongs to)
        current_fn_id = None
        # Simple approach: find the nearest declared function above this line
        for fn_name, nid in declared_fns.items():
            fn_line = int(nid.split(':')[-1])
            if fn_line <= line_num:
                if current_fn_id is None or fn_line > int(current_fn_id.split(':')[-1]):
                    current_fn_id = nid

        if not current_fn_id:
            continue

        # Detect function calls: name(args) or object.method(args)
        # Pattern: standalone function call
        call_matches = re.finditer(r'(?<!\bfunction\s)(?<!\bconst\s)(?<!\blet\s)(?<!\bvar\s)([a-zA-Z_]\w*)\s*\(', stripped)
        for match in call_matches:
            called_name = match.group(1)

            # Skip keywords and common builtins
            skip_names = {
                'if', 'else', 'for', 'while', 'switch', 'catch', 'return',
                'const', 'let', 'var', 'function', 'class', 'new', 'typeof',
                'console', 'require', 'import', 'export', 'async', 'await',
                'try', 'throw', 'true', 'false', 'null', 'undefined',
                'String', 'Number', 'Boolean', 'Array', 'Object', 'Map', 'Set',
                'Promise', 'Error', 'parseInt', 'parseFloat', 'isNaN',
            }
            if called_name in skip_names:
                continue

            # Check if it's a method call (obj.method)
            method_match = re.search(r'(\w+)\.(' + re.escape(called_name) + r')\s*\(', stripped)
            if method_match:
                obj_name = method_match.group(1)
                full_name = f"{obj_name}.{called_name}"
                # Edge from current function to the called method
                edges.append({
                    "from": current_fn_id,
                    "to_fn": full_name
                })
            else:
                # Regular function call
                edges.append({
                    "from": current_fn_id,
                    "to_fn": called_name
                })

    return {"nodes": nodes, "edges": edges}
