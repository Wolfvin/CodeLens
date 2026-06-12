---
name: codelens
description: >
  CodeLens v7.2 — Live Codebase Reference Intelligence (Tree-sitter Edition).
  MUST activate before writing/editing/deleting any class, id, or function.
  Supports 28+ languages. Powered by tree-sitter for AST-based parsing.
  For quick reference, see SKILL-QUICK.md. For version history, see CHANGELOG.md.
---

# CodeLens v7.2

Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

For quick command reference with output schemas and error hints, see **[SKILL-QUICK.md](SKILL-QUICK.md)**.
For version history, see **[CHANGELOG.md](CHANGELOG.md)**.

---

## Setup & Onboarding

```bash
CODELENS_DIR="{project_path}"
CLI="python3 $CODELENS_DIR/scripts/codelens.py"

# 1. First-time setup (one-time)
bash "$CODELENS_DIR/setup.sh"       # Installs tree-sitter + grammar packages

# 2. Initialize workspace (creates .codelens/ config)
$CLI init                           # Auto-detects workspace from cwd

# 3. Build registry (required before any analysis)
$CLI scan                           # Scans all source files, ~1-5 min depending on repo size
$CLI scan --incremental             # Re-scan only changed files (fast, ~1-5 sec)

# 4. Ready to use!
$CLI query "myFunction"             # Check if name exists before writing
```

**Performance notes:**
- `scan` on repos <500 files: ~5-15 seconds
- `scan` on repos 1000-5000 files: ~30-120 seconds
- `scan` on repos 5000+ files: use `--max-files 3000` to prevent timeout
- `scan --incremental` after code changes: ~1-5 seconds
- If `scan` times out, reduce scope with `--max-files` or re-run with `--incremental`

---

## Workspace Auto-Detect

The `workspace` argument is **optional** for ALL commands. If omitted, CodeLens auto-detects via:

1. Current directory (if has project markers: package.json, pyproject.toml, Cargo.toml, etc.)
2. Parent directories (walk up to 10 levels to find project root)
3. Last used workspace (cached at `~/.codelens/.codelens_last_workspace`)
4. Fallback: current working directory

```bash
$CLI scan              # Auto-detect → works!
$CLI query "myFunc"    # Auto-detect → works!
$CLI smell             # Auto-detect → works!
```

---

## Security Commands

### `secrets` — Hardcoded Secret Detection

Scans source code for hardcoded passwords, API keys, tokens, connection strings, and other sensitive values.

```bash
$CLI secrets [ws] [--severity {critical,high,medium,low}]
```

**Output:** JSON with `stats.total_secrets`, `risk` level, `findings[]` (type, file, line, match, severity).
**Categories:** password, api_key, token, connection_string, private_key.

### `dataflow` — Source-to-Sink Data Flow Analysis

Traces how data flows from sources (user input, env vars) to sinks (DB queries, HTML output, command exec).

```bash
$CLI dataflow [ws] [--source {user_input,env_var,file_input,api_response}] [--sink {db_query,html_output,command_exec,file_write,http_header}] [--depth N] [--max-files N] [--timeout SECS]
```

**Output:** JSON with `stats.violations`, `risk` level, `violations[]` (source→sink paths with sanitization status).
**Key fields:** `stats.production_violations` vs `stats.test_violations` — focus on production.

### `vuln-scan` — Dependency Vulnerability Scan

Scans dependency lockfiles (package-lock.json, Cargo.lock, requirements.txt) for known CVEs using native audit tools (npm audit, cargo audit, pip-audit, govulncheck) + built-in vulnerability database.

```bash
$CLI vuln-scan [ws] [--severity {critical,high,medium,low}]
```

**Output:** JSON with `stats.total_vulnerabilities`, `risk` level, `findings[]` (CVE, package, severity, fix_version).
**Requires:** Lockfile in workspace. Without lockfile, returns empty results.

### `env-check` — Environment Variable Audit

Tracks environment variable usage: which are required, which are missing from .env files, which are undocumented.

```bash
$CLI env-check [ws] [--var VAR_NAME]
```

**Output:** JSON with `stats.total_vars`, `variables[]` (name, required, used_in[], defined_in, missing).

---

## Quality Commands

### `smell` — Code Smell Detection

Detects 10 categories of code smells across the workspace.

```bash
$CLI smell [ws] [--categories ...] [--severity {info,warning,critical}]
```

**Output:** JSON with `health_score` (0-100), `total_findings`, `stats.by_category`, `stats.by_severity`.
**Categories:** long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent, sql_injection.

### `complexity` — Cyclomatic & Cognitive Complexity

Computes per-function complexity metrics.

```bash
$CLI complexity [ws] [--name FN] [--file PATH] [--threshold N] [--sort {complexity,cognitive,loc}] [--limit N]
```

**Output:** JSON with `stats` (avg_cyclomatic, avg_cognitive, high_complexity count), `functions[]` (name, complexity, cognitive, loc, file).
**Levels:** simple (1-5), moderate (6-10), complex (11-20), very_complex (21-50), untamable (50+).

### `dead-code` — Dead Code Detection

Finds unreachable code, unused exports, zombie CSS, unused variables, and dead event listeners.

```bash
$CLI dead-code [ws] [--categories {unreachable,unused_exports,zombie_css,unused_vars,dead_listeners}] [--max-results N]
```

**Output:** JSON with `stats.by_category`, findings grouped by category with file, line, item details.

### `debug-leak` — Debug Code Detection

Finds leftover debug code that should be removed before production.

```bash
$CLI debug-leak [ws] [--category {console_log,print_statement,debugger,todo_fixme,commented_code,test_skip,mock_data,dev_only}]
```

**Output:** JSON with `stats.by_category`, findings with file, line, snippet for each leak.

### `circular` — Circular Dependency Detection

Detects circular dependencies in function calls, module imports, and CSS.

```bash
$CLI circular [ws] [--domain {backend,imports,css,all}]
```

**Output:** JSON with `total_cycles`, `cycles.function_calls[]`, `cycles.import_cycles[]`, `cycles.css_cycles[]`.

### `missing-refs` — CSS/HTML Reference Mismatch

Detects CSS classes with no HTML usage, HTML classes with no CSS definition, and possible typos.

```bash
$CLI missing-refs [ws]
```

**Output:** JSON with `total_issues`, `issues.css_no_html[]`, `issues.html_no_css[]`, `issues.possible_typos[]`.

### `side-effect` — Pure vs Impure Function Analysis

Classifies functions as pure or impure based on detected side effects.

```bash
$CLI side-effect [ws] [--name FN] [--file PATH]
```

**Output:** JSON with `analyses[]` (name, classification: pure/impure, side_effects[], effect_count).

### `perf-hint` — Performance Anti-Pattern Detection

Detects 8 categories of performance issues.

```bash
$CLI perf-hint [ws] [--severity {critical,high,medium,low}] [--category {n_plus_one,sync_blocking,memory_leak,expensive_renders,large_bundle,inefficient_iteration,unoptimized_images,cache_miss}]
```

**Output:** JSON with `stats.by_category`, `stats.by_severity`, hints with file, line, description.

---

## Pre-Write & Refactoring Commands

### `query` — Name Existence Check (MOST IMPORTANT)

Check if a class, id, or function name already exists in the registry. **MUST be called before creating any new name.**

```bash
$CLI query "name" [ws] [--domain {frontend,backend}] [--file PATH] [--fuzzy]
```

**Output:** JSON with `found` (bool), `status` (active/dead/duplicate_ref/collision), `action` (CREATE/EXTEND/ASK/STOP), `action_reason`, `callers[]`, `callees[]`.

### `impact` — Change Impact Analysis

Analyzes what would break if a symbol is modified or deleted.

```bash
$CLI impact "name" [ws] [--action {modify,delete}]
```

**Output:** JSON with `risk` (low/medium/high/critical), `affected.direct[]`, `affected.indirect[]`, `affected.files[]`, `affected.tests[]`, `recommendations[]`, `risk_level`, `recommended_action`.

### `refactor-safe` — Rename/Move Safety Check

Pre-flight check for rename or move operations.

```bash
$CLI refactor-safe "name" [ws] [--action {rename,move}] [--new-name X]
```

**Output:** JSON with `safety` (safe/mostly_safe/risky/dangerous), `risks` (doc_refs[], string_refs[], dynamic_refs[]).

### `test-map` — Test Coverage Mapping

Maps which functions have corresponding test files.

```bash
$CLI test-map [ws] [--function FN] [--file PATH]
```

**Output:** JSON with `stats` (coverage_percent, tested_functions, untested_functions), `coverage_map{file: {tested[], untested[]}}`.

### `stack-trace` — Error Propagation Simulation

Traces how errors from a function would propagate through the call chain.

```bash
$CLI stack-trace "name" [ws] [--error-type TYPE] [--depth N]
```

**Output:** JSON with `chains[]` (origin → propagation path with function, file, line).

### `config-drift` — Dependency Drift Detection

Compares declared dependencies vs actual imports.

```bash
$CLI config-drift [ws]
```

**Output:** JSON with `declared_dependencies`, `actual_imports_summary`, `drift` (unused_deps[], missing_deps[], version_mismatches[]).

---

## Navigation & Understanding Commands

### `summary` — Anti-Overload Project Summary

Condensed project overview with prioritized findings. Best for getting a quick picture without information overload.

```bash
$CLI summary [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full,auto}] [--max-tokens N] [--write-agent-md]
```

**Output:** JSON with `identity`, `registry_stats`, `findings[]` (category, total, by_severity, top_items).

### `context` — Rich Symbol Context

Get definition, nearby symbols, callers, callees, and quality metrics for a symbol.

```bash
$CLI context "name" [ws] [--domain {frontend,backend,auto}] [--context-lines N] [--no-code]
```

**Output:** JSON with `found`, `context.definition` (type, name, status, ref_count, file, line), `context.nearby_symbols[]`, `context.quality` (complexity, side_effects, test_coverage).

### `trace` — Deep Call Chain Tracing

Follow the call graph from a symbol, multi-level deep.

```bash
$CLI trace "name" [ws] [--direction {up,down,both}] [--depth N] [--domain {frontend,backend,auto}]
```

**Output:** JSON with `chains.up[]` (callers), `chains.down[]` (callees), `tree` (hierarchical call tree).

### `search` — Regex Code Search

Search for a text pattern across all source files.

```bash
$CLI search "pattern" [ws]
```

**Output:** JSON with `matches[]` (file, line, match text, start_col, end_col).

### `symbols` — Registry Symbol Search

Search for symbols in the registry by name.

```bash
$CLI symbols "name" [ws] [--domain {frontend,backend,all}] [--fuzzy]
```

**Output:** JSON with `results[]` (name, type, status, ref_count, file, line, domain), `stats` (total_matches, truncated).

### `outline` — File Structure Outline

Get the structure of a file: imports, functions, classes, with line numbers.

```bash
$CLI outline [ws] [--file PATH] [--detail {minimal,normal,full}] [--all]
```

**Output:** JSON with `outline.imports[]`, `outline.functions[]`, `outline.classes[]` (each with name, line, params).

### `dependents` — Module Import Tracking

Find which files import a given file, or what a file imports.

```bash
$CLI dependents "file" [ws] [--direction {dependents,dependencies,graph}] [--depth N]
```

**Output:** JSON with `direct_dependents[]`, `transitive_dependents[]`, `stats` (direct_count, transitive_count).

### `list` — Registry Listing with Filter

List registry entries filtered by status or domain.

```bash
$CLI list [ws] [--filter {all,dead,duplicate_define,duplicate_ref,collision,active}] [--domain {frontend,backend,all}] [--limit N] [--offset N]
```

**Output:** JSON with `entries[]`, `total`, `count`, `has_more`, `summary.by_type`, `summary.by_status`.

### `ask` — Natural Language Query Router

Ask a question about the codebase in plain English. Routes to the appropriate command.

```bash
$CLI ask "question" [ws]
```

**Output:** JSON with `results` (depends on routed command), may include `stats` and findings from the routed engine.

---

## Architecture & Discovery Commands

### `entrypoints` — Execution Entry Point Mapping

Find all entry points: main functions, HTTP handlers, CLI commands, event handlers, cron jobs, workers, test entries.

```bash
$CLI entrypoints [ws] [--type {main,http_handler,event_handler,cli_command,cron_job,worker,module_export,test_entry}] [--exclude-tests]
```

**Output:** JSON with `stats.total_entrypoints`, `stats.by_type`, `entrypoints[]` (type, file, line, name).

### `api-map` — Route-to-Handler Mapping

Map REST, GraphQL, and gRPC routes to their handler functions.

```bash
$CLI api-map [ws] [--method {GET,POST,PUT,DELETE,PATCH}] [--path FILTER] [--production-only]
```

**Output:** JSON with `stats.total_routes`, `routes[]` (method, path, handler, file, line).

### `state-map` — Global State Management Tracking

Track global state stores: Redux, Vuex, Pinia, Context, module-level Python variables.

```bash
$CLI state-map [ws] [--store NAME]
```

**Output:** JSON with `stats.total_stores`, `stores[]` (name, type, actions[], files[]).

### `detect` — Framework Detection

Detect frameworks, languages, and tools used in the workspace.

```bash
$CLI detect [ws]
```

**Output:** JSON with `frameworks[]`, `has_react`, `has_vue`, `has_nextjs`, etc. (boolean flags).

### `handbook` — Project Handbook for AI Agents

One-stop project orientation: identity, structure, health, conventions, risks, quick reference.

```bash
$CLI handbook [ws] [--max-files N] [--timeout SECS]
```

**Output:** JSON with `identity`, `structure`, `health`, `conventions`, `risks`, `quick_reference`. Also writes `.codelens/AGENT.md`.

### `diff` — Registry Snapshot Comparison

Compare two registry snapshots to see what changed.

```bash
$CLI diff [ws] [--snapshot1 ID] [--snapshot2 ID] [--list-snapshots]
```

**Output:** JSON with `added[]`, `removed[]`, `modified[]` entries between snapshots.

---

## Advanced Commands

### `analyze` — Full Repository Analysis (One-Shot)

Runs init + scan + all engines in one command. Best for comprehensive analysis.

```bash
$CLI analyze [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full}] [--skip-scan] [--timeout SECS] [--max-items N]
```

**Output:** JSON with `identity`, `frameworks`, `languages`, `architecture`, `security`, `quality`, `risk_score`, `action_plan[]`.

### `type-infer` — Lightweight Type Inference

Infer types for JavaScript/Python functions based on usage patterns.

```bash
$CLI type-infer [ws] [--file PATH] [--function FN]
```

**Output:** JSON with `type_map{file: {var: {type, confidence}}}`, `stats` (variables_typed, functions_typed, high_confidence).

### `ownership` — Git Blame-Based Code Ownership

Find who owns what code using git blame data.

```bash
$CLI ownership [ws] [--file PATH] [--function FN]
```

**Output:** JSON with `ownership[]` (author, lines, percentage, first_commit, last_commit). Fallback to mtime if no git repo.

### `regex-audit` — Regex Safety Audit

Audit regex patterns for ReDoS vulnerability, unsafe constructors, and incorrect escaping.

```bash
$CLI regex-audit [ws] [--severity {high,medium,low}]
```

**Output:** JSON with `stats.vulnerable`, `stats.by_category` (redos_vulnerable, unsafe_constructor, overly_broad, incorrect_escaping, performance).

### `a11y` — Accessibility Audit

Detect WCAG compliance issues in HTML/JSX.

```bash
$CLI a11y [ws]
```

**Output:** JSON with `issues[]` (rule, severity, element, file), `wcag_mapping`, `recommendations[]`.

### `css-deep` — Deep CSS Analysis

Analyze CSS for unused variables, orphan keyframes, specificity wars, duplicate properties, z-index abuse.

```bash
$CLI css-deep [ws] [--severity {high,medium,low}] [--category {unused_vars,orphan_keyframes,specificity_wars,duplicate_props,unused_media,z_index_abuse}]
```

**Output:** JSON with `stats.by_category`, `issues[]` (category, severity, file, detail).

### `binary-scan` — Binary/Compiled Artifact Scan

Scan for compiled binaries, Tauri/Electron artifacts.

```bash
$CLI binary-scan [ws]
```

**Output:** JSON with `stats.total_artifacts`, `findings[]` (path, type, size).

### `artifact-scan` — Compiled Artifact Reverse Engineering

Deep scan for compiled artifacts with source map and WASM analysis.

```bash
$CLI artifact-scan [ws] [--deep]
```

**Output:** JSON with `stats` (binaries, minified_files, source_maps, wasm_modules, built_output_dirs).

---

## AI Workflows

### Pre-Write Check (MANDATORY)

```
1. Check registry exists → if not: init + scan
2. query "name" → found: false = SAFE, active = EXTEND, dead = ASK, collision = STOP
3. Write code
4. scan --incremental
```

### Security Audit Chain

```
secrets → dataflow (user_input→sinks) → env-check → vuln-scan
```

### Quality Gate

```
smell → complexity → debug-leak → dead-code → a11y → secrets
```

### Pre-Deploy Checklist

```
secrets → debug-leak → env-check → config-drift → vuln-scan → dead-code
```

### Code Review

```
scan --incremental → diff → list --filter dead → list --filter collision → missing-refs → secrets --severity critical
```

### Bug Investigation

```
search "pattern" → context "name" → trace --direction up → missing-refs
```

### New Feature Development

```
query "name" → context (if exists) → side-effect → write → scan --incremental → missing-refs → test-map
```

---

## Error Recovery

| Failure | Recovery |
|---------|----------|
| `scan` file read error | Skip unreadable files, scan the rest |
| `scan` grammar import error | Fallback to regex parser automatically |
| `query` registry not found | Auto-run `init` → `scan` → retry |
| `query` registry corrupt | Delete `.codelens/` → `init` → `scan` → retry |
| `trace` symbol not found | Try `search` first to locate, then `trace` with exact name |
| `impact` no edges | Run `scan` first to build edges, then retry |
| `vuln-scan` no lockfile | Returns empty results — not an error |
| `ownership` no git repo | Fallback to mtime-based analysis |
| `perf-hint` too many results | Apply `--severity critical` or `--category` filter |
| Any command timeout | Use `--max-files` to reduce scope, or `--timeout` to increase budget |

---

## Supported Languages

| Language | Parser | Tracks |
|----------|--------|--------|
| HTML | tree-sitter-html | id, class |
| CSS/SCSS | tree-sitter-css / regex | .class, #id selectors |
| JavaScript | tree-sitter-javascript | DOM selectors, function calls |
| TypeScript/TSX | tree-sitter-typescript | className, function calls, components |
| Rust | tree-sitter-rust | fn declarations, calls, impl blocks |
| Python | tree-sitter-python / regex | def, class, imports, calls |
| Vue SFC | regex | :class, class, id, scoped styles |
| Svelte | regex | class:, class, id |
| Go | regex | func declarations, calls |
| PHP | regex | function declarations, calls |
| Java/C#/Dart/Kotlin | regex | function declarations, calls |

---

## Status & Flag Reference

| Status | Meaning | AI Action |
|--------|---------|-----------|
| `active` | Used, ref_count > 0 | Normal, proceed |
| `dead` | Nothing references it | Flag to user |
| `duplicate_ref` | Referenced from many places | List all callers |
| `collision` | ID on >1 HTML element (bug) | STOP, fix first |
| `duplicate_define` | Defined >1x | Warning |

**Priority order:** collision → duplicate_define → dead → duplicate_ref → active → found:false

---

## Integration with AI Agent

### CLI Integration (Recommended)

```python
import subprocess, json
CLI = "/path/to/codelens/scripts/codelens.py"

def cl_query(name, workspace):
    r = subprocess.run(["python3", CLI, "query", name, workspace],
                       capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)
```

### Mandatory Rules

1. **Query before write** — ALWAYS call `query` before creating new class/id/function
2. **Scan after write** — Run `scan --incremental` after modifying code
3. **STOP on collision** — Do not proceed if ID collision detected
4. **Report dead code** — Show it to user, don't silently ignore
5. **Handle errors** — Gracefully handle subprocess timeouts and JSON parse errors

### Reference Files

- `references/agent-integration.md` — Full integration guide (CLI, Python API, JSON schemas, decision trees)
- `references/parser-rules.md` — Parsing rules per language
- `references/query-examples.md` — Query examples and output interpretation
- `references/status-codes.md` — Details for all statuses and flags
