# Changelog

All notable changes to CodeLens are documented here.

## [5.8.0] — 2026-06-11

### Fixed — Critical
- **API whitelist missing `handbook` and `ask` commands** — these key AI-facing commands were rejected by the REST API (`commandRunner.ts`)
- **Path traversal vulnerability** — API routes accepted arbitrary workspace paths without validation, allowing access to system directories (`/etc`, `/root`, etc.)
- **No scan result caching** — `/api/graph` and `/api/health` re-scanned the entire workspace on every GET request (10+ seconds); added 30-second TTL cache
- **Auto-incremental scan couldn't be disabled** — added `--full` flag to force clean re-scan when registry data is stale
- **`fn_map` overwrite bug** — `fallback_python.py` silently overwrote function entries with the same name (e.g., methods in different classes), causing misattributed call edges

### Fixed — High
- **Inconsistent ignore directories** — `framework_detect.py`, `circular_engine.py`, and `validate_engine.py` used hardcoded ignore lists instead of centralized `DEFAULT_IGNORE_DIRS` from `utils.py`
- **`--format json` not explicitly passed** — API calls could receive non-JSON output if user config changed default format; now always passes `--format json`

### Fixed — Medium
- **Secrets engine insufficient masking** — short secrets (< 8 chars) revealed the entire value with "first 4 + ***" strategy; now uses "first 2 + ***" for values under 8 chars
- **`graphStore.loadFromJSON` silently swallows errors** — added logging for malformed JSON attempts
- **EventLog truncation gap** — changed from 1000→500 (50% gap) to 1000→800 (20% gap) for less event history loss

### Added
- `sanitizeWorkspace()` function in `commandRunner.ts` for workspace path validation
- 30-second TTL scan result cache in `/api/graph` and `/api/health` routes
- `--full` flag on `scan` command to force full re-scan

## [5.3.0] — 2026-06-11

### Architecture
- **Major refactoring**: Broke `codelens.py` (3504 lines) into modular command structure
  - `commands/` directory with 41 command modules using registry pattern
  - `formatters/` directory with JSON and markdown formatters
  - `parsers/fallback_*.py` — 6 fallback parsers moved out of main file
  - `codelens.py` is now 307 lines (slim entry point with auto-dispatch)

### Added
- **Semantic convention detection** in `convention_engine.py`:
  - ORM pattern detection (Prisma, SQLAlchemy, TypeORM, Mongoose, Drizzle, Knex)
  - Error handling pattern detection (try-catch, Result type, Either, custom errors)
  - API response format detection (envelope, NextResponse, Express, tRPC)
  - State management library detection (Zustand, Redux, MobX, Recoil, Jotai, Pinia, Context API)
  - Testing framework detection (Jest, Vitest, Pytest, Mocha, Playwright)
- **Integration test suite** (`test_integration.py`):
  - Smoke tests for all 41 commands (JSON + markdown format)
  - Decision tree field validation (query, impact, smell, dead-code)
  - Health score range validation
  - Context quality metrics validation
  - Module structure verification

### Changed
- **Health score formula** rewritten: percentile-based scoring replaces linear deduction
  - Old: `max(0, 100 - (critical*10 + warning*3 + info))` — always 0 for medium+ projects
  - New: density-based tiers + critical ratio adjustment — meaningful scores for all project sizes
  - Example: Clean project = 100, average = 90, messy = 55, high-density = 9
- `handbook` now includes `"status": "ok"` in output
- `scan` incremental mode reports `changed_files_count`
- `_md_trace` handles dict-format chains (up/down directions)
- `_md_impact` handles dict-format affected (direct/indirect groups)
- `_md_query` shows callers/callees and extracts name from node.fn
- `ask` command routing: specific topic patterns checked before generic ones
- `_extract_symbol_name`: strips filler words, prefers code-style identifiers
- `_build_directory_map`: uses dir_hints for common names, recursive file counting
- `entrypoints_engine`: `match.lastindex` NoneType guard added

### Fixed
- UnboundLocalError in `smell` command (local imports shadowing top-level)
- KeyError in `_md_impact` (affected is dict, not list)
- KeyError in `_md_trace` (chains is dict, not list)
- `ask` misrouting "show me API routes" to context instead of api-map
- `_extract_symbol_name` extracting "the" instead of "verify_token"

## [5.2.0] — 2026-06-11

### Added
- `handbook` command — One-stop project orientation for AI agents. Aggregates identity, structure, health, conventions, risks, and quick reference. Writes `.codelens/handbook.json` and `.codelens/AGENT.md`
- `ask` command — Natural language query router. 21 keyword pattern groups route plain English questions to the appropriate CodeLens command
- `--format json|markdown` global flag on ALL commands. Markdown output for direct LLM consumption
- `scan` now generates `outline.json` + `summary.json` in `.codelens/` (previously only `watch` did)
- Decision trees in output: `query` returns `action` + `action_reason`, `impact` returns `risk_level` + `recommended_action`, `smell` returns `actionable_items`, `dead-code` returns `removal_safety` + `dependency_count`
- `context` command enriched with `quality` block: complexity, side effects, safety assessment, smells, test coverage
- `convention_engine.py` — Detects naming conventions, file organization, import styles, component patterns, error handling patterns
- `.codelens/AGENT.md` auto-generated after `scan` and `handbook` — markdown project brief for system prompt context

### Changed
- Renamed `_write_watch_output` → `_write_output_files`, `_compute_watch_summary` → `_compute_summary` (no longer watch-specific)
- Total commands: 39 → 41
- Version: 5.1.0 → 5.2.0

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
