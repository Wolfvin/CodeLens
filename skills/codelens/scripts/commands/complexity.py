"""Complexity command — Compute cyclomatic/cognitive complexity."""

from complexity_engine import compute_complexity
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--name", default=None, help="Specific function to analyze")
    parser.add_argument("--file", default=None, help="Filter by file path")
    parser.add_argument("--threshold", type=int, default=None,
                        help="Minimum complexity threshold to report")
    parser.add_argument("--sort", dest="sort_by", default=None,
                        choices=["complexity", "cognitive", "loc"],
                        help="Sort results by metric")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max number of functions to return")
    parser.add_argument("--max-files", type=int, default=None,
                        help="Max files to scan (default 3000)")


def execute(args, workspace):
    kwargs = {}
    if args.max_files is not None:
        kwargs["max_files"] = args.max_files
    return compute_complexity(workspace, function_name=args.name,
                              file_filter=args.file, threshold=args.threshold,
                              sort_by=args.sort_by, limit=args.limit, **kwargs)


register_command("complexity", "Compute cyclomatic/cognitive complexity", add_args, execute)
