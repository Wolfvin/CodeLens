# Taint Analysis Engine Audit (Issue #49 Phase 1)

> **Status**: Phase 1 — Consolidation complete
> **Date**: 2026-07-01
> **Author**: Worker (issue #49)

## Overview

CodeLens v8.2 had **4 overlapping taint/dataflow engines**. This document
audits each engine's behavior, coverage, and consolidation status.

## Engine Inventory (pre-consolidation)

### 1. `ast_taint_engine.py` (3,755 LOC) — v1, AST-based

**Status**: Primary engine (default for `taint` command)

**Capabilities**:
- AST-level traversal via tree-sitter (Python, JavaScript, TypeScript, TSX)
- Control Flow Graph (CFG) with basic blocks, branches, and joins
- Path-sensitive taint propagation (tracks if/else branches separately)
- Scope-aware (function boundaries, closures, class methods)
- Inter-procedural **within a single file** (tracks taint through function calls)
- Sanitizer-aware (recognizes when taint is removed)
- Full taint path rendering (e.g. `request.args -> user_input -> query -> cursor.execute`)
- Confidence scoring (0.95+ direct, 0.80+ through calls, 0.60+ partial sanitizer, 0.40+ indirect)

**Entry point**: `analyze_workspace(workspace, rules_dir=None, language=None, cross_file=False)`

**Used by**: `taint` command (default), `callgraph_engine.py` (for taint-enhanced call graph)

---

### 2. `crossfile_taint_engine.py` (946 LOC) — v2, Cross-file

**Status**: Consolidated into `ast_taint_engine` (Phase 1)
- `crossfile_taint_engine.py` is now a **thin compat wrapper** that
  delegates to `ast_taint_engine.analyze_workspace(cross_file=True)`.

**Original capabilities** (now in `ast_taint_engine`):
- Builds project-wide call graph (function -> function across files)
- Propagates taint across file boundaries
- Lazy CFG construction (only for files with potential sources/sinks)
- Call graph pruning (only follows edges from tainted functions)
- 30-second time budget for whole-project analysis

**Entry point**: `analyze_cross_file_taint(workspace, language=None, rules_dir=None)`
- still available as a compat function, delegates to `ast_taint_engine`.

**Used by**: `taint --cross-file` command, `check` command (CI quality gate)

---

### 3. `dataflow_engine.py` (1,097 LOC) — v3, Source->Sink

**Status**: Independent engine (not consolidated -- different purpose)

**Capabilities**:
- Source/sink/sanitizer/propagator model
- Answers: "Does user input ever reach a DB query without sanitization?"
- Tracks data flow (not call chains)
- Pattern-based source/sink detection (regex)

**Entry point**: `trace_dataflow(workspace, ...)`

**Used by**: `dataflow` command, `analyze` command, `summary` command

**Note**: `dataflow_engine` is a **different tool** from the taint engines.
It focuses on data flow paths (source -> propagator -> sink), while the
taint engines focus on vulnerability rule matching with taint propagation.
They are complementary, not overlapping. No consolidation needed.

---

### 4. `semantic_engine.py` (428 LOC) — Regex-based (legacy)

**Status**: **Deprecated** (Phase 1) -- kept as fallback with deprecation warning

**Original capabilities**:
- Regex-based taint analysis (no AST)
- YAML rule loading
- Inter-procedural within a single file (regex pattern matching)
- Confidence levels: high/medium/low

**Entry point**: `analyze_workspace(workspace, language=None)`
- still available, emits `DeprecationWarning` to stderr.

**Used by**: `taint --no-ast` (explicit fallback), `self-analyze`, `rule-test`

**Deprecation path**:
- v8.3 (this PR): deprecation warning printed to stderr on every use
- v8.4: `taint --no-ast` will use `ast_taint_engine` with regex fallback mode
  (no tree-sitter) instead of `semantic_engine`
- v9.0: `semantic_engine.py` removed entirely

**Migration**: Use `ast_taint_engine` (default) or `ast_taint_engine` with
`cross_file=True` for cross-file analysis. The AST engine provides strictly
better coverage with fewer false positives.

---

## Consolidation Summary (Phase 1)

| Action | Status |
|--------|--------|
| Audit 4 engines, document behavior + coverage | Done (this document) |
| Deprecate `semantic_engine.py` with warning | DeprecationWarning added |
| Consolidate `crossfile_taint_engine.py` into `ast_taint_engine.py` | Cross-file mode added to `ast_taint_engine`; `crossfile_taint_engine.py` is now a compat wrapper |

## Unified API

After Phase 1, the taint analysis stack has a **single entry point**:

```python
from ast_taint_engine import analyze_workspace

# Intra-file analysis (default -- same as v8.2)
result = analyze_workspace(workspace, language="python")

# Cross-file analysis (replaces crossfile_taint_engine.analyze_cross_file_taint)
result = analyze_workspace(workspace, language="python", cross_file=True)
```

The `taint` command (`scripts/commands/taint.py`) now routes all requests
through `ast_taint_engine.analyze_workspace()` with the `cross_file`
parameter. The old `--cross-file` flag sets `cross_file=True`; the old
`--no-ast` flag falls back to `semantic_engine` (with deprecation warning).

## Next Phases (not in this PR)

- **Phase 2**: Unified cross-file engine reaching 5+ hops (currently 1 hop)
- **Phase 3**: Signature extraction for performance (2x speedup)
- **Phase 4**: Persistence / stored injection modeling
- **Phase 5**: Library method approximation system
- **Phase 6**: Debug-trace tool (`codelens debug-rule`)
- **Phase 7**: LLM validator (optional, 50%+ FP reduction)
