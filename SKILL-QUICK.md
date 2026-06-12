---
name: codelens
description: >
  CodeLens v7.2 Quick Reference — concise trigger map, core commands, and decision rules
  for AI agents. For complete documentation, see SKILL.md.
---

# CodeLens v7.2.0 — Quick Reference (45 Commands)

**MUST activate before writing/editing/deleting any class, id, or function.**

> **AI Loading Guide**: Read THIS FILE FIRST. Do NOT read scripts/*.py unless debugging errors.
> All commands support `--format json|markdown` and auto-detect workspace if omitted.

## State Prerequisites

1. No `.codelens/` → auto-run `init` → `scan` first
2. Registry stale (>24h) → auto-run `scan --incremental`
3. After code changes → always `scan --incremental` before re-query

## Trigger Map — User Intent → Tool

### Core (P0 — Always Trigger)

| User Intent | Tool | Command |
|-------------|------|---------|
| Create new class/id/function | `query` | `codelens query "name" ws` |
| Edit existing code | `query` + `context` | Query first, then context |
| **Anti-overload summary** | `summary` | `codelens summary ws` |
| Quick overview | `summary --detail minimal` | `codelens summary --detail minimal ws` |
| Delete code | `impact` + `dead-code` | Impact check, then delete |
| "does this exist?" | `query` | `codelens query "name" ws` |
| "who calls this?" | `trace --direction up` | `codelens trace "name" ws` |
| Security audit | `secrets` → `dataflow` → `env-check` → `vuln-scan` | Full chain |
| Vulnerability scan | `vuln-scan` | `codelens vuln-scan ws` |

### Search & Understanding (P1)

| User Intent | Tool | Command |
|-------------|------|---------|
| Search pattern | `search` | `codelens search "pattern" ws` |
| Find symbol | `symbols` | `codelens symbols "name" ws` |
| Symbol detail | `context` | `codelens context "name" ws` |
| File structure | `outline` | `codelens outline ws --file path` |
| API routes | `api-map` | `codelens api-map ws` |
| Global state | `state-map` | `codelens state-map ws` |
| Performance issues | `perf-hint` | `codelens perf-hint ws` |

### Quality & Production (P1-P2)

| User Intent | Tool | Command |
|-------------|------|---------|
| "production ready?" | `smell` → `complexity` → `debug-leak` → `dead-code` → `a11y` → `secrets` | Quality gate |
| "what to refactor?" | `smell` | `codelens smell ws` |
| "too complex" | `complexity` | `codelens complexity ws` |
| "cleanup before deploy" | `debug-leak` | `codelens debug-leak ws` |
| "dead code?" | `dead-code` + `list --filter dead` | Full dead code |
| "accessible?" | `a11y` | `codelens a11y ws` |
| "CSS issues?" | `css-deep` | `codelens css-deep ws` |

### Refactoring (P1-P2)

| User Intent | Tool | Command |
|-------------|------|---------|
| "safe to rename?" | `refactor-safe` → `impact` → `test-map` | Full chain |
| "safe to delete?" | `impact` → `dead-code` | Impact then delete |
| "pure function?" | `side-effect` | `codelens side-effect ws` |
| "is it tested?" | `test-map` | `codelens test-map ws` |

## Query Decision Rules

| Query Result | Action |
|-------------|--------|
| `found: false` | SAFE — create new |
| `found: true` + `status: active` | EXTEND — don't overwrite |
| `found: true` + `status: dead` | ASK user — reuse or delete? |
| `found: true` + `status: duplicate_ref` | LIST all referrers first |
| `found: true` + `status: collision` | STOP — active bug, fix first |

## Negative Triggers — SKIP CodeLens

- Document generation (PDF, reports, docs)
- Image/media generation
- Web search queries
- Non-codebase knowledge questions
- Non-code file editing (config, markdown)

## Default Fallback Chains (Vague Requests)

| Pattern | Default Chain |
|---------|---------------|
| General "check/review" | `smell` → `dead-code` → `secrets` |
| "safe/secure?" | `secrets` → `dataflow` → `env-check` → `vuln-scan` |
| "good/clean/ready?" | `complexity` → `debug-leak` → `a11y` → `smell` |
| "slow/fast/optimize" | `perf-hint` → `complexity` → `circular` |
| "CSS/style/layout" | `css-deep` → `missing-refs` → `list --filter duplicate_define` |
| "deploy/ship/release" | `secrets` → `debug-leak` → `env-check` → `vuln-scan` → `dead-code` |

## Colloquial Triggers

| Phrase (EN/ID) | Tool Chain |
|-----------------|------------|
| "this is slow" / "kok lama ya" | `perf-hint` → `complexity` → `circular` |
| "something's weird" / "aneh nih" | `search` → `context` → `trace` → `missing-refs` |
| "help me check" / "bantu cek" | `smell` → `dead-code` → `secrets` |
| "clean up" / "bersihkan" | `debug-leak` → `dead-code` → `smell` |
| "is this safe?" / "aman ga" | `secrets` → `vuln-scan` → `debug-leak` → `env-check` |

---

## All 45 Commands — Grouped by Category

### Setup & Registry

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 1 | `init` | `$CLI init [ws]` | JSON `{initialized, config_path}` | `workspace-not-found` |
| 2 | `scan` | `$CLI scan [ws] [--incremental]` | JSON `{scanned_files, registry_size}` | `workspace-not-found`, `parse-error` |
| 3 | `validate` | `$CLI validate [ws]` | JSON `{valid, issues[]}` | `no-registry` |

### Pre-Write Checks (MOST IMPORTANT)

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 4 | `query` | `$CLI query "name" [ws] [--domain {frontend,backend}] [--fuzzy]` | JSON `{found, status, callers, callees}` | `no-registry` |
| 5 | `impact` | `$CLI impact "name" [ws] [--action {modify,delete}]` | JSON `{affected[], risk_level}` | `symbol-not-found`, `no-registry` |
| 6 | `refactor-safe` | `$CLI refactor-safe "name" [ws] [--action {rename,move}] [--new-name X]` | JSON `{safe, conflicts[], suggestions[]}` | `symbol-not-found`, `no-registry` |

### Navigation & Understanding

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 7 | `summary` | `$CLI summary [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full,auto}]` | JSON/MD `{overview, findings[]}` | `no-registry`, `timeout` |
| 8 | `context` | `$CLI context "name" [ws] [--domain {frontend,backend,auto}]` | JSON `{symbol, code, callers[], callees[]}` | `symbol-not-found`, `no-registry` |
| 9 | `trace` | `$CLI trace "name" [ws] [--direction {up,down,both}] [--depth N]` | JSON `{chain[], depth}` | `symbol-not-found`, `no-registry` |
| 10 | `search` | `$CLI search "pattern" [ws]` | JSON `{matches[], count}` | `no-registry` |
| 11 | `symbols` | `$CLI symbols "name" [ws] [--domain {frontend,backend,all}] [--fuzzy]` | JSON `{symbols[], count}` | `no-registry` |
| 12 | `outline` | `$CLI outline [ws] [--file path] [--detail {minimal,normal,full}]` | JSON `{file, functions[], classes[]}` | `file-not-found`, `no-registry` |
| 13 | `dependents` | `$CLI dependents "file" [ws] [--direction {dependents,dependencies,graph}]` | JSON `{dependents[], dependencies[]}` | `file-not-found`, `no-registry` |
| 14 | `list` | `$CLI list [ws] [--filter {all,dead,duplicate_define,duplicate_ref,collision,active}] [--domain {frontend,backend,all}]` | JSON `{entries[], total}` | `no-registry` |
| 15 | `ask` | `$CLI ask "question" [ws]` | JSON `{answer, suggested_commands[]}` | `no-registry` |

### Entry Points & Architecture

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 16 | `entrypoints` | `$CLI entrypoints [ws] [--type {main,http_handler,event_handler,cli_command,cron_job,worker,module_export,test_entry}] [--exclude-tests]` | JSON `{entrypoints[]}` | `no-registry`, `timeout` |
| 17 | `api-map` | `$CLI api-map [ws] [--method {GET,POST,PUT,DELETE,PATCH}] [--path filter] [--production-only]` | JSON `{routes[{method, path, handler, file}]}` | `no-registry` |
| 18 | `state-map` | `$CLI state-map [ws] [--store name]` | JSON `{stores[{name, actions, files}]}` | `no-registry` |
| 19 | `detect` | `$CLI detect [ws]` | JSON `{frameworks[], languages[]}` | `workspace-not-found` |
| 20 | `handbook` | `$CLI handbook [ws]` | JSON/MD `{project_overview, conventions, key_files}` | `workspace-not-found`, `timeout` |
| 21 | `diff` | `$CLI diff [ws] [--snapshot1 ID] [--snapshot2 ID] [--list-snapshots]` | JSON `{added[], removed[], modified[]}` | `no-snapshots`, `no-registry` |

### Security

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 22 | `secrets` | `$CLI secrets [ws] [--severity {critical,high,medium,low}]` | JSON `{findings[{type, severity, file, line, snippet}]}` | `no-registry` |
| 23 | `dataflow` | `$CLI dataflow [ws] [--source {user_input,env_var,file_input,api_response}] [--sink {db_query,html_output,command_exec,file_write,http_header}]` | JSON `{flows[{source, path, sink, risk}]}` | `no-registry`, `timeout` |
| 24 | `vuln-scan` | `$CLI vuln-scan [ws] [--severity {critical,high,medium,low}]` | JSON `{vulnerabilities[{cve, package, severity, fix_version}]}` | `no-lockfile`, `no-registry` |
| 25 | `env-check` | `$CLI env-check [ws] [--var NAME]` | JSON `{variables[{name, used_in[], defined_in, missing}]}` | `no-registry` |

### Code Quality

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 26 | `smell` | `$CLI smell [ws] [--categories ...] [--severity {info,warning,critical}]` | JSON `{smells[{category, severity, file, description}]}` | `no-registry` |
| 27 | `complexity` | `$CLI complexity [ws] [--name FN] [--file PATH] [--threshold N] [--sort {complexity,cognitive,loc}]` | JSON `{functions[{name, complexity, cognitive, loc}]}` | `no-registry` |
| 28 | `dead-code` | `$CLI dead-code [ws] [--categories {unreachable,unused_exports,zombie_css,unused_vars,dead_listeners}]` | JSON `{findings[{category, item, file}]}` | `no-registry` |
| 29 | `debug-leak` | `$CLI debug-leak [ws] [--category {console_log,print_statement,debugger,todo_fixme,commented_code,test_skip,mock_data,dev_only}]` | JSON `{leaks[{category, file, line, snippet}]}` | `no-registry` |
| 30 | `circular` | `$CLI circular [ws] [--domain {backend,imports,css,all}]` | JSON `{cycles[{participants, type}]}` | `no-registry` |
| 31 | `missing-refs` | `$CLI missing-refs [ws]` | JSON `{missing[{ref, file, type}]}` | `no-registry` |
| 32 | `side-effect` | `$CLI side-effect [ws] [--name FN] [--file PATH]` | JSON `{functions[{name, pure, effects[]}]}` | `no-registry` |
| 33 | `perf-hint` | `$CLI perf-hint [ws] [--severity {critical,high,medium,low}] [--category {n_plus_one,sync_blocking,memory_leak,expensive_renders,large_bundle,inefficient_iteration,cache_miss}]` | JSON `{hints[{category, severity, file, description}]}` | `no-registry` |

### Refactoring & Safety

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 34 | `test-map` | `$CLI test-map [ws] [--function FN] [--file PATH]` | JSON `{coverage[{function, tested, test_files[]}]}` | `no-registry` |
| 35 | `stack-trace` | `$CLI stack-trace "name" [ws] [--error-type TYPE] [--depth N]` | JSON `{propagation[{function, error_type, file}]}` | `symbol-not-found`, `no-registry` |
| 36 | `config-drift` | `$CLI config-drift [ws]` | JSON `{drift[{package, declared_version, actual_usage}]}` | `no-lockfile`, `no-registry` |

### Frontend-Specific

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 37 | `css-deep` | `$CLI css-deep [ws] [--severity {high,medium,low}] [--category {unused_vars,orphan_keyframes,specificity_wars,duplicate_props,unused_media,z_index_abuse}]` | JSON `{issues[{category, severity, file, detail}]}` | `no-registry` |
| 38 | `a11y` | `$CLI a11y [ws]` | JSON `{issues[{rule, severity, element, file}]}` | `no-registry` |

### Advanced & Specialized

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 39 | `analyze` | `$CLI analyze [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full}] [--skip-scan]` | JSON `{summary, security, quality, architecture}` | `workspace-not-found`, `timeout` |
| 40 | `type-infer` | `$CLI type-infer [ws] [--file PATH] [--function FN]` | JSON `{types[{name, inferred_type, confidence}]}` | `no-registry` |
| 41 | `ownership` | `$CLI ownership [ws] [--file PATH] [--function FN]` | JSON `{owners[{author, lines, percentage}]}` | `no-git`, `no-registry` |
| 42 | `regex-audit` | `$CLI regex-audit [ws] [--severity {high,medium,low}]` | JSON `{issues[{pattern, severity, risk, file}]}` | `no-registry` |
| 43 | `binary-scan` | `$CLI binary-scan [ws]` | JSON `{binaries[{path, type, size}]}` | `workspace-not-found` |
| 44 | `artifact-scan` | `$CLI artifact-scan [ws] [--deep]` | JSON `{artifacts[{path, type, details}]}` | `workspace-not-found` |

### Utility

| # | Command | Syntax | Output | Errors |
|---|---------|--------|--------|--------|
| 45 | `watch` | `$CLI watch [ws] [--debounce SECS]` | Streaming: file change events | `workspace-not-found` |

> **Note**: `watch` runs continuously until interrupted. Not for one-shot use.

---

## CLI Usage Pattern

```bash
CODELENS_DIR="{project_path}"
CLI="python3 $CODELENS_DIR/scripts/codelens.py"

# Workspace is AUTO-DETECTED if omitted (since v5.1)
# Fallback: cwd → parent dirs → last workspace → cwd

# Setup
$CLI init
$CLI scan

# Pre-write check (MOST IMPORTANT)
$CLI query "newName"

# With explicit workspace
$CLI init /workspace
$CLI scan /workspace

# Post-write update
$CLI scan --incremental

# Analysis
$CLI smell
$CLI secrets
$CLI vuln-scan
$CLI perf-hint
$CLI css-deep

# Agent-first commands (since v5.2)
$CLI handbook              # One-shot project orientation
$CLI ask "dead code?"      # Natural language query
$CLI context "fn" -f markdown  # Markdown output
```
