# CodeLens v8.1.0 — Quick Reference

**MUST activate before writing/editing/deleting any class, id, or function.**

> Read THIS FILE FIRST. All commands: auto-detect workspace, auto-setup, smart `--top 20`, `--lite`, `--max-tokens N`, `--format ai`.

## Zero-Config Usage

```bash
CLI="python3 /path/to/codelens/scripts/codelens.py"
export CODELENS_AI_MODE=1           # Optional: --format ai becomes default
$CLI query "myFunction" --lite   # → {found, action}. Auto-init+scan if needed.
$CLI smell                       # → Auto --top 20, sorted by severity
$CLI complexity --top 5 --lite   # → Top 5 most complex, minimal output
```

**Auto-setup** caps at 3000 files to prevent timeout. For full analysis: `$CLI scan` manually.

## AI Flags (work with ANY command)

| Flag | Effect |
|------|--------|
| `--top N` | Limit list to N items (sorts by relevance: severity/complexity). Smart default: 20. Override: `--top 0` unlimited |
| `--lite` | Command-specific minimal output (see table below) |
| `--max-tokens N` | Auto-truncate to fit ~N tokens |
| `--format ai` | Normalized: `{stats, items[], truncated, recommendations}` |
| `--deep` | Enable LSP-enhanced deep analysis (requires language server; check with `lsp-status`) |
| `--format sarif` | SARIF v2.1.0 output for GitHub Advanced Security / VS Code |
| `--db-path PATH` | Custom SQLite database path (default: `.codelens/codelens.db`) |

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
| `a11y` / `css-deep` / `regex-audit` / `vuln-scan` | `{risk, stats, top_items[], recommendations[]}` |
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
| "taint analysis" | `taint` (AST) or `dataflow` (cross-file) |
| "what to refactor?" | `smell` |
| "too complex?" | `complexity` |
| "performance?" | `perf-hint` → `circular` |
| "cleanup before deploy" | `debug-leak` → `dead-code` → `secrets` |
| "CSS issues?" | `css-deep` → `missing-refs` |
| "accessible?" | `a11y` |
| "project overview" | `summary` or `handbook` |
| "fix automatically" | `fix --apply` (dry-run by default) |
| "show dashboard" | `dashboard` |
| "trend over time" | `history` |
| "run everything" | `analyze` |
| "CI/CD gate" | `check --severity high` |
| "manage plugins" | `plugin list` / `plugin install` |
| "MCP server" | `serve` |
| "pre/post-write hook" | `guard --pre` / `guard --post` |
| "don't know which command" | `ask "question"` |

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

## All 56 Commands

### Setup & Lifecycle (8+)
`init` · `scan [--incremental] [--max-files N] [--full]` · `validate` · `detect` · `watch [--debounce SECS] [--git-mode] [--interval SECS]` · `git-status` · `migrate` · `serve` · `lsp-status`

### Pre-Write Safety (5)
`query "name" [--domain ...] [--fuzzy]` · `impact "name" [--action modify|delete]` · `refactor-safe "name" [--action rename|move]` · `guard (--pre|--post) --file PATH` · `check [--severity ...] [--max-findings N]`

### Navigation (10)
`summary [--focus security|quality|architecture|all] [--detail minimal|standard|full]` · `context "name"` · `trace "name" [--direction up|down|both]` · `search "pattern"` · `symbols "name" [--fuzzy]` · `outline [--file path]` · `dependents "file"` · `list [--filter ...]` · `ask "question"` · `diff`

### Architecture (8)
`entrypoints` · `api-map` · `state-map` · `detect` · `handbook` · `diff` · `dashboard` · `history`

### Security (5)
`secrets [--severity ...]` · `taint` (AST-based) · `dataflow [--source ...] [--sink ...]` (cross-file) · `vuln-scan` (OSV.dev + native audit) · `env-check [--var NAME]`

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

**Total: 56 commands** (verified via `commands/__init__.py` auto-registration)

## MCP Server (54 Tools)

Start the MCP server for AI agent integration:

```bash
python3 scripts/codelens.py serve
```

Exposes 54 tools as `codelens_<command>` (e.g., `codelens_query`, `codelens_taint`):
- 49 statically-defined tools (full JSON schemas in `mcp_server.py`)
- 5 dynamically-discovered tools (`benchmark`, `dashboard`, `history`, `lsp-status`, `migrate`)
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
