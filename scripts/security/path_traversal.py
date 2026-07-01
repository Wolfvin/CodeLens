"""Path traversal protection for CodeLens (issue #58, Phase 1).

Why this module exists
----------------------
CodeLens reads source files from a workspace directory. When the
workspace path — or any file path derived from agent-supplied input —
is naively joined with ``os.path.join`` and opened, a malicious or
buggy caller can escape the workspace via:

* Relative traversal: ``../../etc/passwd``
* Symlinks inside the workspace that point outside it
* Absolute paths: ``/etc/passwd``
* UNC paths on Windows (``\\\\server\\share``)

This module implements **symlink-aware path confinement** to the
project root:

1. ``os.path.realpath`` is used to resolve **all** symlinks in both
   the project root and the candidate path. This defeats symlink-based
   escapes — the real on-disk location is what matters, not the
   apparent path the caller handed us.
2. The realpath of the candidate must be **equal to** or **start with**
   the realpath of the project root plus a path separator.
3. Symlinks that stay inside the project are still allowed — only
   escapes are refused.

The module exposes three entry points so callers can pick the
ergonomic that fits their context:

* :func:`resolve_path_within_project` — raises
  :class:`PathRefusalError` on escape. Use when the caller cannot
  recover and wants the exception to bubble up.
* :func:`is_path_within_project` — returns ``bool``. Use for
  pre-flight checks ("should I even attempt this read?").
* :func:`safe_resolve_path` — returns ``Optional[str]`` (``None`` on
  refusal). Use in defensive code paths that already handle ``None``
  returns from :func:`utils.safe_read_file`.

The refusal error message is **actionable** — it includes the
offending path, the project root, and a one-line suggestion so an AI
agent receiving the error can self-correct instead of looping.

Integration points (Phase 1)
----------------------------
* :func:`utils.safe_read_file_within_project` — thin wrapper that
  composes this module with :func:`utils.safe_read_file`.
* :mod:`scripts.commands.guard` — agent-driven ``--file`` argument
  is now validated before the file is read.
* :mod:`scripts.mcp_server` — any MCP tool argument named ``file`` /
  ``path`` is validated against the resolved workspace before the
  underlying command is dispatched.
"""

from __future__ import annotations

import os
from typing import Optional

__all__ = [
    "PathRefusalError",
    "is_path_within_project",
    "resolve_path_within_project",
    "safe_resolve_path",
]


class PathRefusalError(PermissionError):
    """Raised when a path resolves outside the project root.

    Inherits from :class:`PermissionError` so existing ``except
    OSError`` / ``except PermissionError`` handlers in callers
    continue to catch it without modification.

    Attributes:
        requested_path: The original path the caller handed in
            (unmodified, for diagnostics).
        resolved_path: The realpath of the requested path (may be
            ``None`` if the path did not exist on disk and could not
            be resolved — in which case the refusal was triggered by
            an absolute path or traversal pattern that *would* escape
            if it did exist).
        project_root: The realpath of the project root that the
            requested path was checked against.
    """

    def __init__(
        self,
        requested_path: str,
        resolved_path: Optional[str],
        project_root: str,
    ) -> None:
        self.requested_path = requested_path
        self.resolved_path = resolved_path
        self.project_root = project_root
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        return (
            f"Path refusal: '{self.requested_path}' resolves outside the "
            f"project root '{self.project_root}'. "
            f"Resolved to: {self.resolved_path or '(non-existent, refused by pattern)'}. "
            f"Use a path that stays within the project root."
        )


def _normalize_project_root(project_root: str) -> str:
    """Realpath the project root, ensuring a trailing separator.

    The trailing separator is critical for the
    ``startswith(project_root + sep)`` check — without it,
    ``/home/proj-evil`` would falsely appear to be inside
    ``/home/proj``.
    """
    if not project_root:
        raise ValueError("project_root must be a non-empty path")
    real_root = os.path.realpath(project_root)
    # Append os.sep so that startswith() respects path-segment
    # boundaries. realpath() strips trailing separators, so we
    # re-add one unconditionally.
    return real_root + os.sep


def is_path_within_project(project_root: str, path: str) -> bool:
    """Return ``True`` if ``path`` resolves inside ``project_root``.

    Non-throwing variant of :func:`resolve_path_within_project`.
    Safe to call with paths that do not exist on disk — ``realpath``
    on a non-existent path returns the resolved absolute path, which
    is then checked against the project root.

    Args:
        project_root: Absolute or relative path to the project root.
            Need not exist (though a non-existent root will refuse
            everything, which is the safe default).
        path: The candidate path to check. May be absolute, relative
            (resolved against cwd), or contain ``..`` segments.

    Returns:
        ``True`` if the realpath of ``path`` is equal to or nested
        under the realpath of ``project_root``.
    """
    if not path:
        return False
    try:
        normalized_root = _normalize_project_root(project_root)
    except ValueError:
        return False

    # realpath on a non-existent path still normalizes the lexical
    # components (collapses '..', resolves symlinks for the parts that
    # DO exist). That's exactly the behavior we want — a path like
    # '/proj/../../etc/passwd' lexically resolves to '/etc/passwd'
    # even if '/proj' itself doesn't exist.
    resolved = os.path.realpath(path)
    # Equality with the root (without the trailing sep) covers the
    # case where path == project_root exactly.
    root_without_sep = normalized_root[:-1]  # strip the trailing sep
    if resolved == root_without_sep:
        return True
    return resolved.startswith(normalized_root)


def resolve_path_within_project(project_root: str, path: str) -> str:
    """Resolve ``path`` against ``project_root`` and return its realpath.

    Raises:
        PathRefusalError: If the realpath of ``path`` escapes
            ``project_root``.

    Args:
        project_root: Absolute or relative path to the project root.
        path: The candidate path. May be absolute, relative, or
            contain ``..`` / symlinks.

    Returns:
        The realpath of ``path`` (with all symlinks resolved), safe
        to ``open()``.
    """
    if not path:
        raise PathRefusalError(path or "<empty>", None, os.path.realpath(project_root or ""))

    normalized_root = _normalize_project_root(project_root)
    resolved = os.path.realpath(path)
    root_without_sep = normalized_root[:-1]

    if resolved == root_without_sep or resolved.startswith(normalized_root):
        return resolved

    raise PathRefusalError(path, resolved, root_without_sep)


def safe_resolve_path(project_root: str, path: str) -> Optional[str]:
    """Non-throwing variant of :func:`resolve_path_within_project`.

    Returns the realpath on success, or ``None`` if the path escapes
    the project root. Designed for code paths that already handle
    ``None`` from :func:`utils.safe_read_file` — drop-in compat.
    """
    try:
        return resolve_path_within_project(project_root, path)
    except PathRefusalError:
        return None
