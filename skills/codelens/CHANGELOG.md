# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [5.8.0] — 2026-06-11

### Added

- **`--full` flag for scan command**: Force full rescan even when a registry exists (which would normally auto-enable incremental mode). Usage: `codelens scan --full`.
- **Indonesian colloquial triggers in `ask`**: Documented Indonesian phrases ("kok lama ya", "aneh nih", "bantu cek", "aman ga", etc.) now actually work in the `ask` command's keyword matching.

### Fixed

- **CRITICAL: Class collision semantics wrong**: Classes with multiple HTML references were incorrectly marked as `collision`. In HTML, multiple elements using the same CSS class is valid and normal. Now classes use `duplicate_ref` instead, and `collision` is reserved for IDs (where duplicate IDs are a spec violation).
- **CRITICAL: Edge cleanup after file deletion kept dangling edges**: The `or e.get("from_fn", "") or e.get("to_fn", "")` conditions were always truthy, keeping edges that should have been removed. Simplified to only check if endpoints are in `remaining_ids`.
- **CRITICAL: Frontend class deletion dropped HTML-only entries**: Classes defined only in HTML (no CSS/JS refs) were silently removed during incremental scan. Now matches the ID cleanup pattern with `len(defined_in_html) > 0` check.
- **CRITICAL: Rust parser impl_for tracking never resets**: `current_impl_for` was set when entering an `impl_item` but never reset, causing ALL subsequent functions to be incorrectly tagged. Now uses a scope stack with `end_byte` tracking for proper scope exit detection.
- **CRITICAL: TSX parser scope resolution bug**: Scope resolution always compared against `fn_declarations[0]` instead of finding the tightest enclosing scope, causing call edges to be attributed to the wrong function in nested function scenarios.
- **HIGH: configdrift pyproject.toml parsing broken**: The `in_deps` flag was set but dependency names were never extracted. Now handles both PEP 621 array format and Poetry key-value format.
- **HIGH: sideeffect engine brace counting ignored strings/comments**: Braces inside string literals and comments were counted, causing incorrect function body boundaries and wrong purity classification. Now strips strings/comments before brace counting.
- **HIGH: stacktrace engine stopped at try/catch even if re-throw**: If a catch block re-throws the error, the engine incorrectly stopped tracing. Now detects re-throw patterns and continues tracing. Also fixed Rust `?` operator handling — it propagates errors, not handles them.
- **HIGH: typeinfer Python regex matched keywords**: `class`, `def`, `return`, `if` etc. were matched as variable names, producing nonsense type inferences. Now filters against Python's keyword list.
- **MEDIUM: should_ignore used substring matching**: Pattern `"src/"` would match `src/server/api/auth.ts` incorrectly. Now uses `pathlib.Path.parts` for exact path-segment matching.
- **MEDIUM: Indonesian colloquial triggers not implemented**: Documented in SKILL.md but absent from `ask.py`. Now added with proper keyword weights.
- **MEDIUM: ask.py module-level engine imports**: 20+ engines imported at module level — if any failed, the entire `ask` command broke. Now all engines are lazy-imported inside `_execute_ask_command()`.
- **MEDIUM: Version mismatch**: `utils.py` and `pyproject.toml` said 5.7.0 but CHANGELOG already had 5.8.0 entry. Aligned to 5.8.0.
- **MEDIUM: Duplicate _recompute_class_status/_recompute_id_status**: Identical functions in `incremental.py` merged into single `_recompute_entry_status(entry, entry_type)`.
- **MEDIUM: HTML parser over-aggressive template filtering**: `'{' in attr_value` filtered out any attribute containing `{`. Now only skips JSX expressions (`{...}`) and Jinja/Vue templates (`{{...}}`).
- **MEDIUM: Vue/Svelte parser line number miscalculation**: Line numbers were calculated against processed substrings (with style/script sections removed), resulting in incorrect offsets. Now properly accounts for template offsets.
- **MEDIUM: Tailwind detector false positives**: Common CSS class names like `hidden`, `block`, `relative` were flagged as Tailwind even in non-Tailwind projects. Now only runs detection if Tailwind is configured in the project.
- **MEDIUM: Registry loading error handling missing**: 5 engine files (impact, trace, context, missing_refs, validate) would crash if registry was unavailable. Now all have try/except with graceful fallbacks.
- **MEDIUM: impact_engine BFS duplicated indirect callers**: `current_depth >= 1` was always True since depth starts at 1, duplicating direct callers in the indirect list. Changed to `current_depth > 1`.
- **MEDIUM: deadcode unreachable code state machine**: Only tracked one global terminal state, missing unreachable code after second terminal statement. Now resets `found_terminal` after reporting, allowing detection of multiple unreachable blocks.

## [5.7.0] — 2026-06-11

### Added

- **Shared DEFAULT_IGNORE_DIRS across 22 engines**: All engine files now import `DEFAULT_IGNORE_DIRS` from `utils.py` instead of defining local copies with inconsistent entries. Added `.nuxt` to the shared set. Eliminated ~132 lines of duplicated configuration.

### Changed

- **Query command status consistency**: All 4 found-code-paths in `query.py` now return `status: "ok"` (was missing on 3 paths: frontend class, frontend id, backend function).
- **Comprehensive logging across 15 files**: Replaced 26 bare `except ... pass` blocks with `logger.debug()`/`logger.warning()` calls in: refactor_safe_engine, context_engine, ownership_engine, registry, testmap_engine, sideeffect_engine, deadcode_engine, circular_engine, entrypoints_engine, configdrift_engine, diff_engine, incremental, framework_detect, handbook, and watch.
- **Outline engine logging**: 5 `except Exception: pass` blocks in tree-sitter fallback functions now log at debug level.
- **Convention engine logging**: 5 `except Exception: pass` blocks in semantic detectors now log at debug level.

## [5.6.0] — 2026-06-11

### Added

- **TSX backend extraction**: When tree-sitter-typescript is not installed, TSX files are now parsed with BOTH frontend AND backend fallback parsers. Backend nodes jumped from 124 → 764 (6.2x) on typical Next.js projects.
- **Shared utils module** (`scripts/utils.py`): Centralized `write_output_files`, `compute_summary`, `is_file_path`, `deduplicate_callers`, `DEFAULT_IGNORE_DIRS`, `DEFAULT_IGNORE_EXTENSIONS`, `CODELENS_VERSION`, and `logger`. Eliminates 290+ lines of duplicated code across 5 files.
- **Proper logging**: Replaced 56 `except Exception: pass` blocks with `logger.warning()`/`logger.debug()` calls. Errors are now visible when they occur instead of being silently swallowed.
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

### Fixed

- **TSX files produced zero backend nodes**: When TSXParser failed to import, only CSS class/ID data was extracted. Now uses `parse_js_backend_fallback` on TSX files too.
- **Auto-incremental returned zero counts**: "No changes detected" response had `backend.nodes: 0, backend.edges: 0` even when registry had thousands of entries.
- **Handbook version stale**: Was hardcoded as 5.2.0 in output, now dynamically reads from `CODELENS_VERSION`.

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
