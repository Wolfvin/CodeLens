# Changelog

All notable changes to CodeLens are documented here.

## [5.1.0] — 2026-05-03

### Added
- Workspace auto-detect: `workspace` argument is now optional for all commands
- Python parser with tree-sitter for function declarations, class methods, and function calls
- `.codelens` directory exclusion during file discovery
- SCSS/Less/Sass preprocessor CSS support
- Vue SFC parser for single-file components
- Svelte component parser
- Tailwind CSS detector for utility class analysis
- TSX/JSX parser for React components with className tracking
- Open-source standards: CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md, pyproject.toml
- Comprehensive Python unit test suite for all parsers and core engines
- Standalone file watcher (`codelens-watch.py`) for auto-generating JSON outlines

### Changed
- CLI supports optional workspace argument with auto-detection fallback chain
- Scan command supports `--incremental` flag for faster re-scans
- Watch mode uses incremental scanning for file changes
- Version bumped from v4 to v5.1
- Total commands: 36 → 39
- Total engines: 23, total parsers: 9

## [5.0.0] — 2026-05-01

### Added
- `vuln-scan` — Dependency vulnerability scanning (npm audit, cargo audit, pip-audit, govulncheck + built-in CVE database)
- `perf-hint` — Performance anti-pattern detection (N+1 queries, sync blocking, memory leaks, expensive renders, large bundles)
- `css-deep` — Deep CSS analysis (unused variables, orphan keyframes, specificity wars, duplicate properties, z-index abuse)
- Priority system for tools (P0 > P1 > P2 > P3)
- Context-aware hints with auto-init and re-scan on stale registry
- SKILL-QUICK.md concise quick-reference for AI consumption

### Changed
- CLI version: v4 → v5
- Total commands: 36 → 39

## [4.0.0] — 2026-05-01

### Added
- `secrets` — Hardcoded secret detection
- `entrypoints` — Execution entry point mapping
- `api-map` — REST/GraphQL/gRPC route-to-handler mapping
- `state-map` — Global state management tracking
- `env-check` — Environment variable auditing
- `debug-leak` — Debug code leak detection
- `complexity` — Cyclomatic/cognitive complexity scoring
- `regex-audit` — ReDoS-vulnerable regex auditing
- `a11y` — Accessibility auditing (WCAG 2.1)

### Fixed
- Python file discovery now correctly handles .py files
- Top-level error handling for clean JSON errors
- Side-effect argparse bug fixed
- Outline positional argument consistency fixed

## [3.0.0] — 2026-04-30

### Added
- `dataflow` — Data flow analysis (source to sink, taint detection)
- `smell` — Code smell detection (10 categories with health score)
- `side-effect` — Function side-effect analysis (pure vs impure)
- `refactor-safe` — Pre-flight rename/move safety check
- `dead-code` — Enhanced dead code detection
- `stack-trace` — Error propagation simulation
- `test-map` — Test coverage mapping
- `config-drift` — Dependency drift detection
- `type-infer` — Lightweight type inference
- `ownership` — Git blame code ownership analysis
- REST API layer: `GET /api/graph`, `POST /api/command`, `GET /api/health`
- WebSocket server (socket.io on port 3030) for real-time graph updates
- In-memory graph state with GraphEvent normalization
- Health score engine with 6 dimensions

## [2.0.0] — 2026-04-30

### Added
- `search`, `symbols`, `trace`, `impact`, `outline`, `missing-refs`, `diff`, `circular`, `context`, `dependents`, `validate` commands
- Tree-sitter powered AST parsing
- 9 tree-sitter parsers (HTML, CSS, JS, TS, Rust, Python, Vue, Svelte, TSX)
- Framework auto-detection
- Incremental scanning support

## [1.0.0] — 2026-04-30

### Added
- Core commands: `init`, `scan`, `query`, `list`, `detect`, `watch`
- Frontend registry (CSS classes + HTML IDs)
- Backend registry (function nodes + call edges)
- Status tracking (active, dead, collision, duplicate)
- HTML, CSS, JS, Rust basic regex parsers
