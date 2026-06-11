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


def execute(args, workspace):
    limit = None if getattr(args, 'all', False) else getattr(args, 'limit', 20)
    return cmd_query(args.name, workspace, args.domain, args.file, limit=limit)


def cmd_query(query_name: str, workspace: str, domain: str = None,
               file_filter: str = None, limit: int = None) -> Dict[str, Any]:
    """Query a specific class/id/function from the registry.

    Args:
        query_name: Name to look up
        workspace: Workspace root path
        domain: 'frontend' or 'backend' or None (both)
        file_filter: Filter by file path substring
        limit: Max callers/callees to return (None=default=20, 0=no limit)
    """
    workspace = os.path.abspath(workspace)
    if limit is None:
        limit = 20

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
    if domain in (None, "frontend"):
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            if cls["name"] == query_name:
                if file_filter and file_filter not in json.dumps(cls):
                    continue
                action, action_reason = _get_query_action(cls["status"])
                return {
                    "found": True,
                    "type": "class",
                    "domain": "frontend",
                    "name": cls["name"],
                    "ref_count": cls["ref_count"],
                    "status": cls["status"],
                    "action": action,
                    "action_reason": action_reason,
                    "css": cls.get("css", []),
                    "js": cls.get("js", [])
                }

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == query_name:
                if file_filter and file_filter not in json.dumps(id_entry):
                    continue
                action, action_reason = _get_query_action(id_entry["status"])
                return {
                    "found": True,
                    "type": "id",
                    "domain": "frontend",
                    "name": id_entry["name"],
                    "ref_count": id_entry["ref_count"],
                    "status": id_entry["status"],
                    "action": action,
                    "action_reason": action_reason,
                    "defined_in_html": id_entry.get("defined_in_html", []),
                    "css": id_entry.get("css", []),
                    "js": id_entry.get("js", [])
                }

    if domain in (None, "backend"):
        backend = load_backend_registry(workspace)

        for node in backend.get("nodes", []):
            if node["fn"] == query_name:
                if file_filter and file_filter not in node.get("file", ""):
                    continue

                all_callers = deduplicate_callers(
                    get_callers(node["id"], backend.get("edges", []))
                )
                all_callees = get_callees(node["id"], backend.get("edges", []),
                                           backend.get("nodes", []))

                # Apply limit to callers/callees
                total_callers = len(all_callers)
                total_callees = len(all_callees)
                callers = all_callers[:limit] if limit else all_callers
                callees = all_callees[:limit] if limit else all_callees

                node_status = node.get("status", "active")
                action, action_reason = _get_query_action(node_status)
                result = {
                    "found": True,
                    "type": "function",
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
                        "async": node.get("async", False)
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

    return {
        "status": "ok",
        "found": False,
        "query": query_name,
        "domain": domain or "auto",
        "action": "CREATE",
        "action_reason": "Name does not exist. Safe to create."
    }


register_command("query", "Query a specific class/id/function", add_args, execute)
