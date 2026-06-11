"""
Edge Resolver for CodeLens
Resolves cross-file function call references.
Builds a complete call graph from all parsed backend data.

v5.10 improvements:
- Self-edge prevention: When a function foo() calls obj.foo(), the resolver
  now avoids creating a self-referencing edge by checking call_object context.
  Previously, window.open_devtools() inside fn open_devtools() would create
  a false self-edge, leading to spurious "recursive call" reports.
- Tauri IPC cross-language resolution: Resolves TypeScript invoke('commandName')
  calls to the corresponding Rust #[tauri::command] handler functions. This
  ensures Tauri command handlers are correctly marked as "active" instead of
  "dead", and the full IPC call graph is visible.
- IPC name index: Indexes Rust Tauri commands by their ipc_name (camelCase)
  to enable direct matching with invoke() calls from the frontend.
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


def _compute_fingerprint(edges: List[Dict]) -> str:
    """Compute a content-based fingerprint for the edges list.
    Uses length + first/last edge IDs to detect changes efficiently.
    This avoids the id() pitfall where Python reuses memory addresses."""
    if not edges:
        return "empty"
    first = edges[0]
    last = edges[-1]
    return f"len={len(edges)}|first_from={first.get('from','')}|first_to={first.get('to','')}|last_from={last.get('from','')}|last_to={last.get('to','')}"


def _build_index(edges: List[Dict], nodes: Optional[List[Dict]] = None) -> None:
    """Build or rebuild the caller/callee index if the edges list changed."""
    fingerprint = _compute_fingerprint(edges)
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
    - Self-edge prevention: avoids creating edges where from == to when call_object
      context indicates the call is on a different object (e.g., window.open_devtools()
      inside fn open_devtools())
    - Tauri IPC resolution: TypeScript invoke('cmdName') → Rust #[tauri::command] fn

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

    # Build IPC name index for Tauri command resolution.
    # Maps ipc_name (camelCase) → list of Rust #[tauri::command] nodes.
    # This enables resolving TypeScript invoke('getProfiles') to Rust fn get_profiles.
    ipc_name_to_nodes: Dict[str, List[Dict]] = defaultdict(list)
    for node in all_nodes:
        ipc_name = node.get("ipc_name")
        if ipc_name and node.get("is_tauri_command"):
            ipc_name_to_nodes[ipc_name].append(node)

    # Also index by file:line for exact matching
    id_to_node: Dict[str, Dict] = {node["id"]: node for node in all_nodes}

    # Resolve edges
    resolved_edges = []
    for edge in all_raw_edges:
        from_id = edge["from"]
        to_fn = edge.get("to_fn", "")
        via_self = edge.get("via_self", False)
        call_object = edge.get("call_object")
        is_ipc_call = edge.get("is_ipc_call", False)

        # Try to resolve the target
        target_node = None

        # ─── Tauri IPC direct resolution ──────────────────────────────
        # When the parser detected an invoke('cmdName') call and marked it
        # with is_ipc_call=True, the to_fn is the actual Tauri command name
        # (camelCase). Try to match it directly against the ipc_name index
        # or via case conversion against Rust function names.
        if is_ipc_call:
            # Try IPC name index first (camelCase → Rust #[tauri::command])
            if to_fn in ipc_name_to_nodes:
                candidates = ipc_name_to_nodes[to_fn]
                if candidates:
                    target_node = candidates[0]

            # Try snake_case conversion (in case parser gave us Rust name)
            if not target_node:
                alt_key = _to_alternate_case(to_fn)
                if alt_key in fn_name_to_nodes:
                    # Prefer Tauri command nodes
                    candidates = fn_name_to_nodes[alt_key]
                    tauri_candidates = [c for c in candidates if c.get("is_tauri_command")]
                    if tauri_candidates:
                        target_node = tauri_candidates[0]
                    elif candidates:
                        target_node = candidates[0]

            # Try direct fn name match (in case parser gave us snake_case Rust name)
            if not target_node and to_fn in fn_name_to_nodes:
                candidates = fn_name_to_nodes[to_fn]
                tauri_candidates = [c for c in candidates if c.get("is_tauri_command")]
                if tauri_candidates:
                    target_node = tauri_candidates[0]

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

        # ─── Self-edge prevention ───────────────────────────────
        # When a function foo() calls obj.foo() or Module::foo(), the resolver
        # might match it back to itself. This creates false self-edges that lead
        # to spurious "recursive function call" reports in the circular engine.
        #
        # We prevent this by checking:
        # 1. If the resolved target is the SAME node as the source (from_id == target_id)
        # 2. AND the edge has call_object context (meaning it's a method call on
        #    a different object, like window.open_devtools() or feat::restart_app())
        # 3. AND there are other candidates available (try them instead)
        #
        # If call_object is set and the only match is self, we mark the edge as
        # unresolved rather than creating a false self-edge.
        if target_node and target_node["id"] == from_id:
            if call_object and not via_self:
                # This is a method call on a DIFFERENT object (e.g., window.open_devtools()
                # inside fn open_devtools). Try to find a different candidate.
                candidates = fn_name_to_nodes.get(to_fn, [])
                other_candidates = [c for c in candidates if c["id"] != from_id]
                if other_candidates:
                    # Prefer same-file, then first
                    from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
                    same_file = [c for c in other_candidates if c.get("file", "") == from_file]
                    target_node = same_file[0] if same_file else other_candidates[0]
                else:
                    # No other candidates — this is likely a method on an external type
                    # (e.g., WebviewWindow::open_devtools). Mark as unresolved.
                    target_node = None

        # Build resolved edge
        if target_node:
            resolved_edge = {
                "from": from_id,
                "to": target_node["id"]
            }
            if via_self:
                resolved_edge["via_self"] = True
            # Mark Tauri IPC bridge edges for visibility in context/trace
            if is_ipc_call:
                resolved_edge["ipc_bridge"] = True
            resolved_edges.append(resolved_edge)
        else:
            # Unresolved — external or not yet scanned
            resolved_edge = {
                "from": from_id,
                "to_fn": to_fn,
                "resolved": False
            }
            resolved_edges.append(resolved_edge)

    # ─── Tauri IPC Cross-Language Edge Resolution ────────────────
    # After resolving same-language edges, add cross-language edges
    # for Tauri IPC: TypeScript invoke('commandName') → Rust #[tauri::command]
    #
    # This is essential for Tauri apps where the frontend calls Rust commands
    # via the IPC bridge. Without these edges, Rust command handlers appear
    # "dead" because no Rust code calls them directly.
    resolved_edges = _resolve_tauri_ipc_edges(all_nodes, resolved_edges, ipc_name_to_nodes)

    # Compute ref_count from incoming edges
    incoming_count: Dict[str, int] = {node["id"]: 0 for node in all_nodes}

    for edge in resolved_edges:
        to_id = edge.get("to")
        if to_id and to_id in incoming_count:
            incoming_count[to_id] += 1

    # Update nodes with ref_count and status
    for node in all_nodes:
        node["ref_count"] = incoming_count.get(node["id"], 0)
        # Tauri IPC commands are always "active" if they have invoke() callers
        # from the frontend, even if no Rust code calls them directly.
        if node.get("is_tauri_command") and node["ref_count"] == 0:
            # Check if there are any IPC edges pointing to this node
            node["status"] = "ipc_exposed"  # Exposed via IPC but not called yet
        else:
            node["status"] = "dead" if node["ref_count"] == 0 else "active"

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


def _resolve_tauri_ipc_edges(
    all_nodes: List[Dict],
    resolved_edges: List[Dict],
    ipc_name_to_nodes: Dict[str, List[Dict]]
) -> List[Dict]:
    """Add cross-language edges for Tauri IPC calls.

    Scans all backend nodes for invoke() call patterns and creates edges
    from the TypeScript caller to the Rust #[tauri::command] handler.

    This bridges the gap between the two languages that the standard
    edge resolution cannot handle, since invoke('getProfiles') in TS
    and fn get_profiles() in Rust are in completely different files
    with different naming conventions.

    v6.2 improvement: Also processes edges already marked with ipc_call=True
    from the TSX parser (which extracts invoke('commandName') directly).
    This makes IPC resolution more reliable because the TSX parser already
    identified the command name string literal.
    """
    ipc_edges_added = 0

    # Build node lookup by id for fast access
    node_by_id: Dict[str, Dict] = {n["id"]: n for n in all_nodes}

    # ─── Pass 1: Process edges with ipc_call=True from TSX parser ─────
    # The TSX parser now extracts invoke('commandName') calls and creates
    # edges with to_fn=commandName and ipc_call=True. We resolve these
    # directly against the IPC name index.
    for edge in resolved_edges:
        if not edge.get("ipc_call"):
            continue

        to_fn = edge.get("to_fn", "")
        if not to_fn or to_fn == "invoke":
            # Dynamic invoke() without a string literal — try regex scan
            continue

        target_node = _match_ipc_command(to_fn, ipc_name_to_nodes, node_by_id)

        if target_node:
            edge["to"] = target_node["id"]
            edge["resolved"] = True
            edge["ipc_bridge"] = True
            if "to_fn" in edge:
                del edge["to_fn"]
            ipc_edges_added += 1
        else:
            # IPC command not found in Rust — still mark as IPC bridge
            # but keep as unresolved. This could indicate a dynamically
            # registered command or a plugin command.
            edge["ipc_bridge"] = True
            edge["resolved"] = False
            edge["unresolved_reason"] = "ipc_command_not_found_in_rust"

    # ─── Pass 2: Try unresolved edges (legacy path) ────────────────
    # For edges that weren't tagged by the TSX parser (e.g., JS backend files)
    # we fall back to the original strategy of matching unresolved edges
    # against IPC command names.
    from_id_to_unresolved: Dict[str, List[Dict]] = defaultdict(list)
    for edge in resolved_edges:
        if edge.get("resolved") is False and not edge.get("ipc_call"):
            from_id_to_unresolved[edge["from"]].append(edge)

    # For each unresolved edge, try to match against IPC command names
    for from_id, unresolved in from_id_to_unresolved.items():
        from_node = node_by_id.get(from_id)
        if not from_node:
            continue

        # Only process TS/JS nodes (frontend/backend JS files)
        from_file = from_node.get("file", "")
        if not (from_file.endswith('.ts') or from_file.endswith('.tsx') or
                from_file.endswith('.js') or from_file.endswith('.jsx')):
            continue

        for edge in unresolved:
            to_fn = edge.get("to_fn", "")
            if not to_fn:
                continue

            target_node = _match_ipc_command(to_fn, ipc_name_to_nodes, node_by_id)

            if target_node:
                # Replace the unresolved edge with a resolved IPC edge
                edge["to"] = target_node["id"]
                edge["resolved"] = True
                edge["ipc_bridge"] = True  # Mark as Tauri IPC bridge edge
                del edge["to_fn"]
                ipc_edges_added += 1

    return resolved_edges


def _match_ipc_command(
    name: str,
    ipc_name_to_nodes: Dict[str, List[Dict]],
    node_by_id: Dict[str, Dict]
) -> Optional[Dict]:
    """Try to match a name against Tauri IPC command nodes.

    Matching strategy (in order of priority):
    1. Direct match on ipc_name (camelCase, e.g., 'getProfiles')
    2. Case conversion: snake_case ↔ camelCase
    3. Direct match on fn_name (for Rust snake_case names passed directly)

    Returns the best matching node, or None if no match found.
    """
    # 1. Direct match on ipc_name (camelCase)
    if name in ipc_name_to_nodes:
        candidates = ipc_name_to_nodes[name]
        return candidates[0]

    # 2. Case conversion: try alternate case
    alt_key = _to_alternate_case(name)
    if alt_key in ipc_name_to_nodes:
        candidates = ipc_name_to_nodes[alt_key]
        return candidates[0]

    # 3. Try matching against Rust fn names directly
    # This handles cases where the TSX parser extracted the snake_case name
    for ipc_name, candidates in ipc_name_to_nodes.items():
        for candidate in candidates:
            if candidate.get("fn") == name or candidate.get("fn") == alt_key:
                return candidate

    return None


def resolve_tauri_ipc_from_apimap(
    all_nodes: List[Dict],
    resolved_edges: List[Dict],
    api_routes: List[Dict]
) -> List[Dict]:
    """Add Tauri IPC edges from the API map data.

    This is called by the scan command after the API map is built,
    to create cross-language edges from invoke() call sites (detected
    in TypeScript) to #[tauri::command] Rust handlers.

    Args:
        all_nodes: All backend registry nodes
        resolved_edges: Current resolved edges
        api_routes: Routes from api-map engine (includes IPC_CALL entries)

    Returns:
        Updated resolved_edges with IPC bridge edges added
    """
    if not api_routes:
        return resolved_edges

    # Build node lookup by (file, line) for precise matching
    node_by_file_line: Dict[Tuple[str, int], Dict] = {}
    for node in all_nodes:
        key = (node.get("file", ""), node.get("line", 0))
        node_by_file_line[key] = node

    # Build IPC name → Rust handler node index
    ipc_name_to_rust_node: Dict[str, Dict] = {}
    for node in all_nodes:
        ipc_name = node.get("ipc_name")
        if ipc_name and node.get("is_tauri_command"):
            ipc_name_to_rust_node[ipc_name] = node

    # Also index Rust fn name directly
    fn_name_to_rust_tauri: Dict[str, Dict] = {}
    for node in all_nodes:
        if node.get("is_tauri_command"):
            fn_name_to_rust_tauri[node["fn"]] = node

    # Find all IPC_CALL routes (from TypeScript invoke() calls)
    # and create edges to the Rust handler
    existing_edge_keys = set()
    for edge in resolved_edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        if from_id and to_id:
            existing_edge_keys.add((from_id, to_id))

    for route in api_routes:
        # Only process IPC_CALL routes (from TypeScript invoke() calls).
        # Do NOT process IPC routes (from Rust #[tauri::command] declarations)
        # because those are the target handlers, not the callers.
        if route.get("method") != "IPC_CALL":
            continue

        handler_name = route.get("handler_name", "")
        handler_name_ipc = route.get("handler_name_ipc", handler_name)
        route_file = route.get("file", "")
        route_line = route.get("line", 0)

        # Find the TypeScript caller node (the function containing the invoke() call)
        caller_node = node_by_file_line.get((route_file, route_line))

        # If we can't find exact line match, find the nearest function in that file
        if not caller_node:
            # Find the closest function node in the same file
            best_node = None
            best_dist = float('inf')
            for node in all_nodes:
                if node.get("file") == route_file:
                    dist = abs(node.get("line", 0) - route_line)
                    if dist < best_dist and node.get("line", 0) <= route_line:
                        best_dist = dist
                        best_node = node
            caller_node = best_node

        if not caller_node:
            continue

        # Find the Rust handler node
        rust_node = None

        # Try IPC name first (camelCase)
        if handler_name_ipc in ipc_name_to_rust_node:
            rust_node = ipc_name_to_rust_node[handler_name_ipc]
        # Try handler name (might be snake_case Rust name)
        elif handler_name in fn_name_to_rust_tauri:
            rust_node = fn_name_to_rust_tauri[handler_name]
        # Try case conversion
        else:
            alt_key = _to_alternate_case(handler_name)
            if alt_key in fn_name_to_rust_tauri:
                rust_node = fn_name_to_rust_tauri[alt_key]

        if not rust_node:
            continue

        # Create the IPC bridge edge if it doesn't already exist
        edge_key = (caller_node["id"], rust_node["id"])
        if edge_key not in existing_edge_keys:
            resolved_edges.append({
                "from": caller_node["id"],
                "to": rust_node["id"],
                "ipc_bridge": True
            })
            existing_edge_keys.add(edge_key)

    return resolved_edges


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
            if edge.get("ipc_bridge"):
                callee["ipc_bridge"] = True
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

    # snake_case → camelCase
    if '_' in name:
        parts = name.split('_')
        # Only convert if it looks like snake_case (lowercase parts)
        if all(p.islower() or p == '' for p in parts if p):
            return parts[0] + ''.join(p.capitalize() for p in parts[1:] if p)
        # Mixed like get_HTTPResponse — keep as-is
        return name

    # camelCase → snake_case
    if name[0].islower() and any(c.isupper() for c in name[1:]):
        result = []
        for c in name:
            if c.isupper():
                result.append('_')
                result.append(c.lower())
            else:
                result.append(c)
        return ''.join(result)

    # No conversion needed
    return name
