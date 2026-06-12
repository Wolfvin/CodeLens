"""
Fallback Go Parser for CodeLens — regex-based extraction.
Extracts functions, methods, types, imports, package declarations,
and function call relationships for edge resolution.
"""

import re
from typing import Dict, List, Any


def parse_go_fallback(content: str, rel_path: str) -> Dict[str, Any]:
    """Parse Go source using regex — extracts functions, types, imports, and call edges."""
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    lines = content.split('\n')

    # Package
    pkg = ""
    for i, line in enumerate(lines, 1):
        m = re.match(r'\s*package\s+(\w+)', line)
        if m:
            pkg = m.group(1)
            break

    # Imports (single + grouped) — these become module-level import edges
    in_import_block = False
    for i, line in enumerate(lines, 1):
        if re.match(r'\s*import\s*\(', line):
            in_import_block = True
            continue
        if in_import_block:
            if ')' in line:
                in_import_block = False
                continue
            m = re.search(r'"([^"]+)"', line)
            if m:
                edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})
            continue
        m = re.match(r'\s*import\s+"([^"]+)"', line)
        if m:
            edges.append({"from": rel_path, "to": m.group(1), "type": "import", "weight": 1})

    # Collect all function/method names for intra-file call resolution
    fn_defs = {}  # fn_name → node_id
    method_defs = {}  # Receiver.Type.method → node_id

    # Functions
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Method with receiver
        m = re.match(r'func\s+\(\s*\w+\s+\*?(\w+)\s*\)\s+(\w+)', stripped)
        if m:
            receiver = m.group(1)
            method_name = m.group(2)
            node_id = f"{rel_path}:{i}:{receiver}.{method_name}"
            nodes.append({"id": node_id, "type": "method",
                          "name": method_name, "fn": method_name,
                          "file": rel_path, "line": i, "domain": "backend", "receiver": receiver})
            method_defs[f"{receiver}.{method_name}"] = node_id
            fn_defs[method_name] = node_id  # also register by short name
            continue
        # Regular function
        m = re.match(r'func\s+(\w+)', stripped)
        if m:
            fn_name = m.group(1)
            ntype = "function"
            if fn_name == "init":
                ntype = "init"
            elif fn_name.startswith("Test"):
                ntype = "test"
            elif fn_name.startswith("Benchmark"):
                ntype = "benchmark"
            node_id = f"{rel_path}:{i}:{fn_name}"
            nodes.append({"id": node_id, "type": ntype,
                          "name": fn_name, "fn": fn_name,
                          "file": rel_path, "line": i, "domain": "backend"})
            fn_defs[fn_name] = node_id

    # Types
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        m = re.match(r'type\s+(\w+)\s+struct\b', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:{m.group(1)}", "type": "struct",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})
            continue
        m = re.match(r'type\s+(\w+)\s+interface\b', stripped)
        if m:
            nodes.append({"id": f"{rel_path}:{i}:{m.group(1)}", "type": "interface",
                          "name": m.group(1), "fn": m.group(1),
                          "file": rel_path, "line": i, "domain": "backend"})

    # ─── Function call edges ─────────────────────────────────────
    # Extract call relationships within the file so edge_resolver can
    # link callers → callees. This fixes the "100% dead code" problem
    # where only import edges existed and no call edges were generated.
    #
    # Strategy: For each function body, find function calls and method calls.
    # We match: fnName(...), obj.Method(...), pkg.Func(...)
    # Skip: keywords (if, for, return, etc.), type assertions, builtins

    _GO_KEYWORDS = frozenset({
        'if', 'for', 'return', 'defer', 'go', 'select', 'switch', 'case',
        'default', 'break', 'continue', 'fallthrough', 'else', 'range',
        'var', 'const', 'type', 'func', 'import', 'package', 'map',
        'chan', 'interface', 'struct', 'goto',
    })
    _GO_BUILTINS = frozenset({
        'append', 'cap', 'close', 'copy', 'delete', 'len', 'make',
        'new', 'panic', 'print', 'println', 'recover', 'complex',
        'real', 'imag', 'clear', 'min', 'max',
    })

    # Build a simple function→body range map
    fn_ranges = []  # [(node_id, start_line, end_line)]
    brace_count = 0
    current_fn = None
    fn_start = 0

    for i, line in enumerate(lines, 1):
        # Detect function start (already registered in nodes)
        stripped = line.strip()
        for node in nodes:
            if node.get("line") == i and node.get("type") in ("function", "method", "init", "test", "benchmark"):
                if current_fn:
                    fn_ranges.append((current_fn, fn_start, i - 1))
                current_fn = node["id"]
                fn_start = i
                brace_count = 0
                break

        if current_fn:
            brace_count += stripped.count('{') - stripped.count('}')
            if brace_count <= 0 and '{' in ''.join(lines[fn_start-1:i]):
                fn_ranges.append((current_fn, fn_start, i))
                current_fn = None

    # Handle last function
    if current_fn:
        fn_ranges.append((current_fn, fn_start, len(lines)))

    # Extract calls from each function body
    call_pattern = re.compile(
        r'(?:^|[^\w.])'                        # Not preceded by identifier/dot
        r'((?:[\w]+\.)?[\w]+)\s*\('             # fnName( or pkg.fnName(
    )

    for fn_id, start_line, end_line in fn_ranges:
        # Get the body lines
        body = '\n'.join(lines[start_line:end_line])
        for m in call_pattern.finditer(body):
            call_expr = m.group(1)
            parts = call_expr.split('.')
            if len(parts) == 2:
                # obj.Method() or pkg.Func()
                obj_or_pkg, method_name = parts
                # Check if it's a known method on a known receiver
                method_key = f"{obj_or_pkg}.{method_name}"
                if method_key in method_defs:
                    edges.append({
                        "from": fn_id,
                        "to": method_defs[method_key],
                        "to_fn": method_name,
                        "type": "call",
                        "weight": 1,
                    })
                elif method_name in fn_defs:
                    # Could be pkg.Func()
                    edges.append({
                        "from": fn_id,
                        "to": fn_defs[method_name],
                        "to_fn": method_name,
                        "type": "call",
                        "weight": 1,
                    })
                else:
                    # Unknown target — create an unresolved call edge
                    edges.append({
                        "from": fn_id,
                        "to_fn": method_name,
                        "type": "call",
                        "weight": 1,
                    })
            elif len(parts) == 1:
                fn_name = parts[0]
                if fn_name in _GO_KEYWORDS or fn_name in _GO_BUILTINS:
                    continue
                if fn_name.startswith(('fmt.', 'os.', 'io.', 'strings.', 'strconv.', 'sync.')):
                    continue
                if fn_name in fn_defs:
                    edges.append({
                        "from": fn_id,
                        "to": fn_defs[fn_name],
                        "to_fn": fn_name,
                        "type": "call",
                        "weight": 1,
                    })
                else:
                    # Unresolved call — still create edge for cross-file resolution
                    edges.append({
                        "from": fn_id,
                        "to_fn": fn_name,
                        "type": "call",
                        "weight": 1,
                    })

    return {"nodes": nodes, "edges": edges}
