# Task: Create WebSocket Mini-Service for CodeLens Neural Workspace

## Agent: Main Agent
## Status: COMPLETED

## Summary
Created the `codelens-ws` WebSocket mini-service at `/home/z/my-project/mini-services/codelens-ws/` that acts as the real-time bridge between the CodeLens Neural Workspace frontend and the CodeLens CLI.

## Files Created

### 1. `/home/z/my-project/mini-services/codelens-ws/package.json`
- Package: `codelens-ws@1.0.0`
- Script: `bun --hot index.ts` for hot-reload development
- Dependency: `socket.io@^4.7.0`

### 2. `/home/z/my-project/mini-services/codelens-ws/index.ts`
Full WebSocket server implementation (~550 lines) with:

#### Server Setup
- Port: **3030**
- socket.io with CORS enabled (`origin: "*"`)
- Path: `/` (required by Caddy gateway)
- Graceful shutdown handlers for SIGTERM/SIGINT

#### In-Memory Graph State
- `graphNodes: GraphNode[]` — all nodes in the workspace
- `graphEdges: GraphEdge[]` — all edges between nodes
- `graphClusters: Cluster[]` — auto-detected brain regions
- `lastWorkspace: string | null` — last scanned workspace path

#### Client → Server Handlers

**`command` handler:**
1. Executes CodeLens CLI via `Bun.spawn` with 60s timeout
2. Parses JSON output from stdout
3. Normalizes result into `GraphEvent` using command-specific normalizers
4. Updates in-memory graph (replace for scan, incremental for others)
5. Emits `graph_event` to client
6. For `scan`, also emits `graph_init` with full graph

**`select_node` handler:**
1. Computes `NodeDetail` from in-memory graph
2. Looks up callers, callees, references, definedIn from edges
3. Falls back to async CLI query if node not in memory
4. Emits `node_detail` back to client

**`viewport` handler:**
- Receives viewport bounds (reserved for LOD optimization)

**Connection handler:**
- On connect, emits `graph_init` if graph data exists in memory

#### Server → Client Messages
- `graph_init` — full graph state (nodes + edges)
- `graph_event` — incremental event with animation
- `node_detail` — detail panel data for selected node
- `command_result` — raw CLI output

#### Normalizer Logic

**`normalizeScan`:**
- Creates nodes from frontend classes (`.name`) and ids (`#name`)
- Creates nodes from backend functions with file node grouping
- Creates `defines` edges from file → function
- Creates `references` edges from JS → CSS class/id
- Auto-detects clusters via REGION_PATTERNS

**`normalizeQuery`:**
- Highlights matching node + connections
- Creates caller/callee edges for backend functions
- Pulse animation on result

**`normalizeTrace`:**
- Builds edge chain from trace steps
- Flow animation with direction support

**`normalizeImpact`:**
- Marks target as `critical`, affected as `warning`
- Alarm/ripple animation based on risk level

**`normalizeGeneric`:**
- Pass-through for other commands
- Flash animation on any found IDs

#### Color Palette
- Mirrors `NEURAL_COLORS` from `src/types/neural.ts`
- Type-based colors + status overrides

#### Cluster Auto-Detection
- 11 region patterns (Auth, UI, API, State, Utils, Tests, Styles, Config, Data, Hooks, Services)
- Auto-assigns nodes to clusters based on label/file path

## Verification
- Server starts successfully on port 3030
- `bun install` completed (socket.io@4.8.3 installed)
- `bun run dev` launches with hot-reload

## Connection from Frontend
Frontend should connect via:
```typescript
import { io } from 'socket.io-client'
const socket = io('/?XTransformPort=3030')
```
