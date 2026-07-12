# Design Doc: Module-top-level Call Extraction (Issue #210)

> **Status:** Proposed
> **Date:** 2026-07-12
> **Author:** Wolfvin
> **Related issues:** #210
> **Related PRs:** (this PR)

---

## Problem

CodeLens `reference_count` (`rc` field in `search --mode symbol` output) was
severely undercounting cross-file calls for any function only called via
the two patterns below — both extremely common in modern Express/Router
modular backends:

1. **Middleware-factory argument pattern.** A function call passed as an
   argument to another call at module top-level, e.g.
   `router.post(path, requirePermission('admin'), handler)`. The
   `requirePermission('admin')` call is inside `router.post(...)`'s
   argument list — at module top-level, not inside any function body.

2. **Inline arrow callback body pattern.** A function call inside an
   inline arrow function passed as a callback, e.g. the route handler
   `(req, res) => { if (hasPermission(...)) {...} }`. The arrow function
   is NOT assigned to a variable, so it's not registered as a function
   declaration, and its body is never walked for call extraction.

Concrete cases reported in issue #210 (verified against the
Coretax-Auto-Downloader / KDS backend):

- `requirePermission` (middleware factory in `src/middleware/permission-gate.ts`)
  was reported with `rc: 0`. Ground truth: 13+ call sites across route files
  via `router.post(path, requirePermission('admin'), handler)` at module top-level.
  Verified via SQLite: `SELECT * FROM graph_edges WHERE target_id = ...`
  returned 0 rows.

- `hasPermission` (utility in `src/lib/permissions.ts`) was reported with
  `rc: 1`. Ground truth: 7 call sites in 3 files (3 in `assignments.ts`,
  3 in `task-templates.ts`, 1 in `permission-gate.ts`). Only the call
  inside `requirePermission`'s direct body was extracted.

Both bugs have the same root cause: the TS/JS backend parsers' per-function
pass only walks bodies of registered function/class declarations. Module-
top-level calls and inline arrow callback bodies are invisible.

## Goal

`search --mode symbol` reports `ref_count` that matches the actual number
of call sites for functions called via the two patterns above, without
regressing any existing callgraph consumer (dead-code, impact, trace).

## Changes

### Architecture / Data Model

Introduce a **module-level pass** in the TS/JS backend parsers, run after
the per-function pass. The pass walks the AST root (`program` node) and
extracts every `call_expression` / `new_expression` that hasn't already
been covered by the per-function pass, by skipping the subtrees of
registered declarations:

- `function_declaration` / `generator_function_declaration`
- `class_declaration` (its `class_body` is walked by the per-function pass)
- `variable_declarator` whose value is `arrow_function` /
  `function_expression` / a `defineStore(...)` call (Pinia store pattern)

Everything else — including inline arrow functions, call arguments, and
non-function `variable_declarator` values like `const router = Router()` —
is walked normally, so calls inside them are extracted.

Edges from module-level calls use a **synthetic source_id** of the form
`<file>:0:<module>`, with NO corresponding `graph_nodes` entry. This
mirrors the convention already used by
`hybrid_type_resolver._file_node_id` for IMPORTS edges. Benefits:

- `ref_count` (computed from the target side) is correct — each call
  site produces one edge, incrementing the target's count.
- `cmd_list` and `search --mode symbol` output remains clean — no fake
  `<module>` function entries appear in user-facing output.
- `dead-code` correctly marks previously-falsely-dead functions as
  active (their `ref_count > 0` now).
- `trace` / `impact` continue to work without crash — their JOINs on
  `source_id = node_id` simply produce no rows for `<module>` sources,
  same as the existing `<rel_path>:0:file` sources for IMPORTS edges.
  This is NOT a regression: before the fix, these commands also saw 0
  callers for `requirePermission` because no CALLS edges existed at all.

### Modified Files

- `scripts/parsers/ts_backend_parser.py` — add `_find_module_level_calls`
  method; call it from `extract_references` after the per-function pass;
  update docstring.
- `scripts/parsers/js_backend_parser.py` — add `_find_module_level_calls`
  method (using the parser's iterative DFS + `keep_alive` pattern from
  issue #116/#163); call it from `extract_references` after the main
  walk loop; update docstring.
- `scripts/parsers/fallback_js_backend.py` — add module-level scan for
  lines not covered by any function's approximate scope; emit edges with
  synthetic `<module>` source.

### Tests

- `tests/test_js_backend_parser.py::TestIssue210ModuleLevelCalls` — 6 new
  tests covering middleware-factory argument, inline arrow callback body,
  multi-site accumulation, no-double-count for function bodies, sanity
  extraction of `router.post` itself.
- `tests/test_ts_backend_parser.py` — new file with 10 tests covering
  baseline TS parsing plus the same issue #210 patterns (TS is the
  primary fix target since the KDS backend is TypeScript).

## Trade-offs

### Alternative A: Create a synthetic `<module>` node per file

- **Pros:** Trace/impact commands would see real caller counts via
  SQLite JOINs (source_id would match a real graph_nodes row).
- **Cons:** Adds fake function entries to the backend registry. Would
  require modifying `commands/list.py` and `search_engine.py` to filter
  them out — violating the issue constraint "Jangan ubah command files
  (commands/*.py) kecuali memang diperlukan". The `test_list_backend_only`
  test would also need updating.
- **Why rejected:** Violates issue constraint. The fix should stay scoped
  to parsers.

### Alternative B: Modify the per-function pass to also walk module top-level

- **Pros:** Single-pass design; no separate module-level walk needed.
- **Cons:** Would require invasive changes to the existing walk logic in
  both parsers. The TS parser's two-pass design (declarations then calls)
  and the JS parser's single-pass design (with issue #116 SIGSEGV
  mitigation) both have non-trivial structure that doesn't naturally
  accommodate "also extract calls outside function bodies".
- **Why rejected:** Higher regression risk; larger blast radius.

### Alternative C: Register inline arrow callbacks as anonymous function declarations

- **Pros:** Per-function pass would naturally walk their bodies.
- **Cons:** Anonymous functions have no name — can't be registered as
  function nodes with a meaningful `fn` field. Would require generating
  synthetic names, polluting the registry.
- **Why rejected:** Pollutes the function registry with anonymous entries.

### Chosen approach: Separate module-level pass with synthetic source_id

- **Why:** Minimal blast radius (parsers only). Follows existing precedent
  for synthetic source_ids (hybrid_type_resolver._file_node_id). No
  changes to command files or the registry shape. Satisfies the issue's
  DoD points 1 and 2 (correct `rc` in `search --mode symbol`).

## Open Questions

- [ ] Should `trace` and `impact` eventually be updated to follow
  `source_id = '<file>:0:<module>'` edges and report module-level callers?
  Currently they skip these dangling sources (same as IMPORTS edges).
  This is a follow-up enhancement, not a regression — filed as a future
  improvement once issue #210 lands.

## Migration / Rollout

No migration impact — additive change. Existing callgraphs gain new edges
for previously-missed call sites; `ref_count` values increase for affected
functions. Functions previously marked "dead" by `audit --check dead-code`
may now be correctly marked "active" if their only callers were module-
top-level. This is a correctness improvement, not a breaking change.

## References

- Issue: #210
- Prior art: `scripts/hybrid_type_resolver.py:_file_node_id` — synthetic
  source_id convention for IMPORTS edges.
- Related design docs: [0004-graph-model](0004-graph-model.md) (graph_edges
  schema, source_id semantics)
