"""Init command — Initialize .codelens directory with auto-detected config."""

import json
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
    """Initialize .codelens directory with auto-detected config.

    Also creates a default ``.codelens/hooks.json`` with all hooks
    disabled (issue #122) so users can discover and enable the MCP
    post_tool hook without having to run ``codelens serve`` first.
    """
    workspace = os.path.abspath(workspace)
    codelens_dir = ensure_codelens_dir(workspace)

    # Auto-detect frameworks
    recommended = get_recommended_config(workspace)
    save_config(workspace, recommended)

    # Issue #122: create default hooks.json so users can discover MCP
    # hooks config without running `codelens serve`. The file is created
    # with all hooks disabled (matches mcp_hooks.DEFAULT_CONFIG) — users
    # edit it to enable specific hooks.
    hooks_path = os.path.join(codelens_dir, "hooks.json")
    if not os.path.exists(hooks_path):
        try:
            # Import lazily so `init` works even if mcp_hooks is unavailable
            # (e.g. on minimal installs without MCP dependencies).
            from mcp_hooks import DEFAULT_CONFIG as _HOOKS_DEFAULT
            default_config = _HOOKS_DEFAULT
        except Exception:
            # Fallback: hardcode the same structure that mcp_hooks uses.
            default_config = {
                "hooks": {
                    "post_tool": {
                        "enabled": False,
                        "severity_threshold": "high",
                    }
                }
            }
        try:
            with open(hooks_path, "w", encoding="utf-8") as f:
                json.dump(default_config, f, indent=2)
                f.write("\n")
        except OSError:
            # Non-fatal: hooks.json is optional. MCP server will create
            # it lazily on first hook use if init couldn't.
            pass

    return {
        "status": "ok",
        "workspace": workspace,
        "codelens_dir": codelens_dir,
        "config": recommended,
        "hooks_json_created": os.path.exists(hooks_path),
    }

# Issue #199: deprecated "init" alias registration removed; this module is now an implementation module imported by the "scan" umbrella command.
