"""Debug-leak command — Detect leftover debug code."""

from debugleak_engine import detect_debug_leaks
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--category", choices=["console_log", "print_statement", "debugger",
                        "todo_fixme", "commented_code", "test_skip", "mock_data", "dev_only"],
                        default=None, help="Filter by leak category")


def execute(args, workspace):
    return detect_debug_leaks(workspace, category=args.category)


register_command("debug-leak", "Detect leftover debug code", add_args, execute)
