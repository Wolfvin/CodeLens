"""Init command — Initialize .codelens directory with auto-detected config.

Issue #15 Phase 1: ``init --add-repo <path>`` appends an additional repo
root to the workspace's ``workspace_roots`` config, enabling cross-repo
intelligence features (trace --cross-repo, combined architecture —
Phase 2). The primary workspace is always first in the roots list;
``--add-repo`` registers additional repos that belong to the same
logical workspace (e.g. a shared library, a sibling service).
"""

import json
import os
from typing import Dict, Any

from registry import (
    add_workspace_root,
    ensure_codelens_dir,
    get_workspace_roots,
    save_config,
)
from framework_detect import get_recommended_config
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    # Issue #15 Phase 1: register an additional repo root that belongs
    # to the same logical workspace. Repeatable (--add-repo A --add-repo B)
    # so users can register multiple sibling repos in one init call.
    parser.add_argument(
        "--add-repo", action="append", default=[], metavar="PATH",
        help="Additional repo root to register in workspace_roots "
             "(issue #15 Phase 1). Repeatable. The path must be an "
             "existing directory. Idempotent — re-adding an already-"
             "registered path is a no-op.",
    )


def execute(args, workspace):
    # Issue #15 Phase 1: if --add-repo is supplied, route to the
    # add_workspace_root helper instead of the normal init flow. This
    # lets users register additional repos on an already-initialized
    # workspace without re-running framework detection.
    if getattr(args, "add_repo", None):
        results = []
        for repo_path in args.add_repo:
            results.append(add_workspace_root(workspace, repo_path))
        return {
            "status": "ok",
            "workspace": os.path.abspath(workspace),
            "workspace_roots": get_workspace_roots(workspace),
            "add_repo_results": results,
        }
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
    # Issue #15 Phase 1: ensure workspace_roots is present in the
    # initial config (empty list = single-repo mode). load_config
    # merges this default, but save_config writes the merged dict —
    # so we set it explicitly here to guarantee the field appears in
    # the written file even on first init.
    if "workspace_roots" not in recommended:
        recommended["workspace_roots"] = []
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


register_command("init", "Initialize .codelens with auto-detected config", add_args, execute)
