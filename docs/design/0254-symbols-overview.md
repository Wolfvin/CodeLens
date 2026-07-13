# Design Doc: Token-efficient symbols overview fast-path

> **Status:** Accepted
> **Date:** 2026-07-13
> **Author:** Claude (direct implementation — user directive)
> **Related issues:** #254
> **Related PRs:** (this PR)

---

## Problem

Gap-analysis vs Serena MCP: Serena's `get_symbols_overview` gives "a hierarchical
map of top-level symbols in a file, allowing agents to understand structure WITHOUT
reading every line" — token-efficient onboarding.

CodeLens has `context --check outline` but: (a) flat per-file output, no workspace-wide
1-call overview; (b) outline re-reads `outline.json` (cached JSON), not the live
`graph_nodes` SQLite table; (c) paginated at 20 files/call — an agent needing "what
lives in each file across 200 files" requires 10 round trips.

## Goal

One call returns compact per-file symbol map (name + kind + line) for a workspace or
specific file — no re-parse, no LSP, data already in `graph_nodes`.

## Implementation

### New Files
- `scripts/commands/symbols_overview.py` — queries `graph_nodes` via sqlite3 directly.
  Groups by file, filters to meaningful kinds (function/method/class/module/route/type/
  interface/struct/enum/trait), sorts by line. No parser import at runtime.

### Modified Files
- `scripts/commands/context.py` — registered `overview` in `_CHECKS`, added
  `_build_namespace` branch (file filter + max_files), updated epilog + examples,
  added `--max-files` argument.
- `tests/test_command_registry.py` — `symbols_overview` added to implementation-module
  allowlist.

### Not Changed
- `graph_nodes` schema — read-only; no migration needed.
- `outline_engine.py` / `outline.py` — unchanged; overview is a separate fast-path,
  not a replacement.

## Output Shape

```json
{
  "status": "ok",
  "stats": {"total_files": 45, "total_symbols": 312, "truncated": false},
  "overview": {
    "scripts/commands/audit.py": [
      {"name": "add_args",   "kind": "function", "line": 83},
      {"name": "execute",    "kind": "function", "line": 201}
    ]
  }
}
```

## Token Efficiency

Per-file: overview ~1100 chars vs outline ~1600 chars (31% smaller). Workspace-wide:
200 files in 1 call vs outline --all paginating 20 files/call. The key gain is
call-count reduction, not per-symbol byte savings.

## Why a new `_CHECKS` entry, not a flag on outline

- Outline reads `outline.json` (per-file cached) via `outline_engine`; overview reads
  `graph_nodes` directly. Different data source = different module.
- Avoids coupling the outline code path to DB-presence logic.
- Follows the pattern of `diagnostics` (#253) and `css` (#251) — thin wrapper per sub-check.

## Alternatives Considered

- **`--detail minimal` on outline.** Rejected — outline's minimal still reads the per-file
  cache, doesn't support workspace-wide single-call, and can't naturally express "no body,
  just name+kind+line".
- **Compact string format** (`"42:fn:handleAuth"`). Considered — would further reduce tokens
  but breaks JSON consumers that iterate `name`/`kind`/`line` keys. The `{"name","kind","line"}`
  dict is a small cost for API stability.

## Testing

6 pytest unit tests: no-registry graceful degradation, symbol grouping, file filter,
noise-kind exclusion, max_files truncation, no-reparse invariant (asserts tree-sitter
never imported). All pass.
