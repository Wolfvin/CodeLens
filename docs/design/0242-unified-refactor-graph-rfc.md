# Design Doc: Unified graph for read (trace/impact) and write (rename/move)

> **Status:** Rejected — recommend not building
> **Date:** 2026-07-12
> **Author:** Claude (direct RFC, no worker — user directive)
> **Related issues:** #242
> **Related PRs:** #247 (issue #241 — the alternative this RFC recommends instead)

---

## Problem

Today the graph that answers "who calls X" (`context --check trace`, `impact`) and the
process that would actually EXECUTE a code change (rename, move, delete) are two
separate worlds — CodeLens has no write/refactor engine at all, only read-only
analysis. The concern raised when this RFC was scoped: if CodeLens (or any tool)
someday adds write capability, the graph used to decide "is this safe to change"
could drift from the graph actually used to execute the change, producing a
rename that was "verified safe" but executes incorrectly.

## Goal

Answer: should CodeLens build an actual write/rename engine, and if so, how does
it guarantee the analysis graph and the execution graph never drift apart?

## Analysis

### What already exists

Issue #241 (merged, PR #247) already ships `impact --action rename
--new-name Y`, which returns a `rename_checklist` — every statically-resolved
call site (file, line, caller) that references the symbol — computed from the
exact same graph `trace`/`impact` use for read-only analysis. There is no
drift problem for the *analysis* side because there is nothing else consuming
a separate graph.

### What "building a write engine" would actually require

A rename that's genuinely safe to auto-apply across a real codebase needs to
handle, at minimum:
- Every call-site reference (what #241 already covers)
- Import/export statement rewriting (named imports, aliased imports, re-exports, barrel files)
- String-based/dynamic references (`import(variableName)`, reflection, computed
  property access, string-keyed dispatch tables) — **not resolvable by static
  analysis at all**, in any tool, not just CodeLens
- JSX/template usage (a component rename must update every `<OldName>` tag)
- Comments/docs mentioning the old name (cosmetic, but a "complete" rename
  engine gets judged on this)
- Cross-language boundaries when the symbol crosses one (e.g. a Tauri IPC
  command name referenced as a string literal on both the Rust and TS side —
  no AST-level "declaration" to rename on the string-literal side at all)

This is not a graph-synchronization problem — it's re-implementing what
language servers (rust-analyzer, tsserver) already do, correctly, via LSP
`textDocument/rename`, which is a *far* larger and more mature codebase than
CodeLens's own read-only analysis engines. CodeLens already has partial LSP
integration (`--deep` flag, `hybrid_engine.py`) — the correct rename
implementation, if CodeLens ever executes a rename, is "shell out to the
already-running language server's rename provider," not a bespoke multi-file
AST rewriter built from scratch in CodeLens's own parsers.

### Why the graph-drift concern is lower stakes than framed

The scenario this RFC was meant to prevent — "graph says safe, execution
breaks something" — is actually the *normal* case for every refactor tool,
including LSP-based ones: a rename computed at time T can be invalidated by a
concurrent edit at time T+1 before it's applied. The mitigation every real
tool uses is the same one that already applies here: re-verify (re-scan) close
to the point of execution, not "share one graph object across analysis and
execution." CodeLens's `--diff-base`/staleness signal (issue #237, merged)
already gives a caller the tool to check "has anything changed since I last
looked" immediately before acting — that's the actual answer to the drift
concern, and it doesn't require building a write engine to get it.

### What the agent actually needs (the real gap, already closed)

An AI agent (Claude Code, Cursor, etc.) invoking CodeLens already has its own
file-edit tools. The gap CodeLens needed to close was "tell me *exactly* what
needs to change and warn me what you can't see" — which is precisely what
issue #241 delivers. The agent applies the checklist with its own edit tool,
then re-scans to verify. CodeLens does not need to hold the pen.

## Recommendation

**Do not build a write/rename engine in CodeLens.** Concretely:

1. Issue #241 (merged) is the correct scope for "safe to change" tooling —
   analysis + checklist, not execution.
2. If CodeLens later wants execution-assisted refactors, the correct design
   is "invoke the already-connected language server's rename provider via the
   existing `--deep`/`hybrid_engine.py` LSP integration," not a new bespoke
   AST-rewriting engine — this reuses infrastructure that already exists and
   is already correct for the in-language case, and doesn't pretend to solve
   the cross-language / string-literal case that no static tool can solve
   completely anyway.
3. If (2) is ever pursued, it deserves its own RFC scoped narrowly to "shell
   out to LSP rename for single-language, same-file-set renames" — explicitly
   NOT attempting cross-language (e.g. Tauri IPC) renames, which remain a
   human/agent responsibility with CodeLens's checklist as the aid.

## Changes

None. This RFC recommends no code changes — issue #242 should be closed with
this document as the record of why.

## Alternatives Considered

- **Build a bespoke multi-file AST rewriter in CodeLens.** Rejected: massive
  scope, high correctness risk (a botched auto-rename silently corrupts code,
  far worse than a botched read-only report), and duplicates already-mature
  LSP rename providers that do this correctly today.
- **"Unify" by having trace/impact and a future rename engine both read from
  the same SQLite tables (graph_nodes/graph_edges).** This is already true —
  there's only one graph in CodeLens today. The unification concern doesn't
  actually apply until a second, execution-side data structure exists to
  drift from — and this RFC recommends never building one.
