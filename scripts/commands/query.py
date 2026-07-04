"""Query command — Query a specific class/id/function from the registry."""

import os
import json
from typing import Dict, Any, List

from registry import load_frontend_registry, load_backend_registry
from edge_resolver import get_callers, get_callees
from commands import register_command
from utils import is_file_path, deduplicate_callers, logger


def _get_query_action(status: str) -> tuple:
    """Return (action, action_reason) based on query result status."""
    if status == "active":
        return ("EXTEND", "Name exists and is active. Do not overwrite — extend or use a different name.")
    elif status == "dead":
        return ("ASK", "Name exists but is dead (unused). Ask user whether to reuse or create new.")
    elif status == "ipc_exposed":
        return ("EXTEND", "Name exists as a Tauri IPC command (exposed to frontend via invoke()). Do not overwrite — extend or use a different name.")
    elif status == "duplicate_ref":
        return ("LIST_FIRST", "Name has duplicate references. List all referrers before making changes.")
    elif status == "collision":
        return ("STOP", "Name collision detected. Fix collision before proceeding.")
    else:
        return ("EXTEND", "Name exists. Proceed with caution.")


def add_args(parser):
    parser.add_argument("name", help="Name to query")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend"], default=None,
                        help="Domain to search")
    parser.add_argument("--file", default=None, help="Filter by file path")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max callers/callees to return (default: 20)")
    parser.add_argument("--all", action="store_true",
                        help="Return all callers/callees (no limit)")
    parser.add_argument("--fuzzy", action="store_true",
                        help="Enable fuzzy/substring matching (case-insensitive)")
    parser.add_argument(
        "--additional-paths",
        default=None,
        metavar="PATHS",
        help=(
            "Comma-separated list of additional repo root paths to search "
            "across (issue #15 cross-repo intelligence). When provided, the "
            "query loads and merges registries from all repos and resolves "
            "cross-repo call edges. Example: "
            "'--additional-paths ../lib/shared,../services/worker'."
        ),
    )


def execute(args, workspace):
    limit = None if getattr(args, 'all', False) else getattr(args, 'limit', 20)
    fuzzy = getattr(args, 'fuzzy', False)

    # ── Cross-repo path (issue #15) ──
    # When --additional-paths is provided, delegate to the cross-repo
    # engine which merges registries from all repos and resolves
    # cross-repo call edges. The result shape is compatible with the
    # single-repo query result, so downstream formatting (compact, ai,
    # etc.) works unchanged.
    additional_paths_raw = getattr(args, 'additional_paths', None)
    if additional_paths_raw:
        from crossrepo_engine import query_cross_repo, _parse_additional_paths
        additional_paths = _parse_additional_paths(additional_paths_raw)
        result = query_cross_repo(
            args.name, workspace, additional_paths,
            fuzzy=fuzzy, limit=limit if limit else 20,
        )
        _attach_baseline_confidence(result, args.name, workspace)
        return result

    # ── Single-repo path (default, unchanged) ──
    result = cmd_query(args.name, workspace, args.domain, args.file, limit=limit, fuzzy=fuzzy)
    _attach_baseline_confidence(result, args.name, workspace)
    return result


def _attach_baseline_confidence(result: Dict[str, Any], query_name: str, workspace: str) -> None:
    """Attach baseline confidence to query results.

    Per ``hybrid_engine.py`` module docstring, CodeLens's default analysis path
    (tree-sitter AST) corresponds to MEDIUM confidence.  ``HybridEngine.enhance_query``
    sets ``confidence=MEDIUM`` when LSP is not active (``deep=False``).  When the
    user later passes ``--deep``, ``codelens.py`` post-processing calls
    ``enhance_query`` again with ``deep=True`` and may override this to HIGH or
    LOW based on LSP verification.

    Even when the queried name is not found, we attach a default
    ``confidence: "medium"`` so consumers always see the field (the response
    still carries ``found: False`` so callers can distinguish).
    """
    if not isinstance(result, dict):
        return
    if not result.get("found"):
        # Name not in registry — still expose a baseline confidence so the
        # response shape is stable for consumers expecting the field.
        result.setdefault("confidence", "medium")
        return
    try:
        from hybrid_engine import create_hybrid_engine
        engine = create_hybrid_engine(workspace, deep=False)
        engine.enhance_query(result, query_name)
        engine.cleanup()
    except Exception:
        result.setdefault("confidence", "medium")


def cmd_query(query_name: str, workspace: str, domain: str = None,
               file_filter: str = None, limit: int = None, fuzzy: bool = False) -> Dict[str, Any]:
    """Query a specific class/id/function from the registry.

    Args:
        query_name: Name to look up
        workspace: Workspace root path
        domain: 'frontend' or 'backend' or None (both)
        file_filter: Filter by file path substring
        limit: Max callers/callees to return (None=default=20, 0=no limit)
        fuzzy: Enable fuzzy/substring matching (case-insensitive) for backend functions
    """
    workspace = os.path.abspath(workspace)
    if limit is None:
        limit = 20

    backend = None  # Initialize; will be loaded lazily when needed

    # ─── File path lookup ─────────────────────────────
    if is_file_path(query_name) and domain in (None, "backend"):
        backend = load_backend_registry(workspace)
        # Try exact match first
        matching_nodes = [n for n in backend.get("nodes", []) if n.get("file", "") == query_name]

        # If no exact match, try partial path match
        if not matching_nodes:
            matching_nodes = [n for n in backend.get("nodes", [])
                              if n.get("file", "").endswith(query_name)
                              or n.get("file", "").endswith('/' + query_name)]

        if matching_nodes:
            # Group results by file
            file_groups: Dict[str, List[Dict]] = {}
            for node in matching_nodes:
                f = node.get("file", "")
                if f not in file_groups:
                    file_groups[f] = []
                file_groups[f].append({
                    "id": node["id"],
                    "fn": node["fn"],
                    "line": node.get("line", 0),
                    "status": node.get("status", "active"),
                    "async": node.get("async", False),
                    "ref_count": node.get("ref_count", 0)
                })

            results_by_file = [
                {"file": f, "symbols": syms}
                for f, syms in file_groups.items()
            ]
            return {
                "status": "ok",
                "found": True,
                "type": "file",
                "domain": "backend",
                "query": query_name,
                "results_by_file": results_by_file
            }

    # ─── Normal name lookup ───────────────────────────
    # Collect ALL matches across frontend and backend registries,
    # then decide whether to return a single detailed result or a
    # multi-match summary.
    frontend_matches = []
    backend_matches = []

    if domain in (None, "frontend"):
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            if cls["name"] == query_name:
                if file_filter:
                    all_refs_json = json.dumps(cls.get("css", []) + cls.get("js", []))
                    if file_filter not in all_refs_json:
                        continue
                frontend_matches.append({
                    "type": "class",
                    "domain": "frontend",
                    "name": cls["name"],
                    "ref_count": cls["ref_count"],
                    "status": cls["status"],
                    "css_count": len(cls.get("css", [])),
                    "js_count": len(cls.get("js", [])),
                })

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == query_name:
                if file_filter and file_filter not in json.dumps(id_entry):
                    continue
                frontend_matches.append({
                    "type": "id",
                    "domain": "frontend",
                    "name": id_entry["name"],
                    "ref_count": id_entry["ref_count"],
                    "status": id_entry["status"],
                    "html_count": len(id_entry.get("defined_in_html", [])),
                    "css_count": len(id_entry.get("css", [])),
                    "js_count": len(id_entry.get("js", [])),
                })

    if domain in (None, "backend"):
        if backend is None:
            backend = load_backend_registry(workspace)

        # Exact match search
        for node in backend.get("nodes", []):
            if node["fn"] == query_name:
                if file_filter and file_filter not in node.get("file", ""):
                    continue
                backend_matches.append(node)

    # ─── Decide: single detailed result or multi-match summary ────
    total_matches = len(frontend_matches) + len(backend_matches)

    # ─── Fuzzy/substring match in backend when no exact matches found ────
    # Must happen BEFORE the total_matches == 0 early return, otherwise
    # --fuzzy flag is completely dead code when there are zero exact matches
    # (which is exactly when you'd want fuzzy matching).
    if domain in (None, "backend") and (fuzzy or total_matches == 0):
        if backend is None:
            backend = load_backend_registry(workspace)
        query_lower = query_name.lower()
        fuzzy_matches = []
        for node in backend.get("nodes", []):
            fn_lower = node.get("fn", "").lower()
            # Case-insensitive contains match, excluding exact matches already found
            if query_lower in fn_lower and fn_lower != query_name.lower():
                if file_filter and file_filter not in node.get("file", ""):
                    continue
                fuzzy_matches.append({
                    "id": node["id"],
                    "fn": node["fn"],
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                    "status": node.get("status", "active"),
                    "async": node.get("async", False),
                    "ref_count": node.get("ref_count", 0),
                })

        if fuzzy_matches:
            # Sort fuzzy matches: prioritize by relevance
            def fuzzy_sort_key(match):
                fn = match.get("fn", "")
                is_exact_ci = 0 if fn.lower() == query_lower else 1
                ref_count = match.get("ref_count", 0)
                is_dead = 0 if match.get("status") != "dead" else 1
                return (is_exact_ci, is_dead, -ref_count, fn.lower())

            fuzzy_matches.sort(key=fuzzy_sort_key)

            return {
                "status": "ok",
                "found": True,
                "type": "function_fuzzy",
                "domain": "backend",
                "query": query_name,
                "match_type": "fuzzy",
                "matches": fuzzy_matches[:limit] if limit else fuzzy_matches,
                "total_matches": len(fuzzy_matches),
                "action": "LIST_FIRST",
                "action_reason": f"No exact match for '{query_name}', but {len(fuzzy_matches)} similar function(s) found. Use exact name for full details."
            }

    if total_matches == 0:
        return {
            "status": "ok",
            "found": False,
            "query": query_name,
            "domain": domain or "auto",
            "action": "CREATE",
            "action_reason": "Name does not exist. Safe to create."
        }

    if total_matches == 1:
        # Single match — return detailed result with callers/callees
        if frontend_matches:
            m = frontend_matches[0]
            # Reload to get full details
            frontend = load_frontend_registry(workspace)
            if m["type"] == "class":
                for cls in frontend.get("classes", []):
                    if cls["name"] == query_name:
                        action, action_reason = _get_query_action(cls["status"])
                        return {
                            "status": "ok",
                            "found": True,
                            "type": "class",
                            "domain": "frontend",
                            "name": cls["name"],
                            "ref_count": cls["ref_count"],
                            "entry_status": cls["status"],
                            "action": action,
                            "action_reason": action_reason,
                            "css": cls.get("css", []),
                            "js": cls.get("js", [])
                        }
            else:  # id
                for id_entry in frontend.get("ids", []):
                    if id_entry["name"] == query_name:
                        action, action_reason = _get_query_action(id_entry["status"])
                        return {
                            "status": "ok",
                            "found": True,
                            "type": "id",
                            "domain": "frontend",
                            "name": id_entry["name"],
                            "ref_count": id_entry["ref_count"],
                            "entry_status": id_entry["status"],
                            "action": action,
                            "action_reason": action_reason,
                            "defined_in_html": id_entry.get("defined_in_html", []),
                            "css": id_entry.get("css", []),
                            "js": id_entry.get("js", [])
                        }

        if backend_matches:
            node = backend_matches[0]
            all_callers = deduplicate_callers(
                get_callers(node["id"], backend.get("edges", []))
            )
            all_callees = get_callees(node["id"], backend.get("edges", []),
                                       backend.get("nodes", []))

            # Apply limit to callers/callees
            total_callers = len(all_callers)
            total_callees = len(all_callees)
            callers = all_callers[:limit] if limit and limit > 0 else all_callers
            callees = all_callees[:limit] if limit and limit > 0 else all_callees

            node_status = node.get("status", "active")
            action, action_reason = _get_query_action(node_status)
            result = {
                "status": "ok",
                "found": True,
                "type": node.get("type", "function"),
                "domain": "backend",
                "action": action,
                "action_reason": action_reason,
                "node": {
                    "id": node["id"],
                    "fn": node["fn"],
                    "ref_count": node.get("ref_count", 0),
                    "status": node_status,
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                    "async": node.get("async", False),
                    "impl_for": node.get("impl_for"),
                    "superclasses": node.get("superclasses")
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
                }
            }

            if node.get("impl_for"):
                result["node"]["impl_for"] = node["impl_for"]
            if node.get("trait_name"):
                result["node"]["trait_name"] = node["trait_name"]
            if node.get("component"):
                result["node"]["component"] = node["component"]
            if node.get("duplicate_define"):
                result["node"]["duplicate_define"] = True

            return result

    # ─── Multiple matches — return summary list ──────────────
    matches_summary = []

    for m in frontend_matches:
        action, action_reason = _get_query_action(m["status"])
        matches_summary.append({
            "domain": "frontend",
            "type": m["type"],
            "name": m["name"],
            "status": m["status"],
            "ref_count": m["ref_count"],
            "action": action,
        })

    for node in backend_matches:
        node_status = node.get("status", "active")
        action, action_reason = _get_query_action(node_status)
        summary = {
            "domain": "backend",
            "type": node.get("type", "function"),
            "id": node["id"],
            "fn": node["fn"],
            "file": node.get("file", ""),
            "line": node.get("line", 0),
            "status": node_status,
            "ref_count": node.get("ref_count", 0),
            "action": action,
            "impl_for": node.get("impl_for"),
            "superclasses": node.get("superclasses"),
        }
        if node.get("component"):
            summary["component"] = True
        if node.get("duplicate_define"):
            summary["duplicate_define"] = True
        matches_summary.append(summary)

    # Determine best overall action
    worst_action = "EXTEND"
    for m in matches_summary:
        a = m.get("action", "EXTEND")
        if a == "STOP":
            worst_action = "STOP"
            break
        if a == "ASK" and worst_action not in ("STOP",):
            worst_action = "ASK"
        if a == "LIST_FIRST" and worst_action not in ("STOP", "ASK"):
            worst_action = "LIST_FIRST"

    # Fuzzy match for multi-match scenarios is now handled above
    # (before the total_matches == 0 early return), so --fuzzy works
    # even when there are zero exact matches.

    return {
        "status": "ok",
        "found": True,
        "type": "multi_match",
        "query": query_name,
        "match_count": total_matches,
        "action": worst_action,
        "action_reason": f"Found {total_matches} definitions. List all before making changes.",
        "matches": matches_summary[:limit] if limit and limit > 0 else matches_summary,
        "pagination": {
            "total_matches": total_matches,
            "shown": min(len(matches_summary), limit) if limit and limit > 0 else len(matches_summary),
            "has_more": total_matches > limit if limit and limit > 0 else False,
        }
    }


register_command("query", "Query a specific class/id/function", add_args, execute,

hidden=True,

)
