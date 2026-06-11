"""Refactor-safe command — Pre-flight rename/move safety check."""

from refactor_safe_engine import check_refactor_safety
from commands import register_command


def add_args(parser):
    parser.add_argument("name", help="Symbol name to rename/move")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--action", choices=["rename", "move"], default="rename",
                        help="Action type (rename or move)")
    parser.add_argument("--new-name", default=None, help="New name (for rename) or new path (for move)")


def execute(args, workspace):
    return check_refactor_safety(
        args.name, workspace,
        action=args.action,
        new_name=args.new_name
    )


register_command("refactor-safe", "Pre-flight rename/move safety check", add_args, execute)
