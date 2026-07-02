# Design Doc 0004: Graph Data Model

> **Status:** Accepted
> **Date:** 2026-06-08 (retroactive — backfilled 2026-07-02)
> **Author:** Wolfvin
> **Related issues:** #8 (graph backend for trace), #59 (graphml export)
> **Related PRs:** original v8.2 implementation, #153 (graphml)

---

## Problem

CodeLens v8.0-v8.1 used a flat registry: two JSON files (`backend.json` and
`frontend.json`) containing arrays of nodes and edges. Every structural
query — "who calls this function?", "what's the blast radius of renaming
this class?", "are there circular dependencies?" — required iterating the
full edge list (O(n) where n = 495k edges on a large codebase).

This had three problems:

1. **Performance** — `trace` on a 30k-node codebase took 8-12s because
   every hop scanned the full edge list. Agents timed out.
2. **No index** — repeated queries re-scanned the same data. There was no
   way to ask "give me the adjacency list for node X" without building it
   on the fly.
3. **No transactional updates** — incremental scans rewrote the entire
   JSON file. A crash mid-write could corrupt the registry.

## Goal

Introduce a proper graph data model that:
- Backs structural queries (trace, impact, circular, dependents) with
  indexed lookups → <100ms per hop on a 30k-node graph
- Lives alongside the flat registry (non-breaking) — all 70 existing
  commands continue to work unchanged
- Supports incremental updates (only changed files re-parsed, graph
  patched in a single transaction)
- Persists to SQLite for crash safety and concurrent read access

## Changes

### Architecture

```
scan (full or incremental)
    │
    ▼
Flat registry (backend.json / frontend.json)  ← source of truth during scan
    │
    ▼ (single bulk transaction)
SQLite database (.codelens/codelens.db)
    ├── graph_nodes table  (one row per symbol: file:line:fn)
    └── graph_edges table  (one row per call/import/define/inherit edge)
         + indexes on source_id, target_id, edge_type
```

### Schema

```sql
graph_nodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id      TEXT NOT NULL UNIQUE,  -- matches flat registry "id" (file:line:fn)
    node_type    TEXT NOT NULL,          -- function|class|file|module|route|type|interface
    name         TEXT NOT NULL,          -- symbol name (flat registry "fn")
    file         TEXT,
    line         INTEGER,
    extra_json   TEXT                    -- preserves original "type", "status", etc.
)

graph_edges (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL,          -- references graph_nodes.node_id
    target_id    TEXT,                   -- NULL for unresolved external calls
    edge_type    TEXT NOT NULL,          -- CALLS|IMPORTS|DEFINES|INHERITS|IMPLEMENTS|USES_TYPE
    file         TEXT,                   -- file where the edge originates
    line         INTEGER,                -- line where the edge originates
    confidence   REAL NOT NULL DEFAULT 1.0,
    extra_json   TEXT                    -- preserves "ipc", "via_self", "to_fn", etc.
)
```

### Indexes

- `idx_graph_nodes_name` — for `find_nodes_by_name()` (symbol search)
- `idx_graph_edges_source` — for `query_callees()` (forward traversal)
- `idx_graph_edges_target` — for `query_callers()` (reverse traversal)
- `idx_graph_edges_type` — for filtering by edge type

### New Files

- `scripts/graph_model.py` — schema, population, incremental update, BFS
  queries (~1100 lines)
- `scripts/edge_resolver.py` — cached adjacency index (O(1) caller/callee
  lookups during BFS)
- `scripts/commands/graph_schema.py` — CLI command for schema introspection

### Modified Files

- `scripts/trace_engine.py` — uses graph backend by default, falls back to
  flat registry if graph tables are empty (issue #8)
- `scripts/impact_engine.py` — uses graph for dependents lookup
- `scripts/circular_engine.py` — uses graph for cycle detection
- `scripts/persistent_registry.py` — manages the SQLite database lifecycle

### Query API

```python
# Find all nodes matching a name (case-insensitive, fuzzy)
find_nodes_by_name(name, db_path) -> List[Dict]

# BFS traversal — callers (who calls this node?)
query_callers(node_id, db_path, max_depth=1) -> List[Dict]

# BFS traversal — callees (what does this node call?)
query_callees(node_id, db_path, max_depth=1) -> List[Dict]

# Stats for diagnostics
graph_stats(db_path) -> {"nodes": int, "edges": int}
```

## Trade-offs

### Alternative A: Keep flat JSON, add in-memory index

- **Pros:** No schema migration, no SQLite dependency
- **Cons:** Still need to load the full JSON into memory on every startup
  (~1.5s for 30k nodes), no transactional updates, no concurrent access
- **Why rejected:** The fundamental problem was re-scanning on every
  startup. An in-memory index doesn't solve persistence or crash safety.

### Alternative B: NetworkX graph persisted via pickle

- **Pros:** Rich graph algorithms (PageRank, centrality) for free
- **Cons:** Pickle is not crash-safe (corrupt on partial write), no
  concurrent read access, NetworkX is a heavy dependency, algorithms
  are O(n) in memory when SQLite indexes give O(log n) on disk
- **Why rejected:** Crash safety and concurrency are hard requirements.
  Pickle fails both. NetworkX is also a large dependency for a feature
  that only needs BFS.

### Alternative C: Neo4j or external graph database

- **Pros:** Purpose-built graph database, query language (Cypher)
- **Cons:** External process to manage, network latency, license
  (Neo4j Community is GPL), overkill for the query patterns CodeLens needs
- **Why rejected:** CodeLens is a single-process CLI tool. Requiring users
  to run Neo4j would massively raise the installation barrier. SQLite is
  already a dependency (for `persistent_registry`) and is zero-config.

### Chosen approach: SQLite tables with indexes

- **Why:** SQLite is already a dependency, zero-config, crash-safe (WAL
  mode), supports concurrent reads, and indexed lookups give O(log n)
  performance. The flat registry remains the source of truth during scan;
  the graph is populated from it in a single bulk transaction. This is
  non-breaking by design — all 70 existing commands work unchanged, and
  `trace_engine` falls back to the flat registry if the graph tables are
  empty.

## Open Questions

- [x] Q1: Should the graph replace the flat registry entirely? —
  **Resolved**: no. The flat registry is the scan output format (JSON,
  human-readable, diff-friendly). The graph is a derived index for
  structural queries. They serve different purposes.
- [x] Q2: How to handle incremental updates? — **Resolved**: issue #8
  Phase 2 added `incremental_graph_update()` which patches only changed
  nodes/edges in a single transaction.
- [ ] Q3: Should we add a Cypher-like query language? — **Open**, tracked
  in issue #9. A Cypher-subset engine was implemented in PR #149/#151
  but is not yet merged as of 2026-07-02.

## Migration / Rollout

The graph tables are additive — `graph_nodes` and `graph_edges` are
prefixed to avoid colliding with any existing table name. The flat
registry tables and JSON files are untouched. Users who never run `scan`
after upgrading to v8.2 see no change (the graph tables are simply empty;
`trace_engine` falls back to the flat registry).

The first `scan` after upgrading to v8.2 populates the graph tables
automatically — no manual migration step.

## References

- Issue: #8 (graph backend for trace — bidirectional fallback)
- Issue: #59 (graphml export — Phase 3 reads from `graph_nodes`/`graph_edges`)
- Issue: #9 (Cypher-like query engine — not yet merged)
- Prior art: Sourcegraph's code graph, GitHub's code navigation (tree-sitter
  + stack graphs)
- Related design docs: [0002-mcp-server](0002-mcp-server.md) (the server
  queries this graph), [0001-taint-engine](0001-taint-engine.md) (taint
  engine uses `edge_resolver` for inter-procedural flow)
