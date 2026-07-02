# Design Doc — <Feature Name>

> **Status:** Draft | Proposed | Accepted | Superseded by [#](./<other>.md)
> **Author:** <GitHub handle>
> **Created:** YYYY-MM-DD
> **Related issues:** #<N>
> **Related PRs:** #<N>
> **Implementation plan:** [`docs/plans/<feature>.md`](../plans/<feature>.md)

<!--
This template is part of the CodeLens design doc convention (issue #67 Phase 1).
Copy this file to `docs/design/<feature>.md` and fill in the sections below.

A design doc is REQUIRED for any PR that adds a new feature to CodeLens.
The CI check in `.github/workflows/require-design-doc.yml` enforces this.
PRs that are pure bug fixes, refactors, or chores are exempt (see CONTRIBUTING.md).

A design doc captures WHY a feature is being built and WHAT trade-offs were
considered — it is NOT a tutorial or user-facing doc. Once the feature ships,
the design doc stays as a historical record of decisions.
-->

## Problem

Describe the concrete problem this feature solves. Answer:

- Who is affected? (which user persona: CLI user, MCP client, CI pipeline, plugin author)
- What can they NOT do today, or what breaks today?
- Why is solving this NOW worth the maintenance cost over the next 2 years?

Include real examples (commands that fail, errors users see, workflows that are
awkward). Link issues, discussions, or external references that document the pain.

If you cannot write 3+ sentences here, the feature is probably too small to
warrant a design doc — consider folding it into an existing doc or skipping
with the `skip-design-doc` label.

## Goal

State the outcome in 1-3 measurable sentences. A reviewer should be able to
read this section alone and tell whether the PR delivered the feature.

Goals should be testable. Bad: "Make scan faster." Good: "Reduce p95 scan time
on a 10k-file Python repo from 8s to <3s on the same hardware."

### Non-goals

List explicitly what this feature will NOT do. Non-goals prevent scope creep
during review and during future maintenance. If a reviewer asks "what about
X?" and X is in non-goals, the answer is "out of scope, future work."

## Changes

Describe the proposed change at the architecture level. Answer:

### Surface area

- New CLI commands (and their `commands/<name>.py` file)
- New MCP tools (and where in `scripts/mcp_server.py` they are registered)
- New engines (and the `scripts/<name>_engine.py` file)
- New parsers (and the `scripts/parsers/<name>_parser.py` file + fallback)
- New config keys or registry schema changes
- New dependencies (and whether they are required or optional)

### Data flow

How does data flow through the new code? Trace from user input (CLI arg / MCP
JSON-RPC request) through to the engine layer and back to the output formatter.
Call out any new tables, files, or persistent state.

### Touch points

Which existing files are modified? For each, briefly describe what changes and
why. Group by concern (engine layer, command layer, formatter layer, tests).

## Trade-offs

List the alternatives you considered and why you rejected them. This section
exists so future maintainers (including future-you) do not re-litigate the
decision without new information. Each alternative should include:

- **Option A: <name>** — short description
  - Pros: ...
  - Cons: ...
  - Why rejected: ...

At least one alternative MUST be listed. If you genuinely cannot think of one,
say "Considered: do nothing — rejected because <concrete cost of inaction>."

## Open questions

Anything you have NOT resolved at the time of writing. Each question should be
answerable by a single reviewer comment. If everything is resolved, write
"None — ready for review."

Format:
- Q1: Should we support X? (lean: yes, but want reviewer input on Y)
- Q2: How should we name Z? (candidates: `foo`, `bar`, `baz`)

## Findings (post-implementation)

Optional section, filled in during or after implementation. Capture:

- Surprises discovered while building
- Deviations from this design doc (and why)
- Follow-up work that should be tracked in new issues

This section turns the design doc from a planning artifact into a historical
record. Future workers reading this doc should be able to understand not just
what was planned but what actually happened.
