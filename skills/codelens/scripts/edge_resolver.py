"""
Edge Resolver for CodeLens
Resolves cross-file function call references.
Builds a complete call graph from all parsed backend data.
"""

from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


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
                from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
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
                from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
                same_file_candidates = [c for c in candidates if c.get("file", "") == from_file]
                if same_file_candidates:
                    target_node = same_file_candidates[0]
                else:
                    candidates_sorted = sorted(candidates, key=lambda c: (c.get("file", ""), c.get("line", 0)))
                    target_node = candidates_sorted[0]
            elif to_fn in alt_case_index:
                candidates = alt_case_index[to_fn]
                from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
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
                    from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
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
                    from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
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

    # Check duplicate_define: same fn name in multiple files
    # Sort nodes within each group by (file, line) for deterministic flagging
    for fn_name, nodes in fn_name_to_nodes.items():
        if len(nodes) > 1:
            sorted_nodes = sorted(nodes, key=lambda n: (n.get("file", ""), n.get("line", 0)))
            for i, node in enumerate(sorted_nodes):
                if i > 0:
                    node["duplicate_define"] = True

    # Invalidate the edge index cache since we produced new resolved_edges
    _edge_cache["fingerprint"] = None

    return all_nodes, resolved_edges


def get_callers(node_id: str, edges: List[Dict]) -> List[Dict]:
    """Get all callers (incoming edges) for a node. Uses cached index for O(1) lookup."""
    _build_index(edges)
    incoming = _edge_cache["to_index"].get(node_id, [])
    return [{"from": edge["from"]} for edge in incoming]


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


# ─── Tauri IPC Cross-Language Edge Resolution ────────────────

def resolve_tauri_ipc_from_apimap(
    nodes: List[Dict],
    edges: List[Dict],
    api_routes: List[Dict]
) -> List[Dict]:
    """Resolve cross-language Tauri IPC edges from API map data.

    In Tauri apps, the frontend calls Rust backend functions via the
    invoke('commandName') IPC bridge. This creates cross-language edges
    that normal same-language resolution cannot find.

    This function matches:
    - Frontend invoke('command_name') calls → Rust #[tauri::command] handlers
    - Uses snake_case ↔ camelCase conversion for name matching

    Args:
        nodes: All parsed backend nodes.
        edges: Currently resolved edges (will be extended).
        api_routes: API route data from apimap_engine.

    Returns:
        Updated edges list with new Tauri IPC edges appended.
    """
    if not api_routes:
        return edges

    # Build index of Rust tauri::command nodes by name
    tauri_nodes: Dict[str, Dict] = {}
    for node in nodes:
        if node.get("is_tauri_command"):
            fn_name = node.get("fn", "")
            tauri_nodes[fn_name] = node
            # Also index by alternate case
            alt = _to_alternate_case(fn_name)
            if alt != fn_name:
                tauri_nodes[alt] = node

    # Build index of all backend nodes for frontend → backend matching
    backend_fn_index: Dict[str, List[Dict]] = {}
    for node in nodes:
        fn_name = node.get("fn", "")
        if fn_name:
            backend_fn_index.setdefault(fn_name, []).append(node)
            alt = _to_alternate_case(fn_name)
            if alt != fn_name:
                backend_fn_index.setdefault(alt, []).append(node)

    new_edges = []
    for route in api_routes:
        handler = route.get("handler", "")
        method = route.get("method", "")
        path = route.get("path", "")

        # Match handler name to a backend node
        target_node = None

        # Try direct match first
        if handler in backend_fn_index:
            candidates = backend_fn_index[handler]
            target_node = candidates[0]

        # Try tauri command nodes
        if not target_node and handler in tauri_nodes:
            target_node = tauri_nodes[handler]

        # Try stripping common prefixes
        if not target_node:
            for prefix in ("cmd_", "handle_", "invoke_"):
                if handler.startswith(prefix):
                    stripped = handler[len(prefix):]
                    if stripped in backend_fn_index:
                        target_node = backend_fn_index[stripped][0]
                        break

        if target_node:
            # Create a synthetic source node for the frontend invoke() call
            source_id = f"tauri_ipc:{method}:{path}"
            new_edges.append({
                "from": source_id,
                "to": target_node["id"],
                "edge_type": "tauri_ipc",
                "invoke_name": handler,
            })

    # Also scan for invoke() patterns in edges that weren't resolved
    for edge in edges:
        if edge.get("resolved") is False:
            to_fn = edge.get("to_fn", "")
            # Check if this looks like a Tauri invoke
            if to_fn in tauri_nodes:
                edge["to"] = tauri_nodes[to_fn]["id"]
                edge["resolved"] = True
                edge["edge_type"] = "tauri_ipc"
                del edge["to_fn"]
            else:
                alt = _to_alternate_case(to_fn)
                if alt in tauri_nodes:
                    edge["to"] = tauri_nodes[alt]["id"]
                    edge["resolved"] = True
                    edge["edge_type"] = "tauri_ipc"
                    del edge["to_fn"]

    edges.extend(new_edges)
    return edges
