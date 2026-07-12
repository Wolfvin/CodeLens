# Design Doc: export-snapshot (restore deps import-snapshot)

> **Status:** Accepted
> **Date:** 2026-07-12
> **Author:** Claude (direct fix, no worker — user directive)
> **Related issues:** #218

---

## Problem

`deps --check import-snapshot` reads `.codelens/snapshot.codelens.gz` and loads
it into the graph DB, but no command produced that file: `export-snapshot` was
one of the commands dropped entirely in the #195 umbrella consolidation, while
`import-snapshot` survived as a `deps` sub-check. Every `import-snapshot` run
on a workspace that never had the old standalone `export-snapshot` command
run fails with `"Snapshot file not found"` — the feature was permanently
non-functional. `snapshot_io.py`'s `build_snapshot()`/`write_snapshot()`
(the actual export logic) were never deleted, only the CLI entry point that
called them.

Separately: the bare `codelens deps <workspace>` (no `--check`) ran every
registered check including `import-snapshot`, which always failed with no
`--input` given — every default `deps` run showed a spurious error entry
unrelated to what the caller asked for.

## Goal

`codelens deps <workspace> --check export-snapshot` writes a snapshot that
`codelens deps <workspace> --check import-snapshot` can load back, restoring
the same node/edge counts (round trip). The bare `codelens deps <workspace>`
default only runs the read-only analyses (affected/dependents/circular).

## Changes

### New Files
- `scripts/commands/export_snapshot.py` — thin CLI wrapper around the
  existing `snapshot_io.build_snapshot()` / `write_snapshot()`, mirroring
  `import_snapshot.py`'s structure (same error-handling shape, same
  `status`/`error` result contract).

### Modified Files
- `scripts/commands/deps.py` — registered `export-snapshot` in `_CHECKS`;
  added `--output` flag; added `_DEFAULT_EXCLUDED_CHECKS` so
  `import-snapshot`/`export-snapshot` (side-effecting, opt-in) are excluded
  from the bare `codelens deps <workspace>` "run everything" default.

### Not Changed
- `snapshot_io.py` — export logic already existed and needed no changes.
- No new top-level CLI command — `export-snapshot` is a `deps --check`
  sub-mode only, consistent with how `import-snapshot` itself is exposed
  post-#195 (confirmed via `tests/test_issue195_consolidation.py`, which
  still asserts `export-snapshot` is not a *standalone* command).

## Testing

`tests/test_export_snapshot.py`: export creates a valid `.gz`, missing-DB
error path, custom `--output` path, full export→import round trip (node/edge
counts preserved into a fresh workspace), and the default-check-list
exclusion for both snapshot checks.

## Alternatives Considered

- Re-adding `export-snapshot` as a standalone top-level command: rejected —
  contradicts the #195 consolidation (12 umbrellas only) and `import-snapshot`
  itself already lives as a `deps` sub-check, so symmetry argues for the same
  placement.
