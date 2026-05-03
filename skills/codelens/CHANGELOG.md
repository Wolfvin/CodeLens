# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.1.0] — 2026-05-03

### Added

- **Workspace Auto-Detect**: The `workspace` argument is now optional for ALL commands. Fallback chain: current directory → parent directories → source files → last workspace cache → cwd
- **Python Parser**: Full tree-sitter Python parsing for function declarations, class methods, and function calls
- **`.codelens` directory exclusion**: Scanner now skips `.codelens/` directory during file discovery
- **SCSS/Less/Sass support**: Preprocessor CSS files are now discovered and parsed
- **Vue SFC parser**: Single-file component parser for Vue.js
- **Svelte parser**: Component parser for Svelte
- **Tailwind CSS detector**: Analyzes Tailwind utility class usage
- **TSX/JSX parser**: React component parser with className tracking
- **Open-source standards**: README.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, .gitignore, pyproject.toml
- **Comprehensive test suite**: Unit tests for all parsers and core engines

### Changed

- `codelens.py` now supports optional `workspace` argument with auto-detection
- Scan command supports `--incremental` flag for faster re-scans
- Watch mode now uses incremental scanning for file changes
- CLI version bumped from v4 to v5
- Total commands: 36 → 39
- Total engines: 23
- Total parsers: 9

## [5.0.0] — 2026-05-01

### Added

- **`vuln-scan`** — Dependency vulnerability scanning (npm audit, cargo audit, pip-audit, govulncheck + built-in CVE database with 35+ entries)
- **`perf-hint`** — Performance anti-pattern detection (N+1 queries, sync blocking, memory leaks, expensive renders, large bundles, inefficient iteration, unoptimized images, cache misses)
- **`css-deep`** — Deep CSS analysis (unused CSS variables, orphan @keyframes, specificity wars, duplicate properties, unused @media, z-index abuse)
- **Priority system**: Tools now have explicit priority weights (P0 > P1 > P2 > P3)
- **State prerequisites**: Explicit init→scan→tools ordering documented
- **Context-aware hints**: Auto-init if registry missing, re-scan if stale (>24h)
- **Colloquial triggers**: Non-technical phrases mapped to tools
- **Negative triggers**: When NOT to activate CodeLens
- **Default fallback chains**: Vague requests get default tool chains
- **SKILL-QUICK.md**: Concise quick-reference for fast AI consumption

### Changed

- CLI version: v4 → v5
- Total commands: 36 → 39
- Total engines: 23
- Total parsers: 9

## [4.0.1] — 2026-05-01

### Added

- Expanded `skill.json` description with explicit trigger phrases
- Added 6-category trigger rules to SKILL.md frontmatter
- Added Auto-Trigger Map section with 7 sub-tables
- Added 5 new scenario flows (Pre-Deploy, Onboarding, Feature Development, Performance, Code Review)
- Updated `agent-integration.md` with Section 0: Auto-Activation & Trigger Guide

## [4.0.0] — 2026-05-01

### Added

- **`secrets`** (P0) — Hardcoded secret detection
- **`entrypoints`** (P0) — Execution entry point mapping
- **`api-map`** (P1) — REST/GraphQL/gRPC route→handler mapping
- **`state-map`** (P1) — Global state management tracking
- **`env-check`** (P1) — Environment variable auditing
- **`debug-leak`** (P2) — Debug code leak detection
- **`complexity`** (P2) — Cyclomatic/cognitive complexity scoring
- **`regex-audit`** (P3) — ReDoS-vulnerable regex auditing
- **`a11y`** (P3) — Accessibility auditing (WCAG 2.1)

### Fixed

- Python file discovery now works (was missing .py handling)
- Top-level error handling added (clean JSON errors instead of tracebacks)
- Side-effect argparse bug fixed (name as optional --name flag)
- Outline positional arg consistency fixed

## [3.0.0] — 2026-04-30

### Added

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

## [2.0.0] — 2026-04-30

### Added

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
- Tree-sitter powered AST parsing
- 9 tree-sitter parsers
- Framework auto-detection
- Incremental scanning

## [1.0.0] — 2026-04-30

### Added

- `init`, `scan`, `query`, `list`, `detect`, `watch` commands
- Frontend registry (classes + ids)
- Backend registry (nodes + edges)
- Status tracking (active, dead, collision, duplicate_ref, duplicate_define)
- HTML, CSS, JS, Rust basic regex parsers
