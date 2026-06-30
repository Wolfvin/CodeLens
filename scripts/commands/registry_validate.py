"""registry-validate command — Validate registry against file system.

Renamed from `validate` in v8.x to make room for `rule-validate` (rule YAML
validation). The deprecated `validate` alias was removed in issue #100 —
use `registry-validate` for registry checks, or `rule-validate` for rule
YAML validation.
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
    "Validate registry against file system",
    add_args,
    execute,
)
