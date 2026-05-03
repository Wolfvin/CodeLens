# CodeLens v5 — Live Codebase Reference Intelligence

> **Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.**

CodeLens is a CLI tool that gives AI agents **full visibility** into a codebase before they write any code. It prevents collision, overwrite of existing logic, and dead code by scanning the workspace and building a real-time reference registry of every class, ID, function, and their relationships.

## Features

- **39 CLI Commands** — From basic scan/query to vulnerability scanning and performance hints
- **Tree-sitter Powered** — Accurate AST-based parsing for HTML, CSS, JS, TS/TSX, Rust, Python, Vue, Svelte, SCSS
- **Framework Auto-Detection** — React/Next.js, Vue, Svelte, Tailwind CSS, and more
- **Incremental Scanning** — Only re-parse changed files for speed
- **Workspace Auto-Detect** — No need to specify workspace path if you're already in the project
- **JSON Output** — All commands output structured JSON for easy programmatic consumption
- **Pre-write Safety** — Check if a class/id/function already exists before creating it
- **Impact Analysis** — Predict what breaks if you modify or delete a symbol
- **Security Auditing** — Detect hardcoded secrets, data flow taint analysis, CVE scanning
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

## Command Reference

### Core Commands (P0 — Always Use)

| Command | Description |
|---------|-------------|
| `init [workspace]` | Initialize .codelens config with auto-detected frameworks |
| `scan [workspace] [--incremental]` | Scan workspace and build registry |
| `query "name" [workspace] [--domain] [--file]` | Pre-write check: does this name already exist? |
| `list [workspace] [--domain] [--filter]` | List entries with filter (dead, collision, duplicate, etc.) |
| `detect [workspace]` | Detect frameworks and show recommended config |
| `watch [workspace]` | Start file watcher for real-time registry updates |

### Search & Understanding (P1)

| Command | Description |
|---------|-------------|
| `search "pattern" [workspace] [--type] [--context]` | Regex search across workspace |
| `symbols "name" [workspace] [--fuzzy]` | Search symbol in registry |
| `trace "name" [workspace] [--direction] [--depth]` | Deep call chain tracing |
| `impact "name" [workspace] [--action]` | Change impact analysis |
| `context "name" [workspace]` | Rich symbol context (definition, callers, callees) |
| `outline [workspace] [--file] [--all]` | File structure outline |
| `missing-refs [workspace]` | Detect CSS/HTML mismatches |
| `dependents "file" [workspace]` | Module-level import tracking |

### Quality & Security (P0-P1)

| Command | Description |
|---------|-------------|
| `secrets [workspace]` | Detect hardcoded API keys, passwords, tokens |
| `vuln-scan [workspace]` | Scan dependencies for known CVEs |
| `dataflow [workspace] [--source] [--sink]` | Data flow taint analysis |
| `env-check [workspace]` | Audit environment variables |
| `smell [workspace]` | Code smell detection with health score |
| `complexity [workspace]` | Cyclomatic/cognitive complexity scoring |
| `dead-code [workspace]` | Enhanced dead code detection |
| `debug-leak [workspace]` | Detect leftover debug code |

### Understanding & Architecture (P1)

| Command | Description |
|---------|-------------|
| `entrypoints [workspace]` | Map execution entry points |
| `api-map [workspace]` | Map REST/GraphQL routes to handlers |
| `state-map [workspace]` | Track global state management |
| `diff [workspace]` | Compare registry snapshots |
| `circular [workspace]` | Detect circular dependencies |
| `validate [workspace]` | Validate registry vs file system |

### Refactoring & Analysis (P2-P3)

| Command | Description |
|---------|-------------|
| `refactor-safe "name" [workspace]` | Pre-flight rename/move safety check |
| `side-effect [workspace] [--name]` | Pure vs impure function analysis |
| `stack-trace "name" [workspace]` | Error propagation simulation |
| `test-map [workspace]` | Test coverage mapping |
| `config-drift [workspace]` | Dependency drift detection |
| `type-infer [workspace]` | Lightweight type inference |
| `ownership [workspace]` | Git blame code ownership |
| `regex-audit [workspace]` | ReDoS-vulnerable regex auditing |
| `a11y [workspace]` | Accessibility auditing (WCAG 2.1) |
| `perf-hint [workspace]` | Performance anti-pattern detection |
| `css-deep [workspace]` | Deep CSS analysis |

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

## Supported Languages & Frameworks

**Languages:** HTML, CSS, SCSS, Less, JavaScript, TypeScript, TSX/JSX, Rust, Python, Vue SFC, Svelte

**Frameworks:** React/Next.js, Vue/Nuxt, Svelte/SvelteKit, Tailwind CSS, Express, Fastify, Koa, Hono, Django, Flask, FastAPI

**Package Managers:** npm, yarn, pnpm, bun, cargo, pip, go modules

## Architecture

```
codelens/
├── SKILL.md                    # Full documentation for AI agents
├── SKILL-QUICK.md              # Quick reference (concise)
├── README.md                   # This file
├── LICENSE.txt                 # MIT License
├── setup.sh                    # Dependency installer
├── skill.json                  # Metadata
├── references/                 # Detailed reference docs
│   ├── parser-rules.md         # Parsing rules per language
│   ├── query-examples.md       # Query usage examples
│   ├── status-codes.md         # Status & flag reference
│   ├── changelog.md            # Version changelog
│   └── agent-integration.md    # AI agent integration guide
└── scripts/
    ├── codelens.py             # CLI entry point (39 commands)
    ├── registry.py             # Registry read/write/build
    ├── base_parser.py          # Base tree-sitter parser
    ├── grammar_loader.py       # Lazy tree-sitter grammar loader
    ├── framework_detect.py     # Framework auto-detection
    ├── incremental.py          # Incremental scan support
    ├── edge_resolver.py        # Cross-file edge resolution
    ├── search_engine.py        # Regex code search
    ├── trace_engine.py         # Call chain tracing
    ├── impact_engine.py        # Change impact analysis
    ├── outline_engine.py       # File structure outline
    ├── missing_refs.py         # CSS/HTML mismatch detection
    ├── diff_engine.py          # Registry diff/snapshots
    ├── circular_engine.py      # Circular dependency detection
    ├── context_engine.py       # Rich symbol context
    ├── dependents_engine.py    # Module import tracking
    ├── validate_engine.py      # Registry validation
    ├── dataflow_engine.py      # Data flow taint analysis
    ├── smell_engine.py         # Code smell detection
    ├── sideeffect_engine.py    # Side-effect analysis
    ├── refactor_safe_engine.py # Refactoring safety check
    ├── deadcode_engine.py      # Enhanced dead code detection
    ├── stacktrace_engine.py    # Error propagation simulation
    ├── testmap_engine.py       # Test coverage mapping
    ├── configdrift_engine.py   # Dependency drift detection
    ├── typeinfer_engine.py     # Lightweight type inference
    ├── ownership_engine.py     # Git blame ownership
    ├── secrets_engine.py       # Hardcoded secret detection
    ├── entrypoints_engine.py   # Entry point mapping
    ├── apimap_engine.py        # API route mapping
    ├── statemap_engine.py      # State management tracking
    ├── envcheck_engine.py      # Environment variable audit
    ├── debugleak_engine.py     # Debug code leak detection
    ├── complexity_engine.py    # Complexity scoring
    ├── regexaudit_engine.py    # Regex auditing
    ├── a11y_engine.py          # Accessibility auditing
    ├── vulnscan_engine.py      # Vulnerability scanning
    ├── perfhint_engine.py      # Performance hints
    ├── cssdeep_engine.py       # Deep CSS analysis
    └── parsers/
        ├── __init__.py
        ├── html_parser.py      # Tree-sitter HTML parser
        ├── css_parser.py       # Tree-sitter CSS parser
        ├── js_frontend_parser.py # JS DOM selector parser
        ├── js_backend_parser.py  # JS function call graph parser
        ├── rust_parser.py      # Rust function call graph parser
        ├── tsx_parser.py       # TSX/JSX React component parser
        ├── vue_parser.py       # Vue SFC parser
        ├── svelte_parser.py    # Svelte component parser
        └── tailwind_detector.py # Tailwind utility analyzer
```

## Requirements

- Python 3.8+
- tree-sitter + language grammars (auto-installed by setup.sh)
- watchdog (optional, for file watching)
- git (optional, for ownership analysis)

## Installation

```bash
# Clone the repository
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens/skills/codelens

# Run setup
bash setup.sh

# Verify
python3 scripts/codelens.py --help
```

## Integration with AI Agents

CodeLens is designed to be used by AI coding agents. The full integration guide is in [references/agent-integration.md](references/agent-integration.md).

**Key principle:** Before an AI writes any new class, ID, or function, it MUST query CodeLens first to check for collisions, overwrites, and dead code.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Security

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities.

## License

MIT License — see [LICENSE.txt](LICENSE.txt)

## Changelog

See [references/changelog.md](references/changelog.md) for version history.
