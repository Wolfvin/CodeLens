# Design Doc: Restore a11y as `audit --check a11y`

> **Status:** Accepted
> **Date:** 2026-07-13
> **Author:** Claude (direct implementation, no worker — user directive)
> **Related issues:** #256
> **Related PRs:** (this PR)

---

## Problem

`a11y_engine.py` (WCAG 2.1 accessibility analysis: missing alt text, missing
form labels, ARIA issues, keyboard-nav gaps, non-semantic HTML, color contrast,
heading order, link text, focus management) is fully functional — verified 2
real findings on `tests/fixtures/sample.html` — but **orphaned**: its CLI
entry point (the old standalone `a11y` command) was deleted in the #195
umbrella consolidation, and `audit_accessibility()` is now reachable from no
command, MCP tool, or `--check` sub-mode.

This is the **exact same situation as `css-deep` (issue #251, PR #252)** and
`export-snapshot` (issue #218): a working engine with a dead entry point.

## Goal

`codelens audit <workspace> --check a11y` runs `audit_accessibility()` and
returns findings in the standard audit umbrella shape, with `--severity` and
`--category` passthrough.

## Changes

### New Files
- `scripts/commands/a11y.py` — thin wrapper over
  `a11y_engine.audit_accessibility()`, mirroring `css_deep.py`'s structure.
  No engine logic duplicated.

### Modified Files
- `scripts/commands/audit.py` — registered `a11y` in `_CHECKS`, added
  namespace branch (severity + category passthrough), updated epilog.
- `tests/test_command_registry.py` — added `a11y` to the
  implementation-module allowlist (it's imported by the audit umbrella,
  not self-registering — same pattern as `css_deep`).

### Not Changed
- `a11y_engine.py` — the engine already works and needed no changes.

## Why a sub-check, not a restored top-level command

Same reasoning as #251: the #195 consolidation reduced 78 commands to 12
umbrellas. Re-adding `a11y` as a top-level command would violate that.
As `--check a11y` under `audit` — alongside dead-code / complexity / smell /
perf-hint / css — it fits the audit umbrella taxonomy and keeps the command
count at exactly 12.

## Testing

Verified end-to-end via CLI: `codelens audit tests --check a11y` → 2 real
findings (missing_label high + semantic_html low) from `tests/fixtures/sample.html`.
`--severity high` passthrough confirmed. `tests/test_command_registry.py`
2 passed.

## Alternatives Considered

- **Leave it dropped.** Rejected — the engine works, HTML/accessibility is in
  scope (CodeLens covers HTML files), and the loss forces manual auditing.
- **Restore as a top-level `a11y` command.** Rejected — violates the
  12-umbrella consolidation. Sub-check placement recovers the capability
  without growing the command surface.
