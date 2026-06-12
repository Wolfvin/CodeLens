"""Validate command — Validate registry against file system."""

from validate_engine import validate_registry
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return validate_registry(workspace)


register_command("validate", "Validate registry against file system", add_args, execute)
