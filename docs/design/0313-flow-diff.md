# Design Doc: Flow-Diff (`impact --check flow-diff`)

> **Status:** Accepted
> **Date:** 2026-07-18
> **Author:** Wolfvin (BOS) / Claude Code
> **Related issues:** #313
> **Composes:** #309 (flow membership), #311 (intra-flow subgraph), #297 (edge diff)

---

## Problem

Edge-diff (#297) can say "200 edges changed between these two snapshots" — true
but not actionable. Named-flow (#309/#311) can collect the PAYMENT chain — but
only as of now. Neither answers the reviewer's actual question: **did the
PAYMENT flow's shape change in this PR?** e.g. `checkout -> validate` removed and
`checkout -> charge` added means validation was bypassed.

## Goal

`impact --check flow-diff --name X` reports the call-edges added/removed **within
one named flow** between two graph snapshots. Read-only, deterministic, no new
engine.

## Design

A pure compose of three existing pieces:

1. `tag_audit_engine.audit_tags()` → the flow's members `(file, symbol)`, from
   the agent's `@FLOW: X` tags **as of now**.
2. `diff_engine.diff_snapshots()` (#297) → `added_edges` / `removed_edges`
   between two snapshots, each labelled `{from, from_file, to, to_file}`.
3. Filter to **intra-flow** edges — both endpoints are members — matching the
   subgraph semantics of #311. Endpoint match keys on `(file, fn)`, with the
   owner stripped from an `Owner.fn` label.

Home is the `impact` umbrella: it already exposes `--name`, `--snapshot1`,
`--snapshot2`. Only a `_CHECKS` entry + a namespace branch are added. Command
count stays 12.

### Membership "as of now" vs edges "between snapshots"

Flow membership comes from the current tags; edge changes come from two
snapshots. This is exactly the "compare a pre-PR snapshot against the working
tree" use case. A function that was in the flow at snapshot A but is untagged
now is not a member now, so its edges are not reported — an accepted, documented
consequence, not a bug.

## Non-goals

- **Intra-flow only.** An edge from a member to a non-member (the flow calling
  out) is not reported unless that callee is also tagged. This keeps the signal
  to the flow's own wiring and avoids stdlib/utility noise — consistent with
  #311. A member→member edge is what "the flow's shape" means here.
- **No git-ref diffing.** Uses snapshot ids (like `impact --check diff`), not
  git refs.
- **No writing / no auto-tagging** — unchanged from #305/#309.

## Testing

Pure-unit for the compose (`_fn_of` owner-strip, `_intra_flow` keeps
member↔member and drops edges leaving the flow, owner-qualified label match),
plus `execute` with the two dependencies stubbed: the validation-bypass case
(checkout→validate removed, checkout→charge added), unchanged flow, unknown
flow → available list, missing `--name` → error, and an edge leaving the flow
ignored. `diff_snapshots` itself is covered by #297 and not re-tested here.
Verified end-to-end on a real two-snapshot demo.
