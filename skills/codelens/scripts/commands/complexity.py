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


def execute(args, workspace):
    return compute_complexity(workspace, function_name=args.name,
                              file_filter=args.file, threshold=args.threshold)


register_command("complexity", "Compute cyclomatic/cognitive complexity", add_args, execute)
