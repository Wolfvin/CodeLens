# @WHO:   scripts/sync/__init__.py
# @WHAT:  CodeLens sync subpackage — index-vs-worktree reconciliation helpers (issue #66)
# @PART:  sync
# @ENTRY: -
#
# This package hosts modules that detect drift between the CodeLens index
# and the working tree. Phase 1 (issue #66) ships ``pending`` — per-file
# staleness detection. Phase 4 ships ``worktree`` — git worktree index
# mismatch detection.
#
# Why a subpackage (not a single module):
#   - Staleness and worktree mismatch are independent concerns that share
#     only the "index vs working tree" theme. Forcing them into one file
#     would violate the single-responsibility rule.
#   - Future phases (connect-time catch-up, native file watcher) will add
#     more modules here. A package keeps the surface area discoverable.

"""CodeLens sync subpackage — workspace ↔ index reconciliation helpers.

This package contains modules that detect and repair drift between the
on-disk working tree and the persisted CodeLens index under
``.codelens/``. Drift can happen for several reasons:

* The user switched git branches without re-scanning.
* The user is working inside a git worktree whose ``.codelens/`` was
  never created, so CodeLens silently walks up and loads the main
  checkout's index — which indexes a *different* branch.
* Files were edited while no MCP server was running (Phase 2 of
  issue #66 — connect-time catch-up, future module).

Modules
-------
``pending`` — per-file staleness detection (issue #66 Phase 1).
    Walks indexed files, compares ``(st_size, st_mtime_ns)`` against the
    stored scan-time values, and re-computes a SHA-256 content hash only
    when size/mtime changed. Returns a list of stale files + a formatted
    banner string suitable for prepending to MCP responses.

``worktree`` — git worktree ↔ index mismatch detection (issue #66 Phase 4).

Why a subpackage?
-----------------
The engines under ``scripts/*_engine.py`` analyse code. The modules
under ``scripts/sync/`` analyse *state*: they answer "is the index
still a faithful reflection of the working tree?" Without that
guarantee, every downstream analysis is potentially reading stale
data, which is worse than no data at all.
"""

from .pending import (  # noqa: F401
    StaleFile,
    StaleFileDetector,
    detect_stale_files,
    format_staleness_banner,
    STALE_FILE_LIMIT_DEFAULT,
)
from .worktree import (  # noqa: F401
    detect_worktree_index_mismatch,
    format_worktree_banner,
    format_worktree_warning,
)

__all__ = [
    # Phase 1 — per-file staleness
    "StaleFile",
    "StaleFileDetector",
    "detect_stale_files",
    "format_staleness_banner",
    "STALE_FILE_LIMIT_DEFAULT",
    # Phase 4 — worktree index mismatch
    "detect_worktree_index_mismatch",
    "format_worktree_banner",
    "format_worktree_warning",
]
