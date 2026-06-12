"""Fallback GDScript parser (when tree-sitter grammars unavailable)."""

import re


def parse_gdscript_fallback(content, file_path):
    """Regex-based GDScript parser fallback.

    Extracts:
    - Functions (func statements)
    - Classes (class_name and inner class statements)
    - Extends / inheritance
    - Signals
    - Constants and variables (as nodes for reference tracking)
    - Preload/load imports (as edges)

    Returns a dict with "nodes" and "edges" following the same format
    as other fallback parsers (e.g. fallback_python.py).
    """

    nodes = []
    edges = []
    fn_map = {}
    current_class = None
    class_indent_stack = []  # Track inner class scopes by indent

    skip_names = {
        'if', 'else', 'elif', 'for', 'while', 'match', 'break', 'continue',
        'pass', 'return', 'yield', 'signal', 'const', 'var', 'onready',
        'export', 'extends', 'class_name', 'func', 'class', 'enum',
        'static', 'remote', 'master', 'puppet', 'remotesync', 'mastersync', 'puppetsync',
        'true', 'false', 'null',
        'print', 'push_error', 'push_warning',
        'int', 'float', 'bool', 'String', 'Vector2', 'Vector3', 'Array',
        'Dictionary', 'Color', 'Rect2', 'Transform', 'Transform2D',
        'Basis', 'Quat', 'Plane', 'AABB', 'RID', 'Object', 'Node',
        'Node2D', 'Node3D', 'Control', 'Resource', 'PackedScene',
        'self', 'super', 'PI', 'TAU', 'INF', 'NAN',
    }

    lines = content.split('\n')

    # ── First pass: extract top-level declarations ──────────────────────

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        curr_indent = len(line) - len(line.lstrip()) if stripped else 0

        # Pop inner class scope when dedenting
        while class_indent_stack and curr_indent <= class_indent_stack[-1][1] and stripped:
            if not stripped.startswith('class '):
                class_indent_stack.pop()
                current_class = class_indent_stack[-1][0] if class_indent_stack else None
            break

        # class_name ClassName — top-level class declaration
        cn_match = re.match(r'^class_name\s+(\w+)', stripped)
        if cn_match:
            class_name = cn_match.group(1)
            current_class = class_name
            node_id = f"{file_path}:{line_num}:class:{class_name}"
            nodes.append({
                "id": node_id,
                "fn": class_name,
                "name": class_name,
                "type": "class",
                "file": file_path,
                "line": line_num,
                "async": False,
            })
            fn_map[class_name] = node_id
            continue

        # extends BaseClass — inheritance
        ext_match = re.match(r'^extends\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)', stripped)
        if ext_match:
            base_class = ext_match.group(1).split('.')[-1]
            if current_class:
                # Add inheritance edge
                for node in nodes:
                    if node.get("fn") == current_class and node.get("type") == "class":
                        if "inherits" not in node:
                            node["inherits"] = []
                        if base_class not in node["inherits"]:
                            node["inherits"].append(base_class)
                        break
            continue

        # class InnerClass: — inner class declaration
        inner_class_match = re.match(r'^class\s+(\w+)\s*:', stripped)
        if inner_class_match:
            inner_name = inner_class_match.group(1)
            class_indent_stack.append((inner_name, curr_indent))
            current_class = inner_name
            node_id = f"{file_path}:{line_num}:class:{inner_name}"
            class_node = {
                "id": node_id,
                "fn": inner_name,
                "name": inner_name,
                "type": "class",
                "file": file_path,
                "line": line_num,
                "async": False,
            }
            # If nested inside another class, note the outer class
            if len(class_indent_stack) > 1:
                class_node["impl_for"] = class_indent_stack[-2][0]
            nodes.append(class_node)
            fn_map[inner_name] = node_id
            continue

        # signal signal_name(args) — signal declaration
        sig_match = re.match(r'^signal\s+(\w+)', stripped)
        if sig_match:
            sig_name = sig_match.group(1)
            node_id = f"{file_path}:{line_num}:signal:{sig_name}"
            sig_node = {
                "id": node_id,
                "fn": sig_name,
                "name": sig_name,
                "type": "signal",
                "file": file_path,
                "line": line_num,
                "async": False,
            }
            if current_class:
                sig_node["impl_for"] = current_class
            nodes.append(sig_node)
            fn_map[sig_name] = node_id
            continue

        # func function_name(args): — function declaration
        func_match = re.match(r'^(?:static\s+)?func\s+([A-Za-z_]\w*)\s*\(', stripped)
        if func_match:
            name = func_match.group(1)
            if name not in skip_names:
                is_static = 'static' in stripped[:func_match.start() + 6]
                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "fn": name,
                    "name": name,
                    "type": "function",
                    "file": file_path,
                    "line": line_num,
                    "async": False,
                }
                if is_static:
                    node_data["static"] = True
                if current_class:
                    node_data["impl_for"] = current_class
                nodes.append(node_data)
                fn_map[name] = node_id
            continue

        # const NAME = value — constant declaration
        const_match = re.match(r'^const\s+([A-Za-z_]\w*)', stripped)
        if const_match:
            const_name = const_match.group(1)
            node_id = f"{file_path}:{line_num}:const:{const_name}"
            const_node = {
                "id": node_id,
                "fn": const_name,
                "name": const_name,
                "type": "constant",
                "file": file_path,
                "line": line_num,
                "async": False,
            }
            if current_class:
                const_node["impl_for"] = current_class
            nodes.append(const_node)
            fn_map[const_name] = node_id
            continue

    # ── Second pass: detect function calls within each function scope ──

    for node in nodes:
        if node["type"] != "function":
            continue

        start_line = node["line"] - 1
        # Determine function scope end by indentation
        fn_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
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
                    edges.append({
                        "from": node["id"],
                        "to_fn": call_name,
                        "via_self": is_self,
                    })

            # preload("path") and load("path") — import-like references
            for m in re.finditer(r'(?:preload|load)\s*\(\s*["\']([^"\']+)["\']', lines[i]):
                import_path = m.group(1)
                edges.append({
                    "from": node["id"],
                    "to_fn": import_path,
                    "via_self": False,
                    "type": "import",
                })

    return {"nodes": nodes, "edges": edges}
