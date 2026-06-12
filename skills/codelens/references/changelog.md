# CodeLens Changelog

## v6.4.0 — 2026-06-12

### Tested against redis/redis (1,844 files: 471 C + 311 H + 20 Lua + 46 Python + 228 TCL + 69 Shell, in-memory database)

### Fixed (5)

- **`is_bundled_file()` missing from `utils.py`** — Broke 4 commands: `ask`, `complexity`, `context`, `perf-hint`. Added function with detection for `deps/`, `vendor/`, `third_party/`, etc.
- **Drupal false positive from `modules/` indicator** — Replaced with `sites/default/` and `sites/all/` which are truly unique to Drupal
- **C/C++ function name false positives** — `void`, `const`, `unsigned`, etc. detected as function names in `smell_engine.py` and `fallback_c.py`
- **C/C++ incorrectly listed as `unsupported_langs`** — Removed since fallback parsers work

### Added (3)

- **C/C++ project framework detection** — `c_project` detected via Makefile/CMakeLists.txt + C source files
- **C/C++ project identity in handbook** — `c-database`, `c-infrastructure`, `c-project` types with Makefile version/name extraction
- **`c_type` in polyglot detection** — C projects included in combined type strings like `c-python-polyglot`

## v5.9.0 — 2026-06-12

### Tested against readest/readest (1,244 files: 1,177 TSX + 40 Rust, Tauri V2 + Next.js 16 ebook reader)

### Added (9)

- **Tauri deep analysis in `binary-scan`** — `scan_tauri_artifacts()` scans Rust source for `#[tauri::command]` functions, maps Rust→camelCase IPC names, parses `tauri.conf.json`, audits capabilities/permissions, detects plugins from Cargo.toml, checks CSP/security, finds sidecars and deep-link schemes
- **Monorepo src-tauri support** — Searches subdirectories for `src-tauri/` (e.g., `apps/app/src-tauri/`)
- **Plugin subdirectory scanning** — Scans `src-tauri/plugins/*/src/` for additional Tauri commands
- **Tauri security analysis** — Checks for missing CSP, enabled asset protocol, dangerous CSP modification, unrestricted IPC commands
- **`src-tauri/Cargo.toml` fallback for Rust detection** — `framework_detect.py` now checks `src-tauri/Cargo.toml` when root has none
- **Deep Cargo.toml scanning** — Recursively scans `src-tauri/plugins/` subdirectories for dependencies
- **`_extract_cargo_deps()` helper** — Eliminates code duplication in Cargo.toml dependency parsing
- **Tauri IPC name conversion** — `_snake_to_camel()` converts Rust snake_case command names to JavaScript camelCase IPC names

### Fixed (4)

- **`binary-scan` crash (ImportError)** — `scan_tauri_artifacts` was imported from `utils` but never implemented, causing every invocation to fail
- **`has_rust: false` for Tauri apps** — Cargo.toml only checked at workspace root, missing `src-tauri/Cargo.toml`
- **Missing Tauri plugin dependencies** — `src-tauri/` was not in the Cargo.toml scan list
- **Regex error in `_scan_rust_tauri_commands`** — Malformed `[\s\n.*?\]` pattern caused `re.error: unterminated character set`

### Tested against BurntSushi/ripgrep (100 Rust files, pure Rust CLI monorepo, 3,749 nodes, 9,449 edges)

### Fixed (7)

- **Critical: `scan`/`handbook` crash** — `get_workspace_outline()` doesn't accept `max_files`. Removed invalid parameter.
- **Critical: `perf-hint` crash** — `detect_perf_hints()` didn't accept `max_files`. Added parameter with file-count limiting.
- **Rust unreachable code false positives (96.5% reduction)** — Multi-line return tracking + if-block scope awareness. 200 → 0 false positives.
- **Rust god object over-counting** — Brace-depth-scoped `impl` method counting. Each impl block counted separately. Critical smells: 54 → 35.
- **Rust doc comment false positives** — `///` and `//!` skipped in debug-leak `commented_code`. 753 → 158.
- **`is_monorepo` inconsistency** — `summary` now uses `_extract_project_identity` (same as `handbook`).
- **Markdown dataflow violation rendering** — Proper `source:line → sink:line` format.

## v6.2.0 — 2026-06-12

### Added (8)

- **C/C++ fallback parser** — `parsers/fallback_cpp.py`: Regex-based parser for `.c`, `.h`, `.cpp`, `.hpp`, `.cc`, `.cxx`, `.hxx`. Extracts functions, methods, structs, typedefs, preprocessor macros, and call edges.
- **Go fallback parser** — `parsers/fallback_go.py`: Regex-based parser for `.go`. Extracts functions, methods, types, and call edges.
- **C/C++ and Go outline support** — `outline_engine.py`: Added `_outline_cpp()` and `_outline_go()`.
- **C/C++ and Go complexity analysis** — `complexity_engine.py`: Added `_extract_cpp_functions()`, `_extract_go_functions()`, `_count_cpp_decisions()`, `_count_go_decisions()`.
- **C/C++ and Go scan integration** — `commands/scan.py`: C/C++ and Go data now included in backend registry.
- **Tauri IPC edge resolver** — `edge_resolver.py`: Implemented `resolve_tauri_ipc_from_apimap()` with snake_case ↔ camelCase matching.
- **Shared performance utilities** — `utils.py`: Added `MAX_FILE_SIZE`, `MAX_FILES_DEFAULT`, `time_budget_expired()`.
- **C/C++ and Go extensions in all engines** — Updated SOURCE_EXTENSIONS in 17 engine files.

### Bug Fixes (4)

- **CRITICAL: Import error crash** — `scan.py`, `handbook.py`, `watch.py` crashed because `resolve_tauri_ipc_from_apimap` was not defined. Now implemented.
- **CRITICAL: Import error crash** — `ask.py`, `env_check.py` crashed because `MAX_FILE_SIZE`, `MAX_FILES_DEFAULT`, `time_budget_expired` were not in `utils.py`. Now added.
- **CRITICAL: C/C++ files scanned but never parsed** — Scan discovered C/C++ files but returned 0 nodes/edges. Now parsed with `fallback_cpp.py`.
- **CRITICAL: Go files scanned but never parsed** — Same as C/C++. Now parsed with `fallback_go.py`.

## v5.7.2 — 2026-06-12

### Bug Fixes (7)

- **CRITICAL: Trace markdown formatter displayed paths character-by-character** — `_md_trace()` treated the `path` string field as an iterable list, producing output like `p → a → c → k → a → g → e → s`. Introduced `_format_trace_chain()` helper with proper string/list handling, depth indentation, and cyclic/unresolved markers.
- **CRITICAL: TS/JS backend parser missed arrow functions in parentheses or `as` expressions** — `const name = ((...args) => {})` and `const name = (() => {}) as Type` were not captured. Added `_unwrap_fn_from_parens()` and `as_expression` handling to both parsers.
- **HIGH: Framework detection missed Rust/Python polyglot projects** — Ruff showed "No frameworks" and "cjs". Added `module_system` for Cargo/Python/polyglot, `languages` field, and `has_rust_backend` from `Cargo.toml` presence.
- **HIGH: Zombie CSS false positives with invalid class names** — Class names like `.(version`, `.===`, `.\`@${...}\`` were reported. Added CSS class name regex validation and character blacklist.
- **HIGH: God object detection massive false positives in JS/TS** — Regex matched `if(`, `for(`, etc. Rewrote to extract class bodies first via brace-depth matching, then count methods. Also scoped Rust `fn` counting to each `impl` block.
- **MEDIUM: API map included test fixture routes** — Added filtering for `/test/`, `/fixtures/`, `*.test.*`, `*.spec.*` paths.
- **MEDIUM: Framework detect markdown missing flags** — Added display for FastAPI, Flask, Django, Tauri, Rust, monorepo, and lockfile fields.

## v5.8.1 — 2026-06-12

### Bug Fixes (3)

- **CRITICAL: `should_ignore_dir` missing from `utils.py`** — The function was imported by `framework_detect.py` and `tailwind_detector.py` but never defined in `utils.py`, causing an `ImportError` that prevented the entire CLI from starting. Added the function with path-segment-aware matching (e.g., `test-target` does NOT match `target`).
- **Secrets engine false positives on Rust type annotations** — Patterns like `password: String`, `password: Option<String>`, and `password: verge.webdav_password.clone()` were incorrectly flagged as hardcoded secrets. Added context-aware filtering: `_is_rust_type_annotation()` checks if the value is a Rust type or variable reference, `_is_js_property_assignment()` checks for JS/TS non-literal property values, `_is_locale_file()` skips i18n translation files, and `_is_schema_type_ref()` skips JSON/YAML schema type references.
- **YAML password pattern too permissive** — The pattern `password:\s*["\']?([^\s"\']{6,})["\']?` matched unquoted variable references like `password: data.password`. Changed to require quotes: `password:\s*["\']([^"\']{6,})["\']`.

### Improvements (2)

- **Rust/Tauri workspace support** — Enhanced framework detection for Tauri apps with `crates/` workspace structure. The `should_ignore_dir` utility now correctly handles Cargo workspace directories.
- **SAFE_VALUE_PATTERNS expanded** — Added Rust/Swift/Kotlin type names (`String`, `Option`, `Some`, `Vec`, etc.), primitive types (`i32`, `u64`, etc.), generic type parameters, encode/decode function names, and localization key patterns to reduce false positives.

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
