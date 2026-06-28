"""Search command — Search code pattern across workspace."""

import os
from search_engine import search_workspace
from registry import load_config
from commands import register_command


def add_args(parser):
    parser.add_argument("pattern", help="Regex pattern to search for")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--type", dest="file_type", default=None,
                        help="File type filter (html, css, js, ts, tsx, rust, python, vue, svelte)")
    parser.add_argument("--file", default=None, help="Filter by file path substring")
    parser.add_argument("--max-results", type=int, default=200, help="Max results (default 200)")
    parser.add_argument("--context", type=int, default=0, help="Context lines around match")
    parser.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    parser.add_argument("--whole-word", action="store_true", help="Match whole words only")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max matches to return after pagination (default: 20). "
                             "Use --limit 0 for unlimited (still bounded by --max-results).")
    parser.add_argument("--offset", type=int, default=0,
                        help="Offset for pagination (default: 0)")


def execute(args, workspace):
    config = load_config(os.path.abspath(workspace))
    # Resolve limit: --top is an alias for --limit (per issue #17 spec).
    top_n = getattr(args, 'top', None)
    if top_n is not None and getattr(args, 'limit', None) is None:
        args.limit = top_n
    result = search_workspace(
        workspace, args.pattern,
        file_type=args.file_type,
        file_filter=args.file,
        max_results=args.max_results,
        context_lines=args.context,
        case_sensitive=not args.ignore_case,
        whole_word=args.whole_word,
        config=config
    )
    # Apply pagination to matches (issue #17).
    if isinstance(result, dict) and "matches" in result:
        matches = result["matches"]
        total = len(matches)
        limit = args.limit if args.limit and args.limit > 0 else total
        offset = max(args.offset, 0)
        paginated = matches[offset:offset + limit]
        result["matches"] = paginated
        result["total_count"] = total
        result["count"] = len(paginated)
        result["offset"] = offset
        result["limit"] = limit
        result["has_more"] = (offset + limit) < total
    return result


register_command("search", "Search code pattern across workspace", add_args, execute)
