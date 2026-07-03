# Design Doc: YAML Node-Type Registry (Issue #43 Approach 2 Stepping Stone)

> **Status:** Accepted
> **Date:** 2026-07-03
> **Author:** Wolfvin
> **Related issues:** #43
> **Related PRs:** (this PR)

---

## Problem

CodeLens has 7 tree-sitter parsers (Python, Rust, JS, TS, TSX, CSS, HTML).
Each parser hardcodes tree-sitter node-type strings like
`"function_definition"`, `"call_expression"`, `"import_statement"` directly
in Python code. Adding a new language means writing a ~250 LOC Python module
that hardcodes these strings — there's no config-driven path.

Issue #43 proposed three approaches to make node discovery more declarative.
The full `.scm` query-file migration (Approach 1) was deferred pending
trigger conditions. This design doc covers **Approach 2 — the YAML node-type
registry** — which the issue explicitly recommends as a low-risk stepping
stone: "DO set up the YAML node-type registry as a low-risk stepping stone."

## Goal

Externalise hardcoded tree-sitter node-type lookups to a YAML config so
that adding a language's node-type mapping requires editing YAML, not
Python. Existing parsers continue to work unchanged — the YAML registry
is an additive new path that future parsers and the eventual `.scm`
engine can use.

## Changes

### Architecture / Data Model

A new `scripts/languages/` package holds:

```
scripts/languages/
├── __init__.py         Re-exports public API
├── node_types.yaml     Language → category → [node types] config
└── loader.py           Cached YAML loader + public API
```

The YAML maps **semantic categories** (stable across languages) to
**concrete tree-sitter node types** (language-specific):

```yaml
python:
  function_def: [function_definition]
  call: [call]
  import: [import_statement]

rust:
  function_def: [function_item]
  call: [call_expression]
  import: [use_declaration]
```

The category names (`function_def`, `call`, `import`, `class_def`) are
the **same across all languages**. This is the design property that the
future `.scm` engine (issue #43 Phase B) will exploit: a `.scm` query
file for one language maps 1:1 to a category here.

### New Files

- `scripts/languages/__init__.py` — package marker, re-exports public API
- `scripts/languages/node_types.yaml` — config for all 7 tree-sitter languages
- `scripts/languages/loader.py` — `get_node_types()`, `get_language_config()`,
  `get_supported_languages()`, `NodeTypeError`, cached frozenset results
- `tests/test_node_types.py` — 32 tests (28 pass, 4 skip without tree-sitter)
- `docs/design/0005-node-type-registry.md` — this design doc

### Modified Files

- `scripts/base_parser.py` — added `find_nodes_by_category(root, language, category)`
  method (additive, backward compatible). Existing `find_nodes_by_type` and
  `find_nodes_by_types` are unchanged.

### CLI / MCP Surface

No new command. No new MCP tool. This is an internal infrastructure change.

### Tests

- `tests/test_node_types.py` — covers:
  - `get_node_types` for all 7 languages (returns correct frozensets)
  - `get_language_config` (full category mapping, returns a copy)
  - `get_supported_languages` (lists all 7, sorted)
  - YAML config validity (no empty lists, no duplicates, all strings non-empty)
  - Cache behaviour (frozenset identity, invalidation)
  - Error handling (unknown language, unknown category, missing PyYAML)
  - `BaseParser.find_nodes_by_category` integration (skipped when tree-sitter missing)

## Trade-offs

### Alternative A: Full `.scm` query-file migration (Approach 1)

- **Pros:** Replaces ~250 LOC Python per language with ~50 LOC `.scm`.
  One generic engine serves all languages. Portable to a future Rust core.
- **Cons:** 2-3 week migration effort. Only replaces Layer 1 (node
  discovery) — Layer 2 (framework semantics) and Layer 3 (edge resolver)
  stay in Python. Issue #43 says "Do not migrate existing parsers now"
  until trigger conditions are met.
- **Why rejected (for now):** Trigger conditions were partially met (P0
  bugs #31/#32 closed, Phase 2 #22 clarified as deferred), but the issue
  recommends the YAML registry as a lower-risk stepping stone first. The
  `.scm` pilot is documented as Phase B (next step) in this design doc.

### Alternative B: Hardcode node types in Python dicts (status quo)

- **Pros:** Zero new files, zero new abstractions.
- **Cons:** Adding a language requires editing Python. No config-driven
  path for future `.scm` migration. Node-type strings scattered across
  7 parser files with no single source of truth.
- **Why rejected:** Issue #43 explicitly recommends the YAML registry as
  a "DO" action. The status quo doesn't prepare the ground for `.scm`
  migration.

### Chosen approach: YAML node-type registry (Approach 2)

- **Why:** Lowest risk (zero migration, purely additive). Creates the
  category abstraction that `.scm` will reuse. Adding a language = adding
  YAML lines, not Python. The YAML is language-agnostic (reusable by a
  future Rust core). Aligns with CodeLens's existing config patterns
  (`plugin.yaml`, `hooks.json`, `codelens.config.json`).

## Open Questions

- [ ] Q1: Should existing parsers be refactored to use `find_nodes_by_category`
  instead of `find_nodes_by_type`? (Owner: BOS, decide after this PR merges)
  — This PR deliberately does NOT refactor existing parsers. The new method
  is available for new parsers and the `.scm` pilot. Refactoring existing
  parsers is Priority 6 in issue #43 ("2-3 weeks, Low ROI").
- [ ] Q2: Should the YAML registry be extensible via plugins (like
  `plugin.yaml`)? (Owner: BOS) — Out of scope for this PR. The plugin
  angle is mentioned in issue #43 as a "future direction, not part of
  this proposal."

## Migration / Rollout

No migration impact — additive change. Existing parsers continue to use
`find_nodes_by_type` / `find_nodes_by_types` unchanged. The new
`find_nodes_by_category` method is available for opt-in use.

## Phase B: `.scm` Pilot (Next Step)

This PR implements Phase A (YAML registry). Phase B — the Rust `.scm`
pilot described in issue #43 — is the recommended next step:

1. Write `scripts/parsers/scm/rust.scm` covering function/method defs,
   struct/enum/impl blocks, call sites, `use` imports, `#[attribute]`.
2. Build `scripts/parsers/scm_engine.py` — a generic engine that loads
   `.scm` files, executes tree-sitter queries, returns nodes/edges in
   the same shape as existing parsers.
3. Run both parsers (legacy + scm) on Rust test fixtures. Assert 100%
   parity on captured nodes/edges.
4. Wire `scm_engine` into `scan.py` for Rust only, behind `--use-scm rust`.
5. If bake is clean: migrate Python, JS, TS, HTML, CSS one language per PR.
6. **Never migrate** Vue/Svelte/Blade — they have heavy Layer 2 framework
   logic that `.scm` cannot express.

Phase B requires tree-sitter's `Query` API which is not available in all
environments. The YAML registry (Phase A) works without tree-sitter at
runtime — it's pure config.

## References

- Issue: #43
- Related issues: #46 (Semgrep-compat rule engine — closed, dependency met),
  #22 (Phase 2 Rust core — closed as deferred)
- Prior art: [ast-grep](https://ast-grep.github.io/),
  [tree-sitter query syntax](https://tree-sitter.github.io/tree-sitter/using-parsers#query-syntax),
  [Semgrep rule syntax](https://semgrep.dev/docs/writing-rules/overview/)
- Related design docs: [0001-taint-engine](0001-taint-engine.md)
