"""CodeLens security hardening modules (issue #58).

This package groups together the security-related helpers that protect
CodeLens — and the AI agents driving it — from untrusted input:

* :mod:`scripts.security.path_traversal` — symlink-aware path
  confinement to the project root (Phase 1 of issue #58).

Future phases will add config secret redaction, git safety guard,
Secretlint integration, and LLM output schema validation.
"""

from .path_traversal import (
    PathRefusalError,
    is_path_within_project,
    resolve_path_within_project,
    safe_resolve_path,
)

__all__ = [
    "PathRefusalError",
    "is_path_within_project",
    "resolve_path_within_project",
    "safe_resolve_path",
]
