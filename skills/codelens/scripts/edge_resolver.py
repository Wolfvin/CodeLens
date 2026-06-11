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

    In Tauri apps, the frontend (JS/TS) calls Rust backend functions via
    the IPC bridge using invoke('commandName'). This function creates
    cross-language edges connecting those invoke() calls to their
    Rust #[tauri::command] handler nodes.

    Args:
        nodes: All resolved backend nodes (including Rust nodes).
        edges: All resolved edges so far.
        api_routes: API routes from apimap_engine, each with 'handler' info.

    Returns:
        Updated edges list with new IPC edges appended.
    """
    if not api_routes:
        return edges

    # Build lookup: Rust tauri_command nodes by command name
    # Tauri command nodes have is_tauri_command=True and fn=command_name
    tauri_cmd_nodes: Dict[str, Dict] = {}
    for node in nodes:
        if node.get("is_tauri_command"):
            fn = node.get("fn", "")
            tauri_cmd_nodes[fn] = node
            # Also index by snake_case version for camelCase matching
            alt = _to_alternate_case(fn)
            if alt != fn:
                tauri_cmd_nodes[alt] = node

    # Build lookup: JS/TS invoke() call nodes by invoked command name
    # Invoke nodes have type="tauri_invoke" and the command name in fn or invoke_cmd
    invoke_nodes: Dict[str, Dict] = {}
    for node in nodes:
        if node.get("type") == "tauri_invoke":
            cmd = node.get("invoke_cmd", node.get("fn", ""))
            if cmd:
                invoke_nodes[cmd] = node
                alt = _to_alternate_case(cmd)
                if alt != cmd:
                    invoke_nodes[alt] = node

    # Also scan edges for unresolved invoke() calls
    # These show up as edges with to_fn matching an invoke pattern
    invoke_edges: Dict[str, str] = {}  # command_name → from_id
    for edge in edges:
        to_fn = edge.get("to_fn", "")
        if not edge.get("resolved") and to_fn:
            # Check if it looks like a Tauri invoke target
            invoke_edges[to_fn] = edge.get("from", "")
            alt = _to_alternate_case(to_fn)
            if alt != to_fn:
                invoke_edges[alt] = edge.get("from", "")

    new_edges = []

    # 1. Connect JS invoke() nodes → Rust tauri_command nodes
    for cmd_name, invoke_node in invoke_nodes.items():
        if cmd_name in tauri_cmd_nodes:
            rust_node = tauri_cmd_nodes[cmd_name]
            ipc_edge = {
                "from": invoke_node["id"],
                "to": rust_node["id"],
                "type": "tauri_ipc",
                "cross_language": True,
            }
            new_edges.append(ipc_edge)

    # 2. Connect unresolved invoke edges → Rust tauri_command nodes
    for cmd_name, from_id in invoke_edges.items():
        if cmd_name in tauri_cmd_nodes:
            rust_node = tauri_cmd_nodes[cmd_name]
            # Avoid duplicate edges
            existing = any(
                e.get("from") == from_id and e.get("to") == rust_node["id"]
                for e in edges
            )
            if not existing:
                ipc_edge = {
                    "from": from_id,
                    "to": rust_node["id"],
                    "type": "tauri_ipc",
                    "cross_language": True,
                }
                new_edges.append(ipc_edge)

    # 3. Connect from API route handlers to Tauri command nodes
    for route in api_routes:
        handler = route.get("handler", "")
        if not handler:
            continue
        # Try to find a matching Tauri command node
        alt_handler = _to_alternate_case(handler)
        for name in (handler, alt_handler):
            if name in tauri_cmd_nodes:
                rust_node = tauri_cmd_nodes[name]
                # Find the API handler node (JS/TS side)
                for node in nodes:
                    if node.get("fn") == handler and node.get("type") in ("api_handler", "function"):
                        existing = any(
                            e.get("from") == node["id"] and e.get("to") == rust_node["id"]
                            for e in edges
                        )
                        if not existing:
                            ipc_edge = {
                                "from": node["id"],
                                "to": rust_node["id"],
                                "type": "tauri_ipc",
                                "cross_language": True,
                            }
                            new_edges.append(ipc_edge)
                        break

    # Invalidate cache since we're modifying edges
    _edge_cache["fingerprint"] = None

    return edges + new_edges
