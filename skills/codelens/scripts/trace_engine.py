"""
Trace Engine for CodeLens
Deep call chain tracing — follows the graph up (callers) and down (callees)
to produce full impact chains for root cause analysis and change planning.
"""

import json
import logging
import os
from collections import deque
from typing import Dict, List, Any, Optional, Set, Tuple

logger = logging.getLogger(__name__)


def trace_symbol(
    name: str,
    workspace: str,
    direction: str = "up",
    max_depth: int = 10,
    domain: str = "auto"
) -> Dict[str, Any]:
    """
    Trace a symbol's call chain deeply (BFS traversal).

    Args:
        name: Symbol name to trace from
        workspace: Absolute path to workspace
        direction: "up" (callers/who uses this), "down" (callees/what this uses), "both"
        max_depth: Maximum traversal depth (default 10)
        domain: "frontend", "backend", or "auto"

    Returns:
        Dict with chains, tree representation, and stats
    """
    workspace = os.path.abspath(workspace)
    chains = {"up": [], "down": []}
    tree = {"root": name, "children": []}

    # ─── Backend Tracing ────────────────────────────────
    if domain in ("backend", "auto"):
        from registry import load_backend_registry
        try:
            backend = load_backend_registry(workspace)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            backend = {"nodes": [], "edges": []}
            logger.warning(f"Could not load backend registry: {e}")
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])

        # Build adjacency lists
        callers_of: Dict[str, List[Dict]] = {}   # node_id → list of caller node_ids
        callees_of: Dict[str, List[Dict]] = {}   # node_id → list of callee node_ids
        node_by_id: Dict[str, Dict] = {}
        node_by_fn: Dict[str, List[Dict]] = {}

        for node in nodes:
            nid = node["id"]
            node_by_id[nid] = node
            fn = node["fn"]
            if fn not in node_by_fn:
                node_by_fn[fn] = []
            node_by_fn[fn].append(node)

        for edge in edges:
            from_id = edge.get("from", "")
            to_id = edge.get("to", "")

            if to_id:
                if to_id not in callers_of:
                    callers_of[to_id] = []
                callers_of[to_id].append({
                    "node_id": from_id,
                    "edge": edge
                })

            if from_id:
                if from_id not in callees_of:
                    callees_of[from_id] = []
                callees_of[from_id].append({
                    "node_id": to_id,
                    "edge": edge
                })

        # Find starting node(s)
        start_nodes = node_by_fn.get(name, [])

        if not start_nodes:
            # Also check if name matches a node_id pattern
            for node in nodes:
                if name in node.get("fn", "") or name in node.get("id", ""):
                    start_nodes.append(node)

        # Shared visited set across all start_nodes to prevent duplicate results
        shared_visited = set()

        for start_node in start_nodes:
            start_id = start_node["id"]

            # Trace UP (callers)
            if direction in ("up", "both"):
                up_chain = _bfs_trace(
                    start_id, callers_of, node_by_id,
                    max_depth, "caller", shared_visited
                )
                chains["up"].extend(up_chain)

            # Trace DOWN (callees)
            if direction in ("down", "both"):
                down_chain = _bfs_trace(
                    start_id, callees_of, node_by_id,
                    max_depth, "callee", shared_visited
                )
                chains["down"].extend(down_chain)

        # Build tree from chains
        if start_nodes:
            tree = _build_tree(name, start_nodes, chains, node_by_id, direction)

    # ─── Frontend Tracing ───────────────────────────────
    if domain in ("frontend", "auto"):
        from registry import load_frontend_registry
        try:
            frontend = load_frontend_registry(workspace)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            frontend = {"classes": [], "ids": []}
            logger.warning(f"Could not load frontend registry: {e}")

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
            affected_files.add(chain["path"])

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

    return result


def _bfs_trace(
    start_id: str,
    adjacency: Dict[str, List[Dict]],
    node_by_id: Dict[str, Dict],
    max_depth: int,
    direction_label: str,
    shared_visited: Optional[Set[str]] = None
) -> List[Dict]:
    """
    BFS traversal of the call graph from start_id.

    Returns a list of chain entries, each with depth, node info, and path.
    If shared_visited is provided, it is used across multiple calls to prevent
    revisiting nodes already seen in a prior BFS traversal.
    """
    chain = []
    visited = shared_visited if shared_visited is not None else set()
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

        neighbors = adjacency.get(current_id, [])
        for neighbor in neighbors:
            neighbor_id = neighbor["node_id"]
            edge = neighbor.get("edge", {})

            if neighbor_id in visited:
                # Already visited — record as cyclic reference
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
                to_fn = edge.get("to_fn", "unknown")
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

    # Build caller tree
    for entry in chains.get("up", []):
        if entry.get("depth", 0) <= 3:
            tree["callers"].append({
                "fn": entry.get("fn", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "depth": entry.get("depth", 0)
            })

    # Build callee tree
    for entry in chains.get("down", []):
        if entry.get("depth", 0) <= 3:
            tree["callees"].append({
                "fn": entry.get("fn", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "depth": entry.get("depth", 0),
                "resolved": entry.get("resolved", True)
            })

    return tree
