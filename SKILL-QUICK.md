# CodeLens — Quick Reference

**MUST activate before writing/editing/deleting any class, id, or function.**

> Read THIS FILE FIRST. All commands: auto-detect workspace, auto-setup, `--lite`, `--max-tokens N`, `--format ai`, `--format compact`.
>
> **Architecture note:** CodeLens consolidated ~78 legacy commands into **12 umbrella commands**, each with `--check <sub-mode>`. If you remember standalone `query`/`trace`/`dead-code`/`secrets`/`init`/`serve`/`guard` — those no longer exist as top-level commands. See [SKILL.md](SKILL.md#architecture--read-this-first-if-you-know-an-older-codelens) for the full old→new mapping.

## Zero-Config Usage

```bash
export CODELENS_AI_MODE=1                                          # Optional: --format ai becomes default
codelens search "myFunction" . --mode symbol --lite                # → symbol status + ref count
codelens audit . --check smell --lite                              # → health_score, top findings by severity
codelens audit . --check complexity --top 5 --lite                 # → top 5 most complex, minimal output
codelens context . --check trace --name main --direction down --format compact
codelens api-map . --check graph-schema                            # → graph shape: nodes/edges/types in ~50 bytes
codelens search "pattern" . --mode regex --limit 5 --offset 10 --format compact
```

**Auto-setup** caps at 3000 files to prevent timeout. For full analysis: `codelens scan` manually (no cap).

## AI Flags (work with every command)

| Flag | Effect |
|---|---|
| `--top N` | Limit list to N items (sorts by relevance: severity/complexity) |
| `--lite` | Command-specific minimal output (see table below) |
| `--max-tokens N` | Auto-truncate to fit ~N tokens |
| `--format ai` | Normalized: `{stats, items[], truncated, recommendations}` |
| `--format compact` | Single-char keys + abbreviated types, ~50% smaller than `json`. Best for high-volume MCP calls |
| `--format sarif` | SARIF v2.1.0 for GitHub Advanced Security / VS Code |
| `--format graphml` | GraphML 1.0 XML for graph-producing commands (`scan`, `context --check trace`, `impact`, `deps --check circular`). Opens in Gephi/Cytoscape/yEd/Neo4j |
| `--limit N` / `--offset N` | Pagination on list-type results. Default limit=20 |
| `--deep` | LSP-enhanced deep analysis (requires a language server; check with `doctor --check lsp-status`) |
| `--db-path PATH` | Custom SQLite database path (default `.codelens/codelens.db`) |
| `--diff-base REF` | Git ref to diff against — only findings from changed files reported (pre-filter, useful for CI PR checks) |

### Lite Mode Per Command

| Command | `--lite` returns |
|---|---|
| `impact --check impact` / `--check diff` | `{status, risk, action}` |
| `audit --check smell` | `{status, health_score, total_findings, action, top_findings[], stats}` |
| `audit --check complexity` | `{status, stats, top_complex[], high_complexity_count}` |
| `audit --check dead-code` | `{status, removal_safety, recommended_action, stats, top_items[], total_dead}` |
| `security --check secrets` | `{status, risk, action, stats, top_findings[]}` |
| `security --check taint` | `{status, risk, stats, top_findings[], recommendations}` |
| `security --check vuln-scan` | `{status, risk, stats, findings[], recommendations}` |
| `summary` | `{status, workspace, identity, frameworks, recommendations, findings[]}` — each finding's items capped to 3 |
| `history` | `{status, workspace, snapshots, latest{...}, trends, deltas}` |
| Other | generic fallback: `{status, stats, top 5 items, recommendations}` |

## Search Decision Rules

| `search --mode symbol` result | Action |
|---|---|
| not found | CREATE — safe to write new |
| found + `active` | EXTEND — don't overwrite |
| found + `dead` | ASK user — reuse or delete? (cross-check with `trace` first) |
| found + `duplicate_ref` | LIST_FIRST — show all referrers |
| found + `collision` | STOP — active bug, fix first |

## Trigger Map

| Intent | Command |
|---|---|
| Create/edit/delete code | `search --mode symbol` → write → `scan --incremental` |
| "what changed?" | `impact --check diff` |
| "do I need to re-scan?" | `history --check git-status` |
| "does this exist?" | `search --mode symbol --lite` |
| "who calls this?" | `context --check trace --direction up` |
| "safe to delete?" | `impact --check impact` → `audit --check dead-code` |
| "production ready?" | `audit --check smell` → `audit --check complexity` → `security --check secrets` |
| "security audit" | `security --check secrets` → `impact --check dataflow` → `security --check vuln-scan` |
| "taint analysis" | `security --check taint` (AST, single-file) or `impact --check dataflow` (cross-file) |
| "what to refactor?" | `audit --check smell` |
| "too complex?" | `audit --check complexity` |
| "performance?" | `audit --check perf-hint` → `deps --check circular` |
| "cleanup before deploy" | `audit --check dead-code` → `security --check secrets` |
| "project overview" | `context` (10-second orient, default sub-mode) or `summary --lite` (findings digest) |
| "CI/CD gate" | `check --severity high` |
| "manage plugins" | `plugin list` |
| "structural query in one call" | `search --mode graph` (Cypher subset) or `graph "cypher"` for raw power-user queries |
| "LSP servers available?" | `doctor --check lsp-status` |
| "share graph with teammate" | `deps --check export-snapshot` → they run `deps --check import-snapshot` |

### Disambiguation

| You want | Use | Not |
|---|---|---|
| "Name exists?" | `search --mode symbol` | `search --mode semantic` (fuzzy-by-meaning, not exact) |
| "Who calls X, transitively?" | `context --check trace --direction up` | `context --check context` (single-level) |
| "Quick symbol info" | `context --check context --name X` | `context --check trace` (trace goes multi-level deep) |
| "Find literal text/regex in code" | `search --mode regex` | `search --mode symbol` (symbol is exact-name lookup, not free text) |
| "Quality check" | `audit --check smell` | `audit --check complexity` (smell = multi-category, complexity = one metric) |
| "Pre-delete check" | `impact --check impact` | `audit --check dead-code` (impact shows blast radius; dead-code shows current unused status) |
| "Security in my code" | `security --check secrets` | `security --check vuln-scan` (vuln-scan checks dependency CVEs, not your code) |
| "Dependency CVEs" | `security --check vuln-scan` | `security --check secrets` (secrets finds hardcoded keys) |
| "Auto-fix issues" | not available — CodeLens finds, it doesn't auto-fix | `check` (gates CI, doesn't fix) |

## The 12 Umbrella Commands

| Command | `--check` sub-modes |
|---|---|
| `scan` | scan (default) · rescan |
| `search "pattern" [workspace]` | semantic (default) · symbol · regex · graph — **pattern first, workspace second**, opposite of every command below |
| `context [workspace]` | orient (default) · outline · trace (`--name X --direction up\|down\|both`) · context (`--name X`) · diagnostics (`--file X`, LSP) · overview (symbol map) · tags (doc-tag audit) |
| `deps [workspace]` | affected (`--files ...`) · dependents (`--files ...`) · circular · import-snapshot (`--input path.gz`) · export-snapshot (`--output path.gz`) |
| `audit [workspace]` | dead-code · complexity · smell · staleness · perf-hint · side-effect · css · a11y |
| `security [workspace]` | secrets · vuln-scan · taint · binary-scan · regex-audit |
| `summary [workspace]` | summary (default) · dashboard · arch-metrics · architecture |
| `impact [workspace]` | impact (`--name X`, default) · diff · dataflow |
| `api-map [workspace]` | api-map (default) · graph-schema |
| `doctor [workspace]` | doctor (default) · env-check · lsp-status |
| `history [workspace]` | history (default) · ownership · git-status |
| `graph [workspace] "cypher query"` | — (power-user raw Cypher) |

Plus two commands hidden from `--help` but callable directly, pending final placement (issue #200): `check [workspace] --severity ... --max-findings N` (CI/CD quality gate), `plugin list` (plugin management).

**Total: 12 commands** (auto-registered via `commands/__init__.py`; rerun `python3 scripts/sync_command_count.py --apply` after adding/removing a command)

## MCP Server (12 Tools)

MCP tools are invoked by an MCP-aware client (Claude Desktop, Cursor, VS Code Copilot, Continue.dev, Cline) — there is no standalone `codelens serve` command to run yourself. Point your MCP client config at `scripts/mcp_server.py`; see [mcp_config.json](mcp_config.json) for ready-made templates.

- **12 tools total** — one `codelens_<command>` per umbrella command (e.g. `codelens_search`, `codelens_audit`, `codelens_security`), auto-discovered from `COMMAND_REGISTRY` (6 statically-defined with full JSON schemas + 6 dynamically-discovered)
- Every tool accepts a `format` parameter (`json`/`markdown`/`ai`/`sarif`/`compact`/`graphml`) — use `format: "compact"` for token-efficient responses
- Long-running commands (`watch`) are excluded from MCP exposure

## Error Handling

All errors return `{status:"error", error, error_type}` (some also include a `suggestion` field). Common patterns:

| Condition | Recovery |
|---|---|
| No `.codelens/` registry | Auto-scans (zero-config) — no separate init step needed |
| Tree-sitter missing | Regex fallback kicks in automatically (run `setup.sh` for full AST accuracy) |
| Any `status:"error"` | Follow the `error`/`suggestion` field in the response |
| Workspace invalid | Auto-detect from cwd/parent dirs |
| `search "X" "Y"` returns empty `"ok"` result unexpectedly | Check argument order — `search` is pattern-first, everything else is workspace-first |
| `--lite` output looks emptier than expected | Command may be hitting the generic fallback reducer, not a dedicated one — see Lite Mode table above |

## First-Time Setup

```bash
pip install codelens
codelens scan /path/to/project        # Builds registry (~5-15s for <500 files); no separate init step
codelens search "main" /path/to/project --mode symbol   # Verify: returns a valid JSON result
# After code changes:
codelens scan /path/to/project --incremental    # ~1-5s
```
