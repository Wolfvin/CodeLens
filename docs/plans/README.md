# Implementation Plans

This directory holds **implementation plans** for CodeLens features. A plan is
a phase-based checklist — each phase produces a mergeable PR.

## When is a plan required?

A PR that adds a new feature to CodeLens MUST include an implementation plan.
The CI check in `.github/workflows/require-design-doc.yml` enforces this (it
checks for both a design doc AND a plan doc).

The same "feature-class" rule applies as for design docs — see
[`../design/README.md`](../design/README.md) for the exact criteria. The
`skip-design-doc` label exempts a PR from both checks.

## How to use the template

1. Copy `template.md` to `<feature-name>.md` (kebab-case, matching the design
   doc name).
2. Fill in the Summary, Phases, Test strategy, Rollout, and Risks sections.
3. Each phase should be independently mergeable. If a phase has more than ~10
   files or ~500 lines, split it.
4. Stop adding phases when the plan is complete. Do NOT pad with "future"
   phases — link a GitHub issue instead.
5. After each phase merges, tick the checkboxes in that phase's `Files` and
   `Acceptance` lists.
6. When all phases are done, mark the plan `Status: Done` and write a
   1-paragraph retrospective in the linked design doc's `Findings` section.

## Existing plans

| Plan | Feature | Design doc | Issue | Status |
|---|---|---|---|---|
| (none yet — feature work is tracked in GitHub issues until the first plan is added under this convention) | | | | |

When you add a new plan, add a row to this table.

> **Note for backfill:** The existing features (taint engine, MCP server, plugin
> system, graph model) were built BEFORE this convention existed. They have
> design docs in [`../design/`](../design/) but no retroactive plans — their
> implementation is already shipped and tracked in `CHANGELOG.md`.
