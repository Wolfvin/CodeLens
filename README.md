# CodeLens v5 — Live Codebase Reference Intelligence

> Before an AI writes a new class/id/function, CodeLens must be checked. This is not optional.

CodeLens is a multi-modal codebase intelligence platform that combines **AST-level parsing** (tree-sitter), **39 analysis commands**, and a **Neural Workspace visualization** to give developers and AI agents real-time insight into code structure, security, quality, and refactoring safety.

---

## Table of Contents

- [What is CodeLens?](#what-is-codelens)
- [Architecture](#architecture)
- [Four Usage Modes](#four-usage-modes)
  - [1. Neural Workspace UI](#1-neural-workspace-ui)
  - [2. CLI Interactive](#2-cli-interactive)
  - [3. CLI for Coders](#3-cli-for-coders)
  - [4. Agents (AI Integration)](#4-agents-ai-integration)
- [39 Commands Reference](#39-commands-reference)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Contributing](#contributing)
- [License](#license)

---

## What is CodeLens?

CodeLens solves a critical problem in modern development: **blind coding**. When developers or AI agents write code without knowing what already exists, they create duplicate classes, collide with existing IDs, overwrite active functions, and leave dead code behind.

CodeLens provides **pre-write collision detection**, **deep call chain tracing**, **security auditing**, **quality scoring**, and **refactoring safety checks** — all powered by tree-sitter AST parsing across 10 programming languages.

### Key Capabilities

| Category | Count | Examples |
|----------|-------|---------|
| **Languages Parsed** | 10 | HTML, CSS, JS, TS/TSX, Vue, Svelte, Rust, Python, SCSS, Tailwind |
| **Core Commands** | 6 | init, scan, query, list, detect, watch |
| **P1: Search & Trace** | 8 | search, symbols, trace, impact, dependents, stack-trace, query, list |
| **P2: Outline & Diff** | 4 | outline, missing-refs, diff, circular |
| **P3: Context & Analysis** | 10 | context, validate, test-map, config-drift, type-infer, ownership, entrypoints, api-map, state-map |
| **Security** | 5 | secrets, vuln-scan, dataflow, env-check, regex-audit |
| **Quality** | 5 | smell, complexity, debug-leak, dead-code, a11y |
| **Performance** | 1 | perf-hint |
| **CSS Deep** | 1 | css-deep |
| **Refactoring** | 2 | refactor-safe, side-effect |
| **Total Commands** | **39** | |
| **Health Analysis** | 6 dimensions | Quality, Security, Coverage, Dependency, Architecture, Maintainability |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CodeLens Platform                      │
├──────────┬──────────┬──────────┬────────────────────────┤
│ Neural   │  CLI     │  CLI     │  Agents                │
│ Workspace│  Inter-  │  for     │  (AI Skill             │
│ UI       │  active  │  Coders  │  Integration)          │
│          │          │          │                         │
│ Next.js  │  Python  │  Python  │  SKILL.md +            │
│ Canvas2D │  TUI     │  CLI     │  trigger maps          │
│ D3-force │  Rich    │  JSON    │  auto-chains           │
│ Zustand  │  output  │  output  │  fallback chains       │
├──────────┴──────────┴──────────┴────────────────────────┤
│              WebSocket + REST API Layer                    │
│              (socket.io :3030 / Next.js API :3000)        │
├──────────────────────────────────────────────────────────┤
│              CodeLens Python CLI (v5.1.0)                 │
│              39 commands · 9 tree-sitter parsers          │
│              24 analysis engines · registry persistence    │
├──────────────────────────────────────────────────────────┤
│              .codelens/ (Registry Cache)                   │
│              frontend.json · backend.json · mtimes.json   │
│              codelens.config.json · snapshots/             │
└──────────────────────────────────────────────────────────┘
```

---

## Four Usage Modes

### 1. Neural Workspace UI

The **Neural Workspace** is an interactive brain-like visualization of your entire codebase. Built with Canvas2D + D3-force, it renders your code as a living neural network where every class, function, component, and route is a neuron connected by dependency synapses.

**Features:**
- **7 Node Shapes**: Class (diamond/amber), ID (circle/coral), Function (hexagon/blue), Component (triangle/purple), Store (star/gold), File (square/teal), Package (ring/pink)
- **16 Node Types**: class, id, function, component, store, file, package, route, env_var, variable, secret, vulnerability, test, import, css_var, keyframe
- **15 Edge Types**: references, calls, imports, defines, depends_on, routes_to, reads, writes, contains, extends, implements, taints, sanitizes, tests, imports_from
- **3-Layer Auto-Clustering**: File Boundary (50%), Import Density (35%), Semantic Signal (15%)
- **6 Animation Types**: pulse, flow, ripple, flash, death, alarm
- **Dark/Light Themes**: Neural Night (#0a0a0f) / Neural Day (#f7fafc)
- **Export**: PNG 2x/4x, SVG
- **9 Sidebar Tabs**: Commands, Workspace, Security, Quality, Performance, CSS, P1, P2/P3, Refactoring
- **Slide-in Panel**: Node detail, code preview, quick actions
- **Command Palette**: Ctrl+K for fuzzy search across all 39 commands
- **Real-time**: WebSocket updates when code changes
- **LOD System**: Cluster → File → Symbol zoom levels
- **Health Score Engine**: Composite 0-100 score across 6 dimensions (Quality 25%, Security 20%, Coverage 20%, Dependency 15%, Architecture 10%, Maintainability 10%) with letter grades A+ through F and actionable recommendations
- **Coupling Heatmap**: Fan-In/Fan-Out analysis with instability metrics, identifying the most tightly-coupled modules in your codebase
- **Impact Radius**: BFS-based dependency depth analysis showing how many nodes would be affected if a specific node changes, grouped by depth level
- **Graph Diff Engine**: Track changes between scans — added/removed/modified nodes and edges, change coupling detection, and risk assessment for breaking changes
- **Semantic Search (TF-IDF)**: Beyond simple string matching — uses term frequency-inverse document frequency scoring with camelCase/snake_case tokenization, status-aware boosting, and prefix/fuzzy matching
- **Heatmap Visualization**: SLOC/Fan-Out-based heat scoring (inspired by Emerge) identifying the hottest, most concerning nodes in your codebase

**Access:**
```bash
npm run dev
# Open http://localhost:3000
```

**How It Works:**
1. On load, the UI fetches graph data from `/api/graph?workspace=...`
2. Nodes are positioned using D3-force simulation (charge, collision, link forces)
3. Canvas2D renders with viewport culling, DPI awareness, and passive wheel zoom
4. Selecting a node opens the SlideInPanel with detail, callers, callees, and quick actions
5. Sidebar tabs execute CLI commands and display results in context

---

### 2. CLI Interactive

The **CLI Interactive** mode is a terminal-first experience for developers who prefer keyboard-driven workflows. It provides the same 39 commands with human-readable, color-coded output.

**Usage:**
```bash
python3 skills/codelens/scripts/codelens.py <command> [workspace] [options]
```

**Workspace Auto-Detect (v5.1):** If you omit the workspace argument, CodeLens auto-detects it by walking up from the current directory to find `package.json`, `pyproject.toml`, `Cargo.toml`, or source files.

**Interactive Examples:**
```bash
# Initialize workspace
python3 codelens.py init                    # Auto-detect workspace

# Full scan — see all classes, IDs, functions, components
python3 codelens.py scan

# Incremental scan — only changed files
python3 codelens.py scan --incremental

# Query before creating a new class/function
python3 codelens.py query "btn-primary"
# → found: true, status: active → DO NOT recreate, extend existing
# → found: false → Safe to create

# Trace a call chain
python3 codelens.py trace "verify_token" --direction both --depth 5

# Check change impact
python3 codelens.py impact "processPayment" --action modify

# Security audit
python3 codelens.py secrets
python3 codelens.py vuln-scan --severity critical
python3 codelens.py dataflow --source user_input --sink db_query

# Quality check
python3 codelens.py smell --severity critical
python3 codelens.py complexity --threshold 20
python3 codelens.py dead-code

# Performance
python3 codelens.py perf-hint --category n_plus_one

# CSS deep analysis
python3 codelens.py css-deep --category z_index_abuse

# Refactoring safety
python3 codelens.py refactor-safe "verify_token" --action rename --new-name "validate_token"
python3 codelens.py side-effect --name processOrder
```

**Output Format:** Human-readable terminal output with color coding. All commands also support JSON output for piping.

---

### 3. CLI for Coders

The **CLI for Coders** mode outputs structured JSON, designed for scripting, CI/CD pipelines, and editor integration. Every command returns a consistent JSON envelope.

**Usage:**
```bash
python3 skills/codelens/scripts/codelens.py <command> [workspace] [options]
# Output is automatically JSON when piped or when stdout is not a TTY
```

**JSON Output Format:**
```json
{
  "status": "ok",
  "command": "query",
  "result": {
    "found": true,
    "name": "btn-primary",
    "type": "class",
    "domain": "frontend",
    "status": "active",
    "ref_count": 5,
    "defined_in": ["src/styles/buttons.css:15"],
    "referenced_by": ["Button.tsx", "Modal.tsx", "Dashboard.tsx"]
  }
}
```

**CI/CD Integration:**
```yaml
# GitHub Actions example
- name: CodeLens Security Gate
  run: |
    python3 codelens.py secrets ./src
    python3 codelens.py vuln-scan ./src --severity critical
    python3 codelens.py debug-leak ./src
```

**Pre-commit Hook:**
```bash
#!/bin/bash
# .git/hooks/pre-commit
python3 codelens.py scan --incremental
python3 codelens.py secrets
python3 codelens.py dead-code
```

**API Route Integration:**
The Next.js app exposes three REST endpoints:
- `GET /api/graph?workspace=/path` — Full workspace graph (nodes + edges + clusters + health score + coupling + heatmap)
- `GET /api/health?workspace=/path` — Codebase health score, coupling heatmap, and recommendations (optional `nodeId` param for impact radius)
- `POST /api/command` — Execute any CLI command, returns normalized GraphEvent

```bash
# Fetch full graph
curl "http://localhost:3000/api/graph?workspace=/home/user/myproject"

# Execute a command
curl -X POST http://localhost:3000/api/command \
  -H "Content-Type: application/json" \
  -d '{"command": "secrets", "args": [], "workspace": "/home/user/myproject"}'
```

---

### 4. Agents (AI Integration)

CodeLens is designed as an **AI skill** with automatic trigger detection, fallback chains, and composite workflows. When integrated into an AI agent, CodeLens activates automatically based on user intent.

**Skill File:** `skills/codelens/SKILL.md`

**Auto-Trigger Examples:**

| User Says | CodeLens Auto-Activates |
|-----------|------------------------|
| "Create a new Button component" | `query "Button"` → check collision |
| "Is this secure?" | `secrets` → `dataflow` → `env-check` → `vuln-scan` |
| "Can I rename this?" | `refactor-safe` → `impact` → `test-map` |
| "Why is this slow?" | `perf-hint` → `complexity` → `circular` |
| "What's dead code?" | `dead-code` → `list --filter dead` |
| "Deploy check" | `secrets` → `debug-leak` → `env-check` → `config-drift` → `vuln-scan` → `dead-code` |
| "How does this app work?" | `entrypoints` → `api-map` → `state-map` |

**Pre-Write Flow (Mandatory):**
```
AI wants to create/edit/delete code
          │
          ▼
1. Registry exists? → No: init + scan
          │
          ▼
2. query "name" → Check collision
          │
          ├─ found: false → Proceed
          ├─ found: active → EXTEND, don't overwrite
          ├─ found: dead → Ask user
          └─ found: collision → STOP. Fix first.
          │
          ▼
3. Write code
          │
          ▼
4. scan --incremental → Update registry
```

**Composite Scenario Chains:**

| Scenario | Chain |
|----------|-------|
| Bug investigation | search → context → trace → missing-refs |
| Pre-deploy gate | secrets → debug-leak → env-check → config-drift → vuln-scan → dead-code |
| Onboarding | entrypoints → api-map → state-map → outline |
| Performance audit | perf-hint → complexity → circular → side-effect |
| CSS cleanup | css-deep → missing-refs → list --filter duplicate_define |

**Negative Triggers (When NOT to activate CodeLens):**
- Document generation ("generate PDF", "create report")
- Image/media generation ("generate image", "create artwork")
- Non-codebase questions ("what is React", "explain SQL")
- UI design tasks ("design a layout") — unless checking existing code

---

## 39 Commands Reference

### Core Commands

| # | Command | Description | Args |
|---|---------|-------------|------|
| 1 | `init` | Initialize .codelens config | `[workspace]` |
| 2 | `scan` | Scan workspace, build registry | `[workspace] [--incremental]` |
| 3 | `query` | Pre-write collision check | `<name> [workspace] [--domain] [--file]` |
| 4 | `list` | List entries with filter | `[workspace] [--domain] [--filter]` |
| 5 | `detect` | Detect frameworks | `[workspace]` |
| 6 | `watch` | File watcher for live updates | `[workspace]` |

### P1: Search & Trace

| # | Command | Description | Args |
|---|---------|-------------|------|
| 7 | `search` | Regex search across workspace | `<pattern> [workspace] [--type] [--file]` |
| 8 | `symbols` | Search registry by symbol name | `<name> [workspace] [--domain] [--fuzzy]` |
| 9 | `trace` | Deep call chain tracing | `<name> [workspace] [--direction] [--depth]` |
| 10 | `impact` | Change impact analysis | `<name> [workspace] [--action]` |
| 11 | `dependents` | Module-level import tracking | `<file> [workspace] [--direction]` |
| 12 | `stack-trace` | Error propagation simulation | `<name> [workspace] [--error-type]` |

### P2: Outline & Diff

| # | Command | Description | Args |
|---|---------|-------------|------|
| 13 | `outline` | File structure outline | `[workspace] [--file] [--all]` |
| 14 | `missing-refs` | CSS/HTML mismatch detection | `[workspace]` |
| 15 | `diff` | Registry snapshot diff | `[workspace] [--snapshot1] [--snapshot2]` |
| 16 | `circular` | Circular dependency detection | `[workspace] [--domain]` |

### P3: Context & Validation

| # | Command | Description | Args |
|---|---------|-------------|------|
| 17 | `context` | Rich symbol context | `<name> [workspace] [--no-code]` |
| 18 | `validate` | Registry vs filesystem check | `[workspace]` |
| 19 | `test-map` | Test coverage mapping | `[workspace] [--function]` |
| 20 | `config-drift` | Dependency drift detection | `[workspace]` |
| 21 | `type-infer` | Lightweight type inference | `[workspace] [--function] [--file]` |
| 22 | `ownership` | Git blame code ownership | `[workspace] [--file] [--function]` |
| 23 | `entrypoints` | Execution entry point mapping | `[workspace] [--type]` |
| 24 | `api-map` | REST/GraphQL route mapping | `[workspace] [--method] [--path]` |
| 25 | `state-map` | Global state tracking | `[workspace] [--store]` |

### Security

| # | Command | Description | Args |
|---|---------|-------------|------|
| 26 | `secrets` | Hardcoded secret detection | `[workspace] [--severity]` |
| 27 | `vuln-scan` | Dependency CVE scanning | `[workspace] [--severity]` |
| 28 | `dataflow` | Taint analysis (source→sink) | `[workspace] [--source] [--sink]` |
| 29 | `env-check` | Environment variable audit | `[workspace] [--var]` |
| 30 | `regex-audit` | ReDoS and regex auditing | `[workspace] [--severity]` |

### Quality

| # | Command | Description | Args |
|---|---------|-------------|------|
| 31 | `smell` | Code smell detection | `[workspace] [--categories] [--severity]` |
| 32 | `complexity` | Cyclomatic/cognitive complexity | `[workspace] [--name] [--threshold]` |
| 33 | `debug-leak` | Debug code leak detection | `[workspace] [--category]` |
| 34 | `dead-code` | Enhanced dead code detection | `[workspace] [--categories]` |
| 35 | `a11y` | Accessibility auditing | `[workspace] [--category] [--severity]` |

### Performance

| # | Command | Description | Args |
|---|---------|-------------|------|
| 36 | `perf-hint` | Performance anti-patterns | `[workspace] [--category] [--severity]` |

### CSS

| # | Command | Description | Args |
|---|---------|-------------|------|
| 37 | `css-deep` | Deep CSS analysis | `[workspace] [--category] [--severity]` |

### Refactoring

| # | Command | Description | Args |
|---|---------|-------------|------|
| 38 | `refactor-safe` | Pre-flight rename/move check | `<name> [workspace] [--action] [--new-name]` |
| 39 | `side-effect` | Function side effect analysis | `[workspace] [--name] [--file]` |

---

## Installation

### Prerequisites

- **Node.js** 18+ (for Neural Workspace UI)
- **Python** 3.10+ (for CLI)
- **Bun** (for WebSocket microservice)
- **Git** (for ownership analysis)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/your-org/codelens.git
cd codelens

# 2. Install Node.js dependencies
npm install

# 3. Setup CodeLens Python CLI
bash skills/codelens/setup.sh

# 4. Start the Neural Workspace UI
npm run dev

# 5. (Optional) Start the WebSocket microservice
cd mini-services/codelens-ws
bun install
bun run index.ts
```

### Environment Variables

Create a `.env` file in the project root:

```env
# CodeLens CLI path (auto-detected if not set)
CODELENS_PATH=/path/to/python3 /path/to/codelens/scripts/codelens.py

# WebSocket port (default: 3030)
CODELENS_WS_PORT=3030
```

---

## Quick Start

### Using the Neural Workspace UI

1. Open `http://localhost:3000`
2. Set your workspace path in the sidebar Workspace tab
3. Click **Full Scan** to build the registry
4. Explore the neural graph — click nodes for detail, use sidebar tabs for analysis
5. Press **Ctrl+K** for the command palette

### Using the CLI

```bash
# Navigate to your project
cd /path/to/your/project

# Initialize and scan
python3 /path/to/codelens/scripts/codelens.py init
python3 /path/to/codelens/scripts/codelens.py scan

# Check before creating a new function
python3 /path/to/codelens/scripts/codelens.py query "myFunction"
# → found: false → Safe to create!

# Run security audit
python3 /path/to/codelens/scripts/codelens.py secrets
python3 /path/to/codelens/scripts/codelens.py vuln-scan

# Check code quality
python3 /path/to/codelens/scripts/codelens.py smell
python3 /path/to/codelens/scripts/codelens.py complexity
```

---

## Tech Stack

### Neural Workspace UI
| Layer | Technology |
|-------|-----------|
| Framework | Next.js 16, React 19 |
| Rendering | Canvas2D, D3-force |
| State | Zustand |
| Styling | Tailwind CSS 4, shadcn/ui |
| Animation | Framer Motion |
| Real-time | socket.io-client |
| Charts | Recharts |
| Code Display | react-syntax-highlighter |

### CLI Engine
| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.10+ |
| Parsing | tree-sitter (9 language grammars) |
| Fallback | Regex-based parsers |
| Registry | JSON file persistence (.codelens/) |
| Incremental | mtime-based change detection |

### WebSocket Server
| Layer | Technology |
|-------|-----------|
| Runtime | Bun |
| Protocol | socket.io |
| Port | 3030 |

---

## Project Structure

```
codelens/
├── src/                              # Next.js Neural Workspace
│   ├── app/
│   │   ├── api/
│   │   │   ├── graph/route.ts        # GET /api/graph — full graph + health + coupling + heatmap
│   │   │   ├── health/route.ts       # GET /api/health — health score + recommendations
│   │   │   └── command/route.ts      # POST /api/command — execute CLI
│   │   ├── globals.css               # Premium glassmorphic design system
│   │   ├── layout.tsx                # Root layout
│   │   └── page.tsx                  # Main Neural Workspace page
│   ├── components/
│   │   ├── canvas/NeuralCanvas.tsx   # Canvas2D + D3-force (~1570 lines)
│   │   ├── panel/SlideInPanel.tsx    # 400px slide-in detail panel
│   │   ├── sidebar/                  # 9 tabs + CommandPalette
│   │   ├── topbar/TopBar.tsx         # Fixed glassmorphic header
│   │   ├── bottom/ResultPanel.tsx    # Tabbed result viewer
│   │   └── ui/                       # 42 shadcn/ui components
│   ├── lib/
│   │   ├── analysisStore.ts          # Zustand store (730 lines)
│   │   ├── commandRunner.ts          # CLI executor (39 wrappers + command whitelist + arg sanitization)
│   │   ├── normalizer.ts             # CLI JSON → GraphEvent normalizer
│   │   ├── graphStore.ts             # In-memory graph CRUD + TF-IDF semantic search
│   │   ├── clusterEngine.ts          # 3-layer auto-clustering (Union-Find)
│   │   ├── healthScore.ts            # Codebase health score engine (6 dimensions + coupling + heatmap + impact radius)
│   │   ├── graphDiff.ts              # Graph diff/change tracking + change coupling + risk assessment
│   │   ├── demoData.ts               # Demo data for offline mode
│   │   └── utils.ts                  # cn() utility
│   └── types/
│       └── neural.ts                 # Unified type system (354 lines)
│
├── skills/codelens/                  # CodeLens CLI Skill
│   ├── SKILL.md                      # AI skill documentation (900+ lines)
│   ├── skill.json                    # Skill metadata
│   ├── setup.sh                      # Python venv + tree-sitter setup
│   ├── scripts/
│   │   ├── codelens.py              # Main CLI entry (916+ lines)
│   │   ├── base_parser.py           # Tree-sitter base parser
│   │   ├── registry.py              # Config + data persistence
│   │   ├── grammar_loader.py        # Grammar management
│   │   ├── framework_detect.py      # Framework detection
│   │   ├── incremental.py           # Incremental scan engine
│   │   ├── edge_resolver.py         # Call graph resolution
│   │   ├── parsers/                 # 10 language parsers
│   │   │   ├── js_frontend_parser.py
│   │   │   ├── js_backend_parser.py
│   │   │   ├── tsx_parser.py
│   │   │   ├── css_parser.py
│   │   │   ├── html_parser.py
│   │   │   ├── rust_parser.py
│   │   │   ├── vue_parser.py
│   │   │   ├── svelte_parser.py
│   │   │   ├── tailwind_detector.py
│   │   │   └── python_parser (via base_parser)
│   │   └── [24 analysis engines]    # secrets, vuln-scan, dataflow, etc.
│   └── references/                  # 5 reference docs
│
├── mini-services/codelens-ws/        # WebSocket microservice
│   ├── index.ts                      # socket.io server (1118 lines)
│   └── package.json
│
└── .codelens/                        # Registry cache (auto-generated)
    ├── frontend.json                 # CSS class/ID registry
    ├── backend.json                  # Function/component registry
    ├── mtimes.json                   # File modification times
    ├── codelens.config.json          # Framework config
    └── snapshots/                    # Timestamped snapshots
```

---

## Contributing

We welcome contributions! Here are areas where help is needed:

1. **Additional Language Parsers** — Go, Java, Kotlin, Swift, C#
2. **Editor Extensions** — VS Code, Neovim, JetBrains
3. **CI/CD Templates** — GitHub Actions, GitLab CI, Jenkins
4. **Test Coverage** — Unit tests for all 24 analysis engines
5. **Performance** — WebWorker for Canvas2D rendering, WASM for tree-sitter

### Development Setup

```bash
# Install dependencies
npm install

# Run CodeLens setup
bash skills/codelens/setup.sh

# Start development server
npm run dev

# Run CLI directly
python3 skills/codelens/scripts/codelens.py scan .
```

---

## Credits & Acknowledgments

CodeLens wouldn't exist without these incredible open-source projects. Huge thanks to all the maintainers and contributors!

### Core Engine

| Project | Repository | How We Use It |
|---------|-----------|---------------|
| **tree-sitter** | [tree-sitter/tree-sitter](https://github.com/tree-sitter/tree-sitter) | AST parsing engine — the foundation of CodeLens' accurate code analysis |
| **tree-sitter-html** | [tree-sitter/tree-sitter-html](https://github.com/tree-sitter/tree-sitter-html) | HTML grammar for parsing HTML structure, ids, and classes |
| **tree-sitter-css** | [tree-sitter/tree-sitter-css](https://github.com/tree-sitter/tree-sitter-css) | CSS grammar for selector, property, and @keyframes analysis |
| **tree-sitter-javascript** | [tree-sitter/tree-sitter-javascript](https://github.com/tree-sitter/tree-sitter-javascript) | JavaScript grammar for frontend/backend JS parsing |
| **tree-sitter-typescript** | [tree-sitter/tree-sitter-typescript](https://github.com/tree-sitter/tree-sitter-typescript) | TypeScript/TSX grammar for React component analysis |
| **tree-sitter-rust** | [tree-sitter/tree-sitter-rust](https://github.com/tree-sitter/tree-sitter-rust) | Rust grammar for function, impl, and trait parsing |
| **tree-sitter-python** | [tree-sitter/tree-sitter-python](https://github.com/tree-sitter/tree-sitter-python) | Python grammar for def, class, and import parsing |

### Neural Workspace UI

| Project | Repository | How We Use It |
|---------|-----------|---------------|
| **Next.js** | [vercel/next.js](https://github.com/vercel/next.js) | React framework powering the Neural Workspace web application |
| **React** | [facebook/react](https://github.com/facebook/react) | UI rendering library for all workspace components |
| **D3-force** | [d3/d3-force](https://github.com/d3/d3-force) | Force-directed graph layout for neural node positioning |
| **shadcn/ui** | [shadcn-ui/ui](https://github.com/shadcn-ui/ui) | Beautiful, accessible UI components used across all panels and tabs |
| **Tailwind CSS** | [tailwindlabs/tailwindcss](https://github.com/tailwindlabs/tailwindcss) | Utility-first CSS framework for rapid styling |
| **Zustand** | [pmndrs/zustand](https://github.com/pmndrs/zustand) | Lightweight state management for graph, analysis, and UI state |
| **Framer Motion** | [motiondivision/motion](https://github.com/motiondivision/motion) | Smooth animations for panels, transitions, and micro-interactions |
| **Recharts** | [recharts/recharts](https://github.com/recharts/recharts) | Chart library for quality/security/performance visualizations |
| **react-syntax-highlighter** | [react-syntax-highlighter/react-syntax-highlighter](https://github.com/react-syntax-highlighter/react-syntax-highlighter) | Code syntax highlighting in the slide-in detail panel |
| **Lucide React** | [lucide-icons/lucide](https://github.com/lucide-icons/lucide) | Icon library for all sidebar, toolbar, and action icons |
| **cmdk** | [pacocoursey/cmdk](https://github.com/pacocoursey/cmdk) | Command palette component (Ctrl+K) for fast command access |
| **socket.io** | [socketio/socket.io](https://github.com/socketio/socket.io) | Real-time WebSocket communication between CLI and UI |

### Tools & Infrastructure

| Project | Repository | How We Use It |
|---------|-----------|---------------|
| **Bun** | [oven-sh/bun](https://github.com/oven-sh/bun) | Fast JavaScript runtime for the WebSocket microservice |
| **Prisma** | [prisma/prisma](https://github.com/prisma/prisma) | ORM for potential database-backed registry persistence |
| **ESLint** | [eslint/eslint](https://github.com/eslint/eslint) | Code quality linting for the Next.js codebase |
| **TypeScript** | [microsoft/TypeScript](https://github.com/microsoft/TypeScript) | Type safety across the entire Neural Workspace codebase |

### Inspiration

These projects and ideas inspired CodeLens' design:

| Project | Repository | Inspiration |
|---------|-----------|-------------|
| **Sourcegraph** | [sourcegraph/sourcegraph](https://github.com/sourcegraph/sourcegraph) | Code intelligence and cross-reference navigation |
| **SonarQube** | [SonarSource/sonarqube](https://github.com/SonarSource/sonarqube) | Code quality gates and smell detection patterns |
| **Snyk** | [snyk/snyk](https://github.com/snyk/snyk) | Vulnerability scanning and dependency audit approach |
| **React DevTools** | [facebook/react](https://github.com/facebook/react) | Component tree visualization and state inspection |
| **AST Explorer** | [fkling/astexplorer](https://github.com/fkling/astexplorer) | Interactive AST visualization that guided our tree-sitter integration |
| **Dependency Cruiser** | [sverweij/dependency-cruiser](https://github.com/sverweij/dependency-cruiser) | Dependency graph visualization and circular dependency detection |

### Competitor Analysis & Feature Inspiration

We studied these excellent tools while building CodeLens v5. Their ideas helped shape our health score engine, coupling analysis, semantic search, and graph diff features:

| Project | Repository | Features That Inspired Us |
|---------|-----------|--------------------------|
| **Axon** | [harshkedia177/axon](https://github.com/harshkedia177/axon) | Graph-powered code intelligence with knowledge graph, health score dashboard, coupling heatmap, dead code report, Cypher query console, and MCP tools for AI agents — inspired our health score engine, coupling analysis, and impact radius features |
| **Emerge** | [glato/emerge](https://github.com/glato/emerge) | Interactive codebase visualization with SLOC/Fan-Out heatmap, Louvain modularity clustering, TF-IDF semantic search, git-based change coupling, and D3-force graph — inspired our heatmap, TF-IDF semantic search, and change coupling detection |
| **CodeGraph** | [ChrisRoyse/CodeGraph](https://github.com/ChrisRoyse/CodeGraph) | Neo4j-based code intelligence with multi-language AST analysis, cross-language dependency tracking, and MCP integration — inspired our graph diff engine and multi-language approach |
| **CodeLandscapeViewer** | [glenwrhodes/CodeLandscapeViewer](https://github.com/glenwrhodes/CodeLandscapeViewer) | Interactive force-directed graph with Code Insight panel showing dependency chains, impact radius, deepest path analysis, and semantic detection of endpoints/models/services — inspired our impact radius and dependency depth computation |
| **CodeAtlas** | [lucyb0207/CodeAtlas](https://github.com/lucyb0207/CodeAtlas) | GitHub repo → interactive dependency graph with AST parsing, focus mode, depth control, and Monaco Editor code preview — inspired our depth-limited tracing and code preview features |
| **CodeVisualizer** | [DucPhamNgoc08/CodeVisualizer](https://github.com/DucPhamNgoc08/CodeVisualizer) | VS Code extension for interactive dependency graphs with module connection analysis — inspired our VS Code extension roadmap |
| **codebase-health-score** | [glue-tools-ai/codebase-health-score](https://github.com/glue-tools-ai/codebase-health-score) | Composite health score calculation from complexity, docs, tests, deps, and collaboration metrics — inspired our 6-dimension health score breakdown |

---

Thank you to every open-source contributor who makes tools like CodeLens possible. You rock! 🙌

---

## License

MIT License — see [LICENSE](./skills/codelens/LICENSE.txt) for details.

---

**CodeLens v5.2.0** — Built with tree-sitter, Canvas2D, D3-force, Next.js, and love for clean code.
