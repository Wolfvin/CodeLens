# Design Doc: Get Function Source (`context --check source`)

> **Status:** Accepted
> **Date:** 2026-07-18
> **Author:** Wolfvin (BOS) / Claude Code
> **Related issues:** #316
> **North-star:** CodeLens replaces the agent's grep + Read navigation (#279 agent-ergonomics)

---

## Problem

Found by dogfooding CodeLens on itself. The most common thing the agent still
does manually is **Read an entire file just to see one function's body**.
Nothing in CodeLens returns a function's source:

- `context --check outline --file F` → `{name, line}` only, even `--detail full`.
- `context --check context --name X` → metadata (callers, advice), no body.

So the agent reads the whole file. That is exactly what CodeLens exists to
replace.

## Goal

`context --check source --name X` returns just function X's source + its
`file:start-end` range. Read-only, deterministic. Command count stays 12.

## Design

Read-only compose, no new engine:

1. **Locate X.** With `--file F`, outline F and match by name (no graph needed).
   Otherwise resolve via `graph_model.find_nodes_by_name` (the graph populated
   by a prior scan).
2. **Bound it.** The function runs from its start line to the line before the
   next declaration in the file (`outline_engine` functions + classes), or EOF
   for the last one. Trailing blank lines are trimmed.
3. **Slice.** Return those lines.

### Why a next-declaration heuristic, not the parser's end line

`outline_engine` does not expose a node end line, and reaching into the
tree-sitter layer to add one is a parser change (backend) out of scope for a
read-only command. The next-declaration boundary is exact for the common case
(a function followed by another declaration) and never guesses beyond the
file's own structure. A more precise end line via the parser is a possible
follow-up (a worker task, since it touches the parser).

## Non-goals

- **No parser change.** Boundary is heuristic on purpose (see above).
- **No cross-file dedup.** A name defined in N files returns N matches; the
  agent narrows with `--file`.
- **Not for module-level code.** It returns a *function's* source; free code
  between declarations may be included up to the next declaration — documented,
  acceptable for "show me this function".

## Agent-ergonomics note

An unscanned workspace with no `--file` returns an explicit
`error_type: "no_graph"` message — never a silent-empty result. This is the
same discipline as #315: the agent must always tell an error from an empty.

## Testing

`--file` mode (no graph) fixtures: exact single-function slice, boundary stops
before the next declaration (no bleed), last function to EOF, trailing-blank
trim, unknown name → not-found, missing `--name` → error. Graph mode: same-name
in two files → two matches. No-graph-and-no-file → explicit error, not empty.
Verified by dogfooding: retrieved `_fn_of`'s 3-line body from a 105-line file
without reading the file.
