"""registry-validate command — Validate registry against file system.

Renamed from `validate` in v8.x to make room for `rule-validate` (rule YAML
validation). The old `validate` command name still works as a deprecated alias
(see ``scripts/commands/validate.py``) but prints a one-line stderr warning
and will be removed in a future release.
"""

import sys

from validate_engine import validate_registry
from commands import register_command


def add_args(parser):
    """Register registry-validate arguments."""
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def execute(args, workspace):
    """Execute the registry-validate command.

    Args:
        args: Parsed argparse namespace with ``workspace``.
        workspace: Resolved workspace root path.

    Returns:
        Dict with the registry validation result (``validate_registry``
        return shape).
    """
    return validate_registry(workspace)


register_command(
    "registry-validate",
    "Validate registry against file system (renamed from `validate`)",
    add_args,
    execute,
)
