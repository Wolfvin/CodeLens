"""Init command — Initialize .codelens directory with auto-detected config."""

import os
from typing import Dict, Any

from registry import ensure_codelens_dir, save_config
from framework_detect import get_recommended_config
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return cmd_init(workspace)


def cmd_init(workspace: str) -> Dict[str, Any]:
    """Initialize .codelens directory with auto-detected config."""
    workspace = os.path.abspath(workspace)
    codelens_dir = ensure_codelens_dir(workspace)

    # Auto-detect frameworks
    recommended = get_recommended_config(workspace)
    save_config(workspace, recommended)

    return {
        "status": "ok",
        "workspace": workspace,
        "codelens_dir": codelens_dir,
        "config": recommended
    }


register_command("init", "Initialize .codelens with auto-detected config", add_args, execute)
