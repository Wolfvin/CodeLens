"""
Rust Parser for CodeLens
Extracts function declarations and function calls from Rust source code.

Detected patterns:
- fn verify_token(token: &str) -> Result<Claims> { ... }
- pub fn hash_password(pw: &str) -> String { ... }
- async fn fetch_data(url: &str) -> Response { ... }
- verify_token(&token)?
- hash_password(&input)
- self.verify_token(&token)

Rules:
- pub fn and fn both tracked
- async fn tracked with async: true
- Method calls via self.method() → tracked as edge to same struct
- Macro calls (println!, vec!) → IGNORED
- Trait implementations → tracked with impl_for: TypeName
"""

import re
from typing import Dict, List, Any


def strip_rust_comments(content: str) -> str:
    """Remove Rust line and block comments."""
    # Remove block comments (including nested doc comments)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    # Remove line comments
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    return content


def extract_rust_references(content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract function declarations and calls from Rust content.

    Returns:
        {
            "nodes": [{"id": str, "fn": str, "file": str, "line": int, "async": bool, "impl_for": str|None}],
            "edges": [{"from": str, "to_fn": str}]
        }
    """
    cleaned = strip_rust_comments(content)
    lines = cleaned.split('\n')

    nodes = []
    edges = []

    # Track declared functions
    declared_fns: Dict[str, str] = {}  # fn_name → node_id

    # Track current impl block
    current_impl_for = None

    # Track function scope (which fn block we're inside)
    current_fn_id = None
    brace_depth = 0
    fn_start_depth = 0

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()

        # Track impl blocks
        impl_match = re.match(r'impl\s+(?:<[^>]+>\s+)?(\w+)', stripped)
        if impl_match:
            current_impl_for = impl_match.group(1)

        # Reset impl_for when we leave the impl block (simplified)
        if stripped.startswith('}') and current_impl_for and brace_depth <= 1:
            current_impl_for = None

        # --- Function Declarations ---
        fn_match = re.search(r'\b(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[<(]', stripped)
        if fn_match:
            fn_name = fn_match.group(1)
            node_id = f"{file_path}:{line_num}"
            is_async = 'async' in stripped[:stripped.index('fn')] if 'fn' in stripped else False

            nodes.append({
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line_num,
                "async": bool(is_async),
                "impl_for": current_impl_for
            })
            declared_fns[fn_name] = node_id
            current_fn_id = node_id
            fn_start_depth = brace_depth
            continue

        # Track brace depth for scope
        brace_depth += stripped.count('{') - stripped.count('}')

        # If we're back at the function start depth, we've left the function
        if current_fn_id and brace_depth <= fn_start_depth and '{' not in stripped and '}' in stripped:
            current_fn_id = None
            continue

        # --- Function Calls (only inside a function) ---
        if not current_fn_id:
            continue

        # Skip macro calls: name!(...)
        # Find function calls: name(args) but not name!(args)
        call_matches = re.finditer(r'(\w+)\s*\((?!!)', stripped)
        for match in call_matches:
            called_name = match.group(1)

            # Skip Rust keywords and builtins
            skip_names = {
                'if', 'else', 'for', 'while', 'loop', 'match', 'return',
                'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl',
                'trait', 'use', 'mod', 'crate', 'super', 'self', 'Self',
                'true', 'false', 'Some', 'None', 'Ok', 'Err',
                'println', 'eprintln', 'format', 'vec', 'boxed', 'panic',
                'assert', 'assert_eq', 'assert_ne', 'todo', 'unimplemented',
                'unreachable', 'derive', 'test', 'cfg', 'allow', 'warn',
            }
            if called_name in skip_names:
                continue

            # Check for self.method() call
            self_match = re.search(r'self\.(\w+)\s*\(', stripped)
            if self_match and self_match.group(1) == called_name:
                edges.append({
                    "from": current_fn_id,
                    "to_fn": called_name,
                    "via_self": True
                })
            else:
                edges.append({
                    "from": current_fn_id,
                    "to_fn": called_name
                })

    return {"nodes": nodes, "edges": edges}
