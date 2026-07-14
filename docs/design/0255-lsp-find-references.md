# Design Doc: Optional LSP-backed find-references for trace-up precision

> **Status:** Accepted
> **Date:** 2026-07-14
> **Author:** Claude (direct implementation, no worker — user directive)
> **Related issues:** #255
> **Related PRs:** (this PR)

---

## Problem

Gap-analysis vs Serena MCP: Serena's find-references uses the language
server (`textDocument/references`) — a real AST/symbol table, high precision,
no missed references. CodeLens's caller/reference discovery
(`context --check trace --direction up`) uses a home-grown call graph that is
an *approximation*. Evidence: a run of ref-count/trace edge-case bugs were
found and fixed across the project (#210, #219, #222, #223 module-level
callers). The graph will always have edge cases; LSP `textDocument/references`
does not.

CodeLens already had the LSP capability: `lsp_client.py:350`
`find_references(file, line, character)` issues `textDocument/references`, and
`hybrid_engine.py` already used it internally to *verify* dead-code and
enhance impact (`_filter_external_references`). But that precision was never
exposed as a navigation path for agents.

## Goal

When `--deep` is active **and** an LSP server is available,
`context --check trace --direction up` (and `--direction both`) uses LSP
`textDocument/references` as the precision source for callers, annotating the
result `trace_source: "lsp"`. Without `--deep`, or without a live LSP server,
or when the symbol can't be resolved/located — the existing graph path is used
unchanged (`trace_source: "graph"`). Zero-config keeps working with no
regression and no LSP dependency.

## Changes

### Modified Files
- `scripts/hybrid_engine.py` — new
  `HybridEngine.find_references_for_symbol(symbol_name)`. Reuses existing
  machinery only: `_find_symbol_definition` (registry lookup) to resolve the
  symbol → `(file, line)`, `_find_symbol_char` to locate the column, then
  `lsp_client.find_references(..., include_declaration=False)`, then
  `_filter_external_references` to drop the definition site. Converts LSP
  0-indexed lines to 1-indexed. Returns `None` (not `[]`) when LSP is
  inactive or the symbol can't be resolved, so the caller can distinguish
  "no LSP path" from "LSP ran, found zero references". Never raises.
- `scripts/commands/trace.py`:
  - `execute()` — after the graph `trace_symbol` call, when `args.deep` is
    truthy and `direction in ("up", "both")`, calls the new
    `_apply_lsp_trace_up`; otherwise annotates `trace_source: "graph"`.
  - `_apply_lsp_trace_up(name, workspace, result)` — creates a hybrid engine
    with `deep=True`, and **only if `engine.lsp_active`** replaces
    `result["chains"]["up"]` with LSP-derived caller entries
    (`source: "lsp"`), sets `trace_source: "lsp"`, and records
    `graph_callers_found` / `lsp_callers_found` for A/B comparison. On engine
    creation failure, inactive LSP, or `None` refs, it leaves the graph
    chains untouched and annotates `trace_source: "graph"`. Always calls
    `engine.cleanup()`.

### No new LSP infrastructure
Per the issue constraint, this reuses `lsp_client.find_references` and the
existing `hybrid_engine` resolution/filter helpers. `find_references_for_symbol`
is orchestration over those, not new LSP plumbing. LSP is never made a hard
dependency — the graph path is the default and the fallback.

### Placement rationale
The precision upgrade lives at the command boundary (`commands/trace.py`),
not in `trace_engine.py`. `trace_engine` stays a pure graph/flat backend with
an unchanged output shape; the opt-in LSP overlay is applied on top only when
`--deep` + LSP are present. This keeps the zero-config trace path completely
untouched and easy to reason about.

## Testing

`tests/test_issue255_lsp_references.py` (8 tests):

**Graceful degradation — live (real scan + CLI-equivalent trace):**
- no `--deep` → `trace_source: "graph"`, callers still found, LSP path never
  touched (no `lsp_available` key).
- `--deep` on a real scanned workspace → well-formed output, `status: ok`,
  no crash, no hang, `trace_source` in `{graph, lsp}`.

**LSP happy path — mocked** (`create_hybrid_engine` / `find_references`
mocked, mirroring #253):
- LSP active + refs → chains.up rewritten to LSP entries, `trace_source: lsp`,
  stats + `graph/lsp_callers_found` updated, `cleanup()` called.
- LSP inactive → graph retained, `lsp_available: false`.
- refs `None` (symbol unresolved) → graph retained.
- engine creation raises → graph retained.
- `find_references_for_symbol` resolves def site, excludes it, converts
  0→1-indexed; returns `None` when LSP inactive.

**Live verification (real CLI, this environment):**
- `codelens context <ws> --check trace --name helper --direction up` →
  `trace_source: graph`, callers found — zero-config unaffected.
- same with `--deep` → `lsp_available: true`, but the live server did not
  return usable references for the symbol, so it degraded to
  `trace_source: graph` — no hang, no error, exit 0.

**LSP happy-path live limitation (honest):** the LSP happy path
(`trace_source: lsp` with real references) could **not** be verified against a
live server in the dev environment — rust-analyzer (the only installed
server) does not respond to `initialize` within 60s (pre-existing, same
limitation documented in #253). The happy path is covered by the mocked tests
above; only the graph fallback and graceful-degradation paths are
live-verified.

## Backward compatibility

Zero-config (`context --check trace ...` without `--deep`) is byte-for-byte
unchanged — the graph result only gains a `trace_source: "graph"` annotation.
No behavior change to `trace_engine.py`. `--direction down` is never touched
by this feature (callees are not references).
