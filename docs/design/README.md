# Design Documents

This directory holds **design docs** for CodeLens features. A design doc
captures WHY a feature exists and WHAT trade-offs were considered — it is the
record of decisions, not a tutorial.

## When is a design doc required?

A PR that adds a new feature to CodeLens MUST include a design doc. The CI
check in `.github/workflows/require-design-doc.yml` enforces this.

A PR is "feature-class" if it adds any new file under:

- `scripts/commands/` (new CLI command)
- `scripts/parsers/` (new language parser)
- `scripts/*_engine.py` (new analysis engine — top-level files only)
- `scripts/mcp_hooks/` (new MCP hook)

Bug fixes, refactors, dependency bumps, and pure docs changes are exempt. If
your PR is feature-class but the change is genuinely too small for a full
design doc (e.g., adding a single flag to an existing command), apply the
`skip-design-doc` label and explain why in the PR description.

## How to use the template

1. Copy `template.md` to `<feature-name>.md` (kebab-case, e.g.
   `cross-file-taint.md`).
2. Fill in every section. If a section does not apply, write "N/A — <reason>"
   rather than deleting it.
3. Link the design doc from your PR description.
4. Also create a corresponding implementation plan in
   [`../plans/`](../plans/) — the CI check requires both.
5. After the PR merges, update the `Findings` section with a 1-paragraph
   retrospective. Do NOT delete the design doc.

## Existing design docs

| Doc | Feature | Issue | PR | Status |
|---|---|---|---|---|
| [`taint-engine.md`](./taint-engine.md) | Taint analysis engine (cross-file unification, `ast_taint_engine.analyze_workspace`) | #49 | #140 | Accepted |
| [`mcp-server.md`](./mcp-server.md) | MCP server architecture (JSON-RPC over stdio, 61 tools) | — | — | Backfill |
| [`plugin-system.md`](./plugin-system.md) | Plugin system (4 types: rule_pack, engine, formatter, command) | — | — | Backfill |
| [`graph-model.md`](./graph-model.md) | SQLite graph model (`graph_nodes` + `graph_edges` schema) | — | — | Backfill |

When you add a new design doc, add a row to this table.
