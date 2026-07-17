# Design Doc: Named-Flow View (`context --check flow`)

> **Status:** Accepted
> **Date:** 2026-07-18
> **Author:** Wolfvin (BOS) / Claude Code
> **Related issues:** #309
> **Related PRs:** (this PR)
> **Builds on:** #305 (tag audit), #297 (edge diff — the phase-2 partner)

---

## Problem

A single logical flow — say a payment path — is implemented across scattered
functions in different files. `@FLOW: PAYMENT` tags mark them, and #305's tag
audit can *inventory* flows, but there is no way to ask the operational
question: **"show me every function in the PAYMENT flow, collected."** The
functions stay scattered; the reader reassembles the chain by hand.

Wolfvin's framing: *"1 flow dari sebuah rantai function — dengan 1 command,
semua function muncul dari yang awalnya tersebar."*

## Goal

One sub-check that collects a named flow's members into a single view, from the
`@FLOW` tags **an agent already wrote** — inventing nothing. Deterministic
(regex only, no LLM). `--name X` collects one flow; bare lists all flows.

## Architecture decision — agent writes, CodeLens stores & serves

Per Wolfvin: **not auto-detection.** The agent authors `@FLOW: NAME` in the
source (the tag is the source of truth); CodeLens owns the graph and serves the
query. This sub-check is the read-only *serve* half. It never invents a flow
name and never edits source.

Two ways to "store" the tags were considered:

- **(A) Persist tags into graph nodes at scan time** — a `flow` attribute on
  each `graph_nodes` row, queryable by SQL join with the call-graph. This
  touches the parser + scan pipeline across every language (backend), so per
  the project's delegation rules it is a **worker task, phase 2**.
- **(B) Read tags on demand and reshape** — compose the existing
  `tag_audit_engine` output flow-first at the command layer. Read-only, touches
  no scan/parser code, same class as #305's tag audit.

This PR ships **(B)** as the MVP: it delivers the collected-flow view now
without backend changes. (A) is the follow-up optimization (fast SQL queries,
join with call-edges) and is the piece to delegate.

## Changes

### New file
- `scripts/commands/flow.py` — thin `execute()`; runs `audit_tags()`, reshapes
  flow-first. `--name X` → one flow's members (or a not-found message listing
  known flows); bare → all flows with member counts.

### Engine enhancement (`tag_audit_engine.py`)
- Each `@FLOW` tag is now attributed to its **enclosing symbol**, so a flow's
  members read as function names, not bare locations. Resolution order:
  1. **comment-above-def** — a def within `_LOOKAHEAD` (3) lines below the tag,
     crossing only blank/comment lines (the JS idiom `// @FLOW` then `export
     function charge`);
  2. else the **nearest def above** (the docstring idiom — tag inside a
     function body);
  3. else the **file** (a true file-header tag, e.g. a `.d.ts` header block).
- `flows[]` gains `members: [{symbol, file, line}]`. `locations` is retained
  unchanged for backward compat (#305 consumers + #306 ai item extraction).
- Declaration detection is a broad, language-agnostic regex (`def/fn/func/
  function/class/struct/interface/type/impl/trait` + JS `const x =` / `x() {`).
  A miss falls back to the file, so it need not be exhaustive.

### Registry / docs
- `commands/context.py`: register `flow` in `_CHECKS` + epilog; wire `--name`
  through `_build_namespace`. Command count stays **12** (sub-check).
- `flow` added to README / SKILL / SKILL-QUICK context rows and the
  `_command_registry` sub-check allowlist.

## Non-goals (explicit)

- **No writing.** Consistent with #305 — deciding a flow's membership is
  authorship, which belongs to the agent.
- ~~No call-edges among members (yet).~~ **Shipped in #311** — `--name X` now
  includes `edges: [{from, to}]` among members, resolved read-only via
  `graph_model.query_callees` filtered to the member set (graceful: no graph DB
  → flat list). The remaining subgraph work is only its pairing with #297
  edge-diff ("did the PAYMENT flow's shape change between two checkpoints?").
- **Enclosing-symbol resolution is heuristic**, not a parser. It resolves the
  common docstring and comment-above-def idioms; an unusual layout falls back
  to the file rather than guessing wrong.

## Testing

Unit tests with synthetic fixtures: docstring-tag → enclosing def; comment-
above-def → the def below; file-header tag → file fallback; look-ahead does not
bind a docstring tag to a later nested def; `--name` filter (found + not-found
with available list); cross-language collection (a PAYMENT flow spanning `.py`
and `.js`). Self-scan sanity: CodeLens's own tree collects its dispatch flows,
including this feature's own `FLOW_VIEW`.
