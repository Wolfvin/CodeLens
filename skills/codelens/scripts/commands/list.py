"""List command — List entries with filter."""

import os
from typing import Dict, Any

from registry import load_frontend_registry, load_backend_registry
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                        help="Domain to list")
    parser.add_argument("--filter", dest="filter_type",
                        choices=["all", "dead", "duplicate_define", "duplicate_ref", "collision", "active"],
                        default="all", help="Filter by status")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max results to return (default: 200)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Offset for pagination (default: 0)")


def execute(args, workspace):
    return cmd_list(workspace, args.domain, args.filter_type,
                    limit=getattr(args, 'limit', 200),
                    offset=getattr(args, 'offset', 0))


def cmd_list(workspace: str, domain: str, filter_type: str = "all",
             limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    """List all entries with optional filter and pagination."""
    workspace = os.path.abspath(workspace)
    results = []

    if domain in ("frontend", "all"):
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            entry = {
                "type": "class",
                "name": cls["name"],
                "ref_count": cls["ref_count"],
                "status": cls["status"]
            }
            if cls.get("css"):
                entry["defined_in"] = f"{cls['css'][0]['path']}:{cls['css'][0]['line']}"

            if filter_type == "all" or cls["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define":
                for css_ref in cls.get("css", []):
                    if css_ref.get("flag") == "duplicate_define":
                        results.append(entry)
                        break

        for id_entry in frontend.get("ids", []):
            entry = {
                "type": "id",
                "name": id_entry["name"],
                "ref_count": id_entry["ref_count"],
                "status": id_entry["status"]
            }
            if id_entry.get("defined_in_html"):
                entry["defined_in"] = f"{id_entry['defined_in_html'][0]['path']}:{id_entry['defined_in_html'][0]['line']}"

            if filter_type == "all" or id_entry["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define":
                for css_ref in id_entry.get("css", []):
                    if css_ref.get("flag") == "duplicate_define":
                        results.append(entry)
                        break

    if domain in ("backend", "all"):
        backend = load_backend_registry(workspace)

        for node in backend.get("nodes", []):
            entry = {
                "type": "function",
                "name": node["fn"],
                "ref_count": node.get("ref_count", 0),
                "status": node.get("status", "active"),
                "defined_in": f"{node.get('file', '')}:{node.get('line', 0)}"
            }

            if filter_type == "all" or node.get("status") == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define" and node.get("duplicate_define"):
                results.append(entry)

    total = len(results)
    paginated = results[offset:offset + limit]

    # Build summary counts by type and status
    by_type = {}
    by_status = {}
    for r in results:
        t = r.get("type", "unknown")
        s = r.get("status", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "status": "ok",
        "domain": domain,
        "filter": filter_type,
        "total": total,
        "count": len(paginated),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
        "summary": {
            "by_type": by_type,
            "by_status": by_status,
        },
        "results": paginated
    }


register_command("list", "List entries with filter", add_args, execute)
