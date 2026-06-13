"""Missing-refs command — Detect CSS/HTML mismatch bugs."""

import sys
import os

# Ensure the parent scripts/ directory is on sys.path so we import
# the top-level missing_refs module, not this file itself.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from missing_refs import detect_missing_refs  # noqa: E402
from commands import register_command  # noqa: E402


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return detect_missing_refs(workspace)


register_command("missing-refs", "Detect CSS/HTML mismatch bugs", add_args, execute)
