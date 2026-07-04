"""Symbols command — Search registry symbols by name."""

from search_engine import search_symbols
from commands import register_command


def add_args(parser):
    parser.add_argument("name", help="Symbol name to search")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                        help="Domain to search")
    parser.add_argument("--fuzzy", action="store_true", help="Allow partial/fuzzy matching")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max results to return (default: 20). Use --limit 0 for unlimited.")
    parser.add_argument("--offset", type=int, default=0,
                        help="Offset for pagination (default: 0)")


def execute(args, workspace):
    # search_symbols caps at max_results internally; we add an outer
    # pagination layer so callers can paginate beyond the engine's own cap.
    max_results = 500  # engine-level cap; --limit paginates within this
    result = search_symbols(
        workspace, args.name,
        domain=args.domain, fuzzy=args.fuzzy,
        max_results=max_results,
    )
    # Apply pagination (issue #17).
    if isinstance(result, dict) and "results" in result:
        results = result["results"]
        total = len(results)
        limit = args.limit if args.limit and args.limit > 0 else total
        offset = max(args.offset, 0)
        paginated = results[offset:offset + limit]
        result["results"] = paginated
        result["total_count"] = total
        result["count"] = len(paginated)
        result["offset"] = offset
        result["limit"] = limit
        result["has_more"] = (offset + limit) < total
    return result


register_command("symbols", "Search symbols in registry by name", add_args, execute,

hidden=True,

deprecated_alias_for='search',

)
