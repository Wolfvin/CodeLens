# CodeLens Changelog

> **For the latest changelog, see [CHANGELOG.md](../CHANGELOG.md) in the skill root.**

## v5.8.0 — 2026-06-11

### Fixed

- **CRITICAL: Version mismatch in pyproject.toml**: Version was 5.1.0 while utils.py and skill.json said 5.7.0. Now aligned to 5.8.0.
- **CRITICAL: Broken test imports**: 5 test files imported fallback parsers from the old monolithic `codelens.py`. Updated to import from `parsers.fallback_*` modules.
- **CRITICAL: Broken pip entry point**: Removed invalid `codelens = "codelens:main"` from `pyproject.toml`.
- **CRITICAL: Non-standard build backend**: Changed to standard `setuptools.build_meta`.
- **HIGH: Frontend deletion cleanup was a no-op**: Deleted files' frontend entries now properly cleaned.
- **HIGH: CSS parser `::` triggered SCSS fallback on standard CSS**: Fixed pseudo-element detection heuristic.
- **HIGH: Class collision detection was broken**: HTML classes now get `defined_in_html` field.
- **HIGH: GrammarLoader was not thread-safe**: Added `threading.Lock` to singleton and dict operations.
- **HIGH: Watch command race condition lost file changes**: Changes during rescan no longer lost.
- **HIGH: Dead code in incremental edge processing**: Removed unreachable code block.
- **MEDIUM: O(n²) BFS in impact_engine**: Replaced with `collections.deque` for O(1) operations.
- **MEDIUM: O(n) path.index() per back-edge in circular_engine**: Added `path_index` dict for O(1) lookup.
- **MEDIUM: Search engine recompiled regex per file**: Now compiled once before `os.walk`.
- **MEDIUM: Dead-code command used wrong field name**: Now correctly iterates over all category lists.
- **MEDIUM: state-map markdown formatter crashed on string actions**: Now handles both dicts and strings.
- **Command count updated**: pyproject.toml description now says "41 commands" (was "39").

## v5.7.0 — 2026-06-11

### Added

- **Shared DEFAULT_IGNORE_DIRS across 22 engines**: All engine files now import from `utils.py`. Added `.nuxt` to the shared set. Eliminated ~132 lines of duplicated configuration.

### Changed

- **Query command status consistency**: All 4 found-code-paths now return `status: "ok"`.
- **Comprehensive logging across 15 files**: Replaced 26 bare `except ... pass` blocks with `logger.debug()`/`logger.warning()` calls.

## v5.6.0 — 2026-06-11

### Added

- **TSX backend extraction**: TSX files now parsed with BOTH frontend AND backend fallback parsers (6.2x more backend nodes).
- **Shared utils module** (`scripts/utils.py`): Centralized shared utilities. Eliminates 290+ lines of duplicated code.
- **Proper logging**: Replaced 56 `except Exception: pass` blocks with proper logging.
- **Fuzzy file path lookup**: `context` and `query` now match partial paths.
- **Auto-incremental scan with registry counts**: Response now includes actual counts instead of zeros.
- **Handbook registry freshness check**: Handbook skips re-scan if registry is less than 5 minutes old.

## v5.5.0 — 2026-06-11

### Added

- **Auto-incremental scan**: Scan automatically uses incremental mode when registry exists.
- **oRPC route detection**: API-map now detects oRPC-style routers.
- **tRPC v10+ detection**: Improved tRPC extraction.
- **Context/Query by file path**: New file-path lookup support.
- **bun.lock support**: Vulnerability scanner now parses Bun's lock format.

### Changed

- **Health score calibration**: Deep nesting reports per-block instead of per-line. Typical React project health: 90 (was 25).

### Fixed

- **Secrets markdown truncation**: Severity "high" was truncated in markdown output. Now displays correctly.

## v5.4.0 — 2026-06-11

### Added

- **True incremental scan**: Partial registry merge for significantly faster re-scans.
- **Complete markdown formatters**: All 41 commands now have specific markdown formatters (was 15/41).
- **Score-based ask routing**: Natural language query router now uses weighted scoring.
- **8 new ask patterns**: CSS issues, accessibility, regex, etc.
- **3 new semantic convention detectors**: CSS framework, Authentication, Deployment.
- **Better error messages**: Command-specific error suggestions with `_suggest_fix()`.
- **Consistent status field**: All commands now return `status: "ok"` or `status: "error"`.

### Changed

- `codelens.py` monolith reduced from 3504 → 307 lines (modular architecture).

## v5.1.0 — 2026-05-03

### Added

- **Workspace Auto-Detect**: The `workspace` argument is now optional for ALL commands.
- **Python Parser**: Full tree-sitter Python parsing.
- **`.codelens` directory exclusion**: Scanner now skips `.codelens/` during file discovery.
- **SCSS/Less/Sass support**: Preprocessor CSS files now discovered and parsed.
- **Vue SFC parser**: Single-file component parser for Vue.js.
- **Svelte parser**: Component parser for Svelte.
- **Tailwind CSS detector**: Analyzes Tailwind utility class usage.
- **TSX/JSX parser**: React component parser with className tracking.
- **Open-source standards**: README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, etc.
- **Comprehensive test suite**: Unit tests for all parsers and core engines.

## v5.0.0 — 2026-05-01

### New Tools (3)

- **`vuln-scan`** — Dependency vulnerability scanning (npm audit, cargo audit, pip-audit, govulncheck + built-in CVE database with 35+ entries)
- **`perf-hint`** — Performance anti-pattern detection (N+1 queries, sync blocking, memory leaks, expensive renders, large bundles, inefficient iteration, unoptimized images, cache misses)
- **`css-deep`** — Deep CSS analysis (unused CSS variables, orphan @keyframes, specificity wars, duplicate properties, unused @media, z-index abuse)

### Auto-Trigger Enhancements

- **Priority system**: Tools now have explicit priority weights (P0 > P1 > P2 > P3) so AI knows which to run first when multiple match
- **State prerequisites**: Explicit init→scan→tools ordering documented
- **Context-aware hints**: Auto-init if registry missing, re-scan if stale (>24h)
- **Colloquial triggers**: Non-technical phrases mapped to tools ("kok lama ya" → perf chain, "bersihkan" → debug-leak+dead-code)
- **Negative triggers**: When NOT to activate CodeLens (PDF generation, image generation, web search, etc.)
- **Default fallback chains**: Vague requests get default tool chains (general→smell+dead-code+secrets, security→secrets+dataflow+env-check, quality→complexity+debug-leak+a11y)

### Documentation Enhancements

- **SKILL-QUICK.md**: Concise 181-line quick-reference for fast AI consumption (vs full SKILL.md for complete reference)
- **changelog.md**: This file — separated changelog from SKILL.md for cleaner structure
- **Language unification**: SKILL-QUICK.md in English for global AI compatibility
- **Error recovery flows**: 8 failure→recovery pairs documented
- **Parallel execution hints**: 5 parallel-safe groups + 5 sequential-required chains
- **Edge case flows**: Empty workspace, no git, monorepo, no package.json

### Integration Enhancements

- **Streaming/real-time integration**: Watch mode + webhook callback pattern documented in agent-integration.md
- **REST API wrapper**: Flask/FastAPI wrapper pattern for HTTP-based agent integration
- **Keyword Detection Matrix**: Bilingual (EN+ID) keyword → tool mapping

### Version Bumps

- CLI version: v4 → v5
- Total commands: 36 → 39
- Total engines: 23
- Total parsers: 9

---

## v4.0.1 — 2026-05-01

### Auto-Trigger Enhancements

- Expanded `skill.json` description with explicit trigger phrases
- Added 6-category trigger rules to SKILL.md frontmatter (Reference, Scan, Security, Understanding, Quality, Refactoring)
- Added Auto-Trigger Map section with 7 sub-tables
- Added 5 new scenario flows (Pre-Deploy, Onboarding, Feature Development, Performance, Code Review)
- Updated `agent-integration.md` with Section 0: Auto-Activation & Trigger Guide including Keyword Detection Matrix

---

## v4.0.0 — 2026-05-01

### New Tools (9)

- **`secrets`** (P0) — Hardcoded secret detection (API keys, passwords, tokens, connection strings, private keys)
- **`entrypoints`** (P0) — Execution entry point mapping
- **`api-map`** (P1) — REST/GraphQL/gRPC route→handler mapping
- **`state-map`** (P1) — Global state management tracking
- **`env-check`** (P1) — Environment variable auditing
- **`debug-leak`** (P2) — Debug code leak detection
- **`complexity`** (P2) — Cyclomatic/cognitive complexity scoring
- **`regex-audit`** (P3) — ReDoS-vulnerable regex auditing
- **`a11y`** (P3) — Accessibility auditing (WCAG 2.1)

### Bug Fixes

- Python file discovery now works (was missing .py handling in discover_files)
- Top-level error handling added (clean JSON errors instead of tracebacks)
- Side-effect argparse bug fixed (name as optional --name flag)
- Outline positional arg consistency fixed (workspace first, like all other commands)

---

## v3.0.0 — 2026-04-30

### New Tools (10)

- **`dataflow`** (P0) — Data flow analysis (source→sink, taint detection)
- **`smell`** (P0) — Code smell detection (10 categories, health score)
- **`side-effect`** (P1) — Function side-effect analysis (pure vs impure)
- **`refactor-safe`** (P1) — Pre-flight rename/move safety check
- **`dead-code`** (P1) — Enhanced dead code detection
- **`stack-trace`** (P2) — Error propagation simulation
- **`test-map`** (P2) — Test coverage mapping
- **`config-drift`** (P2) — Dependency drift detection
- **`type-infer`** (P3) — Lightweight type inference
- **`ownership`** (P3) — Git blame code ownership analysis

---

## v2.0.0 — 2026-04-30

### New Tools (11)

- `search` — Code search across workspace
- `symbols` — Registry-based symbol search
- `trace` — Deep call chain tracing
- `impact` — Change impact analysis
- `outline` — File structure outline
- `missing-refs` — CSS/HTML mismatch detection
- `diff` — Registry snapshot comparison
- `circular` — Circular dependency detection
- `context` — Rich symbol context
- `dependents` — Module-level import tracking
- `validate` — Registry sanity check

### Core Features

- Tree-sitter powered AST parsing
- 9 tree-sitter parsers (HTML, CSS, JS, TS/TSX, Rust, Python, Vue, Svelte, SCSS)
- Framework auto-detection
- Incremental scanning
- JSON output for all commands

---

## v1.0.0 — 2026-04-30

### Initial Release

- `init`, `scan`, `query`, `list`, `detect`, `watch`
- Frontend registry (classes + ids)
- Backend registry (nodes + edges)
- Status tracking (active, dead, collision, duplicate_ref, duplicate_define)
