# CodeLens — AI-Native Code Intelligence

> **Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.**

CodeLens is an AI-native code intelligence platform that gives AI agents **full visibility** into a codebase before they write any code. It prevents collision, overwrite of existing logic, security vulnerabilities, and dead code through 12 CLI commands, an MCP server with 12 tools (56 static + -44 dynamic), AST-based taint analysis, live CVE/OSV scanning, a plugin system with OWASP Top 10 + Compliance rule packs, a true graph data model (nodes + edges) for structural code queries, and token-efficient `--format compact` output for high-volume agent workflows (issue #17).

## Features

- **12 CLI Commands** — From basic scan/query to AST taint analysis, CVE scanning, plugin management, auto-fix, dashboards, CI/CD quality gates, and `graph-schema` for cheap graph-shape introspection
- **MCP Server (12 Tools)** — Native AI agent integration via Model Context Protocol (JSON-RPC over stdio), 56 statically-defined tools + -44 dynamically discovered, every tool accepts a `format` parameter (`json`/`markdown`/`ai`/`sarif`/`compact`)
- **Token-Efficient Compact Output (v8.2, issue #17)** — `--format compact` produces single-char-key JSON with abbreviated types, omitted null fields, and relative paths — ~50% smaller than `json` on real trace output. Combined with `--limit`/`--offset` pagination, 5 structural queries now cost <5k tokens (down from 30-80k)
- **AST Taint Engine** — Tree-sitter based taint analysis with return-value propagation, scope hierarchy, and branch condition refinement
- **Live CVE/OSV Scanning** — Real-time vulnerability data from OSV.dev API with SQLite cache, 9 ecosystems (PyPI, npm, crates.io, Go, Maven, NuGet, RubyGems, Pub, Hex)
- **Cross-File Call Graph** — Workspace-wide call graph with import resolution and bidirectional taint propagation
- **Graph Data Model (v8.2)** — True node + edge graph (`graph_nodes` + `graph_edges` SQLite tables) for structural queries: callers, callees, blast radius, circular chains. Populated during scan; `trace` engine migrated to use it by default with `--use-graph` / `--no-graph` flag for A/B testing
- **Plugin System** — 4 plugin types (rule_pack/engine/formatter/command), 3-tier discovery (local → user → built-in), OWASP Top 10 (36 rules) + Compliance (53 rules: PCI-DSS v4.0 + HIPAA)
- **VS Code Extension** — Diagnostics Provider, Code Actions, Guard hooks, Health status bar
- **CI/CD Integration** — GitHub Actions workflows, SARIF v2.1.0 output, PR decoration, `check` quality-gate command
- **Guard Command** — Pre/post-write verification designed for AI agent workflows
- **Tree-sitter Powered** — Accurate AST-based parsing for HTML, CSS, JS, TS/TSX, Rust, Python, Vue, Svelte, Blade
- **Regex Fallback Parsers** — 28 additional languages supported via regex-based parsers (C, C++, Go, Java, Kotlin, Swift, Ruby, PHP, Scala, Dart, Elixir, Lua, R, Haskell, Nim, Objective-C, GDScript, Shell, Vim, Zig, and more)
- **Framework Auto-Detection** — React/Next.js, Vue, Svelte, Tailwind CSS, Express, Fastify, Koa, Hono, Django, Flask, FastAPI, Tauri, and more
- **Incremental Scanning** — Only re-parse changed files for speed, with SQLite persistent registry storage
- **Git-Aware Re-Index (v8.2)** — `scan --incremental` uses `git diff <last-indexed-sha> --name-only` to enumerate exactly the files git knows changed (mtime fallback when git unavailable). `git-status` reports the HEAD/last-indexed SHA + branch + changed-files count + re-scan recommendation in one call. `diff --git-aware` shows changed files + symbols + downstream caller impact. `watch --git-mode` polls `git diff --name-only` instead of watchdog file events. All features gracefully degrade when git is unavailable
- **Workspace Auto-Detect** — No need to specify workspace path if you're already in the project
- **AI-Optimized Output** — `--format ai` (normalized schema) and `--format compact` (token-efficient single-char keys) flags for AI agent consumption
- **Auto-Fix Engine** — Confidence-scored auto-fixes with dry-run-by-default safety
- **HTML Dashboard** — Generate visual dashboards with historical trend tracking
- **Hybrid LSP Engine** — Optional LSP-enhanced deep analysis (`--deep` flag) when language servers are available
- **Security Auditing** — Detect hardcoded secrets, data flow taint analysis, CVE scanning, ReDoS regex auditing
- **Quality Scoring** — Code smells, complexity metrics, dead code detection
- **CSS Deep Analysis** — Unused variables, orphan keyframes, specificity wars, z-index abuse
- **Performance Hints** — N+1 queries, sync blocking, memory leaks, expensive renders

## Quick Start

```bash
# Install dependencies (tree-sitter grammars + watchdog)
bash setup.sh

# Initialize workspace (auto-detects frameworks)
python3 scripts/codelens.py init /path/to/workspace

# Scan workspace and build registry
python3 scripts/codelens.py scan /path/to/workspace

# Check if "btn-primary" already exists before creating it
python3 scripts/codelens.py query "btn-primary" /path/to/workspace --domain frontend

# List all dead code
python3 scripts/codelens.py list /path/to/workspace --domain all --filter dead

# Detect frameworks
python3 scripts/codelens.py detect /path/to/workspace
```

### Workspace Auto-Detect (v5.1+)

If you omit the workspace path, CodeLens auto-detects it:

```bash
python3 scripts/codelens.py scan              # Auto-detect workspace
python3 scripts/codelens.py query "btn-primary" # Auto-detect workspace
python3 scripts/codelens.py smell              # Auto-detect workspace
```

### Zero-Config for AI Agents (v6+)

If no `.codelens/` registry exists, any analysis command auto-runs `init` + `scan` (capped at 3000 files to prevent timeout):

```bash
export CODELENS_AI_MODE=1           # --format ai becomes default
python3 scripts/codelens.py query "myFunction" --lite
# → Auto-init + auto-scan → then query → {found, action}
```

## Command Reference

CodeLens consolidates 78 legacy commands into **12 focused umbrella commands** (issue #195). Each umbrella command accepts a `--check <category>` flag to select a specific sub-analysis, or runs all sub-analyses by default. Legacy command names still work as deprecated aliases (backward compat for one version) but print a redirect warning to stderr.

### The 12 Umbrella Commands

| Command | Absorbs | Description |
|---------|---------|-------------|
| `scan [workspace] [--check scan\|init\|rescan]` | scan, init, rescan | Scan workspace and build registry. `--check init` writes config only; `--check rescan` is incremental. |
| `search [workspace] "query" [--mode semantic\|symbol\|regex\|graph]` | symbols, semantic-query, query-graph, search | Unified search. Default mode is semantic (TF-IDF by meaning). `--mode symbol` for exact name lookup, `--mode regex` for code search, `--mode graph` for Cypher-subset queries. |
| `context [workspace] [--check orient\|outline\|trace\|context]` | context, outline, trace, orient | Codebase & symbol context. Default `--check orient` gives a 10-second orientation brief. `--name <symbol>` required for trace/context sub-analyses. |
| `deps [workspace] [--check affected\|dependents\|circular\|import-snapshot]` | affected, dependents, circular, import-snapshot | Dependency-graph intelligence. `--check affected` takes `--files`; `--check import-snapshot` takes `--input path.codelens.gz`. |
| `audit [workspace] [--check dead-code\|complexity\|smell\|staleness\|perf-hint\|side-effect]` | dead-code, complexity, smell, staleness, god-module, perf-hint, side-effect | Code-quality audits. Default runs all checks. |
| `security [workspace] [--check secrets\|vuln-scan\|taint\|binary-scan\|regex-audit]` | secrets, vuln-scan, taint, binary-scan, regex-audit | Security & vulnerability scans. Default runs all checks. |
| `summary [workspace] [--check summary\|dashboard\|arch-metrics\|architecture]` | summary, dashboard, arch-metrics, architecture | Auto-summary, dashboards, architecture metrics. Default `--check summary` runs the legacy prioritized-findings aggregator. |
| `impact [workspace] [--check impact\|diff\|dataflow]` | impact, diff, dataflow | Change-impact & dataflow analysis. Default `--check impact` takes `--name <symbol>`. |
| `api-map [workspace] [--check api-map\|graph-schema]` | api-map, routes, graph-schema | API surface & graph schema introspection. Default `--check api-map`. |
| `doctor [workspace] [--check doctor\|env-check\|lsp-status]` | doctor, env-check, lsp-status | Environment audit. Default `--check doctor` runs the full dependency audit. |
| `history [workspace] [--check history\|ownership\|git-status]` | history, ownership, git-status | Historical trends, code ownership, git scan state. Default `--check history`. |
| `graph [workspace] "Cypher query"` | query-graph (raw Cypher) | Raw Cypher-subset graph query for power users. Casual callers should prefer `search --mode graph`. |

### Deprecated Aliases (backward compat, 1 version)

All 40+ legacy command names (e.g. `codelens dead-code`, `codelens symbols`, `codelens trace`, `codelens secrets`, `codelens diff`, `codelens dashboard`, `codelens ownership`, `codelens git-status`, `codelens env-check`, `codelens lsp-status`, `codelens arch-metrics`, `codelens architecture`, `codelens impact`, `codelens dataflow`, `codelens circular`, `codelens affected`, `codelens dependents`, `codelens import-snapshot`, `codelens staleness`, `codelens perf-hint`, `codelens side-effect`, `codelens vuln-scan`, `codelens taint`, `codelens binary-scan`, `codelens regex-audit`, `codelens outline`, `codelens orient`, `codelens semantic-query`, `codelens query-graph`, `codelens graph-schema`, `codelens init`) are still callable but hidden from `--help`. Invoking any of them prints a deprecation warning to stderr that redirects to the new umbrella command.

### Dropped Commands (removed in issue #195)

The following commands were removed entirely — broken, no value, or out of scope: `adr`, `a11y`, `handbook`, `ask`, `serve`, `sessions`, `watch`, `registry-validate`, `rule-test`, `rule-validate`, `artifact-scan`, `css-deep`, `debug-leak`, `detect`, `export-snapshot`, `refactor-safe`, `resolve-types`, `stack-trace`, `migrate` (as a command — utility module kept for tests), `benchmark`, `fix`, `self-analyze`, `guard`, `llm`, `memory`.

### Hidden Commands (pending BOS decision)

The following 13 commands are not in any absorb list nor explicitly dropped. They are kept callable but hidden from `--help` pending a BOS decision on where they belong: `analyze`, `check`, `config-drift`, `deps-audit`, `entrypoints`, `lsp`, `list`, `missing-refs`, `plugin`, `query`, `state-map`, `test-map`, `type-infer`.

## Query Decision Rules

| Query Result | Action |
|-------------|--------|
| `found: false` | SAFE — create new |
| `found: true` + `status: active` | EXTEND — don't overwrite |
| `found: true` + `status: dead` | ASK user — reuse or delete? |
| `found: true` + `status: duplicate_ref` | LIST all referrers first |
| `found: true` + `status: collision` | STOP — active bug, fix first |

## Impact Risk Levels

| Risk Level | Action |
|-----------|--------|
| `critical` | DO NOT change. Report to user. |
| `high` | Warning. List all affected first. |
| `medium` | Caution. Run tests. |
| `low` | Safe, proceed. |

## Interpreting Signals

- `reference_count` / caller count = **how often** something is called, not how important it is. A function called once in the payment flow can be more critical than a utility called 50×.
- To judge importance, run `trace --direction up <symbol>` to find **who** calls it, then weigh by context (payment, auth, hot path).
- Use `--format compact` for AI/script consumption (token-efficient single-char keys), `--lite` for minimal output in large repos.
- First `scan` is intentionally slower — it builds the SQLite graph. Subsequent runs are incremental (pass `--incremental` to only re-scan changed files).

## Supported Languages & Frameworks

**Tree-sitter parsed (AST-level):** HTML, CSS, SCSS, JavaScript, TypeScript, TSX/JSX, Rust, Python, Vue SFC, Svelte, Blade

**Regex fallback parsed (28+ languages):** C, C++, C#, Go, Java, Kotlin, Swift, Ruby, PHP, Scala, Dart, Elixir, Lua, R, Haskell, Nim, Objective-C, GDScript, Shell/Bash, Vim, Zig, and more

**Frameworks:** React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind CSS, Express, Fastify, Koa, Hono, Django, Flask, FastAPI, Tauri, Drupal, pytest, poetry, setuptools, tox, sphinx, nox, hatch

**Package Managers:** npm, yarn, pnpm, bun, cargo, pip, pipenv, poetry, go modules

## Architecture

```
codelens/
├── SKILL.md                       # Full documentation for AI agents
├── SKILL-QUICK.md                 # Quick reference (concise)
├── README.md                      # This file
├── CHANGELOG.md                   # Version history (top-level)
├── CONTRIBUTING.md                # Contribution guidelines
├── SECURITY.md                    # Security policy
├── CODE_OF_CONDUCT.md             # Code of Conduct
├── LICENSE.txt                    # MIT License
├── setup.sh                       # Dependency installer
├── pyproject.toml                 # Python package metadata
├── skill.json                     # Skill metadata
├── mcp_config.json                # MCP server config templates (Claude, Cursor, VS Code, Continue, Cline)
├── pytest.ini                     # Pytest configuration
├── references/                    # Detailed reference docs
│   ├── parser-rules.md            # Parsing rules per language
│   ├── query-examples.md          # Query usage examples
│   ├── status-codes.md            # Status & flag reference
│   ├── changelog.md               # Older changelog (per-version highlights)
│   └── agent-integration.md       # AI agent integration guide
├── scripts/
│   ├── codelens.py                # CLI entry point (12 commands registered)
│   ├── mcp_server.py              # MCP JSON-RPC server (12 tools)
│   ├── registry.py                # Registry read/write/build
│   ├── persistent_registry.py     # SQLite persistent storage (WAL mode)
│   ├── base_parser.py             # Base tree-sitter parser
│   ├── base_engine.py             # Base analysis engine
│   ├── grammar_loader.py          # Lazy tree-sitter grammar loader
│   ├── framework_detect.py        # Framework auto-detection
│   ├── incremental.py             # Incremental scan support
│   ├── edge_resolver.py           # Cross-file edge resolution
│   ├── graph_model.py             # Graph data model (nodes + edges) — issue #8
│   ├── git_aware.py               # Git-diff aware incremental re-index — issue #14
│   ├── search_engine.py           # Regex code search
│   ├── trace_engine.py            # Call chain tracing
│   ├── impact_engine.py           # Change impact analysis
│   ├── outline_engine.py          # File structure outline
│   ├── missing_refs.py            # CSS/HTML mismatch detection
│   ├── diff_engine.py             # Registry diff/snapshots
│   ├── circular_engine.py         # Circular dependency detection
│   ├── context_engine.py          # Rich symbol context
│   ├── dependents_engine.py       # Module import tracking
│   ├── validate_engine.py         # Registry validation
│   ├── dataflow_engine.py         # Data flow taint analysis
│   ├── ast_taint_engine.py        # AST-based taint analysis (tree-sitter)
│   ├── crossfile_taint_engine.py  # Cross-file taint propagation
│   ├── callgraph_engine.py        # Workspace-wide call graph
│   ├── smell_engine.py            # Code smell detection
│   ├── sideeffect_engine.py       # Side-effect analysis
│   ├── refactor_safe_engine.py    # Refactoring safety check
│   ├── deadcode_engine.py         # Enhanced dead code detection
│   ├── stacktrace_engine.py       # Error propagation simulation
│   ├── testmap_engine.py          # Test coverage mapping
│   ├── configdrift_engine.py      # Dependency drift detection
│   ├── typeinfer_engine.py        # Lightweight type inference
│   ├── ownership_engine.py        # Git blame ownership
│   ├── secrets_engine.py          # Hardcoded secret detection
│   ├── entrypoints_engine.py      # Entry point mapping
│   ├── apimap_engine.py           # API route mapping
│   ├── statemap_engine.py         # State management tracking
│   ├── envcheck_engine.py         # Environment variable audit
│   ├── debugleak_engine.py        # Debug code leak detection
│   ├── complexity_engine.py       # Complexity scoring
│   ├── regexaudit_engine.py       # Regex auditing (ReDoS)
│   ├── a11y_engine.py             # Accessibility auditing (WCAG 2.1)
│   ├── vulnscan_engine.py         # Vulnerability scanning
│   ├── osv_client.py              # OSV.dev API client (9 ecosystems)
│   ├── perfhint_engine.py         # Performance hints
│   ├── cssdeep_engine.py          # Deep CSS analysis
│   ├── autofix_engine.py          # Auto-fix with confidence scoring
│   ├── dashboard_engine.py        # HTML dashboard generation
│   ├── history_engine.py          # Historical trend tracking
│   ├── semantic_engine.py         # Semantic rules engine
│   ├── hybrid_engine.py           # LSP-enhanced hybrid analysis
│   ├── lsp_client.py              # LSP client wrapper
│   ├── convention_engine.py       # Naming convention checking
│   ├── plugin_system.py           # Plugin system & marketplace
│   ├── pre_commit_hook.py         # Git pre-commit hook integration
│   ├── utils.py                   # Shared utilities (version, helpers)
│   ├── commands/                  # One file per CLI command (auto-registered, 64 commands)
│   ├── formatters/                # Output formatters (markdown, sarif, compact, graphml)
│   ├── parsers/                   # Tree-sitter + fallback parsers
│   │   ├── html_parser.py, css_parser.py, js_frontend_parser.py, js_backend_parser.py
│   │   ├── rust_parser.py, python_parser.py, tsx_parser.py, ts_backend_parser.py
│   │   ├── vue_parser.py, svelte_parser.py, tailwind_detector.py, blade_parser.py
│   │   └── fallback_*.py          # 28 regex-based fallback parsers (C, C++, Go, Java, ...)
│   ├── rules/                     # Built-in YAML rule packs
│   │   ├── javascript_security.yaml
│   │   └── python_security.yaml
│   └── plugins/                   # Built-in plugin packs
│       ├── owasp_top10/rules/owasp_top10.yaml   (36 rules, A01-A10)
│       └── compliance/rules/{hipaa.yaml, pci_dss.yaml}  (53 rules)
├── benchmarks/                    # Benchmark suite & fixtures (clean_app + vulnerable_app)
├── tests/                         # Pytest test suite
└── vscode-codelens/               # VS Code extension source
```

## Requirements

- Python 3.8+
- tree-sitter + language grammars (auto-installed by `setup.sh`)
- watchdog (optional, for file watching)
- git (optional, for ownership analysis)
- Language server (optional, for `--deep` LSP-enhanced analysis)

## Installation

```bash
# Clone the repository
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens

# Run setup
bash setup.sh

# Verify
python3 scripts/codelens.py --help
```

## Integration with AI Agents

CodeLens is designed to be used by AI coding agents. The full integration guide is in [references/agent-integration.md](references/agent-integration.md).

**Key principle:** Before an AI writes any new class, id, or function, it MUST query CodeLens first to check for collisions, overwrites, and dead code.

### MCP Server Integration

CodeLens ships with a native MCP server (55 tools) for direct AI agent integration:

```bash
# Start MCP server (JSON-RPC over stdio)
python3 scripts/codelens.py serve
```

Every MCP tool accepts a `format` parameter with the enum `[json, markdown, ai, sarif, compact, graphml]`.
For high-volume agent workflows, pass `format: "compact"` to cut token usage ~50%.
For graph-producing commands (`scan`, `trace`, `impact`, `circular`), pass `format: "graphml"` to emit a GraphML 1.0 XML document that opens directly in Gephi/Cytoscape/yEd/Neo4j (issue #59 Phase 3). Example:

```json
// tools/call with format=compact
{"name": "codelens_graph_schema", "arguments": {"workspace": "/path/to/proj", "format": "compact"}}
// → {"s":"ok","n":1234,"e":5678,"nts":{"function":1000,"class":234},"ets":{"CALLS":5678},"ix":6}
```

The new `codelens_graph_schema` tool (issue #17) returns the graph shape in one cheap call —
use it first to decide whether structural queries (callers/callees/blast-radius) will return
meaningful results before paying tokens for them.

See `mcp_config.json` for Claude Desktop, Cursor, VS Code Copilot, Continue.dev, and Cline configuration templates.

### Guard Hooks for AI Agents

```bash
# Pre-write safety check
python3 scripts/codelens.py guard /path/to/workspace --pre --file src/new_module.py

# Post-write verification
python3 scripts/codelens.py guard /path/to/workspace --post --file src/new_module.py
```

### CI/CD Quality Gate

```bash
# Quality gate — exits non-zero on failure (use in CI/CD pipelines)
python3 scripts/codelens.py check /path/to/workspace --severity high --max-findings 50

# SARIF output for GitHub Advanced Security / VS Code
python3 scripts/codelens.py check /path/to/workspace --format sarif > codelens.sarif

# GraphML export — opens in Gephi/Cytoscape/yEd/Neo4j (issue #59 Phase 3)
python3 scripts/codelens.py scan /path/to/workspace --format graphml > codelens.graphml
python3 scripts/codelens.py trace main /path/to/workspace --format graphml > trace.graphml
python3 scripts/codelens.py impact my_function /path/to/workspace --format graphml > impact.graphml
python3 scripts/codelens.py circular /path/to/workspace --format graphml > cycles.graphml
```

### Plugin System

```bash
# List installed plugins
python3 scripts/codelens.py plugin list

# Built-in plugins (already shipped):
#   - owasp_top10  (36 OWASP Top 10 rules, A01-A10)
#   - compliance   (53 rules: PCI-DSS v4.0 + HIPAA Security Rule)

# Search registry (future marketplace)
python3 scripts/codelens.py plugin search "sql injection"
```

## Honest Competitive Positioning

CodeLens excels in **AI-native code intelligence** — a niche where MCP integration, guard hooks, and AI-optimized output matter most. Here is an honest assessment vs established tools:

| Dimension | CodeLens | SonarQube | CodeQL | Semgrep |
|-----------|:--------:|:---------:|:------:|:-------:|
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

**Our genuine strengths:** AI-native design, frontend analysis breadth, MCP integration, guard for AI workflows.

**Where we lag:** Community ecosystem, IDE marketplace presence, deep abstract interpretation (CodeQL's domain), enterprise CI/CD integrations.

**Our goal:** Be the best code intelligence tool for AI agent workflows, not a SonarQube replacement.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

MIT License — see [LICENSE.txt](LICENSE.txt)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history (top-level) and [references/changelog.md](references/changelog.md) for older per-version highlights.
