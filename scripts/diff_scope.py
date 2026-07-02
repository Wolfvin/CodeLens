# @WHO:   scripts/diff_scope.py
# @WHAT:  DiffScope — git-diff-based file allowlist for --diff-base flag (issue #157)
# @PART:  utils
# @ENTRY: DiffScope.from_ref()
"""
DiffScope — restrict CodeLens analysis to git-changed files only.

Issue #157: ``--diff-base <ref>`` global flag. When set, CodeLens should
only report findings from files that changed relative to ``<ref>``. This
matters in CI: a PR check should flag only NEW issues introduced by the
PR, not pre-existing issues in unchanged files.

Design
------
DiffScope is a thin wrapper around ``git_aware.get_changed_files()`` (and
``get_untracked_files()``). It validates the ref, computes the changed-file
set, and exposes:

- ``DiffScope.from_ref(workspace, ref)`` — factory; returns a DiffScope or
  raises ``DiffScopeError`` on invalid ref / not-a-git-repo
- ``scope.changed_files`` — frozenset of relative paths
- ``scope.is_empty`` — True if the diff is empty (caller should early-exit)
- ``scope.allows(path)`` — True if ``path`` is in the changed-file set
- ``scope.filter_findings(findings, file_key=...)`` — drop findings whose
  file is not in the changed-file set

The class is intentionally pure (no I/O beyond the one-time git diff call
in the factory). ``filter_findings`` handles both relative and absolute
file paths — engines are inconsistent (secrets uses rel_path, check uses
absolute file_path for rule-engine findings), so the filter normalizes both
to relative paths before comparing.

@FLOW:    DIFF_SCOPE_FILTER
@CALLS:   git_aware.get_changed_files() -> List[str]
@CALLS:   git_aware.get_untracked_files() -> List[str]
@MUTATES: none (pure utility — reads git, returns data)
"""

from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet, Iterable, List, Optional

# git_aware is in the same scripts/ directory; the CLI adds scripts/ to
# sys.path before importing. Lazy import so this module can be imported
# in test contexts where git_aware isn't on the path yet.


class DiffScopeError(Exception):
    """Raised when a DiffScope cannot be constructed.

    Common causes:
    - The workspace is not a git repository
    - The ref does not exist (typo, wrong branch name)
    - Git is not installed
    """


class DiffScope:
    """An immutable allowlist of git-changed files for one workspace.

    Construct via :meth:`from_ref`. Once constructed, the instance is
    safe to share across commands — the changed-file set is captured at
    construction time and does not change.
    """

    __slots__ = ("_workspace", "_changed_files", "_base_ref")

    def __init__(self, workspace: str, changed_files: Iterable[str]) -> None:
        self._workspace = os.path.abspath(workspace)
        self._base_ref: Optional[str] = None
        # Normalize: relative paths, forward slashes for cross-platform compare.
        # Handle BOTH separators (os.sep + altsep) so backslash paths from
        # Windows are normalized to forward slashes on any platform.
        normalized = set()
        for p in changed_files:
            if not p:
                continue
            # Store as relative path with OS-native separators
            if os.path.isabs(p):
                try:
                    p = os.path.relpath(p, self._workspace)
                except ValueError:
                    # On Windows, relpath across drives raises — keep as-is
                    pass
            # Normalize to forward slashes for stable comparison.
            # Replace both os.sep and os.altsep (Windows: \ and /).
            p = p.replace("\\", "/")
            if os.altsep and os.altsep != "/":
                p = p.replace(os.altsep, "/")
            normalized.add(p)
        self._changed_files: FrozenSet[str] = frozenset(normalized)

    @property
    def workspace(self) -> str:
        """Absolute path to the workspace root."""
        return self._workspace

    @property
    def changed_files(self) -> FrozenSet[str]:
        """FrozenSet of changed file paths (relative, forward-slash)."""
        return self._changed_files

    @property
    def is_empty(self) -> bool:
        """True if no files changed relative to the base ref.

        Callers should check this and early-exit with a clear message
        rather than running analysis that would produce zero findings.
        """
        return len(self._changed_files) == 0

    @property
    def changed_count(self) -> int:
        """Number of changed files."""
        return len(self._changed_files)

    def allows(self, path: str) -> bool:
        """Return True if ``path`` is in the changed-file allowlist.

        Handles both absolute and relative paths. Paths are normalized
        to relative + forward-slash before comparison so the check works
        cross-platform.

        Args:
            path: A file path (absolute or relative to workspace).

        Returns:
            True if the path is in the changed-file set.
        """
        if not path:
            return False
        # Normalize to relative + forward slash (same logic as __init__)
        p = path
        if os.path.isabs(p):
            try:
                p = os.path.relpath(p, self._workspace)
            except ValueError:
                # Windows cross-drive — fall through with original
                pass
        p = p.replace("\\", "/")
        if os.altsep and os.altsep != "/":
            p = p.replace(os.altsep, "/")
        return p in self._changed_files

    def filter_findings(
        self,
        findings: List[Dict[str, Any]],
        file_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Drop findings whose file is not in the changed-file allowlist.

        Engines are inconsistent about the key name for the file path
        (``file``, ``path``, ``defined_in``, ``file_path``) and about
        whether it's absolute or relative. This function tries a list
        of keys in order and uses the first one present on each finding.

        Findings with no recognizable file key are KEPT — they may be
        workspace-level findings (e.g., "no .gitignore found") that
        shouldn't be filtered out by a file-based diff scope.

        Args:
            findings: List of finding dicts.
            file_keys: Optional list of keys to try (default: ``file``,
                ``path``, ``defined_in``, ``file_path``).

        Returns:
            New list containing only findings from changed files (or
            findings with no file key).
        """
        if file_keys is None:
            file_keys = ["file", "path", "defined_in", "file_path"]

        kept: List[Dict[str, Any]] = []
        for f in findings:
            if not isinstance(f, dict):
                kept.append(f)
                continue
            file_path: Optional[str] = None
            for key in file_keys:
                val = f.get(key)
                if isinstance(val, str) and val:
                    file_path = val
                    break
            if file_path is None:
                # No file key — keep workspace-level findings
                kept.append(f)
                continue
            if self.allows(file_path):
                kept.append(f)
        return kept

    def summary(self) -> Dict[str, Any]:
        """Return a dict summary suitable for embedding in command output.

        Commands should add this to their result dict under a
        ``diff_scope`` key so consumers (CI, agents) can see which files
        were in scope.
        """
        return {
            "base_ref": self._base_ref,
            "changed_files": sorted(self._changed_files),
            "changed_count": self.changed_count,
            "workspace": self._workspace,
        }

    # ─── Factory ─────────────────────────────────────────────

    @classmethod
    def from_ref(
        cls,
        workspace: str,
        ref: str,
        include_untracked: bool = True,
    ) -> "DiffScope":
        """Construct a DiffScope by diffing HEAD against ``ref``.

        Args:
            workspace: Path to the workspace root (must be a git repo).
            ref: Git ref to diff against (branch name, tag, SHA, ``HEAD~1``,
                ``origin/main``, etc.).
            include_untracked: If True (default), also include untracked
                files (newly created files not yet ``git add``-ed). These
                are part of the working-tree changes and should be in scope.

        Returns:
            A DiffScope instance.

        Raises:
            DiffScopeError: If the workspace is not a git repo, git is
                unavailable, or ``ref`` does not exist.
        """
        if not ref:
            raise DiffScopeError("--diff-base requires a non-empty ref argument")

        workspace = os.path.abspath(workspace)
        if not os.path.isdir(workspace):
            raise DiffScopeError(
                f"Workspace does not exist or is not a directory: {workspace}"
            )

        # Lazy import so this module can be imported in test contexts
        try:
            from git_aware import get_changed_files, get_untracked_files
        except ImportError as exc:
            raise DiffScopeError(
                f"git_aware module unavailable — cannot compute diff: {exc}"
            ) from exc

        # Validate the ref BEFORE calling get_changed_files.
        # get_changed_files returns [] on invalid ref (same as "no changes"),
        # which would silently produce an empty scope. We need to distinguish
        # "invalid ref" from "valid ref with no changes".
        _validate_git_ref(workspace, ref)

        changed = get_changed_files(workspace, since_sha=ref)

        if include_untracked:
            untracked = get_untracked_files(workspace)
            # Untracked files are returned as absolute paths by get_untracked_files
            changed = list(changed) + [
                os.path.relpath(p, workspace) if os.path.isabs(p) else p
                for p in untracked
            ]

        scope = cls(workspace, changed)
        # Attach the base ref so summary() can report it
        scope._base_ref = ref
        return scope


# ─── Internal helpers ────────────────────────────────────────


def _validate_git_ref(workspace: str, ref: str) -> None:
    """Verify that ``ref`` exists in the git repo at ``workspace``.

    Raises ``DiffScopeError`` if git is unavailable, the workspace is not
    a git repo, or ``ref`` does not resolve to a valid commit.

    Args:
        workspace: Absolute path to workspace root.
        ref: Git ref (branch, tag, SHA, HEAD~1, etc.).
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", ref],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise DiffScopeError(
            f"git command not found — cannot validate ref {ref!r}: {exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DiffScopeError(
            f"git rev-parse timed out validating ref {ref!r}: {exc}"
        ) from exc
    except Exception as exc:
        raise DiffScopeError(
            f"Unexpected error validating ref {ref!r}: {exc}"
        ) from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise DiffScopeError(
            f"Invalid git ref {ref!r}: {stderr or 'ref does not exist'}"
        )
