# @WHO:   scripts/sync/worktree.py
# @WHAT:  Detect git worktree ↔ CodeLens index mismatch (issue #66 Phase 4).
# @PART:  sync
# @ENTRY: detect_worktree_index_mismatch()
"""Git worktree ↔ CodeLens index mismatch detection.

Why this module exists
----------------------
When a user runs CodeLens inside a git worktree that does not have its
own ``.codelens/`` directory, CodeLens's workspace auto-detection
walks up the directory tree and silently picks up the *main*
checkout's ``.codelens/`` index. That index was built from a different
branch — every subsequent ``query`` / ``trace`` / ``dataflow`` /
``taint`` answer is then grounded in the wrong file set, with no
warning to the user or the agent.

This module answers one question:

    "Is the CodeLens index we are about to read actually indexing the
    working tree we are standing in?"

If not, it returns a structured mismatch record that callers can
surface as a warning (``codelens doctor``) or as a banner field on
MCP tool responses (``mcp_server._handle_tools_call``).

Design constraints
------------------
* **No external deps** — uses ``subprocess`` to call ``git``. Mirrors
  the pattern in ``scripts/git_aware.py``.
* **Python 3.8+** compatible.
* **Git is OPTIONAL** — every public function returns a benign "no
  mismatch" result when git is missing or the workspace is not under
  git control. Never raises.
* **Subprocess-budget aware** — ``detect_worktree_index_mismatch``
  shells out at most twice per call (``show-toplevel`` and
  ``git-common-dir``). Callers that need to call this on every MCP
  tool response should cache the result per workspace — see
  ``MCPServer._worktree_mismatch_cache``.

Public API
----------
* :func:`detect_worktree_index_mismatch` — the main entry point.
* :func:`format_worktree_warning` — human-readable warning for
  ``codelens doctor`` text output.
* :func:`format_worktree_banner` — one-line banner for MCP responses.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, Optional

from utils import logger

# Exit-code threshold for "git not installed" vs "git ran but failed".
# ``git --version`` returns 0 on success. ``FileNotFoundError`` means
# git is not installed at all.
_GIT_NOT_INSTALLED_HINT = "git binary not found on PATH"


def _run_git(workspace: str, args: list) -> Optional[str]:
    """Run ``git`` inside ``workspace`` and return stripped stdout.

    Returns ``None`` if git is unavailable, the workspace is not a git
    repository, or the command exits non-zero. Never raises — callers
    treat ``None`` as "git could not answer" and fall back.

    Mirrors :func:`git_aware._run_git` deliberately rather than
    importing it, because (a) that function is private (underscore
    prefixed) and (b) keeping the sync subpackage self-contained means
    it can be vendored into other tooling without dragging
    ``git_aware`` along.

    Args:
        workspace: Absolute path to the directory to run git in.
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
            timeout=5,  # Same budget as git_aware — generous for slow disks,
                        # short enough to not hang an MCP tool call.
            check=False,  # We inspect returncode ourselves.
        )
    except FileNotFoundError:
        # git not installed — log once at debug so we don't spam.
        logger.debug(_GIT_NOT_INSTALLED_HINT)
        return None
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug(f"worktree: git invocation failed: {exc}")
        return None

    if result.returncode != 0:
        # Most common: "not a git repository" when run outside a repo.
        # stderr has the detail; log at debug so users with
        # CODELENS_DEBUG=1 can see why detection bailed.
        logger.debug(
            f"worktree: git {' '.join(args)} exit={result.returncode} "
            f"stderr={result.stderr.strip()[:200]}"
        )
        return None
    return result.stdout.strip() or None


def _resolve_common_dir(workspace: str, raw: str) -> Optional[str]:
    """Resolve a ``--git-common-dir`` return value to an absolute path.

    ``git rev-parse --git-common-dir`` may return a path relative to
    ``workspace`` (e.g. ``.git`` or ``../../.git``) on some git
    versions when ``workspace`` is not the worktree top-level. We need
    an absolute path so the parent-dir computation in
    :func:`detect_worktree_index_mismatch` works regardless of cwd.
    """
    if not raw:
        return None
    if os.path.isabs(raw):
        return os.path.normpath(raw)
    # Resolve relative to the directory git was run in.
    return os.path.normpath(os.path.join(workspace, raw))


def _find_index_root(start_dir: str, max_depth: int = 10) -> Optional[str]:
    """Walk up from ``start_dir`` looking for a ``.codelens/`` directory.

    This mirrors the walk-up in :func:`codelens._detect_workspace` so
    we detect the *same* index that CodeLens would actually load. If
    we walked a different number of levels, we'd risk reporting a
    mismatch against an index that isn't even being used.

    Args:
        start_dir: Directory to start walking from (usually the workspace).
        max_depth: Maximum number of parent dirs to walk up. Default 10
            matches :func:`codelens._detect_workspace`.

    Returns:
        Absolute path to the directory containing ``.codelens/``, or
        ``None`` if no ``.codelens/`` was found within ``max_depth``
        levels.
    """
    current = os.path.abspath(start_dir)
    depth = 0
    while depth <= max_depth:
        if os.path.isdir(os.path.join(current, ".codelens")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            # Reached filesystem root.
            break
        current = parent
        depth += 1
    return None


def detect_worktree_index_mismatch(project_root: str) -> Dict[str, Any]:
    """Detect whether ``project_root`` is a worktree using a foreign index.

    This is the main entry point. It answers:

    * Is ``project_root`` inside a git worktree (i.e., not the main
      checkout)?
    * If so, does the worktree have its own ``.codelens/`` index, or
      is CodeLens going to silently walk up and load the main
      checkout's index — which was built from a *different* branch?

    Args:
        project_root: Absolute path to the directory CodeLens is
            operating on. Usually the resolved workspace.

    Returns:
        A dict with the following shape (always present, never raises):

        ``mismatch`` (bool)
            ``True`` if CodeLens is about to read an index that does
            not belong to the current worktree. Callers should surface
            a warning.

        ``reason`` (str)
            Machine-readable reason code:

            * ``"not_a_git_repo"`` — git not installed or
              ``project_root`` is not inside a git repository.
            * ``"not_a_worktree"`` — main checkout, no worktree
              concerns.
            * ``"worktree_has_own_index"`` — worktree, but its own
              ``.codelens/`` exists. No drift.
            * ``"no_index_found"`` — worktree, and no ``.codelens/``
              anywhere up the tree. No drift (nothing to be wrong).
            * ``"worktree_uses_main_index"`` — MISMATCH. Worktree is
              going to read the main checkout's index.

        ``worktree_root`` (str | None)
            Absolute path to the worktree's top level (the result of
            ``git rev-parse --show-toplevel``). ``None`` if not in a
            git repo.

        ``main_checkout_root`` (str | None)
            Absolute path to the main checkout's root. ``None`` if not
            in a git repo or if git could not resolve the common dir.

        ``index_root`` (str | None)
            Absolute path to the directory that holds the
            ``.codelens/`` CodeLens will actually load. ``None`` if no
            ``.codelens/`` exists anywhere up the tree.

        ``suggestion`` (str | None)
            One-line remediation hint shown to the user. ``None`` when
            there is no mismatch.

    The function is intentionally side-effect free — it does not write
    anything, does not mutate the registry, and does not auto-run
    ``codelens init``. The caller decides what to do with the result.
    """
    # Defensive: ensure project_root is a string and exists, but do
    # NOT raise — return a benign "no mismatch" so callers can keep
    # operating. This matches the spirit of git_aware: detection
    # failure must never break the actual work.
    if not project_root or not isinstance(project_root, str):
        return _no_mismatch("not_a_git_repo")
    if not os.path.isdir(project_root):
        return _no_mismatch("not_a_git_repo")

    # ─── Step 1: git worktree root ────────────────────────────────
    toplevel_raw = _run_git(project_root, ["rev-parse", "--show-toplevel"])
    if toplevel_raw is None:
        return _no_mismatch("not_a_git_repo")
    worktree_root = os.path.abspath(toplevel_raw)

    # ─── Step 2: git common dir (the main repo's .git) ───────────
    common_raw = _run_git(project_root, ["rev-parse", "--git-common-dir"])
    if common_raw is None:
        # Some very old git versions don't know --git-common-dir. We
        # can't reliably detect a worktree without it — bail to "no
        # mismatch" rather than risk a false positive.
        return _no_mismatch("not_a_git_repo")

    common_dir = _resolve_common_dir(project_root, common_raw)
    if not common_dir:
        return _no_mismatch("not_a_git_repo")

    # The common dir is always <main_checkout>/.git (or
    # <main_checkout>/.git for bare-style worktrees). The main
    # checkout root is the parent.
    main_checkout_root = os.path.dirname(common_dir)

    # If the worktree root equals the main checkout root, we're in the
    # main checkout — no worktree concerns. But we still know the
    # worktree_root and main_checkout_root (they're the same path),
    # so populate them for callers that want to display the resolved
    # paths regardless of mismatch state.
    if os.path.abspath(worktree_root) == os.path.abspath(main_checkout_root):
        # Walk up to find the index (mirrors codelens._detect_workspace).
        index_root = _find_index_root(project_root)
        return {
            "mismatch": False,
            "reason": "not_a_worktree" if index_root else "no_index_found",
            "worktree_root": worktree_root,
            "main_checkout_root": main_checkout_root,
            "index_root": index_root,
            "suggestion": None,
        }

    # ─── Step 3: where does .codelens/ actually live? ────────────
    # Walk up from the *project_root* (which may be a subdirectory of
    # the worktree root, not the worktree root itself) so we find the
    # same index that codelens._detect_workspace would find.
    index_root = _find_index_root(project_root)

    if index_root is None:
        # No .codelens anywhere — not a mismatch per se, just an
        # uninitialised workspace. The user will get a "run codelens
        # init" prompt elsewhere; we don't double up.
        return {
            "mismatch": False,
            "reason": "no_index_found",
            "worktree_root": worktree_root,
            "main_checkout_root": main_checkout_root,
            "index_root": None,
            "suggestion": None,
        }

    # If the index lives inside the worktree root, the worktree has
    # its own index — that's the correct setup.
    if os.path.abspath(index_root) == os.path.abspath(worktree_root):
        return {
            "mismatch": False,
            "reason": "worktree_has_own_index",
            "worktree_root": worktree_root,
            "main_checkout_root": main_checkout_root,
            "index_root": index_root,
            "suggestion": None,
        }

    # MISMATCH: the index we're about to read is in the main checkout
    # (or some other ancestor), not in this worktree. Reading it will
    # return symbols from a different branch.
    return {
        "mismatch": True,
        "reason": "worktree_uses_main_index",
        "worktree_root": worktree_root,
        "main_checkout_root": main_checkout_root,
        "index_root": index_root,
        "suggestion": (
            f"Run 'codelens init -i {worktree_root}' to build a "
            f"worktree-local index, or switch to the main checkout at "
            f"{main_checkout_root}."
        ),
    }


def _no_mismatch(reason: str) -> Dict[str, Any]:
    """Return a benign mismatch dict with the given reason code."""
    return {
        "mismatch": False,
        "reason": reason,
        "worktree_root": None,
        "main_checkout_root": None,
        "index_root": None,
        "suggestion": None,
    }


def format_worktree_warning(mismatch: Dict[str, Any]) -> str:
    """Format a mismatch record as a multi-line human-readable warning.

    Used by ``codelens doctor`` text output. Returns an empty string
    when there is no mismatch — doctor calls this unconditionally and
    only prints the result if non-empty.

    Args:
        mismatch: A dict returned by :func:`detect_worktree_index_mismatch`.

    Returns:
        Multi-line warning string, or ``""`` if no mismatch.
    """
    if not mismatch or not mismatch.get("mismatch"):
        return ""
    parts = [
        "WORKTREE INDEX MISMATCH",
        f"  worktree:        {mismatch.get('worktree_root')}",
        f"  main checkout:   {mismatch.get('main_checkout_root')}",
        f"  index loaded:    {mismatch.get('index_root')}",
        "  problem:         CodeLens is reading the main checkout's index,",
        "                   which was built from a different branch.",
    ]
    suggestion = mismatch.get("suggestion")
    if suggestion:
        parts.append(f"  fix:             {suggestion}")
    return "\n".join(parts)


def format_worktree_banner(mismatch: Dict[str, Any]) -> str:
    """Format a mismatch record as a single-line banner for MCP responses.

    Returns an empty string when there is no mismatch, so callers can
    unconditionally prepend the banner without producing empty noise
    on every response.

    Args:
        mismatch: A dict returned by :func:`detect_worktree_index_mismatch`.

    Returns:
        One-line banner string, or ``""`` if no mismatch.
    """
    if not mismatch or not mismatch.get("mismatch"):
        return ""
    return (
        f"⚠️ WORKTREE INDEX MISMATCH: workspace is in a git worktree at "
        f"{mismatch.get('worktree_root')} but CodeLens is reading the index "
        f"at {mismatch.get('index_root')} (main checkout, different branch). "
        f"{mismatch.get('suggestion') or ''}"
    ).strip()
