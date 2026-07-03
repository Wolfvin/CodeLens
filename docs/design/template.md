# Design Doc: [Feature Name]

> **Status:** Proposed | Accepted | Superseded by [NNNN](NNNN-feature-name.md) | Deprecated
> **Date:** YYYY-MM-DD
> **Author:** [Your name / GitHub handle]
> **Related issues:** #NNN
> **Related PRs:** #NNN

---

## Problem

Describe the problem this design solves. What pain exists today? What can't
users/agents/developers do that they should be able to do? What regression or
scaling issue prompted this?

Be concrete — cite specific commands, file paths, error messages, or user
reports. Avoid vague statements like "the system is slow" in favor of
"trace on a 30k-edge graph takes 45s; agents time out at 30s (issue #17)".

## Goal

State the desired outcome in one or two sentences. What does "done" look like?
This is not a list of changes — it's the user-visible result.

Example: "Agents can trace a call chain across the full workspace in <2s,
including cross-file resolution, with results paginated to fit within 5k tokens."

## Changes

List the concrete changes this design introduces. Group by area if the change
is large. Each item should be specific enough that a reviewer can verify it
was implemented.

### Architecture / Data Model
- ...

### New Files
- `scripts/yourfeature_engine.py` — ...
- `scripts/commands/yourfeature.py` — ...

### Modified Files
- `scripts/codelens.py` — add `--your-flag` to format choices (3 places)
- `README.md` — document the new flag

### CLI / MCP Surface
- New command: `codelens yourfeature [args]`
- New MCP tool: `codelens_yourfeature`

### Tests
- `tests/test_yourfeature.py` — covers X, Y, Z

## Trade-offs

Document the alternatives considered and why they were rejected. This is the
most important section — it prevents future contributors from re-litigating a
decision without knowing the context.

### Alternative A: [Name]
- **Pros:** ...
- **Cons:** ...
- **Why rejected:** ...

### Alternative B: [Name]
- **Pros:** ...
- **Cons:** ...
- **Why rejected:** ...

### Chosen approach: [Name]
- **Why:** ...

## Open Questions

List anything that is NOT yet decided. Be honest — an open question is not a
weakness, it's a flag for reviewers. Each item should have an owner and a
decision deadline.

- [ ] Q1: Should we cache the result? (Owner: @handle, decide by YYYY-MM-DD)
- [ ] Q2: How does this interact with `--deep` (LSP) mode? (Owner: @handle)

## Migration / Rollout

If this change is user-visible or breaks existing behavior, describe how users
migrate. Include deprecation timelines, fallback behavior, and how to detect
the old vs new behavior.

If there is no migration concern, write "No migration impact — additive change."

## References

- Issue: #NNN
- PR: #NNN
- Prior art: [link to blog post, paper, or other project's docs]
- Related design docs: [NNNN](NNNN-feature-name.md)
