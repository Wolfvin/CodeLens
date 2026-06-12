"""
Trace Engine for CodeLens
Deep call chain tracing — follows the graph up (callers) and down (callees)
to produce full impact chains for root cause analysis and change planning.

v6.1: Uses edge_resolver's cached index for O(1) lookups instead of building
adjacency lists from scratch. Adds max_results cap to prevent timeout on
massive codebases (127K+ nodes, 495K+ edges).
"""

import os
from collections import deque
from typing import Dict, List, Any, Optional, Set, Tuple

# Performance limit: max chain entries to return (prevents timeout on huge repos)
MAX_CHAIN_RESULTS = 500


def trace_symbol(
    name: str,
    workspace: str,
    direction: str = "up",
    max_depth: int = 10,
    domain: str = "auto",
    max_results: int = MAX_CHAIN_RESULTS
) -> Dict[str, Any]:
    """
    Trace a symbol's call chain deeply (BFS traversal).

    Args:
        name: Symbol name to trace from
        workspace: Absolute path to workspace
        direction: "up" (callers/who uses this), "down" (callees/what this uses), "both"
        max_depth: Maximum traversal depth (default 10)
        domain: "frontend", "backend", or "auto"
        max_results: Max chain entries to return (default 500, prevents timeout)

    Returns:
        Dict with chains, tree representation, and stats
    """
    workspace = os.path.abspath(workspace)
    chains = {"up": [], "down": []}
    tree = {"root": name, "children": []}

    # ─── Backend Tracing ────────────────────────────────
    if domain in ("backend", "auto"):
        from registry import load_backend_registry
        from edge_resolver import get_callers, get_callees
        backend = load_backend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])

        # Build lookup maps (much faster than iterating all edges)
        node_by_id: Dict[str, Dict] = {}
        node_by_fn: Dict[str, List[Dict]] = {}

        for node in nodes:
            nid = node["id"]
            node_by_id[nid] = node
            fn = node["fn"]
            if fn not in node_by_fn:
                node_by_fn[fn] = []
            node_by_fn[fn].append(node)

        # Find starting node(s) — case-insensitive + fuzzy matching
        start_nodes = node_by_fn.get(name, [])

        if not start_nodes:
            # Case-insensitive exact match
            name_lower = name.lower()
            for fn_key, fn_nodes in node_by_fn.items():
                if fn_key.lower() == name_lower:
                    start_nodes.extend(fn_nodes)
                    break

        if not start_nodes:
            # Case-insensitive substring match
            name_lower = name.lower()
            for node in nodes:
                fn_lower = node.get("fn", "").lower()
                if name_lower in fn_lower or name in node.get("id", ""):
                    start_nodes.append(node)

        for start_node in start_nodes:
            start_id = start_node["id"]

            # Trace UP (callers) — uses edge_resolver's cached index
            if direction in ("up", "both"):
                up_chain = _bfs_trace_indexed(
                    start_id, edges, nodes, node_by_id,
                    max_depth, "caller", max_results - len(chains["up"])
                )
                chains["up"].extend(up_chain)

            # Trace DOWN (callees) — uses edge_resolver's cached index
            if direction in ("down", "both"):
                down_chain = _bfs_trace_indexed(
                    start_id, edges, nodes, node_by_id,
                    max_depth, "callee", max_results - len(chains["down"])
                )
                chains["down"].extend(down_chain)

        # Build tree from chains
        if start_nodes:
            tree = _build_tree(name, start_nodes, chains, node_by_id, direction)

    # ─── Frontend Tracing ───────────────────────────────
    if domain in ("frontend", "auto"):
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)

        # For frontend, "tracing" means following class/id references
        for cls in frontend.get("classes", []):
            if cls["name"] == name:
                frontend_chain = _trace_frontend_class(cls)
                if direction in ("up", "both"):
                    chains["up"].extend(frontend_chain["used_by"])
                if direction in ("down", "both"):
                    chains["down"].extend(frontend_chain["defines"])

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == name:
                frontend_chain = _trace_frontend_id(id_entry)
                if direction in ("up", "both"):
                    chains["up"].extend(frontend_chain["used_by"])
                if direction in ("down", "both"):
                    chains["down"].extend(frontend_chain["defines"])

    # Compute stats
    total_up = len(chains["up"])
    total_down = len(chains["down"])
    affected_files = set()
    for chain in chains["up"] + chains["down"]:
        if "file" in chain:
            affected_files.add(chain["file"])
        if "path" in chain:
            # path can be a chain like "file:line → file:line", extract only file paths
            path_val = chain["path"]
            if " → " in path_val:
                # Extract individual file paths from chain notation
                for segment in path_val.split(" → "):
                    # Strip line number: "packages/foo/bar.ts:123" → "packages/foo/bar.ts"
                    if ":" in segment:
                        file_part = segment.rsplit(":", 1)[0]
                        affected_files.add(file_part)
                    else:
                        affected_files.add(segment)
            else:
                # Single file path, possibly with line number
                if ":" in path_val:
                    affected_files.add(path_val.rsplit(":", 1)[0])
                else:
                    affected_files.add(path_val)

    result = {
        "status": "ok",
        "symbol": name,
        "workspace": workspace,
        "direction": direction,
        "max_depth": max_depth,
        "chains": chains,
        "tree": tree,
        "stats": {
            "callers_found": total_up,
            "callees_found": total_down,
            "affected_files": len(affected_files),
            "affected_file_list": sorted(affected_files)
        }
    }

    if total_up + total_down >= max_results:
        result["truncated"] = True
        result["truncation_note"] = f"Results capped at {max_results}. Use --max-results to increase."

    return result


def _bfs_trace_indexed(
    start_id: str,
    edges: List[Dict],
    nodes: List[Dict],
    node_by_id: Dict[str, Dict],
    max_depth: int,
    direction_label: str,
    max_results: int = MAX_CHAIN_RESULTS
) -> List[Dict]:
    """
    BFS traversal using edge_resolver's cached index for O(1) lookups.

    Instead of building adjacency lists from scratch (O(n) where n = 495K edges),
    this uses get_callers/get_callees which leverage the pre-built index.

    Args:
        start_id: Node ID to start from
        edges: List of all edges (passed to edge_resolver for indexed lookup)
        nodes: List of all nodes (passed to edge_resolver for indexed lookup)
        node_by_id: Lookup map for node by ID
        max_depth: Maximum BFS depth
        direction_label: "caller" (trace up) or "callee" (trace down)
        max_results: Max entries to return (prevents timeout)
    """
    from edge_resolver import get_callers, get_callees

    chain = []
    visited: Set[str] = set()
    reported_cycles: Set[str] = set()
    queue = deque()

    # Start node
    if start_id in node_by_id:
        start_node = node_by_id[start_id]
        chain.append({
            "depth": 0,
            "direction": direction_label,
            "node_id": start_id,
            "fn": start_node.get("fn", ""),
            "file": start_node.get("file", ""),
            "line": start_node.get("line", 0),
            "path": f"{start_id}"
        })

    visited.add(start_id)
    queue.append((start_id, 1, start_id))

    while queue:
        current_id, depth, path = queue.popleft()

        if depth > max_depth:
            continue

        if len(chain) >= max_results:
            break

        # Use edge_resolver's cached index for O(1) lookup
        if direction_label == "caller":
            neighbors_raw = get_callers(current_id, edges, nodes)
            neighbors = [{"node_id": n["from"]} for n in neighbors_raw]
        else:
            neighbors_raw = get_callees(current_id, edges, nodes)
            neighbors = []
            for n in neighbors_raw:
                if n.get("resolved", True) is not False:
                    neighbors.append({"node_id": n.get("to", ""), "fn": n.get("fn", "")})
                else:
                    neighbors.append({"node_id": "", "to_fn": n.get("to_fn", "unknown"), "resolved": False})

        for neighbor in neighbors:
            if len(chain) >= max_results:
                break

            neighbor_id = neighbor.get("node_id", "")

            # Skip empty/unresolved neighbor IDs for callers
            if not neighbor_id:
                if neighbor.get("resolved") is False:
                    # Unresolved target
                    to_fn = neighbor.get("to_fn", "unknown")
                    chain.append({
                        "depth": depth,
                        "direction": direction_label,
                        "node_id": "unresolved",
                        "fn": to_fn,
                        "resolved": False,
                        "path": f"{path} → {to_fn}(unresolved)"
                    })
                continue

            # Skip self-edges (recursion is not a meaningful trace)
            if neighbor_id == current_id:
                continue

            if neighbor_id in visited:
                # Already visited — record as cyclic reference
                # Skip trivial self-loops back to start at depth 1
                if neighbor_id == start_id and depth <= 1:
                    continue
                cycle_key = f"{neighbor_id}@{depth}"
                if cycle_key in reported_cycles:
                    continue
                reported_cycles.add(cycle_key)
                if neighbor_id in node_by_id:
                    n = node_by_id[neighbor_id]
                    chain.append({
                        "depth": depth,
                        "direction": direction_label,
                        "node_id": neighbor_id,
                        "fn": n.get("fn", ""),
                        "file": n.get("file", ""),
                        "line": n.get("line", 0),
                        "path": f"{path} → {neighbor_id}",
                        "cyclic": True
                    })
                continue

            visited.add(neighbor_id)

            if neighbor_id in node_by_id:
                n = node_by_id[neighbor_id]
                chain_entry = {
                    "depth": depth,
                    "direction": direction_label,
                    "node_id": neighbor_id,
                    "fn": n.get("fn", ""),
                    "file": n.get("file", ""),
                    "line": n.get("line", 0),
                    "path": f"{path} → {neighbor_id}",
                    "status": n.get("status", "active"),
                    "async": n.get("async", False)
                }
                if n.get("impl_for"):
                    chain_entry["impl_for"] = n["impl_for"]
                if n.get("component"):
                    chain_entry["component"] = True
                chain.append(chain_entry)

                queue.append((neighbor_id, depth + 1, f"{path} → {neighbor_id}"))
            else:
                # Unresolved target
                to_fn = neighbor.get("to_fn", "unknown")
                chain.append({
                    "depth": depth,
                    "direction": direction_label,
                    "node_id": neighbor_id or "unresolved",
                    "fn": to_fn,
                    "resolved": False,
                    "path": f"{path} → {to_fn}(unresolved)"
                })

    return chain


def _trace_frontend_class(cls: Dict) -> Dict[str, List[Dict]]:
    """Trace a frontend class's definition and usage chain."""
    defines = []
    used_by = []

    # CSS definitions (where it's defined)
    for css_ref in cls.get("css", []):
        defines.append({
            "depth": 0,
            "direction": "define",
            "type": "css_definition",
            "fn": cls["name"],
            "path": css_ref.get("path", ""),
            "line": css_ref.get("line", 0),
            "flag": css_ref.get("flag")
        })

    # JS/TSX usage (who uses it)
    for js_ref in cls.get("js", []):
        used_by.append({
            "depth": 1,
            "direction": "caller",
            "type": "js_usage",
            "fn": cls["name"],
            "path": js_ref.get("path", ""),
            "line": js_ref.get("line", 0),
            "source": js_ref.get("source")
        })

    return {"defines": defines, "used_by": used_by}


def _trace_frontend_id(id_entry: Dict) -> Dict[str, List[Dict]]:
    """Trace a frontend ID's definition and usage chain."""
    defines = []
    used_by = []

    # HTML definitions
    for html_ref in id_entry.get("defined_in_html", []):
        defines.append({
            "depth": 0,
            "direction": "define",
            "type": "html_definition",
            "fn": id_entry["name"],
            "path": html_ref.get("path", ""),
            "line": html_ref.get("line", 0)
        })

    # CSS usage
    for css_ref in id_entry.get("css", []):
        used_by.append({
            "depth": 1,
            "direction": "caller",
            "type": "css_usage",
            "fn": id_entry["name"],
            "path": css_ref.get("path", ""),
            "line": css_ref.get("line", 0)
        })

    # JS usage
    for js_ref in id_entry.get("js", []):
        used_by.append({
            "depth": 1,
            "direction": "caller",
            "type": "js_usage",
            "fn": id_entry["name"],
            "path": js_ref.get("path", ""),
            "line": js_ref.get("line", 0)
        })

    return {"defines": defines, "used_by": used_by}


def _build_tree(
    root_name: str,
    start_nodes: List[Dict],
    chains: Dict[str, List[Dict]],
    node_by_id: Dict[str, Dict],
    direction: str
) -> Dict[str, Any]:
    """Build a tree representation from traced chains."""
    tree = {
        "name": root_name,
        "type": "function",
        "callers": [],
        "callees": []
    }

    if start_nodes:
        start = start_nodes[0]
        tree["file"] = start.get("file", "")
        tree["line"] = start.get("line", 0)
        tree["status"] = start.get("status", "active")

    # Build caller tree (skip depth 0 — that's the start node itself, not a caller)
    for entry in chains.get("up", []):
        depth = entry.get("depth", 0)
        if 0 < depth <= 3:
            tree["callers"].append({
                "fn": entry.get("fn", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "depth": depth
            })

    # Build callee tree (skip depth 0 — that's the start node itself, not a callee)
    for entry in chains.get("down", []):
        depth = entry.get("depth", 0)
        if 0 < depth <= 3:
            tree["callees"].append({
                "fn": entry.get("fn", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "depth": depth,
                "resolved": entry.get("resolved", True)
            })

    return tree
