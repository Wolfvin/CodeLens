# CodeLens Changelog

All notable changes to CodeLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepa.changelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/html).

## [7.2.0] — 2026-06-12

### Tested against laravel/framework (2,934 files: 2,801 PHP + 124 Blade + 3 JS + 2 CSS + 4 Shell, PHP framework monorepo)

Real-world test on a pure PHP framework project — the Laravel framework source code itself.
This exposed critical blind spots across 10+ engines that had zero PHP support, despite PHP
being one of the most popular web languages. Prior testing covered JS/TS, Python, Rust, Go,
C/C++, GDScript, and Lua — but never PHP.

### Fixed

- **CRITICAL: `outline_engine.py` PHP class methods not extracted** — `_outline_php()` only extracted top-level standalone functions (`indent == 0`), completely skipping methods inside class/interface/trait/enum bodies. For a typical PHP class with 10 methods, 0 were counted. This caused `total_functions: 11` for 2,801 PHP files (only 11 files had standalone functions). Added brace-depth tracking to capture methods with visibility modifiers, static/abstract flags.

- **CRITICAL: `statemap_engine.py` `.php` not in `SOURCE_EXTENSIONS`** — The engine skipped ALL PHP files entirely (0 stores, 3 files scanned). Added `.php` to `SOURCE_EXTENSIONS`, PHP keyword/builtin skip lists, and `_extract_php_state()` function detecting: PHP superglobals (`$_SESSION`, `$_GET`, `$_POST`), Laravel Config state (`Config::get/set/has`, `config()`), Laravel Facade state (`Cache::`, `Session::`, `DB::`, `Redis::`), and Eloquent model state (`$fillable`, `$hidden`, `protected static $`). Result: 0 → 173 stores.

- **CRITICAL: `dataflow_engine.py` `.php` not in `SOURCE_EXTENSIONS` + zero PHP patterns** — The engine had no PHP source/sink/sanitizer patterns. All PHP files were skipped (1 source, 0 sinks, 3 files). Added PHP superglobal sources (`$_GET/POST/REQUEST/COOKIE/SERVER`), Laravel request sources (`$request->input()`, `request()->all()`, `Input::get()`), PHP env sources (`env()`, `getenv()`, `$_ENV`), PHP SQL sinks (`DB::raw`, `DB::select`, `mysqli_query`, `PDO::query`), PHP command exec sinks (`exec()`, `shell_exec()`, `system()`, `Artisan::call()`), PHP file write sinks, PHP sanitizers (`htmlspecialchars`, `PDO::prepare`, `$request->validate()`, `filter_var()`). Result: 1 → 1,155 sources, 0 → 711 sinks, 18 taint violations.

- **CRITICAL: `sideeffect_engine.py` `.php` not in `SOURCE_EXTENSIONS` + zero PHP patterns** — The engine skipped all PHP files (0 functions, 3 files). Added `.php` to extensions, 7 PHP side-effect pattern groups (php_io, php_output, php_network, php_database, php_state, php_external, php_random — 51 total patterns), PHP function extraction with visibility modifiers, PHP magic method skip list. Result: 0 → 25,830 functions, 2,175 impure, 9.3s elapsed.

- **`framework_detect.py` `has_laravel` false on laravel/framework itself** — When the repo IS the framework, `composer.json` doesn't list itself in `require`. The `name` field (`"laravel/framework"`) and `replace` section (all `illuminate/*` packages) were never checked. Added `composer.json` `name` field check and `replace` section check for framework self-detection. Also added `src/Illuminate/` as Laravel indicator and `symfony/symfony` to Symfony composer_packages.

- **`smell_engine.py` no PHP god-object/deep-nesting/many-params detection** — PHP code quality smells were completely missed. Added PHP class method/property counting for god-object detection (brace-depth tracked), PHP brace-based deep nesting detection, and PHP function parameter counting with visibility modifier support. Result: 0 → 162 god_objects, 0 → 407 deep_nesting, 0 → 161 many_params.

- **`secrets_engine.py` PHPUnit test file patterns missing** — Files named `*Test.php` and `*TestCase.php` (standard PHPUnit conventions) were not recognized as test files, causing false positives. Added `Test.php` and `TestCase.php` to test file patterns. Also added `env()`, `getenv()`, `$_ENV`, `config()` to environment reference patterns. Fixed critical false positive in DbCommand.php where `$connection['password']` variable reference was flagged as hardcoded secret — now downgraded when PHP variable `$` is present.

- **`entrypoints_engine.py` no Laravel scheduled/queue/event entry points** — Added detection for: `$schedule->command()/call()/job()/exec()` (scheduled tasks), `implements ShouldQueue` (queue jobs), `dispatch()` calls (queue dispatch), `Event::listen()` (event listeners), `$listen` property in EventServiceProvider (event provider). Result: 0 → 56 cron_job entry points, 1 event_handler detected.

- **`handbook.py` version `"0.0.0"` for PHP projects** — `composer.json` commonly omits `version` field (managed via git tags). Added fallback chain: git tags → VERSION file → CHANGELOG.md version headers → composer.json `extra.branch-alias`. Result: `"0.0.0"` → `"13.15.0"`.

- **`handbook.py` wrong conventions for PHP projects** — Showed `import_style: "ES modules"` and `module_system: "ESM"` for pure PHP projects. Now detects PHP projects and overrides to `import_style: "composer_autoload"`, `module_system: "Composer"`, `error_handling: "exceptions"`. Added PHP naming conventions (PascalCase classes, camelCase methods).

- **`handbook.py` wrong directory descriptions for PHP/Laravel** — `config-stubs/` showed as "directory", `types/` as "TypeScript type definitions", `src/` as generic "Application source code". Now has Laravel-specific descriptions: "Laravel configuration stubs", "PHP type definition stubs", "Laravel framework source code (Illuminate components)", etc.

- **5 engines timeout on large PHP projects** — `smell`, `dead-code`, `complexity`, `entrypoints`, `api-map` all timed out on 2,801 PHP files. Added `MAX_FILES` and `TIMEOUT_SEC` constants with early-exit checks in scanning loops: smell (5,000 files / 120s), deadcode (5,000 / 120s), complexity (5,000 / 120s), entrypoints (5,000 / 120s), apimap (5,000 / 120s). All commands now complete within time limits.

### Added

- **PHP class method extraction in outline** — Methods inside classes, interfaces, traits, and enums are now extracted with visibility (public/private/protected), static, and abstract flags. Populates `methods` array in class entries.
- **PHP/Laravel state management detection** — Detects Laravel Config stores, Facade state, Eloquent model state, and PHP superglobals.
- **PHP taint analysis** — Full PHP source → sink → sanitizer data flow tracking with Laravel-specific patterns.
- **PHP side-effect analysis** — 51 PHP-specific side-effect patterns across IO, output, network, database, state, external service, and randomness categories.
- **PHP code smell detection** — God-object (method+property counting), deep nesting (brace-depth), many parameters (with type hints and variadic params).
- **Laravel entry point detection** — Scheduled tasks, queue jobs, event listeners, and event providers.
- **composer.json self-detection** — Checks `name` field and `replace` section for framework identity (when the repo IS the framework).
- **PHPUnit test file recognition** — `*Test.php` and `*TestCase.php` patterns.
- **PHP environment reference detection** — `env()`, `getenv()`, `$_ENV`, `config()`.
- **Timeout protection** — 5 additional engines now have file count and time limits for large codebases.
- **PHP convention detection** — Correct `composer_autoload` / `Composer` / `exceptions` for PHP projects.

## [6.4.0] — 2026-06-12

### Tested against exercism/python (2,227 files, 516 Python files, pytest-based exercise track)

Real-world test on a pure Python project with no web frameworks — exposed multiple blind spots
in framework detection, project identity classification, and broken command imports.

### Fixed

- **`is_bundled_file` missing from `utils.py`** (CRITICAL): `complexity_engine.py` and `perfhint_engine.py` imported `is_bundled_file` from `utils`, but the function never existed. This caused `ImportError` during command registration, silently breaking `complexity`, `perf-hint`, `ask`, and `context` commands (4 of 45 commands non-functional). Added `is_bundled_file()` to `utils.py` with detection for dist/build/vendor dirs, minified files, source maps, and common bundled naming patterns.
- **`analyze` command env check used wrong API** (CRITICAL): `_detect_env()` called `audit_environment()` which doesn't exist — the correct function is `check_env_vars()`. Also used wrong return keys (`total_issues`, `issues` instead of `total_vars`, `required_without_fallback`). The `env_issues` category was always skipped in analysis output.
- **`analyze` command hardcoded version**: Output showed `codelens_version: "6.0"` instead of using `CODELENS_VERSION` constant (was `6.3.0`). Now imports from `utils.py`.
- **`pyproject.toml` formatting error**: Missing newlines between `description`/`readme` and `requires-python`/`authors` caused TOML parse failure.

### Added

- **Python tooling framework detection**: Added 7 new Python framework signatures: `pytest`, `poetry`, `setuptools`, `tox`, `sphinx`, `nox`, `hatch`. Includes `pip_packages`, `config_files`, and `indicators` for each. Added `has_pytest`, `has_poetry`, `has_python` flags to detection output.
- **Pipfile dependency parsing**: Comment said "Check Python dependency files (requirements.txt, pyproject.toml, Pipfile)" but Pipfile was never actually parsed. Now parses `[packages]` and `[dev-packages]` sections.
- **Improved pyproject.toml Poetry dependency parsing**: Poetry uses list-style deps like `dependencies = ["requests>=2.0", "flask"]` and section-scoped deps under `[tool.poetry.dependencies]`. Added section-aware TOML parsing for Poetry and PEP 621 dependency formats.
- **Python project identity fallback**: `_extract_project_identity()` now detects Python projects from `requirements.txt` (with content analysis: web framework → `backend-api`, testing → `python-test-suite`, else → `python-project`), `setup.py`/`setup.cfg` → `python-library`, and `.py` file existence → `python-project`. No more `type: "unknown"` for pure Python repos.
- **`scan_tauri_artifacts()` implementation**: `binary_scan.py` imported `scan_tauri_artifacts` from `utils` but it didn't exist (gracefully caught by try/except). Now implemented: parses `tauri.conf.json` for IPC commands, security settings (CSP, asset protocol), sidecar binaries, and warns about dangerous patterns.
- **Command import error logging level**: Changed from `WARNING` to `ERROR` in `commands/__init__.py` so broken command modules are more discoverable.
- **`.py` file detection in framework walk**: Added Python file detection alongside `.vue`, `.svelte`, `.php` in the file pattern walking loop, setting `has_python: True`.

## [6.4.0] — 2026-06-12

### Tested against redis/redis (1,844 files: 471 C + 311 H + 20 Lua + 46 Python + 228 TCL + 69 Shell, in-memory database)

Real-world test on a pure C project with Makefile build system, embedded Lua scripting,
and polyglot codebase (C+Lua+Python+TCL+Shell). Exposed critical gaps in C/C++ project
support that were invisible on JS/TS/Rust/Go projects.

### Fixed

- **`is_bundled_file()` missing from `utils.py`**: `perfhint_engine.py` and `complexity_engine.py` imported `is_bundled_file` from `utils`, but the function was never defined there. This broke 4 commands silently: `ask`, `complexity`, `context`, `perf-hint`. Added `is_bundled_file()` to `utils.py` with detection for `deps/`, `vendor/`, `third_party/`, `external/`, `submodules/`, and minified/bundled file patterns.

- **Drupal false positive from `modules/` indicator**: Redis (and many non-Drupal projects) have a `modules/` directory, which was listed as a Drupal indicator. Replaced `modules/` and `themes/` with `sites/default/` and `sites/all/` — directories that are truly unique to Drupal installations. This eliminates the false positive on Redis and similar C projects with module systems.

- **C/C++ function name false positives in `smell_engine.py`**: The regex `r'(?:static\s+|inline\s+)*(?:\w+[\s*]+)+(\w+)\s*\('` matched C type keywords like `void`, `const`, `unsigned`, `signed`, `volatile`, `extern`, `register`, `auto`, `static`, `inline` as function names, producing absurd findings like "Function 'void' is 248 lines". Added all C type keywords and storage-class specifiers to the skip list.

- **C/C++ function name false positives in `fallback_c.py`**: Same issue as smell_engine — the parser's skip list was missing `void`, `const`, `unsigned`, `signed`, `volatile`, `extern`, `register`, `auto`, `static`, `inline`. Extended the skip list to match.

- **C/C++ listed as `unsupported_langs`**: Despite having working fallback parsers (790 C/C++ files successfully parsed on redis/redis), C and C++ were listed in `UNSUPPORTED_MARKERS` in `framework_detect.py`, causing the scan output to say "these languages are not yet supported". Removed C/C++ from `UNSUPPORTED_MARKERS` since they have fallback parser support.

### Added

- **C/C++ project framework detection**: Added `c_project` framework detection in `framework_detect.py` when a Makefile/CMakeLists.txt is found alongside C/C++ source files. This gives C projects proper framework recognition instead of empty framework lists.

- **C/C++ project identity detection in handbook**: Added C/C++ project type detection in `_extract_project_identity()` with Makefile version/name extraction. Supports classification as `c-database` (projects with `.conf` files like redis.conf), `c-infrastructure` (nginx-like structure), or `c-project` (generic). Polyglot C+Python/Lua projects get combined type like `c-python-polyglot`.

- **`c_type` in polyglot detection**: Extended the polyglot type builder to include C projects alongside Rust, Go, JS, and Python types.

## [6.4.0] — 2026-06-12

### Tested against neovim/neovim (3,856 files: 506 C/C++ + 816 Lua + 12 Shell + 8 Python + 4 JS, C/Lua text editor project)

Real-world test on a C/Lua polyglot project (CMake + Lua runtime). This test exposed
critical issues with non-web projects that have no package.json, pyproject.toml, or Cargo.toml.

### Fixed

- **Critical: `is_bundled_file` missing from `utils.py`** — 4 commands (`ask`, `complexity`, `context`, `perf-hint`) crashed on import because `complexity_engine.py` and `perfhint_engine.py` imported `is_bundled_file` from `utils` but it didn't exist. Added `is_bundled_file()` with directory segment detection (dist/, build/, vendor/, etc.) and bundled filename suffix detection (.bundle.js, .chunk.js, .umd.js, etc.).
- **Critical: `audit_environment` ImportError in `analyze` command** — `_detect_env()` in `analyze.py` called `from envcheck_engine import audit_environment` but the actual function name is `check_env_vars`. Fixed to use the correct import and adapt the response structure.
- **C/C++ no longer listed as "unsupported"** — `framework_detect.py` listed C, C++, Java, Kotlin, C#, Swift, Ruby as "unsupported" based on build system markers (CMakeLists.txt, pom.xml, etc.), even though fallback parsers for ALL these languages were working and extracting thousands of nodes. Now only truly unsupported languages (Zig, OCaml, Perl, Clojure, F#, Erlang, Fortran) are listed. Updated `lang_note` message to be more accurate.
- **Identity detection for C/CMake projects** — Handbook reported `type: unknown`, `version: 0.0.0`, `name: <folder>` for C/C++ projects. Added CMakeLists.txt parsing to extract project name (`project(Name)`), version (`project(Name VERSION x.y.z)` and `set(VERSION_MAJOR/MINOR/PATCH)`), and classify project type (c-lua-application, c-gui-application, c-service, c-library, c-application, c-project).

### Added

- **Languages field in handbook output** — New `languages` key in handbook response with accurate language distribution (e.g., `{"Lua": 816, "C/C++": 506, "Shell/Bash": 12}`). Merges outline engine data with scan result's `files_scanned` for complete coverage including fallback parser languages.
- **Architecture detection in handbook** — New `architecture` key with pattern detection: `core-plugin` (C core + Lua runtime), `client-server`, `mvc`, `core-api`, `fullstack`, `monorepo`, etc. Also includes `key_directories` and `description`.
- **CMake `set(VERSION_MAJOR/MINOR/PATCH)` version extraction** — Projects that don't use `project(Name VERSION x.y.z)` but instead use `set(NVIM_VERSION_MAJOR 0)` etc. now get version detected correctly.
- **`compute_summary` now includes fallback parser languages** — `files_by_language` in `summary.json` previously only contained tree-sitter supported languages (Python, JS, etc.). Now merges `scan_result.files_scanned` data so C/C++, Lua, Go, Java, Kotlin, etc. appear in the summary.

## [6.4.0] — 2026-06-12

### Tested against fastapi/fastapi (1,130 Python files, 48 core library + 582 tests + 454 docs examples)

Real-world test on a pure Python library project. FastAPI's unique structure — a small
core library with massive docs_src/ example directories and comprehensive test suites —
exposed critical false positive patterns that were invisible on application-type repos
(prior testing: vercel/swr for React hooks, n8n-io/n8n for Vue/TS monorepo).

### Fixed

- **CRITICAL: Missing `is_bundled_file()` function** — 4 engines crashed on import (`ask.py`, `complexity.py`, `context.py`, `perf_hint.py`). The function was referenced in `perfhint_engine.py` and `complexity_engine.py` but never defined in `utils.py`. Added proper implementation that detects dist/, build/, out/, minified, and bundled file patterns.

- **CRITICAL: `api-map` command crash** — `map_api_routes()` received unexpected keyword argument `production_only`. The command passed it but the engine function signature didn't accept it. Added `production_only` parameter to `map_api_routes()` with route source filtering.

- **SQL injection false positives (16 → 0 on FastAPI)** — f-strings containing English words like "Updated", "Created", "update", "DELETE" were flagged as SQL injection. Examples: `f"Updated {path}"`, `f"Created PR: {pr.number}"`, `f"Please update the response model {type_!r}"`. Fixed by requiring: (1) a secondary SQL keyword (FROM, WHERE, SET, INTO, TABLE, VALUES, JOIN, etc.) in the same string, AND (2) the primary keyword must appear at or near the start of the string content.

- **docs_src/example directory inflation** — 454 docs example files in FastAPI inflated ALL metric categories. `smell_engine.py` now downgrades all smells from docs/examples/test files to "info" severity with `source: "docs_example"` tag. `debugleak_engine.py` skips docs/example directories entirely. `deadcode_engine.py` skips docs_src paths in unused_exports and registry_dead. `deep_nesting` detection skips /tests/, /docs_src/, /examples/ directories.

- **Library code false positives in deadcode** — 189 "unused exports" in FastAPI core library were actually public API, not dead code. Added `_detect_library_package()` that detects Python packages (with __init__.py re-exports, `__all__`), JS libraries (main/module/exports in package.json without scripts.start). For detected libraries: capitalized exports are assumed public API, severity downgraded to "info", message includes "library public API — may be used by consumers". Also skip __init__.py files entirely (re-export entry points).

- **Secrets false positives in test files (10 → 0 on FastAPI)** — All 10 "secrets" were dummy test data: `hashed_password="secrethashed"`, `"password": "incorrect"`. Added `_is_obvious_test_value()` that catches: dictionary dummy passwords (secret, test, incorrect, fake, mock, etc.), very short alpha-only values (≤4 chars), and test-prefixed patterns (test_*, fake_*, mock_*). Only applied in test files to preserve real secret detection.

- **Deep nesting false positives in test directories (925 items removed)** — Test files in /tests/ directory had deep nesting from test setup patterns (pytest fixtures, nested describe blocks). Added /tests/, /docs_src/, /examples/ to skip_dirs in `_detect_deep_nesting()`.

- **Debug leak false positives in docs/examples** — docs_src example files used print() as demo output, not debug code. Added `DOCS_EXAMPLE_PATTERNS` and skip logic to `debugleak_engine.py`.

- **`analyze` command showed wrong version "6.0"** — Hard-coded string instead of importing `CODELENS_VERSION` from utils. Now imports and uses the constant.

### Added

- **`is_bundled_file()` utility function** — Detects bundled/compiled files (dist/, build/, .min.js, .bundle.js, .d.ts, etc.) for engine skip logic. Used by complexity and perf_hint engines.
- **`_detect_library_package()` in deadcode engine** — Detects if workspace is a library vs application, adjusts unused_exports severity accordingly.
- **`_is_obvious_test_value()` in secrets engine** — Filters out clearly fake test credentials (dummy passwords, test patterns).
- **docs_src/doc_src/examples/documentation directory patterns** — Added across all engines (apimap, smell, deadcode, debugleak) for consistent exclusion of documentation example code.
- **API map `production_only` filtering** — Now actually works, filtering routes tagged as "test" source.

## [6.3.1] — 2026-06-12

### Tested against spacedriveapp/spacedrive (2,934 files, Rust+TS+Swift Tauri monorepo)

Real-world test on a massive virtual distributed filesystem Tauri desktop app (38K+ GitHub stars)
with 16+ Rust crates (including procedural/derive macros), 1,166 Rust files, 405 TS/TSX files,
17 Swift files, 3 Kotlin files, and complex cross-language FFI boundaries. The registry built
13,350 backend nodes and 62,780 edges — one of the most diverse test targets to date.

### Fixed

- **CRITICAL: `is_bundled_file()` missing from utils.py** — The function was imported by
  `complexity_engine.py` and `perfhint_engine.py`, but never defined in `utils.py`. This caused
  ImportError cascade that completely disabled 4 commands: `ask`, `complexity`, `context`, and
  `perf-hint`. Added the missing function with detection for dist/build/out directories, bundled
  file extensions (.bundle.js, .chunk.js, .global.js), minified files, and declaration files.
- **`api-map` crash on `production_only` kwarg** — The `api-map` command passed `production_only`
  argument to `map_api_routes()`, but the engine function did not accept this parameter. Added
  `production_only: bool = False` parameter to `map_api_routes()` and implemented the filter
  that removes test-sourced routes when the flag is set.

## [6.3.1] — 2026-06-12

### Fixed

- **CRITICAL: 4 broken commands restored** — `ask`, `complexity`, `context`, `perf-hint` commands failed to import due to missing `is_bundled_file` symbol in `utils.py`. The new v6.3.0 engines (`complexity_engine.py`, `perfhint_engine.py`) and their consumers reference `is_bundled_file()` but the function was never added to `utils.py`.
- **HIGH: apimap_engine crash on None path** — `_build_route_groups()` and `_is_route_deprecated()` crashed with `AttributeError: 'NoneType' object has no attribute 'split'` when route dict had `path: None`. Fixed by using `route.get("path") or "/"` instead of `route.get("path", "/")` which doesn't handle explicit `None` values.

### Added

- **`is_bundled_file()` function** (`utils.py`): Detects bundled/compiled artifacts (minified JS/CSS, vendor bundles, webpack chunks with content hashes, dist/build output directories). Used by `complexity_engine` and `perfhint_engine` to skip non-source files.
- **`BUNDLED_FILE_PATTERNS`** and **`BUNDLED_DIR_SEGMENTS`** constants in `utils.py` for consistent bundled file detection across engines.

### Test Target Documentation

- **meilisearch/meilisearch** (GitHub): Used as test target for v6.3.1 — a search engine written in Rust with 21 workspace crates, 692 .rs files, 12214 backend nodes, 490543 edges. Detected frameworks: rust, tokio, actix-web. Monorepo with cargo-workspace. Health score: 50/100 (677 critical smells, god object Index with 99 methods). 2 potential secrets in open_api_utils.rs. 1299 debug leaks (851 commented code, 310 debug_log). 402 dead code items. 200 circular dependencies.


## [6.1.0] — 2026-06-12

### Tested against database & XHR/network repos: Redis, LevelDB, Axios, Undici, libuv

Round 2 real-world testing targeting database systems (Redis C, LevelDB C++) and
HTTP/network libraries (Axios JS, Undici JS, libuv C). Exposed critical dead-code
accuracy gaps where exported symbols were falsely marked as "dead".

### Fixed

- **CRITICAL: JS/TS exported symbols falsely marked as dead** (`js_backend_parser.py`, `ts_backend_parser.py`, `fallback_js_backend.py`): The `export` keyword was never propagated to backend registry nodes. Exported classes like `AxiosError`, `EventEmitter`, and `CustomError` appeared as "dead" (0 ref_count, `exported: False`). Now all three parsers detect `export_statement` AST nodes and set `exported: True` on function/class/variable declarations. AxiosError now correctly shows `status: "active"`.
- **CRITICAL: Incremental scan status computation ignores exported/component/pub flags** (`incremental.py`): `merge_backend_data()` used simple `ref_count == 0 -> dead` without checking `exported`, `component`, or `pub` flags. Now uses the same 3-condition check as `edge_resolver.resolve_edges()`.
- **HIGH: Rust `pub fn` falsely marked as dead** (`edge_resolver.py`): `resolve_edges()` only checked `exported` and `component` flags, but Rust uses `"pub": True` (separate key). A `pub fn` with no internal callers was marked `"dead"`. Now also checks `node.get("pub", False)`.
- **HIGH: Dead-code engine misses exported/component flags** (`deadcode_engine.py`): `_detect_dead_from_registry()` skipped `pub` functions but not `exported` or `component` nodes. Now checks all three flags.
- **MEDIUM: Drupal false positive on non-PHP repos** (`framework_detect.py`): Generic indicators `modules/` and `themes/` matched Redis directory. Replaced with specific indicators `sites/default/` and `sites/all/`. Redis no longer falsely detected as Drupal.
- **MEDIUM: HTTP/network libraries not detected** (`framework_detect.py`): Added 7 HTTP library signatures (axios, undici, got, ky, superagent, node-fetch, request), `has_http_library` flag, and `package.json` name field detection for when the repo IS the library.
- **MEDIUM: PascalCase classes too narrow in tree-sitter JS parser** (`js_backend_parser.py`): Only React-extending classes were `component: True`. Now any PascalCase class is marked as `component: True`.

### Test Repos Used

| Repo | Language | Size | Theme | Key Finding |
|------|----------|------|-------|-------------|
| redis/redis | C | ~70MB | Database | Drupal FP (modules/ dir) |
| axios/axios | JS | ~5MB | XHR/Network | AxiosError dead, HTTP lib detection |
| nodejs/undici | JS/TS | ~40MB | XHR/Network | HTTP lib detection |


## [5.10.0] — 2026-06-12

### Tested against n8n-io/n8n (20,355 files: 9,101 JS + 4,626 TSX + 1,092 Vue + 66 Python, workflow automation monorepo)

Real-world test on a massive TypeScript/Vue/Express monorepo (pnpm-workspace + Turborepo).
This is the largest repo tested to date, exposing critical scalability and accuracy issues
that were invisible on smaller projects.

### Fixed

- **Frontend registry CSS class name validation** (2,853 false positives removed, 7,792 → 4,687 classes): Vue `:class` binding expressions like `!!hint,`, `!!item.disabled`, `!==`, `!action.completed,` were stored as CSS class names. Added `_is_valid_css_class_name()` validation in `registry.py` that rejects names starting with `!`, containing operators (`()?.<>=+*/`), longer than 80 chars, or not matching `^[a-zA-Z_-][\w-]*$`.
- **Framework detection for monorepo sub-directory packages**: `detect_frameworks()` only checked root `package.json`, missing React/Vue/Express in workspace packages. Now scans `apps/*/package.json`, `packages/*/package.json`, and `packages/@scope/name/package.json`. Correctly detects `has_vue: true`, `has_express: true` for n8n.
- **Edge resolver built-in JS method filtering**: `resolve_edges()` created resolved edges to `add`, `then`, `setTimeout`, `race`, `clearTimeout`, `includes`, `indexOf`, `substring`, `trim`, `reject`, etc. — treating JS built-in methods as project-defined functions. Now checks `_STD_LIB_METHODS` before resolution (expanded from 80 to 110+ entries). Impact analysis no longer shows these as dependents.
- **API map false positives** (2,922 → 0 test routes with `--production-only`): Added `--production-only` flag. Vue plugins (ChatPlugin, SentryPlugin, PiniaVuePlugin) no longer detected as Express middleware. Tauri detection now requires `src-tauri/Cargo.toml` (not just `invoke()` calls). Auth-protected routes now detected by middleware name patterns (`jwt`, `passport`, `authenticate`, `verifyToken`).
- **Entrypoints garbage test names**: Test names like `:`, `,`, `=` from malformed `it()` parsing. Fixed with word boundary regex and punctuation-only name filtering.
- **Dead code numeric literal false positives**: Numeric literals like `300_000` and `10000` detected as "unused variables". Added `^\d[\d_]*$` pattern check to skip numeric literals.
- **Debug leak config file false positives**: `testEnvironment: 'node'` and `testRegex` in `jest.config.js` flagged as "mock data". Config files (`*.config.js/ts`, `jest.config.*`, `vite.config.*`, etc.) now get severity downgraded to "info" with note "in config file — not production code".
- **Complexity output not sorted by complexity**: Functions listed in file order. Now sorted by complexity level (untamable → very_complex → complex → moderate → simple), then cyclomatic descending.
- **`analyze` command timeout on large repos**: No `--max-files` or per-engine timeout. Added `--max-files` argument (default 5000) and per-engine 30s timeout using `signal.SIGALRM`. Timed-out engines report gracefully instead of blocking.

### Added

- **`api-map --production-only` flag**: Filter out test routes for a clearer picture of production endpoints.
- **`has_express` field** in framework detection output.
- **Auth detection** in API map: middleware names containing auth patterns are flagged.
- **Config file awareness** in debug-leak engine: config files get `severity: "info"` and `should_remove: false`.

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
