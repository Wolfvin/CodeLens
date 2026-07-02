# Implementation Plan: [Feature Name]

> **Design doc:** [NNNN-feature-name.md](../design/NNNN-feature-name.md)
> **Issue:** #NNN
> **PR:** #NNN
> **Status:** Not started | In progress | Complete | Blocked

---

## Scope

One-paragraph summary of what this plan covers. Reference the design doc for
the "why" — this plan is only the "how" and "when".

## Phases

Break the work into phases that can be independently reviewed and merged.
Each phase should leave the codebase in a working state (tests pass, no
half-finished features). Prefer vertical slices over horizontal layers.

### Phase 1: [Name] — [estimated duration]

**Goal:** [one sentence outcome]

**Tasks:**
- [ ] Create `scripts/yourfeature_engine.py` with stub `analyze()` function
- [ ] Add `commands/yourfeature.py` with `add_args` + `execute`
- [ ] Register in CLI (auto-registered via `commands/__init__.py`)
- [ ] Add basic test: `tests/test_yourfeature.py::test_smoke`
- [ ] Run `python scripts/sync_command_count.py --apply`
- [ ] Update `README.md` + `SKILL-QUICK.md` command list

**Acceptance:**
- `codelens yourfeature --help` works
- Smoke test passes
- Command count in docs matches `COMMAND_REGISTRY`

**Dependencies:** None

### Phase 2: [Name] — [estimated duration]

**Goal:** [one sentence outcome]

**Tasks:**
- [ ] Implement full analysis logic in `yourfeature_engine.py`
- [ ] Add edge-case tests: empty input, missing files, corrupt data
- [ ] Add `--format graphml` support (if applicable)
- [ ] Benchmark on `tests/fixtures/` — must complete <1s

**Acceptance:**
- All tests pass
- No regression in `tests/test_cli.py`
- Benchmark target met

**Dependencies:** Phase 1

### Phase 3: [Name] — [estimated duration]

**Goal:** [one sentence outcome]

**Tasks:**
- [ ] ...

**Acceptance:**
- ...

**Dependencies:** Phase 1, Phase 2

## Testing Strategy

Describe how each phase will be verified. Include:
- Unit tests (which files, what scenarios)
- Integration tests (if applicable)
- Manual verification steps (commands to run, expected output)
- Regression checks (which existing tests must still pass)

## Rollback Plan

If this needs to be reverted after merge, what's the procedure?
- Is the change behind a feature flag?
- Can the new command be removed without breaking existing workflows?
- Are there database migrations to undo?

If the change is purely additive (new command, new file), rollback is trivial:
revert the PR. If it modifies existing behavior, describe the fallback path.

## Notes

Anything that doesn't fit above — links to research, relevant Slack
discussions, gotchas discovered during implementation, etc.
