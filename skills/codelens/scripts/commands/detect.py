"""Detect command — Detect frameworks and show recommended config."""

import os
from typing import Dict, Any

from framework_detect import detect_frameworks
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return cmd_detect(workspace)


def cmd_detect(workspace: str) -> Dict[str, Any]:
    """Detect frameworks and show recommended config."""
    workspace = os.path.abspath(workspace)
    return detect_frameworks(workspace)


register_command("detect", "Detect frameworks in workspace", add_args, execute)
