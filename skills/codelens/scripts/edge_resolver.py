"""
Edge Resolver for CodeLens
Resolves cross-file function call references.
Builds a complete call graph from all parsed backend data.
"""

from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


def _extract_file_from_id(node_id: str) -> str:
    """Extract the file path from a node ID like 'path/to/file.rs:42:fn_name'.

    Handles multi-colon formats (Rust, C++) where rsplit(':',1)[0] would
    incorrectly return 'file:line' instead of just 'file'.
    """
    parts = node_id.split(':')
    if len(parts) >= 3:
        # Format: file:line:name — rejoin everything except last two parts
        return ':'.join(parts[:-2])
    elif len(parts) == 2:
        # Format: file:name or file:line
        return parts[0]
    return node_id


# ─── Cached Index for O(1) lookups ────────────────────────────
# Built lazily on first call to get_callers/get_callees, invalidated
# when edges list changes (via _edge_list_fingerprint).
# NOTE: We use len(edges) + first/last edge IDs as a fingerprint
# instead of id() because Python can reuse memory addresses for
# different list objects, causing stale cache hits.

_edge_cache: Dict[str, Any] = {
    "fingerprint": None,  # Content-based fingerprint of edges list
    "to_index": None,     # node_id → List[edge]  (incoming)
    "from_index": None,   # node_id → List[edge]  (outgoing)
    "node_map": None,     # node_id → node dict
}


def _compute_fingerprint(edges: List[Dict], nodes: Optional[List[Dict]] = None) -> str:
    """Compute a content-based fingerprint for the edges list (and optionally nodes).
    Uses length + first/last edge IDs to detect changes efficiently.
    Also includes nodes fingerprint to detect stale node_map after metadata changes.
    This avoids the id() pitfall where Python reuses memory addresses."""
    if not edges:
        return "empty"
    first = edges[0]
    last = edges[-1]
    fp = f"len={len(edges)}|first_from={first.get('from','')}|first_to={first.get('to','')}|last_from={last.get('from','')}|last_to={last.get('to','')}"
    if nodes:
        fp += f"|nodes={len(nodes)}"
        if nodes:
            fn0 = nodes[0].get("fn", "")
            fnN = nodes[-1].get("fn", "")
            fp += f"|first_fn={fn0}|last_fn={fnN}"
    return fp


def _build_index(edges: List[Dict], nodes: Optional[List[Dict]] = None) -> None:
    """Build or rebuild the caller/callee index if the edges list changed."""
    fingerprint = _compute_fingerprint(edges, nodes)
    if _edge_cache["fingerprint"] == fingerprint and _edge_cache["to_index"] is not None:
        return  # Cache is fresh

    to_index: Dict[str, List[Dict]] = defaultdict(list)
    from_index: Dict[str, List[Dict]] = defaultdict(list)
    node_map: Dict[str, Dict] = {}

    if nodes:
        for n in nodes:
            node_map[n["id"]] = n

    for edge in edges:
        to_id = edge.get("to")
        from_id = edge.get("from")
        if to_id:
            to_index[to_id].append(edge)
        if from_id:
            from_index[from_id].append(edge)

    _edge_cache["fingerprint"] = fingerprint
    _edge_cache["to_index"] = dict(to_index)
    _edge_cache["from_index"] = dict(from_index)
    _edge_cache["node_map"] = node_map


def resolve_edges(
    all_nodes: List[Dict],
    all_raw_edges: List[Dict]
) -> Tuple[List[Dict], List[Dict]]:
    """
    Resolve all function call edges by matching to_fn names to declared function nodes.

    Handles:
    - Direct function calls: processData() → matches node with fn="processData"
    - Method calls: obj.method() → tries matching fn="method" first, then "obj.method"
    - Cross-file calls: resolves to correct file:line
    - Multiple definitions: flags duplicate_define
    - snake_case ↔ camelCase: Rust's process_order matches JS's processOrder

    Returns:
        (resolved_nodes, resolved_edges)
    """
    # Build lookup: fn_name → list of nodes
    fn_name_to_nodes: Dict[str, List[Dict]] = defaultdict(list)
    for node in all_nodes:
        fn_name_to_nodes[node["fn"]].append(node)

    # Also build an alternate-case index for snake_case ↔ camelCase matching.
    # This is critical for Tauri / fullstack projects where Rust (snake_case)
    # and JS/TS (camelCase) call each other.
    alt_case_index: Dict[str, List[Dict]] = defaultdict(list)
    for node in all_nodes:
        alt_key = _to_alternate_case(node["fn"])
        if alt_key != node["fn"]:  # Only index if conversion produces a different name
            alt_case_index[alt_key].append(node)

    # Also index by file:line for exact matching
    id_to_node: Dict[str, Dict] = {node["id"]: node for node in all_nodes}

    # Resolve edges
    resolved_edges = []
    for edge in all_raw_edges:
        from_id = edge["from"]
        to_fn = edge.get("to_fn", "")
        via_self = edge.get("via_self", False)

        # Try to resolve the target
        target_node = None

        # 1. Direct match: to_fn matches a function name
        if to_fn in fn_name_to_nodes:
            candidates = fn_name_to_nodes[to_fn]

            if len(candidates) == 1:
                target_node = candidates[0]
            else:
                # Multiple definitions — prefer same file, then first definition
                from_file = _extract_file_from_id(from_id)
                same_file_candidates = [c for c in candidates if c.get("file", "") == from_file]

                if same_file_candidates:
                    target_node = same_file_candidates[0]
                else:
                    # Sort by (file, line) for deterministic selection
                    candidates_sorted = sorted(candidates, key=lambda c: (c.get("file", ""), c.get("line", 0)))
                    target_node = candidates_sorted[0]

        # 2. snake_case ↔ camelCase match (Rust ↔ JS interop)
        if not target_node:
            alt_key = _to_alternate_case(to_fn)
            if alt_key in fn_name_to_nodes:
                candidates = fn_name_to_nodes[alt_key]
                # Prefer same-file matches first
                from_file = _extract_file_from_id(from_id)
                same_file_candidates = [c for c in candidates if c.get("file", "") == from_file]
                if same_file_candidates:
                    target_node = same_file_candidates[0]
                else:
                    candidates_sorted = sorted(candidates, key=lambda c: (c.get("file", ""), c.get("line", 0)))
                    target_node = candidates_sorted[0]
            elif to_fn in alt_case_index:
                candidates = alt_case_index[to_fn]
                from_file = _extract_file_from_id(from_id)
                same_file_candidates = [c for c in candidates if c.get("file", "") == from_file]
                if same_file_candidates:
                    target_node = same_file_candidates[0]
                else:
                    candidates_sorted = sorted(candidates, key=lambda c: (c.get("file", ""), c.get("line", 0)))
                    target_node = candidates_sorted[0]

        # 3. Method match: "obj.method" → try just "method"
        if not target_node and '.' in to_fn:
            method_name = to_fn.split('.')[-1]
            if method_name in fn_name_to_nodes:
                candidates = fn_name_to_nodes[method_name]
                if candidates:
                    # Prefer same file
                    from_file = _extract_file_from_id(from_id)
                    same_file = [c for c in candidates if c.get("file", "") == from_file]
                    target_node = same_file[0] if same_file else candidates[0]

        # 4. Pinia store usage: "useXxxStore" → match store node with fn="useXxxStore"
        if not target_node and to_fn.startswith('use') and to_fn.endswith('Store'):
            if to_fn in fn_name_to_nodes:
                candidates = fn_name_to_nodes[to_fn]
                # Prefer pinia_store type nodes
                pinia_nodes = [c for c in candidates if c.get("type") == "pinia_store"]
                if pinia_nodes:
                    target_node = pinia_nodes[0]
                else:
                    from_file = _extract_file_from_id(from_id)
                    same_file = [c for c in candidates if c.get("file", "") == from_file]
                    target_node = same_file[0] if same_file else candidates[0]

        # Build resolved edge
        if target_node:
            resolved_edge = {
                "from": from_id,
                "to": target_node["id"]
            }
            if via_self:
                resolved_edge["via_self"] = True
            resolved_edges.append(resolved_edge)
        else:
            # Unresolved — external or not yet scanned
            resolved_edge = {
                "from": from_id,
                "to_fn": to_fn,
                "resolved": False
            }
            resolved_edges.append(resolved_edge)

    # Compute ref_count from incoming edges
    incoming_count: Dict[str, int] = {node["id"]: 0 for node in all_nodes}

    for edge in resolved_edges:
        to_id = edge.get("to")
        if to_id and to_id in incoming_count:
            incoming_count[to_id] += 1

    # Update nodes with ref_count and status
    for node in all_nodes:
        node["ref_count"] = incoming_count.get(node["id"], 0)
        # v6: Exported functions and React components are NOT dead even with 0 ref_count.
        # Entry points, exports, and components are consumed externally (e.g., JSX <Component/>).
        if node["ref_count"] == 0 and not node.get("exported", False) and not node.get("component", False):
            node["status"] = "dead"
        else:
            node["status"] = "active"

    # Check duplicate_define: same fn name defined MULTIPLE TIMES in the SAME file
    # Same fn name in different files is normal (e.g., Page, Layout, handler)
    # and should NOT be flagged as duplicate.
    # Group by (fn_name, file) to detect true duplicates within a single file.
    _NEXTJS_CONVENTION_NAMES = {
        # Next.js App Router page components
        'Page', 'Layout', 'Loading', 'Error', 'NotFound', 'Template', 'Default',
        # Next.js API route handlers
        'handler', 'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS',
        # Next.js middleware
        'middleware',
    }

    # Clear any existing duplicate_define flags
    for node in all_nodes:
        node.pop("duplicate_define", None)

    # Group by (fn_name, file) for per-file duplicate detection
    fn_file_groups: Dict[Tuple[str, str], List[Dict]] = {}
    for node in all_nodes:
        key = (node.get("fn", ""), node.get("file", ""))
        if key not in fn_file_groups:
            fn_file_groups[key] = []
        fn_file_groups[key].append(node)

    # Flag duplicate_define only when same fn name appears 2+ times in SAME file
    # Skip Next.js convention names entirely — they are never duplicates
    for (fn_name, _file), nodes in fn_file_groups.items():
        if fn_name in _NEXTJS_CONVENTION_NAMES:
            continue
        if len(nodes) > 1:
            sorted_nodes = sorted(nodes, key=lambda n: n.get("line", 0))
            for i, node in enumerate(sorted_nodes):
                if i > 0:
                    node["duplicate_define"] = True

    # Invalidate the edge index cache since we produced new resolved_edges
    _edge_cache["fingerprint"] = None

    return all_nodes, resolved_edges


def get_callers(node_id: str, edges: List[Dict], nodes: Optional[List[Dict]] = None) -> List[Dict]:
    """Get all callers (incoming edges) for a node. Uses cached index for O(1) lookup.
    
    Returns rich caller info with file, line, and fn keys for markdown formatting.
    """
    _build_index(edges, nodes)
    incoming = _edge_cache["to_index"].get(node_id, [])
    node_map = _edge_cache.get("node_map", {})
    
    results = []
    for edge in incoming:
        from_id = edge.get("from", "")
        # Try to resolve caller info from node_map
        caller_node = node_map.get(from_id, {})
        caller = {
            "from": from_id,
            "file": caller_node.get("file", ""),
            "line": caller_node.get("line", ""),
            "fn": caller_node.get("fn", ""),
            "source": caller_node.get("fn", ""),
        }
        # Fallback: parse from_id string to extract file/line/fn
        if not caller["file"] and ":" in from_id:
            parts = from_id.rsplit(":", 2)
            if len(parts) >= 3:
                caller["file"] = parts[0]
                try:
                    caller["line"] = int(parts[1])
                except (ValueError, TypeError):
                    caller["line"] = parts[1]
                caller["fn"] = parts[2]
                caller["source"] = parts[2]
            elif len(parts) == 2:
                caller["file"] = parts[0]
                caller["fn"] = parts[1]
                caller["source"] = parts[1]
        results.append(caller)
    return results


def get_callees(node_id: str, edges: List[Dict], nodes: List[Dict]) -> List[Dict]:
    """Get all callees (outgoing edges) for a node, with their status. Uses cached index for O(1) lookup."""
    _build_index(edges, nodes)
    outgoing = _edge_cache["from_index"].get(node_id, [])
    node_map = _edge_cache["node_map"]

    callees = []
    for edge in outgoing:
        to_id = edge.get("to", "")
        to_fn = edge.get("to_fn", "")

        callee = {}
        if to_id and to_id in node_map:
            callee["to"] = to_id
            callee["fn"] = node_map[to_id]["fn"]
            callee["status"] = node_map[to_id].get("status", "unknown")
        elif to_fn:
            callee["to_fn"] = to_fn
            callee["resolved"] = False
        else:
            continue

        callees.append(callee)

    return callees


# ─── Case Conversion Helpers ────────────────────────────────────

def _to_alternate_case(name: str) -> str:
    """Convert between snake_case and camelCase for cross-language matching.

    This is essential for fullstack projects (e.g., Tauri, WASM) where:
    - Rust uses snake_case: process_order, get_user_data
    - JavaScript/TypeScript uses camelCase: processOrder, getUserData

    Conversion rules:
    - snake_case → camelCase: get_user_data → getUserData
    - camelCase → snake_case: getUserData → get_user_data
    - If the name doesn't match either convention, returns it unchanged.
    """
    if not name:
        return name

    # Preserve leading underscores (e.g. _private_func → _privateFunc)
    leading = ''
    while name.startswith('_'):
        leading += '_'
        name = name[1:]
    if not name:
        return leading  # name was all underscores

    # snake_case → camelCase
    if '_' in name:
        parts = name.split('_')
        # Only convert if it looks like snake_case (lowercase parts)
        if all(p.islower() or p == '' for p in parts if p):
            return leading + parts[0] + ''.join(p.capitalize() for p in parts[1:] if p)
        # Mixed like get_HTTPResponse — keep as-is
        return leading + name

    # camelCase → snake_case
    if name[0].islower() and any(c.isupper() for c in name[1:]):
        result = []
        for c in name:
            if c.isupper():
                result.append('_')
                result.append(c.lower())
            else:
                result.append(c)
        return leading + ''.join(result)

    # No conversion needed
    return leading + name


# ─── Tauri IPC Edge Resolution ───────────────────────────────

def resolve_tauri_ipc_from_apimap(
    nodes: List[Dict],
    edges: List[Dict],
    api_routes: List[Dict]
) -> List[Dict]:
    """Resolve cross-language Tauri IPC edges from API map data.

    In Tauri apps, the frontend calls Rust backend functions via the IPC bridge:
        TypeScript: invoke('commandName') → Rust: #[tauri::command] fn command_name()

    This function creates resolved edges connecting the frontend invoke() call
    to the corresponding Rust handler, making Tauri command handlers appear as
    "active" (called) rather than "dead" in the codebase analysis.

    Args:
        nodes: List of all parsed nodes (both frontend and backend).
        edges: List of existing resolved edges.
        api_routes: API route data from apimap_engine, containing Tauri IPC routes
                    with 'type' == 'tauri_ipc', 'handler' field with command name,
                    and 'invoke_command' field with the invoked command name.

    Returns:
        Updated list of edges with new IPC edges appended.
    """
    if not api_routes:
        return edges

    # Build a lookup: Rust function name → node
    rust_nodes: Dict[str, Dict] = {}
    for node in nodes:
        file_path = node.get("file", "")
        if file_path.endswith('.rs'):
            fn_name = node.get("fn", "")
            # Index by both original name and snake_case version
            rust_nodes[fn_name] = node
            # Also index the camelCase version of the name for matching
            alt = _to_alternate_case(fn_name)
            if alt != fn_name:
                rust_nodes[alt] = node

    # Build a lookup: frontend invoke call → node
    ts_nodes: Dict[str, Dict] = {}
    for node in nodes:
        file_path = node.get("file", "")
        if not file_path.endswith('.rs'):
            fn_name = node.get("fn", "")
            if fn_name:
                ts_nodes[fn_name] = node

    # Find Tauri IPC routes and create edges
    new_edges = []
    for route in api_routes:
        route_type = route.get("type", "")
        if route_type != "tauri_ipc":
            continue

        invoke_cmd = route.get("invoke_command", "") or route.get("handler", "")
        if not invoke_cmd:
            continue

        # Find the frontend node that calls invoke()
        # The invoke call might be in a function like "greet" or "commandName"
        frontend_node = ts_nodes.get(invoke_cmd)

        # Find the Rust handler node
        # Rust uses snake_case: greet → greet, commandName → command_name
        rust_key = _to_alternate_case(invoke_cmd) if '_' not in invoke_cmd else invoke_cmd
        backend_node = rust_nodes.get(invoke_cmd) or rust_nodes.get(rust_key)

        if backend_node:
            # Mark the Rust node as a Tauri command
            backend_node["is_tauri_command"] = True

            # Create an edge from the frontend to the backend
            if frontend_node:
                new_edge = {
                    "from": frontend_node["id"],
                    "to": backend_node["id"],
                    "ipc": True,
                }
            else:
                # No specific frontend function, but the Rust command is still exposed
                # Mark it so it won't appear as dead code
                new_edge = {
                    "from": f"tauri_ipc:{invoke_cmd}",
                    "to": backend_node["id"],
                    "ipc": True,
                }
            new_edges.append(new_edge)

    return edges + new_edges
