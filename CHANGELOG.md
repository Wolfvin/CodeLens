# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/html).

## [8.2.0] — Unreleased

### Large-File Silent-Skip Replaced with Explicit Regex Fallback (issue #163)

CodeLens silently skipped files above hardcoded line thresholds to
avoid a tree-sitter 0.26 binding segfault (tracked in #116):

- JavaScript: files > 100 lines → skipped (returned `{"nodes": [], "edges": []}`)
- Python: files > 200 lines → skipped

This caused the most complex files in a codebase — the ones most
worth analyzing — to be invisible to all downstream engines
(`complexity`, `dead-code`, `smell`, `entrypoints`). On
Wolfvin/Regrets ~40% of the codebase was silently dropped, including
the worst hotspots (`scripts/validate.js` 2730 lines,
`scripts/validate.py` 2361 lines).

**Root cause investigation:** the tree-sitter 0.26 Python binding has
a nondeterministic SIGSEGV on large files. Existing mitigations
(`BaseParser._last_tree`, `parse_tree()`, `_gc.disable()`) reduce
crash frequency but do not eliminate it. Verified by stress-testing
synthetic and real-world files: crashes begin at ~250 lines for JS
and ~500 lines for Python. The bug cannot be fixed from Python — it
requires a binding upgrade.

**Fix (issue #163):** instead of silently skipping, large files now
use the REGEX FALLBACK parser (`parse_js_backend_fallback` /
`parse_python_fallback`), which gives partial coverage (function
declarations + direct calls) instead of zero coverage. The result
includes a `skipped_from_tree_sitter` field so callers know
tree-sitter was not used and why. The scan command aggregates all
such entries into a top-level `skipped_from_tree_sitter` list in its
JSON output.

Additional hardening applied to `JSBackendParser`:
- Iterative DFS walk replaces recursive `_walk` (prevents Python
  stack frames from holding stale Node references across function
  boundaries — reduces crash frequency on smaller files).
- Iterative DFS in `_find_calls_in_scope` for the same reason.

Thresholds raised: JS 100 → 250, Python 200 → 500 (largest values
that passed 5 consecutive stress-test runs without SIGSEGV).

`outline_engine.py` similarly no longer preemptively falls back to
regex for JS files > 100 lines or Python files > 200 lines — it
attempts tree-sitter first and only falls back on actual parse
exception.

### LSP Status Entry-Point Unification (issue #33)

The `codelens --lsp-status` top-level flag (intercepted in
`scripts/codelens.py`) and the `codelens lsp-status` subcommand
(`scripts/commands/lsp_status.py`) returned **structurally different
payloads** for what the documentation treats as the same operation:

- `--lsp-status` called `hybrid_engine.get_lsp_status()` — the richer
  payload with `available_count`, `total_servers`, per-server `path` +
  `extensions`, and a `recommendation` field.
- `lsp-status` called `lsp_client.detect_available_servers()` directly
  and rebuilt a smaller dict — no `available_count`/`total_servers`,
  per-server entries missing `path`/`extensions`, and a `hint` field
  instead of `recommendation`.

The MCP server dynamically discovers subcommands, so MCP agents
(`codelens_lsp_status` tool) got the **smaller** payload while CLI
users got the **richer** one — two different "truths" for the same
question.

**Fix (Option B from the issue):** both entry points now delegate to
`hybrid_engine.get_lsp_status()` — single source of truth. The
top-level `--lsp-status` flag is preserved as a backward-compatible
alias of the `lsp-status` subcommand. Option A (remove the flag
entirely) was rejected because the issue's DoD explicitly requires
both entry points to produce byte-identical output (repro diff exit
code 0), which is unsatisfiable if one entry point is removed.

A pre-existing determinism bug was also fixed in
`lsp_client.detect_available_servers()`: `extensions` was returned as
`list(config["extensions"])` where `config["extensions"]` is a `set`,
so order varied across Python invocations (hash randomization). Now
sorted, so the repro diff is byte-identical, not just structurally
equal.

### Changed (issue #33)

- **`scripts/commands/lsp_status.py:execute()`** — Now delegates to
  `hybrid_engine.get_lsp_status()` instead of rebuilding a smaller
  dict from `lsp_client.detect_available_servers()`. The ImportError
  fallback was updated to match the new (richer) shape so error
  responses are still structurally consistent.
- **`scripts/lsp_client.py:detect_available_servers()`** — `extensions`
  field is now `sorted(config["extensions"])` instead of
  `list(config["extensions"])` for deterministic cross-invocation
  output.

### Documented (issue #33)

- **`SKILL-QUICK.md`** — Trigger map now has an explicit
  `"LSP servers available?"` → `lsp-status` entry, noting that
  `--lsp-status` is an alias. The Setup & Lifecycle command list also
  documents the alias relationship.

### Tested (issue #33)

- **`tests/test_cli.py:TestLspStatusEntryPointParity`** — New class
  with 3 tests: top-level key parity, per-server field parity, and
  full byte-identical payload equality. Guards against future
  regressions of the dual-truth problem.

### OSV Cache Staleness Flags + `cache_info` Output (issue #30)

Phase 1 roadmap (#21) checklist item: "Fix vuln DB staleness (OSV.dev
API, update scheduler)". The OSV client had a 24h TTL cache with
`cleanup()` but **no staleness indicator in vuln-scan output** and
**no way to force a refresh** — agents consuming `vuln-scan` had no
way to know whether the cached CVE data was fresh or stale, and no
way to override the 24h TTL for a single run.

This change adds three things:

1. **`cache_info` block in vuln-scan output** — a new top-level key
   in the `vuln-scan` JSON describing OSV cache freshness:
   ```json
   "cache_info": {
     "last_refresh": "2026-06-28T10:00:00Z",
     "age_hours": 23.5,
     "ttl_hours": 24,
     "is_stale": false,
     "stale_packages": []
   }
   ```
   `last_refresh` is the ISO 8601 UTC timestamp of the most-recent
   cache entry among the packages queried in this run. `age_hours` is
   its age. `is_stale` is `true` when any queried package's cache
   entry is past TTL or missing. `stale_packages` lists the
   `"name@version"` strings of stale/missing packages (sorted for
   deterministic output).

2. **`--refresh` flag** — `codelens vuln-scan --refresh` bypasses the
   OSV cache and forces a fresh OSV.dev API call for every package.
   The cache is updated with the new results. Silently ignored in
   `--offline` mode (no network to refresh from).

3. **`--max-age Nh` flag** — `codelens vuln-scan --max-age 6h` treats
   cache entries older than 6 hours as stale for this run only,
   re-fetching them from the API. The stored TTL is **not** modified
   (per-run override only). Accepts `Nh` (hours), `Nm` (minutes),
   `Ns` (seconds), `Nd` (days), or a bare integer (interpreted as
   hours, matching `--osv-ttl` semantics). `--max-age 0` is
   equivalent to `--refresh` for cached entries.

Network calls happen only when `--refresh` is set OR the cache is
expired/missing/stale-per-`--max-age`. Default behaviour (no flags)
is unchanged: cached entries within TTL are served from the cache.

### Added (issue #30)

- **`scripts/osv_client.py:OSVCache.peek(key)`** — New method.
  Returns the raw `(response, timestamp, ttl)` tuple WITHOUT applying
  the stored TTL or deleting the entry. This is what `--max-age`
  relies on to apply a per-run TTL threshold without mutating stored
  state. Corrupt entries (invalid JSON) are deleted and treated as
  missing, matching `get()`'s behaviour.
- **`scripts/osv_client.py:OSVClient.query_packages(packages,
  force_refresh=False, max_age=None)`** — New optional params.
  `force_refresh=True` bypasses the cache entirely (issue #30
  `--refresh`); `max_age=N` (seconds) uses `peek()` to apply a
  per-run TTL threshold (issue #30 `--max-age`). Behaviour is
  unchanged when both are unset.
- **`scripts/osv_client.py:OSVClient._parse_cached_response(cached,
  package)`** — New private helper. Factors the two-shape cache
  parsing (list of vuln IDs vs list of full vuln dicts) out of
  `query_packages` so all three code paths (normal, force_refresh,
  max_age) share it. Zero dead code — the inline parsing logic was
  moved, not duplicated.
- **`scripts/osv_client.py:OSVClient.get_cache_info(packages)`** —
  New method. Returns the `cache_info` dict described above.
  Packages with unsupported ecosystems are skipped. Missing entries
  are treated as stale.
- **`scripts/commands/vuln_scan.py:_parse_max_age(raw)`** — New
  helper. Parses `--max-age` duration strings into seconds.
- **`scripts/commands/vuln_scan.py`** — New `--refresh` and
  `--max-age` CLI flags.
- **`tests/test_vuln_staleness.py`** — 39 tests across 7 classes
  covering `_parse_max_age`, `OSVCache.peek`, `get_cache_info`
  (empty/all-stale/all-fresh/mixed/sorted/ttl), `force_refresh`
  (bypasses cache / uses cache / ignored offline), `max_age`
  (old→stale / young→fresh / stored TTL unchanged / `0`=refresh),
  end-to-end `scan_vulnerabilities` output on `clean_app` and
  `vulnerable_app` fixtures, and CLI arg wiring. All network-free
  (API calls mocked via `unittest.mock.patch.object`).

### Changed (issue #30)

- **`scripts/vulnscan_engine.py:scan_vulnerabilities()`** — Gains
  `refresh` and `max_age` params, forwarded to
  `osv_client.query_packages(force_refresh=, max_age=)`. Computes a
  `cache_info` block after the OSV query (three code paths: success
  → from `get_cache_info()`; no packages → empty shape; OSV
  exception → empty shape with `error` field). The return dict now
  includes a `cache_info` key.
- **`scripts/commands/vuln_scan.py:execute()`** — Validates
  `--max-age` via `_parse_max_age()` before calling the engine.
  Invalid `--max-age` returns a structured
  `{status:'error', error:'invalid_argument', message:...}` dict
  instead of raising.

### Non-Breaking (issue #30)

- The `cache_info` block is additive — no existing `vuln-scan`
  output key is removed or renamed. Consumers who don't read
  `cache_info` see no change.
- `scan_vulnerabilities()`'s new params (`refresh`, `max_age`) are
  optional with defaults (`False`, `None`), so existing callers are
  unaffected.
- `OSVClient.query_packages()`'s new params are optional with
  defaults (`False`, `None`); existing callers (including
  `query_single`, `batch_query`, and `scan_with_osv`) are
  unaffected.
- `OSVCache.peek()` is a new method; no existing method's signature
  or behaviour changes.
- Network behaviour is unchanged by default: the OSV API is only
  contacted when `--refresh` is set OR a cache entry is expired /
  missing / stale per `--max-age`. The default 24h TTL path is
  byte-for-byte identical to the pre-issue-#30 code.
- `--refresh` is silently ignored in `--offline` mode (matches the
  existing offline contract — no network calls are ever attempted
  when `offline=True`).

### Migration Notes for Agent Authors (issue #30)

Agents that consume `vuln-scan` output can now check
`cache_info.is_stale` to decide whether to trust the cached CVE
results. If stale, re-run with `--refresh` (force fresh API calls
for all packages) or `--max-age 6h` (only re-fetch entries older
than 6 hours, cheaper than a full refresh). `stale_packages` lists
the specific packages that need attention.

### Incremental Graph Update (issue #25)

Previously, `scan --incremental` updated only the flat backend registry
and skipped graph population entirely. As a result, `graph_nodes` and
`graph_edges` became stale after any incremental scan — `trace --use-graph`
returned outdated callers/callees, and the recommended post-edit workflow
(`scan --incremental`) silently broke the graph backend that #8 introduced.

This fix adds a slice-level update path: only the changed files' nodes
and edges are deleted and re-inserted from the flat registry, then
`refine_call_edges` (from #13) is re-invoked to rebuild IMPORTS edges
and re-refine CALLS edges. The full scan path is unchanged — it still
calls `populate_graph_tables` for a bulk rebuild.

### Added (issue #25)

- **`scripts/graph_model.py:incremental_graph_update(workspace, db_path, changed_files)`**
  — New function. Performs a slice-level graph update:
  1. Normalize `changed_files` (absolute paths) to workspace-relative
     paths. Empty input is a no-op (returns zero counts) so the
     no-changes path in `scan --incremental` is safe.
  2. Identify `graph_nodes` rows whose `file` is in the changed set
     (the stale node ids that must be replaced).
  3. Delete `graph_edges` rows that touch any changed file:
     - edges whose `file` (originating file) is in the changed set
       (covers CALLS edges from changed files + IMPORTS edges whose
       importer changed), AND
     - edges whose `source_id` or `target_id` references a stale node
       id from step 2 (covers cross-file edges from an unchanged file
       into a changed file — the target may have been renamed/moved).
  4. Delete the stale `graph_nodes` rows themselves.
  5. Re-read the flat backend registry (already updated by
     `merge_backend_data` in the scan pipeline) and INSERT only the
     nodes whose `file` is in the changed set, plus CALLS edges that
     touch the changed set (either endpoint's file is in the set).
  6. Call `refine_call_edges(workspace, db_path)` so IMPORTS edges
     and import-aware CALLS-edge refinement are rebuilt for the
     affected slice. `refine_call_edges` is idempotent (it clears
     and rebuilds the `import_registry` table and IMPORTS edges from
     scratch each call), so invoking it here is safe regardless of
     whether a previous scan already ran it.

  Returns: `{nodes, edges, edges_refined, edges_unresolved}` where
  `nodes`/`edges` are the TOTAL graph row counts after the update
  (not the delta) so the return shape matches `populate_graph_tables`.

- **`tests/test_graph_incremental.py`** — 19 tests across 9 classes
  covering: no-op cases, equivalence with full populate, idempotency,
  slice isolation, file modification reflection (rename/add/remove),
  stale edge dropping (no orphan edges), return-value shape, end-to-end
  via `cmd_scan(incremental=True)` (graph field present in BOTH full
  and incremental scan output with matching counts), and a performance
  assertion (<200ms for 5 changed files; issue spec targets <100ms).

### Changed (issue #25)

- **`scripts/commands/scan.py`** — Incremental path now calls
  `incremental_graph_update(workspace, db_path, changed_files)` instead
  of skipping graph population. The full-scan path is unchanged (still
  calls `populate_graph_tables` + `refine_call_edges`). Scan output now
  ALWAYS includes a `graph` field with the actual final state
  (`{nodes, edges}`) of `graph_nodes` + `graph_edges`, regardless of
  scan mode — previously the incremental path emitted no `graph` field
  at all. The `type_resolution` field is populated by the incremental
  path too (from `incremental_graph_update`'s return value).

### Non-Breaking (issue #25)

- Full-scan behavior is unchanged — `populate_graph_tables` is still
  called for a clean bulk rebuild on every full scan.
- The incremental path is best-effort: any failure inside
  `incremental_graph_update` is logged at WARNING level and swallowed,
  so the flat registry remains the source of truth and the scan still
  succeeds (matches the existing full-scan error-handling contract).
- The function is idempotent — running twice with the same
  `changed_files` yields the same final graph state.
- The `graph` field added to the incremental-scan output is additive;
  no existing field is removed or renamed. Consumers who previously
  special-cased the missing `graph` field on incremental scans see a
  populated `{nodes, edges}` shape identical to the full-scan output.
- On the `clean_app` fixture: full scan reports
  `graph: {nodes: 31, edges: 134}` (CALLS + IMPORTS, after refine).
  Subsequent incremental scan with no changes reports the same counts.
  Incremental scan after renaming `format_text` → `format_text_renamed`
  in `src/utils.py` updates the graph (renamed node present, old name
  gone from that file) and reports updated edge counts.

### Migration Notes for Engine Authors (issue #25)

Engines that read `graph_nodes` / `graph_edges` after an incremental
scan no longer need to fall back to the flat registry or trigger a
manual full scan — the graph is always in sync with the flat registry
after `cmd_scan` returns, regardless of `incremental=True/False`.

### Confidence Fields on Non-Deep Output (test fix)

Previously, the `confidence` / `confidence_distribution` fields were only
attached to `query` / `impact` / `dead-code` output when the `--deep` flag
was passed (which triggers LSP verification). This meant consumers of the
default (non-deep) output had no way to know the analysis provenance. The
hybrid engine's module docstring already documents the intended semantics
(`high` = LSP verified, `medium` = AST matched, `low` = regex only), and
`HybridEngine.enhance_*` methods already set `confidence = MEDIUM` when LSP
is not active — but those methods were only invoked from the `--deep`
post-processing path in `codelens.py`, never from the command `execute()`
entry points.

This fix completes the partially-implemented feature by attaching baseline
`confidence = "medium"` (and `confidence_distribution` for `dead-code`) at
command execution time, before the `--deep` post-processing layer runs.
When `--deep` is later applied, LSP verification may override individual
fields to `high` or `low` as before.

### Added (confidence fields)

- **`query` command** — top-level `confidence` field is now always present
  on `found` results (value: `"medium"` for AST-based analysis, `"high"` or
  `"low"` when `--deep` + LSP verifies).
- **`impact` command** — top-level `confidence` field is now always present
  on `status: ok` results.
- **`dead-code` command** — each finding in `results` now carries a
  `confidence` field; `stats.confidence_distribution` (counts of
  `high` / `medium` / `low`) is now always present.

### Non-Breaking (confidence fields)

- All previously-passing tests continue to pass.
- The new fields are additive — no existing field is removed or renamed.
- When `--deep` is used, the `--deep` post-processing layer in
  `codelens.py` still runs and may override the baseline confidence based
  on LSP verification, exactly as before.
- The `confidence` field is also surfaced in the `--format ai` normalized
  output via the existing `_META_KEYS` extraction in
  `formatters/__init__.py`.

### Token-Efficient Output + Pagination (issue #17)

Adds a 5th output format (`compact`) and pagination to all list-type commands
so AI agents pay fewer tokens for the same information. A single `trace` call
that previously returned 5-10KB of verbose JSON now returns ~2.5-5KB of
compact single-char-key JSON. Target: 5 structural queries cost <5k tokens
total (down from 30-80k).

### Added (issue #17)

- **`--format compact`** — New 5th output format alongside `json`/`markdown`/
  `ai`/`sarif`. Implemented in `scripts/formatters/compact.py`:
  - Omits null/empty fields (saves ~15% on average).
  - Abbreviates node types: `function→fn`, `class→cls`, `file→f`, `module→m`,
    `route→r`, `type→t`, `interface→i`.
  - Abbreviates edge types: `CALLS→C`, `IMPORTS→I`, `DEFINES→D`, `INHERITS→H`,
    `IMPLEMENTS→M`, `USES_TYPE→U`.
  - Uses single-char keys: `name→n`, `file→f`, `line→l`, `type→t`, `status→s`,
    `confidence→c`, etc. (full map in `formatters/compact.py:FIELD_KEY_ABBR`).
  - Strips the workspace prefix from absolute paths.
  - Output is still valid JSON — MCP clients parse it directly.

- **`graph-schema` command + `codelens_graph_schema` MCP tool** — Returns
  node + edge counts, node-type distribution, edge-type distribution, and
  index count in one cheap call. Example compact output:
  `{"s":"ok","n":31,"e":97,"nts":{"function":30,"class":1},"ets":{"CALLS":97},"ix":6}`.
  The cheapest way for an agent to understand the graph shape before issuing
  structural queries.

- **`--limit N` / `--offset N` pagination** on `list`, `search`, `trace`,
  `symbols`, `outline`. Default `--limit 20`. All paginated commands now
  return `total_count`, `count`, `offset`, `limit`, `has_more` fields. The
  existing `--top N` flag is preserved as an alias for `--limit N --offset 0`.

- **`format` parameter on every MCP tool** — All MCP tools now accept a
  `format` parameter with the enum `[json, markdown, ai, sarif, compact]`.
  Default remains `ai` (normalized schema). Pass `format: "compact"` for
  token-efficient responses.

- **`tests/test_compact_format.py`** — 28 test cases covering compact
  formatter rules, pagination behavior, graph-schema command, MCP tool
  advertisement, and token-savings assertions.

### Changed (issue #17)

- **`scripts/codelens.py`** — Global `--format` flag (and per-subparser flag)
  now accept `compact` as a 5th choice. Pre-parse loop updated to recognize
  `compact` before subcommand dispatch.
- **`scripts/formatters/__init__.py`** — `format_output()` now dispatches to
  `formatters.compact.format_compact` when `format_type == "compact"`.
- **`scripts/commands/search.py`** — Adds `--limit`/`--offset`, paginates
  the `matches` list, adds `total_count`/`count`/`offset`/`limit`/`has_more`
  fields.
- **`scripts/commands/list.py`** — Default `--limit` lowered from 200 to 20
  (per issue #17 spec); adds `total_count` field alongside the existing
  `total`. `--limit 0` means unlimited (preserves backward compat).
- **`scripts/commands/trace.py`** — Adds `--limit`/`--offset`, paginates
  `chains.up` and `chains.down`, adds `total_count` field.
- **`scripts/commands/symbols.py`** — Adds `--limit`/`--offset`, paginates
  `results`, adds `total_count`/`has_more` fields.
- **`scripts/commands/outline.py`** — Adds `--limit`/`--offset`, paginates
  `outlines`, adds `total_count`/`has_more` fields.
- **`scripts/mcp_server.py`** — Adds `graph-schema` to `_TOOL_DEFINITIONS`.
  Adds `_inject_format_enum()` helper that injects the shared `format`
  property into every tool's inputSchema. `_execute_command` now respects
  `arguments["format"]` — when set to `"compact"`, returns the compacted
  dict via `formatters.compact.compact_dict` instead of the AI-normalized
  schema.

### Non-Breaking (issue #17)

- Existing `--format json/ai/markdown/sarif` outputs are unchanged.
- Existing `--top N` flag still works (alias for `--limit N --offset 0`).
- Existing `list --limit 200` (the old default) still works — only the
  default value changed from 200 to 20. Pass `--limit 200` explicitly to
  restore the old behavior, or `--limit 0` for unlimited.
- All 56 existing CLI commands continue to work unchanged.
- 28 new tests pass; 4 pre-existing `test_hybrid_engine.py` failures
  (confidence-field assertions) are unchanged — NOT caused by this change.

### Migration Notes for Engine Authors

The compact formatter is purely a presentation-layer concern. Engines do
not need to know about it — the formatter reads the engine's existing
output dict and produces a compacted JSON string. To verify your engine's
output compacts well, run:

```bash
$CLI <your-command> --format compact | python3 -m json.tool
```

If a field you depend on disappears in compact output, it's because the
value was null/empty (the formatter drops these). Either populate the
field with a meaningful default, or accept that null fields are noise.

---

### Graph Data Model (issue #8)

Replaces the ad-hoc flat-registry graph traversal with a true node + edge graph
backed by SQLite. This unblocks structural queries like "who calls this function
across the entire codebase", "blast radius if I rename this class", and
"circular dependency chains" — engines no longer need to reimplement partial
graph traversal logic.

### Added

- **`scripts/graph_model.py`** — New module implementing the graph data model:
  - `init_graph_schema(conn)` — Creates `graph_nodes` + `graph_edges` tables
    and 6 indexes (idempotent, called during database initialization).
  - `populate_graph_tables(workspace, db_path)` — Reads the flat backend
    registry and bulk-inserts all nodes + edges in a single transaction.
    Clears stale rows first so re-scans don't duplicate.
  - `query_callers(node_id, db_path, max_depth=1)` — BFS over CALLS edges
    in reverse (who calls this node).
  - `query_callees(node_id, db_path, max_depth=1)` — BFS over CALLS edges
    forward (what this node calls).
  - `clear_graph_tables(db_path)` — DELETE FROM both tables.
  - `find_nodes_by_name`, `graph_tables_exist`, `graph_tables_populated`,
    `graph_stats` — introspection helpers for engines and tests.

- **Graph schema** (additive, prefixed `graph_` to avoid collisions):
  ```sql
  graph_nodes(id, node_id UNIQUE, node_type, name, file, line, extra_json)
  graph_edges(id, source_id, target_id, edge_type, file, line,
              confidence, extra_json)
  ```
  Node types: `function|class|file|module|route|type|interface`
  Edge types: `CALLS|IMPORTS|DEFINES|INHERITS|IMPLEMENTS|USES_TYPE`
  (Only `CALLS` is populated in v8.2; other types are reserved for future
  engine migrations — `impact`, `circular`, `dependents`.)

- **`trace --use-graph` / `--no-graph` flags** — The `trace` command now
  queries the graph tables by default, with the flat-registry path retained
  as fallback. Use `--no-graph` to force the flat path for A/B testing.

- **`tests/test_graph_model.py`** — 20 test cases covering schema init,
  population, query_callers, query_callees, re-population idempotency, and
  the trace pilot A/B comparison.

### Git-Aware Incremental Re-Index (issue #14)

Replaces the file-watcher-only change detection with optional git-diff
awareness so incremental scans target exactly the files git knows changed
(tracked + untracked), instead of relying solely on filesystem mtimes.
All features gracefully degrade to None / [] / False / mtime-fallback
when git is unavailable or the workspace is not a git repo.

### Added (git-aware)

- **`scripts/git_aware.py`** — New module implementing the git-aware
  change-detection layer:
  - `get_current_sha(workspace)` / `get_current_branch(workspace)` —
    HEAD SHA + branch (None when not a git repo).
  - `get_changed_files(workspace, since_sha=None)` — `git diff
    --name-only` (HEAD or `<sha>`).
  - `get_untracked_files(workspace)` — `git ls-files --others
    --exclude-standard` so newly-created (not-yet-added) files are
    visible to incremental scans.
  - `get_last_indexed_sha` / `set_last_indexed_sha` — registry_meta
    key/value bookmark of the HEAD SHA + branch at the time of the last
    successful scan.
  - `detect_branch_switch(workspace, db_path)` — True when HEAD moved
    AND the branch name changed (catches `git checkout`, not same-branch
    commits).
  - `rescan_recommended(workspace, db_path)` — True when a branch
    switch is detected OR any changed files exist since the last index.
  - `init_registry_meta(conn)` — creates the `registry_meta(key TEXT
    PRIMARY KEY, value TEXT)` table (idempotent).

- **`scripts/commands/git_status.py`** — New `git-status` command
  (auto-registered). Single-call "do I need to re-scan?" check for AI
  agents. Reports: current_sha, current_branch, last_indexed_sha,
  last_indexed_branch, changed_files_count, branch_switch_detected,
  rescan_recommended. Always returns status=ok; git-unavailable is
  reported via git_available=False (not an error).

- **`tests/test_git_aware.py`** — 32 test cases across 9 classes
  (TestCurrentSha, TestChangedFiles, TestRegistryMeta, TestBranchSwitch,
  TestRescanRecommended, TestGitStatusCommand, TestDiffGitAware,
  TestIncrementalGitPath, TestScanStoresBookmark). All git operations
  use a temp directory + `git init` — no dependency on the CodeLens
  repo's git state. Tests skip with `pytest.skip('git not available')`
  when git is missing.

### Changed (git-aware)

- **`scripts/incremental.py`** — `find_changed_files` now tries the
  git-aware path FIRST: if a `last_indexed_sha` bookmark exists in
  `registry_meta`, uses `git diff <sha> --name-only` + `git ls-files
  --others` to enumerate exactly the files git knows changed. Deleted
  files (in diff but not on disk) are returned in the deleted slot so
  `scan.py`'s existing deletion-cleanup path runs unchanged. Falls back
  to the existing mtime-based detection when git is unavailable, no
  bookmark is stored, or any unexpected error occurs. Signature is
  backward-compatible — `db_path` is a new optional kwarg.
- **`scripts/commands/scan.py`** — After a successful scan (full or
  incremental), if git is available, persists `last_indexed_sha` +
  `last_indexed_branch` via `set_last_indexed_sha()`. Scan output now
  includes a `git` field with `{last_indexed_sha, last_indexed_branch}`
  so agents can verify the bookmark was recorded. Fail-soft: if the
  bookmark write fails, the scan still succeeds.
- **`scripts/commands/diff.py`** — New `--git-aware` flag. When set,
  the diff command produces a single-call "what changed + what's
  affected" view: changed_files (from git), symbols (from flat backend
  registry, filtered to changed files), impact (callers from
  `graph_model.query_callers` when graph tables are populated). Default
  snapshot-diff behavior is unchanged — `--git-aware` is purely
  additive. Falls back to `git_available=False` when git is unavailable
  (status stays "ok").
- **`scripts/commands/watch.py`** — New `--git-mode` flag (default
  off). When set, switches from watchdog file events to git-diff
  polling: every `--interval` seconds (default 2.0), runs `git diff
  --name-only` + `git ls-files --others` and re-indexes only the files
  git knows changed. Falls back to mtime polling when git is
  unavailable or the workspace is not a git repo. Default watchdog
  behavior is preserved (BOS decision: keep watchdog as default, ADD
  git-awareness as alternative).
- **`scripts/persistent_registry.py`** — Calls `init_registry_meta(conn)`
  during `_init_schema` so the `registry_meta` table always exists by
  the time any git-aware function tries to read or write a bookmark.
  Additive — no existing table or column modified.

### Non-Breaking (git-aware)

- All 56 existing CLI commands continue to work unchanged.
- The git-aware layer is purely additive — when git is unavailable, all
  functions return None / [] / False and the existing mtime path runs.
- The `registry_meta` table is additive — no existing table or column
  was modified.
- Scan output gained a new top-level `git` field; existing fields are
  untouched.
- The `diff --git-aware` flag is opt-in; default `diff` behavior is
  unchanged.

### Known Gaps (NOT made worse by this change)

- **Issue #25 (incremental graph population)** — Incremental scans
  still don't populate the graph tables (`graph_nodes` + `graph_edges`);
  only full scans do. `diff --git-aware` reports an empty `impact` array
  when graph tables aren't populated (e.g. after an incremental-only
  scan). This is a pre-existing gap tracked in #25 and is NOT made
  worse by this change.

### Hybrid Type Resolution (issue #13)

Adds a post-AST-pass type resolution layer that uses the per-file import
registry to refine CALLS edges. Previously `user.profile.update()` was
recorded as a call to `update` with no target type — the call graph had
holes wherever methods were called on imported objects. Now the receiver
type is resolved via the import registry, and the CALLS edge's
`target_id` is refined to the correct target node (e.g. `Profile.update`
in `models.py` instead of an arbitrary `update` match).

### Added (type resolution)

- **`scripts/hybrid_type_resolver.py`** — New module with:
  - `build_import_registry(workspace, db_path)` — Scans Python
    `from X import Y` / `import X.Y as Z` and TS/JS
    `import {Y} from 'X'` / `import * as X from 'Y'` statements. Stores
    results in a new `import_registry` SQLite table
    `(file, local_name, module_path, symbol_name, line)`. Also writes
    IMPORTS edges to `graph_edges` (edge_type='IMPORTS') so the graph
    model now carries import relationships alongside CALLS.
  - `resolve_receiver_type(file_path, receiver_expr, import_registry)` —
    Resolves a dotted receiver expression (`user.profile`) to a fully
    qualified type (`models.Profile`) via the import registry + class
    definitions in `graph_nodes`. Best-effort: returns `None` when
    unresolvable, never crashes.
  - `refine_call_edges(workspace, db_path)` — For each CALLS edge with
    a generic/unresolved `target_id`, attempts to resolve the receiver
    type and updates `target_id` to the resolved node. Stores
    `{"resolved_type": "...", "resolution_method": "import_registry"}`
    in the edge's `extra_json` on success, or
    `{"resolution_attempted": true, "failure_reason": "..."}` on failure.
    Returns stats: `{edges_total, edges_refined, edges_unresolved}`.

- **`resolve-types` command + `codelens_resolve_types` MCP tool** —
  Manually triggers type resolution without a full re-scan. Useful for
  agents who want to refresh type resolution after adding new imports.
  Output: `{status, edges_total, edges_refined, edges_unresolved,
  import_registry_size}`.

- **IMPORTS edges in graph model** — The graph now carries two edge
  types: `CALLS` (from #8) and `IMPORTS` (from #13). Future
  `query_graph` work (#9, Phase 3) can traverse both.

### Changed (type resolution)

- **`scripts/commands/scan.py`** — After `populate_graph_tables()` (from
  #8), calls `refine_call_edges(workspace, db_path)`. Scan output now
  includes a `type_resolution` field: `{edges_refined, edges_unresolved}`.
- **`scripts/graph_model.py`** — `graph_stats()` now reports IMPORTS
  edges in the `edge_types` breakdown alongside CALLS.

### Non-Breaking (type resolution)

- Type resolution is best-effort: unresolvable edges are left unchanged
  with a `resolution_attempted` flag. No CALLS edge is ever deleted.
- The `import_registry` table is additive — no existing table modified.
- On the `clean_app` fixture: 11/97 CALLS edges refined, 55 unresolved
  (the remaining 31 are self-referential or std-lib calls that don't
  need refinement). On the synthetic `type_resolution` fixture
  (`tests/fixtures/type_resolution/`), `user.profile.update()` correctly
  refines to `Profile.update` even when a `Cache.update` competitor
  exists.

### Changed

- **`scripts/persistent_registry.py`** — Calls `init_graph_schema(conn)`
  during `_init_schema` so the graph tables always exist by the time any
  engine tries to query them. Additive — existing tables untouched.
- **`scripts/commands/scan.py`** — After the flat backend registry is built,
  calls `populate_graph_tables(workspace, db_path)` to populate the graph
  tables in a single bulk transaction. Scan output now includes a `graph`
  field with node + edge counts.
- **`scripts/trace_engine.py`** — Pilot engine migration: `trace_symbol` is
  now a dispatcher that picks between `trace_via_graph` (default) and
  `trace_via_flat` (fallback). Falls back to flat automatically when graph
  tables are empty (pre-8.2 databases). Output shape is identical regardless
  of backend — callers and formatters don't need to know which backend ran.

### Non-Breaking

- All 56 existing CLI commands continue to work unchanged.
- Existing flat tables (`symbols`, `refs`, `files`, `analysis_cache`,
  `scan_metadata`) and JSON registries (`frontend.json`, `backend.json`)
  are untouched.
- The graph tables are additive — no existing table or column was modified.
- Scan performance impact is negligible (single bulk INSERT in one
  transaction; <5ms on the clean_app fixture with 31 nodes + 97 edges).

### Migration Notes for Engine Authors

The flat registry remains the source of truth during scan. The graph tables
are a derived projection that engines can query for structural traversals.
To migrate an engine to the graph backend:

1. Check `graph_model.graph_tables_populated(db_path)` — if False, fall back
   to the flat path (don't hard-fail).
2. Use `graph_model.find_nodes_by_name(name, db_path)` to find start nodes.
3. Use `graph_model.query_callers` / `query_callees` for BFS traversal.
4. Preserve the existing flat-path output shape so callers and formatters
   don't break. See `trace_engine.trace_via_graph` for a reference impl.

Future engine migrations (post-v8.2): `impact`, `circular`, `dependents`.

### `get_architecture` — single-call codebase overview (issue #19)

Orientation on an unfamiliar codebase previously required 4-6 chained commands
(scan → list → detect → entrypoints → api-map → read entry files), burning
10-20k tokens before any real work started. The new `architecture` command
+ `codelens_architecture` MCP tool collapses that into a single call returning
a compact overview: languages, frameworks, entry points, packages, top routes,
graph hotspots, total symbol count, and an `adrs` placeholder (ADR feature is
issue #16, Phase 3).

#### Added

- **`scripts/architecture_engine.py`** — New engine module orchestrating
  existing engines into one overview:
  - `get_architecture(workspace, lite=False)` — single public entry point.
  - `_compute_languages` — three-tier resolution: fresh scan_result's
    `files_scanned` → `.codelens/summary.json` → cheap stat-only extension
    walk. Scan-result buckets are collapsed to canonical language names
    (e.g. `js_backend` + `js_frontend` → `javascript`).
  - `_compute_frameworks` — thin wrapper around `framework_detect`.
  - `_compute_entry_points` — wraps `entrypoints_engine.map_entrypoints`,
    dedupes by file path, prioritises main/handler/cli types.
  - `_compute_packages` — scans `src/`, `app/`, `lib/`, `packages/`,
    `server/`, `internal/` for immediate subdirectories that contain source
    files (one level of recursion allowed for flat two-tier packages).
  - `_compute_routes` — wraps `apimap_engine.map_api_routes`, normalises
    each route to `{method, path, handler}`, capped at 20.
  - `_compute_hotspots` — single SQL round-trip: `SELECT gn.file,
    COUNT(*) FROM graph_edges JOIN graph_nodes ... GROUP BY gn.file
    ORDER BY cnt DESC LIMIT 5`. This is the killer feature of the new
    graph model — files ranked by total incoming CALLS edges across all
    their symbols (blast-radius surface).
  - `_compute_total_symbols` — `graph_stats(db_path).nodes`.
  - Cache layer: writes `.codelens/architecture_cache.json` on first call;
    subsequent calls return the cache as long as `.codelens/codelens.db`
    mtime hasn't advanced (i.e. scan hasn't been re-run). Lite and full
    payloads have different shapes — the cache won't serve the wrong shape
    even when the db is unchanged.

- **`scripts/commands/architecture.py`** — New CLI command auto-registered
  via `commands/__init__.py`. Flags: `--lite` (omit routes/packages/hotspots
  for <1k token orientation), `--no-cache` (force rebuild).

- **`codelens_architecture` MCP tool** — Added to `_TOOL_DEFINITIONS` in
  `scripts/mcp_server.py`. Schema: `{workspace: string}` required;
  `{format: string, lite: boolean}` optional. Calls the `architecture`
  command internally.

- **`tests/test_architecture.py`** — 24 test cases covering all eight spec
  verification points: status ok, all required fields, lite mode shape,
  hotspots sorting + graph query match + distinct files, cache create +
  reuse + invalidation + lite/full shape isolation, MCP tool listing +
  end-to-end call, <4000-byte token budget (raw + MCP-normalised).

#### Design Decisions

- **Architecture-specific fields nested inside `stats`** — The MCP
  `_normalize_to_ai` formatter preserves `stats` as-is but drops unknown
  top-level keys. To deliver the full architecture data through MCP without
  modifying the shared formatter (which would collide with parallel worker
  2-a's compact-format changes), all architecture fields (languages,
  frameworks, entry_points, packages, routes, hotspots, total_symbols, adrs)
  are nested inside `stats`. CLI consumers see the same shape.
- **`adrs` placeholder is `[]`** — ADR detection is issue #16 (Phase 3).
  The field is reserved so consumers can rely on the shape today.
- **Auto-scan on fresh workspace** — If `.codelens/codelens.db` doesn't
  exist or the graph tables are empty when `architecture` is called, the
  engine runs `cmd_scan` first. This makes the tool self-sufficient for
  the issue #19 use-case ("agent starts on an unfamiliar codebase").
- **File-level hotspots (not per-symbol)** — The SQL query groups by
  `gn.file`, not `ge.target_id`, so each hotspot is a distinct file with
  its total blast radius. Matches the issue spec example
  `"src/models/user.py (47 dependents)"`.

#### Token Budget Verification (clean_app fixture)

- `--lite` raw engine payload: **284 bytes** (~71 tokens)
- `--lite` MCP-normalised response: **298 bytes** (~75 tokens)
- Full raw engine payload: **502 bytes** (~125 tokens)
- Full MCP-normalised response: **515 bytes** (~128 tokens)

All well under the 1k-token target.

---

## [8.1.0] — 2026-06-13

### F1 Benchmark Improvements

- **Avg F1: 0.803 → 0.872 (+8.6%)**
- **Avg FPR (clean): 0.153 → 0.050 (-67%)**
- **Targets met: 28.6% → 57.1%**

### Circular Engine Fixes

- Added module-level cycle detection in `_detect_function_cycles`
- Added bidirectional import pair safety net in `_detect_import_cycles`
- Added cross-type deduplication between `function_call` and `import_chain` cycles
- **Result:** circular F1 0.667 → 1.000, circular FPR (clean) 0.222 → 0.000

### Dead-Code Engine Fixes

- Fixed JS local export vs re-export differentiation (`export { X }` vs `export { X } from`)
- Fixed Python unreachable code indent comparison (`<=` → `<`)
- Fixed Python multi-line return statement bracket counting
- **Result:** dead-code F1 0.800 → 0.952, dead-code FPR (clean) 0.500 → 0.000

### AST Taint Engine Depth Improvements

- **Return value propagation** — functions returning tainted data now propagate taint to callers
- **Scope-hierarchical TaintState** — parent chain lookup prevents cross-scope contamination
- **Branch condition refinement** — `branch_condition` is now used during propagation for path-sensitive analysis

### CI/CD Integration

- Added `.github/workflows/codelens-ci.yml` (test + benchmark + self-check + SARIF upload)
- Added `.github/workflows/codelens-quality-gate.yml` (PR quality gate)
- Added `.github/workflows/codelens-sarif.yml` (SARIF upload to GitHub Security)
- Added `.github/workflows/codelens-benchmark.yml` (regression benchmark)
- Added `.gitlab-ci.yml` (GitLab CI pipeline)

### Documentation

- Added honest competitive positioning table to README (vs SonarQube, CodeQL, Semgrep)
- Updated README command tables to cover all 56 commands (was ~39)
- Updated MCP tool count: 54 (49 static + 5 dynamic)
- Updated architecture tree to reflect actual `scripts/` directory structure
- Synced SKILL.md, SKILL-QUICK.md version numbers to v8.1

---

## [8.0.0] — 2026-06-13

### The "7 Killer Features" Release

Real-world tested against multiple large open-source codebases (spacedriveapp/spacedrive, exercism/python, redis/redis, neovim/neovim, readest/readest, BurntSushi/ripgrep, calcom/cal.com, excalidraw/excalidraw, n8n-io/n8n, cockroachdb/cockroach, denoland/deno, Vercel Turborepo).

### Added — 7 Major Features

1. **AST-based Taint Analysis Engine** (`ast_taint_engine.py`, 3057 lines)
   - Real tree-sitter AST traversal replaces regex line-by-line
   - Path-sensitive, scope-aware, inter-procedural taint tracking
   - Confidence scoring with taint path rendering
   - Default engine when tree-sitter is available
   - New command: `taint`

2. **Live CVE/OSV Database Integration** (`osv_client.py`, 1600 lines)
   - Real-time vulnerability data from OSV.dev API
   - 9 ecosystems: PyPI, npm, crates.io, Go, Maven, NuGet, RubyGems, Pub, Hex
   - SQLite cache with configurable TTL (24h default)
   - Rate limiting + offline mode fallback
   - Phase 0 in `vuln-scan` pipeline (before native audit tools)

3. **Plugin System & Rule Marketplace** (`plugin_system.py`, 1462 lines)
   - 4 plugin types: `rule_pack`, `engine`, `formatter`, `command`
   - 3-tier discovery: local (`.codelens/plugins/`) > user (`~/.codelens/plugins/`) > built-in (`scripts/plugins/`)
   - New command: `plugin <install|list|search|update|info|validate>`
   - Built-in OWASP Top 10 plugin (36 rules, all 10 categories A01-A10)
   - Built-in Compliance plugin (53 rules: PCI-DSS v4.0 + HIPAA Security Rule)

4. **VS Code Extension** (`vscode-codelens/`, 2011 lines)
   - Diagnostics Provider (SARIF → VS Code on save/open)
   - Code Actions Provider (QuickFix + Fix All)
   - Guard pre-save hooks
   - Status bar health indicator (green/yellow/red)
   - 8 configuration settings
   - Supports Python, JavaScript, TypeScript

5. **Enhanced Cross-File Dataflow Engine** (`callgraph_engine.py`, 3539 lines)
   - Workspace-wide call graph using tree-sitter
   - Cross-file import resolution (`from/import`, `require` destructuring)
   - Data flow graph with forward + reverse taint propagation
   - Inter-procedural taint across file boundaries

6. **OWASP Top 10 + Compliance Mapping** (89 rules total)
   - A01-A10 all covered with Python + JavaScript rules
   - PCI-DSS v4.0: 32 rules mapping Requirements 1-12
   - HIPAA Security Rule: 21 rules mapping 45 CFR § 164.312

7. **Bug Fixes (10 critical bugs)**
   - `semantic_engine.py`: sanitizer detection logic
   - `hybrid_engine.py`: loose path comparison → `os.path.samefile`
   - `persistent_registry.py`: thread-local SQLite connections + WAL mode
   - `javascript_security.yaml`: normalized schema (`id`/`name`)
   - `--deep` argument conflict between `artifact-scan` and global flag

### Added — Additional Features

- **Auto-fix engine** (`autofix_engine.py`) — confidence-scored fixes, dry-run by default. New command: `fix`
- **HTML dashboard engine** (`dashboard_engine.py`) — visual dashboards with trend tracking. New command: `dashboard`
- **Historical trend tracking** (`history_engine.py`). New command: `history`
- **Semantic rules engine** (`semantic_engine.py`) — taint analysis for vulnerability detection
- **Hybrid analysis engine** (`hybrid_engine.py`) — LSP integration for deep accuracy (`--deep` flag)
- **SQLite persistent registry** (`persistent_registry.py`) — incremental scanning + analysis cache. New command: `migrate`
- **LSP status command** — `lsp-status` checks which language servers are available for `--deep` analysis
- **Benchmark suite** (`benchmarks/`) — accuracy metrics, regression testing, fixtures (`clean_app` + `vulnerable_app`). New command: `benchmark`
- **Self-analyze command** — `self-analyze` runs CodeLens on its own codebase
- **Pre-commit hook** (`pre_commit_hook.py`) — Git hook integration

### CI/CD & Quality

- 248 new tests added across `tests/`
- SARIF v2.1.0 output formatter (`formatters/sarif.py`)
- Markdown output formatter (`formatters/markdown.py`)
- `check` command — CI/CD quality gate that exits non-zero on failure
- `analyze` command — full repo analysis: init + scan + all engines in one shot
- `summary` command — auto-summary with prioritized findings (anti-overload)
- `handbook` command — generate project handbook for AI agents

### Version Bumps

- CLI version: v7.2 → v8.0 → v8.1
- Total commands: 45 → 56 (+11 new)
- Total MCP tools: 49 static → 54 (49 static + 5 dynamic)
- Total engines: ~23 → ~35
- Total parsers: 9 tree-sitter + 28 fallback = 37 total parser modules

### New Commands (11)

`analyze`, `artifact-scan`, `benchmark`, `binary-scan`, `check`, `fix`, `guard`, `handbook`, `lsp-status`, `migrate`, `plugin`, `serve`, `summary`, `taint`, `dashboard`, `history`

(Plus `serve` which was the MCP server entry point — previously internal, now a registered command.)

---

## [6.3.2] — 2026-06-12

### Tested against spacedriveapp/spacedrive (2,905 files, 1,166 Rust files, 404 TS/TSX, 62K edges)

Real-world test on a Tauri VDFS (Virtual Distributed Filesystem) file explorer monorepo —
a unique architecture combining a Rust core with P2P networking, React/TSX frontend,
Tauri desktop app, React Native mobile app, and WASM extensions. This repo exposed
false positives in the secrets engine and dead code in the query command.

### Fixed

- **`secrets` engine URI scheme false positive** (HIGH): The URL-embedded password pattern
  `[\w+\-\.]+:([^\s@"\']{4,})@` matched URI paths like `sidecar://content_id/thumbs/grid@2x.webp`
  as passwords because the capture group `[^\s@"\']` allowed `/` characters. URI schemes with
  `://` and `@` in the path (common in custom protocol handlers) were incorrectly flagged as
  `password` with severity `critical`. Fixed by adding `/` to the excluded character class:
  `[^\s/@"\']{4,}`. This still correctly captures real URL-embedded passwords like
  `user:password@host.com` and `ftp://user:pass@host.com` (which match from the `user:pass`
  portion), while rejecting paths with `/` that are clearly URI paths, not credentials.

- **`ask` command symbol extraction missed common question prefixes** (MEDIUM): The
  `_extract_symbol_name()` function only stripped prefixes like "what is", "where is",
  "how does" but missed "what does", "what do", "why does", "why do", "when does",
  "when do", "how can", "how should". This caused questions like "What does the Library
  struct do?" to extract "what" as the symbol instead of "library", making the ask
  command completely useless for these common question patterns. Added all 8 missing
  prefixes. Also added pronoun fillers ("i ", "we ", "you ", "they ", "my ", "our ")
  to prevent them from being extracted as symbol names (e.g., "How can I find..."
  now extracts "find" instead of "i").

- **`query --fuzzy` was dead code when zero exact matches** (HIGH): The fuzzy matching
  block was placed AFTER the `total_matches == 0` early return, meaning `--fuzzy` was
  completely non-functional when there were no exact matches — precisely the scenario
  where fuzzy matching is most needed. For example, `query spawn --fuzzy` returned
  "Name does not exist. Safe to create." even though `symbols spawn` found 12 matches.
  Moved the fuzzy matching block BEFORE the early return so it executes when either
  `--fuzzy` is enabled OR no exact matches are found. Removed the duplicate fuzzy
  block that was unreachable at the bottom of the function.

## [6.4.0] — 2026-06-12

### Tested against exercism/python (2,227 files, 516 Python files, pytest-based exercise track)

Real-world test on a pure Python project with no web frameworks — exposed multiple blind spots
in framework detection, project identity classification, and broken command imports.

### Fixed

- **`is_bundled_file` missing from `utils.py`** (CRITICAL): `complexity_engine.py` and `perfhint_engine.py` imported `is_bundled_file` from `utils`, but the function never existed. This caused `ImportError` during command registration, silently breaking `complexity`, `perf-hint`, `ask`, and `context` commands (4 of 45 commands non-functional). Added `is_bundled_file()` to `utils.py` with detection for dist/build/vendor dirs, minified files, source maps, and common bundled naming patterns.
- **`analyze` command env check used wrong API** (CRITICAL): `_detect_env()` called `audit_environment()` which doesn't exist — the correct function is `check_env_vars()`. Also used wrong return keys (`total_issues`, `issues` instead of `total_vars`, `required_without_fallback`). The `env_issues` category was always skipped in analysis output.
- **`analyze` command hardcoded version**: Output showed `codelens_version: "6.0"` instead of using `CODELENS_VERSION` constant (was `6.3.0`). Now imports from `utils.py`.
- **`pyproject.toml` formatting error**: Missing newlines between `description`/`readme` and `requires-python`/`authors` caused TOML parse failure.

### Added

- **Python tooling framework detection**: Added 7 new Python framework signatures: `pytest`, `poetry`, `setuptools`, `tox`, `sphinx`, `nox`, `hatch`. Includes `pip_packages`, `config_files`, and `indicators` for each. Added `has_pytest`, `has_poetry`, `has_python` flags to detection output.
- **Pipfile dependency parsing**: Comment said "Check Python dependency files (requirements.txt, pyproject.toml, Pipfile)" but Pipfile was never actually parsed. Now parses `[packages]` and `[dev-packages]` sections.
- **Improved pyproject.toml Poetry dependency parsing**: Poetry uses list-style deps like `dependencies = ["requests>=2.0", "flask"]` and section-scoped deps under `[tool.poetry.dependencies]`. Added section-aware TOML parsing for Poetry and PEP 621 dependency formats.
- **Python project identity fallback**: `_extract_project_identity()` now detects Python projects from `requirements.txt` (with content analysis: web framework → `backend-api`, testing → `python-test-suite`, else → `python-project`), `setup.py`/`setup.cfg` → `python-library`, and `.py` file existence → `python-project`. No more `type: "unknown"` for pure Python repos.
- **`scan_tauri_artifacts()` implementation**: `binary_scan.py` imported `scan_tauri_artifacts` from `utils` but it didn't exist (gracefully caught by try/except). Now implemented: parses `tauri.conf.json` for IPC commands, security settings (CSP, asset protocol), sidecar binaries, and warns about dangerous patterns.
- **Command import error logging level**: Changed from `WARNING` to `ERROR` in `commands/__init__.py` so broken command modules are more discoverable.
- **`.py` file detection in framework walk**: Added Python file detection alongside `.vue`, `.svelte`, `.php` in the file pattern walking loop, setting `has_python: True`.

## [6.4.0] — 2026-06-12

### Tested against redis/redis (1,844 files: 471 C + 311 H + 20 Lua + 46 Python + 228 TCL + 69 Shell, in-memory database)

Real-world test on a pure C project with Makefile build system, embedded Lua scripting,
and polyglot codebase (C+Lua+Python+TCL+Shell). Exposed critical gaps in C/C++ project
support that were invisible on JS/TS/Rust/Go projects.

### Fixed

- **`is_bundled_file()` missing from `utils.py`**: `perfhint_engine.py` and `complexity_engine.py` imported `is_bundled_file` from `utils`, but the function was never defined there. This broke 4 commands silently: `ask`, `complexity`, `context`, `perf-hint`. Added `is_bundled_file()` to `utils.py` with detection for `deps/`, `vendor/`, `third_party/`, `external/`, `submodules/`, and minified/bundled file patterns.

- **Drupal false positive from `modules/` indicator**: Redis (and many non-Drupal projects) have a `modules/` directory, which was listed as a Drupal indicator. Replaced `modules/` and `themes/` with `sites/default/` and `sites/all/` — directories that are truly unique to Drupal installations. This eliminates the false positive on Redis and similar C projects with module systems.

- **C/C++ function name false positives in `smell_engine.py`**: The regex `r'(?:static\s+|inline\s+)*(?:\w+[\s*]+)+(\w+)\s*\('` matched C type keywords like `void`, `const`, `unsigned`, `signed`, `volatile`, `extern`, `register`, `auto`, `static`, `inline` as function names, producing absurd findings like "Function 'void' is 248 lines". Added all C type keywords and storage-class specifiers to the skip list.

- **C/C++ function name false positives in `fallback_c.py`**: Same issue as smell_engine — the parser's skip list was missing `void`, `const`, `unsigned`, `signed`, `volatile`, `extern`, `register`, `auto`, `static`, `inline`. Extended the skip list to match.

- **C/C++ listed as `unsupported_langs`**: Despite having working fallback parsers (790 C/C++ files successfully parsed on redis/redis), C and C++ were listed in `UNSUPPORTED_MARKERS` in `framework_detect.py`, causing the scan output to say "these languages are not yet supported". Removed C/C++ from `UNSUPPORTED_MARKERS` since they have fallback parser support.

### Added

- **C/C++ project framework detection**: Added `c_project` framework detection in `framework_detect.py` when a Makefile/CMakeLists.txt is found alongside C/C++ source files. This gives C projects proper framework recognition instead of empty framework lists.

- **C/C++ project identity detection in handbook**: Added C/C++ project type detection in `_extract_project_identity()` with Makefile version/name extraction. Supports classification as `c-database` (projects with `.conf` files like redis.conf), `c-infrastructure` (nginx-like structure), or `c-project` (generic). Polyglot C+Python/Lua projects get combined type like `c-python-polyglot`.

- **`c_type` in polyglot detection**: Extended the polyglot type builder to include C projects alongside Rust, Go, JS, and Python types.

## [6.4.0] — 2026-06-12

### Tested against neovim/neovim (3,856 files: 506 C/C++ + 816 Lua + 12 Shell + 8 Python + 4 JS, C/Lua text editor project)

Real-world test on a C/Lua polyglot project (CMake + Lua runtime). This test exposed
critical issues with non-web projects that have no package.json, pyproject.toml, or Cargo.toml.

### Fixed

- **Critical: `is_bundled_file` missing from `utils.py`** — 4 commands (`ask`, `complexity`, `context`, `perf-hint`) crashed on import because `complexity_engine.py` and `perfhint_engine.py` imported `is_bundled_file` from `utils` but it didn't exist. Added `is_bundled_file()` with directory segment detection (dist/, build/, vendor/, etc.) and bundled filename suffix detection (.bundle.js, .chunk.js, .umd.js, etc.).
- **Critical: `audit_environment` ImportError in `analyze` command** — `_detect_env()` in `analyze.py` called `from envcheck_engine import audit_environment` but the actual function name is `check_env_vars`. Fixed to use the correct import and adapt the response structure.
- **C/C++ no longer listed as "unsupported"** — `framework_detect.py` listed C, C++, Java, Kotlin, C#, Swift, Ruby as "unsupported" based on build system markers (CMakeLists.txt, pom.xml, etc.), even though fallback parsers for ALL these languages were working and extracting thousands of nodes. Now only truly unsupported languages (Zig, OCaml, Perl, Clojure, F#, Erlang, Fortran) are listed. Updated `lang_note` message to be more accurate.
- **Identity detection for C/CMake projects** — Handbook reported `type: unknown`, `version: 0.0.0`, `name: <folder>` for C/C++ projects. Added CMakeLists.txt parsing to extract project name (`project(Name)`), version (`project(Name VERSION x.y.z)` and `set(VERSION_MAJOR/MINOR/PATCH)`), and classify project type (c-lua-application, c-gui-application, c-service, c-library, c-application, c-project).

### Added

- **Languages field in handbook output** — New `languages` key in handbook response with accurate language distribution (e.g., `{"Lua": 816, "C/C++": 506, "Shell/Bash": 12}`). Merges outline engine data with scan result's `files_scanned` for complete coverage including fallback parser languages.
- **Architecture detection in handbook** — New `architecture` key with pattern detection: `core-plugin` (C core + Lua runtime), `client-server`, `mvc`, `core-api`, `fullstack`, `monorepo`, etc. Also includes `key_directories` and `description`.
- **CMake `set(VERSION_MAJOR/MINOR/PATCH)` version extraction** — Projects that don't use `project(Name VERSION x.y.z)` but instead use `set(NVIM_VERSION_MAJOR 0)` etc. now get version detected correctly.
- **`compute_summary` now includes fallback parser languages** — `files_by_language` in `summary.json` previously only contained tree-sitter supported languages (Python, JS, etc.). Now merges `scan_result.files_scanned` data so C/C++, Lua, Go, Java, Kotlin, etc. appear in the summary.

## [6.4.0] — 2026-06-12

### Tested against fastapi/fastapi (1,130 Python files, 48 core library + 582 tests + 454 docs examples)

Real-world test on a pure Python library project. FastAPI's unique structure — a small
core library with massive docs_src/ example directories and comprehensive test suites —
exposed critical false positive patterns that were invisible on application-type repos
(prior testing: vercel/swr for React hooks, n8n-io/n8n for Vue/TS monorepo).

### Fixed

- **CRITICAL: Missing `is_bundled_file()` function** — 4 engines crashed on import (`ask.py`, `complexity.py`, `context.py`, `perf_hint.py`). The function was referenced in `perfhint_engine.py` and `complexity_engine.py` but never defined in `utils.py`. Added proper implementation that detects dist/, build/, out/, minified, and bundled file patterns.

- **CRITICAL: `api-map` command crash** — `map_api_routes()` received unexpected keyword argument `production_only`. The command passed it but the engine function signature didn't accept it. Added `production_only` parameter to `map_api_routes()` with route source filtering.

- **SQL injection false positives (16 → 0 on FastAPI)** — f-strings containing English words like "Updated", "Created", "update", "DELETE" were flagged as SQL injection. Examples: `f"Updated {path}"`, `f"Created PR: {pr.number}"`, `f"Please update the response model {type_!r}"`. Fixed by requiring: (1) a secondary SQL keyword (FROM, WHERE, SET, INTO, TABLE, VALUES, JOIN, etc.) in the same string, AND (2) the primary keyword must appear at or near the start of the string content.

- **docs_src/example directory inflation** — 454 docs example files in FastAPI inflated ALL metric categories. `smell_engine.py` now downgrades all smells from docs/examples/test files to "info" severity with `source: "docs_example"` tag. `debugleak_engine.py` skips docs/example directories entirely. `deadcode_engine.py` skips docs_src paths in unused_exports and registry_dead. `deep_nesting` detection skips /tests/, /docs_src/, /examples/ directories.

- **Library code false positives in deadcode** — 189 "unused exports" in FastAPI core library were actually public API, not dead code. Added `_detect_library_package()` that detects Python packages (with __init__.py re-exports, `__all__`), JS libraries (main/module/exports in package.json without scripts.start). For detected libraries: capitalized exports are assumed public API, severity downgraded to "info", message includes "library public API — may be used by consumers". Also skip __init__.py files entirely (re-export entry points).

- **Secrets false positives in test files (10 → 0 on FastAPI)** — All 10 "secrets" were dummy test data: `hashed_password="secrethashed"`, `"password": "incorrect"`. Added `_is_obvious_test_value()` that catches: dictionary dummy passwords (secret, test, incorrect, fake, mock, etc.), very short alpha-only values (≤4 chars), and test-prefixed patterns (test_*, fake_*, mock_*). Only applied in test files to preserve real secret detection.

- **Deep nesting false positives in test directories (925 items removed)** — Test files in /tests/ directory had deep nesting from test setup patterns (pytest fixtures, nested describe blocks). Added /tests/, /docs_src/, /examples/ to skip_dirs in `_detect_deep_nesting()`.

- **Debug leak false positives in docs/examples** — docs_src example files used print() as demo output, not debug code. Added `DOCS_EXAMPLE_PATTERNS` and skip logic to `debugleak_engine.py`.

- **`analyze` command showed wrong version "6.0"** — Hard-coded string instead of importing `CODELENS_VERSION` from utils. Now imports and uses the constant.

### Added

- **`is_bundled_file()` utility function** — Detects bundled/compiled files (dist/, build/, .min.js, .bundle.js, .d.ts, etc.) for engine skip logic. Used by complexity and perf_hint engines.
- **`_detect_library_package()` in deadcode engine** — Detects if workspace is a library vs application, adjusts unused_exports severity accordingly.
- **`_is_obvious_test_value()` in secrets engine** — Filters out clearly fake test credentials (dummy passwords, test patterns).
- **docs_src/doc_src/examples/documentation directory patterns** — Added across all engines (apimap, smell, deadcode, debugleak) for consistent exclusion of documentation example code.
- **API map `production_only` filtering** — Now actually works, filtering routes tagged as "test" source.

## [6.3.1] — 2026-06-12

### Tested against spacedriveapp/spacedrive (2,934 files, Rust+TS+Swift Tauri monorepo)

Real-world test on a massive virtual distributed filesystem Tauri desktop app (38K+ GitHub stars)
with 16+ Rust crates (including procedural/derive macros), 1,166 Rust files, 405 TS/TSX files,
17 Swift files, 3 Kotlin files, and complex cross-language FFI boundaries. The registry built
13,350 backend nodes and 62,780 edges — one of the most diverse test targets to date.

### Fixed

- **CRITICAL: `is_bundled_file()` missing from utils.py** — The function was imported by
  `complexity_engine.py` and `perfhint_engine.py`, but never defined in `utils.py`. This caused
  ImportError cascade that completely disabled 4 commands: `ask`, `complexity`, `context`, and
  `perf-hint`. Added the missing function with detection for dist/build/out directories, bundled
  file extensions (.bundle.js, .chunk.js, .global.js), minified files, and declaration files.
- **`api-map` crash on `production_only` kwarg** — The `api-map` command passed `production_only`
  argument to `map_api_routes()`, but the engine function did not accept this parameter. Added
  `production_only: bool = False` parameter to `map_api_routes()` and implemented the filter
  that removes test-sourced routes when the flag is set.

## [6.3.1] — 2026-06-12

### Fixed

- **CRITICAL: 4 broken commands restored** — `ask`, `complexity`, `context`, `perf-hint` commands failed to import due to missing `is_bundled_file` symbol in `utils.py`. The new v6.3.0 engines (`complexity_engine.py`, `perfhint_engine.py`) and their consumers reference `is_bundled_file()` but the function was never added to `utils.py`.
- **HIGH: apimap_engine crash on None path** — `_build_route_groups()` and `_is_route_deprecated()` crashed with `AttributeError: 'NoneType' object has no attribute 'split'` when route dict had `path: None`. Fixed by using `route.get("path") or "/"` instead of `route.get("path", "/")` which doesn't handle explicit `None` values.

### Added

- **`is_bundled_file()` function** (`utils.py`): Detects bundled/compiled artifacts (minified JS/CSS, vendor bundles, webpack chunks with content hashes, dist/build output directories). Used by `complexity_engine` and `perfhint_engine` to skip non-source files.
- **`BUNDLED_FILE_PATTERNS`** and **`BUNDLED_DIR_SEGMENTS`** constants in `utils.py` for consistent bundled file detection across engines.

### Test Target Documentation

- **meilisearch/meilisearch** (GitHub): Used as test target for v6.3.1 — a search engine written in Rust with 21 workspace crates, 692 .rs files, 12214 backend nodes, 490543 edges. Detected frameworks: rust, tokio, actix-web. Monorepo with cargo-workspace. Health score: 50/100 (677 critical smells, god object Index with 99 methods). 2 potential secrets in open_api_utils.rs. 1299 debug leaks (851 commented code, 310 debug_log). 402 dead code items. 200 circular dependencies.


## [6.1.0] — 2026-06-12

### Tested against database & XHR/network repos: Redis, LevelDB, Axios, Undici, libuv

Round 2 real-world testing targeting database systems (Redis C, LevelDB C++) and
HTTP/network libraries (Axios JS, Undici JS, libuv C). Exposed critical dead-code
accuracy gaps where exported symbols were falsely marked as "dead".

### Fixed

- **CRITICAL: JS/TS exported symbols falsely marked as dead** (`js_backend_parser.py`, `ts_backend_parser.py`, `fallback_js_backend.py`): The `export` keyword was never propagated to backend registry nodes. Exported classes like `AxiosError`, `EventEmitter`, and `CustomError` appeared as "dead" (0 ref_count, `exported: False`). Now all three parsers detect `export_statement` AST nodes and set `exported: True` on function/class/variable declarations. AxiosError now correctly shows `status: "active"`.
- **CRITICAL: Incremental scan status computation ignores exported/component/pub flags** (`incremental.py`): `merge_backend_data()` used simple `ref_count == 0 -> dead` without checking `exported`, `component`, or `pub` flags. Now uses the same 3-condition check as `edge_resolver.resolve_edges()`.
- **HIGH: Rust `pub fn` falsely marked as dead** (`edge_resolver.py`): `resolve_edges()` only checked `exported` and `component` flags, but Rust uses `"pub": True` (separate key). A `pub fn` with no internal callers was marked `"dead"`. Now also checks `node.get("pub", False)`.
- **HIGH: Dead-code engine misses exported/component flags** (`deadcode_engine.py`): `_detect_dead_from_registry()` skipped `pub` functions but not `exported` or `component` nodes. Now checks all three flags.
- **MEDIUM: Drupal false positive on non-PHP repos** (`framework_detect.py`): Generic indicators `modules/` and `themes/` matched Redis directory. Replaced with specific indicators `sites/default/` and `sites/all/`. Redis no longer falsely detected as Drupal.
- **MEDIUM: HTTP/network libraries not detected** (`framework_detect.py`): Added 7 HTTP library signatures (axios, undici, got, ky, superagent, node-fetch, request), `has_http_library` flag, and `package.json` name field detection for when the repo IS the library.
- **MEDIUM: PascalCase classes too narrow in tree-sitter JS parser** (`js_backend_parser.py`): Only React-extending classes were `component: True`. Now any PascalCase class is marked as `component: True`.

### Test Repos Used

| Repo | Language | Size | Theme | Key Finding |
|------|----------|------|-------|-------------|
| redis/redis | C | ~70MB | Database | Drupal FP (modules/ dir) |
| axios/axios | JS | ~5MB | XHR/Network | AxiosError dead, HTTP lib detection |
| nodejs/undici | JS/TS | ~40MB | XHR/Network | HTTP lib detection |


## [5.10.0] — 2026-06-12

### Tested against n8n-io/n8n (20,355 files: 9,101 JS + 4,626 TSX + 1,092 Vue + 66 Python, workflow automation monorepo)

Real-world test on a massive TypeScript/Vue/Express monorepo (pnpm-workspace + Turborepo).
This is the largest repo tested to date, exposing critical scalability and accuracy issues
that were invisible on smaller projects.

### Fixed

- **Frontend registry CSS class name validation** (2,853 false positives removed, 7,792 → 4,687 classes): Vue `:class` binding expressions like `!!hint,`, `!!item.disabled`, `!==`, `!action.completed,` were stored as CSS class names. Added `_is_valid_css_class_name()` validation in `registry.py` that rejects names starting with `!`, containing operators (`()?.<>=+*/`), longer than 80 chars, or not matching `^[a-zA-Z_-][\w-]*$`.
- **Framework detection for monorepo sub-directory packages**: `detect_frameworks()` only checked root `package.json`, missing React/Vue/Express in workspace packages. Now scans `apps/*/package.json`, `packages/*/package.json`, and `packages/@scope/name/package.json`. Correctly detects `has_vue: true`, `has_express: true` for n8n.
- **Edge resolver built-in JS method filtering**: `resolve_edges()` created resolved edges to `add`, `then`, `setTimeout`, `race`, `clearTimeout`, `includes`, `indexOf`, `substring`, `trim`, `reject`, etc. — treating JS built-in methods as project-defined functions. Now checks `_STD_LIB_METHODS` before resolution (expanded from 80 to 110+ entries). Impact analysis no longer shows these as dependents.
- **API map false positives** (2,922 → 0 test routes with `--production-only`): Added `--production-only` flag. Vue plugins (ChatPlugin, SentryPlugin, PiniaVuePlugin) no longer detected as Express middleware. Tauri detection now requires `src-tauri/Cargo.toml` (not just `invoke()` calls). Auth-protected routes now detected by middleware name patterns (`jwt`, `passport`, `authenticate`, `verifyToken`).
- **Entrypoints garbage test names**: Test names like `:`, `,`, `=` from malformed `it()` parsing. Fixed with word boundary regex and punctuation-only name filtering.
- **Dead code numeric literal false positives**: Numeric literals like `300_000` and `10000` detected as "unused variables". Added `^\d[\d_]*$` pattern check to skip numeric literals.
- **Debug leak config file false positives**: `testEnvironment: 'node'` and `testRegex` in `jest.config.js` flagged as "mock data". Config files (`*.config.js/ts`, `jest.config.*`, `vite.config.*`, etc.) now get severity downgraded to "info" with note "in config file — not production code".
- **Complexity output not sorted by complexity**: Functions listed in file order. Now sorted by complexity level (untamable → very_complex → complex → moderate → simple), then cyclomatic descending.
- **`analyze` command timeout on large repos**: No `--max-files` or per-engine timeout. Added `--max-files` argument (default 5000) and per-engine 30s timeout using `signal.SIGALRM`. Timed-out engines report gracefully instead of blocking.

### Added

- **`api-map --production-only` flag**: Filter out test routes for a clearer picture of production endpoints.
- **`has_express` field** in framework detection output.
- **Auth detection** in API map: middleware names containing auth patterns are flagged.
- **Config file awareness** in debug-leak engine: config files get `severity: "info"` and `should_remove: false`.

## [5.9.2] — 2026-06-12

### Tested against vercel/swr (254 source files: 114 TSX + 99 JS backend + 34 JS frontend, React+Next.js monorepo)

Real-world test on a TypeScript/React data-fetching library. Confirmed significant false positive reduction
across all analysis engines after targeted fixes based on SWR analysis findings.

### Fixed

- **Dataflow `command_exec` false positives** (79% reduction: 19 → 4 violations): `Function\s*\(` regex matched `isFunction()`, `createFunction()`, etc. Added word boundary `(?:^|[^\w.])Function\s*\(` to only match the bare JS `Function` constructor. Same fix applied to `exec(?:Sync)?\s*\(` which matched `execQuery()`, `execSql()`. These utility type-checks and database helpers are NOT command execution sinks.
- **Smell `long_fn` reports test files** (9% critical reduction: 43 → 39): `_detect_long_functions()` did not skip test/story/fixture files. Added same `_skip_keywords` filter that `_detect_deep_nesting()` already uses (`'.test.', '.spec.', '.fixture.', '.stories.', '.story.', '__tests__'`). Long test blocks are expected and not actionable.
- **A11y engine scans test files** (85% reduction: 122 → 18 issues): No test file exclusion existed in the accessibility scan loop. Added skip filter for test/spec/story/fixture files. Mock JSX in test files (`<img />` without alt, `<button>` without keyboard handler) are not real accessibility issues.
- **Dead code `unused_vars` false positives** (94% reduction: 51 → 3): `_detect_unused_variables()` flagged exported variables as unused because it only checked single-file usage. Added `exported_names` collection (named exports, re-exports, default exports) and skip them. Also expanded `skip_names` with common patterns (`result`, `data`, `value`, `options`, `args`, `params`, `callback`, `next`, `dispatch`, `action`, `payload`).
- **Dead code `registry_dead` test file false positives** (37% reduction: 200 → 127): `_detect_dead_from_registry()` only checked directory paths (`/test`, `/tests`), missing filename patterns like `.test.ts`, `.spec.tsx`. Added `.test.`, `.spec.`, `.e2e.`, `.stories.`, `.story.` patterns and `/__tests__/`.
- **Module system detection wrong for TypeScript projects** (cjs → esm): `framework_detect.py` defaulted to `"cjs"` when `package.json` lacked `"type": "module"`. Many TS projects compile to ESM without this field. Added detection of `tsconfig.json` `compilerOptions.module`, `.mjs`/`.cjs` file extensions, and `exports` field with `"import"` key. Reports `"mixed"` when both ESM and CJS indicators exist.
- **Context engine fuzzy matching too loose**: Used pure substring match sorted by shortest name. Ported scoring logic from `query.py`: exact case-insensitive match priority, active vs dead status priority, ref_count (popularity) ranking. Prevents `"use"` matching `"refuse"` and prefers the most relevant function.
- **Version mismatch**: `CODELENS_VERSION` was `"5.8.1"` while `pyproject.toml` was `"5.9.1"`. Both now synced to `"5.9.2"`.
- **`pyproject.toml` parse error**: `description` and `readme` fields were concatenated on one line. Fixed line break.

## [5.8.1] — 2026-06-12

### Tested against cockroachdb/cockroach (10,112 source files: 9,439 Go + 183 Proto, 555MB Go database)

Real-world test on a pure Go distributed SQL database with 116,033 backend nodes and 113,338 edges.
Confirmed: 2,287 smells (health score 70), 200 dead items, 106 circular deps, 11,291 debug leaks,
1,716 entrypoints, 13 secrets, 4 CVEs, 32 API routes, 15 state stores.

### Added

- **Go project type detection in handbook**: `handbook` now parses `go.mod` to extract module name, Go version, and classify Go projects into types: `go-database`, `go-web-service`, `go-grpc-service`, `go-infrastructure`, `go-project`. Module name extraction (e.g., `github.com/cockroachdb/cockroach` → name: `cockroach`, version from `go` directive).
- **Go framework content-based detection**: `detect_frameworks()` now reads `go.mod` content instead of just checking file existence. Detects `gin`, `echo`, `fiber`, `chi`, `mux`, `grpc`, `protobuf` only when the dependency string actually appears in go.mod. Prevents false positives where every Go project was classified as gin/echo.
- **Go-specific code indicators for debug-leak**: Added `code_indicators_go` with Go-specific patterns (`func`, `var`, `const`, `type`, `:=`, `chan`, `select`, `defer`, `range`). Previously defaulted to JS indicators which caused massive over-detection.
- **License block detection in debug-leak**: `_score_commented_code_likelihood()` now returns 0 for comment blocks that start with copyright/license keywords (copyright, SPDX, Apache License, BSD, MIT, GPL, etc.). Eliminates thousands of false positives from license headers.

### Fixed

- **`get_workspace_outline()` TypeError**: `write_output_files()` in `utils.py` called `get_workspace_outline(workspace, max_files=max_files)` but the function doesn't accept `max_files`. Removed invalid keyword argument.
- **`perf-hint` TypeError crash**: `perf_hint.py` called `detect_perf_hints(workspace, ..., max_files=5000)` but the function doesn't accept `max_files`. Removed invalid keyword argument.
- **gin/echo false positive for Go projects**: Every Go project with a `go.mod` was incorrectly classified as using gin and echo frameworks because both had `"config_files": ["go.mod"]`. Changed to `config_files: []` and use content-based detection instead.
- **Go listed as "unsupported language"**: Go has a fallback parser (`fallback_go.py`) and is actively parsed during scan, but was still listed in `unsupported_langs` with the message "not yet supported by tree-sitter parsers". Removed Go from the unsupported markers list.
- **Handbook `type: unknown` and `version: 0.0.0` for Go projects**: Go projects without package.json or Cargo.toml had no identity detection. Added `go.mod` parsing to extract name, version, and type classification.
- **Debug-leak Go commented_code false positives**: Go projects use multi-line `//` comments heavily for godoc, generating 22,433 false "commented code" findings on cockroachdb. Fixed by: (1) requiring 5+ consecutive lines for Go (vs 3 for other languages), (2) requiring score ≥ 3 for Go (vs 2), (3) adding Go-specific code indicators, (4) skipping license/copyright blocks. Result: 22,433 → 6,734 (70% reduction).

### Changed

- **Go project classification priority**: Module name patterns (cockroachdb, postgres, mysql, etc.) now take priority over dependency-based classification for more accurate type detection.
- **Version bump**: 5.8.0 → 5.8.1

## [5.8.0] — 2026-06-12

### Tested against denoland/deno (5,448 source files: 970 Rust + 4,567 TS/JS, 143MB polyglot monorepo)

Real-world test on a Rust+TypeScript runtime with 36,186 backend nodes and 269,678 edges.
Confirmed: 19,994 smells (health score 50), 676 dead items, 775 circular deps,
1,959 functions analyzed, 3,709 debug leaks, 1,010 entrypoints, 283 state stores,
302 regex patterns, 164 a11y issues, 313 perf hints, 50 env vars.

### Added

- **Rust framework detection**: `detect_frameworks()` now parses `Cargo.toml` for dependencies and detects `rust`, `tokio`, `actix-web`, `axum`, `warp`, `rocket`, `deno_core` from Cargo dependencies. Also scans workspace members' `Cargo.toml` in `crates/`, `ext/`, `libs/`, `packages/` directories.
- **Rust HTTP route extraction**: `api-map` command now detects routes from Rust web frameworks:
  - actix-web / rocket: `#[get("/path")]`, `#[post("/path")]` attribute macros
  - actix-web: `web::resource("/path")` programmatic routes
  - axum: `.route("/path", get(handler))` method chaining
  - warp: `warp::path("segment")` filter chains
- **Cargo workspace monorepo detection**: `handbook` now detects `[workspace]` sections in `Cargo.toml` and sub-directory crate patterns (`crates/*/Cargo.toml`, `ext/*/Cargo.toml`). Reports `is_monorepo: true` with `monorepo_tools: ["cargo-workspace"]`.
- **`is_generated_file()` utility**: Added to `utils.py` for detecting lock files, declaration files, minified files, and other generated artifacts. Fixes `refactor_safe_engine.py` import crash (was importing non-existent function). Total commands: 42 → 43.
- **`has_rust` field in framework detection**: `detect_frameworks()` now includes `has_rust: true` when `Cargo.toml` is found, and adds Rust-specific backend paths to recommended config.

### Fixed

- **`refactor_safe` command crash**: `refactor_safe_engine.py` imported `is_generated_file` from `utils` but the function did not exist, causing the entire command module to fail loading (42/43 commands loaded). Now all 43 commands load successfully.
- **State-map `__dunder` false positives**: Runtime binding helpers (`__default`, `__createBinding`, `__exportStar`, `importDefault`, `__reexport`, `__buffer`, `__default_export__`, `__telemetry`, `__esModule`, etc.) were classified as state stores. Added 15+ JS/TS runtime helper names to post-filter skip set, plus a general `__dunder` runtime helper detection pattern. Result: 0 `__dunder` false positives (was 8 in deno test).
- **`handbook` crash on `cmd_scan()` call**: Handbook called `cmd_scan(workspace, max_files=max_files)` but `cmd_scan()` doesn't accept `max_files` parameter. Removed the invalid keyword argument.
- **Smell `health_score` not at top level**: `health_score` was only available inside `stats` dict, making it harder to access programmatically. Now also returned as a top-level key in the response dict.
- **Markdown formatter for smell**: Now reads `health_score` from top-level first, then falls back to `stats.health_score` for backward compatibility.
- **Version mismatch**: `skill.json` version was `5.7.1` but description referenced v5.10/v6.1. Updated to `5.8.0` with accurate description.

### Changed

- **Complexity engine file cap**: Increased from 3,000 → 5,000 files. Function cap increased from 5,000 → 8,000. Prevents missing analysis on large repos.
- **Debug-leak engine file cap**: Increased from 3,000 → 5,000 files per run for better coverage on large repos.
- **Rust framework config paths**: When Rust is detected, recommended config now includes `crates/*/src/` and `ext/*/src/` as backend paths.

## [5.7.2] — 2026-06-12

### Fixed
- **state-map markdown crash**: `_md_state_map()` called `.get('name')` on action/slice entries, but entries are strings in Pinia/Vuex/Redux/Zustand stores. Now handles both dict and string formats gracefully.
- **binary-scan ImportError**: `scan_binary_artifacts` function was missing from `utils.py`. Now fully implemented with extension-based detection and binary signature scanning (ELF, PE, Mach-O, WASM, etc.).
- **Pinia/Vuex/Redux false positive actions**: JS/TS keywords (`if`, `for`, `while`, etc.) and built-in methods (`push`, `includes`, `toUpperCase`, etc.) were being extracted as store actions. Added `_is_js_keyword_or_builtin()` filter with 80+ entries. Also improved section extraction using `_extract_section()` with proper brace-matching instead of fragile regex.

### Added
- **binary-scan command fully functional**: New `_md_binary_scan` markdown formatter. Scans for compiled binaries, archives, images, and Python bytecode with size reporting and recommendations.
- **Tauri IPC route mapping in api-map**: Frontend `invoke('command')` calls and backend `#[tauri::command]` Rust handlers are now extracted as IPC routes. Shows full invoke:// endpoint paths.
- **Unsupported language detection**: Framework detection now identifies Go, Java, Kotlin, C/C++, C#, Swift, and Ruby projects. Scan output shows a `lang_note` warning when unsupported languages are detected.
- **Go framework signatures**: Added `golang`, `gin`, `echo` to framework detection signatures.
- **`_extract_section()` helper**: New brace-matching helper for state management extractors that properly handles nested braces and string literals, replacing fragile regex patterns.

## [6.0.0] — 2026-06-12

### Added
- **Monorepo-aware framework detection**: Detects turborepo, pnpm-workspace, lerna, nx. Walks sub-directory package.json (apps/*, packages/*) to find frameworks in workspace packages. Detects Rust/Cargo workspaces. Build tool detection (Vite, webpack, esbuild).
- **Polyglot project identity**: Handbook detects combined types (e.g., `rust-js-monorepo`) when both package.json and Cargo.toml exist.
- **Dead code from registry cross-reference**: Uses backend registry's `ref_count` data to find functions with zero references.
- **Monorepo-aware config defaults**: `init` now adds `apps/*/`, `packages/*/`, `crates/*/` paths when monorepo detected.
- **`should_ignore_dir()` utility**: New shared utility in `utils.py` for path-segment-aware directory ignore checking. Replaces inline implementations across multiple engines.
- **`safe_read_file()` utility**: New shared utility for safe file reading with size limits and encoding handling. Prevents out-of-memory on large files.
- **`time_budget_expired()` utility**: New shared utility for checking global timeout budgets in engines. Prevents runaway scans on massive codebases.
- **Performance safeguards in `utils.py`**: `MAX_FILE_SIZE` (200KB), `MAX_FILES_DEFAULT` (5000), `GLOBAL_TIMEOUT_SEC` (120s) constants for all engines.
- **`handbook --quick` mode**: New flag to skip expensive engines (secrets, vuln-scan, circular, dead-code) for faster results on large codebases.
- **Engine status tracking in handbook**: Handbook now reports `engines_ok` and `engines_failed` lists in `meta`. Overall status is `ok`, `degraded`, or `error` based on engine results.
- **Lazy imports in `ask` command**: All 17 engine imports moved from module-level to inside `_execute_ask_command()`. Reduces CLI startup time significantly.
- **Thread-safe grammar loader**: `GrammarLoader` singleton now uses `threading.Lock()` for thread safety in watch command.
- **Modern tree-sitter API support**: `GrammarLoader.get_parser()` now handles both legacy (`Parser(lang)`) and modern (`parser.language = lang`) tree-sitter APIs.
- **Graceful command import**: `commands/__init__.py` now wraps each command module import in try/except, so one failing module doesn't prevent others from registering.
- **`truncated` field in env-check output**: Indicates when file count or timeout limits were hit, so users know results are partial.

### Fixed
- **God object detection**: Class method counting now scoped to actual class/impl body via brace-depth tracking. Was counting ALL function calls in the file as methods (10-30x inflation).
- **API route false positives**: Routes must start with `/` for non-router objects. Expanded skip list (80+ objects). Prevents `headers.get('user-agent')` from being reported as `GET /user-agent`.
- **CSS specificity false positives**: Tracks brace depth to distinguish CSS rule selectors from property values. Was flagging `rgba()`, `var()`, gradient values as selectors.
- **State map over-classification**: Skips ALL_CAPS constants, React components (arrow functions, forwardRef, memo, styled), and immutable values. Removed module.exports scanning.
- **Entrypoints markdown formatting**: Bracket types like `[main]` no longer get mangled by markdown link reference interpretation.
- **Dead code zero results**: Fixed registry cross-reference to use correct field names (`fn` instead of `name`). Added filtering for main(), pub functions, and test fixtures.
- **Handbook type detection**: No longer defaults to `node-project` for Rust+TS monorepos. Cargo.toml is always checked regardless of existing type.
- **`should_ignore_dir` ImportError in tailwind_detector.py**: Was importing a function that didn't exist in `utils.py`. Now uses shared implementation from `utils.py`.
- **`safe_read_file` ImportError in a11y_engine.py**: Removed unused import of non-existent function. a11y_engine now uses the shared `safe_read_file` from `utils.py`.
- **Silent exception swallowing in `context.py`**: `except Exception: pass` replaced with proper `logger.debug()` call.
- **Silent exception swallowing in `handbook.py`**: `except Exception: pass` for sub-directory package.json replaced with `logger.debug()`.
- **Handbook always reports `status: ok`**: Now reports `ok`, `degraded`, or `error` based on engine success/failure counts.
- **env-check returns empty output on large repos**: Added `MAX_FILE_SIZE`, `MAX_FILES` (5000), and `GLOBAL_TIMEOUT_SEC` (90s) limits. Now uses `safe_read_file()` instead of raw `open()`.
- **Version inconsistency**: SKILL.md said "v6" but code said "5.7.1". All version references now unified to "6.0.0".
- **CLI version hardcoded**: `codelens.py` description now uses `CODELENS_VERSION` constant instead of hardcoded "v5".

## [5.6.0] — 2026-06-11

### Added

- **TSX backend extraction**: When tree-sitter-typescript is not installed, TSX files are now parsed with BOTH frontend AND backend fallback parsers. Backend nodes jumped from 124 → 764 (6.2x) on typical Next.js projects.
- **Shared utils module** (`scripts/utils.py`): Centralized `write_output_files`, `compute_summary`, `is_file_path`, `deduplicate_callers`, `DEFAULT_IGNORE_DIRS`, `DEFAULT_IGNORE_EXTENSIONS`, `CODELENS_VERSION`, and `logger`. Eliminates 290+ lines of duplicated code across 5 files.
- **Proper logging**: Replaced silent `except Exception: pass` blocks with `logger.warning()`/`logger.debug()` calls across all engine and utility files. Errors are now visible when they occur instead of being silently swallowed.
- **Fuzzy file path lookup**: `context layout.tsx` and `query layout.tsx` now match partial paths (end-of-path matching). Previously required exact path like `apps/web/app/[locale]/layout.tsx`. Returns grouped results when multiple files match.
- **Auto-incremental scan with registry counts**: When no changes detected, the response now includes actual backend/frontend counts instead of zeros.
- **Handbook registry freshness check**: Handbook skips re-scan if `backend.json` is less than 5 minutes old. Reduces handbook execution time from 2.8s → 0.3s for consecutive runs.

### Changed

- **is_frontend_file / is_backend_file**: Now uses path segment matching instead of substring matching. `"src/"` no longer falsely matches `src/server/api/auth.ts` as a frontend file.
- **_detect_workspace depth limit**: Walks up at most 10 directory levels (was unlimited). Prevents matching a `.git` directory many levels up.
- **Incremental scan with deleted files**: Instead of falling back to full rescan, deleted files are selectively removed from the registry. Preserves incremental scan performance.
- **god_objects Python scoping**: Method count is now scoped to each class using indentation analysis (was counting ALL `def` in the file).
- **Consistent status field**: `context` and `query` file-path responses now include `status: "ok"` (was missing).
- **Context multi-file response**: New `type: "files"` response format when multiple files match a partial path query, with markdown formatting support.
- **Handbook version**: Now uses `CODELENS_VERSION` constant from `utils.py` (was hardcoded as `"5.2.0"`).
- **Centralized `DEFAULT_IGNORE_DIRS`**: All 30 engine/command files now import `DEFAULT_IGNORE_DIRS` from `utils.py` instead of defining local copies. Single source of truth ensures consistency across all scanners.
- **pyproject.toml version**: Aligned with skill.json and CODELENS_VERSION (was 5.1.0, now 5.6.0). Description updated from "39 commands" to "41 commands".

### Fixed

- **TSX files produced zero backend nodes**: When TSXParser failed to import, only CSS class/ID data was extracted. Now uses `parse_js_backend_fallback` on TSX files too.
- **Auto-incremental returned zero counts**: "No changes detected" response had `backend.nodes: 0, backend.edges: 0` even when registry had thousands of entries.
- **Handbook version stale**: Was hardcoded as 5.2.0 in output, now dynamically reads from `CODELENS_VERSION`.
- **Test import errors**: 6 test files (test_cli, test_css_parser, test_html_parser, test_js_backend_parser, test_js_frontend_parser, test_rust_parser) were importing from old monolithic `codelens.py`. Updated to import from the new modular structure (`commands.scan`, `parsers.fallback_*`).
- **Scan edge filter for deleted files**: Edge cleanup was overly permissive — kept ALL unresolved edges regardless of whether they referenced deleted nodes. Now only keeps edges where `from` is in remaining nodes.
- **setup.sh version reference**: Updated from "v2" to "v5" to match current version.
- **CLI test suite**: `__tests__/cli/test_scan.py` now uses hermetic temporary workspaces instead of scanning the host project, and added 3 new test cases (init, scan+query integration, registry creation).

## [5.5.0] — 2026-06-11

### Added

- **Auto-incremental scan**: Scan now automatically uses incremental mode when a registry already exists (`.codelens/backend.json` present). No need to pass `--incremental` flag. First scan is always full; subsequent scans auto-detect changes.
- **oRPC route detection**: API-map now detects oRPC-style routers (`.procedure()`, `router({})`, `protectedProcedure`/`adminProcedure` chains). Detects 67 routes in typical oRPC projects (was 2).
- **tRPC v10+ detection**: Improved tRPC extraction with `t.procedure`, `publicProcedure.query/mutation`, `initTRPC`, and router body parsing for named procedure paths.
- **Context by file path**: `context src/lib/auth.ts` now returns all symbols defined in that file, not just symbol-name lookups.
- **Query by file path**: `query src/lib/auth.ts` returns all symbols in the file, grouped by file.
- **bun.lock support**: Vulnerability scanner now parses Bun's text-based `bun.lock` format for dependency checking.
- **Next.js destructured route exports**: API-map now detects `export const { GET, POST } = handler()` and `export const GET = ...` patterns in Next.js App Router.

### Changed

- **Health score calibration**: Deep nesting now reports per-block instead of per-line (was 6419 findings → 300). Magic values skip config/test/fixture files and JSX style props. Weighted density formula (`critical*3 + warning + info*0.1`) prevents info-level smells from tanking scores. Typical React project health: 90 (was 25).
- **Deep nesting thresholds**: Raised from 4→5 (warning) and 6→8 (critical) to account for natural React component nesting.
- **Duplicate caller filtering**: `query` and `context` commands now deduplicate callers by (file, line) tuple.

### Fixed

- **Secrets markdown truncation**: Severity "high" was truncated to "igh]" in markdown output due to f-string variable name collision. Now displays correctly as `[HIGH]`, `[CRITICAL]`, etc.

## [5.4.0] — 2026-06-11

### Added

- **True incremental scan**: Partial registry merge — changed files' entries are updated in-place instead of rebuilding the entire registry. Unchanged files' data is preserved, making `--incremental` significantly faster for large codebases.
- **Complete markdown formatters**: All 41 commands now have specific markdown formatters (was 15/41). No command falls through to generic formatting anymore.
- **Score-based ask routing**: Natural language query router now uses weighted scoring instead of first-match. Technical terms score 3x, action words 1x, generic words 0x. Correctly routes "show me the API routes" to api-map instead of context.
- **8 new ask patterns**: CSS issues→css-deep, accessibility→a11y, regex→regex-audit, what changed→diff, tech stack→detect, how to configure→env-check, which files import→dependents, is this code safe→refactor-safe.
- **3 new semantic convention detectors**: CSS framework (Tailwind/Bootstrap/MUI/Chakra/Ant/Bulma), Authentication (NextAuth/Passport/JWT/OAuth/Firebase/Supabase/Clerk), Deployment (Vercel/Netlify/Docker/Fly.io/Railway/Render/Heroku/AWS/GCP).
- **Better error messages**: Command-specific error suggestions with `_suggest_fix()`. Split error handling into FileNotFoundError, ImportError, and generic Exception with helpful suggestions.
- **Consistent status field**: All commands now return `status: "ok"` (or `status: "error"` on failure). Previously some commands like `list`, `query`, `detect`, and `diff` were missing this field.

### Changed

- `codelens.py` monolith reduced from 3504 → 307 lines (modular architecture)
- Ask command accuracy: 12/12 test cases pass (was ~8/12 with first-match routing)
- Health score: percentile-based formula (clean=95, average=85, messy=55, CodeLens=5)
- Convention engine: 8 semantic detectors total (was 5)

## [5.1.0] — 2026-05-03

### Added

- **Workspace Auto-Detect**: The `workspace` argument is now optional for ALL commands. Fallback chain: current directory → parent directories → source files → last workspace cache → cwd
- **Python Parser**: Full tree-sitter Python parsing for function declarations, class methods, and function calls
- **`.codelens` directory exclusion**: Scanner now skips `.codelens/` directory during file discovery
- **SCSS/Less/Sass support**: Preprocessor CSS files are now discovered and parsed
- **Vue SFC parser**: Single-file component parser for Vue.js
- **Svelte parser**: Component parser for Svelte
- **Tailwind CSS detector**: Analyzes Tailwind utility class usage
- **TSX/JSX parser**: React component parser with className tracking
- **Open-source standards**: README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, .gitignore, pyproject.toml
- **Comprehensive test suite**: Unit tests for all parsers and core engines

### Changed

- `codelens.py` now supports optional `workspace` argument with auto-detection
- Scan command supports `--incremental` flag for faster re-scans
- Watch mode now uses incremental scanning for file changes
- CLI version bumped from v4 to v5
- Total commands: 36 → 39
- Total engines: 23
- Total parsers: 9

## [5.0.0] — 2026-05-01

### Added

- **`vuln-scan`** — Dependency vulnerability scanning (npm audit, cargo audit, pip-audit, govulncheck + built-in CVE database with 35+ entries)
- **`perf-hint`** — Performance anti-pattern detection (N+1 queries, sync blocking, memory leaks, expensive renders, large bundles, inefficient iteration, unoptimized images, cache misses)
- **`css-deep`** — Deep CSS analysis (unused CSS variables, orphan @keyframes, specificity wars, duplicate properties, unused @media, z-index abuse)
- **Priority system**: Tools now have explicit priority weights (P0 > P1 > P2 > P3)
- **State prerequisites**: Explicit init→scan→tools ordering documented
- **Context-aware hints**: Auto-init if registry missing, re-scan if stale (>24h)
- **Colloquial triggers**: Non-technical phrases mapped to tools
- **Negative triggers**: When NOT to activate CodeLens
- **Default fallback chains**: Vague requests get default tool chains
- **SKILL-QUICK.md**: Concise quick-reference for fast AI consumption

### Changed

- CLI version: v4 → v5
- Total commands: 36 → 39
- Total engines: 23
- Total parsers: 9

## [4.0.1] — 2026-05-01

### Added

- Expanded `skill.json` description with explicit trigger phrases
- Added 6-category trigger rules to SKILL.md frontmatter
- Added Auto-Trigger Map section with 7 sub-tables
- Added 5 new scenario flows (Pre-Deploy, Onboarding, Feature Development, Performance, Code Review)
- Updated `agent-integration.md` with Section 0: Auto-Activation & Trigger Guide

## [4.0.0] — 2026-05-01

### Added

- **`secrets`** (P0) — Hardcoded secret detection
- **`entrypoints`** (P0) — Execution entry point mapping
- **`api-map`** (P1) — REST/GraphQL/gRPC route→handler mapping
- **`state-map`** (P1) — Global state management tracking
- **`env-check`** (P1) — Environment variable auditing
- **`debug-leak`** (P2) — Debug code leak detection
- **`complexity`** (P2) — Cyclomatic/cognitive complexity scoring
- **`regex-audit`** (P3) — ReDoS-vulnerable regex auditing
- **`a11y`** (P3) — Accessibility auditing (WCAG 2.1)

### Fixed

- Python file discovery now works (was missing .py handling)
- Top-level error handling added (clean JSON errors instead of tracebacks)
- Side-effect argparse bug fixed (name as optional --name flag)
- Outline positional arg consistency fixed

## [3.0.0] — 2026-04-30

### Added

- **`dataflow`** (P0) — Data flow analysis (source→sink, taint detection)
- **`smell`** (P0) — Code smell detection (10 categories, health score)
- **`side-effect`** (P1) — Function side-effect analysis (pure vs impure)
- **`refactor-safe`** (P1) — Pre-flight rename/move safety check
- **`dead-code`** (P1) — Enhanced dead code detection
- **`stack-trace`** (P2) — Error propagation simulation
- **`test-map`** (P2) — Test coverage mapping
- **`config-drift`** (P2) — Dependency drift detection
- **`type-infer`** (P3) — Lightweight type inference
- **`ownership`** (P3) — Git blame code ownership analysis

## [2.0.0] — 2026-04-30

### Added

- `search` — Code search across workspace
- `symbols` — Registry-based symbol search
- `trace` — Deep call chain tracing
- `impact` — Change impact analysis
- `outline` — File structure outline
- `missing-refs` — CSS/HTML mismatch detection
- `diff` — Registry snapshot comparison
- `circular` — Circular dependency detection
- `context` — Rich symbol context
- `dependents` — Module-level import tracking
- `validate` — Registry sanity check
- Tree-sitter powered AST parsing
- 9 tree-sitter parsers
- Framework auto-detection
- Incremental scanning

## [1.0.0] — 2026-04-30

### Added

- `init`, `scan`, `query`, `list`, `detect`, `watch` commands
- Frontend registry (classes + ids)
- Backend registry (nodes + edges)
- Status tracking (active, dead, collision, duplicate_ref, duplicate_define)
- HTML, CSS, JS, Rust basic regex parsers

---

## Historical Changelog (from SKILL.md)

These changelog entries were previously embedded in SKILL.md and have been moved here
to reduce SKILL.md size for AI consumption. The reference documentation remains in SKILL.md.

# CodeLens v6

Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

## What's New in v6.5 — Tested on calcom/cal.com (5,050 TS/TSX files, Turborepo monorepo, 22 packages)

- **Bugfix: Vue false positive from Vite config**: `vite.config.js` was listed as a Vue config file, causing ALL Vite-based projects (React, Svelte, etc.) to be falsely detected as using Vue. Now `vite.config.js` is correctly associated with the new `vite` framework entry. Frameworks now report `has_vite: true` separately from `has_vue: true`. The `vue_mode` config is only set when actual `.vue` files or `vue` package dependency exists. Eliminates the contradiction where `has_vue: false` but "vue" appeared in frameworks list.
- **Bugfix: Secrets false positives in enum definitions**: TypeScript/JavaScript enum values like `IncorrectEmailPassword = "incorrect-email-password"` and `UserMissingPassword = "missing-password"` were flagged as critical `password` secrets. Added `_is_enum_or_constant_definition()` context-aware filter that detects PascalCase/ALL_CAPS identifiers assigned kebab-case string values (enum pattern) and skips them. Critical findings dropped from 8 to 1 on cal.com.
- **Bugfix: Secrets false positives in .env.example**: `.env.example`, `.env.sample`, `.env.template`, and `.env.demo` files were scanned for secrets in Phase 2 (.env file scanner) and reported `DATABASE_URL` and other template values as critical `connection_string` findings. Now skipped entirely — these files contain placeholder/example values, not real secrets.
- **Bugfix: API map keyword false positives**: GraphQL resolver extraction pattern `(\w+)\s*[:=]\s*\(` matched JS/TS reserved words like `if`, `else`, `for` as GraphQL field names, producing routes like `QUERY Query.if`. Added reserved word filtering (36 keywords) to `_extract_graphql_schema()`, `_extract_graphql_code()`, and `_find_next_js_function()`. Keyword false positives eliminated entirely.
- **Bugfix: Dead code false positives for Next.js lifecycle functions**: `generateMetadata`, `getServerSideProps`, `getStaticProps`, `getStaticPaths`, `getInitialProps`, `generateStaticParams`, `generateViewport` were flagged as dead code because they have `ref_count == 0` — they're called by the Next.js framework at runtime, not by user code. Added Next.js lifecycle function skip list to `_detect_dead_from_registry()`, only applied for `.ts`/`.tsx`/`.js`/`.jsx` files.
- **Bugfix: Dataflow timeout crash**: `dataflow` command had hardcoded `max_files=5000` and `timeout_sec=120` with no CLI override. On repos with 5000+ files, it would timeout and produce no output (JSONDecodeError). Added `--max-files` (default 3000) and `--timeout` (default 120) CLI arguments to the dataflow command. Now produces valid output even on large repos.
- **Vite as first-class framework**: Added `vite` framework entry with config files `vite.config.js`, `vite.config.ts`, `vite.config.mts`. Projects using Vite are now correctly identified without being misattributed to Vue. `has_vite: true` flag added to `detect_frameworks()` output.
- **Version**: 6.3.1 → 6.5.0.

## What's New in v6.4 — Tested on excalidraw/excalidraw (632 files, React+TS yarn-workspace monorepo)

- **Bugfix: `is_bundled_file` missing from utils.py**: 4 commands (`ask`, `complexity`, `context`, `perf-hint`) were silently broken due to missing `is_bundled_file` function in `utils.py`. Now added with proper path-based and extension-based detection for minified, bundled, and dist/build output files.
- **Bugfix: `analyze` env_issues engine ImportError**: `_detect_env()` called non-existent `audit_environment` from `envcheck_engine`. Fixed to use correct `check_env_vars()` function. The env_issues engine now runs successfully in `analyze`.
- **Bugfix: Risk score saturation to 0**: `_compute_risk_score()` used linear deduction that immediately saturated to 0/100 on projects with multiple finding categories. Now uses logarithmic scaling (`log2(1+n)`) with per-category caps and exponential decay for negative scores, producing meaningful risk scores (e.g., 30/100 instead of 0/100 for a project with 367 critical issues).
- **Bugfix: `dependents` workspace auto-swap**: When passing a workspace directory as the first argument to `dependents`, the auto-swap correctly updated `args.workspace` but not the `workspace` parameter passed to engine functions. Fixed by updating both.
- **Bugfix: `ask` router specificity**: "show me the architecture" was misrouted to `context` (score 4.0) instead of `handbook` (score 3.27) because the coverage bonus favored short keyword patterns. Added a 1.5x specificity bonus for patterns matching weight-3 technical terms.
- **Auto-detect detail level**: `summary --detail auto` (now the default) automatically adapts detail level based on codebase size: <100 files → "full", 100-1000 → "standard", >1000 → "minimal". Prevents information overload on large repos.
- **Smart truncation**: `summary --max-tokens 8000` estimates output token count and progressively truncates `top_items` lists to stay within budget. Prevents AI agent context overflow.
- **AGENT.md generation**: `summary --write-agent-md` writes a condensed markdown file to `.codelens/AGENT.md` optimized for AI agent system prompts. Includes identity, frameworks, priority findings, and actionable recommendations.
- **Version**: 6.3.0 → 6.4.0.

## What's New in v6.3 — Tested on n8n-io/n8n (20K+ files, Vue+TS pnpm/turborepo monorepo)

- **Large repo timeout fixes**: `missing_refs` O(n²) typo detection now time-budgeted (15s cap, 2-char prefix filtering, 500K comparison cap, pre-built lookup dict). `analyze` command gets `--timeout` (default 300s) with per-engine time budget and graceful degradation (skips engines when <20% budget remains). `handbook` command gets `--timeout` (default 120s) with per-engine skip and `partial: true` output flag.
- **api-map tauri false positive fix**: Removed overly broad `invoke\s*\(` pattern from tauri import detection. Many non-Tauri projects (AWS Lambda, gRPC, n8n workflow nodes) use `invoke()` calls that were falsely detected as Tauri IPC. Now only matches explicit `@tauri-apps/api` imports.
- **state-map react_context false positive fix**: `react_context` detection now requires actual React dependency (`has_react` check via framework_detect or package.json). Vue/Pinia projects no longer produce `react_context` false positives. File-level import check also added: `createContext` must come from a React import.
- **entrypoints `--exclude-tests` flag**: New `--exclude-tests` flag on the `entrypoints` command filters out `test_entry` type from scanning. Reduces n8n entrypoints from 71K (98% test entries) to 1.6K production entries. `test_entry` output also capped at 100 items max. Analyze command passes `exclude_tests=True` by default.
- **smell god_object JS/TS brace-depth tracking**: Replaced naive regex that counted ALL function-like patterns in the entire file (10-30x inflation) with proper brace-depth tracking like Rust impl blocks. Now only counts methods inside actual `class { }` body blocks. Example: `N8NStartupError` went from 87 false methods to 3 actual methods.
- **missing_refs output improvements**: Per-category truncation (max 200 items), `truncated_counts` for actual totals, `findings` flat list for consistency with other engines, `typo_truncated` flag when time budget expires.
- **analyze graceful degradation**: Skipped engines report `skipped: true` with `skip_reason` and `action` (suggests running individually). `skipped_engines` summary in output. Per-engine `elapsed_seconds` timing.
- **Version**: 5.9.2 → 6.3.0.

## What's New in v6.3.1 — Tested on Readest (1200+ TSX, 40 Rust, Tauri V2 + Next.js)

- **Performance: `--max-files` on remaining heavy engines**: Commands that still timed out on repos with 1000+ files now accept `--max-files` (default: 3000). Added to: `a11y`, `side-effect`, `test-map`. Already present in: `dead-code`, `complexity`, `smell`, `debug-leak`.
- **Performance: `--max-results` on dead-code**: New `--max-results` flag (default: 100) to cap results per category. Prevents massive JSON output on repos with thousands of dead code items.
- **Workspace auto-detect improvement**: `resolve_workspace()` now prioritizes last-used workspace over cwd/project-marker auto-detection. This fixes the common issue where subcommands like `symbols`, `search`, `trace`, `impact`, `context`, `dependents` would resolve to the wrong workspace when the workspace argument is omitted (e.g., resolving to `/home/z/my-project` instead of the actual project).
- **a11y truncated flag**: `a11y` engine now reports `truncated: true` when file-count limit is reached, making it clear that results are partial.

## What's New in v6.0 — The "Analyze Everything" Release

- **`analyze` command (P0)**: One-shot full repository analysis. Automatically runs init + scan + all engines (secrets, smells, complexity, debug-leak, dead-code, circular, perf-hints, config-drift, binary-artifacts, dataflow, env-check, vuln-scan). Produces comprehensive report with project identity, frameworks, languages, architecture overview, API routes, entry points, risk assessment (0-100 score), prioritized action plan, and contextual recommendations.
- **PHP support in all engines**: `.php` added to SOURCE_EXTENSIONS in `debugleak_engine.py`, `smell_engine.py`, `complexity_engine.py`, and `perfhint_engine.py`. PHP files now scanned for code smells, complexity, debug leaks, and performance hints.
- **PHP debug leak detection**: `var_dump()`, `print_r()`, `phpinfo()`, `dd()`, `dump()`, `ray()`, `dpm()`, `kint()`, `xdebug_var_dump()`, `exit;`, `die()`.
- **PHP complexity detection**: New `_extract_php_functions()` — detects `public/private/protected function` and standalone `function` declarations.
- **PHP smell detection**: Long functions, deep nesting, many parameters for PHP methods.
- **PHP performance hints**: 8 PHP-specific patterns — Doctrine N+1, Eloquent N+1, sleep(), blocking file_get_contents(), exec()/shell_exec(), memory leaks in long-running processes, Redis KEYS command, missing TTL.
- **Multi-language SOURCE_EXTENSIONS**: Added `.java`, `.cs`, `.dart`, `.lua` to all applicable engines.
- **Risk assessment**: 0-100 risk score with emoji indicators (🔴🟠🟡🟢) based on finding severity.
- **Prioritized action plan**: Auto-generates P0-P3 action items with concrete next steps.
- **Contextual recommendations**: Language/framework-specific recommendations (PHP: phpstan, Go: go vet, Python: mypy+ruff).
- **Total commands**: 44 → 45.

## What's New in v5.8.1 — Tested on cockroachdb/cockroach (10K files, Go database)

- **Go project type detection**: `handbook` parses `go.mod` for module name, Go version, and classifies projects as `go-database`, `go-web-service`, `go-grpc-service`, `go-infrastructure`, or `go-project`.
- **Go framework content-based detection**: `detect_frameworks()` reads go.mod content (not just file existence). Detects gin/echo/fiber/chi/mux/grpc/protobuf only when dependency actually appears. No more false positives on non-web Go projects.
- **Go removed from unsupported_langs**: Go has fallback parser support and is actively scanned, so it's no longer listed as "unsupported".
- **Go debug-leak commented_code false positive reduction**: 22,433 → 6,734 findings (70% reduction) via Go-specific code indicators, higher block length threshold (5 vs 3), higher score threshold (3 vs 2), and license block skip.
- **Bugfix: `get_workspace_outline()` TypeError**: Removed invalid `max_files` kwarg.
- **Bugfix: `perf-hint` TypeError crash**: Removed invalid `max_files` kwarg from `detect_perf_hints()` call.
- **Bugfix: Handbook `type: unknown` and `version: 0.0.0`** for Go projects: Now extracts identity from go.mod.

## What's New in v5.8.0 — Tested on denoland/deno (5,448 files, Rust+TS polyglot monorepo)

- **Rust framework detection**: `detect_frameworks()` now parses `Cargo.toml` for dependencies and detects `rust`, `tokio`, `actix-web`, `axum`, `warp`, `rocket`, `deno_core`. Also scans workspace members' `Cargo.toml` in `crates/`, `ext/`, `libs/`, `packages/`.
- **Rust HTTP route extraction**: `api-map` now detects routes from Rust web frameworks: actix-web (`#[get]`/`#[post]` attributes, `web::resource()`), axum (`.route("/path", get(handler))`), warp (`warp::path("segment")`), rocket (`#[get]`/`#[post]` attributes).
- **Cargo workspace monorepo detection**: `handbook` detects `[workspace]` in `Cargo.toml` and sub-crate patterns. Reports `is_monorepo: true` with `monorepo_tools: ["cargo-workspace"]`.
- **`is_generated_file()` utility**: Detects lock files, declaration files, minified files. Fixes `refactor_safe` command crash. Total commands: 42 → 43.
- **State-map `__dunder` runtime helper filtering**: JS/TS runtime binding helpers (`__default`, `__createBinding`, `__exportStar`, `__importDefault`, `__reexport`, `__buffer`, `__esModule`, etc.) no longer classified as state stores. General `__` prefix pattern also filtered.
- **`handbook` crash fix**: Removed invalid `max_files` keyword argument from `cmd_scan()` call.
- **Smell `health_score` at top level**: `health_score` now also returned as top-level key for easier programmatic access.
- **File scan cap increases**: Complexity engine 3,000→5,000 files. Debug-leak 3,000→5,000 files.
- **Version alignment**: skill.json version `5.7.1` → `5.8.0`. Description now accurately reflects current capabilities.

## What's New in v5.8.0 (elizaOS/eliza test) — Previous Release

- **State map false positive reduction**: Expanded skip lists for Node.js globals (__dirname, __filename, process, Buffer, etc.), CLI argument constants, path aliases (ROOT, HOME, CWD), environment variable references, and import-like assignments. ALL_CAPS single-word constants (VERBOSE, CLI, CHECK, PRUNE) now correctly skipped. Python global filtering also improved with builtin/dunder/path skips. State stores dropped from ~1493 false positives to significantly fewer real ones.
- **Entrypoints markdown fix (v2)**: Angle brackets like `<module_export>` and `<main>` were treated as HTML tags by markdown renderers, silently consumed. Now uses backticks for reliable rendering: `module_export`, `main`.
- **Performance: --max-files limit**: Scan and handbook commands now accept `--max-files` (default: 5000) to prevent timeout on very large repos. Proportionally truncates file categories with a warning. Use `--max-files 0` to scan all files.
- **Debug leak output improvement**: Each leak item now includes `pattern` (the detected pattern name), `message` (human-readable description), and `content` (the matched line content). Markdown formatter shows descriptive messages like "Debug console statement: console.log()" instead of raw category names.
- **Python global state filtering**: Skips ALL_CAPS constants, dunder attributes (__name__, __file__, __all__), and path/env references (os.path, Path, os.getenv). Reduces false positives in Python projects.

## What's New in v6 — Real-World Tested on Vercel Turborepo (1769 files, Rust+TS monorepo)

- **Monorepo-aware framework detection**: Detects turborepo, pnpm-workspace, lerna, nx. Walks sub-directory package.json (apps/*, packages/*) to find Next.js, React, etc. in workspace packages, not just root. Detects Rust/Cargo workspaces. Build tool detection (Vite, webpack, esbuild).
- **Accurate god object detection**: Class method counting now scoped to actual class/impl body via brace-depth tracking. Was counting ALL function calls in the file as methods (10-30x inflation). Rust impl blocks also properly scoped.
- **API route false positive elimination**: Routes must start with `/` for non-router objects. Expanded skip list (80+ objects: request, headers, cache, store, etc.). Prevents `headers.get('user-agent')` from being reported as `GET /user-agent`.
- **CSS specificity false positive fix**: Tracks brace depth to distinguish CSS rule selectors from property values. Was flagging `rgba(0, 0, 0, 0.1)`, `var(--x)`, `from -160deg` as selectors. Specificity wars dropped from 31 false positives to 4 real ones.
- **Dead code from registry cross-reference**: Uses backend registry's `ref_count` data to find functions with zero references. Skips main(), pub functions, and test fixtures. Found 200+ genuine dead items that the text-only scanner missed.
- **State map constant/component filtering**: Skips ALL_CAPS constants (MAX_FILES, etc.), React components (arrow functions, forwardRef, memo, styled), and immutable values. State stores dropped from 825 false positives to ~150 real ones. Removed module.exports scanning that classified every exported function as a store.
- **Polyglot project identity**: Handbook detects combined types (e.g., `rust-js-monorepo`) when both package.json and Cargo.toml exist. No longer defaults to `node-project` for Rust+TS monorepos.
- **Entrypoints markdown fix**: Bracket types like `[main]` no longer get mangled by markdown link reference interpretation. Uses backticks instead (v5.8: angle brackets were still broken — `<main>` treated as HTML tag).

## What's New in v5

- **Vulnerability Scanning**: Dependency CVE scanning via native audit tools (npm audit, cargo audit, pip-audit, govulncheck) + built-in vulnerability database with 35+ entries
- **Performance Anti-Pattern Detection**: 8 categories — N+1 queries, sync blocking, memory leaks, expensive re-renders, large bundles, inefficient iterations, unoptimized images, cache misses
- **Deep CSS Analysis**: Unused custom properties (--var), orphan @keyframes, specificity wars (!important overuse), duplicate property declarations, z-index abuse, non-standard @media breakpoints

## What's New in v5.6 — Real-World Tested

- **TSX backend extraction**: 6.2x more backend nodes from TSX files when tree-sitter-typescript is unavailable. Uses `parse_js_backend_fallback` on TSX to extract functions and imports.
- **Shared utils module**: Centralized `write_output_files`, `compute_summary`, `is_file_path`, `deduplicate_callers`, `DEFAULT_IGNORE_DIRS`, `CODELENS_VERSION`, and `logger`. Eliminates 290+ lines of duplicated code.
- **Proper logging**: Replaced 56 `except Exception: pass` blocks with `logger.warning()`/`logger.debug()`. Errors are now visible instead of silently swallowed.
- **Fuzzy file path lookup**: `context layout.tsx` and `query layout.tsx` now match partial paths (end-of-path matching). Returns grouped results for multiple matches.
- **Registry freshness check**: Handbook skips re-scan if registry is less than 5 minutes old (2.8s → 0.3s for consecutive runs).
- **Incremental deleted file handling**: Selectively removes deleted file entries from registry instead of full rescan.
- **Path segment matching**: `is_frontend_file`/`is_backend_file` no longer use substring matching. Prevents `src/` from falsely matching `src/server/api/auth.ts`.
- **Workspace detection depth limit**: Walks up at most 10 directory levels (was unlimited).
- **God objects Python scoping**: Method count now scoped to each class using indentation (was counting ALL `def` in file).

## What's New in v5.2 — Agent Optimization

- **`handbook` command**: One-stop project orientation for AI agents. Aggregates identity, structure, health, conventions, risks, and quick reference into a single output. Writes `.codelens/handbook.json` and `.codelens/AGENT.md`.
- **`ask` command**: Natural language query router. Agents don't need to memorize 41 commands — just ask a question and CodeLens routes to the right tool.
- **`--format markdown`**: Global flag on ALL commands. Output markdown instead of JSON for direct LLM consumption.
- **`scan` generates `outline.json` + `summary.json`**: Previously only `watch` produced these AI-friendly files. Now `scan` does too.
- **Decision trees in output**: `query` returns `action` + `action_reason`, `impact` returns `risk_level` + `recommended_action`, `smell` returns `actionable_items`, `dead-code` returns `removal_safety`.
- **`context` enriched with quality metrics**: Adds `quality` block with complexity, side effects, safety assessment, smells, and test coverage.
- **Convention detection**: New `convention_engine.py` detects naming conventions, file organization, import styles, component patterns, and error handling.
- **`.codelens/AGENT.md`**: Auto-generated markdown project brief that can be included as system prompt context.

---
