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

## First-Time Setup

```bash
CODELENS_DIR="{project_path}"
CLI="python3 $CODELENS_DIR/scripts/codelens.py"

# 1. Install dependencies (one-time)
bash "$CODELENS_DIR/setup.sh"

# 2. Initialize workspace
$CLI init                  # Creates .codelens/ config, auto-detects workspace

# 3. Build registry (REQUIRED before any analysis)
$CLI scan                  # Scans all source files. <500 files: ~5-15s, 1K-5K: ~30-120s
                           # For large repos: $CLI scan --max-files 3000

# 4. Done! Use any command
$CLI query "myFunction"    # Check before writing
```

**After code changes**: always `$CLI scan --incremental` (~1-5s) before re-querying.

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

## Command vs Command — Disambiguation Guide

| You want... | Use | Not | Why |
|-------------|-----|-----|-----|
| "Does this name exist?" | `query` | `symbols` | query checks registry + status, symbols only lists matches |
| "Who calls this function?" | `trace --direction up` | `symbols` | trace follows call graph, symbols only searches names |
| "Quick info about a symbol" | `context` | `trace` | context gives 1-level callers/callees + code, trace goes deep |
| "Full call chain depth" | `trace` | `context` | trace follows multi-level call graph, context is 1-level |
| "Find text/pattern in code" | `search` | `symbols` | search is regex on source code, symbols queries the registry |
| "Check code quality broadly" | `smell` | `complexity` | smell detects 10 categories, complexity is one specific metric |
| "Measure how complex this is" | `complexity` | `smell` | complexity gives cyclomatic/cognitive scores, smell is qualitative |
| "Pre-delete check" | `impact --action delete` | `dead-code` | impact shows who BREAKS, dead-code shows what's UNUSED |
| "Find unused code" | `dead-code` | `impact` | dead-code finds unreachable/unused items, impact traces breakage |
| "Pre-rename check" | `refactor-safe` | `impact` | refactor-safe checks rename/move safety specifically |
| "Project overview for AI" | `summary` | `handbook` | summary = prioritized findings, handbook = project identity/conventions |
| "Project identity & conventions" | `handbook` | `summary` | handbook = frameworks/conventions/structure, summary = quality findings |
| "Security audit" | `secrets` first | `vuln-scan` | secrets scans YOUR code, vuln-scan scans DEPENDENCIES |
| "Dependency vulnerabilities" | `vuln-scan` | `secrets` | vuln-scan checks CVE databases, secrets finds hardcoded keys |
| "CSS issues" | `css-deep` | `missing-refs` | css-deep is comprehensive CSS analysis, missing-refs is CSS/HTML mismatch only |
| "Where does this app start?" | `entrypoints` | `api-map` | entrypoints finds ALL entry types, api-map focuses on HTTP routes |
| "Map API routes" | `api-map` | `entrypoints` | api-map maps REST/GraphQL/gRPC, entrypoints is broader |
| "Environment variables audit" | `env-check` | `secrets` | env-check tracks usage/missing, secrets finds hardcoded values |
| "Detect frameworks" | `detect` | `handbook` | detect = quick framework list, handbook = full project orientation |
| "Don't know which command" | `ask "question"` | (any specific) | ask routes natural language to the right command |

---

## All 45 Commands — Grouped by Category (Output Schemas Validated)

### Setup & Registry

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 1 | `init` | `$CLI init [ws]` | `{status, workspace, codelens_dir, config}` | `workspace-not-found` |
| 2 | `scan` | `$CLI scan [ws] [--incremental]` | `{status, scanned_files, frontend{classes,ids}, backend{nodes,edges}, incremental}` | `workspace-not-found` |
| 3 | `validate` | `$CLI validate [ws]` | `{status, total_issues, issues{missing_files[], unregistered_files[]}}` | returns empty if no registry |

### Pre-Write Checks (MOST IMPORTANT)

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 4 | `query` | `$CLI query "name" [ws] [--domain {frontend,backend}] [--fuzzy]` | `{found, type, status, domain, action, action_reason, node{id,fn,status,file,line}, callers[], callees[]}` | returns `found:false` if not in registry |
| 5 | `impact` | `$CLI impact "name" [ws] [--action {modify,delete}]` | `{risk, affected{direct[],indirect[],files[],tests[]}, risk_level, recommended_action, recommendations[], fuzzy_match}` | returns `risk:low` if symbol not found |
| 6 | `refactor-safe` | `$CLI refactor-safe "name" [ws] [--action {rename,move}] [--new-name X]` | `{safety, risks{doc_refs[],string_refs[],dynamic_refs[]}}` | returns result for any name |

### Navigation & Understanding

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 7 | `summary` | `$CLI summary [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full,auto}]` | `{identity, registry_stats, findings[{category,total,by_severity,top_items}]}` | empty findings if no registry |
| 8 | `context` | `$CLI context "name" [ws] [--domain {frontend,backend,auto}]` | `{found, context{definition{type,name,status,ref_count,file,line}, nearby_symbols[], quality}}` | `found:false, context:null` if not found |
| 9 | `trace` | `$CLI trace "name" [ws] [--direction {up,down,both}] [--depth N]` | `{chains{up[],down[]}, tree{name,children[]}}` | empty chains if not found |
| 10 | `search` | `$CLI search "pattern" [ws]` | `{matches[{file,line,match,start_col,end_col}]}` | empty matches if no registry |
| 11 | `symbols` | `$CLI symbols "name" [ws] [--domain {frontend,backend,all}] [--fuzzy]` | `{results[{name,type,status,ref_count,file,line,domain}], stats{total_matches,truncated}}` | empty results if no registry |
| 12 | `outline` | `$CLI outline [ws] [--file path] [--detail {minimal,normal,full}]` | `{file, language, line_count, outline{imports[],functions[],classes[]}}` | `status:"error", message:"File not found"` |
| 13 | `dependents` | `$CLI dependents "file" [ws] [--direction {dependents,dependencies,graph}]` | `{direct_dependents[], transitive_dependents[], stats}` | empty lists if file not found |
| 14 | `list` | `$CLI list [ws] [--filter ...] [--domain {frontend,backend,all}]` | `{entries[], total, count, has_more, summary{by_type,by_status}}` | empty if no registry |
| 15 | `ask` | `$CLI ask "question" [ws]` | Routes to appropriate engine - output varies by routed command | returns stats + results from routed engine |

### Entry Points & Architecture

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 16 | `entrypoints` | `$CLI entrypoints [ws] [--type ...] [--exclude-tests]` | `{stats{total_entrypoints,by_type}, entrypoints[{type,file,line,name}]}` | empty if no registry |
| 17 | `api-map` | `$CLI api-map [ws] [--method ...] [--path filter] [--production-only]` | `{frameworks_detected[], stats{total_routes,production_routes,by_method}, routes[{method,path,handler,file,line}]}` | empty if no registry |
| 18 | `state-map` | `$CLI state-map [ws] [--store name]` | `{stats{total_stores,total_slices,by_type}, stores[{name,type,actions[],files[]}]}` | empty if no registry |
| 19 | `detect` | `$CLI detect [ws]` | `{frameworks[], has_react, has_vue, has_nextjs, ...}` | all `false` if no frameworks |
| 20 | `handbook` | `$CLI handbook [ws]` | `{identity, structure, health, conventions, risks, quick_reference}` | writes `.codelens/AGENT.md` |
| 21 | `diff` | `$CLI diff [ws] [--snapshot1 ID] [--snapshot2 ID] [--list-snapshots]` | `{snapshots[{id,created_at}]} or {added[],removed[],modified[]}` | `snapshots:[]` if no scans yet |

### Security

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 22 | `secrets` | `$CLI secrets [ws] [--severity ...]` | `{stats{total_secrets,by_category,by_severity}, risk, findings[{type,file,line,match,severity}]}` | empty findings if no registry |
| 23 | `dataflow` | `$CLI dataflow [ws] [--source ...] [--sink ...]` | `{stats{sources_found,sinks_found,violations,production_violations}, risk, violations[]}` | `timed_out:true` if budget exceeded |
| 24 | `vuln-scan` | `$CLI vuln-scan [ws] [--severity ...]` | `{stats{total_vulnerabilities,by_severity,by_ecosystem}, risk, findings[{cve,package,severity,fix_version}]}` | empty if no lockfile |
| 25 | `env-check` | `$CLI env-check [ws] [--var NAME]` | `{stats{total_vars,required,optional,undocumented}, variables[{name,required,used_in[],defined_in}]}` | empty if no registry |

### Code Quality

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 26 | `smell` | `$CLI smell [ws] [--categories ...] [--severity ...]` | `{health_score, total_findings, stats{by_category,by_severity}, findings[]}` | empty if no registry |
| 27 | `complexity` | `$CLI complexity [ws] [--name FN] [--file PATH] [--threshold N] [--sort ...]` | `{stats{total_functions,avg_cyclomatic,avg_cognitive,high_complexity}, functions[{name,complexity,cognitive,loc}]}` | empty if no registry |
| 28 | `dead-code` | `$CLI dead-code [ws] [--categories ...]` | `{stats{total_dead_code,by_category,by_source}, findings[{category,file,line,item}]}` | `truncated:true` if max-results hit |
| 29 | `debug-leak` | `$CLI debug-leak [ws] [--category ...]` | `{stats{total_leaks,by_category}, findings[{category,file,line,snippet}]}` | empty if no registry |
| 30 | `circular` | `$CLI circular [ws] [--domain {backend,imports,css,all}]` | `{total_cycles, cycles{function_calls[],import_cycles[],css_cycles[]}}` | empty if no registry |
| 31 | `missing-refs` | `$CLI missing-refs [ws]` | `{total_issues, issues{css_no_html[],html_no_css[],possible_typos[]}, truncated_counts}` | empty if no registry |
| 32 | `side-effect` | `$CLI side-effect [ws] [--name FN] [--file PATH]` | `{analyses[{name,file,line,classification,side_effects[],effect_count}], count}` | empty if no registry |
| 33 | `perf-hint` | `$CLI perf-hint [ws] [--severity ...] [--category ...]` | `{stats{total_hints,by_category,by_severity}, hints[{category,severity,file,description}]}` | empty if no registry |

### Refactoring & Safety

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 34 | `test-map` | `$CLI test-map [ws] [--function FN] [--file PATH]` | `{stats{total_functions,tested_functions,coverage_percent}, coverage_map{file:{tested[],untested[]}}}` | empty if no registry |
| 35 | `stack-trace` | `$CLI stack-trace "name" [ws] [--error-type TYPE] [--depth N]` | `{chains[{origin{fn,file,line}, chain[]}]}` | empty chains if not found |
| 36 | `config-drift` | `$CLI config-drift [ws]` | `{project_type, declared_dependencies, actual_imports_summary, drift{unused_deps[],missing_deps[]}}` | empty if no lockfile |

### Frontend-Specific

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 37 | `css-deep` | `$CLI css-deep [ws] [--severity ...] [--category ...]` | `{stats{total_issues,by_category,by_severity}, issues[{category,severity,file,detail}]}` | empty if no CSS |
| 38 | `a11y` | `$CLI a11y [ws]` | `{stats{total_issues,by_category,by_severity}, issues[], wcag_mapping{}, recommendations[]}` | `0 issues, 0 files_scanned` if no HTML |

### Advanced & Specialized

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 39 | `analyze` | `$CLI analyze [ws] [--focus ...] [--detail ...] [--skip-scan]` | `{identity, frameworks, languages, architecture, security, quality, risk_score, action_plan[]}` | `timeout` on very large repos |
| 40 | `type-infer` | `$CLI type-infer [ws] [--file PATH] [--function FN]` | `{stats{variables_typed,functions_typed,high_confidence}, type_map{file:{var:{type,confidence}}}}` | empty if no registry |
| 41 | `ownership` | `$CLI ownership [ws] [--file PATH] [--function FN]` | `{ownership[{author,lines,percentage,first_commit,last_commit}]}` | `status:"no_git"` fallback to mtime |
| 42 | `regex-audit` | `$CLI regex-audit [ws] [--severity ...]` | `{stats{total_patterns,vulnerable,by_category}, findings[]}` | `truncated:true` on large repos |
| 43 | `binary-scan` | `$CLI binary-scan [ws]` | `{stats{files_scanned,total_artifacts,total_size_bytes,by_category}, findings[]}` | `0 artifacts` for pure source repos |
| 44 | `artifact-scan` | `$CLI artifact-scan [ws] [--deep]` | `{stats{total_artifacts,binaries,minified_files,source_maps,wasm_modules,built_output_dirs}}` | `0 artifacts` for pure source repos |

### Utility

| # | Command | Syntax | Output (validated) | Errors |
|---|---------|--------|--------|--------|
| 45 | `watch` | `$CLI watch [ws] [--debounce SECS]` | Streaming: file change events | runs continuously until interrupted |

---

## CLI Usage Pattern

```bash
CODELENS_DIR="{project_path}"
CLI="python3 $CODELENS_DIR/scripts/codelens.py"

# Workspace is AUTO-DETECTED if omitted
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

# Agent-first commands
$CLI handbook              # One-shot project orientation
$CLI ask "dead code?"      # Natural language query
$CLI context "fn" -f markdown  # Markdown output
```
