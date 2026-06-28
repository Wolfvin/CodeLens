"""Outline command — Get file structure outline."""

from outline_engine import get_file_outline, get_workspace_outline
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None, help="Specific file to outline")
    parser.add_argument("--detail", choices=["minimal", "normal", "full"], default="normal",
                        help="Detail level")
    parser.add_argument("--all", action="store_true", dest="all_files",
                        help="Outline all files in workspace")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max files to return after pagination (default: 20). "
                             "Use --limit 0 for unlimited.")
    parser.add_argument("--offset", type=int, default=0,
                        help="Offset for pagination of outlines (default: 0)")


def execute(args, workspace):
    if args.all_files:
        result = get_workspace_outline(workspace)
    elif args.file:
        result = get_file_outline(args.file, workspace, detail_level=args.detail)
    else:
        result = get_workspace_outline(workspace)
    # Apply pagination to workspace outlines (issue #17).
    if isinstance(result, dict) and "outlines" in result:
        outlines = result["outlines"]
        total = len(outlines)
        limit = args.limit if args.limit and args.limit > 0 else total
        offset = max(args.offset, 0)
        paginated = outlines[offset:offset + limit]
        result["outlines"] = paginated
        result["total_count"] = total
        result["count"] = len(paginated)
        result["offset"] = offset
        result["limit"] = limit
        result["has_more"] = (offset + limit) < total
    return result


register_command("outline", "Get file structure outline", add_args, execute)
