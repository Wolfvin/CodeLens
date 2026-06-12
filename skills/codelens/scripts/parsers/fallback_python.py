"""Fallback Python parser (when tree-sitter grammars unavailable)."""

import re


def parse_python_fallback(content, file_path):
    """Regex-based Python parser fallback (when tree-sitter unavailable)."""

    nodes = []
    edges = []
    fn_map = {}
    current_class = None
    class_stack = []  # Track nested class scopes

    skip_names = {
        'if', 'else', 'elif', 'for', 'while', 'with', 'try', 'except', 'finally',
        'return', 'yield', 'raise', 'break', 'continue', 'pass', 'import', 'from',
        'class', 'def', 'async', 'await', 'lambda', 'global', 'nonlocal',
        'True', 'False', 'None',
        'print', 'len', 'range', 'int', 'str', 'float', 'bool', 'list', 'dict',
        'set', 'tuple', 'type', 'isinstance', 'super', 'property',
        'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
        'iter', 'next', 'abs', 'min', 'max', 'sum', 'any', 'all',
        'self', 'cls',
    }

    prev_indent = 0
    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()
        curr_indent = len(line) - len(line.lstrip())

        # Track class context using indentation-based scope
        if stripped.startswith('class '):
            class_match = re.match(r'class\s+(\w+)', stripped)
            if class_match:
                class_stack.append((class_match.group(1), curr_indent))
                current_class = class_match.group(1)

        # Pop class stack when dedenting
        while class_stack and curr_indent <= class_stack[-1][1] and stripped and not stripped.startswith('class '):
            class_stack.pop()
            current_class = class_stack[-1][0] if class_stack else None

        prev_indent = curr_indent

        # def name(
        for m in re.finditer(r'\b(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\(', stripped):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in stripped[:m.start()]}
                if current_class:
                    node_data["impl_for"] = current_class
                nodes.append(node_data)
                fn_map[name] = node_id

    # Detect function calls (simplified scope scanning)
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1
        # Get the indent level of the function definition
        fn_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
        # Scan until dedent back to same or lower level
        end_line = len(lines)
        for i in range(start_line + 1, len(lines)):
            if lines[i].strip() == '':
                continue
            line_indent = len(lines[i]) - len(lines[i].lstrip())
            if line_indent <= fn_indent and lines[i].strip():
                end_line = i
                break

        for i in range(start_line, end_line):
            # Direct calls: name(
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    is_self = bool(re.search(r'\bself\.' + re.escape(call_name), lines[i]))
                    edges.append({"from": node["id"], "to_fn": call_name, "via_self": is_self})

    return {"nodes": nodes, "edges": edges}
