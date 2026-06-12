"""Debug-leak command — Detect leftover debug code."""

from debugleak_engine import detect_debug_leaks
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--category", choices=["console_log", "print_statement", "debugger",
                        "todo_fixme", "commented_code", "test_skip", "mock_data", "dev_only"],
                        default=None, help="Filter by leak category")
    parser.add_argument("--max-files", type=int, default=None,
                        help="Max files to scan (default: 3000)")


def execute(args, workspace):
    kwargs = {"category": args.category}
    if args.max_files is not None:
        kwargs["max_files"] = args.max_files
    return detect_debug_leaks(workspace, **kwargs)


register_command("debug-leak", "Detect leftover debug code", add_args, execute)
