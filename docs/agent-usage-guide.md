# CodeLens as an Agent's Primary Code-Intelligence Tool

> **Status:** Living reference, verified against a real 425-file polyglot
> workspace (rs/ts/tsx/js/css/html + Python for CodeLens itself).
> **Last verified:** 2026-07-12
> **Purpose:** Tell an agent what to reach for instead of manual `grep`, and
> what NOT to trust yet.

This is not API documentation (see `--help` per command for that). This is
the accumulated result of exercising every umbrella command end-to-end on a
real Tauri + React + Rust codebase and fixing what broke.

---

## The one rule that will burn you

**`search` takes `pattern` first, `workspace` second** — every other umbrella
command (`audit`, `deps`, `context`, `security`, ...) takes `workspace`
first. Getting this backwards does **not** error — it silently searches for
the workspace path as the pattern and returns an empty `"ok"` result. If a
search comes back suspiciously empty, check argument order before assuming
the symbol doesn't exist.

```
codelens search "pattern" <workspace> --mode symbol   # correct
codelens audit <workspace> --check dead-code            # different order, also correct
```

---

## Replacing grep: which mode for which question

| Question | Use | Notes |
|---|---|---|
| "Where is symbol X defined?" | `search "X" . --mode symbol` | Exact name match across all languages in one call. |
| "What calls/is called by X?" | `context . --check trace --name X --direction up\|down` | Full transitive chain with depth, crosses file *and* language boundaries (verified: TS → Rust in one chain). |
| "Find code related to concept Y" (fuzzy) | `search "Y" . --mode semantic` | TF-IDF over symbol names/paths, not full-text — good for "where's the auth code", not literal string matches. |
| "Find this exact string/regex" | `search "regex" . --mode regex --type ts` | This is the real grep replacement. **Always pass `--type`** (html/css/js/ts/tsx/rust/python/vue/svelte) — without it, the default result cap can silently truncate the walk (see "max-results early exit" below) before reaching your target file if match density is skewed toward certain paths. |
| "Structural/graph question" (e.g. "all functions calling any DB write") | `search "MATCH (f)-[:CALLS]->(g:function) WHERE ..." . --mode graph` | Cypher subset — replaces chaining trace+impact+context by hand. |
| "Is this safe to delete?" | `audit . --check dead-code` **plus** `context . --check trace --name X --direction up` | Don't trust dead-code alone — cross-check with trace. See Known Gaps. |
| "What imports this file?" | `deps . --check dependents --files path/to/file.ts` | |
| "Any circular imports?" | `deps . --check circular` | |
| "Any secrets/vulnerable deps/injection risk?" | `security . --check secrets\|vuln-scan\|taint\|regex-audit` | **Taint is Python/JS/TS/TSX only** — see Known Gaps, no Rust coverage. |
| "10-second repo orientation" | `context . --check orient` (or bare `context .`, it's the default) | Framework detection, dev commands, entry points. |
| "Prioritized health snapshot" | `summary .` | Aggregates dead-code/smell/taint/vuln-scan; use `--lite` for an agent-sized payload. |

---

## `--lite`: use it, but know its coverage

`--lite` is the actual token-budget lever for agent use — full non-lite
output on a real workspace routinely runs 10-50x larger. As of this session
it works correctly for **all 12 umbrella commands** (was previously broken
for every umbrella — see Fixed This Session). Coverage of *dedicated*
reducers (extra compression beyond the generic fallback):

- **Rich, hand-tuned:** `query`, `impact`, `smell`, `complexity`, `dead-code`,
  `debug-leak`, `perf-hint`, `secrets`, `taint`, `a11y`/`css-deep`/
  `regex-audit`/`vuln-scan`, `summary`, `history`.
- **Generic fallback (adequate, not hand-tuned):** everything else —
  `orient`, `outline`, `trace`, `context`, `api-map`, `doctor`, `circular`,
  `affected`, `dependents`. Still bounded (carries scalar fields + first 5
  of the primary list), just not as surgically trimmed.

If a `--lite` result on some command looks emptier than it should, check
whether it hits a dedicated reducer or the generic fallback — the generic
fallback only knows a fixed set of top-level key names
(`found`/`action`/`risk`/`health_score`/`query`/`symbol`/`workspace` +
`stats`/`recommendations` + one primary list). Deeply nested fields it
doesn't recognize get silently dropped, not an error.

---

## Per-language coverage (verified)

| Language | scan/parse | search | trace/context | audit dead-code | security taint | security secrets/vuln-scan |
|---|---|---|---|---|---|---|
| TypeScript/TSX | ✓ (`.ts` counted under the `tsx` scan-stat bucket, cosmetic only) | ✓ | ✓ (verified 28-caller chain) | ✓ | ✓ | ✓ |
| JavaScript | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| React (JSX/TSX components) | ✓ | ✓ | ✓ | ✓ (correctly distinguishes "default export unused" from "named export used" — verified against a real component) | ✓ | ✓ |
| Python | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Rust | ✓ | ✓ | ✓ (trace chains cross into `.rs` from TS/TSX call sites) | ✓ **after this session's fix** — inline `#[cfg(test)] mod tests { #[test] fn ... }` no longer false-positives (was ~56%+ of registry_dead noise before) | **✗ not supported** — engine is Python/JS/TS/TSX only, no Rust source/sink rules | ✓ (regex/gitleaks are language-agnostic) |
| CSS | ✓ (class/id extraction) | ✓ regex mode | n/a (no call graph for CSS) | n/a | n/a | ✓ (regex/gitleaks scan text) |
| HTML | ✓ | ✓ regex mode | n/a | n/a | n/a | ✓ |

**Rust dead-code residual gap (issue #228, not fixed this session):** `impl`
blocks and trait-default methods are still structurally false-flagged as
dead in some cases — this is a different, deeper false-positive source than
the test-function one fixed above (parser doesn't yet understand a trait impl
satisfies a contract rather than being "called"). Cross-check any Rust
`impl`-typed dead-code finding with `trace --direction up` before trusting it.

---

## Fixed this session (verified, not just claimed)

All fixes verified by direct CLI reproduction + `pytest` (added regression
tests where the bug wasn't already covered) before/after comparison. No
worker involved per explicit user directive — root cause identified by
reading the actual failure, not pattern-matched from symptoms.

1. **`search --help` example order was backwards** (`scripts/commands/search.py`)
   — the epilog/docstring examples showed `workspace` before `pattern`,
   opposite of the actual argparse signature. Following the documented
   example silently returns an empty result. Fixed the docstring/epilog;
   the actual argument order was already correct.

2. **`graph` mode `truncated` flag was meaningless** (`query_graph_engine.py`)
   — set to `True` whenever the query merely *contained* a `LIMIT` clause,
   regardless of whether any rows were actually cut off. A `LIMIT 50` query
   matching 1 row reported `truncated: true`, misleading callers into
   thinking more results existed. Now computed from actual row count vs.
   limit. Added `tests/test_query_graph.py::test_truncated_flag_false_when_limit_exceeds_match_count`.

3. **`--lite` was completely broken for all 12 umbrella commands**
   (`scripts/codelens.py::_apply_lite`) — the reducer dispatch table
   predates the #195 umbrella consolidation and keyed off the *old* leaf
   command names (`smell`, `dead-code`, `query`, ...). Since umbrella
   commands always pass their own name (`context`, `audit`, `security`,
   ...), no branch ever matched — every umbrella's `--lite` output
   silently collapsed to `{"status": "ok"}` with all data dropped. Fixed
   by unwrapping the `{"s","st","r":[{"_check":name,...}]}` envelope,
   applying the existing per-check reducers keyed by each item's own
   `_check` name, then re-wrapping. Verified: `audit --check dead-code
   --lite` now returns `removal_safety`/`stats`/`top_items` as designed.

4. **Rust inline test functions false-flagged as dead code**
   (`deadcode_engine.py::_detect_dead_from_registry`) — the existing
   test-file exemption only matched separate-directory conventions
   (`/tests/`, `/__tests__/`), which doesn't cover Rust's idiomatic
   `#[cfg(test)] mod tests { #[test] fn ... }` living inline in the same
   file as production code. On the verified workspace this was **56%+ of
   all Rust `registry_dead` findings** (real measurement: 100→69 in the
   top-100 window after the fix, with `mod tests` blocks also newly
   exempted). Fixed by peeking at the source lines above a flagged
   symbol for a `#[test]`-family attribute. Added
   `tests/test_deadcode_engine.py::test_registry_dead_exempts_rust_inline_test_functions`.

5. **`deps --check import-snapshot` was permanently non-functional**
   (issue #218) — `export-snapshot` was dropped entirely in #195 with no
   replacement, so `import-snapshot` could never find a snapshot file to
   load; the underlying `build_snapshot()`/`write_snapshot()` logic in
   `snapshot_io.py` was never deleted, just orphaned. Added
   `scripts/commands/export_snapshot.py` (new `deps --check
   export-snapshot` sub-mode) and verified a full export→import round
   trip preserves node/edge counts. Also excluded both snapshot checks
   from the bare `codelens deps <workspace>` default (they're
   side-effecting/opt-in and previously always showed a spurious error
   with no `--input`/`--output` given). See
   `docs/design/0218-export-snapshot.md` and
   `tests/test_export_snapshot.py`.

6. **`summary --lite` didn't actually reduce output** — summary's own
   `--help` describes it as "anti-overload prioritized findings", but
   `--lite` fell through to the generic fallback which only trims the
   *outer* `findings` list, not each finding's nested `top_items` (and
   dataflow findings nest a full `flow_chain` per item). On the verified
   workspace, `summary . --lite` returned the same multi-thousand-token
   payload as the non-lite call. Added a dedicated `summary` reducer that
   trims each category's `top_items` to 3 and strips `flow_chain`. Added
   regression test.

7. **`history --lite` collapsed to `{"status", "workspace"}`** — same root
   cause as #6: history's real payload (`snapshots`, `latest`, `trends`,
   `deltas`) lives under keys the generic fallback doesn't recognize.
   Added a dedicated `history` reducer. Added regression test.

8. **Windows CRLF corruption in all stdout/stderr output** — `_force_utf8_stdio()`
   (the fix for issue #179's Unicode arrow crash) re-wraps stdout/stderr
   with `io.TextIOWrapper(..., encoding='utf-8')` but never set `newline=''`,
   so every `\n` written on Windows silently became `\r\n` (Python's
   default write-side `os.linesep` translation). This affects every JSON/
   text line CodeLens prints on Windows — harmless for JSON *parsing* but
   breaks byte-exact comparisons and any tool assuming Unix line endings.
   Fixed by adding `newline=''`. This was already caught by an existing
   test (`test_writes_unicode_arrow_to_replaced_stream`) that was failing
   before this fix.

## Test suite baseline (verified 2026-07-12, post-fixes)

Full suite (`pytest tests/ --ignore=test_integration.py --ignore=test_lsp_server.py
--ignore=test_large_file_parsing.py`) has ~20 pre-existing failures unrelated
to this session's changes — confirmed by isolating each one and checking it
touches files never edited today (Windows path-separator assumptions in
`test_codelensignore.py`/`test_compact_format.py`/`test_history_engine.py`/
`test_secrets_gitleaks.py`, `os.geteuid()` not existing on Windows in
`test_doctor.py`, schema-version test debt in `test_confidence.py`, etc.).
Two additional failures observed this session
(`test_cli.py::TestArgparseFormatConflictRegression::test_scan_with_format_*`)
are pure environment slowness, not a functional break — `codelens scan .` on
the CodeLens repo itself (400+ Python files) exceeded the test's 60s
subprocess timeout before the actual assertion (no argparse error in stderr)
was ever reached. None of these block real usage; they're Windows-vs-POSIX
test debt, not product bugs.

## Known limitations (not fixed — scope, not a quick bug)

- **No Rust taint analysis.** `security --check taint` only analyzes
  Python/JS/TS/TSX (`ast_taint_engine.get_supported_languages()`). A Tauri
  app that shells out via `std::process::Command` (verified: this workspace
  has several `Command::new(...)` sinks fed by `std::env::var()` sources in
  `.rs` files) gets zero taint coverage on the Rust side. This is a real
  feature gap for `harus berkerja di rs` — building Rust source/sink rules
  + AST walking is a multi-day feature, not a bug fix, so it wasn't
  attempted this session. Tracked as a GitHub issue for follow-up.
- **Rust `impl`-block dead-code false positives** (issue #228) — separate,
  deeper false-positive source than the test-function one fixed this
  session. Still open.
- **`.ts` files are silently counted under the `tsx` bucket** in `scan`
  output stats (`files_scanned.tsx` = actual `.tsx` + `.ts` count). Cosmetic
  only — parsing/analysis is correct, just the reported stat label is
  misleading if you're trying to verify TS vs TSX file counts from `scan`
  output alone.
- **`language` field is always empty (`""`) in `search --mode semantic`
  results** — `graph_nodes` (the table semantic search reads from) doesn't
  carry a language column; documented as intentional in
  `semantic_search_engine.py`'s own docstring (file extension already
  conveys language). Not fixed — would need a schema change for
  low value (extension already tells you the language).
