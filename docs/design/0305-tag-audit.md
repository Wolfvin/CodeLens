# Design Doc: Doc-Tag Audit (`context --check tags`)

> **Status:** Accepted
> **Date:** 2026-07-17
> **Author:** Wolfvin (BOS) / Claude Code
> **Related issues:** #305
> **Related PRs:** (this PR)

---

## Problem

CodeLens (and every Wolfvin project) documents intent with a per-file header
(`@WHO`/`@WHAT`/`@PART`/`@ENTRY`) and per-function docstring tags
(`@FLOW`/`@CALLS`/`@MUTATES`). The convention is real and enforced by habit,
but **nothing reads it back**, so the data rots silently:

- 46 of 236 `.py` files in `scripts/` carry the header (19%). The other 190 are
  invisible to any "which files are undocumented?" question.
- 21 named flows are hand-written (`AUDIT_DISPATCH`, `SECRETS_SCAN`, `ORIENT`…),
  but there is no way to list them or ask "which flow does this file belong to?"
- Two flows — `LLM_INVOKE` (`scripts/llm/provider.py:447`) and `LLM_TOOL_INVOKE`
  (`scripts/llm/base_tool.py:241`) — name code whose command (`llm`) was dropped
  in #195. Orphaned tags accumulate with nothing to surface them.

A convention with no tooling is documentation that lies over time.

## Goal

One sub-check that answers three questions from the tags **already in the
source**, inventing nothing: what flows exist and where, which files carry a
full / partial / no header, and which files are untagged. Fully deterministic
(regex only, no LLM), so two runs on the same tree are byte-identical.

## Changes

### New Files
- `scripts/tag_audit_engine.py` — `TagAuditEngine(BaseEngine)` + `audit_tags()`.
  Walks the workspace via the shared `BaseEngine` (reusing its ignore-dir and
  time-budget logic — no new walker), regex-matches the tag convention, and
  aggregates into a report.
- `scripts/commands/tags.py` — thin `execute()` wrapper delegating to the engine.

### Registry
- `commands/context.py`: register `tags` in `_CHECKS` + epilog. Command count
  stays 12 (sub-check, not a top-level command).

### Identity / parsing decisions
- A tag is counted only when it **opens** a comment/docstring line (optional
  `#`/`//`/`*`/`--` marker, then whitespace, then `@TAG:`). This is what
  separates a real declaration from a prose mention like ``the `@FLOW: PURE`
  example`` — without the anchor, any file *documenting* the convention (this
  engine included) registers phantom flows. Caught by dogfooding during
  implementation.
- A flow's name is the first whitespace-delimited token of its `@FLOW` value;
  the remainder is human prose.
- File header completeness = presence of all four of `@WHO/@WHAT/@PART/@ENTRY`.
  Partial (1–3 present) is reported separately as a likely-forgotten tag.
- Language-agnostic: the tags are identical across Python (`#`) and TS/JS
  (`//`); only the comment marker differs, so detection keys on the tag, not
  the language.

## Non-goals (explicit)

- **No writing.** The engine never adds or updates a tag in source. Auto-tagging
  and staleness-by-body-hash are deliberately out of scope: deciding a tag's
  *value* is authorship, which for a deterministic no-LLM tool belongs to the
  human/agent, not the scanner. Tracked as a possible follow-up.
- **No reachability claim.** Orphan flows (e.g. `LLM_*`) are surfaced by
  location, not asserted as dead — reachability needs more than a regex.

## Testing

Unit tests with synthetic fixtures (full / partial / no header, prose-mention
rejection, flow-name tokenization) plus a self-scan sanity check against
CodeLens's own tree (22 flows including this feature's own `TAG_AUDIT`, the two
`LLM_*` orphans surfaced). Deterministic output asserted by sorting.

## Known limitation

`--format markdown` and `--format ai` render the `context` umbrella envelope
`{s,st,r}` empty ("Symbol not found") — a pre-existing formatter gap affecting
all context sub-checks, tracked in #306. `json` and `compact` (the agent-facing
formats) are correct.
