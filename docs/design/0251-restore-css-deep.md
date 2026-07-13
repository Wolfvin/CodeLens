# Design Doc: Restore css-deep as `audit --check css`

> **Status:** Accepted
> **Date:** 2026-07-13
> **Author:** Claude (direct implementation, no worker — user directive)
> **Related issues:** #251
> **Related PRs:** (this PR)

---

## Problem

`cssdeep_engine.py` (deep CSS analysis: unused CSS variables, orphan
keyframes, specificity wars, duplicate properties, unused media queries,
z-index abuse) is fully functional — verified 154 real findings on the
Coretax `smart-tax-assistance` workspace — but **orphaned**: its CLI entry
point (the old standalone `css-deep` command) was deleted in the #195
umbrella consolidation, and `analyze_css_deep()` is now reachable from no
command, MCP tool, or `--check` sub-mode. This is the same situation as
`export-snapshot` (issue #218, restored): a working engine with a dead
entry point.

CSS is in CodeLens's stated language scope (react/css/html). Losing deep
CSS analysis means falling back to manual grep for questions like "is this
CSS variable still used?".

## Goal

`codelens audit <workspace> --check css` runs `analyze_css_deep()` and
returns findings in the standard umbrella `{s, st, r}` shape, with
`--severity` and `--category` passthrough.

## Changes

### New Files
- `scripts/commands/css_deep.py` — thin wrapper over
  `cssdeep_engine.analyze_css_deep()`, mirroring `export_snapshot.py`'s
  structure. No engine logic duplicated.

### Modified Files
- `scripts/commands/audit.py` — registered `css` in `_CHECKS`, added the
  namespace branch (severity + category passthrough), updated epilog.
- `tests/test_command_registry.py` — added `css_deep` to the
  implementation-module allowlist (it's imported by the audit umbrella,
  not self-registering — same as `export_snapshot`).
- `docs/agent-usage-guide.md` — css-deep documented as available again.

### Not Changed
- `cssdeep_engine.py` — the engine already works and needed no changes.

## Why a sub-check, not a restored top-level command

The #195 consolidation reduced 78 commands to 12 umbrellas. Re-adding
`css-deep` as a **top-level** command would violate that (command count
would go to 13). As a `--check css` sub-mode under `audit` — alongside
dead-code / complexity / smell / perf-hint, all code-quality analyses — it
fits the umbrella taxonomy and keeps the command count at exactly 12
(verified via `--command-count`). This is compatible with the #195
philosophy (fewer top-level commands, richer sub-checks), not a reversal
of it.

## Testing

`tests/test_css_deep_command.py`: wrapper delegation, severity/category
passthrough, audit umbrella dispatch of `css`, and severity reaching the
engine through the synthetic namespace. Verified end-to-end on the real
workspace: 154 findings, `--severity high` → 3, `--category z_index_abuse`
→ 1.

## Alternatives Considered

- **Leave it dropped.** Rejected — the engine works, CSS is in scope, and
  the loss forces manual grep for CSS-variable/keyframe usage. Same
  reasoning that restored `export-snapshot` (#218).
- **Restore as a top-level `css-deep` command.** Rejected — violates the
  12-umbrella consolidation. Sub-check placement recovers the capability
  without growing the command surface.
