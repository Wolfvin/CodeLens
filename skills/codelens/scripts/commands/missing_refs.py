"""Missing-refs command — Detect CSS/HTML mismatch bugs."""

from missing_refs import detect_missing_refs
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return detect_missing_refs(workspace)


register_command("missing-refs", "Detect CSS/HTML mismatch bugs", add_args, execute)
