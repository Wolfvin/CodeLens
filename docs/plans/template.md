# Implementation Plan — <Feature Name>

> **Status:** Draft | In Progress | Done | Abandoned
> **Author:** <GitHub handle>
> **Created:** YYYY-MM-DD
> **Design doc:** [`docs/design/<feature>.md`](../design/<feature>.md)
> **Tracking issue:** #<N>

<!--
This template is part of the CodeLens implementation plan convention (issue #67
Phase 1). Copy this file to `docs/plans/<feature>.md` and fill in the phases.

An implementation plan is REQUIRED for any PR that adds a new feature to CodeLens.
The CI check in `.github/workflows/require-design-doc.yml` enforces this.
PRs that are pure bug fixes, refactors, or chores are exempt (see CONTRIBUTING.md).

A plan doc is a checklist — each phase is independently shippable. The goal is
to make PRs reviewable in isolation, not to plan the universe. If a phase is
"future work", say so and stop there.
-->

## Summary

1-3 sentences: what does this plan deliver end-to-end, and how does it map to
the design doc? Link the design doc.

## Phases

Each phase is a unit of work that produces a mergeable PR. Smaller phases are
better than larger ones — if a phase has more than ~10 files or ~500 lines,
split it.

### Phase 1 — <name>

**Goal:** <one-sentence outcome>

**Files:**
- [ ] `scripts/<name>_engine.py` — new engine
- [ ] `scripts/commands/<name>.py` — new command
- [ ] `tests/test_<name>_engine.py` — unit tests
- [ ] `README.md` — update supported commands list
- [ ] `SKILL.md` / `SKILL-QUICK.md` — update command count
- [ ] `pyproject.toml` / `skill.json` — version bump if needed

**Acceptance:**
- [ ] `codelens <name>` runs end-to-end without errors on a clean workspace
- [ ] `pytest tests/test_<name>_engine.py -v` passes
- [ ] `python3 scripts/sync_command_count.py --check` reports no drift
- [ ] No new warnings in `codelens doctor` output

**Out of scope for Phase 1:**
- <explicit list of things deferred to later phases or future issues>

### Phase 2 — <name>

**Goal:** <one-sentence outcome>

**Depends on:** Phase 1 merged

**Files:**
- [ ] ...

**Acceptance:**
- [ ] ...

**Out of scope for Phase 2:**
- ...

### Phase N — <name>

(Repeat the structure for each phase. Stop when the plan is complete — do not
pad with "future" phases. If something is genuinely future work, link a GitHub
issue instead of inventing a phase.)

## Test strategy

How will correctness be verified at each phase? At minimum:

- Unit tests for new engine logic (one test file per engine)
- Integration test for the new CLI command (in `tests/test_cli.py` or a new file)
- Regression test if fixing a bug (`tests/test_<bug>_regression.py`)

If a phase adds optional behavior (e.g., tree-sitter-accelerated path), test
BOTH the fast path and the fallback path.

## Rollout

How is this shipped to users?

- Version bump? (yes/no, and which: patch/minor/major)
- CHANGELOG entry? (yes — add a draft entry here)
- Migration needed? (if yes, link `commands/migrate.py` update or document the migration)
- Documentation update? (README, SKILL.md, references/*.md)

## Risks

What could go wrong during implementation? For each risk, note mitigation.

- **Risk:** <thing that could break>
  - **Mitigation:** <how to detect / prevent / recover>
- **Risk:** ...
  - **Mitigation:** ...

## Done

When ALL phases are merged and the tracking issue is closed, mark this plan
`Status: Done` and update the design doc's `Findings` section with a 1-paragraph
retrospective. Do NOT delete this file — it stays as the historical record.
