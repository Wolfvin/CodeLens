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
``worktree`` — git worktree ↔ index mismatch detection (issue #66 Phase 4).

Why a subpackage?
-----------------
The engines under ``scripts/*_engine.py`` analyse code. The modules
under ``scripts/sync/`` analyse *state*: they answer "is the index
still a faithful reflection of the working tree?" Without that
guarantee, every downstream analysis is potentially reading stale
data, which is worse than no data at all.
"""

__all__ = ["worktree"]
