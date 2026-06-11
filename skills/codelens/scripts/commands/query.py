"""Query command — Query a specific class/id/function from the registry."""

import os
import json
from typing import Dict, Any, List

from registry import load_frontend_registry, load_backend_registry
from edge_resolver import get_callers, get_callees
from commands import register_command


# Known file extensions used to detect file path queries
_FILE_PATH_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.css', '.html', '.rs', '.vue', '.svelte'}


def _is_file_path(name: str) -> bool:
    """Check if a name looks like a file path."""
    if '/' in name:
        return True
    for ext in _FILE_PATH_EXTENSIONS:
        if name.endswith(ext):
            return True
    return False


def _deduplicate_callers(callers: List[Dict]) -> List[Dict]:
    """Deduplicate callers by (file, line) tuple extracted from the 'from' field."""
    seen = set()
    unique = []
    for c in callers:
        from_id = c.get("from", "")
        # Extract file and line from "file:line:fn" format
        if ":" in from_id:
            parts = from_id.rsplit(":", 2)
            file_part = parts[0] if len(parts) >= 2 else from_id
            line_part = parts[1] if len(parts) >= 2 else "0"
            key = (file_part, line_part)
        else:
            key = (from_id, "0")
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


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

    # ─── File path lookup ─────────────────────────────
    if _is_file_path(query_name) and domain in (None, "backend"):
        backend = load_backend_registry(workspace)
        matching_nodes = [n for n in backend.get("nodes", []) if n.get("file", "") == query_name]

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

                callers = _deduplicate_callers(
                    get_callers(node["id"], backend.get("edges", []))
                )
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
        "status": "ok",
        "found": False,
        "query": query_name,
        "domain": domain or "auto",
        "action": "CREATE",
        "action_reason": "Name does not exist. Safe to create."
    }


register_command("query", "Query a specific class/id/function", add_args, execute)
