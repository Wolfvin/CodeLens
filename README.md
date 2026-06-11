# CodeLens — Live Codebase Reference Intelligence

CodeLens is a backend developer tool that scans your codebase using tree-sitter AST parsing and exposes structured JSON data via a REST API and WebSocket interface. It provides 41 analysis commands covering code search, call tracing, impact analysis, security auditing, quality scoring, and refactoring safety — all powered by a Python CLI that outputs machine-readable JSON. Connect any client (AI agent, editor plugin, custom dashboard) to consume real-time codebase intelligence.

---

## Prerequisites

- **Python 3.10+** with `tree-sitter` and `tree-sitter-languages` installed
- **Node.js 18+** or **Bun** (for the API server)
- **SQLite** (bundled, no separate install needed)
- A virtual environment with tree-sitter bindings (run `bash skills/codelens/setup.sh` once)

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/Wolfvin/CodeLens.git
cd CodeLens

# 2. Copy and edit the environment config
cp .env.example .env
# Edit .env — at minimum set CODELENS_PYTHON and CODELENS_SCRIPT:
#   CODELENS_PYTHON=/path/to/your/venv/bin/python3
#   CODELENS_SCRIPT=./skills/codelens/scripts/codelens.py

# 3. Install dependencies
bun install   # or: npm install

# 4. Install tree-sitter (one-time)
bash skills/codelens/setup.sh

# 5. Start the dev server
bun run dev
```

The API server starts on **port 3000**. The WebSocket server runs on **port 3030**.

---

## API Endpoints

### `GET /api/graph?workspace=/path/to/project`

Runs a full scan of the workspace and returns normalized graph data — nodes, edges, clusters, health score, coupling, and heatmap. This is the primary endpoint for fetching the complete codebase graph.

**Example request:**

```bash
curl "http://localhost:3000/api/graph?workspace=/home/user/my-project"
```

**Example response:**

```json
{
  "nodes": [
    {
      "id": "be_fn_handleAuth",
      "label": "handleAuth",
      "type": "function",
      "domain": "backend",
      "status": "active",
      "file": "src/auth.ts",
      "line": 42,
      "clusterId": "api",
      "radius": 8,
      "color": "#63b3ed",
      "data": { "refCount": 3, "async": true }
    }
  ],
  "edges": [
    {
      "id": "e_1_m1abc",
      "source": "be_fn_handleAuth",
      "target": "be_fn_validateToken",
      "type": "calls",
      "weight": 2,
      "status": "active"
    }
  ],
  "clusters": [
    {
      "id": "api",
      "label": "API",
      "icon": "📡",
      "tint": "#63b3ed",
      "nodeIds": ["be_fn_handleAuth", "be_fn_validateToken"],
      "cohesion": 0.85
    }
  ],
  "healthScore": {
    "overall": 78,
    "quality": 82,
    "security": 65,
    "coverage": 60,
    "dependency": 90,
    "architecture": 75,
    "maintainability": 80
  },
  "coupling": [
    { "nodeId": "be_fn_handleAuth", "inDegree": 3, "outDegree": 5, "instability": 0.63 }
  ],
  "heatmap": [
    { "nodeId": "be_fn_handleAuth", "score": 0.89, "factors": ["high-fan-out", "async-complexity"] }
  ]
}
```

### `POST /api/command`

Execute any of the 39 CodeLens CLI commands and receive a normalized `GraphEvent` in response. This is the general-purpose command endpoint.

**Example request:**

```bash
curl -X POST http://localhost:3000/api/command \
  -H "Content-Type: application/json" \
  -d '{"command": "trace", "args": ["--direction", "up"], "workspace": "/home/user/my-project"}'
```

**Example response:**

```json
{
  "sourceCommand": "trace",
  "timestamp": 1749500000000,
  "nodes": [
    { "id": "be_fn_validateToken", "label": "validateToken", "type": "function", "domain": "backend", "status": "active", "data": {} }
  ],
  "edges": [
    { "id": "e_2_m2def", "source": "be_fn_handleAuth", "target": "be_fn_validateToken", "type": "calls", "weight": 2, "status": "active" }
  ],
  "animation": {
    "type": "flow",
    "targetNodeIds": ["be_fn_validateToken"],
    "direction": "up",
    "speed": 1.5,
    "intensity": "high"
  },
  "metadata": {
    "riskLevel": "low",
    "category": "trace",
    "summary": "Traced 3 nodes from \"validateToken\""
  }
}
```

### `GET /api/health?workspace=/path/to/project`

Returns codebase health metrics: overall score (0–100), per-dimension breakdown, coupling analysis, hotspot heatmap, and optional impact radius for a specific node.

**Query parameters:**
- `workspace` (required) — absolute path to the project
- `nodeId` (optional) — compute impact radius for this node

**Example request:**

```bash
curl "http://localhost:3000/api/health?workspace=/home/user/my-project&nodeId=be_fn_handleAuth"
```

**Example response:**

```json
{
  "healthScore": {
    "overall": 78,
    "quality": 82,
    "security": 65,
    "coverage": 60,
    "dependency": 90,
    "architecture": 75,
    "maintainability": 80
  },
  "coupling": [
    { "nodeId": "be_fn_handleAuth", "inDegree": 3, "outDegree": 5, "instability": 0.63 }
  ],
  "heatmap": [
    { "nodeId": "be_fn_handleAuth", "score": 0.89, "factors": ["high-fan-out"] }
  ],
  "impactRadius": {
    "nodeId": "be_fn_handleAuth",
    "directCount": 5,
    "transitiveCount": 12,
    "riskLevel": "medium"
  },
  "timestamp": 1749500000000
}
```

---

## WebSocket Events

The WebSocket server (socket.io on port 3030) streams real-time graph updates. Connect with any socket.io client.

### `command`

Send a CLI command through the WebSocket. The server executes it, normalizes the result, and broadcasts a `graph_event` to all connected clients.

**Client emits:**

```json
{
  "command": "scan",
  "args": ["/home/user/my-project"]
}
```

**Server responds with `command_result`:**

```json
{
  "command": "scan",
  "result": { "frontend": { "classes": [], "ids": [] }, "backend": { "nodes": [], "edges": [] } }
}
```

### `graph_init`

Broadcast when a scan completes or on client connection (if graph data exists). Contains the full graph state.

**Payload:**

```json
{
  "nodes": [ { "id": "be_fn_handleAuth", "label": "handleAuth", ... } ],
  "edges": [ { "source": "be_fn_handleAuth", "target": "be_fn_validateToken", ... } ]
}
```

### `graph_event`

Broadcast after any command execution. Contains incremental updates as a `GraphEvent` with nodes, edges, animation hints, and metadata.

**Payload:**

```json
{
  "event": {
    "sourceCommand": "impact",
    "timestamp": 1749500000000,
    "nodes": [ { "id": "be_fn_handleAuth", "status": "critical", ... } ],
    "edges": [ { "source": "be_fn_handleAuth", "target": "be_fn_validateToken", ... } ],
    "animation": { "type": "alarm", "targetNodeIds": ["be_fn_handleAuth"], "intensity": "critical" },
    "metadata": { "riskLevel": "critical", "category": "impact", "summary": "3 nodes affected, risk=critical" }
  }
}
```

### `node_detail`

Sent in response to a `select_node` event. Contains rich context for a specific node: callers, callees, references, side effects, complexity, and more.

**Client emits:**

```json
{ "node_id": "be_fn_handleAuth" }
```

**Server responds with `node_detail`:**

```json
{
  "node_id": "be_fn_handleAuth",
  "detail": {
    "node": { "id": "be_fn_handleAuth", "label": "handleAuth", "type": "function", ... },
    "callers": [ { "fn": "main", "file": "src/index.ts", "line": 10 } ],
    "callees": [ { "fn": "validateToken", "file": "src/auth.ts", "line": 55 } ],
    "complexity": 7,
    "purity": 0.4,
    "sideEffects": ["writes: session.cookie"]
  }
}
```

---

## 41 CLI Commands

### Core

| Command | Description |
|---------|-------------|
| `init` | Initialize `.codelens` config in a workspace |
| `scan` | Scan workspace and build the node/edge registry |
| `query` | Look up a symbol by name and return its details |
| `list` | List registry entries with optional domain/type filter |
| `detect` | Auto-detect frameworks used in the workspace |
| `watch` | Watch for file changes, re-scan with debounce, generate outline.json + summary.json |
| `handbook` | Generate project handbook for AI agents (identity, structure, health, conventions, risks) |
| `ask` | Natural language query router — ask a question, CodeLens routes to the right command |

### Search & Trace (P1)

| Command | Description |
|---------|-------------|
| `search` | Search code patterns across the workspace |
| `symbols` | Search registry symbols by name (supports fuzzy) |
| `trace` | Trace a symbol's call chain (up/down/bidirectional) |
| `impact` | Analyze change impact for a symbol |
| `dependents` | Module-level import tracking |
| `stack-trace` | Error propagation simulation |
| `query` | Look up a specific symbol by name |

### Outline & Diff (P2)

| Command | Description |
|---------|-------------|
| `outline` | Get file structure outline |
| `missing-refs` | Detect CSS/HTML selector mismatches |
| `diff` | Compare registry snapshots |
| `circular` | Detect circular dependencies |

### Context & Analysis (P3)

| Command | Description |
|---------|-------------|
| `context` | Get rich symbol context (callers, callees, refs) |
| `validate` | Validate registry against file system |
| `test-map` | Test coverage mapping |
| `config-drift` | Dependency drift detection |
| `type-infer` | Lightweight type inference |
| `ownership` | Git blame code ownership analysis |
| `entrypoints` | Map execution entry points |
| `api-map` | Map REST/GraphQL routes to handlers |
| `state-map` | Track global state management |

### Security

| Command | Description |
|---------|-------------|
| `secrets` | Detect hardcoded secrets and API keys |
| `vuln-scan` | Dependency vulnerability scanning (CVE database) |
| `dataflow` | Data flow analysis (source to sink, taint detection) |
| `env-check` | Audit environment variables |
| `regex-audit` | Detect ReDoS-vulnerable regex patterns |

### Quality

| Command | Description |
|---------|-------------|
| `smell` | Code smell detection (10 categories) |
| `complexity` | Cyclomatic/cognitive complexity scoring |
| `debug-leak` | Detect leftover debug code |
| `dead-code` | Enhanced dead code detection |
| `a11y` | Accessibility auditing (WCAG 2.1) |

### Performance & CSS

| Command | Description |
|---------|-------------|
| `perf-hint` | Performance anti-pattern detection |
| `css-deep` | Deep CSS analysis (unused vars, specificity wars, z-index abuse) |

### Refactoring

| Command | Description |
|---------|-------------|
| `refactor-safe` | Pre-flight rename/move safety check |
| `side-effect` | Function side-effect analysis (pure vs impure) |

---

## Running Dev vs Production

### Development

```bash
# Terminal 1: API server (port 3000)
bun run dev

# Terminal 2: WebSocket server (port 3030)
cd mini-services/codelens-ws && bun run index.ts
```

### Production

```bash
# Build and start the API server
bun run build
bun run start

# WebSocket server (background or via process manager)
cd mini-services/codelens-ws && NODE_ENV=production bun run index.ts
```

### Reverse Proxy (Caddy)

The included `Caddyfile` proxies port 81 to the Next.js server on 3000, with WebSocket support via the `XTransformPort` query parameter:

```
:81 {
    handle {
        reverse_proxy localhost:3000
    }
}
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CODELENS_PYTHON` | **Yes** | — | Path to Python 3 with tree-sitter installed |
| `CODELENS_SCRIPT` | **Yes** | — | Path to `codelens.py` CLI script |
| `CODELENS_WS_PORT` | No | `3030` | WebSocket server port |
| `CORS_ORIGIN` | No | `*` | Allowed origin(s) for CORS |
| `DATABASE_URL` | No | `file:./db/custom.db` | SQLite database path |
| `NODE_ENV` | No | — | `development` or `production` |

---

## Project Structure

```
CodeLens/
├── src/
│   ├── app/api/          # REST API routes (graph, command, health)
│   │   ├── graph/route.ts
│   │   ├── command/route.ts
│   │   └── health/route.ts
│   ├── lib/              # Core backend logic
│   │   ├── commandRunner.ts   # CLI command execution + whitelist
│   │   ├── normalizer.ts      # CLI JSON → GraphEvent normalizer
│   │   ├── clusterEngine.ts   # Auto-clustering logic
│   │   ├── healthScore.ts     # Health/coupling/heatmap scoring
│   │   ├── graphStore.ts      # In-memory graph store
│   │   ├── graphDiff.ts       # Graph diff computation
│   │   ├── analysisStore.ts   # Analysis result cache
│   │   ├── db.ts              # Prisma/SQLite connection
│   │   └── utils.ts           # Shared utilities
│   └── types/
│       └── neural.ts          # Unified type system
├── mini-services/
│   └── codelens-ws/      # Socket.io WebSocket server
│       └── index.ts
├── skills/codelens/       # CodeLens Python CLI (v5.1)
│   ├── scripts/           # 39 command engines + parsers
│   ├── tests/             # Python unit tests
│   └── setup.sh           # One-time tree-sitter setup
├── __tests__/             # Backend integration tests
├── db/                    # SQLite database
├── .env.example           # Environment variable template
└── next.config.ts         # Next.js config (standalone output)
```

---

## Watch Mode (File Watcher)

The `watch` command monitors your workspace for file changes, re-scans automatically, and generates AI-friendly output files. It uses debounce to coalesce rapid changes and prints a clean one-line summary instead of raw JSON.

```bash
# Watch with default 0.5s debounce
python3 skills/codelens/scripts/codelens.py watch /path/to/project

# Custom debounce interval
python3 skills/codelens/scripts/codelens.py watch /path/to/project --debounce 1.0

# Short flag
python3 skills/codelens/scripts/codelens.py watch /path/to/project -d 2.0
```

**Terminal output (clean one-line summary):**
```
[CodeLens] Scanning /path/to/project...
[14:32:01] ✓ 87 files | 312 funcs | 45 classes | 203 nodes | 156 edges
[CodeLens] Watching /path/to/project (debounce: 0.5s) — Press Ctrl+C to stop
  Changed: src/auth.ts
[14:32:15] ✓ 87 files | 314 funcs | 45 classes | 205 nodes | 158 edges | 1 changed
```

**Generated output files** (in `.codelens/`):
- `.codelens/outline.json` — per-file detail (functions, classes, imports, exports)
- `.codelens/summary.json` — aggregate totals (file count, function count, language breakdown, node/edge counts)

---

## License

See [skills/codelens/LICENSE.txt](skills/codelens/LICENSE.txt).
