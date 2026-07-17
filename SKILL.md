---
name: codelens
description: >
  CodeLens — AI-Native Code Intelligence. 12 commands for AI-powered code
  analysis, security auditing, quality scoring, AST-based taint analysis, live CVE
  scanning, and pre-write safety checks (each command is an umbrella over focused
  --check sub-modes). Tree-sitter parsing for 7 core languages (Rust, TypeScript,
  TSX, JavaScript, Python, HTML, CSS) plus 28+ languages via regex fallback.
  MCP server exposes 12 tools for AI agent integration.
  For quick command reference with validated output schemas, see SKILL-QUICK.md.
  For version history, see CHANGELOG.md.
---

# CodeLens

Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

**Quick command reference →** [SKILL-QUICK.md](SKILL-QUICK.md) (validated output schemas, error behavior, trigger maps)
**Version history →** [CHANGELOG.md](CHANGELOG.md)
**Verified per-language coverage & known gaps →** [docs/agent-usage-guide.md](docs/agent-usage-guide.md)

---

## Architecture — read this first if you know an older CodeLens

CodeLens consolidated ~78 legacy commands into **12 umbrella commands** (issue #195/#199/#200). If you have seen CodeLens before and remember `query`, `init`, `smell`, `dead-code`, `secrets`, `trace`, `impact`, `circular`, `guard`, or `serve` as top-level commands — those no longer exist as standalone commands. They are now `--check <sub-mode>` flags under one of the 12 umbrellas below:

```
codelens query "name" .                 →  DROPPED (no direct replacement; use `search --mode symbol`)
codelens dead-code .                    →  codelens audit . --check dead-code
codelens secrets .                      →  codelens security . --check secrets
codelens trace "name" .                 →  codelens context . --check trace --name "name"
codelens impact "name" .                →  codelens impact . --check impact --name "name"
codelens circular .                     →  codelens deps . --check circular
codelens init .                         →  DROPPED (scan auto-inits)
codelens serve                          →  DROPPED (MCP tools invoked by an MCP-aware client, not this CLI)
codelens guard --pre --file X           →  DROPPED
```

## The 12 Umbrella Commands

| Command | `--check` sub-modes |
|---|---|
| `scan` | scan (default) · rescan |
| `search` | semantic (default) · symbol · regex · graph — **`pattern` comes first, workspace second**, opposite of every other command here |
| `context` | orient (default) · outline · trace · context · diagnostics (LSP lint, needs `--file`) · overview (token-efficient symbol map) · tags (`@FLOW`/`@ENTRY` doc-tag audit) |
| `deps` | affected · dependents · circular (default: all three) · import-snapshot · export-snapshot |
| `audit` | dead-code · complexity · smell · staleness · perf-hint · side-effect · css (deep CSS) · a11y (WCAG 2.1) (default: all) |
| `security` | secrets · vuln-scan · taint · binary-scan · regex-audit (default: all) |
| `summary` | summary (default) · dashboard · arch-metrics · architecture |
| `impact` | impact (default) · diff · dataflow |
| `api-map` | api-map (default) · graph-schema |
| `doctor` | doctor (default) · env-check · lsp-status |
| `history` | history (default) · ownership · git-status |
| `graph` | — (raw Cypher; casual callers use `search --mode graph` instead) |

Two additional commands are registered but hidden from `--help` (pending a maintainer decision on their final home, issue #200): `check` (CI/CD quality gate) and `plugin` (plugin management). Both work today — call them directly, e.g. `codelens check . --severity high`.

---

## Zero-Config for AI — Just Run Any Command

If no `.codelens/` registry exists, running any analysis command automatically triggers `scan` first:

```bash
codelens search "myFunction" . --mode symbol --lite
# → If no .codelens/ exists: auto-scan → then search
# → Returns: {status:"ok", ...} — see the specific command's Lite Mode row below
```

### AI-Optimized Flags (work with every command)

| Flag | Effect | When to use |
|---|---|---|
| `--top N` | Limit list results to top N items (sorts by relevance first) | Large repos, token budget concerns |
| `--max-tokens N` | Truncate output to fit ~N tokens | Strict context window limits |
| `--lite` | Minimal output: command-specific tailored response | Quick checks, decision-making — **use this by default in an agent loop** |
| `--format ai` | Normalized schema: `{stats, items[], truncated, recommendations}` | Consistent parsing across commands |
| `--format compact` | Single-char keys, ~50% smaller than `json` | High-volume MCP tool calls |

### Lite Mode Per Command

| Command | `--lite` returns |
|---|---|
| `search --mode symbol` | full symbol result (no dedicated reducer — small payload already) |
| `impact --check impact` / `impact --check diff` | `{status, risk, action}` |
| `audit --check smell` | `{status, health_score, total_findings, action, top_findings[], stats}` |
| `audit --check complexity` | `{status, stats, top_complex[], high_complexity_count}` |
| `audit --check dead-code` | `{status, removal_safety, recommended_action, stats, top_items[], total_dead}` |
| `security --check secrets` | `{status, risk, action, stats, top_findings[]}` |
| `security --check taint` | `{status, risk, stats, top_findings[], recommendations}` |
| `summary` | `{status, workspace, identity, frameworks, recommendations, findings[]}` — each finding's `top_items` capped to 3, nested `flow_chain` stripped |
| `history` | `{status, workspace, snapshots, latest{health_score,...}, trends, deltas}` |
| Other | generic fallback: `{status, stats, top 5 items, recommendations}` — adequate, not hand-tuned |

### The One Command You Need

```bash
codelens search "handleAuth" . --mode symbol --lite
```

If not found → safe to write. If found + `status: active` → extend, don't overwrite. If found + `status: dead` → ask before reusing.

---

## Onboarding — First-Time AI Setup

### Prerequisites

- Python 3.8+ installed
- Target codebase accessible on filesystem

### Step 1: Install

```bash
pip install codelens
```

(For a source checkout: `bash setup.sh && pip install -e .` — installs tree-sitter grammars. If tree-sitter is unavailable, CodeLens automatically falls back to regex-based parsing.)

### Step 2: Build the Registry

```bash
codelens scan /path/to/project
```

No separate `init` step — `scan` handles workspace detection and registry creation in one call.

**Timing:** <500 files: ~5-15s · 1,000-5,000 files: ~30-120s · 5,000+ files: use `--max-files 3000` to prevent timeout.

**Output:** `{status:"ok", files_scanned{...}, frontend{classes,ids}, backend{nodes,edges}}`

### Step 3: Verify

```bash
codelens search "main" /path/to/project --mode symbol
```

Any valid JSON response means setup is complete.

### Step 4: After Code Changes

```bash
codelens scan /path/to/project --incremental
```

Without this, queries return stale data.

### Common First-Time Issues

| Issue | Cause | Fix |
|---|---|---|
| `WARNING: TSBackendParser init failed` | tree-sitter not installed | `bash setup.sh`, or ignore (regex fallback works) |
| `Auto-detected workspace: ...` | Invalid workspace arg | Check the returned `workspace` field matches your project |
| Search silently returns 0 results | Argument order backwards | `search` takes `pattern` first, `workspace` second — every other command is the reverse |
| Empty results after scan | No recognized source files | Check `.codelens/codelens.config.json` ignore list |
| `status: "error"` on any command | Registry not built | Run `scan` first |
| Scan takes too long | Very large repo | Use `--max-files 3000` |

---

## Workspace Auto-Detect

The `workspace` argument is optional for every command:

```bash
codelens scan                              # Auto-detect → works!
codelens search "myFunc" --mode symbol     # Auto-detect → works!
codelens audit --check smell               # Auto-detect → works!
```

Resolution order: current directory (project markers: package.json, pyproject.toml, Cargo.toml, ...) → parent directories (up to 10 levels) → last used workspace cache → current working directory.

---

## AI Workflows

### Pre-Write Check (recommended)

```
1. search "name" --mode symbol → not found = SAFE, active = EXTEND, dead = ASK
2. Write code
3. scan --incremental
```

### Security Audit Chain

```
security --check secrets → security --check taint → security --check vuln-scan
```

### Quality Gate

```
audit --check smell → audit --check complexity → audit --check dead-code → security --check secrets
```

### Code Review

```
scan --incremental → deps --check circular → audit --check dead-code → security --check secrets
```

### Bug Investigation

```
search "pattern" . --mode regex → context . --check trace --name X --direction up
```

### New Feature Development

```
search "name" --mode symbol → context (if exists) → audit --check side-effect → write → scan --incremental
```

---

## Error Recovery

| Failure | Recovery |
|---|---|
| `scan` file read error | Skip unreadable files, scan the rest |
| `scan` grammar import error | Fallback to regex parser automatically |
| `search --mode symbol` not found | Returns `found:false`-equivalent (not an error) — run `scan` first if registry is missing |
| Registry corrupt | Delete `.codelens/` → `scan` → retry |
| `context --check trace` symbol not found | Try `search --mode symbol` first to locate the exact name |
| `impact` no edges | Run `scan` first to build edges, then retry |
| `security --check vuln-scan` no lockfile | Returns empty results — not an error |
| `history --check ownership` no git repo | Fallback to mtime-based analysis |
| Any command timeout | Use `--max-files` to reduce scope |
| Any `status:"error"` | Follow the `error`/`suggestion` field in the response |

---

## Status & Flag Reference

| Status | Meaning | AI Action |
|---|---|---|
| `active` | Used, ref_count > 0 | Normal, proceed |
| `dead` | Nothing references it in the graph | Cross-check with `trace --direction up` before flagging to user |
| `duplicate_ref` | Referenced from many places | List all callers |
| `collision` | Same id/name defined ambiguously | Stop, fix first |
| `duplicate_define` | Defined more than once | Warning |

**Priority order:** collision → duplicate_define → dead → duplicate_ref → active → not found

---

## Reading the Output — Signal vs. Metric

| Metric | What it actually means | How to interpret |
|---|---|---|
| `reference_count` / caller count | **Popularity** — how often a symbol is referenced | Not a criticality signal. A payment-flow function called once is more critical than a utility called 50×. |
| `status: dead` | Nothing references it in the graph | Flag for removal — but verify it's not an entry point (HTTP handler, CLI subcommand, exported API) first. |
| `status: duplicate_ref` | Referenced from many places | List all callers with `context --check trace --direction up` before changing. |
| `high_complexity` | Cyclomatic complexity ≥ threshold | Hotspot for bugs, not necessarily important. Cross-reference with `trace --direction up`. |

**To judge importance:** `context --check trace --name X --direction up` to see **who** calls it, then weigh by context (payment, auth, entry point) — not by raw count.

**To reduce noise:** `--format compact` for token-efficient output, `--lite` for decision-making mode, `--detail minimal` (where supported) for critical-severity findings only.

**First scan is slow by design** — it builds the SQLite graph. Subsequent scans are incremental (`--incremental`).

---

## Integration with AI Agent

### CLI Integration

```python
import subprocess, json

def cl_search(name, workspace, mode="symbol"):
    r = subprocess.run(
        ["codelens", "search", name, workspace, "--mode", mode, "--lite"],
        capture_output=True, text=True, timeout=30,
    )
    return json.loads(r.stdout)
```

### Mandatory Rules

1. **Search before write** — always check for an existing symbol before creating a new class/id/function
2. **Scan after write** — run `scan --incremental` after modifying code
3. **Report dead code, don't silently ignore it**
4. **Handle errors** — gracefully handle subprocess timeouts and JSON parse errors

### Token Budget Strategy

1. **`--top N`** — sorts by relevance first (severity, complexity, ...), then truncates
2. **`--lite`** — command-specific minimal payload (see table above)
3. **`--max-tokens N`** — hard cap, truncates the largest lists to fit
4. **`--format ai`** — normalizes output to `{stats, items[], truncated, recommendations}`
5. **`--format compact`** — single-char keys, smallest payload
6. Set `CODELENS_AI_MODE=1` to make `--format ai` the default output format
7. Auto-setup caps scanning at 3000 files — run `scan` manually (no cap) for full analysis on large repos

### CODELENS_AI_MODE

```bash
export CODELENS_AI_MODE=1
codelens audit --check smell        # now outputs in --format ai by default
```

Without this env var, the default format is `json`.

### Reference Files

- [docs/agent-usage-guide.md](docs/agent-usage-guide.md) — verified per-language coverage, `--lite` reducer coverage, known gaps, with real before/after fix evidence
- `references/agent-integration.md` — CLI/Python API integration guide
- `references/parser-rules.md` — parsing rules per language
- `references/query-examples.md` — query examples and output interpretation
- `references/status-codes.md` — details for all statuses and flags

---

## Feature Summary

- **AST Taint Engine** (`security --check taint`) — tree-sitter AST traversal, path-sensitive, scope-aware, inter-procedural taint tracking with confidence scoring. **Python/JS/TS/TSX only** — no Rust source/sink rules yet.
- **Live CVE/OSV Scanning** (`security --check vuln-scan`) — real-time data from OSV.dev across 9 ecosystems (PyPI, npm, crates.io, Go, Maven, NuGet, RubyGems, Pub, Hex), SQLite cache + offline fallback.
- **Plugin System** (`plugin` command) — 4 plugin types (rule_pack/engine/formatter/command), 3-tier discovery. Ships with OWASP Top 10 (36 rules) + Compliance (53 rules: PCI-DSS v4.0 + HIPAA).
- **Cross-File Dataflow Engine** (`impact --check dataflow`) — workspace-wide call graph with import resolution and bidirectional taint propagation.
- **CI/CD Quality Gate** (`check` command) — exits non-zero on failure, SARIF output for GitHub Advanced Security / VS Code.
- **Gitleaks-Backed Secrets Scanner** (`security --check secrets`) — uses [gitleaks](https://github.com/gitleaks/gitleaks) as the primary backend when installed (600+ rules, entropy scoring), falls back to the built-in regex scanner otherwise. `--no-gitleaks` forces the regex backend.
- **Rust-aware dead-code detection** — `#[cfg(test)] mod tests { #[test] fn ... }` inline test functions are correctly exempted (fixed 2026-07-12; previously 56%+ of Rust `registry_dead` findings were test-function false positives).
