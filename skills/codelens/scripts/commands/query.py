"""Query command — Query a specific class/id/function from the registry."""

import os
import json
from typing import Dict, Any

from registry import load_frontend_registry, load_backend_registry
from edge_resolver import get_callers, get_callees
from commands import register_command


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


def execute(args, workspace):
    return cmd_query(args.name, workspace, args.domain, args.file)


def cmd_query(query_name: str, workspace: str, domain: str = None,
               file_filter: str = None) -> Dict[str, Any]:
    """Query a specific class/id/function from the registry."""
    workspace = os.path.abspath(workspace)

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

                callers = get_callers(node["id"], backend.get("edges", []))
                callees = get_callees(node["id"], backend.get("edges", []),
                                       backend.get("nodes", []))

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
                    "callees": callees
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
        "found": False,
        "query": query_name,
        "domain": domain or "auto",
        "action": "CREATE",
        "action_reason": "Name does not exist. Safe to create."
    }


register_command("query", "Query a specific class/id/function", add_args, execute)
