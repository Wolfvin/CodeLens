# Changelog

All notable changes to CodeLens are documented here.

## [7.2.0] — 2026-06-12

### Tested against ArchiveBox/ArchiveBox (412 Python files, Django+CLI+MCP)

Real-world test on a self-hosted web archiving tool — Django project with management commands, REST API, MCP server, and heavy subprocess/shell integration.

### Added

- Django URL route detection (path(), re_path(), url(), include(), View.as_view()) — 0 → 61 routes
- `production_only` parameter for api-map (fixes TypeError crash)
- `is_bundled_file()` utility (fixes 4 broken commands)
- Django model/lazy-import/type-alias state filtering — 22 → 1 stores
- Secrets: path value filtering (pwd="/tmp/..." is a path, not password)
- Secrets: URL test data filtering (example.com in tests)
- pyproject.toml description extraction — empty → "Self-hosted internet archiving solution."
- Debug-leak Django CLI context — 1041 → 728 leaks (-30%)
- SQL injection FP reduction — 124 → 24 (-81%), critical 88 → 1 (-99%)

### Fixed

- CRITICAL: `is_bundled_file` missing — broke 4 commands
- CRITICAL: api-map TypeError crash (production_only kwarg)
- CRITICAL: Zero Django routes detected
- State map: Django models misclassified as module_constant
- Handbook: empty description from pyproject.toml
- SQL injection: 124 FPs from HTML context and CLI commands

## [7.1.0] — 2026-06-12

### Tested against nestjs/nest (1673 TypeScript files, lerna monorepo, 11 packages)

Real-world test on the NestJS framework itself — a decorator-based TypeScript monorepo with HTTP controllers, GraphQL resolvers, gRPC services, microservice patterns, and WebSocket gateways.

### Added

- NestJS framework detection (platform, 17 feature packages, decorator pattern fallback)
- NestJS decorator-based API route detection (HTTP, GraphQL, gRPC, microservices) — 0 → 353 routes
- NestJS DI provider state mapping (`@Module({ providers: [...] })`)
- `is_bundled_file()` utility function (fixes 4 broken commands)
- Localhost connection string filtering in secrets engine (17 → 1 FP)
- Secrets findings now include `value` and `line_content` fields
- Class method smell detection (long_fn: 22 → 85, many_params: 5 → 49)
- TypeScript export dead code detection (`export interface/type/enum/declare`) — 0 → 476 findings
- NestJS dataflow decorator input sources (`@Body()`, `@Param()`, etc.) — 48 production violations
- Side-effect engine: class method detection + performance limits (0 → 286 impure)
- Context-aware `hooks/` directory descriptions in handbook

### Fixed

- CRITICAL: `is_bundled_file` missing — broke ask, complexity, context, perf_hint commands
- CRITICAL: No NestJS framework detection
- CRITICAL: API map detected decorator definitions as routes (22 FP eliminated)
- State map: NestJS decorators misclassified as stores
- Handbook: `hooks/` always described as "Custom React hooks"
- Handbook: platform-fastify detected as "express"
- Side-effect engine: infinite timeout on large projects

## [5.9.0] — 2026-06-12

### Tested against gitlab-org/gitlab-vscode-extension (882 files: 763 TS + 82 JS + 18 Vue)

Real-world test on a VSCode extension with unusual hybrid architecture (TypeScript extension host + Vue 2/3 webview subprojects).
This test target exposed significant gaps in CodeLens's handling of VSCode extension patterns, monorepo structures, and runtime-only APIs.

### Fixed

- **CRITICAL: JS/TS god object detection counts control flow as methods**: smell_engine.py regex matched `if(`, `for(`, `while(`, `return(`, `super(`, `console.log(` as class methods — 10-30x inflation. Added negative lookahead for control flow keywords and property accesses.
- **HIGH: perf-hint large_bundle false positives for Node.js built-ins**: `import * as path from 'node:path'` flagged as "prevents tree-shaking" — never bundled. Now skipped for `node:*` protocol imports.
- **HIGH: perf-hint large_bundle false positives for VSCode extension API**: `import * as vscode from 'vscode'` flagged — provided at runtime, never bundled. Now skipped.
- **HIGH: perf-hint memory_leak false positives for process signal handlers**: `process.on('exit')` flagged as memory leak — intentionally permanent. Now skipped for exit/SIGINT/SIGTERM/SIGHUP events.
- **HIGH: side-effect engine misses VSCode extension API calls**: `activate()` classified as "pure" despite calling `vscode.window.createOutputChannel()`, `vscode.commands.registerCommand()`, etc. Added `vscode_api` side-effect category with 11 patterns covering window, commands, workspace, languages, debug, and webview IPC. Now correctly detects 119 VSCode API side effects in GitLab extension.
- **HIGH: config-drift reports `vscode` as missing dependency**: `vscode` is an ambient runtime API declared as `@types/vscode` in devDependencies — standard VSCode practice. Added `vscode` and `electron` to builtins. Missing deps dropped from 24 to 2.
- **HIGH: config-drift false positives in monorepo structures**: Only root `package.json` was scanned; nested subproject package.json files were invisible. Added `_merge_nested_package_jsons()` that discovers and merges dependencies from subprojects (Lerna/Nx/Turborepo/VSCode webview workspaces).
- **MEDIUM: regex-audit flags URL strings as "unescaped dot"**: `gitlab.com`, `example.org`, `www.w3.org` in CSP allowlists and test fixtures flagged. Now skips patterns with no regex metacharacters — plain strings, not regex patterns.
- **MEDIUM: a11y color contrast warnings in test files**: Color contrast in `*.test.js` is meaningless. Now skips color contrast checks in files matching test indicators.
- **pyproject.toml formatting fix**: Merged `description` and `readme` fields on the same line — separated for valid TOML.

## [5.8.1] — 2026-06-12

### Security

- **CRITICAL: Rate limiters wired up in all API routes**: `apiRateLimiter`, `scanRateLimiter`, and `commandRateLimiter` were imported but never used. All 6 API routes now enforce rate limits with proper 429 responses and `retryAfterMs` headers.
- **CRITICAL: Consolidated workspace validation**: Merged duplicate `validateWorkspace()` from `constants.ts` and `workspaceValidator.ts` into a single canonical implementation with consistent blocklist (added `/sbin`, `/usr/sbin`, `/var/run`). Old `workspaceValidator.ts` now re-exports from `constants.ts` for backward compatibility.
- **CRITICAL: Scan cache invalidation on scan command**: `POST /api/command` with `scan` now calls `scanCache.invalidate()` so subsequent `GET /api/graph` and `GET /api/health` requests return fresh data instead of stale cached results.

### Fixed

- **CRITICAL: node-detail and search endpoints re-run scan on every request**: Both `/api/node-detail` and `/api/search` now use `scanCache.getScan()` first, only falling back to CLI execution when cache is empty. Eliminates a major DoS vector.
- **HIGH: O(n²) Gini coefficient → O(n log n)**: Replaced double-loop `computeGini()` with sort-based algorithm. Performance improvement for large codebases with many owners.
- **HIGH: Circular dependency count over-counting**: DFS cycle detection now deduplicates cycles by normalizing back-edge signatures, preventing the same cycle from being counted multiple times from different starting nodes.
- **HIGH: Edge resolver id()-based caching**: Replaced `id(edges)` memory address check with content-based fingerprinting (`len + first/last edge IDs`). Python can reuse memory addresses for different list objects, causing stale cache hits.
- **MEDIUM: Entrypoints markdown formatter truncation**: `[module_export]` was truncated to `odule_export` because `[m` was interpreted as ANSI escape sequence ESC[m. Changed to `**module_export**` bold format which is immune to terminal escape interpretation.
- **MEDIUM: Entrypoints formatter missing handler info**: HTTP handler entries now show method, path, and handler name; module exports show handler name when available.

### Changed

- **Data-driven command → state mapping in analysisStore**: Replaced 35+ case switch statement with declarative `COMMAND_TO_STATE` map and `applyCommandToState()` function. Special commands (scan, init, detect, watch) still use targeted switch logic, but all standard analysis commands are now mapped via the data-driven approach. Adding new commands only requires a single map entry.
- **validateWorkspace return type**: Now returns `ValidationResult { valid, resolved, error? }` instead of throwing. Added `validateWorkspaceOrThrow()` convenience wrapper for routes that prefer exception-based control flow.

## [5.8.0] — 2026-06-11

### Added

- **SearchConfig dataclass**: Replaced 11-parameter `search_workspace()` with `SearchConfig` dataclass + `search_with_config()` for better maintainability. Legacy function preserved for backward compatibility.
- **FrontendRegistryInput dataclass**: Replaced 9-parameter `build_frontend_registry()` with `FrontendRegistryInput` dataclass. Eliminates `many_params` code smell.
- **Package manager detection**: Framework detect now identifies bun/pnpm/yarn/npm from lock files (`bun.lock`, `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`).
- **tRPC / oRPC framework detection**: Added `has_trpc` and `has_orpc` flags from package dependency analysis.
- **normalizeGeneric normalizer**: Added generic normalizer for `handbook` and `ask` commands in the main normalizer (src/lib/normalizer.ts).
- **Expanded WebSocket normalizer**: Added explicit animation routing for 17 previously-unhandled commands in the WebSocket server.
- **Missing logger import fix**: `framework_detect.py` now imports `logger` from `utils`, fixing `NameError` on parse failures.

### Changed

- **Gini coefficient O(n²) → O(n log n)**: Replaced double-nested-loop with sorted-sum method in `healthScore.ts`. Dramatically faster for large codebases.
- **Version bump**: 5.7.1 → 5.8.0 across `utils.py`, `skill.json`, `pyproject.toml`, `CHANGELOG.md`.

### Security

- **Workspace path validation**: REST API and WebSocket now validate workspace paths — reject `..` traversal, optional `CODELENS_WORKSPACE_ROOT` allowlist, symlink resolution.
- **WebSocket command injection prevention**: Command whitelist, arg sanitization, and shell metacharacter rejection for Socket.IO `command` event.
- **Error info disclosure fixed**: All API catch blocks now use `err: unknown` with safe message extraction instead of exposing internal error details.

### Fixed

- **CRITICAL: Class collision false-positive**: CSS classes used on multiple HTML elements were incorrectly flagged as "collision". Only IDs should trigger collision detection (registry.py `compute_frontend_status`).
- **CRITICAL: Handbook circular dependency reporting**: `handbook` read non-existent `chains` key from `detect_circular()`. Now correctly reads from `cycles` dict.
- **CRITICAL: Scan edge filtering on file deletion**: Deleted-file cleanup preserved stale edges referencing removed nodes. Both `from` and `to` must now reference surviving node IDs.
- **CRITICAL: Double normalization in WebSocket**: `normalizeGeneric()` was called twice for security/quality/performance/CSS/refactoring commands. Now computed once and reused.
- **CRITICAL: CLI output JSON parse failure**: WebSocket `JSON.parse` failed when CLI emitted `[CodeLens]` prefix lines. New `parseCliOutput()` helper strips non-JSON prefix.
- **HIGH: Module-level throw on missing env vars**: Server crashed on startup if `CODELENS_PYTHON`/`CODELENS_SCRIPT` were unset. Now uses lazy getters; errors surface at first command execution.
- **HIGH: Hardcoded workspace path**: `analysisStore.ts` default workspace `/home/z/my-project` replaced with env var `NEXT_PUBLIC_CODELENS_WORKSPACE` or `process.cwd()`.
- **HIGH: `--format` argument placement**: `--format` now works after the subcommand name (e.g., `scan /path --format markdown`). Moved from main parser to subparsers.
- **HIGH: Trace deduplication**: Multi-start-node traces no longer produce duplicate nodes. Shared `visited` set across BFS calls.
- **HIGH: Context engine int() crash**: `int()` on node ID suffix crashed on non-numeric values. Added `_safe_parse_line()` with try/except.
- **HIGH: Missing refs StopIteration**: `next()` without default crashed on corrupted registry. Now uses `next(..., None)` with None guard.
- **HIGH: Search engine KeyError**: Direct dict key access `r['path']`/`r['line']` crashed on missing fields. Changed to `.get()`.
- **HIGH: ask.py args mutation**: `args.pop("_confidence")` mutated the args dict. Changed to `args.get()`.
- **HIGH: Orphaned logger in vulnscan_engine**: Used `logging.getLogger()` instead of shared `from utils import logger`. All log calls were silently discarded.
- **MEDIUM: O(n²) normalizer performance**: `nodes.find()` replaced with `Set<string>` for dedup in 6 normalizer methods.
- **MEDIUM: O(n²) coupling computation**: `computeCoupling()` in healthScore.ts still O(N×E) but documented for future optimization.
- **MEDIUM: Tailwind content paths**: Added `./src/**/*` to content paths — production CSS was missing utility classes from src/.
- **MEDIUM: React StrictMode**: Changed from `false` to `true` for better dev warnings.
- **MEDIUM: WebSocket graph updates O(N)**: `findIndex` replaced with `Map<string, number>` index.
- **MEDIUM: WebSocket memory leak**: `commandTimestamps` Map now cleaned up on socket disconnect.
- **MEDIUM: Circular engine recursion limit**: Raised to 5000 for deeply nested codebases.
- **MEDIUM: Incremental mtime float comparison**: Uses tolerance `abs(a-b) > 0.001` instead of exact equality.
- **MEDIUM: Shared DEFAULT_SOURCE_EXTENSIONS**: Centralized in utils.py, eliminating duplication across 6+ engine files.
- **LOW: Root API route**: Returns proper health/version check instead of "Hello, world!".
- **LOW: Demo data bundle size**: Changed to dynamic import in analysisStore.ts.
- **LOW: Client-side fetch timeout**: 90s AbortController added to `/api/command` requests.
- **LOW: setup.sh version**: Updated from "v2" to "v5".

### Added

- **`scan --force` flag**: Force full re-scan even when existing registry triggers auto-incremental mode.
- **Workspace path validation utility**: Exported `validateWorkspace()` from commandRunner.ts for reuse.

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
