<p align="center">
  <img alt="CodeLens" src="https://img.shields.io/badge/CodeLens-AI--Native%20Code%20Intelligence-blue?style=for-the-badge" />
</p>

<p align="center">
  <a href="https://pypi.org/project/codelens/"><img alt="PyPI" src="https://img.shields.io/pypi/v/codelens?color=blue"></a>
  <a href="LICENSE.txt"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green.svg"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.8%2B-blue"></a>
  <a href="CONTRIBUTING.md"><img alt="PRs Welcome" src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg"></a>
</p>

# CodeLens — AI-Native Code Intelligence

> **Before an AI writes a new class, id, or function, CodeLens must be checked. This is not optional.**

CodeLens is code intelligence built for AI agents, not humans skimming a dashboard. It gives an agent **full visibility into a codebase before it writes a line** — preventing collisions with existing symbols, silent overwrites, security vulnerabilities, and dead code it can't see coming. One CLI, 12 focused commands, an MCP server for direct agent integration, tree-sitter parsing across 7 core languages (13 with regex fallback for 28 more), and token-efficient output modes built for high-volume agent workflows.

**Replace this:**
```bash
grep -r "handleAuth" src/          # text match, no idea who calls it, is it dead, is it safe to touch
```

**With this:**
```bash
codelens search "handleAuth" . --mode symbol   # exact symbol + status(active/dead) + reference count
codelens context . --check trace --name handleAuth --direction up   # every real caller, cross-file, cross-language
```

---

## Table of Contents

- [Quick Start](#quick-start)
- [Why CodeLens](#why-codelens)
- [The 12 Commands](#the-12-commands)
- [Common Workflows](#common-workflows)
- [Interpreting Output](#interpreting-output)
- [Supported Languages & Frameworks](#supported-languages--frameworks)
- [AI Agent Integration](#ai-agent-integration)
- [Architecture](#architecture)
- [Installation](#installation)
- [Honest Competitive Positioning](#honest-competitive-positioning)
- [Contributing](#contributing)

---

## Quick Start

```bash
pip install codelens

# Scan a workspace and build the graph (auto-runs on first use of any command too)
codelens scan /path/to/workspace

# Find a symbol before creating one — does "handleAuth" already exist?
codelens search "handleAuth" /path/to/workspace --mode symbol

# 10-second orientation on an unfamiliar codebase
codelens context /path/to/workspace

# What's actually dead vs. what looks dead?
codelens audit /path/to/workspace --check dead-code
```

Omit the workspace path and CodeLens auto-detects it from your current directory:

```bash
cd /path/to/workspace
codelens search "handleAuth" --mode symbol
codelens context
```

### Zero-config for AI agents

If no `.codelens/` registry exists yet, any analysis command auto-runs `scan` first — no separate init step required:

```bash
export CODELENS_AI_MODE=1          # --format ai becomes the default
codelens search "handleAuth" . --mode symbol --lite
# → auto-scans (first run only) → returns {status, found, action}
```

> **Token budget matters.** Always pass `--lite` in an agent loop — it cuts every command's output down to the fields that actually drive a decision. See [Interpreting Output](#interpreting-output).

---

## Why CodeLens

Grep and manual reads answer "does this string exist." They don't answer the questions that actually matter before an agent writes or deletes code:

| Question grep can't answer | CodeLens command |
|---|---|
| Is this symbol actually dead, or just rarely called? | `audit --check dead-code` cross-checked with `context --check trace --direction up` |
| Who calls this function, transitively, across file *and* language boundaries? | `context --check trace --name X --direction up\|down` |
| Will deleting/changing this break something? | `impact --check impact --name X` |
| Is there a real command-injection/taint path from user input to a shell call? | `security --check taint` |
| What does this codebase even look like in 10 seconds? | `context` (orient is the default) |
| Structural graph question ("all functions calling any DB write") in one call, not five chained lookups | `search --mode graph` (Cypher subset) |

Every answer comes from a real SQLite-backed call graph (`graph_nodes` + `graph_edges`), built once per scan and reused — not re-grepped from scratch on every query.

---

## The 12 Commands

CodeLens consolidates what used to be ~78 separate commands into **12 umbrella commands** (each with `--check <sub-analysis>` for a specific sub-mode; omit `--check` to run all sub-analyses).

| Command | `--check` sub-modes | What it answers |
|---|---|---|
| `scan` | scan (default) · rescan | Build/refresh the workspace graph. Everything else depends on this having run once. |
| `search` | semantic (default) · symbol · regex · graph | The grep replacement. `pattern` comes **first**, workspace second — opposite of every other command below. See [gotcha](#a-gotcha-worth-memorizing). |
| `context` | orient (default) · outline · trace · context · diagnostics · overview | Orientation, file structure, call-chain tracing, rich symbol context, LSP diagnostics (`--file`), token-efficient symbol map. |
| `deps` | affected · dependents · circular (default: all three) · import-snapshot · export-snapshot | Dependency graph: what's affected by a change, who imports what, circular imports, team snapshot sharing. |
| `audit` | dead-code · complexity · smell · staleness · perf-hint · side-effect · css · a11y (default: all) | Code quality. `dead-code` cross-checked against `context --check trace` before you trust it. `css` = deep CSS analysis, `a11y` = WCAG 2.1 accessibility. |
| `security` | secrets · vuln-scan · taint · binary-scan · regex-audit (default: all) | Hardcoded secrets, CVE/OSV dependency scanning, AST taint analysis, ReDoS. **Taint is Python/JS/TS/TSX only** — no Rust source/sink rules yet. |
| `summary` | summary (default) · dashboard · arch-metrics · architecture | Prioritized, anti-overload findings digest. Use `--lite` — it's designed to still be big without it. |
| `impact` | impact (default) · diff · dataflow | Blast-radius analysis before you touch something. |
| `api-map` | api-map (default) · graph-schema | HTTP/IPC route inventory, auth-middleware coverage, cheap graph-shape introspection. |
| `doctor` | doctor (default) · env-check · lsp-status | Environment/dependency health check. |
| `history` | history (default) · ownership · git-status | Trend tracking across scans, git blame ownership, scan staleness vs. HEAD. |
| `graph` | — | Raw Cypher-subset query for power users. Casual callers should use `search --mode graph` instead. |

### A gotcha worth memorizing

`search` takes `pattern` first, `workspace` second. Every other command above takes `workspace` first. Getting this backwards does **not** error — the workspace path silently becomes the search pattern and you get an empty `"ok"` result.

```bash
codelens search "handleAuth" .  --mode symbol   # correct
codelens audit                .  --check dead-code  # different order, also correct
```

---

## Common Workflows

```bash
# Before creating a new component/function — does it already exist?
codelens search "AdGate" . --mode symbol --lite

# Full 10-second orientation on a repo you've never seen
codelens context .

# Is this symbol safe to delete? (cross-check dead-code with trace)
codelens audit . --check dead-code --lite
codelens context . --check trace --name myOldHelper --direction up

# What breaks if I change this?
codelens impact . --check impact --name processPayment

# Security sweep before a release
codelens security . --check secrets
codelens security . --check vuln-scan
codelens security . --check taint

# CI/CD quality gate — exits non-zero on failure
codelens check . --severity high --max-findings 50
codelens check . --format sarif > codelens.sarif

# Structural query in one call instead of chaining trace+impact+context
codelens search "MATCH (f:function)-[:CALLS]->(g:function) WHERE g.name CONTAINS 'exec' RETURN f.name, g.name LIMIT 20" . --mode graph

# GraphML export — opens directly in Gephi/Cytoscape/yEd/Neo4j
codelens scan . --format graphml > codelens.graphml
codelens context . --check trace --name main --format graphml > trace.graphml
```

---

## Interpreting Output

### `--lite` is the real token-budget lever

Full non-lite output on a real workspace routinely runs 10-50x larger than `--lite`. Every command supports it; coverage of dedicated (hand-tuned) reducers vs. the generic fallback is documented in [docs/agent-usage-guide.md](docs/agent-usage-guide.md).

### Decision rules

| `search --mode symbol` result | Action |
|---|---|
| not found | Safe to create |
| found, `status: active` | Extend, don't overwrite |
| found, `status: dead` | Ask before reusing — verify with `trace` first |
| found, multiple matches | List all referrers before touching anything |

| `impact` risk level | Action |
|---|---|
| `critical` | Do not change without explicit user confirmation |
| `high` | List every affected file first |
| `medium` | Proceed with test coverage |
| `low` | Safe |

### `reference_count` is popularity, not importance

A function called once in the payment flow can be more critical than a utility called 50 times. To judge real importance: `context --check trace --name X --direction up` to see **who** calls it, then weigh by context (payment, auth, entry point). `status: dead` in `audit --check dead-code` is not automatically "safe to delete" either — cross-check the same way; entry points (HTTP handlers, CLI subcommands, exported APIs) often show zero inbound graph edges but are still critical.

First `scan` on a workspace is intentionally slower (builds the SQLite graph from scratch). Every subsequent scan is incremental.

---

## Supported Languages & Frameworks

**Tree-sitter parsed (AST-level), verified against a real 425-file polyglot Tauri+React workspace:** Rust, TypeScript, TSX/JSX, JavaScript, Python, HTML, CSS/SCSS. Also: Vue SFC, Svelte, Blade.

**Regex fallback (28+ additional languages):** C, C++, C#, Go, Java, Kotlin, Swift, Ruby, PHP, Scala, Dart, Elixir, Lua, R, Haskell, Nim, Objective-C, GDScript, Shell/Bash, Vim, Zig, and more.

**Frameworks auto-detected:** React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind CSS, Express, Fastify, Koa, Hono, Django, Flask, FastAPI, Tauri, and more.

**Per-language verified coverage** (dead-code accuracy, taint gaps, trace behavior) is documented in detail in [docs/agent-usage-guide.md](docs/agent-usage-guide.md) — including the honest gap: `security --check taint` has zero Rust coverage today.

---

## AI Agent Integration

**Key principle:** before an AI writes any new class, id, or function, it should query CodeLens first to check for collisions, overwrites, and dead code.

### MCP Server

CodeLens ships a native MCP server (JSON-RPC over stdio) with **12 tools** — one per umbrella command, auto-discovered from the command registry:

```bash
codelens serve   # not available — MCP tools are invoked by an MCP-aware client (Claude Desktop, Cursor, VS Code Copilot, Continue.dev, Cline), see mcp_config.json for templates
```

Every MCP tool accepts a `format` parameter (`json`/`markdown`/`ai`/`sarif`/`compact`/`graphml`). For high-volume agent workflows pass `format: "compact"` (single-char keys, ~50% smaller). For graph-shape introspection before paying tokens on a structural query, call `codelens_api_map` with `--check graph-schema` first:

```json
{"name": "codelens_api_map", "arguments": {"workspace": "/path/to/proj", "check": "graph-schema", "format": "compact"}}
// → {"s":"ok","n":1234,"e":5678,"nts":{"function":1000,"class":234},"ets":{"CALLS":5678}}
```

See [mcp_config.json](mcp_config.json) for Claude Desktop, Cursor, VS Code Copilot, Continue.dev, and Cline configuration templates.

### CI/CD Quality Gate

```bash
# Exits non-zero on failure — wire into CI
codelens check . --severity high --max-findings 50

# SARIF for GitHub Advanced Security / VS Code
codelens check . --format sarif > codelens.sarif
```

### Plugin System

```bash
codelens plugin list
# Built-in: owasp_top10 (36 rules, A01-A10) + compliance (53 rules: PCI-DSS v4.0 + HIPAA)
```

---

## Architecture

```
codelens/
├── SKILL.md / SKILL-QUICK.md      # Full / quick reference for AI agents
├── README.md                      # This file
├── docs/
│   ├── agent-usage-guide.md       # Verified per-language coverage, --lite reducer coverage, known gaps
│   └── design/                    # Design docs (one per feature-class PR, issue-numbered)
├── references/                    # parser-rules, query-examples, status-codes, agent-integration
├── scripts/
│   ├── codelens.py                # CLI entry point
│   ├── mcp_server.py              # MCP JSON-RPC server (12 tools)
│   ├── commands/                  # One file per CLI command + per-umbrella --check sub-mode
│   ├── *_engine.py                # Analysis engines (taint, callgraph, deadcode, secrets, ...)
│   ├── parsers/                   # Tree-sitter + 28 regex fallback parsers
│   ├── formatters/                # json, markdown, ai, sarif, compact, graphml
│   ├── graph_model.py             # graph_nodes + graph_edges SQLite schema
│   └── plugins/                   # owasp_top10, compliance rule packs
├── benchmarks/                    # Benchmark suite & fixtures
├── tests/                         # pytest suite
└── vscode-codelens/                # VS Code extension source
```

## Installation

```bash
pip install codelens
codelens --help
```

For local development against the source checkout:

```bash
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens
bash setup.sh
pip install -e .
codelens --help
```

**Requirements:** Python 3.8+. tree-sitter grammars auto-installed by `setup.sh`. `watchdog` optional (file watching), `git` optional (ownership analysis), a language server optional (`--deep` LSP-enhanced analysis).

---

## Honest Competitive Positioning

CodeLens excels in **AI-native code intelligence** — a niche where MCP integration and AI-optimized output matter most. Here's an honest assessment against established tools:

| Dimension | CodeLens | SonarQube | CodeQL | Semgrep |
|---|:---:|:---:|:---:|:---:|
| AI Agent Integration | **8** | 4 | 3 | 5 |
| Frontend Breadth | **8** | 6 | 3 | 5 |
| MCP / AI-Native Design | **9** | 2 | 2 | 3 |
| Taint Analysis Depth | 5 | 7 | **10** | 7 |
| CI/CD & SARIF | 5 | **10** | 7 | 8 |
| Plugin/Rule Ecosystem | 2 | **10** | 5 | 8 |
| IDE Integration | 4 | **9** | 8 | 9 |
| Community & Maturity | 1 | **10** | 8 | 7 |
| Live CVE Scanning | 7 | 9 | 3 | **8** |
| Cross-File Analysis | 6 | 8 | **10** | 7 |

**Genuine strengths:** AI-native design, frontend analysis breadth, MCP integration.
**Where we lag:** community ecosystem, IDE marketplace presence, deep abstract interpretation (CodeQL's domain).
**Goal:** the best code intelligence tool for AI agent workflows — not a SonarQube replacement.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security issues: see [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE.txt](LICENSE.txt).

## Changelog

[CHANGELOG.md](CHANGELOG.md) (current) · [references/changelog.md](references/changelog.md) (older per-version highlights).
