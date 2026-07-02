# Design Doc — Taint Analysis Engine

> **Status:** Accepted
> **Author:** Wolfvin
> **Created:** 2026-06-30 (backfilled 2026-07-02)
> **Related issues:** #49
> **Related PRs:** #140
> **Implementation plan:** (none — feature shipped before plan convention existed)

## Problem

CodeLens v1 shipped a taint analyzer (`semantic_engine.py`) that relied on
regex pattern matching over source code. This produced two classes of failure
that eroded user trust in `codelens taint` output:

1. **False positives** — string matches inside comments, docstrings, or
   unrelated identifiers were reported as taint flows. A user running
   `codelens taint` on a Flask codebase would see dozens of "SQL injection"
   findings where the only "evidence" was the word `query` appearing in a
   docstring near the word `request`.
2. **False negatives** — regex cannot track data flow through assignments,
   function calls, or branch conditions. A real SQL injection where
   `request.args["id"]` flows through three intermediate variables into
   `cursor.execute(...)` was missed entirely because no single regex matched
   the start-to-end pattern.

The taint analysis also operated per-file, so cross-file flows (a tainted
value returned by `auth.py:get_user_id()` and used in `db.py:run_query()`)
were invisible. Users had to manually trace calls between files to find
vulnerabilities that competing tools (Semgrep, CodeQL) reported automatically.

The cost of inaction: `codelens taint` would continue to be a tool users
distrusted, forcing them to run a second static analyzer alongside CodeLens
for security work — defeating the "one tool" value proposition.

## Goal

Provide AST-based, path-sensitive, inter-procedural taint analysis that
matches the precision of Semgrep for the four languages CodeLens already
parses with tree-sitter (Python, JavaScript, TypeScript, TSX), and unify
single-file and cross-file analysis under one entry point so callers do not
need to know which mode they are using.

### Non-goals

- Taint analysis for languages without a tree-sitter grammar in CodeLens
  (Rust, Go, Java, etc.). These still get the regex fallback via
  `semantic_engine.py` (deprecated but not yet removed).
- Whole-program analysis with pointer aliasing. We track value flow, not
  alias sets — `x = [tainted]; y = x[0]` is not recognized as tainted.
- Taint persistence across CodeLens sessions. Each `analyze_workspace` call
  rebuilds the CFG. (Tracked as future work in issue #49 Phase 2.)
- Library approximation (treat external call as sink/source based on
  heuristics). Tracked as future work in issue #49 Phase 3.

## Changes

### Surface area

- **New engine:** `scripts/ast_taint_engine.py` (~3,750 lines)
  - Public entry points: `analyze_workspace()`, `analyze_file()`,
    `is_available()`, `get_supported_languages()`
  - Class `ASTTaintAnalyzer` orchestrates CFG construction → taint
    propagation → sink checking → finding generation
  - Unified `cross_file=True` parameter on `analyze_workspace()` (PR #140)
- **Deprecated engine:** `scripts/semantic_engine.py` — still importable,
  emits a `DeprecationWarning` to stderr on every call. Slated for removal
  in v9.0.
- **Compat wrapper:** `scripts/crossfile_taint_engine.py` — still importable,
  `analyze_cross_file_taint()` now delegates to `ast_taint_engine.analyze_workspace(cross_file=True)`.
- **CLI command:** `codelens taint` — unchanged interface, internally
  dispatches to `ast_taint_engine` when tree-sitter is available, falls back
  to `semantic_engine` otherwise.
- **MCP tool:** `codelens_taint` — same dispatch logic as CLI.
- **No new dependencies.** tree-sitter was already a CodeLens dependency
  for parsing; this engine reuses the existing `grammar_loader.py` infrastructure.

### Data flow

```
codelens taint --workspace /path
       │
       ▼
commands/taint.py::execute(args)
       │
       ▼
ast_taint_engine.analyze_workspace(workspace, rules_dir, cross_file=True)
       │
       ├─ Phase 1: parse each file with tree-sitter → AST
       │            (uses grammar_loader._get_parser, cached per language)
       │
       ├─ Phase 2: build CFG per file
       │            CFGNode = basic block; edges = control flow
       │            Branches (if/else, try/except, for, while) become
       │            separate paths; joins merge taint state.
       │
       ├─ Phase 3: identify taint sources
       │            Built-in: request.args, request.form, request.json,
       │            os.environ, sys.argv, input(), process.argv, etc.
       │            Rule-supplied: from YAML rules (sources/sinks/sanitizers)
       │
       ├─ Phase 4: forward taint propagation through CFG
       │            Path-sensitive: each branch keeps its own taint set.
       │            Scope-aware: function boundaries contain taint unless
       │            the function returns tainted data.
       │            Inter-procedural (within file): calls to local functions
       │            propagate taint through arguments and return values.
       │            Inter-procedural (cross file, when cross_file=True):
       │            builds a CallGraph across the workspace, follows
       │            taint through call edges.
       │
       ├─ Phase 5: check taint arrival at sinks
       │            For each sink call (cursor.execute, eval, os.system,
       │            subprocess.call, etc.), check whether any argument
       │            carries taint. If yes, generate a finding.
       │
       └─ Phase 6: emit findings with taint paths
                    Each finding includes the full taint chain, e.g.:
                    "request.args → user_input → query → cursor.execute"
                    Confidence score (0.40-0.95) based on path complexity
                    and sanitizer presence.
```

### Touch points

- `scripts/ast_taint_engine.py` — new file (this is the engine itself).
- `scripts/crossfile_taint_engine.py` — modified in PR #140 to become a
  thin compat wrapper. Public API preserved.
- `scripts/semantic_engine.py` — modified to emit DeprecationWarning. Public
  API preserved.
- `scripts/commands/taint.py` — modified to dispatch to ast_taint_engine
  when available, fall back to semantic_engine otherwise.
- `tests/test_dataflow_engine.py`, `tests/test_hybrid_engine_core.py`,
  `tests/test_hybrid_engine.py`, `tests/test_hybrid_type_resolver.py` —
  updated to assert on the new entry point and the deprecation warning.
- `docs/taint-engine-audit.md` — new audit doc capturing the consolidation
  decision (referenced from CONTEXT.md).
- `CHANGELOG.md` — entry under v8.2.0 noting the consolidation.

## Trade-offs

- **Option A: Regex-only (do nothing)** — keep `semantic_engine.py` as the
  only taint engine.
  - Pros: zero new code, zero maintenance cost.
  - Cons: false positives erode user trust; false negatives leave real
    vulnerabilities unreported. CodeLens cannot compete with Semgrep/CodeQL
    on security work.
  - Why rejected: issue #49 was filed specifically because users were
    complaining about both classes of failure. Inaction guarantees the
    complaints continue.

- **Option B: Adopt Semgrep as a subprocess** — shell out to `semgrep`
  binary when `codelens taint` is invoked.
  - Pros: best-in-class analysis with zero implementation effort.
  - Cons: adds a runtime dependency on a 100MB+ binary; breaks the
    "single-Python-process" deployment story that the MCP server relies on;
    Semgrep's rule format is incompatible with CodeLens YAML rules, forcing
    users to maintain two rule sets.
  - Why rejected: deployment friction outweighs the implementation effort
    for our four target languages. The AST taint engine covers 80% of
    Semgrep's precision for our use case at 0% of the binary dependency cost.

- **Option C: Build AST taint engine in-house (chosen)** — implement CFG
  construction + path-sensitive propagation using the tree-sitter AST we
  already build for parsing.
  - Pros: no new dependencies; reuses existing parser infrastructure;
    gives full control over rule format and finding schema; unifies with
    the existing `Finding` dataclass used by other engines.
  - Cons: ~3,750 lines of new code to maintain; will not match Semgrep's
    precision on aliasing or pointer analysis; requires ongoing investment
    as new language constructs appear (e.g., Python match statements,
    TypeScript satisfies operator).
  - Why chosen: the maintenance cost is bounded (four languages, well-known
    CFG construction algorithm) and the integration cost with the rest of
    CodeLens (Finding schema, MCP tool, formatter) is zero. Option B's
    deployment friction is unbounded (Semgrep releases, binary size, rule
    format drift).

- **Option D: Cross-file analysis as a separate engine (rejected in PR #140)**
  — keep `crossfile_taint_engine.py` as a parallel engine that users opt
  into via a separate command.
  - Pros: clearer API surface; users can choose single-file or cross-file.
  - Cons: two commands to maintain, two code paths that diverge over time,
    users have to know which to use. The PR #140 consolidation specifically
    addressed this by making `cross_file=True` a parameter on the unified
    `analyze_workspace()` entry point.
  - Why rejected: violates DRY and forces users to understand an
    implementation detail (file boundary) that should be invisible.

## Open questions

None — design is implemented (PR #140 merged) and stable. Future work is
tracked in issue #49 Phases 2-4:

- Phase 2: persistence (cache CFG across sessions, invalidate on file change)
- Phase 3: library approximation (mark unresolvable calls as potential
  sources/sinks based on name heuristics)
- Phase 4: debug trace (emit step-by-step taint propagation log for rule
  authors debugging false positives)

## Findings (post-implementation)

PR #140 shipped Phase 1 (single-file + cross-file consolidation) on
2026-07-01. The consolidation removed ~600 lines of duplicated CFG code
from `crossfile_taint_engine.py` (now a 47-line compat wrapper). The
`semantic_engine` deprecation pathway is working as designed — three
downstream tests in `tests/test_dataflow_engine.py` were updated to assert
on the new entry point and the deprecation warning, and no other callers
of `semantic_engine` were found in the codebase.

One follow-up issue was filed during implementation: the `Finding` schema
used by `ast_taint_engine` includes a `taint_path` field that other engines
do not populate. This is a schema divergence that should be reconciled
when issue #52 (formatters expansion) lands — the unified `Finding`
dataclass from PR #139 will need to make `taint_path` optional rather than
omitted. Tracked as a note in `docs/taint-engine-audit.md`, no separate
issue yet.
