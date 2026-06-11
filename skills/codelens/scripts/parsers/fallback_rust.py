"""Fallback Rust parser (when tree-sitter grammars unavailable)."""

import re


def parse_rust_fallback(content, file_path):
    """Regex-based Rust parser fallback (when tree-sitter unavailable)."""
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    nodes = []
    edges = []
    fn_map = {}

    skip_names = {
        'if', 'else', 'for', 'while', 'loop', 'match', 'return', 'break',
        'continue', 'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl',
        'trait', 'use', 'mod', 'crate', 'super', 'self', 'Self',
        'true', 'false', 'as', 'in', 'ref', 'move', 'dyn', 'async', 'await',
        'Some', 'None', 'Ok', 'Err', 'new', 'default',
    }

    current_impl = None
    brace_depth = 0
    impl_brace_depth = None  # brace depth when impl block was entered

    for line_num, line in enumerate(content.split('\n'), 1):
        # Track brace depth
        open_braces = line.count('{')
        close_braces = line.count('}')

        # Track impl blocks
        impl_match = re.search(r'\bimpl\s+(?:\w+\s+for\s+)?(\w+)', line)
        if impl_match:
            current_impl = impl_match.group(1)
            impl_brace_depth = brace_depth + open_braces - close_braces if '{' in line else brace_depth

        # Update brace depth after processing the line
        brace_depth += open_braces - close_braces

        # Reset impl context when we've closed all braces opened inside the impl block
        if current_impl and impl_brace_depth is not None and brace_depth < impl_brace_depth:
            current_impl = None
            impl_brace_depth = None

        # fn name(
        for m in re.finditer(r'\b(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z_]\w*)\s*[\(<]', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if current_impl:
                    node_data["impl_for"] = current_impl
                nodes.append(node_data)
                fn_map[name] = node_id

    # Detect function calls (simplified)
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1
        end_line = min(start_line + 50, len(lines))
        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            # Direct calls: name(
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    is_self = bool(re.search(r'\bself\.' + re.escape(call_name), lines[i]))
                    edges.append({"from": node["id"], "to_fn": call_name, "via_self": is_self})

    return {"nodes": nodes, "edges": edges}
