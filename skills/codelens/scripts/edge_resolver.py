"""
Edge Resolver for CodeLens
Resolves cross-file function call references.
Builds a complete call graph from all parsed backend data.
"""

from typing import Dict, List, Any, Optional, Tuple


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

    Returns:
        (resolved_nodes, resolved_edges)
    """
    # Build lookup: fn_name → list of nodes
    fn_name_to_nodes: Dict[str, List[Dict]] = {}
    for node in all_nodes:
        fn_name = node["fn"]
        if fn_name not in fn_name_to_nodes:
            fn_name_to_nodes[fn_name] = []
        fn_name_to_nodes[fn_name].append(node)

    # Also index by file:line for exact matching
    id_to_node: Dict[str, Dict] = {}
    for node in all_nodes:
        id_to_node[node["id"]] = node

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
                    target_node = candidates[0]

        # 2. Method match: "obj.method" → try just "method"
        if not target_node and '.' in to_fn:
            method_name = to_fn.split('.')[-1]
            if method_name in fn_name_to_nodes:
                candidates = fn_name_to_nodes[method_name]
                if candidates:
                    target_node = candidates[0]

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
    incoming_count: Dict[str, int] = {}
    for node in all_nodes:
        incoming_count[node["id"]] = 0

    for edge in resolved_edges:
        to_id = edge.get("to")
        if to_id and to_id in incoming_count:
            incoming_count[to_id] += 1

    # Update nodes with ref_count and status
    for node in all_nodes:
        node["ref_count"] = incoming_count.get(node["id"], 0)
        node["status"] = "dead" if node["ref_count"] == 0 else "active"

    # Check duplicate_define: same fn name in multiple files
    for fn_name, nodes in fn_name_to_nodes.items():
        if len(nodes) > 1:
            # Mark all but the first
            for i, node in enumerate(nodes):
                if i > 0:
                    node["duplicate_define"] = True

    return all_nodes, resolved_edges


def get_callers(node_id: str, edges: List[Dict]) -> List[Dict]:
    """Get all callers (incoming edges) for a node."""
    callers = []
    for edge in edges:
        if edge.get("to") == node_id:
            callers.append({"from": edge["from"]})
    return callers


def get_callees(node_id: str, edges: List[Dict], nodes: List[Dict]) -> List[Dict]:
    """Get all callees (outgoing edges) for a node, with their status."""
    # Build node lookup
    node_map = {n["id"]: n for n in nodes}

    callees = []
    for edge in edges:
        if edge.get("from") == node_id:
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
