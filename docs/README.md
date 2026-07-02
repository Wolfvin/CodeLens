# CodeLens Documentation

This directory contains CodeLens design documents, implementation plans, and
process guides.

## Structure

```
docs/
├── README.md                  ← you are here
├── design/                    ← design docs (why a feature exists)
│   ├── template.md            ← copy this to start a new design doc
│   ├── 0001-taint-engine.md
│   ├── 0002-mcp-server.md
│   ├── 0003-plugin-system.md
│   └── 0004-graph-model.md
└── plans/                     ← implementation plans (how/when to build)
    └── template.md            ← copy this to start a new plan
```

## When Do I Need a Design Doc?

A design doc is **required** for PRs that add a new feature. The CI check
(`scripts/check_design_doc.py`, runs via `.github/workflows/design-doc-check.yml`)
automatically detects new-feature PRs by file pattern and fails if no design
doc is included.

### What counts as a "new feature"?

Any of these triggers the requirement:

| Pattern | Example | Why |
|---------|---------|-----|
| New file in `scripts/commands/` | `commands/yourfeature.py` | New CLI command |
| New `scripts/*_engine.py` file | `yourfeature_engine.py` | New analysis engine |
| New file in `scripts/formatters/` | `formatters/yourformat.py` | New output format |
| New parser in `scripts/parsers/` (non-fallback) | `parsers/yourlang_parser.py` | New language support |

### What does NOT require a design doc?

- Bug fixes (modifications to existing files)
- Test additions
- Documentation changes
- Dependency updates
- Refactors that don't change behavior
- Fallback parsers (`parsers/fallback_*.py`) — these are regex versions of
  existing tree-sitter parsers, not new features

### Bypassing the check

If a feature is genuinely trivial (e.g., a one-line command alias) and a
design doc would be pure overhead, add the `skip-design-doc` label to the PR.
Use this sparingly — the check exists to ensure design decisions are recorded
for future contributors.

## How to Write a Design Doc

1. Copy `docs/design/template.md` to `docs/design/NNNN-feature-name.md`
   - `NNNN` is the next available number (zero-padded to 4 digits)
   - `feature-name` is a short kebab-case slug
2. Fill in the sections:
   - **Problem** — what pain exists today? Be concrete.
   - **Goal** — what does "done" look like? User-visible outcome.
   - **Changes** — concrete file changes, grouped by area
   - **Trade-offs** — alternatives considered and why they were rejected
     (the most important section — prevents re-litigating decisions)
   - **Open Questions** — what's NOT yet decided, with owners
   - **Migration / Rollout** — how users migrate, or "additive — no migration"
3. Reference the design doc in your PR description

See `docs/design/0001-taint-engine.md` through `0004-graph-model.md` for
retroactive examples documenting existing features.

## How to Write an Implementation Plan

A plan is **recommended** (but not enforced) for multi-phase features. Copy
`docs/plans/template.md` to `docs/plans/NNNN-feature-name.md` and break the
work into independently-reviewable phases.

Plans are living documents — update the checklist as you progress. When the
feature is complete, the plan can be archived or merged into the design doc's
"Changes" section.

## Numbering Convention

Design docs and plans use ADR-style numbering: `NNNN-feature-name.md` where
`NNNN` is a zero-padded sequential number. This ensures sort stability and
makes it easy to reference a doc by number (e.g., "see design doc 0003").

The numbering is per-directory — `docs/design/0001-foo.md` and
`docs/plans/0001-bar.md` are independent sequences.

## Lifecycle

```
1. PROPOSE  → create design doc in docs/design/ as part of your feature PR
2. ACCEPT   → BOS reviews the design doc as part of PR review
3. IMPLEMENT → the design doc reflects the as-built design; update if the
              implementation diverged from the proposal
4. SUPERSEDE → if a future PR replaces this feature, mark the doc as
              "Superseded by NNNN" and create a new doc for the replacement
5. DEPRECATE → if the feature is removed, mark the doc as "Deprecated"
              but keep it for historical reference
```

Design docs are **never deleted** — they form the historical record of why
the codebase is structured the way it is. Even deprecated docs remain so
future contributors can understand past decisions.
