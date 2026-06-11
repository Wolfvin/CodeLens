# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.7.2] — 2026-06-12

### Fixed

- **CRITICAL: Trace markdown formatter displayed paths character-by-character** — `_md_trace()` treated the `path` string field as an iterable list, splitting `"packages/runtime-core/src/ref.ts"` into `p → a → c → k → a → g → e → s → / → …`. Introduced `_format_trace_chain()` helper that correctly handles both string and list `path` values, with depth indentation, cyclic markers (↻), and unresolved markers (⚠).
- **CRITICAL: TS/JS backend parser missed arrow functions wrapped in parentheses or `as` expressions** — Patterns like `const name = ((...args) => { ... })` and `const name = ((...args) => { ... }) as Type` were not captured because tree-sitter wraps these in `parenthesized_expression` and `as_expression` nodes respectively. Added `_unwrap_fn_from_parens()` recursive helper and `as_expression` handling to both `TSBackendParser` and `JSBackendParser`. This fixes missing functions like Vue's `createApp` in query results.
- **HIGH: Framework detection missed Rust/Python polyglot projects** — Ruff (Rust+Python) showed "No frameworks detected" and "cjs" module system. Added proper `module_system` detection for Cargo-only (`cargo`), Python-only (`python`), and Rust+Python (`rust-python`) projects. Added `languages` field to framework detection output. Added `has_rust_backend` flag display and `Cargo.toml` presence detection for `has_rust_backend`.
- **HIGH: Zombie CSS false positives with invalid class names** — CSS class names containing special characters like `.(version`, `.===`, `.\`@${currentCommit}\`` were reported as zombie CSS. Added regex validation (`^[a-zA-Z_\-][a-zA-Z0-9_\-]*$`) and character blacklist filtering to `_detect_zombie_css()` in `deadcode_engine.py`.
- **HIGH: God object detection had massive false positives in JS/TS files** — The regex `(?:async\s+)?(?:private|public|protected|static)?\s*(?:get|set)?\s*\w+\s*\(` matched any function-like pattern in the entire file, including `if(`, `for(`, `console.log(`, etc. Rewrote `_detect_god_objects()` for JS/TS to properly extract class bodies first using brace-depth matching, then count only actual class methods. Also rewrote Rust detection to scope `fn` counting to each `impl` block instead of the entire file.
- **MEDIUM: API map included routes from test fixture files** — Routes from `/test/`, `/tests/`, `/fixtures/`, `/examples/`, `*.test.*`, `*.spec.*` files were reported as real API routes. Added test fixture file filtering to `apimap_engine.py` with path and filename pattern matching.
- **MEDIUM: Framework detect markdown output missing flags** — `_md_detect()` did not display `has_fastapi`, `has_flask`, `has_django`, `has_tauri`, or `has_rust_backend` flags. Also missing `is_monorepo` and `lockfile` display. Added all missing flags and fields.

### Testing

Tested against 3 diverse, large open-source repositories:
- **vuejs/core** (Vue.js framework) — 506 JS files, 11 TSX, 11 Vue files — tested Vue parser, JS/TS backend parsing, query, trace, complexity, dead code, data flow
- **astral-sh/ruff** (Rust+Python linter) — 1863 Rust files, 2942 Python files — tested Rust parser, Python parser, framework detection for polyglot, secrets scan, smell engine
- **sveltejs/kit** (SvelteKit framework) — 904 Svelte files, 682 JS backend files — tested Svelte parser, SSR framework detection, a11y, smell engine, state map

## [5.8.0] — 2026-06-12

### Added

- **Monorepo support** (`scripts/framework_detect.py`): Full monorepo workspace detection — scans all `package.json` files in sub-packages (pnpm workspaces, npm/yarn workspaces, Turborepo). This fixes a critical bug where React was not detected in monorepo projects like Tauri apps with `apps/` structure. New functions: `_discover_workspace_package_jsons()`, `_glob_package_jsons()`, `_collect_deps_from_package_jsons()`. Detects `is_monorepo` flag and `lockfile` type (bun/pnpm/yarn/npm).
- **Deep Tauri config scan** (`scripts/framework_detect.py`): Tauri config (`tauri.conf.json`) is now detected anywhere in the workspace tree, not just at `src-tauri/tauri.conf.json`. This fixes detection in monorepo structures like `apps/<name>/src-tauri/tauri.conf.json`.
- **Monorepo-aware init config** (`scripts/framework_detect.py`): `get_recommended_config()` now generates correct `frontend_paths` and `backend_paths` for monorepo Tauri projects (e.g., `apps/readest-app/src/` for frontend, `apps/readest-app/src-tauri/src/` for backend).
- **Lockfile detection** (`scripts/framework_detect.py`): Added automatic detection of package managers from lock files: `bun.lock`/`bun.lockb` → bun, `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `package-lock.json` → npm. Exposed as `lockfile` in framework detection output.
- **New framework signatures** (`scripts/framework_detect.py`): Added detection for `trpc`, `orpc`, `zustand`, `redux`, and `vite` frameworks/packages.
- **SearchConfig dataclass** (`scripts/search_engine.py`): Introduced `SearchConfig` dataclass to replace the 11-parameter `search_workspace()` function. The old function is preserved for backward compatibility and now delegates to `search_with_config(cfg)`. This eliminates the `many_params` code smell (11 → 2 parameters) and makes call sites self-documenting.
- **FrontendRegistryInput dataclass** (`scripts/registry.py`): Introduced `FrontendRegistryInput` dataclass to replace the 9-parameter `build_frontend_registry()` function. Legacy function preserved for backward compatibility, delegates to `build_frontend_registry_from_input(inp)`. Eliminates the `many_params` code smell (9 → 1 parameter).
- **normalizeGeneric normalizer** (`src/lib/normalizer.ts`): Added a generic normalizer method that produces a simple GraphEvent from any CLI output. Used for `handbook` and `ask` commands which previously fell through to the "unknown command" fallback.
- **Expanded WebSocket normalizer coverage** (`mini-services/codelens-ws/index.ts`): Added explicit animation routing for 17 previously-unhandled commands (test-map, config-drift, type-infer, ownership, entrypoints, api-map, state-map, handbook, stack-trace, diff, validate, outline, dependents, list, context, detect, init). Previously these all fell through to the default generic handler.
- **Missing logger import fix** (`scripts/framework_detect.py`): Added `logger` import from `utils` — the module was referencing `logger.debug()` without importing it, causing `NameError` at runtime when parsing requirements.txt/pyproject.toml failed.

### Fixed

- **CRITICAL: `should_ignore_dir` missing from utils.py** — The function was imported by `framework_detect.py`, `tailwind_detector.py`, and 40 command modules via the import chain, but never defined in `utils.py`. This caused ALL 41 CLI commands to fail with `ImportError` on startup. Added the function with path-segment-aware matching consistent with `should_ignore()` in scan.py.
- **CRITICAL: Frontend registry deletion cleanup used nonexistent field** — Incremental scan tried to clean deleted-file entries using `c.get("defined_in")`, but frontend classes use `css`/`js` arrays with `path` fields, and IDs use `defined_in_html`. This meant deleted files' frontend data was NEVER removed from the registry. Rewrote cleanup to properly strip refs by path and recalculate ref_count/status.
- **CRITICAL: `ask` command missing handlers for 8 commands** — Side-effect, dataflow, missing-refs, ownership, config-drift, stack-trace, and type-infer queries all returned "Unknown command" because `_execute_ask_command` had no handler branches. Added all missing handlers.
- **HIGH: Rust parser `impl_for` context leaked to sibling functions** — When tree-sitter walked past an `impl_item` to a sibling `function_item` outside the impl block, `current_impl_for` still held the previous impl's type name. Fixed by checking parent ancestry before assigning impl context.
- **HIGH: Circular dependency detection missed `../` imports** — The import regex only matched `./` relative imports, silently ignoring all parent-directory imports (`import X from '../utils'`). Fixed regex to match `\.{1,2}/` for both `./` and `../`.
- **HIGH: `vulnscan_engine.py` created its own logger** — Bypassed the shared `utils.get_logger()` which configures handlers and log level, causing all vulnscan debug/warning messages to be silently dropped. Changed to import `logger` from utils.
- **HIGH: Version mismatch** — `utils.py` had version 5.7.0, `skill.json` and `pyproject.toml` had 5.7.1. Unified to 5.8.0 across all three.
- **MEDIUM: `scan.py` imported unused `compute_frontend_status`** — Removed dead import.
- **MEDIUM: `context_engine.py` used raw `open()` instead of `safe_read_file()`** — Could crash on minified/large files. Switched to the safe utility.
- **MEDIUM: `search_engine.py` used simple set membership for directory ignoring** — Didn't benefit from path-segment-aware matching. Added `should_ignore_dir()` call.
- **MEDIUM: Dead code branch in `incremental.py`** — `if not is_resolved and from_is_changed` was unreachable because `from_is_changed` was already checked earlier. Removed the dead branch.
- **MEDIUM: `context_engine.py` auto-domain silently dropped backend matches** — When a name matched in both frontend and backend, only the frontend result was returned. Now adds `also_matched_in` note to indicate the overlap.
- **MEDIUM: `convention_engine.py` had no file count limits** — Could be extremely slow on large codebases (10K+ files). Added `MAX_FILES_PER_CATEGORY = 500` sampling limit.
- **LOW: 12 engine files imported `DEFAULT_IGNORE_DIRS` but not `logger`** — Added `logger` to imports in: smell_engine, debugleak_engine, apimap_engine, envcheck_engine, dependents_engine, dataflow_engine, regexaudit_engine, statemap_engine, complexity_engine, typeinfer_engine, cssdeep_engine, entrypoints_engine.

### Changed

- **Gini coefficient optimization** (`src/lib/healthScore.ts`): Replaced O(n²) double-nested-loop implementation with O(n log n) sorted-sum method: `G = (2 * Σ(i * x_i)) / (n * Σ x_i) - (n + 1) / n`. This dramatically improves performance for large codebases with many owners.
- **Version bump**: Updated from 5.7.1 to 5.8.0 across `utils.py`, `skill.json`, and `CHANGELOG.md`.
- **Tauri+React monorepo JSX mode** (`scripts/framework_detect.py`): JSX mode is now correctly enabled when both React and Tauri are detected in a monorepo.

### Test Target Documentation

- **readest/readest** (GitHub): Used as a test target for monorepo support — a large Tauri ebook reader app with React frontend and Rust backend. Monorepo structure: 40 Rust files, 1167 TSX files, 1 CSS file. Previously, `detect` returned `has_react: false` because React was only in `apps/readest-app/package.json`. After fix, all 6 frameworks detected: react, next.js, tailwind, zustand, vite, tauri. Also validated: smell (6389 issues, health 75), secrets (72 findings), complexity (3494 functions), circular deps (111 cycles), dead code (450 items), vuln scan (1 CVE), perf hints (952), a11y (584 issues).

## [5.6.0] — 2026-06-11

### Added

- **TSX backend extraction**: When tree-sitter-typescript is not installed, TSX files are now parsed with BOTH frontend AND backend fallback parsers. Backend nodes jumped from 124 → 764 (6.2x) on typical Next.js projects.
- **Shared utils module** (`scripts/utils.py`): Centralized `write_output_files`, `compute_summary`, `is_file_path`, `deduplicate_callers`, `DEFAULT_IGNORE_DIRS`, `DEFAULT_IGNORE_EXTENSIONS`, `CODELENS_VERSION`, and `logger`. Eliminates 290+ lines of duplicated code across 5 files.
- **Proper logging**: Replaced silent `except Exception: pass` blocks with `logger.warning()`/`logger.debug()` calls across all engine and utility files. Errors are now visible when they occur instead of being silently swallowed.
- **Fuzzy file path lookup**: `context layout.tsx` and `query layout.tsx` now match partial paths (end-of-path matching). Previously required exact path like `apps/web/app/[locale]/layout.tsx`. Returns grouped results when multiple files match.
- **Auto-incremental scan with registry counts**: When no changes detected, the response now includes actual backend/frontend counts instead of zeros.
- **Handbook registry freshness check**: Handbook skips re-scan if `backend.json` is less than 5 minutes old. Reduces handbook execution time from 2.8s → 0.3s for consecutive runs.

### Changed

- **is_frontend_file / is_backend_file**: Now uses path segment matching instead of substring matching. `"src/"` no longer falsely matches `src/server/api/auth.ts` as a frontend file.
- **_detect_workspace depth limit**: Walks up at most 10 directory levels (was unlimited). Prevents matching a `.git` directory many levels up.
- **Incremental scan with deleted files**: Instead of falling back to full rescan, deleted files are selectively removed from the registry. Preserves incremental scan performance.
- **god_objects Python scoping**: Method count is now scoped to each class using indentation analysis (was counting ALL `def` in the file).
- **Consistent status field**: `context` and `query` file-path responses now include `status: "ok"` (was missing).
- **Context multi-file response**: New `type: "files"` response format when multiple files match a partial path query, with markdown formatting support.
- **Handbook version**: Now uses `CODELENS_VERSION` constant from `utils.py` (was hardcoded as `"5.2.0"`).
- **Centralized `DEFAULT_IGNORE_DIRS`**: All 30 engine/command files now import `DEFAULT_IGNORE_DIRS` from `utils.py` instead of defining local copies. Single source of truth ensures consistency across all scanners.
- **pyproject.toml version**: Aligned with skill.json and CODELENS_VERSION (was 5.1.0, now 5.6.0). Description updated from "39 commands" to "41 commands".

### Fixed

- **TSX files produced zero backend nodes**: When TSXParser failed to import, only CSS class/ID data was extracted. Now uses `parse_js_backend_fallback` on TSX files too.
- **Auto-incremental returned zero counts**: "No changes detected" response had `backend.nodes: 0, backend.edges: 0` even when registry had thousands of entries.
- **Handbook version stale**: Was hardcoded as 5.2.0 in output, now dynamically reads from `CODELENS_VERSION`.
- **Test import errors**: 6 test files (test_cli, test_css_parser, test_html_parser, test_js_backend_parser, test_js_frontend_parser, test_rust_parser) were importing from old monolithic `codelens.py`. Updated to import from the new modular structure (`commands.scan`, `parsers.fallback_*`).
- **Scan edge filter for deleted files**: Edge cleanup was overly permissive — kept ALL unresolved edges regardless of whether they referenced deleted nodes. Now only keeps edges where `from` is in remaining nodes.
- **setup.sh version reference**: Updated from "v2" to "v5" to match current version.
- **CLI test suite**: `__tests__/cli/test_scan.py` now uses hermetic temporary workspaces instead of scanning the host project, and added 3 new test cases (init, scan+query integration, registry creation).

## [5.5.0] — 2026-06-11

### Added

- **Auto-incremental scan**: Scan now automatically uses incremental mode when a registry already exists (`.codelens/backend.json` present). No need to pass `--incremental` flag. First scan is always full; subsequent scans auto-detect changes.
- **oRPC route detection**: API-map now detects oRPC-style routers (`.procedure()`, `router({})`, `protectedProcedure`/`adminProcedure` chains). Detects 67 routes in typical oRPC projects (was 2).
- **tRPC v10+ detection**: Improved tRPC extraction with `t.procedure`, `publicProcedure.query/mutation`, `initTRPC`, and router body parsing for named procedure paths.
- **Context by file path**: `context src/lib/auth.ts` now returns all symbols defined in that file, not just symbol-name lookups.
- **Query by file path**: `query src/lib/auth.ts` returns all symbols in the file, grouped by file.
- **bun.lock support**: Vulnerability scanner now parses Bun's text-based `bun.lock` format for dependency checking.
- **Next.js destructured route exports**: API-map now detects `export const { GET, POST } = handler()` and `export const GET = ...` patterns in Next.js App Router.

### Changed

- **Health score calibration**: Deep nesting now reports per-block instead of per-line (was 6419 findings → 300). Magic values skip config/test/fixture files and JSX style props. Weighted density formula (`critical*3 + warning + info*0.1`) prevents info-level smells from tanking scores. Typical React project health: 90 (was 25).
- **Deep nesting thresholds**: Raised from 4→5 (warning) and 6→8 (critical) to account for natural React component nesting.
- **Duplicate caller filtering**: `query` and `context` commands now deduplicate callers by (file, line) tuple.

### Fixed

- **Secrets markdown truncation**: Severity "high" was truncated to "igh]" in markdown output due to f-string variable name collision. Now displays correctly as `[HIGH]`, `[CRITICAL]`, etc.

## [5.4.0] — 2026-06-11

### Added

- **True incremental scan**: Partial registry merge — changed files' entries are updated in-place instead of rebuilding the entire registry. Unchanged files' data is preserved, making `--incremental` significantly faster for large codebases.
- **Complete markdown formatters**: All 41 commands now have specific markdown formatters (was 15/41). No command falls through to generic formatting anymore.
- **Score-based ask routing**: Natural language query router now uses weighted scoring instead of first-match. Technical terms score 3x, action words 1x, generic words 0x. Correctly routes "show me the API routes" to api-map instead of context.
- **8 new ask patterns**: CSS issues→css-deep, accessibility→a11y, regex→regex-audit, what changed→diff, tech stack→detect, how to configure→env-check, which files import→dependents, is this code safe→refactor-safe.
- **3 new semantic convention detectors**: CSS framework (Tailwind/Bootstrap/MUI/Chakra/Ant/Bulma), Authentication (NextAuth/Passport/JWT/OAuth/Firebase/Supabase/Clerk), Deployment (Vercel/Netlify/Docker/Fly.io/Railway/Render/Heroku/AWS/GCP).
- **Better error messages**: Command-specific error suggestions with `_suggest_fix()`. Split error handling into FileNotFoundError, ImportError, and generic Exception with helpful suggestions.
- **Consistent status field**: All commands now return `status: "ok"` (or `status: "error"` on failure). Previously some commands like `list`, `query`, `detect`, and `diff` were missing this field.

### Changed

- `codelens.py` monolith reduced from 3504 → 307 lines (modular architecture)
- Ask command accuracy: 12/12 test cases pass (was ~8/12 with first-match routing)
- Health score: percentile-based formula (clean=95, average=85, messy=55, CodeLens=5)
- Convention engine: 8 semantic detectors total (was 5)

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
