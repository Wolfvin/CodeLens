"""Fallback JS backend parser (when tree-sitter grammars unavailable)."""

import re


def parse_js_backend_fallback(content, file_path):
    """Regex-based JS backend parser fallback (when tree-sitter unavailable)."""
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)

    nodes = []
    edges = []
    fn_map = {}  # name → node_id for edge resolution

    # Skip JS keywords and builtins
    skip_names = {
        'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
        'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
        'async', 'await', 'yield', 'import', 'export', 'from', 'default',
        'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
        'true', 'false', 'null', 'undefined', 'void', 'delete',
        'console', 'require', 'module', 'exports', 'process', 'global',
        'String', 'Number', 'Boolean', 'Array', 'Object', 'Map', 'Set',
        'Promise', 'Error', 'TypeError', 'parseInt', 'parseFloat',
        'JSON', 'Date', 'RegExp', 'Math', 'Buffer',
        'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    }

    # Detect function declarations: function name(...), const name = (), const name = function
    for line_num, line in enumerate(content.split('\n'), 1):
        # function name(
        for m in re.finditer(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

        # const/let/var name = ( => arrow function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s*)?\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

        # const/let/var name = function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s+)?function', line):
            name = m.group(1)
            if name not in skip_names and name not in fn_map:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

    # Detect function calls (simplified — within function bodies)
    # For each function found, scan its approximate scope for calls
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1  # 0-indexed
        # Approximate: scan from function start to next function or 50 lines
        end_line = min(start_line + 50, len(lines))
        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    edges.append({"from": node["id"], "to_fn": call_name})

    return {"nodes": nodes, "edges": edges}
