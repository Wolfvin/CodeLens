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

## Onboarding — Step-by-Step for First-Time AI Users

**What you need:** A codebase directory with source files. CodeLens auto-detects most project types.

```bash
# Step 1: Set CLI path (use your skill's installed location)
CLI="python3 /path/to/codelens/scripts/codelens.py"

# Step 2: Initialize — creates .codelens/ directory with config
$CLI init /path/to/project
# → Returns {status:"ok", workspace, codelens_dir, config{...}}
# If workspace arg is invalid, auto-detects from cwd/parent dirs

# Step 3: Scan — builds the registry (REQUIRED)
$CLI scan /path/to/project
# → Returns {status:"ok", files_scanned{...}, frontend{...}, backend{...}}
# Takes ~5-15s for <500 files, ~30-120s for 1K-5K files
# If timeout: use --max-files 3000 to limit scope

# Step 4: Verify with query
$CLI query "main" /path/to/project
# → Returns {status:"ok", found:true|false, action:CREATE|EXTEND|ASK|STOP}

# Step 5: If scan was already done before, just refresh:
$CLI scan /path/to/project --incremental   # ~1-5s
```

**Common first-time issues:**
- `WARNING: TSBackendParser init failed` → tree-sitter not installed, falls back to regex. Run `setup.sh`.
- `Auto-detected workspace: ...` → workspace arg was invalid, auto-detect kicked in. Normal.
- Empty results after scan → workspace has no recognized source files, or paths are ignored.

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
| "CSS/style/layout" | `css-deep` → `missing-refs` → `list --filter dead` |
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

## All 45 Commands — Grouped by Category

> **Schema convention**: All commands return `status: "ok"` on success. Top-level fields `status`, `workspace` are always present. Only **key fields for AI parsing** are listed below — many commands return additional metadata fields.

### Setup & Registry

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 1 | `init` | `$CLI init [ws]` | `status, workspace, codelens_dir, config{frontend_paths[],backend_paths[],ignore[],frameworks[],is_monorepo,lockfile,has_rust_backend}` | Invalid dir → auto-detect from cwd. Never errors. |
| 2 | `scan` | `$CLI scan [ws] [--incremental] [--max-files N]` | `status, workspace, files_scanned{html,css,js_frontend,js_backend,tsx,rust,python,vue,...}, frontend{classes,ids}, backend{nodes,edges}` | Tree-sitter missing → regex fallback (logged). Unreadable files → skipped. |
| 3 | `validate` | `$CLI validate [ws]` | `status, workspace, total_issues, issues{missing_files[],unregistered_files[{file,ext,message}],stale_references[{type,name,file,line,message}],orphan_entries[]}` | No registry → still runs, returns 0 issues |

### Pre-Write Checks (MOST IMPORTANT)

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 4 | `query` | `$CLI query "name" [ws] [--domain {frontend,backend}] [--fuzzy]` | **found=true**: `found, type, domain, status, action, action_reason, node{id,fn,ref_count,status,file,line,async,impl_for,superclasses}, callers[], callees[], pagination{callers_total,callees_total,has_more_callers,has_more_callees}`. **found=false**: `found:false, query, domain, action:"CREATE", action_reason` | Never errors. No registry → returns found:false. |
| 5 | `impact` | `$CLI impact "name" [ws] [--action {modify,delete}]` | `status, symbol, workspace, action, risk{low,medium,high,critical}, affected{direct[{type,name,file,line,relation,domain}],indirect[],files[],tests[]}, recommendations[]` | Symbol not found → `risk:"low"`, empty affected. |
| 6 | `refactor-safe` | `$CLI refactor-safe "name" [ws] [--action {rename,move}] [--new-name X]` | `status, symbol, workspace, action, new_name, safety{safe,mostly_safe,risky,dangerous}, risks{doc_refs[],string_refs[{file,line,string,risk,message}],dynamic_refs[]}` | Always returns result for any name. |

### Navigation & Understanding

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 7 | `summary` | `$CLI summary [ws] [--focus {security,quality,architecture,all}] [--detail {minimal,standard,full,auto}]` | `status, workspace, focus, detail, identity{name,type,version}, registry_stats{backend_nodes,backend_edges,frontend_classes,frontend_ids,dead_nodes,active_nodes}, findings[{category,total,by_severity,top_items}]` | No registry → empty findings. Budget exceeded → `timed_out_engines[]`. |
| 8 | `context` | `$CLI context "name" [ws] [--domain {frontend,backend,auto}]` | **found=true**: `found, context{symbol,workspace,definition{type,name,status,ref_count,file,line,async,impl_for,superclasses,match_type},nearby_symbols[{fn,line,status}],quality{...}}`. **found=false**: `found:false, context:null` | Not found → found:false. Large codebase (>10K nodes) → quality enrichment skipped. |
| 9 | `trace` | `$CLI trace "name" [ws] [--direction {up,down,both}] [--depth N]` | `status, symbol, workspace, direction, max_depth, chains{up[{depth,direction,node_id,fn,file,line,path}],down[]}, tree{name,type,callers[],callees[],file,line,status}, stats{callers_found,callees_found,affected_files}` | Symbol not found → empty chains, tree with no children. |
| 10 | `search` | `$CLI search "pattern" [ws]` | `status, pattern, workspace, matches[{file,line,match,start_col,end_col}]` | No registry → empty matches. |
| 11 | `symbols` | `$CLI symbols "name" [ws] [--domain {frontend,backend,all}] [--fuzzy]` | `status, query, domain, fuzzy, stats{total_matches,shown,truncated,frontend_matches,backend_matches}, results[{domain,type,name,status,ref_count,location,async,impl_for,component,superclasses}]` | No registry → empty results. Truncated → stats.truncated:true. |
| 12 | `outline` | `$CLI outline [ws] [--file path] [--detail {minimal,normal,full}]` | `status, file, language, line_count, outline{imports[{text,line}],functions[{name,line}],classes[{name,line}]}` | File not found → `status:"error", message:"..."`. |
| 13 | `dependents` | `$CLI dependents "file" [ws] [--direction {dependents,dependencies,graph}]` | `status, file, workspace, suggestion, direct_dependents[], transitive_dependents[], stats{...}` | No file arg → `status:"error"`. File not found → empty lists. |
| 14 | `list` | `$CLI list [ws] [--filter ...] [--domain {frontend,backend,all}]` | `status, domain, filter, total, count, offset, limit, has_more, summary{by_type{},by_status{}}, results[{type,name,ref_count,status,defined_in}]` | No registry → empty results. |
| 15 | `ask` | `$CLI ask "question" [ws]` | `status, stats{...}, results{...}` (varies by routed command) | Timeout (45s) → `status:"timeout"`. Unknown command → `status:"error"`. |

### Entry Points & Architecture

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 16 | `entrypoints` | `$CLI entrypoints [ws] [--type ...] [--exclude-tests]` | `status, workspace, stats{total_entrypoints,by_type{main,http_handler,cli_command,event_handler,cron_job,worker,module_export,test_entry}}, entrypoints[{type,file,line,label,path,method,handler}]` | No registry → empty entrypoints. |
| 17 | `api-map` | `$CLI api-map [ws] [--method ...] [--path filter] [--production-only]` | `status, workspace, frameworks_detected[], stats{total_routes,production_routes,test_routes,by_method{},auth_protected,public,files_scanned}, routes[{method,path,handler_name,file,line,middleware_chain[]}]` | No registry → empty routes. |
| 18 | `state-map` | `$CLI state-map [ws] [--store name]` | `status, workspace, stats{total_stores,total_slices,by_type{},files_scanned,frameworks_detected,truncated}, stores[{name,type,actions[],files[]}], state_flow[], recommendations[]` | No registry → empty stores. |
| 19 | `detect` | `$CLI detect [ws]` | `status, frameworks[], has_react, has_vue, has_nextjs, has_angular, has_fastapi, has_flask, has_django, has_rust, has_rust_backend, is_monorepo, monorepo_tools[], lockfile, css_preprocessor, module_system, unsupported_langs[]` | Always returns — all `false` if no frameworks. |
| 20 | `handbook` | `$CLI handbook [ws]` | `status, meta{workspace,generated_at,codelens_version}, identity{name,version,type,languages,frameworks,is_monorepo}, structure{directory_map,entrypoints}, health{...}, conventions{...}, risks{...}, quick_reference{...}` | Partial results → `partial:true, time_budget_used, time_budget_total`. Writes `.codelens/AGENT.md`. |
| 21 | `diff` | `$CLI diff [ws] [--snapshot1 ID] [--snapshot2 ID] [--list-snapshots]` | `status, workspace, last_snapshot, summary{added,removed,changed,new_collisions,new_dead,resolved_dead}, frontend{added_classes[],removed_classes[],...}, backend{added_nodes[],removed_nodes[],...}` | No snapshots → `snapshots:[]`. |

### Security

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 22 | `secrets` | `$CLI secrets [ws] [--severity ...]` | `status, workspace, stats{total_secrets,by_category{password,api_key,token,secret_key,connection_string},by_severity{},env_files_checked}, risk, findings[{type,file,line,match,value,line_content,severity,category}]` | No registry → empty findings. |
| 23 | `dataflow` | `$CLI dataflow [ws] [--source ...] [--sink ...] [--timeout SECS]` | `status, workspace, stats{sources_found,sinks_found,sanitizers_found,violations,test_violations,production_violations,safe_paths,untraced_sources,files_scanned,timed_out}, risk, violations[{source{source_type,label,file,line,match,severity},sink{sink_type,label,file,line,match,severity},flow_chain[]}]` | `stats.timed_out:true` if budget exceeded. |
| 24 | `vuln-scan` | `$CLI vuln-scan [ws] [--severity ...]` | `status, workspace, stats{total_vulnerabilities,by_severity{},by_ecosystem{},files_scanned[]}, risk, findings[{cve,package,severity,fix_version}], audit_available, recommendations[]` | No lockfile → empty findings, `audit_available:false`. |
| 25 | `env-check` | `$CLI env-check [ws] [--var NAME]` | `status, workspace, stats{total_vars,required,optional,undocumented,in_env_file,files_scanned}, variables[{name,referenced_in[{file,line,context,is_compile_time}],has_fallback,is_required,defined_in_env_file[],is_in_gitignore,documentation,is_secret}]` | No registry → empty variables. |

### Code Quality

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 26 | `smell` | `$CLI smell [ws] [--categories ...] [--severity ...]` | `status, workspace, health_score, total_findings, stats{files_scanned,total_smells,critical,warning,info,by_category{},by_severity{},health_score}, by_category{category_name:[{file,line,...,severity,message}]}, files_truncated` | No registry → empty findings. |
| 27 | `complexity` | `$CLI complexity [ws] [--name FN] [--file PATH] [--threshold N] [--sort ...]` | `status, workspace, stats{total_functions,files_scanned,avg_cyclomatic,avg_cognitive,high_complexity,by_complexity_level{simple,moderate,complex,very_complex,untamable}}, functions[{name,file,line,cyclomatic,cognitive,loc,params,max_nesting,complexity_level,refactoring_suggestion}]` | No registry → empty functions. |
| 28 | `dead-code` | `$CLI dead-code [ws] [--categories ...]` | `status, workspace, stats{files_scanned,total_dead_code,by_category{},by_source{core,test,config},truncated}, results{unreachable[{file,line,after,after_line,severity,message,suggestion,source}],unused_vars[],unused_exports[],registry_dead[]}` | `stats.truncated:true` if max-results hit. |
| 29 | `debug-leak` | `$CLI debug-leak [ws] [--category ...]` | `status, workspace, stats{total_leaks,files_scanned,by_category{console_log,print_statement,debugger,todo_fixme,commented_code,test_skip,mock_data,dev_only},by_severity{},truncated}, leaks[{category,file,line,pattern,message}]` | No registry → empty leaks. |
| 30 | `circular` | `$CLI circular [ws] [--domain {backend,imports,css,all}]` | `status, workspace, domain, total_cycles, cycles{function_calls[{type,chain[{id,fn,file,line}]}],import_cycles[],css_cycles[]}` | No registry → 0 cycles. |
| 31 | `missing-refs` | `$CLI missing-refs [ws]` | `status, workspace, total_issues, issues{css_no_html[],html_no_css[],css_id_no_html[],js_id_no_html[],possible_typos[]}, findings[], truncated_counts{}, stats{...}` | No registry → 0 issues. |
| 32 | `side-effect` | `$CLI side-effect [ws] [--name FN] [--file PATH]` | `status, workspace, stats{total_functions,pure,impure,purity_ratio,effect_summary{io,external,network,state,dom,...},files_scanned,truncated,elapsed_sec}, functions[{name,file,line,classification,side_effects[],effect_count,is_async}]` | No registry → empty functions. |
| 33 | `perf-hint` | `$CLI perf-hint [ws] [--severity ...] [--category ...]` | `status, workspace, stats{total_hints,by_category{n_plus_one,sync_blocking,memory_leak,...},by_severity{},files_scanned,truncated,by_source{},truncated_categories}, risk, hints[{...}]` | No registry → 0 hints. |

### Refactoring & Safety

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 34 | `test-map` | `$CLI test-map [ws] [--function FN] [--file PATH]` | `status, workspace, stats{total_source_files,total_test_files,total_functions,tested_functions,untested_functions,coverage_percent,files_without_tests}, coverage_map{file:{fn:{tested,test_files[],confidence}}}` | No registry → 0% coverage. |
| 35 | `stack-trace` | `$CLI stack-trace "name" [ws] [--error-type TYPE] [--depth N]` | `status, function, workspace, error_type, chains[{origin{fn,file,line},chain[{depth,node_id,fn,file,line,is_origin}],chain_length}], propagation[{origin_fn,origin_file,handling}]` | Symbol not found → empty chains. |
| 36 | `config-drift` | `$CLI config-drift [ws]` | `status, workspace, project_type, declared_dependencies{dependencies{},dev_dependencies{},peer_dependencies{}}, actual_imports_summary{total_unique_imports,by_type{external,relative,phantom,local_packages}}, drift{missing[{package,severity,message,suggestion}],...}` | No lockfile → limited results. |

### Frontend-Specific

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 37 | `css-deep` | `$CLI css-deep [ws] [--severity ...] [--category ...]` | `status, workspace, stats{total_issues,by_category{},by_severity{},css_files_scanned,html_js_files_scanned}, findings[{type,category,severity,file,line,detail,name,fix_suggestion}], recommendations[]` | No CSS → empty findings. |
| 38 | `a11y` | `$CLI a11y [ws]` | `status, workspace, stats{total_issues,files_scanned,by_category{},by_severity{},truncated}, issues[], wcag_mapping{}, recommendations[]` | No HTML → `0 issues, 0 files_scanned`. |

### Advanced & Specialized

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 39 | `analyze` | `$CLI analyze [ws] [--focus ...] [--detail ...] [--skip-scan] [--timeout SECS]` | `status, workspace, focus, detail, codelens_version, time_budget_seconds, scan{...}, identity{...}, frameworks[], languages[], architecture{...}, security{...}, quality{...}, risk_score, action_plan[]` | Engine timeout → `skipped:true, skip_reason`. Budget skip → per-engine. |
| 40 | `type-infer` | `$CLI type-infer [ws] [--file PATH] [--function FN]` | `status, workspace, stats{files_analyzed,variables_typed,functions_typed,high_confidence}, type_map{file:{var:{type,confidence,kind,line,source}}}` | No registry → empty type_map. |
| 41 | `ownership` | `$CLI ownership [ws] [--file PATH] [--function FN]` | `status, workspace, ownership_summary[{author,commits,lines_owned,files_owned}], file_ownerships{file:author}` | No git → `status:"ok"` with mtime-based fallback. |
| 42 | `regex-audit` | `$CLI regex-audit [ws] [--severity ...]` | `status, workspace, stats{total_patterns,files_scanned,truncated,vulnerable,by_category{unsafe_constructor,overly_broad,redos_vulnerable,incorrect_escaping,performance},by_severity{}}, findings[{category,file,line,pattern,issue,severity,fix_suggestion}]` | `truncated:true` on large repos. |
| 43 | `binary-scan` | `$CLI binary-scan [ws]` | `status, workspace, stats{files_scanned,total_artifacts,total_size_bytes,by_category{}}, findings[], recommendations[]` | `0 artifacts` for pure source repos. |
| 44 | `artifact-scan` | `$CLI artifact-scan [ws] [--deep]` | `status, workspace, reverse_engineering_mode, deep_scan, stats{total_artifacts,binaries,minified_files,source_maps,wasm_modules,built_output_dirs}, built_dirs[], binaries[], minified_files[], source_maps[], wasm_modules[], recommendations[]` | `0 artifacts` for pure source repos. |

### Utility

| # | Command | Syntax | Key Output Fields | Error Behavior |
|---|---------|--------|-------------------|----------------|
| 45 | `watch` | `$CLI watch [ws] [--debounce SECS]` | Streaming output to stdout. Not JSON. | Ctrl+C to stop. watchdog not installed → polling fallback. |

---

## Global Error Handling (All Commands)

All commands share a top-level error handler in `codelens.py`. When an unhandled exception occurs:

```json
{
  "status": "error",
  "error_type": "FileNotFoundError|ImportError|...",
  "error": "human-readable message",
  "suggestion": "command-specific fix suggestion"
}
```

**Specific error patterns:**

| Condition | What happens | How to recover |
|-----------|-------------|----------------|
| Workspace dir invalid | Auto-detect kicks in | Check output `workspace` field |
| No `.codelens/` registry | Commands still run, return empty/default results | Run `init` then `scan` |
| Tree-sitter not installed | Regex fallback (logged as WARNING) | Run `setup.sh` |
| File not found in `outline` | `status:"error", message:"..."` | Check file path |
| No file arg in `dependents` | `status:"error"` with usage message | Provide file path |
| `ask` timeout (45s SIGALRM) | `status:"timeout"` | Run the specific command directly |
| `analyze` engine timeout | Per-engine `skipped:true` | Run that engine's command directly |
| `summary` budget exceeded | `timed_out_engines[]` | Use `--detail minimal` or specific commands |
| `handbook` budget exceeded | `partial:true` | Run individual commands for skipped sections |
| `dataflow` budget exceeded | `stats.timed_out:true` | Use `--timeout` to increase budget |
| Any unhandled exception | `status:"error"` + suggestion | Follow suggestion or run `init` + `scan` |

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
