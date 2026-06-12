# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [6.3.0] — 2026-06-12

### Tested against neovim/neovim (3,826 source files: 822 Lua + 506 C/C++ + 8 Python, C+Lua polyglot)

Real-world test on a C+Lua editor (neovim) with CMake + Zig build system.
Confirmed: 16,802 backend nodes, 9,913 edges, 5,535 functions outlined,
29,860 code smells across C/Lua/Zig files, polyglot project identity
(c-cpp-lua-zig-polyglot), framework detection from file extensions.

### Added

- **C/C++ outline parser** (`_outline_c_cpp`): Full regex-based outline for C/C++ files extracting functions, classes, structs, enums, macros, includes, typedefs. Properly skips preprocessor directives (#ifdef, #ifndef, #endif, #if, #else, #elif, #pragma) — they are no longer misidentified as functions.
- **Lua outline parser** (`_outline_lua`): Regex-based outline for Lua files extracting functions (global, local, method, exported), tables, requires.
- **Java/Kotlin outline parser** (`_outline_java`): Regex-based outline extracting classes, interfaces, enums, methods, imports, packages.
- **PHP outline parser** (`_outline_php`): Regex-based outline extracting functions, classes, interfaces, traits, enums, includes.
- **Zig outline parser** (`_outline_zig`): Regex-based outline extracting functions (pub/private), constants, imports.
- **Polyglot project identity** (`_extract_project_identity`): Now detects C/C++ (CMakeLists.txt), Lua (.lua files), and Zig (build.zig) project types. Combined type string for polyglot projects (e.g., "c-cpp-lua-zig-polyglot"). Extracts project name and version from CMakeLists.txt (project() command) and Makefile (VERSION variable).
- **Framework detection from file extensions** (`detect_frameworks`): New step 8 counts source files by language extension and adds language frameworks (c, cpp, lua, java, golang, csharp, php, zig) when files exist. Also detects CMake and Zig build systems. Includes `language_file_counts` and `is_polyglot`/`project_type` in output.
- **Language detection in outline** (`_detect_language`): Now recognizes 16+ languages including C, C++, Lua, Java, Kotlin, C#, PHP, Zig.

### Fixed

- **CRITICAL: `get_workspace_outline()` crash** — The function didn't accept `max_files` parameter but `utils.py` passed it, causing TypeError after every scan. Added `max_files` parameter (default: 5000) with proper iteration limiting.
- **C/C++ preprocessor directives misidentified as functions** — `#ifdef WIN32`, `#ifndef MSWIN`, `#define ENABLE_ASAN_UBSAN` etc. were incorrectly parsed as function definitions in `fallback_c.py`. Now properly skips all lines starting with `#`. Also added preprocessor keywords to the exclusion list.
- **Outline engine missing language support** — `get_workspace_outline()` only included JS/TS/Rust/Python/Go/HTML/CSS/Vue/Svelte extensions. Now includes C, C++, Lua, Java, Kotlin, C#, PHP, Zig extensions.
- **Smell engine only analyzed Python/JS/TS/Rust** — `SOURCE_EXTENSIONS` in `smell_engine.py` excluded C, C++, Lua, Java, Go, Zig. Now includes all 16+ languages.
- **Complexity engine only analyzed Python/JS/TS/Rust** — Same issue as smell engine. Fixed by adding all language extensions.
- **Dead code engine missing language support** — Added `.lua`, `.java`, `.cs`, `.php`, `.zig` to `SOURCE_EXTENSIONS`.
- **Dead code false positives for C entry points** — Functions like `nvim_main`, `WinMain`, `DllMain`, and functions ending with `_init`, `_start`, `_entry` in C/C++ files were marked as dead. Now properly skipped.
- **Project identity "unknown" for C/Lua/Zig projects** — `_extract_project_identity()` only checked package.json, pyproject.toml, and Cargo.toml. Now also checks CMakeLists.txt, Makefile, build.zig, and .lua file presence.
- **Framework detection missed C, Lua, Zig** — Only detected cmake from config files. Now detects all languages from actual source file extensions.
- **Version mismatch** — skill.json (5.8.0), pyproject.toml (5.9.0), utils.py (5.8.0) were all different. Now unified to 6.3.0.

### Changed

- `outline_engine.py` source_extensions expanded from 15 → 25+ extensions
- `framework_detect.py` now includes `language_file_counts` and `is_polyglot`/`project_type` in output
- `skill.json` description updated to reflect v6.3 capabilities
- `skill.json` tags expanded with lua, zig, cmake, c, java, csharp, polyglot, etc.

## [5.8.0] — 2026-06-12

### Tested against denoland/deno (5,448 source files: 970 Rust + 4,567 TS/JS, 143MB polyglot monorepo)

Real-world test on a Rust+TypeScript runtime with 36,186 backend nodes and 269,678 edges.
Confirmed: 19,994 smells (health score 50), 676 dead items, 775 circular deps,
1,959 functions analyzed, 3,709 debug leaks, 1,010 entrypoints, 283 state stores,
302 regex patterns, 164 a11y issues, 313 perf hints, 50 env vars.

### Added

- **Rust framework detection**: `detect_frameworks()` now parses `Cargo.toml` for dependencies and detects `rust`, `tokio`, `actix-web`, `axum`, `warp`, `rocket`, `deno_core` from Cargo dependencies. Also scans workspace members' `Cargo.toml` in `crates/`, `ext/`, `libs/`, `packages/` directories.
- **Rust HTTP route extraction**: `api-map` command now detects routes from Rust web frameworks:
  - actix-web / rocket: `#[get("/path")]`, `#[post("/path")]` attribute macros
  - actix-web: `web::resource("/path")` programmatic routes
  - axum: `.route("/path", get(handler))` method chaining
  - warp: `warp::path("segment")` filter chains
- **Cargo workspace monorepo detection**: `handbook` now detects `[workspace]` sections in `Cargo.toml` and sub-directory crate patterns (`crates/*/Cargo.toml`, `ext/*/Cargo.toml`). Reports `is_monorepo: true` with `monorepo_tools: ["cargo-workspace"]`.
- **`is_generated_file()` utility**: Added to `utils.py` for detecting lock files, declaration files, minified files, and other generated artifacts. Fixes `refactor_safe_engine.py` import crash (was importing non-existent function). Total commands: 42 → 43.
- **`has_rust` field in framework detection**: `detect_frameworks()` now includes `has_rust: true` when `Cargo.toml` is found, and adds Rust-specific backend paths to recommended config.

### Fixed

- **`refactor_safe` command crash**: `refactor_safe_engine.py` imported `is_generated_file` from `utils` but the function did not exist, causing the entire command module to fail loading (42/43 commands loaded). Now all 43 commands load successfully.
- **State-map `__dunder` false positives**: Runtime binding helpers (`__default`, `__createBinding`, `__exportStar`, `importDefault`, `__reexport`, `__buffer`, `__default_export__`, `__telemetry`, `__esModule`, etc.) were classified as state stores. Added 15+ JS/TS runtime helper names to post-filter skip set, plus a general `__dunder` runtime helper detection pattern. Result: 0 `__dunder` false positives (was 8 in deno test).
- **`handbook` crash on `cmd_scan()` call**: Handbook called `cmd_scan(workspace, max_files=max_files)` but `cmd_scan()` doesn't accept `max_files` parameter. Removed the invalid keyword argument.
- **Smell `health_score` not at top level**: `health_score` was only available inside `stats` dict, making it harder to access programmatically. Now also returned as a top-level key in the response dict.
- **Markdown formatter for smell**: Now reads `health_score` from top-level first, then falls back to `stats.health_score` for backward compatibility.
- **Version mismatch**: `skill.json` version was `5.7.1` but description referenced v5.10/v6.1. Updated to `5.8.0` with accurate description.

### Changed

- **Complexity engine file cap**: Increased from 3,000 → 5,000 files. Function cap increased from 5,000 → 8,000. Prevents missing analysis on large repos.
- **Debug-leak engine file cap**: Increased from 3,000 → 5,000 files per run for better coverage on large repos.
- **Rust framework config paths**: When Rust is detected, recommended config now includes `crates/*/src/` and `ext/*/src/` as backend paths.

## [5.7.2] — 2026-06-12

### Fixed
- **state-map markdown crash**: `_md_state_map()` called `.get('name')` on action/slice entries, but entries are strings in Pinia/Vuex/Redux/Zustand stores. Now handles both dict and string formats gracefully.
- **binary-scan ImportError**: `scan_binary_artifacts` function was missing from `utils.py`. Now fully implemented with extension-based detection and binary signature scanning (ELF, PE, Mach-O, WASM, etc.).
- **Pinia/Vuex/Redux false positive actions**: JS/TS keywords (`if`, `for`, `while`, etc.) and built-in methods (`push`, `includes`, `toUpperCase`, etc.) were being extracted as store actions. Added `_is_js_keyword_or_builtin()` filter with 80+ entries. Also improved section extraction using `_extract_section()` with proper brace-matching instead of fragile regex.

### Added
- **binary-scan command fully functional**: New `_md_binary_scan` markdown formatter. Scans for compiled binaries, archives, images, and Python bytecode with size reporting and recommendations.
- **Tauri IPC route mapping in api-map**: Frontend `invoke('command')` calls and backend `#[tauri::command]` Rust handlers are now extracted as IPC routes. Shows full invoke:// endpoint paths.
- **Unsupported language detection**: Framework detection now identifies Go, Java, Kotlin, C/C++, C#, Swift, and Ruby projects. Scan output shows a `lang_note` warning when unsupported languages are detected.
- **Go framework signatures**: Added `golang`, `gin`, `echo` to framework detection signatures.
- **`_extract_section()` helper**: New brace-matching helper for state management extractors that properly handles nested braces and string literals, replacing fragile regex patterns.

## [6.0.0] — 2026-06-12

### Added
- **Monorepo-aware framework detection**: Detects turborepo, pnpm-workspace, lerna, nx. Walks sub-directory package.json (apps/*, packages/*) to find frameworks in workspace packages. Detects Rust/Cargo workspaces. Build tool detection (Vite, webpack, esbuild).
- **Polyglot project identity**: Handbook detects combined types (e.g., `rust-js-monorepo`) when both package.json and Cargo.toml exist.
- **Dead code from registry cross-reference**: Uses backend registry's `ref_count` data to find functions with zero references.
- **Monorepo-aware config defaults**: `init` now adds `apps/*/`, `packages/*/`, `crates/*/` paths when monorepo detected.
- **`should_ignore_dir()` utility**: New shared utility in `utils.py` for path-segment-aware directory ignore checking. Replaces inline implementations across multiple engines.
- **`safe_read_file()` utility**: New shared utility for safe file reading with size limits and encoding handling. Prevents out-of-memory on large files.
- **`time_budget_expired()` utility**: New shared utility for checking global timeout budgets in engines. Prevents runaway scans on massive codebases.
- **Performance safeguards in `utils.py`**: `MAX_FILE_SIZE` (200KB), `MAX_FILES_DEFAULT` (5000), `GLOBAL_TIMEOUT_SEC` (120s) constants for all engines.
- **`handbook --quick` mode**: New flag to skip expensive engines (secrets, vuln-scan, circular, dead-code) for faster results on large codebases.
- **Engine status tracking in handbook**: Handbook now reports `engines_ok` and `engines_failed` lists in `meta`. Overall status is `ok`, `degraded`, or `error` based on engine results.
- **Lazy imports in `ask` command**: All 17 engine imports moved from module-level to inside `_execute_ask_command()`. Reduces CLI startup time significantly.
- **Thread-safe grammar loader**: `GrammarLoader` singleton now uses `threading.Lock()` for thread safety in watch command.
- **Modern tree-sitter API support**: `GrammarLoader.get_parser()` now handles both legacy (`Parser(lang)`) and modern (`parser.language = lang`) tree-sitter APIs.
- **Graceful command import**: `commands/__init__.py` now wraps each command module import in try/except, so one failing module doesn't prevent others from registering.
- **`truncated` field in env-check output**: Indicates when file count or timeout limits were hit, so users know results are partial.

### Fixed
- **God object detection**: Class method counting now scoped to actual class/impl body via brace-depth tracking. Was counting ALL function calls in the file as methods (10-30x inflation).
- **API route false positives**: Routes must start with `/` for non-router objects. Expanded skip list (80+ objects). Prevents `headers.get('user-agent')` from being reported as `GET /user-agent`.
- **CSS specificity false positives**: Tracks brace depth to distinguish CSS rule selectors from property values. Was flagging `rgba()`, `var()`, gradient values as selectors.
- **State map over-classification**: Skips ALL_CAPS constants, React components (arrow functions, forwardRef, memo, styled), and immutable values. Removed module.exports scanning.
- **Entrypoints markdown formatting**: Bracket types like `[main]` no longer get mangled by markdown link reference interpretation.
- **Dead code zero results**: Fixed registry cross-reference to use correct field names (`fn` instead of `name`). Added filtering for main(), pub functions, and test fixtures.
- **Handbook type detection**: No longer defaults to `node-project` for Rust+TS monorepos. Cargo.toml is always checked regardless of existing type.
- **`should_ignore_dir` ImportError in tailwind_detector.py**: Was importing a function that didn't exist in `utils.py`. Now uses shared implementation from `utils.py`.
- **`safe_read_file` ImportError in a11y_engine.py**: Removed unused import of non-existent function. a11y_engine now uses the shared `safe_read_file` from `utils.py`.
- **Silent exception swallowing in `context.py`**: `except Exception: pass` replaced with proper `logger.debug()` call.
- **Silent exception swallowing in `handbook.py`**: `except Exception: pass` for sub-directory package.json replaced with `logger.debug()`.
- **Handbook always reports `status: ok`**: Now reports `ok`, `degraded`, or `error` based on engine success/failure counts.
- **env-check returns empty output on large repos**: Added `MAX_FILE_SIZE`, `MAX_FILES` (5000), and `GLOBAL_TIMEOUT_SEC` (90s) limits. Now uses `safe_read_file()` instead of raw `open()`.
- **Version inconsistency**: SKILL.md said "v6" but code said "5.7.1". All version references now unified to "6.0.0".
- **CLI version hardcoded**: `codelens.py` description now uses `CODELENS_VERSION` constant instead of hardcoded "v5".

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
