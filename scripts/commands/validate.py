"""validate command — DEPRECATED alias for ``registry-validate``.

This command was renamed to ``registry-validate`` to make room for the new
``rule-validate`` command (rule YAML validation). It still works for one
release cycle but prints a deprecation warning to stderr. It will be removed
in a future release — switch to ``codelens registry-validate``.
"""

import sys

from validate_engine import validate_registry
from commands import register_command

# Deprecation notice — printed once per invocation to stderr (NOT stdout, which
# is reserved for JSON/machine-readable output). Surfaced in both interactive
# and CI usage so users notice and migrate before the alias is removed.
_DEPRECATION_WARNING = (
    "[CodeLens] DEPRECATED: `codelens validate` is renamed to "
    "`codelens registry-validate`. The old name still works for one release "
    "cycle but will be removed. Use `registry-validate` for registry checks, "
    "or `rule-validate` for rule YAML validation.\n"
)


def add_args(parser):
    """Register validate (deprecated alias) arguments — same as registry-validate."""
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def execute(args, workspace):
    """Execute the deprecated validate command.

    Prints a deprecation warning to stderr, then delegates to
    ``validate_registry`` (same behavior as ``registry-validate``).

    Args:
        args: Parsed argparse namespace with ``workspace``.
        workspace: Resolved workspace root path.

    Returns:
        Dict with the registry validation result.
    """
    print(_DEPRECATION_WARNING, file=sys.stderr, end="")
    return validate_registry(workspace)


# Register under the legacy name so existing scripts / muscle memory keep
# working. The new canonical name is registered in ``registry_validate.py``.
register_command(
    "validate",
    "DEPRECATED — use `registry-validate` instead",
    add_args,
    execute,
)
