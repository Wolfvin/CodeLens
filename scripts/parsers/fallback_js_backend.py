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
    # Also handles TypeScript generic functions where <...> may span multiple lines
    # by joining continuation lines before pattern matching
    joined_lines = []
    buf = ''
    for line in content.split('\n'):
        stripped = line.rstrip()
        if buf:
            # Continue joining lines until we find the opening paren or brace
            buf += ' ' + stripped
            if '(' in stripped or '{' in stripped:
                joined_lines.append(buf)
                buf = ''
            elif stripped.endswith(','):
                continue  # Still in generic params
            else:
                joined_lines.append(buf)
                buf = ''
        else:
            # Start a new join if line has function/class but no opening paren yet
            if re.search(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*$', stripped):
                buf = stripped
            elif re.search(r'\bclass\s+([a-zA-Z_]\w*)\s*$', stripped):
                buf = stripped
            elif re.search(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*<', stripped) and '(' not in stripped:
                buf = stripped
            elif re.search(r'\bclass\s+([a-zA-Z_]\w*)\s*<', stripped) and '{' not in stripped and '(' not in stripped:
                buf = stripped
            else:
                joined_lines.append(stripped)
    if buf:
        joined_lines.append(buf)

    for line_num_raw, line in enumerate(joined_lines, 1):
        # Approximate original line number: count actual lines up to this point
        # We use a simpler approach: search in the original content for position
        pass  # Will process below with original line numbers

    # Process original lines for accurate line numbers, but also check joined lines
    # for multi-line declarations
    original_lines = content.split('\n')

    # Multi-line generic function detection: scan for patterns that start on one line
    # and continue on the next.
    # Note: Line numbers may be slightly off because comments were stripped above,
    # but this is acceptable for dead-code analysis — the important thing is detecting
    # the function at all.
    multiline_fn_pattern = re.compile(
        r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*<[^)]*?\(',
        re.MULTILINE | re.DOTALL
    )
    for m in multiline_fn_pattern.finditer(content):
        name = m.group(1)
        if name not in skip_names:
            # Find the line number in original content
            line_num = content[:m.start()].count('\n') + 1
            if name not in fn_map:
                node_id = f"{file_path}:{line_num}"
                # Check if exported
                # Look backwards from the match start to check for 'export'
                prefix = content[max(0, m.start()-50):m.start()]
                is_exported = bool(re.search(r'\bexport\s*$', prefix))
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in m.group(0)[:20]}
                if is_exported:
                    node_data["exported"] = True
                nodes.append(node_data)
                fn_map[name] = node_id

    for line_num, line in enumerate(original_lines, 1):
        # Check if this line has an export keyword (for marking exported symbols)
        is_exported = bool(re.match(r'\s*export\s+', line))

        # function name(
        for m in re.finditer(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if is_exported:
                    node_data["exported"] = True
                nodes.append(node_data)
                fn_map[name] = node_id

        # TypeScript generic function: function name<Generic>(  or  async function name<Generic>(
        # The standard regex above misses these because <...> appears between name and (
        for m in re.finditer(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*<[^>]*>\s*\(', line):
            name = m.group(1)
            if name not in skip_names and name not in fn_map:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if is_exported:
                    node_data["exported"] = True
                nodes.append(node_data)
                fn_map[name] = node_id

        # class declarations: class ClassName, class ClassName extends ..., class ClassName implements ...
        # Also matches: class ClassName<Generic> (TypeScript generic classes)
        for m in re.finditer(r'\bclass\s+([a-zA-Z_]\w*)\s*[{<(]', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                is_component = name[0].isupper()
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": False, "node_type": "class",
                             "component": is_component}
                if is_exported:
                    node_data["exported"] = True
                # Extract heritage info (extends/implements)
                heritage_match = re.search(r'\bclass\s+' + re.escape(name) + r'(?:\s*<[^>]*>)?\s+(extends|implements)\s+([^{]+)', line)
                if heritage_match:
                    node_data["heritage"] = heritage_match.group(2).strip()
                nodes.append(node_data)
                fn_map[name] = node_id

        # const/let/var name = ( => arrow function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s*)?\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if is_exported:
                    node_data["exported"] = True
                nodes.append(node_data)
                fn_map[name] = node_id

        # const/let/var name = function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s+)?function', line):
            name = m.group(1)
            if name not in skip_names and name not in fn_map:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if is_exported:
                    node_data["exported"] = True
                nodes.append(node_data)
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
