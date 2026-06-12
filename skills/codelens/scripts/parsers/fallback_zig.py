"""Fallback Zig parser (regex-based, when tree-sitter grammars unavailable).

Parses Zig source to extract:
- Functions (fn) — with pub, extern, export, inline, callconv
- Structs (struct) — with pub
- Enums (enum) — with variant count, pub
- Unions (union) — with pub
- Opaque types (opaque {}) — with pub
- Constants (const) — with pub
- Variables (var) — with pub
- Error sets (error {}) — with pub
- Usingnamespace declarations
- Imports (@import)

Zig syntax reference: https://ziglang.org/documentation/master/
"""

import re
from typing import Dict, List, Any, Optional


def parse_zig_fallback(content: str, file_path: str) -> Dict[str, Any]:
    """Regex-based Zig parser fallback.

    Returns dict with 'nodes' and 'edges' lists suitable for the backend registry.
    Each node has: id, name, type, file, line, pub, and other type-specific fields.
    """
    # Strip comments first (Zig uses // for line comments, no block comments)
    stripped = re.sub(r'//.*$', '', content, flags=re.MULTILINE)

    nodes = []
    edges = []
    fn_map = {}  # name -> node_id for call resolution

    skip_names = {
        'if', 'else', 'for', 'while', 'switch', 'return', 'break',
        'continue', 'try', 'catch', 'error', 'defer', 'errdefer',
        'const', 'var', 'pub', 'fn', 'struct', 'enum', 'union',
        'opaque', 'true', 'false', 'null', 'undefined',
        'usingnamespace', 'test', 'extern', 'export', 'inline',
        'noinline', 'callconv', 'async', 'await', 'suspend', 'resume',
        'anytype', 'anyframe', 'type', 'void', 'bool', 'noreturn',
        'comptime', 'packed', 'linksection', 'align',
        # Common Zig stdlib types
        'Allocator', 'ArrayList', 'HashMap', 'StringHashMap',
        'std', 'builtin', 'root',
    }

    lines = stripped.split('\n')

    # ─── Pass 1: Extract all declarations ──────────────────

    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()

        # Skip empty lines
        if not stripped_line:
            continue

        # Detect visibility modifier
        is_pub = stripped_line.startswith('pub ')
        prefix = 'pub ' if is_pub else ''

        # ─── Functions ─────────────────────────────────
        # Zig fn syntax: [pub] [extern|export|inline|noinline] fn name(params) [callconv(...)] [!?]ReturnType
        # Also handles: pub fn name(...) ... and export fn name(...) ...
        fn_match = re.search(
            r'^(?:pub\s+)?(?:extern\s+|export\s+|inline\s+|noinline\s+)?fn\s+(\w+)\s*\(',
            stripped_line
        )
        if fn_match:
            fn_name = fn_match.group(1)
            if fn_name in skip_names:
                continue

            is_extern = 'extern ' in stripped_line[:stripped_line.index('fn')]
            is_export = 'export ' in stripped_line[:stripped_line.index('fn')]
            is_inline_fn = 'inline ' in stripped_line[:stripped_line.index('fn')]

            # Determine if this is a method inside a struct/enum/union (previous non-blank declaration)
            impl_for = None
            # Walk backward to find the container this fn might belong to
            for prev_idx in range(line_num - 2, -1, -1):
                prev_line = lines[prev_idx].strip()
                if not prev_line:
                    continue
                # Check if previous declaration is a container type
                container_match = re.search(
                    r'^(?:pub\s+)?const\s+(\w+)\s*=\s*(?:packed\s+)?(?:struct|enum|union|opaque)',
                    prev_line
                )
                if container_match:
                    impl_for = container_match.group(1)
                break

            node_id = f"{file_path}:{line_num}:fn:{fn_name}"
            node = {
                "id": node_id,
                "name": fn_name,
                "type": "function",
                "file": file_path,
                "line": line_num,
                "pub": is_pub,
                "extern": is_extern,
                "export": is_export,
                "inline": is_inline_fn,
                "impl_for": impl_for,
            }
            nodes.append(node)
            fn_map[fn_name] = node_id

            # Extract @import calls from function body (scan next ~50 lines)
            for body_idx in range(line_num - 1, min(line_num + 49, len(lines))):
                body_line = lines[body_idx]
                import_match = re.search(r'@import\s*\(\s*"([^"]+)"\s*\)', body_line)
                if import_match:
                    edges.append({
                        "from": node_id,
                        "to_fn": import_match.group(1),
                        "type": "imports",
                        "file": file_path,
                        "line": body_idx + 1,
                    })

            continue

        # ─── Const declarations (struct, enum, union, opaque, type alias, error set) ───
        # Zig: [pub] const Name = struct { ... }
        # Zig: [pub] const Name = enum { ... }
        # Zig: [pub] const Name = union { ... }
        # Zig: [pub] const Name = opaque {}
        # Zig: [pub] const Name = error { ... }
        # Zig: [pub] const Name = @Type(...)
        # Zig: [pub] const Name = some_type;

        const_match = re.match(
            r'^pub\s+const\s+(\w+)\s*=\s*(.*?)(?:;|$)',
            stripped_line
        )
        if not const_match and not is_pub:
            const_match = re.match(
                r'^const\s+(\w+)\s*=\s*(.*?)(?:;|$)',
                stripped_line
            )

        if const_match:
            const_name = const_match.group(1)
            const_value = const_match.group(2).strip()

            if const_name in skip_names or const_name.startswith('_'):
                continue

            # Check what kind of const this is
            if re.match(r'(?:packed\s+)?struct\s*(?:\{|$)', const_value):
                node_id = f"{file_path}:{line_num}:struct:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "struct",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[const_name] = node_id

                # Check for @import inside struct initialization
                for body_idx in range(line_num - 1, min(line_num + 99, len(lines))):
                    body_line = lines[body_idx]
                    import_match = re.search(r'@import\s*\(\s*"([^"]+)"\s*\)', body_line)
                    if import_match:
                        edges.append({
                            "from": node_id,
                            "to_fn": import_match.group(1),
                            "type": "imports",
                            "file": file_path,
                            "line": body_idx + 1,
                        })

            elif re.match(r'(?:packed\s+)?enum\s*(?:\(|{)', const_value):
                # Count variants if on same line or scan ahead
                variant_count = _count_enum_variants(lines, line_num - 1)
                node_id = f"{file_path}:{line_num}:enum:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "enum",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "variant_count": variant_count,
                })
                fn_map[const_name] = node_id

            elif re.match(r'(?:packed\s+)?union\s*(?:\(|{)', const_value):
                node_id = f"{file_path}:{line_num}:union:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "union",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[const_name] = node_id

            elif re.match(r'opaque\s*{', const_value):
                node_id = f"{file_path}:{line_num}:opaque:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "opaque",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[const_name] = node_id

            elif re.match(r'error\s*{', const_value):
                node_id = f"{file_path}:{line_num}:error_set:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "error_set",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[const_name] = node_id

            else:
                # Regular const (value assignment, type alias, etc.)
                # Skip trivial assignments like const std = @import("std")
                if '@import' in const_value:
                    # Track as import edge
                    import_match = re.search(r'@import\s*\(\s*"([^"]+)"\s*\)', const_value)
                    if import_match:
                        edges.append({
                            "from": f"{file_path}:{line_num}:const:{const_name}",
                            "to_fn": import_match.group(1),
                            "type": "imports",
                            "file": file_path,
                            "line": line_num,
                        })
                    # Still create a node for the const alias
                node_id = f"{file_path}:{line_num}:const:{const_name}"
                nodes.append({
                    "id": node_id,
                    "name": const_name,
                    "type": "const",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[const_name] = node_id

            continue

        # ─── Var declarations ───────────────────────────
        var_match = re.match(
            r'^pub\s+var\s+(\w+)\s*[:=]',
            stripped_line
        )
        if not var_match and not is_pub:
            var_match = re.match(
                r'^var\s+(\w+)\s*[:=]',
                stripped_line
            )
        if var_match:
            var_name = var_match.group(1)
            if var_name not in skip_names and not var_name.startswith('_'):
                node_id = f"{file_path}:{line_num}:var:{var_name}"
                nodes.append({
                    "id": node_id,
                    "name": var_name,
                    "type": "var",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                })
                fn_map[var_name] = node_id
            continue

        # ─── Usingnamespace ────────────────────────────
        usingnamespace_match = re.match(
            r'^pub\s+usingnamespace\s+(\w+)',
            stripped_line
        )
        if not usingnamespace_match:
            usingnamespace_match = re.match(
                r'^usingnamespace\s+(\w+)',
                stripped_line
            )
        if usingnamespace_match:
            target = usingnamespace_match.group(1)
            edges.append({
                "from": file_path,
                "to_fn": target,
                "type": "usingnamespace",
                "file": file_path,
                "line": line_num,
            })
            continue

        # ─── Top-level @import (not in const) ──────────
        import_match = re.search(r'@import\s*\(\s*"([^"]+)"\s*\)', stripped_line)
        if import_match:
            edges.append({
                "from": file_path,
                "to_fn": import_match.group(1),
                "type": "imports",
                "file": file_path,
                "line": line_num,
            })
            continue

    # ─── Pass 2: Resolve function calls ────────────────────

    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()
        # Skip comment lines
        if stripped_line.startswith('//'):
            continue

        # Find function calls: identifier(args) or identifier.identifier(args)
        # But skip declarations (fn, if, while, for, switch)
        for call_match in re.finditer(r'(?<!\w)(\w+)\s*\(', stripped_line):
            callee = call_match.group(1)
            if callee in skip_names:
                continue
            if callee in fn_map:
                # Find the caller (function we're inside)
                # Simple heuristic: find the closest preceding fn node
                caller_id = _find_enclosing_fn(nodes, file_path, line_num)
                if caller_id and caller_id != fn_map[callee]:
                    edges.append({
                        "from": caller_id,
                        "to_fn": callee,
                        "type": "calls",
                        "file": file_path,
                        "line": line_num,
                    })

    return {"nodes": nodes, "edges": edges}


def _count_enum_variants(lines: list, start_idx: int) -> int:
    """Count the number of variants in a Zig enum declaration."""
    count = 0
    brace_depth = 0
    found_open = False
    for i in range(start_idx, min(start_idx + 200, len(lines))):
        line = lines[i]
        for ch in line:
            if ch == '{':
                brace_depth += 1
                found_open = True
            elif ch == '}':
                brace_depth -= 1
                if found_open and brace_depth == 0:
                    return count
        # Count items inside the enum (simple heuristic: lines with just a name)
        if found_open and brace_depth == 1:
            stripped = line.strip().rstrip(',')
            if stripped and not stripped.startswith('//') and stripped not in ('', '{', '}'):
                # Check it looks like an identifier (not a function or special syntax)
                if re.match(r'^\w+$', stripped):
                    count += 1
    return count


def _find_enclosing_fn(nodes: list, file_path: str, line_num: int) -> Optional[str]:
    """Find the node ID of the function that encloses the given line."""
    best_node = None
    best_line = 0
    for node in nodes:
        if node.get("file") == file_path and node.get("type") == "function":
            node_line = node.get("line", 0)
            if node_line <= line_num and node_line > best_line:
                best_line = node_line
                best_node = node["id"]
    return best_node
