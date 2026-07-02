# Per-File Staleness Banner (issue #66 Phase 1)

> **Status:** Phase 1 shipped. Phases 2–5 tracked as follow-up issues.
> **Last updated:** 2026-07-02

## Alasan Dibuat

After a `codelens scan`, the index is a snapshot. If the user edits a
file after the scan, queries against the index may return outdated
symbol locations, dead-code verdicts, or stale call graphs. Before
Phase 1, the MCP server happily served stale results with no warning —
agents acted on outdated data without knowing.

Phase 1 adds a **per-file staleness banner** that detects when indexed
files have been edited since the last scan and surfaces a warning to
the agent before the tool's actual output. The banner is prepended to
every read-tool response (suppressed on `scan`/`init` — those are the
fix path, not analysis calls).

## Arsitektur

```
scripts/sync/
├── __init__.py         # Re-exports public API
└── pending.py          # StaleFileDetector + detect_stale_files()
                        #   + format_staleness_banner()
                        # In-memory Dict[str, float] cache, thread-safe
                        # via threading.Lock, 5s TTL per workspace.

scripts/commands/
└── staleness.py        # `codelens staleness` CLI command — manual check
                        #   + full list when MCP banner truncates to 10

scripts/mcp_server.py   # MCPServer._staleness_detector (lazy)
                        #   + _attach_staleness_banner() — prepends banner
                        #   + _invalidate_staleness_cache() — after scan

tests/
└── test_staleness.py   # 41 tests — detection, cache, thread safety,
                        #   banner formatting, CLI, MCP integration
```

## Detection algorithm

```
1. Load stored mtimes from .codelens/mtimes.json
   (source of truth — written by incremental.save_mtimes() on every scan)
2. For each indexed file:
   a. os.stat() — if file gone, skip (deletion is Phase 2's concern)
   b. If |current_mtime - stored_mtime| <= 0.001s, skip (filesystem noise)
   c. If confirm_with_hash=True (default):
      - Compute SHA-256 of current content
      - Load stored hash from SQLite `files` table (if available)
      - If hashes match, skip (mtime changed but content identical — e.g. `touch`)
      - If hashes differ or stored hash unavailable, flag as stale
   d. Else (confirm_with_hash=False): flag on mtime change alone
3. Sort by edit_age ascending (most recent edit first)
4. Return tuple of StaleFile records
```

**Why mtimes.json (not SQLite `files` table) as the source of truth?**
`mtimes.json` is written by every scan, including workspaces that use
the legacy JSON registry (pre-v8.2). The SQLite `files` table is only
populated when the persistent registry is active. Using `mtimes.json`
keeps Phase 1 working on every workspace configuration.

**Why 0.001s mtime tolerance?**
Filesystems with coarse mtime resolution (FAT32, some network shares)
can report mtimes that differ by sub-millisecond even when content is
identical. The stored mtime comes from `os.path.getmtime()` which
returns a float; comparing with a small epsilon avoids false positives
from filesystem noise.

## Cache

`StaleFileDetector` caches results per workspace for 5 seconds
(`DETECTOR_CACHE_TTL_SECONDS`). The cache is:

- **Thread-safe** — protected by `threading.Lock`. The MCP server
  dispatches tool calls in a thread pool, so concurrent calls must not
  race or duplicate work.
- **Per-workspace** — keyed by absolute workspace path. Multiple
  workspaces don't interfere.
- **Invalidated on scan** — `MCPServer._invalidate_staleness_cache()`
  is called after a successful `scan` command. The scan refreshes the
  index, so any cached staleness verdict is now stale itself.

The cache exists because walking 10k+ files on every tool call would
add ~50 ms of latency. A 5-second TTL keeps the banner fresh enough
for interactive use (a user editing a file should see the banner
within seconds) without re-stat-ing the whole tree on every query.

## Banner shape

```
⚠️ Some files referenced below were edited since the last index sync.
The index may be stale for these files — re-run `codelens scan` to refresh.
Stale files (showing 3 of 3, most recent first):
  • path/to/file.py (edited 2.3s ago, content differs)
  • other.js (edited 1m 12s ago, content differs)
  • third.ts (edited 5m 0s ago, size/mtime differ)
```

- **Plain text** (not markdown) — renders correctly in both terminal
  output and MCP tool-response content blocks.
- **⚠️ marker** — agents can pattern-match on it.
- **"content differs"** vs **"size/mtime differ"** — distinguishes
  hash-confirmed staleness from mtime-only staleness.
- **Most recent first** — the agent sees the most relevant context first.
- **Truncates to 10 files** with "and N more" — keeps the banner
  actionable; the full list is available via `codelens staleness`.

## MCP integration

`MCPServer._handle_tools_call` calls `_attach_staleness_banner()` on
three response paths:

1. **Cached response** — banner attached (the workspace's staleness is
   independent of whether the tool result was cached).
2. **Fresh success** — banner attached, unless the command is `scan` or
   `init` (those are the remediation path).
3. **Error response** — banner attached, unless `scan`/`init`. If the
   user is in a stale workspace, that context is more useful than the
   error itself — the error is almost certainly caused by the stale
   index.

The banner is prepended to the first content block's `text` field AND
attached as a structured `response["_staleness"]` field. Both paths
ensure the warning surfaces — agents that pattern-match on JSON keys
see the structured field; agents that read only the text see the
prepended banner.

After a successful `scan`, `_invalidate_staleness_cache(workspace)` is
called so the next read tool re-probes against the fresh index.

## CLI command

```bash
# Check staleness (text output, default)
codelens staleness [workspace]

# JSON output for scripts
codelens staleness [workspace] --format json

# Skip SHA-256 confirmation (faster, false-positive on `touch`)
codelens staleness [workspace] --no-confirm-hash

# Show more files in the banner (default 10)
codelens staleness [workspace] --limit 50
```

## Definition of Done (Phase 1, dari issue)

- [x] In-memory `Dict[str, float]` (path → edit_timestamp), thread-safe via `threading.Lock`
- [x] Walk indexed file list with `os.stat(path)` to compare `(st_size, st_mtime_ns)`
- [x] Re-compute content-hash only when size/mtime changed
- [x] Prepend `⚠️ Some files referenced below were edited since the last index sync…` banner to MCP responses
- [x] Surface non-referenced pending files as small footer (the "and N more" line + `codelens staleness` for full list)
- [x] New file: `scripts/sync/pending.py`

Phase 2 (connect-time catch-up), Phase 3 (native file watcher), and
Phase 5 (anonymous telemetry) are deferred to follow-up issues.

## Design decisions

1. **Why a separate `scripts/sync/` subpackage?**
   Staleness and worktree mismatch (Phase 4, separate PR #154) are
   independent concerns that share only the "index vs working tree"
   theme. A package keeps them discoverable without forcing them into
   one file (single-responsibility rule).

2. **Why lazy construction of the detector in MCPServer?**
   Keeps the import out of the server's startup path. If the sync
   subpackage ever fails to import (e.g. a missing dependency in a
   stripped-down install), the server still starts and only staleness
   detection is degraded.

3. **Why prepend (not append) the banner?**
   Agents read tool output top-to-bottom. If the banner is at the
   bottom, the agent may have already acted on stale data before
   reaching it. Prepending ensures the warning is the first thing the
   agent sees.

4. **Why both structured `_staleness` field AND prepended text?**
   Different agents consume tool output differently. Some
   pattern-match on JSON keys (those see the structured field). Others
   read only the text content (those see the prepended banner). Both
   paths ensure the warning surfaces without requiring agents to
   change.

5. **Why is `content_hash_changed` a tri-state (True/False/None)?**
   - `True` — size/mtime differ AND content hash differs (definitely stale)
   - `False` — size/mtime differ BUT content hash matches (not stale, e.g. `touch`)
   - `None` — size/mtime differ, no stored hash available to confirm
     (probably stale, but can't be sure). The banner says "size/mtime
     differ" rather than "content differs" in this case.

6. **Why sort ascending by edit_age (smallest first)?**
   `edit_age = now - current_mtime`. A file edited 1s ago has age=1;
   a file edited 10s ago has age=10. Ascending puts age=1 first →
   most recent first, matching the banner text.

## Testing

```
PYTHONUTF8=1 PYTHONPATH=scripts python3 -m pytest tests/test_staleness.py -v
```

41 tests, all network-free and filesystem-light. Tests create small
temporary workspaces with synthetic `mtimes.json` files — no real
CodeLens scan is needed. Coverage:

- Basic detection (mtime change, deleted files, empty workspace)
- Content-hash confirmation (touch without content change)
- Cache (TTL, invalidation, all-workspace invalidation)
- Thread safety (20 concurrent calls)
- Banner formatting (single file, truncation, age format)
- CLI command (registration, JSON/text output, --no-confirm-hash)
- MCP integration (prepend on read tools, suppress on scan/init,
  invalidate after scan, init failure isolation)

## Phases 2–5 (deferred)

| Phase | Scope                                                    | Status         |
|-------|----------------------------------------------------------|----------------|
| 2     | Connect-time catch-up — content-hash reconciliation on MCP reconnect | Not started |
| 3     | Native file watcher (FSEvents/inotify/ReadDirectoryChangesW) | Not started |
| 4     | Worktree mismatch detection (PR #154)                    | PR ready       |
| 5     | Anonymous opt-in telemetry                               | Not started    |

Phase 2 will extend `StaleFileDetector` to also run content-hash
reconciliation on MCP reconnect, blocking the first query until
catch-up finishes (or 5s timeout, then proceed with stale + banner).
The `StaleFileDetector` cache and `StaleFile` data structure are
designed to accommodate this without API change.
