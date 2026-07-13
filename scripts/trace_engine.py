"""
Trace Engine for CodeLens
Deep call chain tracing — follows the graph up (callers) and down (callees)
to produce full impact chains for root cause analysis and change planning.

v8.2: Adds a true graph backend (`trace_via_graph`) that queries the new
graph_nodes + graph_edges tables (issue #8). The flat-registry path
(`trace_via_flat`, formerly `trace_symbol`) is retained as fallback. The
public `trace_symbol` dispatcher picks graph by default and falls back to
flat when the graph tables are empty (e.g., pre-8.2 databases). Pass
`use_graph=False` to force the flat path for A/B testing.

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
    max_results: int = MAX_CHAIN_RESULTS,
    use_graph: bool = True,
) -> Dict[str, Any]:
    """
    Trace a symbol's call chain deeply (BFS traversal).

    Dispatcher that picks between the graph backend (default, v8.2+) and the
    flat-registry backend (legacy fallback). The graph backend queries the
    graph_nodes + graph_edges tables populated during scan; the flat backend
    walks backend.json in memory via edge_resolver.

    Falls back to flat automatically when:
      - `use_graph` is False, OR
      - The graph tables don't exist or are empty (e.g., pre-8.2 database, or
        scan hasn't been run yet)

    Args:
        name: Symbol name to trace from
        workspace: Absolute path to workspace
        direction: "up" (callers/who uses this), "down" (callees/what this uses), "both"
        max_depth: Maximum traversal depth (default 10)
        domain: "frontend", "backend", or "auto"
        max_results: Max chain entries to return (default 500, prevents timeout)
        use_graph: When True (default), prefer the graph backend. Set False to
                   force the flat-registry path (A/B testing).

    Returns:
        Dict with chains, tree representation, and stats (identical shape
        regardless of backend — see trace_via_flat / trace_via_graph).
    """
    workspace = os.path.abspath(workspace)

    if use_graph:
        db_path = os.path.join(workspace, ".codelens", "codelens.db")
        try:
            from graph_model import graph_tables_populated
            if graph_tables_populated(db_path):
                return trace_via_graph(
                    name, workspace, direction, max_depth, domain, max_results
                )
        except Exception:
            # If graph introspection fails for any reason, fall back to flat
            # silently — trace must never hard-fail just because the graph
            # backend is unavailable.
            pass

    return trace_via_flat(
        name, workspace, direction, max_depth, domain, max_results
    )


def trace_via_flat(
    name: str,
    workspace: str,
    direction: str = "up",
    max_depth: int = 10,
    domain: str = "auto",
    max_results: int = MAX_CHAIN_RESULTS,
) -> Dict[str, Any]:
    """
    Trace a symbol's call chain using the flat in-memory backend registry.

    This is the original (pre-v8.2) trace implementation, kept as a fallback
    and for A/B comparison against the graph backend. Walks backend.json via
    edge_resolver's cached index.

    Args:
        name: Symbol name to trace from
        workspace: Absolute path to workspace
        direction: "up" (callers), "down" (callees), "both"
        max_depth: Maximum traversal depth
        domain: "frontend", "backend", or "auto"
        max_results: Max chain entries to return

    Returns:
        Dict with chains, tree, and stats.
    """
    workspace = os.path.abspath(workspace)
    chains = {"up": [], "down": []}
    tree = {"root": name, "children": []}

    # ─── Backend Tracing (flat registry) ─────────────────
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

    # ─── Frontend Tracing (shared with graph path) ──────
    if domain in ("frontend", "auto"):
        _trace_frontend_into(name, workspace, chains, direction)

    return _assemble_result(name, workspace, direction, max_depth, chains, tree, max_results)


def trace_via_graph(
    name: str,
    workspace: str,
    direction: str = "up",
    max_depth: int = 10,
    domain: str = "auto",
    max_results: int = MAX_CHAIN_RESULTS,
) -> Dict[str, Any]:
    """
    Trace a symbol's call chain using the graph backend (graph_nodes + graph_edges).

    Queries the SQLite graph tables populated during scan (issue #8). Uses
    BFS over CALLS edges via graph_model.query_callers / query_callees.
    Produces the same result-dict shape as `trace_via_flat` so callers and
    formatters don't need to know which backend was used.

    Frontend tracing (CSS/HTML refs) is delegated to the same shared helper
    as the flat path — the graph model only covers the backend call graph
    in this pilot migration.

    Args:
        name: Symbol name to trace from
        workspace: Absolute path to workspace
        direction: "up" (callers), "down" (callees), "both"
        max_depth: Maximum traversal depth
        domain: "frontend", "backend", or "auto"
        max_results: Max chain entries to return

    Returns:
        Dict with chains, tree, and stats (same shape as trace_via_flat).
    """
    workspace = os.path.abspath(workspace)
    db_path = os.path.join(workspace, ".codelens", "codelens.db")

    from graph_model import find_nodes_by_name, query_callers, query_callees

    chains = {"up": [], "down": []}
    tree = {"root": name, "children": []}

    # ─── Backend Tracing (graph backend) ────────────────
    if domain in ("backend", "auto"):
        start_nodes = find_nodes_by_name(name, db_path)

        for start_node in start_nodes:
            start_id = start_node["node_id"]

            if direction in ("up", "both"):
                up_chain = _bfs_trace_graph(
                    start_id, start_node, db_path,
                    max_depth, "caller", max_results - len(chains["up"]),
                )
                chains["up"].extend(up_chain)

            if direction in ("down", "both"):
                down_chain = _bfs_trace_graph(
                    start_id, start_node, db_path,
                    max_depth, "callee", max_results - len(chains["down"]),
                )
                chains["down"].extend(down_chain)

        if start_nodes:
            tree = _build_tree_graph(name, start_nodes, chains, direction)

    # ─── Frontend Tracing (shared with flat path) ──────
    if domain in ("frontend", "auto"):
        _trace_frontend_into(name, workspace, chains, direction)

    return _assemble_result(name, workspace, direction, max_depth, chains, tree, max_results)


# ─── Shared Frontend Tracing ──────────────────────────────────


def _trace_frontend_into(
    name: str,
    workspace: str,
    chains: Dict[str, List[Dict]],
    direction: str,
) -> None:
    """Append frontend (CSS/HTML) reference chains into the shared chains dict.

    Frontend tracing is identical for both backends because the graph model
    only covers the backend call graph in this pilot. This helper reads
    frontend.json and extends chains["up"] / chains["down"] in place.

    Args:
        name: Symbol name to trace.
        workspace: Absolute path to workspace.
        chains: Dict with "up" and "down" lists to extend in place.
        direction: "up", "down", or "both".
    """
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


def _assemble_result(
    name: str,
    workspace: str,
    direction: str,
    max_depth: int,
    chains: Dict[str, List[Dict]],
    tree: Dict[str, Any],
    max_results: int,
) -> Dict[str, Any]:
    """Compute stats and assemble the final trace result dict.

    Shared by both trace_via_flat and trace_via_graph so the output shape is
    identical regardless of backend.
    """
    total_up = len(chains["up"])
    total_down = len(chains["down"])
    affected_files = set()
    for chain in chains["up"] + chains["down"]:
        if "file" in chain:
            affected_files.add(chain["file"])
        if "path" in chain:
            path_val = chain["path"]
            if " → " in path_val:
                for segment in path_val.split(" → "):
                    if ":" in segment:
                        file_part = segment.rsplit(":", 1)[0]
                        affected_files.add(file_part)
                    else:
                        affected_files.add(segment)
            else:
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


# ─── Flat-Backend BFS ─────────────────────────────────────────


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


# ─── Graph-Backend BFS ────────────────────────────────────────


def _bfs_trace_graph(
    start_id: str,
    start_node: Dict[str, Any],
    db_path: str,
    max_depth: int,
    direction_label: str,
    max_results: int = MAX_CHAIN_RESULTS,
) -> List[Dict]:
    """
    BFS traversal over the graph_edges (CALLS) table via graph_model.

    Mirrors `_bfs_trace_indexed` shape so chain entries are interchangeable
    between backends. Uses graph_model.query_callers / query_callees which
    perform indexed SQLite lookups (O(log n) per hop).

    Args:
        start_id: graph_nodes.node_id to start from.
        start_node: The start node dict (from find_nodes_by_name).
        db_path: Absolute path to the SQLite database file.
        max_depth: Maximum BFS depth.
        direction_label: "caller" (trace up) or "callee" (trace down).
        max_results: Max entries to return (prevents timeout).

    Returns:
        List of chain-entry dicts with the same shape as _bfs_trace_indexed.
    """
    from graph_model import query_callers, query_callees
    # Lazy import to filter std-lib callees the same way the flat backend does.
    # The flat path silently skips std-lib methods (resolved=True, no node_id);
    # we mirror that here so A/B output matches on the fixture.
    try:
        from edge_resolver import _is_std_lib_method
    except ImportError:
        def _is_std_lib_method(_fn: str) -> bool:
            return False

    chain: List[Dict] = []

    # Depth-0 entry: the start node itself (matches flat path behavior)
    start_extra = start_node.get("extra", {}) or {}
    chain.append({
        "depth": 0,
        "direction": direction_label,
        "node_id": start_id,
        "fn": start_node.get("name", ""),
        "file": start_node.get("file", ""),
        "line": start_node.get("line", 0) or 0,
        "path": f"{start_id}",
        "status": start_extra.get("status", "active"),
        "async": start_extra.get("async", False),
    })

    # We need per-(node_id, depth) BFS but query_callers/query_callees return
    # a flat list. Re-implement BFS here using the graph_model functions per
    # hop. visited tracks node_ids already emitted to the chain.
    visited: Set[str] = set()
    visited.add(start_id)
    reported_cycles: Set[str] = set()
    queue = deque()
    queue.append((start_id, 1, start_id))

    while queue:
        current_id, depth, path = queue.popleft()

        if depth > max_depth:
            continue

        if len(chain) >= max_results:
            break

        if direction_label == "caller":
            neighbors = query_callers(current_id, db_path, max_depth=1)
        else:
            neighbors = query_callees(current_id, db_path, max_depth=1)

        for neighbor in neighbors:
            if len(chain) >= max_results:
                break

            neighbor_id = neighbor.get("node_id") or ""

            # Unresolved callee (target_id was NULL in graph_edges).
            # Skip std-lib methods to match flat-backend behavior (the flat
            # path's edge_resolver marks them resolved=True with no node_id,
            # and _bfs_trace_indexed silently skips them).
            if not neighbor_id:
                to_fn = neighbor.get("name", "unknown")
                if direction_label == "callee" and _is_std_lib_method(to_fn):
                    continue
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
                if neighbor_id == start_id and depth <= 1:
                    continue
                cycle_key = f"{neighbor_id}@{depth}"
                if cycle_key in reported_cycles:
                    continue
                reported_cycles.add(cycle_key)
                neighbor_extra = neighbor.get("extra", {}) or {}
                cyclic_entry = {
                    "depth": depth,
                    "direction": direction_label,
                    "node_id": neighbor_id,
                    "fn": neighbor.get("name", ""),
                    "file": neighbor.get("file", ""),
                    "line": neighbor.get("line", 0) or 0,
                    "path": f"{path} → {neighbor_id}",
                    "cyclic": True,
                    "status": neighbor_extra.get("status", "active"),
                    "async": neighbor_extra.get("async", False),
                }
                # Issue #223: preserve module_level marker on cyclic entries.
                if neighbor.get("module_level"):
                    cyclic_entry["module_level"] = True
                    cyclic_entry["fn"] = "<module>"
                chain.append(cyclic_entry)
                continue

            visited.add(neighbor_id)
            neighbor_extra = neighbor.get("extra", {}) or {}
            chain_entry = {
                "depth": depth,
                "direction": direction_label,
                "node_id": neighbor_id,
                "fn": neighbor.get("name", ""),
                "file": neighbor.get("file", ""),
                "line": neighbor.get("line", 0) or 0,
                "path": f"{path} → {neighbor_id}",
                "status": neighbor_extra.get("status", "active"),
                "async": neighbor_extra.get("async", False),
            }
            if neighbor_extra.get("impl_for"):
                chain_entry["impl_for"] = neighbor_extra["impl_for"]
            if neighbor_extra.get("component"):
                chain_entry["component"] = True
            # Issue #223: module-level caller entry from graph_model._bfs.
            # Mark it so formatters can render "module-level caller in <file>"
            # distinctly. Do NOT enqueue for further BFS — module scope is
            # the top of a file's call hierarchy, so module-level callers
            # have no further callers of their own.
            if neighbor.get("module_level"):
                chain_entry["module_level"] = True
                chain_entry["fn"] = "<module>"
                chain.append(chain_entry)
                continue
            chain.append(chain_entry)

            if depth < max_depth:
                queue.append((neighbor_id, depth + 1, f"{path} → {neighbor_id}"))

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
    """Build a tree representation from traced chains (flat backend)."""
    tree = {
        "name": root_name,
        "type": start_nodes[0].get("type", "function") if start_nodes else "function",
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


def _build_tree_graph(
    root_name: str,
    start_nodes: List[Dict[str, Any]],
    chains: Dict[str, List[Dict]],
    direction: str
) -> Dict[str, Any]:
    """Build a tree representation from traced chains (graph backend).

    Same shape as _build_tree, but pulls start-node metadata from the graph
    node dict (which uses 'name' instead of 'fn' and stores original fields
    under 'extra').
    """
    first = start_nodes[0] if start_nodes else {}
    first_extra = first.get("extra", {}) or {}
    tree = {
        "name": root_name,
        "type": first.get("node_type", "function") if first else "function",
        "callers": [],
        "callees": []
    }

    if first:
        tree["file"] = first.get("file", "")
        tree["line"] = first.get("line", 0) or 0
        tree["status"] = first_extra.get("status", "active")

    for entry in chains.get("up", []):
        depth = entry.get("depth", 0)
        if 0 < depth <= 3:
            tree["callers"].append({
                "fn": entry.get("fn", ""),
                "file": entry.get("file", ""),
                "line": entry.get("line", 0),
                "depth": depth
            })

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
