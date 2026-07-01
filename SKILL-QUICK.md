# CodeLens — Quick Reference

**MUST activate before writing/editing/deleting any class, id, or function.**

> Read THIS FILE FIRST. All commands: auto-detect workspace, auto-setup, smart `--top 20`, `--lite`, `--max-tokens N`, `--format ai`, `--format compact` (issue #17).

## Zero-Config Usage

```bash
CLI="python3 /path/to/codelens/scripts/codelens.py"
export CODELENS_AI_MODE=1           # Optional: --format ai becomes default
$CLI query "myFunction" --lite                              # → {found, action}
$CLI smell                                                  # → Auto --top 20, sorted by severity
$CLI complexity --top 5 --lite                              # → Top 5 most complex, minimal output
$CLI trace "main" --direction down --format compact         # → token-efficient single-char keys (issue #17)
$CLI graph-schema                                           # → graph shape: nodes/edges/types in ~50 bytes (issue #17)
$CLI list --limit 5 --offset 10 --format compact            # → paginated + compact
```

**Auto-setup** caps at 3000 files to prevent timeout. For full analysis: `$CLI scan` manually.

## AI Flags (work with ANY command)

| Flag | Effect |
|------|--------|
| `--top N` | Limit list to N items (sorts by relevance: severity/complexity). Smart default: 20. Override: `--top 0` unlimited |
| `--lite` | Command-specific minimal output (see table below) |
| `--max-tokens N` | Auto-truncate to fit ~N tokens |
| `--format ai` | Normalized: `{stats, items[], truncated, recommendations}` |
| `--format compact` | Token-efficient: single-char keys + abbreviated types (issue #17). ~50% smaller than `json`. Best for high-volume MCP tool calls |
| `--format sarif` | SARIF v2.1.0 output for GitHub Advanced Security / VS Code |
| `--limit N` / `--offset N` | Pagination on list-type commands (`list`, `search`, `trace`, `symbols`, `outline`). Default limit=20 (issue #17). `--top N` is an alias for `--limit N --offset 0` |
| `--deep` | Enable LSP-enhanced deep analysis (requires language server; check with `lsp-status`) |
| `--db-path PATH` | Custom SQLite database path (default: `.codelens/codelens.db`) |
| `--diff-base REF` | Git ref (branch/tag/SHA/`HEAD~1`) to diff against. Only findings from files changed relative to REF are reported. Empty diff → early exit. Useful for CI PR checks. Works on all analysis commands (issue #157) |

### Lite Mode Per Command

| Command | `--lite` returns |
|---------|------------------|
| `query` | `{status, found, action, action_reason}` |
| `impact` / `refactor-safe` | `{status, risk, action}` |
| `smell` | `{health_score, total_findings, action, top_findings[], stats}` |
| `complexity` | `{stats, top_complex[], high_complexity_count}` |
| `dead-code` | `{removal_safety, recommended_action, stats, top_items[], total_dead}` |
| `debug-leak` | `{stats, top_leaks[], leaks_total}` |
| `perf-hint` | `{risk, stats, top_hints[], hints_total}` |
| `secrets` | `{risk, action, stats, top_findings[]}` |
| `a11y` / `css-deep` / `regex-audit` | `{risk, stats, top_items[], recommendations[]}` |
| `vuln-scan` | `{risk, stats, findings[], osv_stats, cache_info{last_refresh, age_hours, ttl_hours, is_stale, stale_packages[]}, recommendations[]}` — `cache_info.is_stale` tells agents whether to re-run with `--refresh` (issue #30) |
| `taint` | `{status, stats, top_violations[], recommendations[]}` |
| `guard` | `{status, risk, action, blocked_reason?}` |
| `check` | `{status, exit_code, total_findings, critical_count}` |
| Other | `{status, stats, top 5 items, recommendations}` |

## Query Decision Rules

| Result | Action |
|--------|--------|
| `found: false` | CREATE — safe to write new |
| `found: true` + `active` | EXTEND — don't overwrite |
| `found: true` + `dead` | ASK user — reuse or delete? |
| `found: true` + `duplicate_ref` | LIST_FIRST — show all referrers |
| `found: true` + `collision` | STOP — active bug, fix first |

## Trigger Map

| Intent | Command |
|--------|---------|
| Create/edit/delete code | `query` → write → `scan --incremental` |
| "what changed?" | `diff --git-aware` |
| "do I need to re-scan?" | `git-status` |
| "does this exist?" | `query --lite` |
| "who calls this?" | `trace --direction up` |
| "safe to delete?" | `impact` → `dead-code` |
| "safe to rename?" | `refactor-safe` |
| "production ready?" | `smell` → `complexity` → `debug-leak` → `secrets` |
| "security audit" | `secrets` → `dataflow` → `env-check` → `vuln-scan` |
| "are CVE results fresh?" | `vuln-scan` → check `cache_info.is_stale` → if stale, re-run `vuln-scan --refresh` or `vuln-scan --max-age 6h` (issue #30) |
| "taint analysis" | `taint` (AST) or `dataflow` (cross-file) |
| "what to refactor?" | `smell` |
| "too complex?" | `complexity` |
| "performance?" | `perf-hint` → `circular` |
| "cleanup before deploy" | `debug-leak` → `dead-code` → `secrets` |
| "CSS issues?" | `css-deep` → `missing-refs` |
| "accessible?" | `a11y` |
| "project overview" | `architecture --lite` (single call, <1k tokens) or `summary` / `handbook` (deeper) |
| "fix automatically" | `fix --apply` (dry-run by default) |
| "show dashboard" | `dashboard` |
| "trend over time" | `history` |
| "run everything" | `analyze` |
| "CI/CD gate" | `check --severity high` |
| "manage plugins" | `plugin list` / `plugin install` |
| "MCP server" | `serve` |
| "pre/post-write hook" | `guard --pre` / `guard --post` |
| "don't know which command" | `ask "question"` |
| "LSP servers available?" | `lsp-status` (issue #33: `--lsp-status` top-level flag is an alias — both produce the identical payload, and the MCP `codelens_lsp_status` tool uses the same subcommand path) |

### Disambiguation

| You want | Use | Not |
|----------|-----|-----|
| "Name exists?" | `query` | `symbols` (query checks status+action) |
| "Who calls?" | `trace` | `context` (trace goes deep) |
| "Quick symbol info" | `context` | `trace` (context is 1-level) |
| "Find text in code" | `search` | `symbols` (search is regex on files) |
| "Quality check" | `smell` | `complexity` (smell = 10 categories) |
| "Complexity score" | `complexity` | `smell` (complexity = metrics) |
| "Pre-delete check" | `impact` | `dead-code` (impact shows breakage) |
| "Find unused code" | `dead-code` | `impact` (dead-code finds unused) |
| "Security in my code" | `secrets` | `vuln-scan` (vuln-scan checks deps) |
| "Dependency CVEs" | `vuln-scan` | `secrets` (secrets finds hardcoded) |
| "Project identity" | `handbook` | `summary` (summary = findings) |
| "AST taint (precise)" | `taint` | `dataflow` (dataflow is cross-file, regex-aware) |
| "Cross-file taint" | `dataflow` | `taint` (taint is single-file, AST-deep) |
| "Auto-fix issues" | `fix` | `check` (check just gates, doesn't fix) |

## All 69 Commands

### Setup & Lifecycle (8+)
`init` · `scan [--incremental] [--max-files N] [--full]` · `registry-validate` · `detect` · `watch [--debounce SECS] [--git-mode] [--interval SECS]` · `git-status` · `migrate` · `serve` · `lsp-status` (issue #33: `codelens --lsp-status` top-level flag is an alias of `codelens lsp-status` — both delegate to `hybrid_engine.get_lsp_status()` and return the identical payload)

### Pre-Write Safety (5)
`query "name" [--domain ...] [--fuzzy]` · `impact "name" [--action modify|delete]` · `refactor-safe "name" [--action rename|move]` · `guard (--pre|--post) --file PATH` · `check [--severity ...] [--max-findings N]`

### Navigation (11)
`architecture [--lite] [--no-cache]` · `summary [--focus security|quality|architecture|all] [--detail minimal|standard|full]` · `context "name"` · `trace "name" [--direction up|down|both] [--limit N] [--offset N]` · `search "pattern" [--limit N] [--offset N]` · `symbols "name" [--fuzzy] [--limit N] [--offset N]` · `outline [--file path] [--limit N] [--offset N]` · `dependents "file"` · `list [--filter ...] [--limit N] [--offset N]` · `ask "question"` · `diff [--git-aware]`

### Architecture (10)
`entrypoints` · `api-map` · `state-map` · `detect` · `handbook` · `diff [--git-aware]` · `dashboard` · `history` · `graph-schema` · `resolve-types`

### Security (5)
`secrets [--severity ...]` · `taint` (AST-based) · `dataflow [--source ...] [--sink ...]` (cross-file) · `vuln-scan [--offline] [--osv-ttl N] [--refresh] [--max-age Nh]` (OSV.dev + native audit; `--refresh` bypasses cache, `--max-age Nh` overrides per-run TTL, `cache_info` in output signals staleness — issue #30) · `env-check [--var NAME]`

### Quality (9)
`smell [--categories ...] [--severity ...]` · `complexity [--name FN] [--threshold N] [--sort ...]` · `dead-code [--categories ...]` · `debug-leak [--category ...]` · `circular [--domain ...]` · `missing-refs` · `side-effect [--name FN]` · `perf-hint [--severity ...] [--category ...]` · `fix [--apply]`

### Refactoring (3)
`test-map` · `stack-trace "name"` · `config-drift`

### Frontend (2)
`css-deep` · `a11y`

### Advanced & RE (5)
`analyze [--focus ...] [--timeout SECS]` · `type-infer` · `ownership` · `regex-audit` · `binary-scan` · `artifact-scan [--deep]`

### Tooling (1)
`plugin <install|list|search|update|info|validate>`

**Total: 69 commands** (auto-registered via `commands/__init__.py`; rerun `python3 scripts/sync_command_count.py --apply` after adding/removing a command)

## MCP Server (67 Tools)

Start the MCP server for AI agent integration:

```bash
python3 scripts/codelens.py serve
```

Exposes 67 tools as `codelens_<command>` (e.g., `codelens_query`, `codelens_taint`, `codelens_graph_schema`, `codelens_architecture`, `codelens_resolve_types`, `codelens_git_status`):
- 50 statically-defined tools (full JSON schemas in `mcp_server.py`)
- 13 dynamically-discovered tools (auto-discovered from `COMMAND_REGISTRY`; long-running `watch` and `serve` are excluded)
- Every tool accepts a `format` parameter (`json`/`markdown`/`ai`/`sarif`/`compact`). Use `format: "compact"` for token-efficient responses (~50% smaller than `json`).
- `watch` and `serve` itself are excluded (long-running)

See `mcp_config.json` for Claude Desktop, Cursor, VS Code Copilot, Continue.dev, and Cline configuration templates.

## Error Handling

All errors return `{status:"error", error_type, error, suggestion}`. Common patterns:

| Condition | Recovery |
|-----------|----------|
| No `.codelens/` | Auto-init+scan (zero-config) |
| Tree-sitter missing | Regex fallback (run `setup.sh` for AST) |
| `ask` timeout (45s) | Run specific command directly |
| Any `status:"error"` | Follow `suggestion` field |
| Workspace invalid | Auto-detect from cwd/parent dirs |
| `analyze` engine timeout | `skipped:true` per-engine — run that command individually |
| `summary` budget exceeded | `timed_out_engines[]` — use `--detail minimal` or specific commands |
| `handbook` budget exceeded | `partial:true` — run individual commands for skipped sections |
| `guard` blocks write | Follow `blocked_reason` — fix the flagged issue before retrying |

## First-Time Setup (if zero-config fails)

```bash
bash /path/to/codelens/setup.sh    # One-time: install tree-sitter
$CLI init                           # Creates .codelens/ config
$CLI scan                           # Builds registry (~5-15s for <500 files)
$CLI query "main"                   # Verify: returns {found, action}
# After code changes: $CLI scan --incremental (~1-5s)
```
