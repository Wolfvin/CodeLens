---
name: codelens
description: >
  CodeLens — AI-Native Code Intelligence. 78 commands for AI-powered code analysis,
  security auditing, quality scoring, AST-based taint analysis, live CVE scanning,
  and pre-write safety checks. Supports 28+ languages with tree-sitter + regex
  fallback parsing. MCP server exposes 76 tools for AI agent integration.
  For quick command reference with validated output schemas, see SKILL-QUICK.md.
  For version history, see CHANGELOG.md.
---

# CodeLens

Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

**Quick command reference →** [SKILL-QUICK.md](SKILL-QUICK.md) (validated output schemas, error behavior, trigger maps)
**Version history →** [CHANGELOG.md](CHANGELOG.md)

---

## Zero-Config for AI — Just Run Any Command

CodeLens now supports **zero-config AI usage**. If no registry exists, running any analysis command automatically triggers `init` + `scan`:

```bash
$CLI query "myFunction" --lite
# → If no .codelens/ exists: auto-init + auto-scan → then query
# → Returns: {status:"ok", found:true|false, action:"CREATE"|"EXTEND"|"ASK"|"STOP"}
```

### AI-Optimized Flags (work with ANY command)

| Flag | Effect | When to use |
|------|--------|-------------|
| `--top N` | Limit list results to top N items (sorts by relevance first) | Large repos, token budget concerns |
| `--max-tokens N` | Truncate output to fit ~N tokens | Strict context window limits |
| `--lite` | Minimal output: command-specific tailored response | Quick checks, decision-making |
| `--format ai` | Normalized schema: `{stats, items[], truncated, recommendations}` | Consistent parsing across commands |

### Smart Defaults (Zero-Config Token Savings)

- **Auto `--top 20`**: List commands (smell, complexity, dead-code, secrets, etc.) auto-apply `--top 20`. No more 1000+ item responses by default.
- **Sort-aware `--top`**: Items are sorted by relevance BEFORE truncating — severity for quality commands, cyclomatic score for complexity, effect_count for side-effect.
- **Command-specific `--lite`**: 10+ commands have tailored lite output, not just query. Each lite mode returns the most actionable subset.
- **Override**: Use `--top 0` for unlimited results, or `--top N` for any custom limit.

### Lite Mode Per Command

| Command | `--lite` returns |
|---------|------------------|
| `query` | `{status, found, action, action_reason}` |
| `impact` / `refactor-safe` | `{status, risk, action}` |
| `smell` | `{status, health_score, total_findings, action, top_findings[], stats}` |
| `complexity` | `{status, stats, top_complex[], high_complexity_count}` |
| `dead-code` | `{status, removal_safety, recommended_action, stats, top_items[], total_dead}` |
| `debug-leak` | `{status, stats, top_leaks[], leaks_total}` |
| `perf-hint` | `{status, risk, stats, top_hints[], hints_total}` |
| `secrets` | `{status, risk, action, stats, top_findings[]}` |
| Other | `{status, stats, top 5 items, recommendations}` |

### The One Command You Need

```bash
export CODELENS_AI_MODE=1   # Optional: makes --format ai the default
$CLI query "name" --lite    # Auto-setup + minimal response = {found, action}
```

If `action: CREATE` → safe to write. If anything else → check first.

---

## Onboarding — First-Time AI Setup

This section guides a new AI agent through the complete CodeLens setup process from zero to productive.

### Prerequisites

- Python 3.8+ installed
- Target codebase accessible on filesystem
- ~50MB disk space for tree-sitter grammars (optional but recommended)

### Step 1: Install Dependencies

```bash
bash /path/to/codelens/setup.sh
```

This installs tree-sitter and language grammar packages. If this fails or tree-sitter is unavailable, CodeLens automatically falls back to regex-based parsing — it still works, just with less precision.

### Step 2: Initialize the Workspace

```bash
CLI="python3 /path/to/codelens/scripts/codelens.py"
$CLI init /path/to/project
```

**What it does:** Creates `.codelens/` directory in the workspace root with config file. Auto-detects project type, framework, and language.

**Output:** `{status:"ok", workspace, codelens_dir, config{frontend_paths, backend_paths, ignore, frameworks, ...}}`

**What if the workspace path is wrong?** CodeLens auto-detects by walking up from cwd to find a project root (package.json, pyproject.toml, Cargo.toml, etc.). If it auto-detects, you see a stderr warning.

### Step 3: Build the Registry (REQUIRED)

```bash
$CLI scan /path/to/project
```

**What it does:** Parses all source files, builds a registry of symbols (functions, classes, IDs, CSS classes) and their relationships (call edges, references).

**Timing:**
- <500 files: ~5-15 seconds
- 1,000-5,000 files: ~30-120 seconds
- 5,000+ files: use `--max-files 3000` to prevent timeout

**Output:** `{status:"ok", files_scanned{html,css,python,...}, frontend{classes,ids}, backend{nodes,edges}}`

**What if it's slow?** Use `--max-files N` to limit the number of files scanned. Use `--incremental` after the first scan to only rescan changed files (~1-5 seconds).

**What if tree-sitter is not installed?** You see `WARNING: TSBackendParser init failed, using JS fallback: No module named 'tree_sitter'`. This is non-fatal — regex fallback kicks in automatically.

### Step 4: Verify the Setup

```bash
$CLI query "main" /path/to/project
```

**Expected:** `{status:"ok", found:true|false, ...}` — if you get a valid JSON response, your setup is complete.

### Step 5: After Code Changes

After modifying any source file, always run:

```bash
$CLI scan --incremental /path/to/project
```

This rescans only changed files (~1-5 seconds). Without this, queries may return stale data.

### Common First-Time Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `WARNING: TSBackendParser init failed` | tree-sitter not installed | Run `setup.sh`, or ignore (regex fallback works) |
| `Auto-detected workspace: ...` | Invalid workspace arg | Check the returned `workspace` field matches your project |
| Empty results after scan | No recognized source files | Check `.codelens/codelens.config.json` ignore list |
| `status: "error"` on any command | Registry not built | Run `init` then `scan` first |
| Scan takes too long | Very large repo | Use `--max-files 3000` |

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
| `query` registry not found | Returns `found:false` (not an error) — run `init` + `scan` |
| `query` registry corrupt | Delete `.codelens/` → `init` → `scan` → retry |
| `trace` symbol not found | Try `search` first to locate, then `trace` with exact name |
| `impact` no edges | Run `scan` first to build edges, then retry |
| `vuln-scan` no lockfile | Returns empty results — not an error |
| `ownership` no git repo | Fallback to mtime-based analysis |
| `perf-hint` too many results | Apply `--severity critical` or `--category` filter |
| Any command timeout | Use `--max-files` to reduce scope, or `--timeout` to increase budget |
| `ask` timeout (45s) | `status:"timeout"` — run the specific command directly |
| `analyze` engine timeout | `skipped:true` per-engine — run that command individually |
| `summary` budget exceeded | `timed_out_engines[]` — use `--detail minimal` or specific commands |
| `handbook` budget exceeded | `partial:true` — run individual commands for skipped sections |
| Any `status:"error"` | Follow the `suggestion` field in the error response |

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

## Reading the Output — Signal vs. Metric

| Metric | What it actually means | How to interpret |
|--------|------------------------|------------------|
| `reference_count` / caller count | **Popularity** — how often a symbol is referenced | Not a criticality signal. A payment-flow function called once is more critical than a utility called 50×. |
| `status: dead` | Nothing references it | Flag for removal — but verify it's not an entry point (HTTP handler, CLI subcommand, exported API). |
| `status: duplicate_ref` | Referenced from many places | List all callers with `trace --direction up` before changing. |
| `high_complexity` | Cyclomatic complexity ≥ threshold | Hotspot for bugs, not necessarily important. Cross-reference with `trace --direction up`. |

**To judge importance:** run `trace --direction up <symbol>` to see **who** calls it, then weigh by context (payment, auth, hot path) — not by raw count.

**To reduce noise:**
- `--format compact` — token-efficient single-char keys (AI/script consumption)
- `--lite` — minimal output (decision-making mode, per-command tailored)
- `--detail minimal` (summary) — critical-severity findings only

**First scan is slow by design** — it builds the SQLite graph. Subsequent scans are incremental (`--incremental`).

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

### Token Budget Strategy

CodeLens has **smart defaults** that prevent token overflow without any flags:

1. **Auto `--top 20`** — List commands automatically limit to 20 items. No configuration needed.
2. **Sort-aware truncation** — `--top N` sorts by relevance first (severity, complexity, etc.), so you always get the most important items.
3. **`--lite`** for `query` — returns just `{found, action}` instead of full node details + callers + callees
4. **`--max-tokens 500`** for strict budgets — automatically truncates largest lists to fit
5. **`--format ai`** — normalizes output to consistent `{stats, items[], truncated, recommendations}` schema
6. **`--severity critical`** for `smell`, `secrets`, `perf-hint`, `vuln-scan` — filters noise
7. **`--category`** filters on `dead-code`, `smell`, `perf-hint`, `debug-leak` — narrow scope
8. Use `query --lite` before `context` — if `found:false`, no need for context
9. Use `--top 0` to override smart defaults and get unlimited results
10. Set `CODELENS_AI_MODE=1` env var to make `--format ai` the default output format
11. Auto-setup caps at 3000 files — run `scan` manually for full analysis on large repos

### Auto-Setup Behavior

When no `.codelens/` registry exists, any analysis command auto-runs `init` + `scan`. This is transparent — you don't need to think about setup.

**Timeout protection**: Auto-setup caps scanning at **3000 files** to prevent long waits. If your repo has more files, the auto-setup will be fast but partial. For full analysis, run `scan` manually:

```bash
$CLI scan    # Full scan (no file limit)
```

The `_auto_setup` field in the response tells you if it was capped:
```json
{"auto_setup": true, "capped": true, "hint": "Auto-setup capped at 3000 files. Run 'scan' manually for full analysis."}
```

### CODELENS_AI_MODE

Set the `CODELENS_AI_MODE` environment variable to `1`, `true`, or `yes` to make `--format ai` the **default** output format. This eliminates the need to add `--format ai` to every command.

```bash
export CODELENS_AI_MODE=1
$CLI smell          # Now outputs in --format ai by default
$CLI complexity     # Same
```

Without this env var, the default format is `json` (backward compatible).

### Reference Files

- `references/agent-integration.md` — Full integration guide (CLI, Python API, JSON schemas, decision trees)
- `references/parser-rules.md` — Parsing rules per language
- `references/query-examples.md` — Query examples and output interpretation
- `references/status-codes.md` — Details for all statuses and flags

---

## v8.x Feature Summary

CodeLens v8.0+ adds 7 major capability pillars over v7.x:

1. **AST Taint Engine** (`taint` command) — Tree-sitter AST traversal, path-sensitive, scope-aware, inter-procedural taint tracking with confidence scoring and taint path rendering. Default engine when tree-sitter is available.
2. **Live CVE/OSV Scanning** (`vuln-scan` v2) — Real-time data from OSV.dev API across 9 ecosystems (PyPI, npm, crates.io, Go, Maven, NuGet, RubyGems, Pub, Hex) with SQLite cache + offline fallback.
3. **Plugin System** (`plugin` command) — 4 plugin types (rule_pack / engine / formatter / command), 3-tier discovery (local > user > built-in). Ships with OWASP Top 10 (36 rules) + Compliance (53 rules: PCI-DSS v4.0 + HIPAA).
4. **VS Code Extension** (`vscode-codelens/`) — Diagnostics on save, QuickFix code actions, guard pre-save hooks, status bar health indicator, SARIF v2.1.0 integration.
5. **Cross-File Dataflow Engine** (`dataflow` v2) — Workspace-wide call graph with import resolution (`from/import`, `require` destructuring) and bidirectional taint propagation.
6. **OWASP Top 10 + Compliance Mapping** — 89 rules total (A01-A10 + PCI-DSS requirements 1-12 + HIPAA 45 CFR § 164.312).
7. **CI/CD Quality Gate** (`check` command) — Exits non-zero on failure, SARIF output for GitHub Advanced Security / VS Code.
8. **Gitleaks-Backed Secrets Scanner** (`secrets` command, issue #159) — When [gitleaks](https://github.com/gitleaks/gitleaks) is installed, `codelens secrets` uses it as the primary backend for 600+ maintained rules and entropy scoring. Falls back to the built-in regex scanner when gitleaks is unavailable (opt-in upgrade, never a hard dependency). Use `--no-gitleaks` to force the regex backend. Install: `brew install gitleaks` / `go install github.com/gitleaks/gitleaks/v8@latest` / [GitHub releases](https://github.com/gitleaks/gitleaks/releases).

v8.1 follows up with F1 benchmark improvements (avg F1 0.803 → 0.872), circular engine depth fixes (F1 0.667 → 1.000), dead-code engine fixes (F1 0.800 → 0.952), and AST taint depth enhancements (return-value propagation, scope-hierarchical TaintState, branch condition refinement).
