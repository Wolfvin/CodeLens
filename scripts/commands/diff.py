"""Diff command — Compare registry snapshots, with optional git-aware delta.

Default mode (unchanged from pre-8.2): compares the current flat
registry against the last saved snapshot via diff_engine.

Git-aware mode (``--git-aware``, issue #14): reports the files git
knows changed since the last indexed SHA, the symbols defined in those
files (from the flat backend registry), and the downstream impact
(callers of those symbols from the graph tables, when populated).

The two modes are complementary — snapshot diff captures scan-to-scan
deltas, git-aware diff captures the uncommitted-scratch delta agents
typically care about right before a write.
"""

import os
from typing import Any, Dict, List

from diff_engine import (
    diff_current_vs_last, diff_snapshots, save_snapshot, list_snapshots,
)
from commands import register_command
from utils import logger


def add_args(parser):
    """Register diff CLI arguments."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--snapshot1", default=None,
        help="First snapshot ID (default: second-to-last)",
    )
    parser.add_argument(
        "--snapshot2", default=None,
        help="Second snapshot ID (default: last)",
    )
    parser.add_argument(
        "--list-snapshots", action="store_true",
        help="List available snapshots",
    )
    parser.add_argument(
        "--git-aware", action="store_true",
        help="Show git-diff delta since last indexed SHA: changed files, "
             "symbols in those files, and downstream impact (callers) "
             "from the graph tables. Falls back to 'git unavailable' "
             "status when git is not available or the workspace is not "
             "a git repo.",
    )


def execute(args, workspace):
    """Execute the diff command.

    Dispatches to git-aware mode when ``--git-aware`` is set, otherwise
    preserves the pre-8.2 snapshot-diff behavior.
    """
    if getattr(args, "git_aware", False):
        return cmd_diff_git_aware(workspace)
    if args.list_snapshots:
        snaps = list_snapshots(workspace)
        return {"status": "ok", "snapshots": snaps}
    elif args.snapshot1 or args.snapshot2:
        return diff_snapshots(workspace, args.snapshot1, args.snapshot2)
    else:
        return diff_current_vs_last(workspace)


def cmd_diff_git_aware(workspace: str) -> Dict[str, Any]:
    """Build the git-aware diff report for ``workspace``.

    Combines three views into one call:
    1. ``changed_files`` — paths git knows changed since the last
       indexed SHA (tracked) plus untracked new files.
    2. ``symbols`` — backend flat-registry nodes whose ``file`` field
       matches a changed path. Gives agents the symbol-level delta.
    3. ``impact`` — for each changed symbol, the direct callers from
       the graph tables (``graph_model.query_callers``). Empty when
       the graph tables aren't populated (e.g. incremental scan only
       — see issue #25).

    Args:
        workspace: Absolute path to the workspace root.

    Returns:
        Dict with: status, workspace, git_available, last_indexed_sha,
        current_sha, changed_files[], symbols[], impact[]. ``status``
        is always ``"ok"`` — git-unavailable is reported via
        ``git_available=False`` (not an error).
    """
    workspace = os.path.abspath(workspace)

    try:
        from git_aware import (
            get_current_sha, get_last_indexed_sha, get_changed_files,
            get_untracked_files,
        )
    except ImportError:
        return {
            "status": "ok",
            "workspace": workspace,
            "git_available": False,
            "message": "git_aware module not available",
            "changed_files": [],
            "symbols": [],
            "impact": [],
        }

    try:
        from graph_model import _default_db_path
        db_path = _default_db_path(workspace)
    except ImportError:
        db_path = os.path.join(workspace, ".codelens", "codelens.db")

    current_sha = get_current_sha(workspace)
    if not current_sha:
        return {
            "status": "ok",
            "workspace": workspace,
            "git_available": False,
            "message": "workspace is not a git repo (or git unavailable)",
            "changed_files": [],
            "symbols": [],
            "impact": [],
        }

    last_sha = get_last_indexed_sha(workspace, db_path)
    # Tracked changes since last index (or working-tree vs HEAD when no
    # bookmark yet) + untracked new files.
    changed_rel = set(get_changed_files(workspace, since_sha=last_sha))
    changed_rel |= set(get_untracked_files(workspace))
    changed_files = sorted(changed_rel)

    # Symbols defined in the changed files (from the flat backend registry).
    symbols: List[Dict[str, Any]] = []
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        for node in backend.get("nodes", []):
            if node.get("file", "") in changed_rel:
                symbols.append({
                    "id": node.get("id", ""),
                    "name": node.get("fn", node.get("name", "")),
                    "type": node.get("type", "function"),
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                })
    except Exception:
        logger.debug("git-aware diff: failed to read backend registry", exc_info=True)

    # Downstream impact — callers of each changed symbol from the graph.
    # Empty when graph tables aren't populated (e.g. incremental-only scan
    # — see issue #25). That's a known gap, not a bug in this command.
    impact: List[Dict[str, Any]] = []
    try:
        from graph_model import (
            graph_tables_populated, find_nodes_by_name, query_callers,
        )
        if graph_tables_populated(db_path) and symbols:
            for sym in symbols:
                # find_nodes_by_name matches by name (not file), so we
                # post-filter to the changed file to avoid pulling in
                # same-named symbols from other files.
                matches = find_nodes_by_name(sym["name"], db_path)
                matches = [m for m in matches if m.get("file") == sym["file"]]
                callers: List[Dict[str, Any]] = []
                for m in matches:
                    for c in query_callers(m["node_id"], db_path, max_depth=1):
                        callers.append({
                            "caller": c.get("name", ""),
                            "caller_file": c.get("file", ""),
                            "caller_line": c.get("line", 0),
                            "called": sym["name"],
                            "called_file": sym["file"],
                        })
                if callers:
                    impact.append({
                        "symbol": sym["name"],
                        "file": sym["file"],
                        "callers_count": len(callers),
                        "callers": callers,
                    })
    except Exception:
        logger.debug("git-aware diff: graph impact lookup failed", exc_info=True)

    return {
        "status": "ok",
        "workspace": workspace,
        "git_available": True,
        "current_sha": current_sha,
        "last_indexed_sha": last_sha,
        "changed_files_count": len(changed_files),
        "changed_files": changed_files,
        "symbols_count": len(symbols),
        "symbols": symbols,
        "impact": impact,
    }


register_command(
    "diff",
    "Compare registry snapshots (--git-aware for git-diff delta + impact)",
    add_args,
    execute,
)

