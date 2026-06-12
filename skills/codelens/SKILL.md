---
name: codelens
description: >
  CodeLens v6 — Live Codebase Reference Intelligence (Tree-sitter Edition).
  MUST activate this skill EVERY TIME you are about to create, edit, or delete HTML class/id,
  CSS selector, JSX className, or function in Rust/JS/TS/Python. Use before writing new code
  that involves id, class, className, or function name — to prevent collision,
  overwrite of existing logic, and dead code.
  Also trigger when user asks for any of:
  — REFERENCE: "check if this id already exists", "see all that use class X",
    "what functions call Y", "show all references to N",
    "who imports this file", "trace call chain"
  — CODEBASE SCAN: "scan my workspace", "audit dead code", "check duplicate CSS",
    "detect frameworks", "validate registry", "show file outline"
  — SECURITY: "is this code secure", "find hardcoded secrets/API keys/passwords",
    "are there any leaked API keys", "audit env vars", "check environment variables",
    "find ReDoS regex", "is this regex safe", "check data flow security"
  — UNDERSTANDING: "how does this app work", "where are the entry points",
    "map API routes", "what endpoints exist", "track global state",
    "who reads/writes this state", "what's the file structure"
  — QUALITY: "is this code ready for production", "find code smells",
    "measure complexity", "which function is most complex", "find debug code",
    "cleanup console.log/print", "check accessibility", "is this component accessible",
    "find TODO/FIXME", "check WCAG compliance"
  — REFACTORING: "is it safe to rename/move this", "what happens if I delete this",
    "check refactoring safety", "who owns this code", "what's the impact of this change"
  v3 adds: data flow analysis, code smell detection, side-effect analysis, refactoring safety,
  enhanced dead code, error propagation, test coverage mapping, config drift detection,
  lightweight type inference, and code ownership analysis.
  v4 adds: hardcoded secret detection, execution entry point mapping, API route→handler mapping,
  global state management tracking, environment variable auditing, debug code leak detection,
  cyclomatic/cognitive complexity scoring, ReDoS-vulnerable regex auditing, accessibility auditing.
  v5 adds: dependency vulnerability scanning (CVE database + npm/cargo/pip audit), performance anti-pattern detection (N+1, sync blocking, memory leaks, expensive renders, large bundles), deep CSS analysis (unused variables, orphan keyframes, specificity wars, duplicate properties, z-index abuse).
  v6 adds: monorepo-aware framework detection (turborepo, pnpm-workspace, nx), accurate god object detection (class/impl body scoping), API route false positive elimination, CSS specificity false positive fix, dead code from registry cross-reference, state map constant/component filtering, polyglot project identity.
  Supports: HTML, CSS, JS, TS/TSX, Rust, Python, Vue SFC, Svelte, Tailwind CSS, SCSS.
  Powered by tree-sitter for accurate AST-based parsing.
---

## What's New in v6.5 — Tested on ionic-team/ionic-framework (2330 files, Stencil+React+Vue+Angular lerna monorepo)

- **Stencil.js framework detection**: `detect_frameworks()` now recognizes `@stencil/core` dependency and `stencil.config.ts` config files. Stencil components (`@Component`, `@Prop`, `@State`, `@Method`, `@Listen`) are detected as framework indicators. Sub-directory scanning also detects Stencil in monorepo packages.
- **SCSS control flow false positive fix**: `css-deep` specificity_wars engine now skips SCSS directives (`@if`, `@else`, `@each`, `@for`, `@while`, `@mixin`, `@include`, `@function`, `@at-root`) that were incorrectly classified as CSS selectors. Handles both standalone directives and inline closing-brace patterns (`} } @else if $var == val {`). Eliminates 4+ false positives from SCSS mixin/control flow blocks per project.
- **CSS ID hex-color false positive fix**: `missing-refs` now filters out hex color codes (3-8 hex chars like `a0a0a0`, `a1eb9a`) that were falsely classified as CSS IDs. Reduced missing-refs noise from 163 to 72 issues (91 false positives eliminated) on the Ionic test repo.
- **Monorepo identity from core sub-package**: `_extract_project_identity()` now looks for a `core/`, `packages/core/`, `lib/`, or `src/` sub-directory package.json when the root package.json has no meaningful name (common in lerna monorepos where root is private). For scoped packages like `@ionic/core`, uses the scope name ("ionic") as the project identity. Fixes "test-target-repo" and "0.0.0" identity on monorepos.
- **Monorepo core/ directory scanning**: `_find_package_jsons()` now also checks top-level directories like `core/`, `lib/`, `src/` for package.json files, not just standard monorepo directories (`apps/`, `packages/`). This fixes framework detection for repos like Ionic where the main package lives in `core/` not `packages/`.
- **Stencil wrapper component filtering in state-map**: React wrapper components that wrap Stencil web components (Ion-prefixed like `IonButton`, `IonCheckbox`) are no longer classified as state stores. These are React components, not global state. Reduced state-map entries from 16+ to 6 real stores.
- **Skip .d.ts in entrypoints**: TypeScript declaration files (`.d.ts`) are no longer listed as entry points. They're type declarations, not executable code. Eliminates noise from type declaration files in the entry points list.
- **Version**: 6.3.1 → 6.5.0.

# CodeLens v6

Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

## What's New in v6.4 — Tested on excalidraw/excalidraw (632 files, React+TS yarn-workspace monorepo)

- **Bugfix: `is_bundled_file` missing from utils.py**: 4 commands (`ask`, `complexity`, `context`, `perf-hint`) were silently broken due to missing `is_bundled_file` function in `utils.py`. Now added with proper path-based and extension-based detection for minified, bundled, and dist/build output files.
- **Bugfix: `analyze` env_issues engine ImportError**: `_detect_env()` called non-existent `audit_environment` from `envcheck_engine`. Fixed to use correct `check_env_vars()` function. The env_issues engine now runs successfully in `analyze`.
- **Bugfix: Risk score saturation to 0**: `_compute_risk_score()` used linear deduction that immediately saturated to 0/100 on projects with multiple finding categories. Now uses logarithmic scaling (`log2(1+n)`) with per-category caps and exponential decay for negative scores, producing meaningful risk scores (e.g., 30/100 instead of 0/100 for a project with 367 critical issues).
- **Bugfix: `dependents` workspace auto-swap**: When passing a workspace directory as the first argument to `dependents`, the auto-swap correctly updated `args.workspace` but not the `workspace` parameter passed to engine functions. Fixed by updating both.
- **Bugfix: `ask` router specificity**: "show me the architecture" was misrouted to `context` (score 4.0) instead of `handbook` (score 3.27) because the coverage bonus favored short keyword patterns. Added a 1.5x specificity bonus for patterns matching weight-3 technical terms.
- **Auto-detect detail level**: `summary --detail auto` (now the default) automatically adapts detail level based on codebase size: <100 files → "full", 100-1000 → "standard", >1000 → "minimal". Prevents information overload on large repos.
- **Smart truncation**: `summary --max-tokens 8000` estimates output token count and progressively truncates `top_items` lists to stay within budget. Prevents AI agent context overflow.
- **AGENT.md generation**: `summary --write-agent-md` writes a condensed markdown file to `.codelens/AGENT.md` optimized for AI agent system prompts. Includes identity, frameworks, priority findings, and actionable recommendations.
- **Version**: 6.3.0 → 6.4.0.

## What's New in v6.3 — Tested on n8n-io/n8n (20K+ files, Vue+TS pnpm/turborepo monorepo)

- **Large repo timeout fixes**: `missing_refs` O(n²) typo detection now time-budgeted (15s cap, 2-char prefix filtering, 500K comparison cap, pre-built lookup dict). `analyze` command gets `--timeout` (default 300s) with per-engine time budget and graceful degradation (skips engines when <20% budget remains). `handbook` command gets `--timeout` (default 120s) with per-engine skip and `partial: true` output flag.
- **api-map tauri false positive fix**: Removed overly broad `invoke\s*\(` pattern from tauri import detection. Many non-Tauri projects (AWS Lambda, gRPC, n8n workflow nodes) use `invoke()` calls that were falsely detected as Tauri IPC. Now only matches explicit `@tauri-apps/api` imports.
- **state-map react_context false positive fix**: `react_context` detection now requires actual React dependency (`has_react` check via framework_detect or package.json). Vue/Pinia projects no longer produce `react_context` false positives. File-level import check also added: `createContext` must come from a React import.
- **entrypoints `--exclude-tests` flag**: New `--exclude-tests` flag on the `entrypoints` command filters out `test_entry` type from scanning. Reduces n8n entrypoints from 71K (98% test entries) to 1.6K production entries. `test_entry` output also capped at 100 items max. Analyze command passes `exclude_tests=True` by default.
- **smell god_object JS/TS brace-depth tracking**: Replaced naive regex that counted ALL function-like patterns in the entire file (10-30x inflation) with proper brace-depth tracking like Rust impl blocks. Now only counts methods inside actual `class { }` body blocks. Example: `N8NStartupError` went from 87 false methods to 3 actual methods.
- **missing_refs output improvements**: Per-category truncation (max 200 items), `truncated_counts` for actual totals, `findings` flat list for consistency with other engines, `typo_truncated` flag when time budget expires.
- **analyze graceful degradation**: Skipped engines report `skipped: true` with `skip_reason` and `action` (suggests running individually). `skipped_engines` summary in output. Per-engine `elapsed_seconds` timing.
- **Version**: 5.9.2 → 6.3.0.

## What's New in v6.3.1 — Tested on Readest (1200+ TSX, 40 Rust, Tauri V2 + Next.js)

- **Performance: `--max-files` on remaining heavy engines**: Commands that still timed out on repos with 1000+ files now accept `--max-files` (default: 3000). Added to: `a11y`, `side-effect`, `test-map`. Already present in: `dead-code`, `complexity`, `smell`, `debug-leak`.
- **Performance: `--max-results` on dead-code**: New `--max-results` flag (default: 100) to cap results per category. Prevents massive JSON output on repos with thousands of dead code items.
- **Workspace auto-detect improvement**: `resolve_workspace()` now prioritizes last-used workspace over cwd/project-marker auto-detection. This fixes the common issue where subcommands like `symbols`, `search`, `trace`, `impact`, `context`, `dependents` would resolve to the wrong workspace when the workspace argument is omitted (e.g., resolving to `/home/z/my-project` instead of the actual project).
- **a11y truncated flag**: `a11y` engine now reports `truncated: true` when file-count limit is reached, making it clear that results are partial.

## What's New in v6.0 — The "Analyze Everything" Release

- **`analyze` command (P0)**: One-shot full repository analysis. Automatically runs init + scan + all engines (secrets, smells, complexity, debug-leak, dead-code, circular, perf-hints, config-drift, binary-artifacts, dataflow, env-check, vuln-scan). Produces comprehensive report with project identity, frameworks, languages, architecture overview, API routes, entry points, risk assessment (0-100 score), prioritized action plan, and contextual recommendations.
- **PHP support in all engines**: `.php` added to SOURCE_EXTENSIONS in `debugleak_engine.py`, `smell_engine.py`, `complexity_engine.py`, and `perfhint_engine.py`. PHP files now scanned for code smells, complexity, debug leaks, and performance hints.
- **PHP debug leak detection**: `var_dump()`, `print_r()`, `phpinfo()`, `dd()`, `dump()`, `ray()`, `dpm()`, `kint()`, `xdebug_var_dump()`, `exit;`, `die()`.
- **PHP complexity detection**: New `_extract_php_functions()` — detects `public/private/protected function` and standalone `function` declarations.
- **PHP smell detection**: Long functions, deep nesting, many parameters for PHP methods.
- **PHP performance hints**: 8 PHP-specific patterns — Doctrine N+1, Eloquent N+1, sleep(), blocking file_get_contents(), exec()/shell_exec(), memory leaks in long-running processes, Redis KEYS command, missing TTL.
- **Multi-language SOURCE_EXTENSIONS**: Added `.java`, `.cs`, `.dart`, `.lua` to all applicable engines.
- **Risk assessment**: 0-100 risk score with emoji indicators (🔴🟠🟡🟢) based on finding severity.
- **Prioritized action plan**: Auto-generates P0-P3 action items with concrete next steps.
- **Contextual recommendations**: Language/framework-specific recommendations (PHP: phpstan, Go: go vet, Python: mypy+ruff).
- **Total commands**: 44 → 45.

## What's New in v5.8.1 — Tested on cockroachdb/cockroach (10K files, Go database)

- **Go project type detection**: `handbook` parses `go.mod` for module name, Go version, and classifies projects as `go-database`, `go-web-service`, `go-grpc-service`, `go-infrastructure`, or `go-project`.
- **Go framework content-based detection**: `detect_frameworks()` reads go.mod content (not just file existence). Detects gin/echo/fiber/chi/mux/grpc/protobuf only when dependency actually appears. No more false positives on non-web Go projects.
- **Go removed from unsupported_langs**: Go has fallback parser support and is actively scanned, so it's no longer listed as "unsupported".
- **Go debug-leak commented_code false positive reduction**: 22,433 → 6,734 findings (70% reduction) via Go-specific code indicators, higher block length threshold (5 vs 3), higher score threshold (3 vs 2), and license block skip.
- **Bugfix: `get_workspace_outline()` TypeError**: Removed invalid `max_files` kwarg.
- **Bugfix: `perf-hint` TypeError crash**: Removed invalid `max_files` kwarg from `detect_perf_hints()` call.
- **Bugfix: Handbook `type: unknown` and `version: 0.0.0`** for Go projects: Now extracts identity from go.mod.

## What's New in v5.8.0 — Tested on denoland/deno (5,448 files, Rust+TS polyglot monorepo)

- **Rust framework detection**: `detect_frameworks()` now parses `Cargo.toml` for dependencies and detects `rust`, `tokio`, `actix-web`, `axum`, `warp`, `rocket`, `deno_core`. Also scans workspace members' `Cargo.toml` in `crates/`, `ext/`, `libs/`, `packages/`.
- **Rust HTTP route extraction**: `api-map` now detects routes from Rust web frameworks: actix-web (`#[get]`/`#[post]` attributes, `web::resource()`), axum (`.route("/path", get(handler))`), warp (`warp::path("segment")`), rocket (`#[get]`/`#[post]` attributes).
- **Cargo workspace monorepo detection**: `handbook` detects `[workspace]` in `Cargo.toml` and sub-crate patterns. Reports `is_monorepo: true` with `monorepo_tools: ["cargo-workspace"]`.
- **`is_generated_file()` utility**: Detects lock files, declaration files, minified files. Fixes `refactor_safe` command crash. Total commands: 42 → 43.
- **State-map `__dunder` runtime helper filtering**: JS/TS runtime binding helpers (`__default`, `__createBinding`, `__exportStar`, `__importDefault`, `__reexport`, `__buffer`, `__esModule`, etc.) no longer classified as state stores. General `__` prefix pattern also filtered.
- **`handbook` crash fix**: Removed invalid `max_files` keyword argument from `cmd_scan()` call.
- **Smell `health_score` at top level**: `health_score` now also returned as top-level key for easier programmatic access.
- **File scan cap increases**: Complexity engine 3,000→5,000 files. Debug-leak 3,000→5,000 files.
- **Version alignment**: skill.json version `5.7.1` → `5.8.0`. Description now accurately reflects current capabilities.

## What's New in v5.8.0 (elizaOS/eliza test) — Previous Release

- **State map false positive reduction**: Expanded skip lists for Node.js globals (__dirname, __filename, process, Buffer, etc.), CLI argument constants, path aliases (ROOT, HOME, CWD), environment variable references, and import-like assignments. ALL_CAPS single-word constants (VERBOSE, CLI, CHECK, PRUNE) now correctly skipped. Python global filtering also improved with builtin/dunder/path skips. State stores dropped from ~1493 false positives to significantly fewer real ones.
- **Entrypoints markdown fix (v2)**: Angle brackets like `<module_export>` and `<main>` were treated as HTML tags by markdown renderers, silently consumed. Now uses backticks for reliable rendering: `module_export`, `main`.
- **Performance: --max-files limit**: Scan and handbook commands now accept `--max-files` (default: 5000) to prevent timeout on very large repos. Proportionally truncates file categories with a warning. Use `--max-files 0` to scan all files.
- **Debug leak output improvement**: Each leak item now includes `pattern` (the detected pattern name), `message` (human-readable description), and `content` (the matched line content). Markdown formatter shows descriptive messages like "Debug console statement: console.log()" instead of raw category names.
- **Python global state filtering**: Skips ALL_CAPS constants, dunder attributes (__name__, __file__, __all__), and path/env references (os.path, Path, os.getenv). Reduces false positives in Python projects.

## What's New in v6 — Real-World Tested on Vercel Turborepo (1769 files, Rust+TS monorepo)

- **Monorepo-aware framework detection**: Detects turborepo, pnpm-workspace, lerna, nx. Walks sub-directory package.json (apps/*, packages/*) to find Next.js, React, etc. in workspace packages, not just root. Detects Rust/Cargo workspaces. Build tool detection (Vite, webpack, esbuild).
- **Accurate god object detection**: Class method counting now scoped to actual class/impl body via brace-depth tracking. Was counting ALL function calls in the file as methods (10-30x inflation). Rust impl blocks also properly scoped.
- **API route false positive elimination**: Routes must start with `/` for non-router objects. Expanded skip list (80+ objects: request, headers, cache, store, etc.). Prevents `headers.get('user-agent')` from being reported as `GET /user-agent`.
- **CSS specificity false positive fix**: Tracks brace depth to distinguish CSS rule selectors from property values. Was flagging `rgba(0, 0, 0, 0.1)`, `var(--x)`, `from -160deg` as selectors. Specificity wars dropped from 31 false positives to 4 real ones.
- **Dead code from registry cross-reference**: Uses backend registry's `ref_count` data to find functions with zero references. Skips main(), pub functions, and test fixtures. Found 200+ genuine dead items that the text-only scanner missed.
- **State map constant/component filtering**: Skips ALL_CAPS constants (MAX_FILES, etc.), React components (arrow functions, forwardRef, memo, styled), and immutable values. State stores dropped from 825 false positives to ~150 real ones. Removed module.exports scanning that classified every exported function as a store.
- **Polyglot project identity**: Handbook detects combined types (e.g., `rust-js-monorepo`) when both package.json and Cargo.toml exist. No longer defaults to `node-project` for Rust+TS monorepos.
- **Entrypoints markdown fix**: Bracket types like `[main]` no longer get mangled by markdown link reference interpretation. Uses backticks instead (v5.8: angle brackets were still broken — `<main>` treated as HTML tag).

## What's New in v5

- **Vulnerability Scanning**: Dependency CVE scanning via native audit tools (npm audit, cargo audit, pip-audit, govulncheck) + built-in vulnerability database with 35+ entries
- **Performance Anti-Pattern Detection**: 8 categories — N+1 queries, sync blocking, memory leaks, expensive re-renders, large bundles, inefficient iterations, unoptimized images, cache misses
- **Deep CSS Analysis**: Unused custom properties (--var), orphan @keyframes, specificity wars (!important overuse), duplicate property declarations, z-index abuse, non-standard @media breakpoints

## What's New in v5.6 — Real-World Tested

- **TSX backend extraction**: 6.2x more backend nodes from TSX files when tree-sitter-typescript is unavailable. Uses `parse_js_backend_fallback` on TSX to extract functions and imports.
- **Shared utils module**: Centralized `write_output_files`, `compute_summary`, `is_file_path`, `deduplicate_callers`, `DEFAULT_IGNORE_DIRS`, `CODELENS_VERSION`, and `logger`. Eliminates 290+ lines of duplicated code.
- **Proper logging**: Replaced 56 `except Exception: pass` blocks with `logger.warning()`/`logger.debug()`. Errors are now visible instead of silently swallowed.
- **Fuzzy file path lookup**: `context layout.tsx` and `query layout.tsx` now match partial paths (end-of-path matching). Returns grouped results for multiple matches.
- **Registry freshness check**: Handbook skips re-scan if registry is less than 5 minutes old (2.8s → 0.3s for consecutive runs).
- **Incremental deleted file handling**: Selectively removes deleted file entries from registry instead of full rescan.
- **Path segment matching**: `is_frontend_file`/`is_backend_file` no longer use substring matching. Prevents `src/` from falsely matching `src/server/api/auth.ts`.
- **Workspace detection depth limit**: Walks up at most 10 directory levels (was unlimited).
- **God objects Python scoping**: Method count now scoped to each class using indentation (was counting ALL `def` in file).

## What's New in v5.2 — Agent Optimization

- **`handbook` command**: One-stop project orientation for AI agents. Aggregates identity, structure, health, conventions, risks, and quick reference into a single output. Writes `.codelens/handbook.json` and `.codelens/AGENT.md`.
- **`ask` command**: Natural language query router. Agents don't need to memorize 41 commands — just ask a question and CodeLens routes to the right tool.
- **`--format markdown`**: Global flag on ALL commands. Output markdown instead of JSON for direct LLM consumption.
- **`scan` generates `outline.json` + `summary.json`**: Previously only `watch` produced these AI-friendly files. Now `scan` does too.
- **Decision trees in output**: `query` returns `action` + `action_reason`, `impact` returns `risk_level` + `recommended_action`, `smell` returns `actionable_items`, `dead-code` returns `removal_safety`.
- **`context` enriched with quality metrics**: Adds `quality` block with complexity, side effects, safety assessment, smells, and test coverage.
- **Convention detection**: New `convention_engine.py` detects naming conventions, file organization, import styles, component patterns, and error handling.
- **`.codelens/AGENT.md`**: Auto-generated markdown project brief that can be included as system prompt context.

---

## Skill Location

```
{project_path}/skills/codelens
```

---

## Prerequisites

Run setup once before using CodeLens:

```bash
bash "$CODELENS_DIR/setup.sh"
```

---

## Workspace Auto-Detect

**NEW in v5.1**: The `workspace` argument is now **optional** for ALL commands. If omitted, CodeLens auto-detects the workspace using this fallback chain:

1. **Current directory** — if it contains project markers (package.json, pyproject.toml, Cargo.toml, etc.)
2. **Parent directories** — walks up to find a project root
3. **Source files** — if current directory has any source files (.py, .js, .ts, etc.)
4. **Last workspace** — cached from previous command (`~/.codelens/.codelens_last_workspace`)
5. **Fallback** — current working directory

This means you can now run commands like:
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" scan              # Auto-detect workspace
python3 "$CODELENS_DIR/scripts/codelens.py" query "btn-primary" # Auto-detect workspace
python3 "$CODELENS_DIR/scripts/codelens.py" smell              # Auto-detect workspace
```

You can still explicitly specify a workspace:
```bash
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace
```

---

## Available Tools

### 0. `codelens_analyze` — Full Repository Analysis (NEW v6.0)

**The one-shot command to understand an entire repository.** Automatically runs init + scan + all engines, then produces a comprehensive report with risk assessment and action plan.

This is the recommended first command when you encounter a new repository. It replaces running 10+ individual commands.

```bash
# Full analysis (runs init + scan + all engines)
python3 "$CODELENS_DIR/scripts/codelens.py" analyze /path/to/workspace

# Security-focused analysis only
python3 "$CODELENS_DIR/scripts/codelens.py" analyze /path/to/workspace --focus security

# Full detail (no severity filtering)
python3 "$CODELENS_DIR/scripts/codelens.py" analyze /path/to/workspace --detail full

# Skip re-scanning if registry already exists
python3 "$CODELENS_DIR/scripts/codelens.py" analyze /path/to/workspace --skip-scan
```

**Output includes:**
- Project identity (name, type, version, description)
- Frameworks and languages detected
- Architecture overview (files, lines, directory structure, key modules, entry points)
- API route map
- Prioritized findings from all engines (secrets, smells, complexity, debug leaks, dead code, circular deps, perf hints, config drift, binary artifacts, data flow, env issues, vulnerabilities)
- Risk assessment (0-100 score with 🔴🟠🟡🟢 indicator)
- Prioritized action plan (P0-P3)
- Contextual recommendations (language/framework-specific)

**When to use:** Always run `analyze` when you first encounter a repository. Use `summary` for quick checks, `analyze` for deep understanding.

### 1. `codelens_init` — Initialize Workspace

Run once at the start. Auto-detect frameworks and create config.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" init [/path/to/workspace]
```

### 2. `codelens_scan` — Scan Workspace

Scan entire workspace and build registry. Use `--incremental` to only re-parse changed files. Now supports **Python** parsing with tree-sitter.

```bash
# Full scan (workspace auto-detected)
python3 "$CODELENS_DIR/scripts/codelens.py" scan

# Full scan with explicit workspace
python3 "$CODELENS_DIR/scripts/codelens.py" scan /path/to/workspace

# Incremental scan (only changed files)
python3 "$CODELENS_DIR/scripts/codelens.py" scan --incremental
```

### 3. `codelens_query` — Pre-write Check (MOST IMPORTANT)

Call this **BEFORE** creating a new class, id, className, or function.

```bash
# Query in a specific domain
python3 "$CODELENS_DIR/scripts/codelens.py" query "modal-btn" --domain frontend

# Auto-detect domain
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token"

# Filter by file
python3 "$CODELENS_DIR/scripts/codelens.py" query "hash_password" --domain backend --file "src/utils/"

# With explicit workspace
python3 "$CODELENS_DIR/scripts/codelens.py" query "verify_token" /path/to/workspace
```

**Rules for AI:**
- `found: true` + `status: active` → DO NOT recreate. Extend the existing one.
- `found: true` + `status: dead` → Exists but unused. Reuse or delete first.
- `found: true` + `status: duplicate_ref` → Called from many places. Edit with caution.
- `found: true` + `status: collision` → ACTIVE BUG. STOP. Fix first.
- `found: false` → Safe. Proceed to create.

### 4. `codelens_list` — List with Filter

```bash
# All dead code
python3 "$CODELENS_DIR/scripts/codelens.py" list --domain all --filter dead

# ID collision (HTML bug)
python3 "$CODELENS_DIR/scripts/codelens.py" list --domain frontend --filter collision

# Duplicate CSS
python3 "$CODELENS_DIR/scripts/codelens.py" list --domain frontend --filter duplicate_define

# Backend dead functions
python3 "$CODELENS_DIR/scripts/codelens.py" list --domain backend --filter dead
```

### 5. `codelens_detect` — Detect Frameworks

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" detect [/path/to/workspace]
```

### 6. `codelens_watch` — File Watcher

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" watch [/path/to/workspace]

# With custom debounce interval
python3 "$CODELENS_DIR/scripts/codelens.py" watch --debounce 1.0
```

### 7. `codelens_handbook` — Project Handbook for AI Agents (NEW v5.2)

One-stop project orientation. Aggregates data from 10+ engines into a single output. Writes `.codelens/handbook.json` and `.codelens/AGENT.md`.

**AI Use Case:** "I just landed on this project. Give me everything I need to know."

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" handbook [/path/to/workspace]

# Markdown output (direct LLM consumption)
python3 "$CODELENS_DIR/scripts/codelens.py" handbook --format markdown
```

**Returns:** identity (name, version, type, frameworks), structure (directory map, entrypoints, API routes, state management), health (score, smells, risks), conventions (naming, patterns), risks (circular deps, dead code, secrets, vulnerabilities), quick reference (file/function/class counts).

### 8. `codelens_ask` — Natural Language Query (NEW v5.2)

Ask a question in plain English. CodeLens routes to the appropriate command automatically.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" ask "where is authentication handled?"
python3 "$CODELENS_DIR/scripts/codelens.py" ask "what functions are dead code?"
python3 "$CODELENS_DIR/scripts/codelens.py" ask "which files use Redis?"
python3 "$CODELENS_DIR/scripts/codelens.py" ask "what happens if I change verify_token"
```

**Supported queries:** "where is X", "dead code", "security", "how does X connect to Y", "API routes", "circular dependency", "test coverage", "performance", "overview", and more.

---

## Global Options (NEW v5.2)

### `--format json|markdown`

All commands support `--format markdown` for direct LLM consumption. JSON (default) is unchanged.

```bash
# JSON (default)
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" --format json

# Markdown (for LLM prompt)
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" --format markdown

# Short form
python3 "$CODELENS_DIR/scripts/codelens.py" smell -f markdown
```

---

## P1 Tools — Search, Trace, Impact

### 9. `codelens_search` — Code Search

Search regex pattern across the entire workspace. Like ripgrep but built-in.

```bash
# Search all useEffect
python3 "$CODELENS_DIR/scripts/codelens.py" search "useEffect" /path/to/workspace

# Search in specific file types only
python3 "$CODELENS_DIR/scripts/codelens.py" search "router\\.post" /path/to/workspace --type js

# Case-insensitive + context lines
python3 "$CODELENS_DIR/scripts/codelens.py" search "CREATE TABLE" /path/to/workspace --ignore-case --context 3

# Whole word
python3 "$CODELENS_DIR/scripts/codelens.py" search "Button" /path/to/workspace --type tsx --whole-word
```

**Options:** `--type`, `--file`, `--max-results`, `--context`, `--ignore-case`, `--whole-word`

### 8. `codelens_symbols` — Symbol Search

Search symbol in the registry (not in files). Faster than search.

```bash
# Exact match
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "btn" /path/to/workspace

# Fuzzy search (partial match)
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "modal" /path/to/workspace --fuzzy

# Backend only
python3 "$CODELENS_DIR/scripts/codelens.py" symbols "auth" /path/to/workspace --domain backend --fuzzy
```

### 9. `codelens_trace` — Deep Call Chain

Trace call chain from a symbol. For root cause analysis and impact assessment.

```bash
# Trace callers (who calls this function)
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction up

# Trace callees (what does this function call)
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction down

# Both directions
python3 "$CODELENS_DIR/scripts/codelens.py" trace "verify_token" /path/to/workspace --direction both --depth 5
```

**AI Use Case:** "Bug in render() → trace where it originates" → `trace render workspace --direction up`

### 10. `codelens_impact` — Change Impact Analysis

Predict the impact if a symbol is modified or deleted. Mandatory before refactoring.

```bash
# Check impact if modify
python3 "$CODELENS_DIR/scripts/codelens.py" impact "verify_token" /path/to/workspace --action modify

# Check impact if delete
python3 "$CODELENS_DIR/scripts/codelens.py" impact "btn-primary" /path/to/workspace --action delete
```

**Output:** risk level (low/medium/high/critical), affected files, direct/indirect dependents, recommendations.

**AI Action:**
- `risk: critical` → DO NOT change. Report to user.
- `risk: high` → Warning. List all affected first.
- `risk: medium` → Caution. Run tests.
- `risk: low` → Safe, proceed.

---

## P2 Tools — Outline, Missing-refs, Diff, Circular

### 11. `codelens_outline` — File Structure Outline

View file structure without reading full content. All functions, classes, imports, exports.

```bash
# Outline a single file
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --file src/auth.ts

# Outline with detail level
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --file src/auth.ts --detail full

# Outline all files in workspace
python3 "$CODELENS_DIR/scripts/codelens.py" outline /path/to/workspace --all
```

### 12. `codelens_missing-refs` — CSS/HTML Mismatch Detection

Detect bugs: class in HTML but not in CSS, CSS selector but no HTML, typos.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" missing-refs /path/to/workspace
```

**Detects:**
- `css_no_html` — CSS class defined but never used
- `html_no_css` — HTML/JSX class used but no CSS definition
- `css_id_no_html` — CSS style ID but no HTML definition
- `js_id_no_html` — JS reference ID but no HTML definition
- `possible_typos` — Dead class similar to active class (possible typo)

### 13. `codelens_diff` — Registry Diff

Compare current registry vs last snapshot. Track what changed.

```bash
# Diff vs last snapshot
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace

# List all snapshots
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace --list-snapshots

# Compare two specific snapshots
python3 "$CODELENS_DIR/scripts/codelens.py" diff /path/to/workspace --snapshot1 20240101T120000Z --snapshot2 20240102T090000Z
```

**Note:** Snapshots are automatically saved every time `scan` is run.

### 14. `codelens_circular` — Circular Dependency Detection

Detect circular: function calls, import chains, CSS @import.

```bash
# Check all
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace

# Only function call cycles
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace --domain backend

# Only import cycles
python3 "$CODELENS_DIR/scripts/codelens.py" circular /path/to/workspace --domain imports
```

**Severity:** `critical` (2-node cycle), `warning` (3+ node cycle), `info` (long chain)

---

## P3 Tools — Context, Dependents, Validate

### 15. `codelens_context` — Rich Symbol Context

Everything an AI needs about a symbol: definition code, callers, callees, file outline, imports.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace

# Without source code
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace --no-code

# More context lines
python3 "$CODELENS_DIR/scripts/codelens.py" context "verify_token" /path/to/workspace --context-lines 10
```

**Returns:** definition, code_snippet, callers, callees, nearby_symbols, file_outline, imports

### 16. `codelens_dependents` — Module-Level Import Tracking

Who imports this file? Module level, not function level.

```bash
# Who imports this file?
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace

# What does this file import?
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace --direction dependencies

# Full dependency graph
python3 "$CODELENS_DIR/scripts/codelens.py" dependents src/utils/auth.ts /path/to/workspace --direction graph
```

### 17. `codelens_validate` — Registry Sanity Check

Check whether the registry is still in sync with the file system.

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" validate /path/to/workspace
```

**Detects:**
- `missing_files` — File in registry but already deleted
- `unregistered_files` — New files not yet scanned
- `stale_references` — Line numbers that have changed
- `orphan_entries` — Entries where all file references are gone

---

## v3 P0: Dataflow & Smell

### 18. `codelens_dataflow` — Data Flow Analysis (Source→Sink)

Trace where data flows from sources (user input, env vars, file reads, API responses) to sinks (DB queries, HTML output, command exec, file writes, HTTP headers). Detect taint violations (data that reaches dangerous sinks without sanitization).

- Shows safe paths (data that passes through sanitizers)
- Risk level: none/low/medium/high/critical

**AI Use Case:** "Does user input ever reach an SQL query without sanitization?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace

# Filter by source type
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace --source user_input

# Filter by sink type
python3 "$CODELENS_DIR/scripts/codelens.py" dataflow /path/to/workspace --sink db_query
```

**Options:** `--source` (user_input, dom_input, env_var, file_input, api_response), `--sink` (db_query, html_output, command_exec, file_write, http_header), `--depth`

### 19. `codelens_smell` — Code Smell Detection

Detect 10 code smell categories: long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent. Each smell has severity (info/warning/critical) and refactoring suggestion. Computes health_score (0-100).

**AI Use Case:** "What should I refactor first in this codebase?"

```bash
# All categories
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace

# Specific categories
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace --categories long_fn god_object

# Critical smells only
python3 "$CODELENS_DIR/scripts/codelens.py" smell /path/to/workspace --severity critical
```

---

## v3 P1: Side-effect, Refactor-safe, Dead-code

### 20. `codelens_side-effect` — Side Effect Analysis

Tag functions as pure vs impure. Detect 7 side-effect categories: DOM, State, Network, IO, Timer, Random, External. Compute purity ratio for the entire workspace.

**AI Use Case:** "Is it safe to call this function multiple times?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace

# Specific function
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace --name processOrder

# Filter by file
python3 "$CODELENS_DIR/scripts/codelens.py" side-effect /path/to/workspace --file src/orders.ts
```

### 21. `codelens_refactor-safe` — Refactoring Safety Check

Pre-flight check before rename/move symbol. Detect: string refs, dynamic access, eval refs, meta-programming, test refs, config refs, doc refs, import breaks, CSS refs. Safety level: safe/mostly_safe/cautious/risky/dangerous. Generates pre-refactor checklist.

**AI Use Case:** "Can I safely rename this function?"

```bash
# Check rename safety
python3 "$CODELENS_DIR/scripts/codelens.py" refactor-safe verify_token /path/to/workspace --action rename --new-name validate_token

# Check move safety
python3 "$CODELENS_DIR/scripts/codelens.py" refactor-safe auth /path/to/workspace --action move --new-name src/auth/
```

### 22. `codelens_dead-code` — Enhanced Dead Code Detection

More than just 0-ref_count: detect unreachable code, unused exports, zombie CSS, unused variables, dead event listeners.

**AI Use Case:** "What code can I safely delete?"

```bash
# All categories
python3 "$CODELENS_DIR/scripts/codelens.py" dead-code /path/to/workspace

# Specific categories
python3 "$CODELENS_DIR/scripts/codelens.py" dead-code /path/to/workspace --categories unreachable unused_exports
```

---

## v3 P2: Stack-trace, Test-map, Config-drift

### 23. `codelens_stack-trace` — Error Propagation Simulation

Simulate what happens if a function throws: trace error up the call stack. Show which callers have try/catch (handled) and which don't (unhandled → crash). Crash risk: low/medium/high/critical.

**AI Use Case:** "If this fails, what breaks?"

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" stack-trace verify_token /path/to/workspace

# With specific error type
python3 "$CODELENS_DIR/scripts/codelens.py" stack-trace processOrder /path/to/workspace --error-type NetworkError
```

### 24. `codelens_test-map` — Test Coverage Mapping

Map which functions have test coverage. Strategies: file name matching, function name matching, import matching. Find files with no tests at all.

**AI Use Case:** "Is this function tested before I modify it?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" test-map /path/to/workspace

# Specific function
python3 "$CODELENS_DIR/scripts/codelens.py" test-map /path/to/workspace --function verify_token
```

### 25. `codelens_config-drift` — Dependency Drift Detection

Validate package.json/Cargo.toml/requirements.txt vs actual imports. Find: missing deps, unused deps, phantom imports.

**AI Use Case:** "Are there packages forgotten to install or declared but never used?"

```bash
python3 "$CODELENS_DIR/scripts/codelens.py" config-drift /path/to/workspace
```

---

## v3 P3: Type-infer, Ownership

### 26. `codelens_type-infer` — Lightweight Type Inference

Infer types for variables and functions in JS/Python. Strategies: literal inference, return type inference, known API return types, propagation. Skip files that already have TypeScript annotations.

**AI Use Case:** "What type does this function return?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace

# Specific file
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace --file src/utils.ts

# Specific function
python3 "$CODELENS_DIR/scripts/codelens.py" type-infer /path/to/workspace --function processOrder
```

### 27. `codelens_ownership` — Code Ownership Analysis

Git blame-based ownership: who last touched what, how old is this code. Find stale code, hotspots (many authors), orphan files (no recent changes). Fallback to mtime if git is unavailable.

**AI Use Case:** "Who should I ask before changing this?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace

# Specific file
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace --file src/auth.ts

# Specific function
python3 "$CODELENS_DIR/scripts/codelens.py" ownership /path/to/workspace --function verify_token
```

---

## v4 P0: Secrets, Entrypoints

### 28. `codelens_secrets` — Hardcoded Secret Detection

Detect API keys, passwords, tokens, connection strings, private keys, and secret keys that are hardcoded in source code. Includes Shannon entropy detection to flag high-entropy strings that may be secrets. Scan .env files and check .gitignore.

**AI Use Case:** "Are there any leaked API keys in the codebase?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" secrets /path/to/workspace

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" secrets /path/to/workspace --severity critical
```

**Categories:** api_key, password, token, connection_string, private_key, secret_key, oauth, webhook

### 29. `codelens_entrypoints` — Execution Entry Point Mapping

Map all execution entry points: main(), HTTP handlers, event listeners, CLI commands, cron jobs, workers, module exports, test entries. "Where does this application start?"

**AI Use Case:** "How do I run this code? Which endpoints can be called?"

```bash
# All entry points
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace

# Only HTTP handlers
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace --type http_handler

# Only main entry
python3 "$CODELENS_DIR/scripts/codelens.py" entrypoints /path/to/workspace --type main
```

**Types:** main, http_handler, event_handler, cli_command, cron_job, worker, module_export, test_entry

---

## v4 P1: API Map, State Map, Env Check

### 30. `codelens_api-map` — REST/GraphQL/gRPC Route Mapping

Map all routes to handlers: Express, Fastify, Koa, Hono, Next.js, Nuxt, Django, Flask, FastAPI, GraphQL, gRPC, tRPC. Extract method, path, handler name, middleware chain. Flag auth-protected vs public routes.

**AI Use Case:** "What endpoints exist? What handles POST /users?"

```bash
# All routes
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace

# Filter method
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace --method POST

# Filter path
python3 "$CODELENS_DIR/scripts/codelens.py" api-map /path/to/workspace --path "/api/users"
```

### 31. `codelens_state-map` — Global State Tracking

Track state management: Redux, React Context, Zustand, MobX, Pinia, Vuex, Recoil, Jotai, XState, module-level state. Map reads/writes per state slice.

**AI Use Case:** "Which components read/write this state?"

```bash
# All state
python3 "$CODELENS_DIR/scripts/codelens.py" state-map /path/to/workspace

# Specific store
python3 "$CODELENS_DIR/scripts/codelens.py" state-map /path/to/workspace --store userSlice
```

### 32. `codelens_env-check` — Environment Variable Audit

Audit env vars: which are referenced, required (no fallback), undocumented, missing from .env.example. Check naming inconsistencies and secrets in .env files.

**AI Use Case:** "What env vars must be set before deploy? What's missing from .env.example?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" env-check /path/to/workspace

# Check specific var
python3 "$CODELENS_DIR/scripts/codelens.py" env-check /path/to/workspace --var DATABASE_URL
```

---

## v4 P2: Debug Leak, Complexity

### 33. `codelens_debug-leak` — Debug Code Leak Detection

Detect leftover debug code: console.log, print(), debugger, TODO/FIXME/HACK, commented-out code blocks, test skips, mock data, dev-only guards. Context-aware (skip console.error in catch blocks, downgrade findings in test files).

**AI Use Case:** "What should be cleaned up before production?"

```bash
# All categories
python3 "$CODELENS_DIR/scripts/codelens.py" debug-leak /path/to/workspace

# Specific category
python3 "$CODELENS_DIR/scripts/codelens.py" debug-leak /path/to/workspace --category console_log
```

**Categories:** console_log, print_statement, debugger, todo_fixme, commented_code, test_skip, mock_data, dev_only

### 34. `codelens_complexity` — Complexity Scoring

Compute cyclomatic + cognitive complexity per function with precise numbers. Unlike `smell` which detects patterns qualitatively — this tool gives numerical scores. Cyclomatic: 1-5 simple, 6-10 moderate, 11-20 complex, 21-50 very complex, 50+ untamable. Cognitive: SonarSource spec with nesting increment.

**AI Use Case:** "Which function is most complex and needs refactoring?"

```bash
# Full workspace
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace

# Specific function
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace --name processOrder

# Threshold filter
python3 "$CODELENS_DIR/scripts/codelens.py" complexity /path/to/workspace --threshold 20
```

---

## v4 P3: Regex Audit, A11y

### 35. `codelens_regex-audit` — Regex Pattern Auditing

Audit regex patterns: ReDoS-vulnerable patterns (nested quantifiers, overlapping alternatives), overly broad patterns, incorrect escaping, unsafe RegExp constructor (dynamic input), performance issues.

**AI Use Case:** "Are there regexes that could cause DoS? Wrong patterns?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" regex-audit /path/to/workspace

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" regex-audit /path/to/workspace --severity critical
```

**Categories:** redos_vulnerable, overly_broad, incorrect_escaping, unsafe_constructor, performance

### 36. `codelens_a11y` — Accessibility Auditing

Detect a11y issues: missing alt text, form labels, ARIA issues, keyboard navigation, semantic HTML, color contrast, heading order, vague link text, focus management. Mapped to WCAG 2.1 criteria.

**AI Use Case:** "Is this component accessible? What needs fixing?"

```bash
# Full audit
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace

# Specific category
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace --category missing_alt

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" a11y /path/to/workspace --severity critical
```

**Categories:** missing_alt, missing_label, aria_issues, keyboard_nav, semantic_html, color_contrast, heading_order, link_text, focus_management

---

## v5 P0: Vulnerability Scanning

### 37. `codelens_vuln-scan` — Dependency Vulnerability Scanning

Scan dependencies for known CVEs using native audit tools (npm audit, cargo audit, pip-audit, govulncheck) and a built-in vulnerability database with 35+ entries. Supports npm, Rust, Python, and Go ecosystems. Each finding includes CVE ID, severity, fix version, and recommendation.

**AI Use Case:** "Are there any known vulnerabilities in my dependencies?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" vuln-scan /path/to/workspace

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" vuln-scan /path/to/workspace --severity critical
```

**Categories:** vulnerability (CVE-based), with ecosystem support for npm, rust, pip, go

## v5 P1: Performance Hints

### 38. `codelens_perf-hint` — Performance Anti-Pattern Detection

Detect performance anti-patterns across 8 categories: N+1 queries, sync blocking calls, memory leaks (missing cleanup), expensive React re-renders, large bundle imports, inefficient iterations, unoptimized images, and cache misses. Each hint includes severity, fix suggestion, and context.

**AI Use Case:** "Where are the performance bottlenecks in this codebase?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" perf-hint /path/to/workspace

# Filter by category
python3 "$CODELENS_DIR/scripts/codelens.py" perf-hint /path/to/workspace --category n_plus_one

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" perf-hint /path/to/workspace --severity critical
```

**Categories:** n_plus_one, sync_blocking, memory_leak, expensive_renders, large_bundle, inefficient_iteration, unoptimized_images, cache_miss

## v5 P2: Deep CSS Analysis

### 39. `codelens_css-deep` — Deep CSS Analysis

Analyze CSS for deep issues: unused custom properties (--var), orphan @keyframes animations, specificity wars (!important overuse, deeply nested selectors), duplicate property declarations within rule blocks, non-standard @media breakpoints, and z-index abuse (excessive values, too many unique values). Cross-references CSS with HTML/JS for variable and keyframe usage.

**AI Use Case:** "Are there unused CSS variables? Is there z-index chaos?"

```bash
# Full workspace scan
python3 "$CODELENS_DIR/scripts/codelens.py" css-deep /path/to/workspace

# Filter by category
python3 "$CODELENS_DIR/scripts/codelens.py" css-deep /path/to/workspace --category unused_vars

# Filter severity
python3 "$CODELENS_DIR/scripts/codelens.py" css-deep /path/to/workspace --severity high
```

**Categories:** unused_vars, orphan_keyframes, specificity_wars, duplicate_props, unused_media, z_index_abuse

---

## Auto-Trigger Map — User Intent → Tool Selection

This table helps the AI choose the right tool based on user keywords or intent.
**MUST reference this table every time the user asks something related to the codebase.**

### State Prerequisites

Before running any analysis tool, ensure these prerequisites are met:
1. **Registry exists**: If `.codelens/` does not exist → run `init` + `scan` first
2. **Registry is fresh**: If `.codelens/` was last updated >24h ago → run `scan --incremental` first
3. **After code changes**: Always run `scan --incremental` before re-querying

Auto-init behavior: If a tool requires a registry and none exists, the AI SHOULD automatically run `init` → `scan` before proceeding.

### Colloquial Trigger Phrases

Non-technical phrases that should still trigger CodeLens tools:

| Phrase (English) | Phrase (Indonesian) | Tool Chain |
|-------------------|---------------------|------------|
| "this is slow" / "why so slow" / "takes forever" | "kok lama ya" / "kenapa lama" | `perf-hint` + `complexity` + `circular` |
| "something's weird" / "this is broken" | "aneh nih" / "kok error" | `search` → `context` → `trace` → `missing-refs` |
| "help me check" / "give it a look" | "bantu cek" / "tolong cek" | `smell` + `dead-code` + `secrets` |
| "clean this up" / "tidy up" | "bersihkan" / "rapikan" | `debug-leak` + `dead-code` + `smell` |
| "is this safe?" / "can I deploy this?" | "aman ga" / "bisa deploy ga" | `secrets` + `vuln-scan` + `debug-leak` + `env-check` |
| "make it faster" / "optimize" | "percepat" / "optimasi" | `perf-hint` + `complexity` + `circular` |
| "the CSS is messy" / "style issues" | "CSS berantakan" | `css-deep` + `missing-refs` + `list --filter duplicate_define` |

### Negative Triggers — When NOT to Activate CodeLens

CodeLens should NOT be activated for these tasks:
- **Document generation**: "generate PDF", "create report", "write document" → SKIP CodeLens
- **Image/media generation**: "generate image", "create artwork" → SKIP CodeLens
- **Web search**: "search the web", "find online" → SKIP CodeLens
- **Non-codebase questions**: "what is React", "explain SQL" → SKIP CodeLens
- **File operations on non-code**: editing config files, writing markdown → SKIP CodeLens
- **UI design tasks**: "design a layout", "create mockup" → SKIP CodeLens (unless checking existing code)

**Rule**: If the task does not involve reading, writing, editing, or analyzing source code in the workspace, CodeLens is not needed.

### Default Fallback Chains

When a user's request is vague and doesn't clearly map to a specific tool, use these default chains:

| Vague Request Pattern | Default Chain |
|-----------------------|---------------|
| General "check" / "review" / "analyze" | `smell` → `dead-code` → `secrets` |
| Security-adjacent ("safe?", "secure?", "risk?") | `secrets` → `dataflow` → `env-check` → `vuln-scan` |
| Quality-adjacent ("good?", "clean?", "ready?") | `complexity` → `debug-leak` → `a11y` → `smell` |
| Performance-adjacent ("slow?", "fast?", "optimize?") | `perf-hint` → `complexity` → `circular` |
| CSS-adjacent ("style?", "layout?", "CSS?") | `css-deep` → `missing-refs` → `list --filter duplicate_define` |
| Pre-deploy-adjacent ("deploy?", "ship?", "release?") | `secrets` → `debug-leak` → `env-check` → `config-drift` → `vuln-scan` → `dead-code` |

### Core Triggers (ALWAYS activate CodeLens)

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| Create new class/id/function | `query` | `codelens query "name" workspace` | P0 |
| Edit existing class/id/function | `query` + `context` | Query first, then context for detail | P0 |
| Delete code | `impact` + `dead-code` | Impact check first, then delete | P0 |
| "does this id already exist" / "does this class exist" | `query` | `codelens query "name" workspace` | P0 |
| "who uses this" | `query` or `trace --direction up` | Query for overview, trace for chain | P0 |
| "who calls this" | `trace --direction up` | Full call chain | P1 |
| "what does this call" | `trace --direction down` | Downstream call chain | P1 |

### Reference & Search Triggers

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| "search for" / "find all" | `search` | `codelens search "pattern" workspace` | P1 |
| "find symbol" | `symbols` | `codelens symbols "name" workspace` | P1 |
| "tell me about this" / "detail about this function" | `context` | `codelens context "name" workspace` | P1 |
| "who imports this" | `dependents` | `codelens dependents path workspace` | P2 |
| "outline" / "what's in this file" | `outline` | `codelens outline workspace --file path` | P2 |
| "check duplicate CSS" / "check duplicate class" | `list --filter duplicate_define` | `codelens list workspace --filter duplicate_define` | P3 |
| "CSS doesn't match HTML" / "missing CSS" / "orphan class" | `missing-refs` | `codelens missing-refs workspace` | P2 |
| "circular dependency" / "import cycle" | `circular` | `codelens circular workspace` | P2 |

### Security Triggers

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| "hardcoded secret" / "find passwords" / "leaked API key" | `secrets` | `codelens secrets workspace` | P0 |
| "is this secure" / "security audit" / "vulnerability check" | `secrets` + `dataflow` + `env-check` + `vuln-scan` | Full security chain | P0 |
| "SQL injection risk" / "taint analysis" | `dataflow` | `codelens dataflow workspace --source user_input --sink db_query` | P0 |
| "XSS risk" / "user input to HTML" | `dataflow` | `codelens dataflow workspace --source user_input --sink html_output` | P0 |
| "env var" / "environment variable" / "what must be set" | `env-check` | `codelens env-check workspace` | P1 |
| "dangerous regex" / "ReDoS" / "regex DoS" | `regex-audit` | `codelens regex-audit workspace` | P3 |
| "data flow" / "taint" / "sanitization" | `dataflow` | `codelens dataflow workspace` | P0 |
| "known vulnerabilities" / "CVE" / "dependency security" | `vuln-scan` | `codelens vuln-scan workspace` | P0 |

### Understanding & Onboarding Triggers

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| "how does this app work" / "explain this codebase" | `entrypoints` + `api-map` + `state-map` | Full understanding chain | P0 |
| "entry point" / "where does it start" / "main function" | `entrypoints` | `codelens entrypoints workspace` | P0 |
| "API route" / "endpoint" / "POST /users" | `api-map` | `codelens api-map workspace` | P1 |
| "state management" / "Redux" / "global state" / "Context" | `state-map` | `codelens state-map workspace` | P1 |
| "what framework" / "detect stack" | `detect` | `codelens detect workspace` | P3 |
| "scan workspace" / "analyze codebase" | `scan` | `codelens scan workspace` | P0 |

### Quality & Production Readiness Triggers

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| "production ready" / "ready to deploy" / "quality check" | `smell` + `complexity` + `debug-leak` + `dead-code` + `a11y` + `secrets` + `vuln-scan` | Quality Gate chain | P0 |
| "code smell" / "what to refactor first" / "technical debt" | `smell` | `codelens smell workspace` | P0 |
| "complexity" / "too complex" / "most complex function" | `complexity` | `codelens complexity workspace` | P2 |
| "console.log" / "debug code" / "cleanup before deploy" | `debug-leak` | `codelens debug-leak workspace` | P2 |
| "TODO" / "FIXME" / "HACK" | `debug-leak` | `codelens debug-leak workspace --category todo_fixme` | P2 |
| "dead code" / "unused" / "zombie CSS" | `dead-code` + `list --filter dead` | Full dead code analysis | P1 |
| "accessibility" / "a11y" / "WCAG" / "screen reader" | `a11y` | `codelens a11y workspace` | P3 |
| "missing alt text" / "form label" / "ARIA" | `a11y` | `codelens a11y workspace --category missing_alt` | P3 |
| "performance" / "slow" / "optimize" / "fast" | `perf-hint` | `codelens perf-hint workspace` | P1 |
| "CSS issues" / "style problems" / "z-index" | `css-deep` | `codelens css-deep workspace` | P2 |

### Refactoring & Change Triggers

| User Intent / Keywords | Tool | Command | Priority |
|------------------------|------|---------|----------|
| "rename" / "safe to rename" / "change function name" | `refactor-safe` + `impact` + `test-map` | Full refactoring chain | P1 |
| "move file" / "safe to move" | `refactor-safe` + `dependents` | Check move safety | P1 |
| "delete" / "safe to remove" | `impact` + `dead-code` | Impact then delete | P0 |
| "impact" / "what if I change" / "change impact" | `impact` | `codelens impact "name" workspace` | P1 |
| "pure function" / "side effect" / "impure" | `side-effect` | `codelens side-effect workspace` | P1 |
| "test coverage" / "is it tested" / "untested" | `test-map` | `codelens test-map workspace` | P1 |
| "error propagation" / "if this fails" / "crash path" | `stack-trace` | `codelens stack-trace "name" workspace` | P2 |
| "package drift" / "missing dep" / "unused dep" | `config-drift` | `codelens config-drift workspace` | P2 |
| "type" / "return type" / "infer type" | `type-infer` | `codelens type-infer workspace` | P3 |
| "owner" / "who wrote this" / "git blame" | `ownership` | `codelens ownership workspace` | P3 |

### Composite Scenario Triggers

| User Scenario | Auto-Chain | Priority |
|---------------|------------|----------|
| User writes new code with class/id/function | `init` → `scan` → `query` → write → `scan --incremental` | P0 |
| User reports a bug | `search` → `context` → `trace` → `missing-refs` | P1 |
| User asks "is this secure?" | `secrets` → `dataflow` → `env-check` → `vuln-scan` | P0 |
| User asks "is this production ready?" | `smell` → `complexity` → `debug-leak` → `dead-code` → `a11y` → `secrets` → `vuln-scan` | P0 |
| User onboards to new codebase | `handbook` (single command replaces multi-step chain) | P0 |
| User asks a vague question | `ask "question"` (NL router) | P1 |
| User wants to rename/delete | `refactor-safe` → `impact` → `test-map` → rename → `scan --incremental` | P1 |
| User deploys / pre-deploy check | `secrets` → `debug-leak` → `env-check` → `config-drift` → `vuln-scan` → `dead-code` | P0 |
| User builds new feature | `query` → `context` → `side-effect` → write → `scan --incremental` → `missing-refs` | P1 |
| User asks about performance | `perf-hint` → `complexity` → `circular` → `side-effect` | P1 |
| User asks about CSS quality | `css-deep` → `missing-refs` → `list --filter duplicate_define` | P2 |

---

## AI Workflows

### Basic Flow (Pre-write Check)

```
User asks to create a new feature with id/class/function
          │
          ▼
1. Check if registry exists
   - If not → codelens_init + codelens_scan
          │
          ▼
2. Call codelens_query for the name to be created
          │
          ├─ found: false → Proceed to create
          ├─ found: true + active → EXTEND, do not overwrite
          ├─ found: true + dead → Ask user: reuse or delete?
          ├─ found: true + duplicate_ref → LIST all referrers first
          └─ found: true + collision → STOP. Report. Fix first.
          │
          ▼
3. After creating → re-scan (incremental)
          │
          ▼
4. Flag dead code and collision to user
```

### Advanced Flow (Bug Investigation)

```
User: "Bug — modal won't close"
          │
          ▼
1. codelens_search "closeModal" workspace
   → Find where closeModal is defined and called
          │
          ▼
2. codelens_context "closeModal" workspace
   → View definition code, callers, callees, imports
          │
          ▼
3. codelens_trace "closeModal" workspace --direction up
   → Trace who calls closeModal (full chain)
          │
          ▼
4. codelens_missing-refs workspace
   → Check for missing CSS classes or wrong IDs
          │
          ▼
5. Report to user: "Bug found in ..."
```

### Pre-Delete Flow (Safe Removal)

```
User: "Delete function X"
          │
          ▼
1. codelens_impact "X" workspace --action delete
   → Check risk level and affected files
          │
          ├─ risk: critical → STOP. Report to user.
          ├─ risk: high → Warning. List affected.
          └─ risk: low → Proceed.
          │
          ▼
2. Delete function X
          │
          ▼
3. codelens_scan workspace --incremental
          │
          ▼
4. codelens_list workspace --filter dead
   → Check for new dead code that may have been created
          │
          ▼
5. codelens_diff workspace
   → Verify the changes that occurred
```

### Security Auditing Flow (v3)

```
User: "Is this API endpoint secure?"
          │
          ▼
1. codelens dataflow workspace --source user_input
   → Find where user input flows
          │
          ▼
2. codelens dataflow workspace --sink db_query
   → Check if unsanitized data reaches SQL
          │
          ▼
3. codelens side-effect processOrder workspace
   → Check if function has network/IO side effects
          │
          ▼
4. codelens smell workspace --severity critical
   → Find critical code smells nearby
          │
          ▼
5. Report: "Security findings..."
```

### Pre-Refactoring Flow (v3)

```
User: "Rename verify_token to validate_token"
          │
          ▼
1. codelens refactor-safe verify_token workspace --action rename --new-name validate_token
   → Check for hidden risks
          │
          ├─ safety: dangerous → STOP. Report risks.
          ├─ safety: risky → Warning. List string refs.
          └─ safety: safe → Proceed with rename.
          │
          ▼
2. codelens impact verify_token workspace --action modify
   → Check how many files affected
          │
          ▼
3. codelens test-map workspace --function verify_token
   → Check if tested (update test names too)
          │
          ▼
4. Rename + codelens scan workspace --incremental
```

### Security Audit Flow (v4 — Enhanced)

```
User: "Is this codebase secure for production?"
          │
          ▼
1. codelens secrets workspace
   → Find hardcoded API keys, passwords, tokens
          │
          ▼
2. codelens dataflow workspace --source user_input --sink db_query
   → Check unsanitized data flow to SQL
          │
          ▼
3. codelens dataflow workspace --source user_input --sink html_output
   → Check XSS risk
          │
          ▼
4. codelens env-check workspace
   → Find required env vars without fallbacks
          │
          ▼
5. codelens regex-audit workspace --severity critical
   → Find ReDoS-vulnerable regex
          │
          ▼
6. codelens debug-leak workspace
   → Find leftover debug code for cleanup
          │
          ▼
7. Report: "Security findings..."
```

### Web App Understanding Flow (v4)

```
User: "I need to understand this web app"
          │
          ▼
1. codelens entrypoints workspace
   → "Where does this app start? What are the entry points?"
          │
          ▼
2. codelens api-map workspace
   → "What endpoints exist? Which handlers serve them?"
          │
          ▼
3. codelens state-map workspace
   → "What global state exists? Who reads/writes it?"
          │
          ▼
4. codelens outline workspace --all
   → "What's the file structure?"
          │
          ▼
5. codelens dependents <key-file> workspace --direction graph
   → "How do modules relate?"
```

### Quality Gate Flow (v4)

```
User: "Is this code ready for production?"
          │
          ▼
1. codelens smell workspace
   → Health score and smell categories
          │
          ▼
2. codelens complexity workspace --threshold 20
   → Find overly complex functions
          │
          ▼
3. codelens debug-leak workspace
   → Leftover debug code?
          │
          ▼
4. codelens dead-code workspace
   → Unused code to remove?
          │
          ▼
5. codelens a11y workspace
   → Accessibility issues?
          │
          ▼
6. codelens secrets workspace
   → Leaked credentials?
          │
          ▼
7. Report: "Quality gate pass/fail..."
```

### Pre-Deploy Flow (v4)

```
User: "I'm about to deploy — anything I should check?"
          │
          ▼
1. codelens secrets workspace
   → Hardcoded credentials that could leak?
          │
          ▼
2. codelens debug-leak workspace
   → Leftover console.log, print, debugger statements?
          │
          ▼
3. codelens env-check workspace
   → Required env vars without fallback? Missing from .env.example?
          │
          ▼
4. codelens config-drift workspace
   → Declared but unused packages? Missing declarations?
          │
          ▼
5. codelens dead-code workspace
   → Unused code that adds bundle size?
          │
          ▼
6. Report: "Pre-deploy checklist results..."
```

### New Developer Onboarding Flow (v4)

```
User: "I'm new to this project — help me understand the codebase"
          │
          ▼
1. codelens detect workspace
   → What frameworks and tools are used?
          │
          ▼
2. codelens entrypoints workspace
   → Where does the app start? What are the entry points?
          │
          ▼
3. codelens api-map workspace
   → What API endpoints exist?
          │
          ▼
4. codelens state-map workspace
   → How is state managed? Where is the global state?
          │
          ▼
5. codelens outline workspace --all
   → What's the file structure and what does each file contain?
          │
          ▼
6. codelens ownership workspace
   → Who wrote what? Who to ask about specific code?
          │
          ▼
7. Report: "Codebase overview for onboarding..."
```

### New Feature Development Flow (v4 — Enhanced)

```
User: "Add a new shopping cart feature"
          │
          ▼
1. codelens query "cart" workspace
   → Does anything cart-related already exist?
          │
          ▼
2. codelens query "CartButton" workspace --domain frontend
   → Check for component name collision
          │
          ▼
3. codelens context "cart" workspace
   → If found, understand existing implementation
          │
          ▼
4. codelens side-effect workspace --name existingCartFn
   → Is existing cart code pure or impure?
          │
          ▼
5. Write new cart code
          │
          ▼
6. codelens scan workspace --incremental
   → Update registry with new code
          │
          ▼
7. codelens missing-refs workspace
   → Any CSS classes referenced but not defined?
          │
          ▼
8. codelens a11y workspace
   → Cart is user-facing — check accessibility
          │
          ▼
9. codelens test-map workspace --function addToCart
   → Is the new code tested?
          │
          ▼
10. Report: "Feature added, findings..."
```

### Performance Investigation Flow (v4)

```
User: "This page is slow — help me find the bottleneck"
          │
          ▼
1. codelens complexity workspace --threshold 15
   → Find overly complex functions (likely slow)
          │
          ▼
2. codelens side-effect workspace
   → Find impure functions (network/IO calls)
          │
          ▼
3. codelens circular workspace
   → Circular dependencies cause re-renders/re-computation
          │
          ▼
4. codelens state-map workspace
   → State that's read/written by many components = re-render cascade
          │
          ▼
5. codelens smell workspace --categories god_object large_file callback_hell
   → Patterns that hurt performance
          │
          ▼
6. Report: "Performance bottlenecks found..."
```

### Code Review Assistance Flow (v4)

```
User: "Review this PR / these changes"
          │
          ▼
1. codelens scan workspace --incremental
   → Update registry with latest code
          │
          ▼
2. codelens diff workspace
   → What changed since last snapshot?
          │
          ▼
3. codelens list workspace --filter dead
   → New dead code introduced?
          │
          ▼
4. codelens list workspace --filter collision
   → New ID collisions?
          │
          ▼
5. codelens missing-refs workspace
   → New CSS/HTML mismatches?
          │
          ▼
6. codelens secrets workspace --severity critical
   → Critical secrets leaked?
          │
          ▼
7. Report: "Code review findings..."
```

### Vulnerability Scanning Flow (v5)

```
User: "Are my dependencies secure?" / "Any known CVEs?"
          │
          ▼
1. codelens vuln-scan workspace
   → Scan dependencies for known CVEs
          │
          ▼
2. If findings found → codelens secrets workspace
   → Check for hardcoded credentials too
          │
          ▼
3. codelens env-check workspace
   → Are vulnerable env vars exposed?
          │
          ▼
4. Report: "Vulnerability findings with fix recommendations..."
```

### Performance Investigation Flow (v5 — Enhanced)

```
User: "Why is this slow?" / "Find performance bottlenecks"
          │
          ▼
1. codelens perf-hint workspace
   → Detect N+1, sync blocking, memory leaks, expensive renders
          │
          ▼
2. If N+1 found → codelens dataflow workspace
   → Trace data flow to understand query patterns
          │
          ▼
3. If memory leak found → codelens side-effect workspace
   → Check cleanup patterns in side effects
          │
          ▼
4. Report: "Performance findings with fix suggestions..."
```

### CSS Deep Audit Flow (v5)

```
User: "Is my CSS clean?" / "Check for CSS issues"
          │
          ▼
1. codelens css-deep workspace
   → Find unused vars, orphan keyframes, specificity wars, z-index abuse
          │
          ▼
2. If unused vars found → remove them
          │
          ▼
3. codelens missing-refs workspace
   → Cross-check: any CSS references now broken?
          │
          ▼
4. If specificity wars found → refactor
          │
          ▼
5. Report: "CSS audit findings with recommendations..."
```

---

## Error Recovery Flows

When a CodeLens command fails, follow these recovery procedures:

| Failure | Recovery |
|---------|----------|
| `scan` fails (file read error) | Skip unreadable files, scan the rest. Report which files failed. |
| `scan` fails (grammar import error) | Fallback to regex parser automatically. No action needed. |
| `query` fails (registry not found) | Auto-run `init` → `scan` → retry `query`. |
| `query` fails (registry corrupt) | Delete `.codelens/` directory → `init` → `scan` → retry. |
| `trace` fails (symbol not found) | Try `search` first to locate the symbol, then `trace` with the exact name. |
| `impact` fails (no edges) | Run `scan` first to build edges, then retry `impact`. |
| `vuln-scan` fails (npm not found) | Skip native audit, use built-in CVE database + lock-file parsing. |
| `perf-hint` returns too many results | Apply `--severity critical` or `--category` filter to narrow scope. |

---

## Supported Languages & Frameworks

| Language | Parser | Tracks |
|----------|--------|--------|
| HTML | tree-sitter-html | id, class |
| CSS | tree-sitter-css | .class, #id selectors |
| SCSS/Less | regex fallback | .class, #id selectors |
| JavaScript | tree-sitter-javascript | DOM selectors, function calls |
| TypeScript/TSX | tree-sitter-typescript | className, function calls, components |
| Rust | tree-sitter-rust | fn declarations, calls, impl blocks |
| Vue SFC | regex | :class, class, id, scoped styles |
| Svelte | regex | class:, class, id, scoped styles |
| Tailwind CSS | pattern detection | utility classes, @apply, dynamic patterns |

---

## Status & Flag Reference

| Status | Level | Meaning | AI Action |
|--------|-------|---------|-----------|
| `active` | node | Used, ref_count > 0 | Normal, proceed |
| `dead` | node | Nothing references it | Flag to user |
| `duplicate_ref` | node | Referenced from many places | List all callers |
| `collision` | node | ID on >1 HTML element (bug) | STOP, fix first |
| `duplicate_define` | flag | Defined >1x | Warning to user |

**Action Priority:**
1. `collision` → **STOP, fix first**
2. `duplicate_define` → **WARNING**
3. `dead` → **ASK first**
4. `duplicate_ref` → **LIST all callers first**
5. `active` → **Normal, proceed**
6. `found: false` → **Safe, proceed to create**

---

## Integration with AI Agent

CodeLens uses **passive integration** — the AI agent calls the CLI/API manually when needed.

### 3 Integration Methods

| Method | Best For | Latency |
|--------|----------|---------|
| **CLI (subprocess)** | Any agent, non-Python | ~200-500ms |
| **Python API (import)** | Python-based agents | ~50-100ms |
| **JSON file read** | Read-only, dashboard | ~1ms |

### Quick Integration (CLI)

```python
import subprocess, json
CLI = "/path/to/skills/codelens/scripts/codelens.py"

def cl_query(name, workspace):
    r = subprocess.run(["python3", CLI, "query", name, workspace],
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)
```

### Quick Integration (Python API)

```python
import sys; sys.path.insert(0, "/path/to/skills/codelens/scripts")
from codelens import cmd_scan, cmd_query, cmd_list, cmd_init

cmd_init("/workspace")                    # Once
cmd_scan("/workspace")                    # Before work
result = cmd_query("btn-primary", "/workspace")  # Before write
cmd_scan("/workspace", incremental=True)  # After write
```

### Mandatory Integration Rules

1. **Query before write** — ALWAYS call `codelens_query` before creating a new class/id/function
2. **Scan after write** — Run `codelens_scan --incremental` after modifying code
3. **STOP on collision** — Do not proceed if there is an ID collision, report to user
4. **Report dead code** — Do not silently ignore, show it to the user
5. **Handle errors gracefully** — Handle ImportError and FileNotFoundError

### Full Integration Guide

For complete details on integrating CodeLens with various AI agent types,
read: **`references/agent-integration.md`**

Covers:
- CLI & Python API integration patterns
- JSON output schemas for each command
- Decision trees (pre-write, post-write, refactoring)
- Integration patterns per agent type (editor, reviewer, refactoring, docs)
- Error handling & graceful degradation
- Multi-agent coordination
- Integration checklist

---

## Further References

Load the following reference files for details:

- `references/agent-integration.md` — **Guide for integrating with AI agents (CLI, Python API, JSON schemas, decision trees)**
- `references/parser-rules.md` — Parsing rules per language
- `references/query-examples.md` — Query examples and output interpretation
- `references/status-codes.md` — Details for all statuses and flags
