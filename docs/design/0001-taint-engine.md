# Design Doc 0001: Taint Analysis Engine

> **Status:** Accepted
> **Date:** 2026-06-15 (retroactive — backfilled 2026-07-02)
> **Author:** Wolfvin
> **Related issues:** #49 (Phase 1 consolidation)
> **Related PRs:** #140 (consolidation), original implementation pre-#49

---

## Problem

CodeLens needed taint analysis to detect source-to-sink data flow vulnerabilities
(SQL injection, XSS, SSRF, path traversal, command injection). The first
attempt — `semantic_engine.py` — used regex pattern matching on source code
strings. This produced unacceptable false positives:

- String literals containing `request` or `query` were flagged as taint
  sources even when they appeared in comments or unrelated variable names.
- No path sensitivity: if a sanitizer ran on one branch of an `if/else`,
  the regex engine still flagged the other branch.
- No scope awareness: a variable named `user_input` in function A was
  treated as tainted in function B even though they had no data dependency.
- No inter-procedural flow: `def f(x): return x` followed by
  `f(request.args)` was not recognized as passing taint through `f`.

Agents using CodeLens reported that taint findings were "noisy and
untrustworthy" — they had to manually re-verify every finding, which defeated
the purpose of automated analysis.

## Goal

Produce taint analysis with:
- <5% false-positive rate on standard vulnerable-app fixtures
- Full taint path rendering (source → intermediate → sink) so agents can
  verify the finding without re-reading source code
- Path sensitivity (different taint states on if/else branches)
- Inter-procedural flow within a single file
- Confidence scores so agents can prioritize high-confidence findings first

## Changes

### Architecture

Six-phase pipeline per file:

1. **Parse** — tree-sitter produces an AST (language-aware, no regex)
2. **CFG construction** — basic blocks with branches and joins
3. **Source identification** — built-in patterns + YAML rule definitions
4. **Forward propagation** — taint flows through assignments, calls, returns
5. **Sink check** — does taint arrive at a known sink?
6. **Finding generation** — render full path + confidence score

### New Files

- `scripts/ast_taint_engine.py` — the engine itself (~3700 lines)
- `scripts/crossfile_taint_engine.py` — cross-file wrapper (Phase 1 of #49
  made this a thin compat layer over `ast_taint_engine.analyze_workspace(cross_file=True)`)
- `scripts/commands/taint.py` — CLI command
- `scripts/rules/python_security.yaml` — built-in taint rules
- `scripts/rules/javascript_security.yaml` — built-in taint rules

### Modified Files

- `scripts/codelens.py` — auto-registers `taint` command via `commands/__init__.py`
- `scripts/mcp_server.py` — `codelens_taint` MCP tool

### Confidence Scoring

| Score | Meaning |
|-------|---------|
| 0.95+ | Direct source→sink, no sanitizer, same scope |
| 0.80+ | Source→sink through function call, no sanitizer |
| 0.60+ | Source→sink with partial sanitizer |
| 0.40+ | Indirect taint, may be sanitized |

## Trade-offs

### Alternative A: Regex-based (`semantic_engine.py`)

- **Pros:** Fast, no tree-sitter dependency, simple to add new patterns
- **Cons:** No path sensitivity, no scope awareness, high false-positive rate
- **Why rejected:** False positives made the feature unusable for agents.
  `semantic_engine.py` is now deprecated (PR #140) and prints a warning on
  every use.

### Alternative B: LSP-based taint analysis

- **Pros:** Uses language servers' type inference — would catch flows the
  AST-only approach misses (e.g., dynamic dispatch)
- **Cons:** Requires a running LSP server per language, 10-30s startup time,
  not all languages have LSP servers, results vary by LSP implementation
- **Why rejected:** Too heavy a dependency for the core engine. LSP
  verification is available as an optional `--deep` enhancement via
  `hybrid_engine.py`, not as the primary path.

### Alternative C: Dataflow engine reuse

- **Pros:** `dataflow_engine.py` already does some flow tracking
- **Cons:** It tracks variable assignments, not taint semantics (source/sink).
  Reusing it would require grafting on taint-specific logic, producing a
  Frankenstein engine.
- **Why rejected:** Separation of concerns — dataflow answers "where does
  this value come from?", taint answers "is this a security vulnerability?".

### Chosen approach: Tree-sitter AST + CFG

- **Why:** Language-aware (no regex false positives), path-sensitive (CFG
  tracks branches), inter-procedural (follows calls within a file), and
  tree-sitter is already a CodeLens dependency for parsing. The cross-file
  extension (#49 Phase 1) adds inter-procedural flow across files without
  changing the per-file algorithm.

## Open Questions

- [x] Q1: How to handle library method approximation? — **Resolved** by
  #49 Phase 4 (not yet implemented as of 2026-07-01; cross-file flow is
  Phase 1, library approximation is Phase 4).
- [x] Q2: Should taint findings be persisted to SQLite? — **Resolved**:
  yes, via `persistent_registry.store_scan_result()`.
- [ ] Q3: How to handle taint through async/await boundaries? — **Open**.
  Current engine treats `await f()` as a synchronous call, which may miss
  taint flow through event-loop-mediated callbacks.

## Migration / Rollout

The AST taint engine is additive — it does not replace `semantic_engine.py`
(which remains as a deprecated alias for backward compatibility). Users who
had `semantic_engine` in their CI scripts see a deprecation warning but
their scripts continue to work.

No database migration — taint findings are stored in the existing
`scan_results` table via the standard `store_scan_result()` path.

## References

- Issue: #49 (taint analysis depth — multi-phase consolidation)
- PR: #140 (Phase 1 — cross-file consolidation)
- Prior art: Semgrep's taint mode, CodeQL's dataflow analysis
- Related design docs: [0003-plugin-system](0003-plugin-system.md) (taint
  rules can be shipped as a `rule_pack` plugin)
