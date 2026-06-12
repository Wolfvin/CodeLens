"""Fallback Rust parser (when tree-sitter grammars unavailable).

Parses Rust source to extract:
- Functions (fn) — with impl_for, trait_name, pub, async, unsafe
- Structs (struct) — with fields count, pub
- Enums (enum) — with variant count, pub
- Traits (trait) — with method count, pub
- Impl blocks (impl) — impl_for, trait_name
- Modules (mod) — with pub
- Constants (const) — with pub
- Type aliases (type) — with pub
- Use statements (use) — for dependency tracking
- Macro definitions (macro_rules!)

This ensures agents can query ANY Rust symbol, not just functions.
"""

import re
from typing import Dict, List, Any, Optional


def parse_rust_fallback(content: str, file_path: str) -> Dict[str, Any]:
    """Regex-based Rust parser fallback (when tree-sitter unavailable).

    Returns dict with 'nodes' and 'edges' lists suitable for the backend registry.
    Each node has: id, name, type, file, line, pub, async (for fn), impl_for (if in impl),
    trait_name (if trait impl), and other type-specific fields.
    """
    # Strip comments first
    stripped = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    nodes = []
    edges = []
    fn_map = {}  # name -> node_id for call resolution

    skip_names = {
        'if', 'else', 'for', 'while', 'loop', 'match', 'return', 'break',
        'continue', 'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl',
        'trait', 'use', 'mod', 'crate', 'super', 'self', 'Self',
        'true', 'false', 'as', 'in', 'ref', 'move', 'dyn', 'async', 'await',
        'Some', 'None', 'Ok', 'Err', 'new', 'default',
        'where', 'type', 'const', 'static',
    }

    current_impl_for = None
    current_trait_name = None
    brace_depth = 0
    impl_brace_start = None
    lines = stripped.split('\n')

    # ─── Pass 1: Extract all declarations ──────────────────

    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()

        # Track brace depth for impl scope
        old_brace_depth = brace_depth
        brace_depth += stripped_line.count('{') - stripped_line.count('}')

        # Detect when we exit an impl block
        if impl_brace_start is not None and brace_depth <= impl_brace_start:
            # We've returned to the brace depth before the impl
            current_impl_for = None
            current_trait_name = None
            impl_brace_start = None

        # ─── Impl blocks ───────────────────────────────
        impl_match = re.search(
            r'\bimpl\s+(?:(?P<trait>\w+)(?:\s*<[^>]*>)?\s+for\s+)?(?P<target>\w+)(?:\s*<[^>]*>)?',
            stripped_line
        )
        if impl_match:
            target = impl_match.group('target')
            trait = impl_match.group('trait')
            if target and target not in skip_names:
                current_impl_for = target
                current_trait_name = trait

                # Create an impl node so it shows up in queries
                impl_id = f"{file_path}:{line_num}:impl:{target}"
                impl_node = {
                    "id": impl_id,
                    "name": f"impl {f'{trait} for ' if trait else ''}{target}",
                    "fn": f"impl_{target}",  # backward compat: fn field for query
                    "type": "impl",
                    "file": file_path,
                    "line": line_num,
                    "pub": False,
                    "impl_for": target,
                    "ref_count": 0,
                    "status": "active",
                }
                if trait:
                    impl_node["trait_name"] = trait
                nodes.append(impl_node)

                # Track brace depth to know when impl ends
                if '{' in stripped_line:
                    impl_brace_start = old_brace_depth
                else:
                    # Multi-line impl: opening brace is on a later line
                    impl_brace_start = -1  # sentinel: need to find opening brace

        # Check if we're waiting for impl's opening brace
        if impl_brace_start == -1 and '{' in stripped_line and current_impl_for:
            impl_brace_start = old_brace_depth

        # ─── Struct declarations ───────────────────────
        struct_match = re.search(
            r'\b(?:pub\s+)?(?:pub\s*\([^)]*\)\s+)?struct\s+(\w+)',
            stripped_line
        )
        if struct_match:
            name = struct_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('struct')]
                node_id = f"{file_path}:{line_num}:struct:{name}"
                # Count fields (rough estimate from the same line + next few lines)
                field_count = _count_struct_fields(lines, line_num - 1)
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "struct",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "field_count": field_count,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Enum declarations ─────────────────────────
        enum_match = re.search(
            r'\b(?:pub\s+)?(?:pub\s*\([^)]*\)\s+)?enum\s+(\w+)',
            stripped_line
        )
        if enum_match:
            name = enum_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('enum')]
                node_id = f"{file_path}:{line_num}:enum:{name}"
                # Count variants
                variant_count = _count_enum_variants(lines, line_num - 1)
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "enum",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "variant_count": variant_count,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Trait declarations ────────────────────────
        trait_match = re.search(
            r'\b(?:pub\s+)?trait\s+(\w+)(?:\s*<[^>]*>)?',
            stripped_line
        )
        if trait_match:
            name = trait_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('trait')]
                node_id = f"{file_path}:{line_num}:trait:{name}"
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "trait",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Function declarations ─────────────────────
        fn_match = re.search(
            r'\b(?:(pub)\s+)?(?:(pub\s*\([^)]*\))\s+)?(?:(async)\s+)?(?:(unsafe)\s+)?fn\s+(\w+)\s*[<\(]',
            stripped_line
        )
        if fn_match:
            is_pub = fn_match.group(1) is not None or fn_match.group(2) is not None
            is_async = fn_match.group(3) is not None
            is_unsafe = fn_match.group(4) is not None
            name = fn_match.group(5)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {
                    "id": node_id,
                    "name": name,
                    "fn": name,
                    "type": "function",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "async": is_async,
                    "unsafe": is_unsafe,
                    "ref_count": 0,
                    "status": "active",
                }
                if current_impl_for:
                    node_data["impl_for"] = current_impl_for
                if current_trait_name:
                    node_data["trait_name"] = current_trait_name
                nodes.append(node_data)
                fn_map[name] = node_id

        # ─── Module declarations ───────────────────────
        mod_match = re.search(
            r'\b(?:pub\s+)?(?:pub\s*\([^)]*\)\s+)?mod\s+(\w+)',
            stripped_line
        )
        if mod_match:
            name = mod_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('mod')]
                node_id = f"{file_path}:{line_num}:mod:{name}"
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "module",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Const declarations ────────────────────────
        const_match = re.search(
            r'\b(?:pub\s+)?const\s+(\w+)\s*:',
            stripped_line
        )
        if const_match:
            name = const_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('const')]
                node_id = f"{file_path}:{line_num}:const:{name}"
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "const",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Static declarations ───────────────────────
        static_match = re.search(
            r'\b(?:pub\s+)?static\s+(\w+)\s*:',
            stripped_line
        )
        if static_match:
            name = static_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('static')]
                node_id = f"{file_path}:{line_num}:static:{name}"
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "static",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Type alias declarations ───────────────────
        type_match = re.search(
            r'\b(?:pub\s+)?type\s+(\w+)\s*(?:<[^>]*>)?\s*=',
            stripped_line
        )
        if type_match:
            name = type_match.group(1)
            if name not in skip_names:
                is_pub = 'pub' in stripped_line[:stripped_line.index('type')]
                node_id = f"{file_path}:{line_num}:type:{name}"
                nodes.append({
                    "id": node_id,
                    "name": name,
                    "fn": name,  # backward compat
                    "type": "type_alias",
                    "file": file_path,
                    "line": line_num,
                    "pub": is_pub,
                    "ref_count": 0,
                    "status": "active",
                })
                fn_map[name] = node_id

        # ─── Macro definitions ─────────────────────────
        macro_match = re.search(
            r'\bmacro_rules!\s+(\w+)',
            stripped_line
        )
        if macro_match:
            name = macro_match.group(1)
            node_id = f"{file_path}:{line_num}:macro:{name}"
            nodes.append({
                "id": node_id,
                "name": name,
                "fn": name,  # backward compat
                "type": "macro",
                "file": file_path,
                "line": line_num,
                "pub": True,  # macros are always pub
                "ref_count": 0,
                "status": "active",
            })
            fn_map[name] = node_id

    # ─── Pass 2: Detect function calls and type usage ──────

    for node in nodes:
        if node.get("type") not in ("function", "impl"):
            continue

        start_line = node["line"] - 1
        # Look at function body (up to 80 lines or until next fn/struct/etc)
        end_line = min(start_line + 80, len(lines))

        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            current_line = lines[i]

            # Direct function/method calls: name(
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', current_line):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node.get("fn"):
                    is_self_call = bool(re.search(r'\bself\.' + re.escape(call_name), current_line))
                    edges.append({
                        "from": node["id"],
                        "to_fn": call_name,
                        "via_self": is_self_call,
                    })

            # Type usage: name { or name :: or <name> or &name or name::
            # This detects struct construction, enum variants, trait bounds, etc.
            for m in re.finditer(r'\b([A-Z][a-zA-Z_]\w*)\s*[{::<]', current_line):
                type_name = m.group(1)
                if type_name not in skip_names and type_name != node.get("fn"):
                    edges.append({
                        "from": node["id"],
                        "to_fn": type_name,
                        "via_type": True,
                    })

            # Method call chains: .method(
            for m in re.finditer(r'\.\s*([a-z_][a-zA-Z_]\w*)\s*\(', current_line):
                method_name = m.group(1)
                if method_name not in skip_names:
                    edges.append({
                        "from": node["id"],
                        "to_fn": method_name,
                        "via_method": True,
                    })

    # ─── Pass 3: Use statements for dependency tracking ──────

    use_edges = []
    for line_num, line in enumerate(lines, 1):
        stripped_line = line.strip()
        # use crate::module::Item;
        # use super::module::*;
        # use std::collections::HashMap;
        use_match = re.match(r'\s*use\s+(.+?);', stripped_line)
        if use_match:
            use_path = use_match.group(1).strip()
            # Extract the last item name (the actual import)
            parts = use_path.replace('{', '').replace('}', '').replace(' ', '').split('::')
            if parts:
                last_part = parts[-1].split(',')[0]  # handle {A, B, C}
                if last_part and last_part not in skip_names and last_part != 'self':
                    use_edges.append({
                        "from_file": file_path,
                        "from_line": line_num,
                        "use_path": use_path,
                        "imported_name": last_part,
                    })

    return {
        "nodes": nodes,
        "edges": edges,
        "use_statements": use_edges,
    }


def _count_struct_fields(lines: List[str], start_idx: int) -> int:
    """Count the number of fields in a struct definition.

    Handles both struct { field1, field2 } and tuple struct (Type, Type).
    """
    count = 0
    brace_depth = 0
    started = False

    for i in range(start_idx, min(start_idx + 50, len(lines))):
        line = lines[i]
        for ch in line:
            if ch == '{':
                brace_depth += 1
                started = True
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and started:
                    return count
            elif started and brace_depth == 1:
                # Count commas at depth 1 for field separation
                pass

        if started and brace_depth >= 1:
            # Count fields by looking for name: Type patterns
            for m in re.finditer(r'\b[a-z_]\w*\s*:', line):
                count += 1

    return count


def _count_enum_variants(lines: List[str], start_idx: int) -> int:
    """Count the number of variants in an enum definition."""
    count = 0
    brace_depth = 0
    started = False

    for i in range(start_idx, min(start_idx + 100, len(lines))):
        line = lines[i]
        for ch in line:
            if ch == '{':
                brace_depth += 1
                started = True
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and started:
                    return count

        if started and brace_depth >= 1:
            # Count variant names (Capitalized identifiers before { or ( or ,)
            for m in re.finditer(r'\b([A-Z][a-zA-Z_]\w*)\s*[{(,}]', line):
                variant_name = m.group(1)
                # Filter out common non-variant names
                if variant_name not in ('Some', 'None', 'Ok', 'Err', 'Self'):
                    count += 1

    return count
