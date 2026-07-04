"""Git-status command — Show git-aware scan state (issue #14).

Reports the current HEAD SHA + branch, the last-indexed SHA + branch
(stored in registry_meta), the number of changed files since the last
index, and whether a re-scan is recommended. Designed for AI agents
that need a single-call 'do I need to re-scan?' check.

All fields degrade gracefully to None / 0 / False when git is
unavailable or the workspace is not a git repo.
"""

import os
from typing import Any, Dict

from commands import register_command
from utils import logger


def add_args(parser):
    """Register git-status CLI arguments."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def execute(args, workspace):
    """Execute the git-status command.

    Returns a dict with: status, workspace, git_available, current_sha,
    current_branch, last_indexed_sha, last_indexed_branch,
    changed_files_count, branch_switch_detected, rescan_recommended.
    """
    return cmd_git_status(workspace)


def cmd_git_status(workspace: str) -> Dict[str, Any]:
    """Build the git-aware status report for ``workspace``.

    Reads the last-indexed bookmark from ``registry_meta`` and compares
    it to the current HEAD. Used by AI agents to decide whether a
    re-scan is needed without running a full diff themselves.

    Args:
        workspace: Absolute path to the workspace root.

    Returns:
        Dict with the fields documented in :func:`execute`. ``status``
        is always ``"ok"`` — git-unavailable is not an error condition,
        it's reported via ``git_available=False``.
    """
    workspace = os.path.abspath(workspace)

    # Lazy import so the command still registers when git_aware is
    # removed by a downstream fork. graph_model import is for the
    # default db path; if it's missing we fall back to the conventional
    # path string.
    try:
        from git_aware import (
            get_current_sha, get_current_branch,
            get_last_indexed_sha, get_last_indexed_branch,
            get_changed_files, detect_branch_switch,
            rescan_recommended,
        )
    except ImportError:
        logger.debug("git_aware module not available; git-status will report unavailable")
        return {
            "status": "ok",
            "workspace": workspace,
            "git_available": False,
            "current_sha": None,
            "current_branch": None,
            "last_indexed_sha": None,
            "last_indexed_branch": None,
            "changed_files_count": 0,
            "branch_switch_detected": False,
            "rescan_recommended": False,
        }

    try:
        from graph_model import _default_db_path
        db_path = _default_db_path(workspace)
    except ImportError:
        db_path = os.path.join(workspace, ".codelens", "codelens.db")

    current_sha = get_current_sha(workspace)
    git_available = current_sha is not None

    if not git_available:
        return {
            "status": "ok",
            "workspace": workspace,
            "git_available": False,
            "current_sha": None,
            "current_branch": None,
            "last_indexed_sha": get_last_indexed_sha(workspace, db_path),
            "last_indexed_branch": get_last_indexed_branch(db_path),
            "changed_files_count": 0,
            "branch_switch_detected": False,
            "rescan_recommended": False,
        }

    current_branch = get_current_branch(workspace)
    last_sha = get_last_indexed_sha(workspace, db_path)

    # Changed files since last index. If no bookmark yet, count working
    # tree changes vs HEAD (which is what an agent would care about
    # before the first scan-after-install).
    if last_sha:
        changed_files = get_changed_files(workspace, since_sha=last_sha)
    else:
        changed_files = get_changed_files(workspace, since_sha=None)

    branch_switch = detect_branch_switch(workspace, db_path)
    rescan = rescan_recommended(workspace, db_path)

    return {
        "status": "ok",
        "workspace": workspace,
        "git_available": True,
        "current_sha": current_sha,
        "current_branch": current_branch,
        "last_indexed_sha": last_sha,
        "last_indexed_branch": get_last_indexed_branch(db_path),
        "changed_files_count": len(changed_files),
        "changed_files": sorted(changed_files),
        "branch_switch_detected": branch_switch,
        "rescan_recommended": rescan,
    }


register_command(
    "git-status",
    "Show git-aware scan state (SHA, branch, changed files, rescan recommendation)",
    add_args,
    execute,
hidden=True,
deprecated_alias_for='history',
)
