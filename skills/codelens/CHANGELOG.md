# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semav.org/spec/v2.0.0.html).

## [5.10.0] — 2026-06-12

### Polyglot Expansion — 6 New Language Parsers

**Tested against a polyglot monorepo with 7 languages (Ruby, Elixir, Kotlin, Swift, Dart, Scala, Shell)**

Real-world test on a multi-language project with 56 source files across 7 languages.
Results: 609 backend nodes, 1,090 edges, 129 active nodes, 94 API routes.
Before: Only 8 Kotlin files parsed (103 nodes, 0 edges, 0 routes).

#### New Language Parsers (regex-based fallback)

- **Ruby** (`fallback_ruby.py`): Classes, modules, methods (instance & class), attr_accessor/reader/writer,
  Rails patterns (before_action, has_many, belongs_to, validates, scope), require/require_relative,
  include/extend, method call edges
- **Elixir** (`fallback_elixir.py`): defmodule, def/defp, defmacro/defmacrop, use/import/alias/require,
  Phoenix routes (get/post/put/patch/delete), scope, pipe_through, Ecto schemas (field, has_many, belongs_to),
  GenServer patterns, pipe operator call chains (|>)
- **Dart** (`fallback_dart_extra.py`): Classes, abstract classes, mixins, extensions, enums, typedef,
  factory constructors, Flutter widget detection (StatefulWidget/StatelessWidget),
  import/export/part, method call edges
- **Swift** (`fallback_swift.py`): Classes, structs, protocols, extensions, enums, actors,
  SwiftUI View detection, ObservableObject, async/await patterns, import dependencies,
  inheritance tracking
- **Scala** (`fallback_scala.py`): Classes, case classes, objects, traits, sealed traits/classes,
  implicit functions, Spark patterns, SBT build detection, package/import dependencies,
  extension method calls
- **Shell/Bash** (`fallback_shell.py`): Function definitions, export variables,
  source/. dependencies, Dockerfile patterns (FROM, RUN, ENTRYPOINT, CMD),
  function call edges

#### New Framework Detection

- **Rails**: Gemfile, config/routes.rb, app/controllers/, app/models/ directory indicators
- **Phoenix**: mix.exs, config/config.exs, lib/*_web/endpoint.ex indicators
- **Flutter**: pubspec.yaml, lib/main.dart directory indicators
- **SwiftUI**: Package.swift, import SwiftUI indicators
- **Vapor**: Package.swift, import Vapor indicators
- **Spark**: build.sbt, import org.apache.spark indicators
- **Akka**: build.sbt, import akka indicators
- **Play Framework**: build.sbt, conf/application.conf indicators

#### New API Route Extraction

- **Rails** (`routes.rb`): get/post/put/patch/delete, resources, namespace, root
- **Phoenix** (`router.ex`): get/post/put/patch/delete, resources, scope, pipe_through

#### New Outline Support

- Ruby: modules, classes, methods (instance & class), require
- Elixir: defmodule, def/defp/defmacro, use/import/alias/require
- Dart: classes, mixins, enums, extensions, functions, imports
- Swift: classes, structs, protocols, extensions, enums, functions, imports
- Scala: case classes, classes, traits, objects, enums, functions, imports
- Shell: functions, exports, Dockerfile FROM patterns

#### Other Changes

- Updated `unsupported_langs` to remove Ruby, Elixir, Dart, Swift, Scala, Shell (now parsed)
- Added Kotlin to detected-but-not-unsupported (Java fallback parses .kt files)
- Extended `_detect_language()` mapping with 14 new extensions
- Extended `_FILE_PATH_EXTENSIONS` with new language extensions
- Updated `lang_note` supported set and language name mapping
- Added framework-specific path configurations for Rails, Phoenix, Flutter, SwiftUI, Vapor, Spark, Akka, Play
- File discovery: .rb, .ex, .exs, .dart, .swift, .scala, .sh, .bash, .zsh, .rake, Dockerfile, Rakefile, Gemfile, mix.exs

## [6.1.0] — 2026-06-12

### Tested against minetest/minetest (2,430 files: 598 C++ headers + 445 C++ + 206 Lua + 40 GLSL, CMake/C++ game engine with Lua scripting)

Real-world test on a polyglot C++/Lua/GLSL voxel game engine (Luanti/Minetest). This is the first
test on a non-web, non-API-server project — a native C++ game engine with embedded Lua scripting,
GLSL shaders, and Android Java support. Identified and fixed major gaps in project identity detection,
language classification, entry point detection, and tooling recommendations for native/C++ projects.

### Added

- **CMake project identity detection**: `_extract_project_identity()` now parses `CMakeLists.txt` for `project(Name VERSION X.Y.Z)`, extracting project name and version. Classifies CMake projects as `cpp-game-engine` (C++ + Lua scripting), `qt-desktop-app`, `cpp-graphics`, `cpp-mobile-app`, or `cpp-project` based on CMakeLists.txt content and directory structure.
- **Lua entry point detection**: New `lua_entry` entrypoint type with 4 patterns: `dofile()`, `require()`, `core.register_*()` (Luanti/Minetest API), and `minetest.register_*()` (legacy Minetest API). These detect game mod registration, script loading, and module initialization patterns.
- **C++ entry point detection**: Added 4 new C++ entry point patterns: `WinMain` (Windows GUI), `wmain` (Unicode console), `SDL_main` (SDL game), `DllMain` (DLL entry). These cover the most common Windows/native application entry points beyond `int main()`.
- **Game engine directory hints**: `_build_directory_map()` now recognizes 18 new directory names common in game engines and native C++ projects: `builtin`, `mods`, `games`, `textures`, `fonts`, `shaders`, `client`, `clientmods`, `irr`, `android`, `po`, `worlds`, `include`, `cmake`, `fastlane`, `misc`, etc.
- **GLSL shader language detection**: `_detect_languages()` now recognizes `.glsl`, `.fsh`, `.vsh`, `.frag`, `.vert` extensions as `glsl` language.
- **CMake language detection**: `.cmake` extension recognized as `cmake` language.
- **Game/native framework signatures**: Added 4 new framework signatures in `FRAMEWORK_SIGNATURES`: `sdl` (SDL_Init/SDL_main), `irrlicht` (IrrlichtDevice), `opengl` (glGenBuffers/glBindVertexArray), `vulkan` (VkInstance/vkCreateInstance).
- **Lua debug leak patterns**: Added 3 new debug leak patterns for Lua: `debug.debug()`, `debug.traceback()`, `debug.dump()`.
- **C++/Lua/GLSL tooling recommendations**: `_generate_recommendations()` now suggests `clang-tidy` + `cppcheck` for C++ projects, `luacheck` + `lua-language-server` for Lua projects, and `glslangValidator` for GLSL shaders.
- **CMake/Lua path configuration**: `get_recommended_config()` adds `src/`, `lib/`, `include/` for CMake projects, and `builtin/`, `scripts/`, `mods/` for Lua-scriptable projects.
- **CMake `has_cmake` flag**: Framework detection now sets `has_cmake` when CMakeLists.txt is found.

### Fixed

- **`.h` headers classified as C instead of C++**: `_detect_languages()` mapped `.h` → `"c"`, but most `.h` files in C++ projects are C++ headers. Now maps `.h` → `"cpp"`, `.hpp` → `"cpp"`, `.hxx` → `"cpp"`.
- **C/C++ listed as unsupported languages**: `UNSUPPORTED_MARKERS` in `framework_detect.py` listed C and C++ as unsupported even though fallback parsers exist for both. Removed C, C++, Java, and Kotlin from `UNSUPPORTED_MARKERS` — all have working fallback parsers.
- **Architecture `total_files` only counting tree-sitter-supported files**: `analyze` command showed `total_files: 7` for a 2430-file C++ project because `get_workspace_outline()` only processes tree-sitter-supported languages. Now counts ALL source files across all supported extensions (including .cpp, .h, .lua, .glsl, etc.) and uses `max(outlined, actual)`.
- **Project type `unknown` for CMake/C++ projects**: `_extract_project_identity()` returned `type: "unknown"` and `version: "0.0.0"` for CMake projects because it only checked `package.json`, `pyproject.toml`, `Cargo.toml`, and `go.mod`. Now also checks `CMakeLists.txt`.
- **Polyglot type detection missing C++**: The combined type detection (`active_types`) only checked `[js_type, python_type, rust_type, go_type]`. Now also includes `cmake_type`, producing types like `cpp-lua-polyglot` for C++ game engines with Lua scripting.

## [6.5.0] — 2026-06-12

### Tested against SerenityOS/serenity (18,601 source files: 7,447 C/C++, 1,814 HTML, 1,098 JS, 26 Python, C++ OS monorepo)

Real-world test on a complete from-scratch desktop operating system (33.4k stars) with custom kernel,
userspace libc, GUI toolkit, JS engine (LibJS), and web browser (Ladybird). The largest and most
architecturally diverse repo tested to date.

### Added

- **C++ project identity detection**: `handbook` now recognizes C++ projects via `CMakeLists.txt`.
  Extracts project name from `project(Name)` and version from `project(Name VERSION x.y.z)`.
  Detects three C++ project types: `cpp-os` (Kernel/ directory exists), `cpp-monorepo` (≥3 of
  AK/Base/Meta/Ports/Tests directories), and `cpp-project` (default CMakeLists.txt-based).
- **CMake monorepo detection**: Projects with ≥2 subdirectory `CMakeLists.txt` files are detected
  as monorepos with `monorepo_tools: ["cmake-workspace"]`. Also triggered when Kernel/ directory
  exists alongside root CMakeLists.txt.

### Fixed

- **C/C++ removed from `unsupported_langs`**: When fallback C/C++ parsers successfully parse files
  (7,447 in SerenityOS), `c` and `cpp` are removed from the unsupported languages list. The
  `lang_note` now reads "parsed via fallback parsers (7447 files)" instead of the misleading
  "not yet supported by tree-sitter parsers".
- **God object test file false positives**: JS/TS test files in `/Tests/`, `/tests/`, `/test/`,
  `/__tests__/`, `/spec/`, `/specs/` directories are now skipped with **case-insensitive** matching.
  Previously, capitalized paths like `LibJS/Tests/` were not caught. 52 false positives eliminated
  on SerenityOS (critical smells: 1,037 → 985).

## [5.9.2] — 2026-06-12

### Tested against vercel/swr (254 source files: 114 TSX + 99 JS backend + 34 JS frontend, React+Next.js monorepo)

Real-world test on a TypeScript/React data-fetching library. Confirmed significant false positive reduction
across all analysis engines after targeted fixes based on SWR analysis findings.

### Fixed

- **Dataflow `command_exec` false positives** (79% reduction: 19 → 4 violations): `Function\s*\(` regex matched `isFunction()`, `createFunction()`, etc. Added word boundary `(?:^|[^\w.])Function\s*\(` to only match the bare JS `Function` constructor. Same fix applied to `exec(?:Sync)?\s*\(` which matched `execQuery()`, `execSql()`. These utility type-checks and database helpers are NOT command execution sinks.
- **Smell `long_fn` reports test files** (9% critical reduction: 43 → 39): `_detect_long_functions()` did not skip test/story/fixture files. Added same `_skip_keywords` filter that `_detect_deep_nesting()` already uses (`'.test.', '.spec.', '.fixture.', '.stories.', '.story.', '__tests__'`). Long test blocks are expected and not actionable.
- **A11y engine scans test files** (85% reduction: 122 → 18 issues): No test file exclusion existed in the accessibility scan loop. Added skip filter for test/spec/story/fixture files. Mock JSX in test files (`<img />` without alt, `<button>` without keyboard handler) are not real accessibility issues.
- **Dead code `unused_vars` false positives** (94% reduction: 51 → 3): `_detect_unused_variables()` flagged exported variables as unused because it only checked single-file usage. Added `exported_names` collection (named exports, re-exports, default exports) and skip them. Also expanded `skip_names` with common patterns (`result`, `data`, `value`, `options`, `args`, `params`, `callback`, `next`, `dispatch`, `action`, `payload`).
- **Dead code `registry_dead` test file false positives** (37% reduction: 200 → 127): `_detect_dead_from_registry()` only checked directory paths (`/test`, `/tests`), missing filename patterns like `.test.ts`, `.spec.tsx`. Added `.test.`, `.spec.`, `.e2e.`, `.stories.`, `.story.` patterns and `/__tests__/`.
- **Module system detection wrong for TypeScript projects** (cjs → esm): `framework_detect.py` defaulted to `"cjs"` when `package.json` lacked `"type": "module"`. Many TS projects compile to ESM without this field. Added detection of `tsconfig.json` `compilerOptions.module`, `.mjs`/`.cjs` file extensions, and `exports` field with `"import"` key. Reports `"mixed"` when both ESM and CJS indicators exist.
- **Context engine fuzzy matching too loose**: Used pure substring match sorted by shortest name. Ported scoring logic from `query.py`: exact case-insensitive match priority, active vs dead status priority, ref_count (popularity) ranking. Prevents `"use"` matching `"refuse"` and prefers the most relevant function.
- **Version mismatch**: `CODELENS_VERSION` was `"5.8.1"` while `pyproject.toml` was `"5.9.1"`. Both now synced to `"5.9.2"`.
- **`pyproject.toml` parse error**: `description` and `readme` fields were concatenated on one line. Fixed line break.

## [5.9.0] — 2026-06-12

### Tested against database & XHR/network repos

Real-world testing on 5 diverse open-source repositories:
- **redis/redis** (30MB, 789 C/H files, 19,030 backend nodes) — C in-memory database
- **axios/axios** (5.5MB, 201 JS/TS files, 436 backend nodes) — JavaScript HTTP client
- **libuv/libuv** (7.4MB, 364 C/H files, 6,590 backend nodes) — C networking/event loop
- **nodejs/undici** (11MB, 619 JS/TS files, 1,078 backend nodes) — Node.js HTTP/1.1 client
- **google/leveldb** (1.9MB, 132 C++/H files, 1,557 backend nodes) — C++ key-value database

### Fixed

- **`binary-scan` command crash (ImportError)**: `scan_tauri_artifacts` was imported but never implemented in `utils.py`. The `binary-scan` command would always crash with `cannot import name 'scan_tauri_artifacts' from 'utils'`. Added full implementation: detects Tauri config files, IPC commands from Rust source, capabilities/permissions, sidecar binaries, updater config, WebView security settings, and deep-link schemes. Returns `None` for non-Tauri projects (graceful skip).
- **Drupal false positive from `modules/` directory**: Redis was incorrectly detected as a Drupal project because `modules/` and `themes/` were Drupal indicators. These are too generic — many non-Drupal projects have `modules/` directories (e.g., Redis modules, Go modules). Changed Drupal indicators to `sites/default/` and `sites/all/` (Drupal-specific paths), and added `sites/default/settings.php` as a config file. Redis is no longer falsely detected as Drupal.
- **`new ClassName()` not tracked as call edge**: JS/TS/TSX parsers only tracked `call_expression` nodes (e.g., `funcName()`) but not `new_expression` nodes (e.g., `new AxiosError()`). This caused classes that are only instantiated via `new` to appear as "dead" in dead-code analysis. AxiosError (core Axios class, used in 17+ files) had `ref_count: 0` and `status: dead`. Added `_parse_new_expression()` to all three parsers (js_backend_parser, ts_backend_parser, tsx_parser). After fix: AxiosError correctly shows `ref_count: 29` and `status: active` with 11 callers.
- **pyproject.toml formatting error**: `description` and `readme` fields were merged on a single line, causing TOML parse failure.

### Added

- **HTTP/network library detection**: `detect_frameworks()` now recognizes 7 HTTP client libraries as frameworks: `axios`, `undici`, `got`, `ky`, `superagent`, `node-fetch`, `request`. Added `has_http_library` flag to detection output. Works both when the library is a dependency AND when the repo IS the library itself (checks `package.json` `name` field).
- **`scan_tauri_artifacts()` in utils.py**: Full Tauri RE analysis — IPC command/handler mapping from Rust source, capabilities/permissions security audit, sidecar binary detection, updater configuration, WebView CSP/asset-protocol security, deep-link scheme analysis, and risk assessment summary.
- **New framework signatures**: Added 7 HTTP library signatures with packages and `has_http_library` flag support.

### Changed

- **Version bump**: 5.8.1 → 5.9.0

## [5.8.1] — 2026-06-12

### Tested against cockroachdb/cockroach (10,112 source files: 9,439 Go + 183 Proto, 555MB Go database)

Real-world test on a pure Go distributed SQL database with 116,033 backend nodes and 113,338 edges.
Confirmed: 2,287 smells (health score 70), 200 dead items, 106 circular deps, 11,291 debug leaks,
1,716 entrypoints, 13 secrets, 4 CVEs, 32 API routes, 15 state stores.

### Added

- **Go project type detection in handbook**: `handbook` now parses `go.mod` to extract module name, Go version, and classify Go projects into types: `go-database`, `go-web-service`, `go-grpc-service`, `go-infrastructure`, `go-project`. Module name extraction (e.g., `github.com/cockroachdb/cockroach` → name: `cockroach`, version from `go` directive).
- **Go framework content-based detection**: `detect_frameworks()` now reads `go.mod` content instead of just checking file existence. Detects `gin`, `echo`, `fiber`, `chi`, `mux`, `grpc`, `protobuf` only when the dependency string actually appears in go.mod. Prevents false positives where every Go project was classified as gin/echo.
- **Go-specific code indicators for debug-leak**: Added `code_indicators_go` with Go-specific patterns (`func`, `var`, `const`, `type`, `:=`, `chan`, `select`, `defer`, `range`). Previously defaulted to JS indicators which caused massive over-detection.
- **License block detection in debug-leak**: `_score_commented_code_likelihood()` now returns 0 for comment blocks that start with copyright/license keywords (copyright, SPDX, Apache License, BSD, MIT, GPL, etc.). Eliminates thousands of false positives from license headers.

### Fixed

- **`get_workspace_outline()` TypeError**: `write_output_files()` in `utils.py` called `get_workspace_outline(workspace, max_files=max_files)` but the function doesn't accept `max_files`. Removed invalid keyword argument.
- **`perf-hint` TypeError crash**: `perf_hint.py` called `detect_perf_hints(workspace, ..., max_files=5000)` but the function doesn't accept `max_files`. Removed invalid keyword argument.
- **gin/echo false positive for Go projects**: Every Go project with a `go.mod` was incorrectly classified as using gin and echo frameworks because both had `"config_files": ["go.mod"]`. Changed to `config_files: []` and use content-based detection instead.
- **Go listed as "unsupported language"**: Go has a fallback parser (`fallback_go.py`) and is actively parsed during scan, but was still listed in `unsupported_langs` with the message "not yet supported by tree-sitter parsers". Removed Go from the unsupported markers list.
- **Handbook `type: unknown` and `version: 0.0.0` for Go projects**: Go projects without package.json or Cargo.toml had no identity detection. Added `go.mod` parsing to extract name, version, and type classification.
- **Debug-leak Go commented_code false positives**: Go projects use multi-line `//` comments heavily for godoc, generating 22,433 false "commented code" findings on cockroachdb. Fixed by: (1) requiring 5+ consecutive lines for Go (vs 3 for other languages), (2) requiring score ≥ 3 for Go (vs 2), (3) adding Go-specific code indicators, (4) skipping license/copyright blocks. Result: 22,433 → 6,734 (70% reduction).

### Changed

- **Go project classification priority**: Module name patterns (cockroachdb, postgres, mysql, etc.) now take priority over dependency-based classification for more accurate type detection.
- **Version bump**: 5.8.0 → 5.8.1

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
