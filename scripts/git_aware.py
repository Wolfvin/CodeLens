"""Git-aware utilities for CodeLens (issue #14).

Provides optional git-diff based change detection so that incremental scans
can target exactly the files git knows changed, instead of relying solely on
filesystem mtime polling. All functions degrade gracefully when git is not
available or the workspace is not a git repository — they return ``None`` /
``[]`` / ``False`` so callers can fall back to the existing mtime path.

Design constraints (see BOS spec for issue #14):
- No external deps (uses ``subprocess`` to call ``git`` — no GitPython).
- Python 3.8+ compatible.
- Every public function has a docstring.
- Git is OPTIONAL: every function must work when git is missing or the
  workspace is not under git control.

The "last indexed" git SHA + branch are persisted in a new ``registry_meta``
table (created by :func:`init_registry_meta`) so subsequent scans can diff
against the bookmark instead of HEAD's parent.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from typing import List, Optional

from utils import logger


# ─── SQL DDL for the registry_meta table ──────────────────────────────
# A simple key/value store for git-aware scan bookmarks. Lives alongside
# the existing CodeLens SQLite tables (symbols, refs, files, ...) and the
# graph tables (graph_nodes, graph_edges). Additive — no existing table
# or column is modified.

_CREATE_REGISTRY_META = """
CREATE TABLE IF NOT EXISTS registry_meta (
    key TEXT PRIMARY KEY,
    value TEXT
)
"""

# Keys used in registry_meta.
KEY_LAST_INDEXED_SHA = "last_indexed_sha"
KEY_LAST_INDEXED_BRANCH = "last_indexed_branch"


# ─── Schema initialization ───────────────────────────────────────────

def init_registry_meta(conn: sqlite3.Connection) -> None:
    """Create the ``registry_meta`` table if it does not exist.

    Idempotent — safe to call on every database initialization. Called
    automatically by :class:`persistent_registry.PersistentRegistry` during
    schema init so the table always exists by the time any git-aware
    function tries to read or write a bookmark.

    Args:
        conn: An open ``sqlite3.Connection``. Caller owns the connection and
              is responsible for committing / closing.
    """
    try:
        conn.execute(_CREATE_REGISTRY_META)
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"registry_meta schema init error: {e}")


# ─── Internal git invocation helpers ─────────────────────────────────

def _run_git(workspace: str, args: List[str]) -> Optional[str]:
    """Run a ``git`` command inside ``workspace`` and return stdout (stripped).

    Returns ``None`` if git is unavailable, the workspace is not a git
    repository, or the command exits non-zero. Never raises — callers
    should treat ``None`` as "git could not answer" and fall back.

    Args:
        workspace: Absolute path to the workspace root.
        args: Arguments to pass to ``git`` (e.g. ``["rev-parse", "HEAD"]``).

    Returns:
        Stripped stdout on success, ``None`` on any failure.
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except FileNotFoundError:
        # git binary not installed
        return None
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug(f"git invocation failed: {e}")
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


# ─── Public API ──────────────────────────────────────────────────────

def get_current_sha(workspace: str) -> Optional[str]:
    """Return the HEAD commit SHA of the git repo at ``workspace``.

    Args:
        workspace: Absolute path to the workspace root.

    Returns:
        The 40-char commit SHA, or ``None`` if git is unavailable, the
        workspace is not a git repo, or HEAD does not point at a commit
        (e.g. an empty repo with no commits yet).
    """
    return _run_git(workspace, ["rev-parse", "HEAD"])


def get_current_branch(workspace: str) -> Optional[str]:
    """Return the current branch name of the git repo at ``workspace``.

    Returns ``"HEAD"`` (detached HEAD) when applicable. Returns ``None``
    if git is unavailable or the workspace is not a git repo.

    Args:
        workspace: Absolute path to the workspace root.

    Returns:
        Branch name string (e.g. ``"main"``, ``"feat/x"``), ``"HEAD"`` for
        detached HEAD, or ``None`` on failure.
    """
    return _run_git(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])


def get_changed_files(workspace: str, since_sha: Optional[str] = None) -> List[str]:
    """Return a list of file paths changed in the git repo at ``workspace``.

    Uses ``git diff --name-only`` to enumerate changes. Paths are relative
    to ``workspace`` (matches git's default output).

    Two modes:

    * ``since_sha=None`` — working-tree changes vs HEAD (uncommitted edits
      + staged changes). Equivalent to ``git diff HEAD --name-only``.
    * ``since_sha=<sha>`` — changes between ``<sha>`` and HEAD, plus any
      uncommitted working-tree changes. Implemented as ``git diff <sha>
      --name-only`` which includes both committed and uncommitted deltas
      relative to ``<sha>``.

    Args:
        workspace: Absolute path to the workspace root.
        since_sha: Optional git commit SHA to diff against.

    Returns:
        List of relative file paths (may be empty). Returns ``[]`` if git
        is unavailable or the workspace is not a git repo.
    """
    args = ["diff", "--name-only"]
    if since_sha:
        args.append(since_sha)
    else:
        args.append("HEAD")
    out = _run_git(workspace, args)
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def get_untracked_files(workspace: str) -> List[str]:
    """Return git-untracked file paths in ``workspace`` (excluding gitignored).

    Uses ``git ls-files --others --exclude-standard`` so gitignored files
    (node_modules, dist, .env, etc.) are NOT returned. Required because
    :func:`get_changed_files` only reports tracked files — newly created
    files that have not yet been ``git add`` -ed would otherwise be
    invisible to incremental scans.

    Args:
        workspace: Absolute path to the workspace root.

    Returns:
        List of relative file paths (may be empty). Returns ``[]`` if git
        is unavailable or the workspace is not a git repo.
    """
    out = _run_git(workspace, ["ls-files", "--others", "--exclude-standard"])
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


# ─── registry_meta read/write ────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection to ``db_path`` (creates parent dir)."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def get_meta_value(db_path: str, key: str) -> Optional[str]:
    """Read a single key from the ``registry_meta`` table.

    Args:
        db_path: Absolute path to the SQLite database file.
        key: The metadata key to read.

    Returns:
        The stored value, or ``None`` if the key is absent, the table does
        not exist, or the database file is missing.
    """
    if not os.path.exists(db_path):
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM registry_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None
    except sqlite3.Error as e:
        logger.debug(f"get_meta_value('{key}') error: {e}")
        return None
    finally:
        conn.close()


def set_meta_value(db_path: str, key: str, value: Optional[str]) -> None:
    """Upsert a single key in the ``registry_meta`` table.

    Creates the table if it does not exist (idempotent). Deleting a key is
    done by passing ``value=None``.

    Args:
        db_path: Absolute path to the SQLite database file.
        key: The metadata key to write.
        value: The metadata value to write, or ``None`` to delete the key.
    """
    conn = _connect(db_path)
    try:
        init_registry_meta(conn)
        if value is None:
            conn.execute(
                "DELETE FROM registry_meta WHERE key = ?", (key,)
            )
        else:
            conn.execute(
                "INSERT INTO registry_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"set_meta_value('{key}') error: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_last_indexed_sha(workspace: str, db_path: str) -> Optional[str]:
    """Return the last-indexed git SHA bookmark for ``workspace``.

    Args:
        workspace: Absolute path to the workspace root (unused but kept for
                   API symmetry with the other git-aware functions).
        db_path: Absolute path to the SQLite database file.

    Returns:
        The previously stored HEAD SHA at the time of the last successful
        scan, or ``None`` if no bookmark has been set yet (e.g. first scan
        on a fresh repo, or git was unavailable last time).
    """
    _ = workspace  # API symmetry — workspace not needed to read a key
    return get_meta_value(db_path, KEY_LAST_INDEXED_SHA)


def set_last_indexed_sha(workspace: str, db_path: str, sha: Optional[str]) -> None:
    """Persist the last-indexed git SHA + current branch for ``workspace``.

    Writes both ``last_indexed_sha`` and ``last_indexed_branch`` so that
    :func:`detect_branch_switch` can later compare branches. Passing
    ``sha=None`` clears both bookmarks (used when leaving a non-git repo).

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Absolute path to the SQLite database file.
        sha: The HEAD SHA to bookmark, or ``None`` to clear.
    """
    branch = get_current_branch(workspace) if sha else None
    set_meta_value(db_path, KEY_LAST_INDEXED_SHA, sha)
    set_meta_value(db_path, KEY_LAST_INDEXED_BRANCH, branch)


def get_last_indexed_branch(db_path: str) -> Optional[str]:
    """Return the branch name recorded at the time of the last scan.

    Args:
        db_path: Absolute path to the SQLite database file.

    Returns:
        The branch name string, or ``None`` if no bookmark has been set.
    """
    return get_meta_value(db_path, KEY_LAST_INDEXED_BRANCH)


def detect_branch_switch(workspace: str, db_path: str) -> bool:
    """Detect whether the active git branch changed since the last scan.

    Returns ``True`` only when ALL of the following hold:

    * git is available and the workspace is a git repo,
    * a previous scan bookmarked a SHA + branch,
    * the current HEAD SHA differs from the bookmarked SHA,
    * the current branch name differs from the bookmarked branch name.

    The SHA check is what catches any commit/checkout/amend/rebase; the
    branch-name check is what narrows "HEAD moved" to "user switched
    branches" specifically (so committing on the same branch doesn't
    trigger a branch-switch re-index).

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Absolute path to the SQLite database file.

    Returns:
        ``True`` if a branch switch is detected, ``False`` otherwise
        (including when git is unavailable).
    """
    current_sha = get_current_sha(workspace)
    if not current_sha:
        return False
    last_sha = get_last_indexed_sha(workspace, db_path)
    if not last_sha:
        return False
    if current_sha == last_sha:
        return False
    current_branch = get_current_branch(workspace)
    last_branch = get_last_indexed_branch(db_path)
    if not current_branch or not last_branch:
        return False
    return current_branch != last_branch


def rescan_recommended(workspace: str, db_path: str) -> bool:
    """Return ``True`` when a re-scan is recommended for ``workspace``.

    A re-scan is recommended when EITHER:

    * :func:`detect_branch_switch` returns ``True`` (branch switch rewrote
      many files at once), OR
    * :func:`get_changed_files` reports any working-tree changes since
      the last indexed SHA.

    This is the "do I need to re-scan?" predicate used by the
    ``git-status`` command.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Absolute path to the SQLite database file.

    Returns:
        ``True`` if a re-scan is recommended, ``False`` otherwise.
    """
    if detect_branch_switch(workspace, db_path):
        return True
    last_sha = get_last_indexed_sha(workspace, db_path)
    if not last_sha:
        # Never indexed under git — recommend a scan if there's any working
        # tree state to capture (which there always is on a first scan).
        return bool(get_current_sha(workspace))
    return len(get_changed_files(workspace, since_sha=last_sha)) > 0
