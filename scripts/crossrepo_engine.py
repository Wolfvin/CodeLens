"""
Cross-Repo Intelligence Engine for CodeLens (issue #15 MVP).

Provides multi-repo symbol table merging and cross-repo edge resolution so
agents can trace calls that cross repository boundaries — e.g. a call from
``services/api`` into ``lib/shared``.

Implements the Minimum Viable Version from issue #15:
    Just support multiple ``repo_path`` entries — resolve imports against
    the combined symbol table from all indexed repos.

Design
------
This module is **non-breaking and additive**. It does NOT modify:

- ``scan`` — each repo is scanned independently as before.
- ``init`` — no config schema changes required (additional paths are
  passed via the ``--additional-paths`` CLI flag).
- ``load_backend_registry`` — the single-repo loader is untouched.
- ``resolve_edges`` — the existing resolver is reused as-is.

Instead, it sits *on top* of the existing registry layer:

1. Loads the backend registry from the primary workspace.
2. Loads backend registries from each additional repo path.
3. Tags every node with a ``repo`` field (the workspace path it came
   from) so downstream consumers can tell which repo a symbol lives in.
4. Merges all nodes + raw edges into combined lists.
5. Re-runs :func:`edge_resolver.resolve_edges` on the combined set.
   Because the resolver matches ``to_fn`` (function name) against the
   full node list, a call from repo A to a function defined in repo B
   is now resolved automatically — the resolver doesn't care which repo
   a node came from.
6. Post-processes the resolved edges: any edge whose ``from`` node and
   ``to`` node are in different repos gets ``cross_repo: True`` and a
   ``target_repo`` field, so agents can distinguish intra-repo calls
   from cross-repo calls.

The merged registry has the same shape as a single-repo backend
registry (``{"nodes": [...], "edges": [...]}``), so it can be fed
directly into :func:`edge_resolver.get_callers`,
:func:`edge_resolver.get_callees`, and the query logic in
:func:`commands.query.cmd_query`.

Public surface
--------------
- :func:`load_merged_registry` — merge multiple repos into one registry.
- :func:`query_cross_repo` — multi-repo symbol query (drop-in
  replacement for single-repo query when additional paths are given).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from registry import load_backend_registry
from edge_resolver import resolve_edges
from utils import logger


# ─── Path Normalization ───────────────────────────────────────

def _norm_path(p: str) -> str:
    """Normalize a workspace path for comparison (absolute, no trailing /)."""
    return os.path.abspath(p).rstrip(os.sep) if p else ""


def _parse_additional_paths(raw: Optional[str]) -> List[str]:
    """Parse the ``--additional-paths`` CLI value into a list of paths.

    Accepts comma-separated paths (``"path1,path2,path3"``) and ignores
    empty entries. Whitespace around each path is stripped.

    Args:
        raw: The raw string from ``--additional-paths``, or ``None``.

    Returns:
        List of absolute path strings. Empty if ``raw`` is ``None`` or
        all entries are empty/whitespace.
    """
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [os.path.abspath(p) for p in parts if p]


# ─── Registry Merging ─────────────────────────────────────────

def load_merged_registry(
    primary_workspace: str,
    additional_paths: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Load and merge backend registries from multiple repos.

    Loads the primary workspace's backend registry plus each additional
    repo's registry, tags every node with its source ``repo`` path, and
    re-resolves edges against the combined symbol table so cross-repo
    calls are resolved.

    Args:
        primary_workspace: Absolute path to the primary workspace root.
        additional_paths: List of additional repo root paths to merge.
            May be ``None`` or empty (returns just the primary registry
            with ``repo`` tags added — still a valid merged registry).

    Returns:
        Dict with the same shape as a single-repo backend registry::

            {
                "workspace": "<primary workspace>",
                "repos": ["<primary>", "<additional1>", ...],
                "nodes": [...],           # merged, each with "repo" field
                "edges": [...],           # re-resolved, cross-repo flagged
                "stats": {
                    "total_nodes": <int>,
                    "total_edges": <int>,
                    "cross_repo_edges": <int>,
                    "repos_merged": <int>,
                },
            }

        If the primary workspace has no registry (never scanned), returns
        an empty merged registry with ``repos_merged: 0``. If additional
        repos can't be loaded, they're silently skipped (counted in
        ``repos_merged`` only if they contributed at least one node).
    """
    primary_workspace = os.path.abspath(primary_workspace)
    additional_paths = additional_paths or []

    # ── Load primary ──
    primary_reg = load_backend_registry(primary_workspace)
    primary_nodes = primary_reg.get("nodes", [])
    primary_edges = primary_reg.get("edges", [])

    # Tag primary nodes with repo
    for node in primary_nodes:
        node.setdefault("repo", primary_workspace)

    # Collect raw edges — we need `from` and `to_fn` for re-resolution.
    # Already-resolved edges still carry `to_fn`, so we can pass them
    # through resolve_edges which will re-match against the merged node set.
    all_nodes: List[Dict[str, Any]] = list(primary_nodes)
    all_raw_edges: List[Dict[str, Any]] = list(primary_edges)

    repos_merged = 1 if primary_nodes else 0

    # ── Load additionals ──
    for repo_path in additional_paths:
        repo_path = os.path.abspath(repo_path)
        if repo_path == primary_workspace:
            # Skip if same as primary (user accidentally listed it twice)
            continue
        try:
            reg = load_backend_registry(repo_path)
            nodes = reg.get("nodes", [])
            edges = reg.get("edges", [])
            if not nodes:
                logger.debug(f"crossrepo: additional repo {repo_path} has no nodes, skipping")
                continue
            # Tag with repo
            for node in nodes:
                node.setdefault("repo", repo_path)
            all_nodes.extend(nodes)
            all_raw_edges.extend(edges)
            repos_merged += 1
        except Exception as e:
            logger.warning(
                f"crossrepo: failed to load additional repo {repo_path}: {e}",
                exc_info=True,
            )

    # ── Re-resolve edges against the merged node set ──
    # resolve_edges returns (resolved_nodes, resolved_edges). The
    # resolved_nodes are the same nodes we passed in (possibly with
    # `duplicate_define` flags set). The resolved_edges have `to`
    # (target node_id) filled in where a match was found.
    if all_nodes and all_raw_edges:
        resolved_nodes, resolved_edges = resolve_edges(all_nodes, all_raw_edges)
    else:
        resolved_nodes = all_nodes
        resolved_edges = []

    # ── Tag cross-repo edges ──
    # Build a node_id → repo map for O(1) lookup
    node_repo: Dict[str, str] = {}
    for node in resolved_nodes:
        node_id = node.get("id", "")
        repo = node.get("repo", "")
        if node_id and repo:
            node_repo[node_id] = repo

    cross_repo_count = 0
    for edge in resolved_edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        from_repo = node_repo.get(from_id, "")
        to_repo = node_repo.get(to_id, "")
        if from_repo and to_repo and from_repo != to_repo:
            edge["cross_repo"] = True
            edge["target_repo"] = to_repo
            edge["source_repo"] = from_repo
            cross_repo_count += 1
        else:
            edge["cross_repo"] = False

    return {
        "workspace": primary_workspace,
        "repos": [primary_workspace] + [
            p for p in additional_paths if os.path.abspath(p) != primary_workspace
        ],
        "nodes": resolved_nodes,
        "edges": resolved_edges,
        "stats": {
            "total_nodes": len(resolved_nodes),
            "total_edges": len(resolved_edges),
            "cross_repo_edges": cross_repo_count,
            "repos_merged": repos_merged,
        },
    }


# ─── Multi-Repo Query ─────────────────────────────────────────

def query_cross_repo(
    name: str,
    primary_workspace: str,
    additional_paths: Optional[List[str]] = None,
    fuzzy: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    """Query a symbol across multiple repos.

    This is a multi-repo version of :func:`commands.query.cmd_query`. It
    loads the merged registry, finds matching nodes across all repos,
    and returns callers/callees with ``repo`` and ``cross_repo``
    annotations so agents can see which calls cross repo boundaries.

    Args:
        name: Symbol name to query.
        primary_workspace: Primary workspace root path.
        additional_paths: Additional repo paths to search across.
        fuzzy: Enable fuzzy/substring matching (case-insensitive).
        limit: Max callers/callees to return per result.

    Returns:
        Dict with the same shape as ``cmd_query`` output, plus:

        * Each node in the result has a ``repo`` field.
        * Each caller/callee that crosses a repo boundary has
          ``cross_repo: True`` and ``target_repo`` / ``source_repo``.
        * ``stats`` includes ``repos_searched`` and ``cross_repo_edges``.

        If the name is not found in any repo, returns a not-found result
        with ``action: "CREATE"`` (same as single-repo query).
    """
    from edge_resolver import get_callers, get_callees
    from utils import deduplicate_callers

    primary_workspace = os.path.abspath(primary_workspace)
    additional_paths = additional_paths or []

    merged = load_merged_registry(primary_workspace, additional_paths)
    nodes = merged.get("nodes", [])
    edges = merged.get("edges", [])
    repos_searched = merged.get("stats", {}).get("repos_merged", 0)

    # ── Exact + fuzzy match across all repos ──
    name_lower = name.lower()
    exact_matches = []
    fuzzy_matches = []

    for node in nodes:
        fn = node.get("fn", "")
        if fn == name:
            exact_matches.append(node)
        elif fuzzy and name_lower in fn.lower() and fn.lower() != name_lower:
            fuzzy_matches.append(node)

    # If we have exact matches, use those; otherwise fall back to fuzzy
    matches = exact_matches if exact_matches else fuzzy_matches

    if not matches:
        return {
            "status": "ok",
            "found": False,
            "query": name,
            "action": "CREATE",
            "action_reason": "Name does not exist in any searched repo. Safe to create.",
            "repos_searched": repos_searched,
            "stats": merged.get("stats", {}),
        }

    # ── Single match: return detailed result with callers/callees ──
    if len(matches) == 1:
        node = matches[0]
        node_repo = node.get("repo", primary_workspace)

        all_callers = deduplicate_callers(get_callers(node["id"], edges, nodes))
        all_callees = get_callees(node["id"], edges, nodes)

        # Annotate callers/callees with cross-repo info
        node_repo_map = {n.get("id", ""): n.get("repo", "") for n in nodes}

        for caller in all_callers:
            from_id = caller.get("from", "")
            caller_repo = node_repo_map.get(from_id, "")
            caller["repo"] = caller_repo
            caller["cross_repo"] = bool(
                caller_repo and caller_repo != node_repo
            )

        for callee in all_callees:
            to_id = callee.get("to", "")
            callee_repo = node_repo_map.get(to_id, "")
            callee["repo"] = callee_repo
            callee["cross_repo"] = bool(
                callee_repo and callee_repo != node_repo
            )

        total_callers = len(all_callers)
        total_callees = len(all_callees)
        callers = all_callers[:limit] if limit and limit > 0 else all_callers
        callees = all_callees[:limit] if limit and limit > 0 else all_callees

        return {
            "status": "ok",
            "found": True,
            "type": node.get("type", "function"),
            "query": name,
            "repo": node_repo,
            "cross_repo_search": repos_searched > 1,
            "repos_searched": repos_searched,
            "node": {
                "id": node["id"],
                "fn": node["fn"],
                "ref_count": node.get("ref_count", 0),
                "status": node.get("status", "active"),
                "file": node.get("file", ""),
                "line": node.get("line", 0),
                "repo": node_repo,
            },
            "callers": callers,
            "callees": callees,
            "pagination": {
                "callers_total": total_callers,
                "callees_total": total_callees,
                "callers_shown": len(callers),
                "callees_shown": len(callees),
                "has_more_callers": total_callers > len(callers),
                "has_more_callees": total_callees > len(callees),
            },
            "stats": merged.get("stats", {}),
        }

    # ── Multiple matches: return summary list ──
    matches_summary = []
    for node in matches[:limit] if limit and limit > 0 else matches:
        node_repo = node.get("repo", primary_workspace)
        matches_summary.append({
            "id": node["id"],
            "fn": node["fn"],
            "file": node.get("file", ""),
            "line": node.get("line", 0),
            "status": node.get("status", "active"),
            "ref_count": node.get("ref_count", 0),
            "repo": node_repo,
        })

    total_matches = len(matches)
    return {
        "status": "ok",
        "found": True,
        "type": "multi_match",
        "query": name,
        "match_type": "exact" if exact_matches else "fuzzy",
        "cross_repo_search": repos_searched > 1,
        "repos_searched": repos_searched,
        "match_count": total_matches,
        "action": "LIST_FIRST",
        "action_reason": (
            f"Found {total_matches} definitions across {repos_searched} repo(s). "
            "List all before making changes."
        ),
        "matches": matches_summary,
        "pagination": {
            "total_matches": total_matches,
            "shown": len(matches_summary),
            "has_more": total_matches > len(matches_summary),
        },
        "stats": merged.get("stats", {}),
    }
