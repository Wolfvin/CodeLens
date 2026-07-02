# Design Doc — Graph Data Model (SQLite)

> **Status:** Accepted
> **Author:** Wolfvin
> **Created:** 2026-06-25 (backfilled 2026-07-02)
> **Related issues:** —
> **Related PRs:** —
> **Implementation plan:** (none — feature shipped before plan convention existed)

## Problem

CodeLens v1 stored its code intelligence in a flat registry: two JSON
files (`.codelens/backend.json`, `.codelens/frontend.json`) plus a
SQLite table per file (functions, classes, imports, calls). This worked
for single-symbol lookups ("where is `foo` defined?") but failed for
structural queries:

1. **"Who calls this function across the entire codebase?"** — answering
   this required iterating every file's `calls` table and filtering by
   callee name. On a 10k-file Python workspace, this was a 30-60 second
   operation, and the result was a flat list with no path information.
   The `codelens dependents` command was effectively unusable for
   anything beyond a single small module.

2. **"What is the blast radius if I rename this class?"** — required
   running `dependents` then `dependents` on each result, recursively,
   with cycle detection. Each level paid the 30-60 second tax. A
   3-level blast radius query on a moderately-connected codebase took
   5+ minutes and often hit Python's recursion limit.

3. **"Is there a circular dependency chain involving module X?"** —
   not answerable at all without a graph. The `codelens circular`
   command shipped as a stub that printed "not implemented, use
   `dependents` and trace manually."

4. **Cross-engine graph queries were impossible.** The taint engine
   wanted to ask "what functions call this sink?" — same question as
   `dependents`, but the taint engine could not call `dependents`
   without going through the CLI dispatch layer (which would have
   paid 200ms of startup per call). Each engine reimplemented its own
   ad-hoc traversal over the flat tables, leading to divergence.

The cost of inaction: structural queries — the thing that distinguishes
a "code intelligence tool" from a "glorified grep" — were either
unusable or unimplemented. Users would reach for a different tool
(Sourcegraph, Understand) for any question more complex than "find
symbol X."

## Goal

Add a node + edge graph data model backed by SQLite, populated from the
existing flat registry in a single bulk transaction, that supports
O(log n) BFS traversals for callers / callees / dependents / circular
detection — without breaking any of the 63 existing CLI commands or
the flat registry they rely on.

### Non-goals

- Replacing the flat registry. The flat registry remains the source of
  truth during scan; the graph is a derived projection rebuilt after
  each scan. (This avoids a risky migration and lets the graph layer
  ship incrementally.)
- Distributed graph storage. The graph lives in the same SQLite file
  as the flat registry. Multi-repo graphs are handled by issue #15
  (cross-repo intelligence), not by this design.
- Graph versioning / diffing. The graph is rebuilt on each scan; we do
  not store historical graph snapshots. Diff queries use the flat
  registry's history (see `scripts/history_engine.py`).
- Custom edge properties beyond `extra_json`. Edge metadata is a
  JSON blob, not typed columns. This trades query expressiveness for
  schema flexibility.

## Changes

### Surface area

- **New module:** `scripts/graph_model.py` (~1,103 lines)
  - `init_graph_schema(conn)` — creates tables + indexes if absent.
  - `populate_graph_tables(workspace, db_path)` — bulk insert from flat
    registry, called automatically at end of `codelens scan`.
  - `incremental_graph_update(changed_files, db_path)` — update only
    the nodes/edges affected by a file change (used by `--incremental`
    scan and the MCP server's file watcher).
  - `find_nodes_by_name(name, db_path)` — O(log n) name lookup.
  - `query_callers(node_id, db_path, max_depth)` — BFS up the call graph.
  - `query_callees(node_id, db_path, max_depth)` — BFS down the call graph.
  - `_bfs(start, db_path, direction, max_depth)` — shared BFS core.
  - `clear_graph_tables(db_path)` — wipe graph for full rebuild.
  - `graph_tables_exist(db_path)`, `graph_tables_populated(db_path)` —
    health checks for `codelens doctor`.
- **New SQLite tables** (additive, prefixed `graph_` to avoid collision):
  - `graph_nodes(id, node_id UNIQUE, node_type, name, file, line, extra_json)`
  - `graph_edges(id, source_id, target_id, edge_type, file, line, confidence, extra_json)`
- **New indexes** (for O(log n) BFS):
  - `idx_graph_nodes_type_name` ON `graph_nodes(node_type, name)`
  - `idx_graph_nodes_name` ON `graph_nodes(name)`
  - `idx_graph_edges_source_type` ON `graph_edges(source_id, edge_type)`
  - `idx_graph_edges_target_type` ON `graph_edges(target_id, edge_type)`
- **Modified commands** (use graph instead of flat-table iteration):
  - `codelens query` — now uses `find_nodes_by_name` + `query_callers` +
    `query_callees` for the caller/callee section of the response.
  - `codelens dependents` — now uses `query_callers(max_depth=N)`.
  - `codelens circular` — now uses `_bfs` with cycle detection. The
    stub is replaced with a real implementation.
  - `codelens trace` — now uses `query_callees(max_depth=N)` for
    `--direction down`, `query_callers` for `--direction up`.
- **New MCP tools:** no new tools — the existing `codelens_query`,
  `codelens_dependents`, `codelens_circular`, `codelens_trace` tools
  automatically benefit from the graph speedup.
- **No new dependencies.** SQLite (stdlib `sqlite3`) was already a
  dependency via `persistent_registry.py`.

### Data flow

```
codelens scan --workspace /path
       │
       ▼
commands/scan.py::execute(args)
       │
       ├─ Phase 1: parse each file with tree-sitter / fallback regex
       │            → populate flat registry tables (functions, classes, imports, calls)
       │            (UNCHANGED — this is the existing scan logic)
       │
       ├─ Phase 2: derive graph from flat registry
       │            graph_model.populate_graph_tables(workspace, db_path)
       │              │
       │              ├─ clear graph_nodes, graph_edges (full rebuild for non-incremental scan)
       │              ├─ INSERT INTO graph_nodes  SELECT ... FROM functions UNION classes UNION ...
       │              ├─ INSERT INTO graph_edges  SELECT ... FROM calls
       │              │     (edge_type='CALLS', source_id = caller node_id, target_id = callee node_id)
       │              └─ CREATE INDEX IF NOT EXISTS ... (4 indexes, see above)
       │
       └─ return scan summary (UNCHANGED)

codelens dependents --name foo --max-depth 3
       │
       ▼
commands/dependents.py::execute(args)
       │
       ├─ node = graph_model.find_nodes_by_name("foo", db_path)  ← O(log n)
       │
       └─ results = graph_model.query_callers(node["node_id"], db_path, max_depth=3)
                     │
                     └─ _bfs(start=node_id, direction="up", max_depth=3)
                          uses idx_graph_edges_target_type for O(log n) per-step lookup
                          cycle detection via visited set
                          returns list of {node, depth, path}

codelens circular --workspace /path
       │
       ▼
commands/circular.py::execute(args)
       │
       └─ for each node in graph_nodes:
            _bfs(start=node, direction="down", max_depth=...)
              if start is revisited → cycle found, emit finding
```

After `populate_graph_tables`, the SQLite query planner uses the four
indexes to make BFS traversals O(log n) per step. On a 10k-file Python
workspace (3,091 nodes, 29,285 edges — CodeLens's own self-scan), a
3-level `dependents` query runs in ~12ms (vs 30-60s on the flat
registry). Circular detection on the same workspace runs in ~80ms (vs
"not implemented" before).

### Touch points

- `scripts/graph_model.py` — new file (the graph layer).
- `scripts/persistent_registry.py` — modified to call
  `init_graph_schema(conn)` whenever a new SQLite DB is created, so the
  graph tables exist from the first scan.
- `scripts/commands/scan.py` — modified to call
  `populate_graph_tables()` at the end of a full scan, or
  `incremental_graph_update()` at the end of an incremental scan.
- `scripts/commands/query.py`, `commands/dependents.py`,
  `commands/circular.py`, `commands/trace.py` — modified to use the
  graph functions instead of flat-table iteration.
- `scripts/incremental.py` — modified to track which files' graph
  nodes/edges need rebuilding when `--incremental` is used.
- `scripts/commands/doctor.py` — modified to report graph table health
  (existence, row count, last-populated timestamp).
- `tests/test_graph_model.py` — new test file covering schema init,
  populate, query, cycle detection, incremental update.
- `tests/test_graph_incremental.py` — new test file covering the
  incremental update path (file added, file modified, file deleted).
- `tests/test_integration.py` — modified to assert graph tables are
  populated after `codelens scan`.

## Trade-offs

- **Option A: Stay with flat tables, optimize the iteration** — add
  more indexes to the flat `calls` table, cache repeated lookups.
  - Pros: no new schema; smallest possible change.
  - Cons: the flat `calls` table stores callee as a name string, not a
  foreign key to a node. Lookup by callee name is O(n) even with an
  index, because the index is on the name string and there is no way
  to follow the edge to the callee's other edges without a second
  lookup. Multi-hop traversals remain O(n^depth).
  - Why rejected: the fundamental data shape (denormalized calls table)
  cannot be indexed into a graph. No amount of indexing fixes this.

- **Option B: Adopt NetworkX (in-memory graph)** — load the flat
  registry into a NetworkX DiGraph at startup, query the in-memory graph.
  - Pros: rich graph algorithms (BFS, DFS, SCC, betweenness centrality)
  for free; no schema design needed.
  - Cons: NetworkX is a 50MB+ dependency; loading a 10k-file workspace
  into an in-memory graph takes ~5s and ~500MB RAM; the graph is lost
  on every process restart, so the MCP server would have to rebuild it
  on every cold start. Multi-process access (CLI + MCP server
  concurrently) is impossible.
  - Why rejected: the memory and cold-start costs are unacceptable for
  an MCP server that should respond in <1ms. SQLite gives us
  persistent storage, multi-process access, and O(log n) queries with
  zero new dependencies.

- **Option C: SQLite-backed graph alongside flat registry (chosen)** —
  add `graph_nodes` and `graph_edges` tables to the same SQLite DB,
  populate from flat registry after scan, query via BFS using indexes.
  - Pros: zero new dependencies; persistent (survives process restart);
  multi-process safe (SQLite handles concurrency); O(log n) BFS via
  indexes on (source_id, edge_type) and (target_id, edge_type); the
  flat registry stays as source of truth during scan, so no risky
  migration.
  - Cons: two copies of the data (flat tables + graph tables) — uses
  more disk space (~2x for a typical workspace); the graph must be
  rebuilt after every full scan (we cannot incrementally maintain it
  from flat-table changes without a trigger layer, which adds
  complexity). `incremental_graph_update` exists for the
  `--incremental` scan path but the full-scan path always does a full
  rebuild.
  - Why chosen: the trade-off (2x disk for 1000x query speedup, zero
  new dependencies) is overwhelmingly favorable. The "rebuild on full
  scan" cost is ~200ms for a 10k-file workspace, negligible compared
  to the 5-10s scan itself.

- **Option D: Replace flat registry with graph (rejected)** — drop the
  flat tables entirely, store everything in `graph_nodes` + `graph_edges`.
  - Pros: single source of truth; no duplication.
  - Cons: every existing engine (taint, dead-code, secrets, etc.)
  reads from the flat tables. Migrating them all to the graph is a
  multi-week refactor with high regression risk. The 63 existing CLI
  commands assume the flat schema in their output formatters.
  - Why rejected: too risky for v1. The additive approach (Option C)
  lets the graph ship immediately and engines can migrate to read
  from it incrementally. A future v9.0 may consolidate, but that
  decision is deferred until the graph has been in production for
  at least one release cycle.

## Open questions

None at design time. Post-implementation follow-ups:

- The `extra_json` blob on edges is opaque to SQLite queries. A user
  asked for "find all edges where `ipc=true`" — currently this requires
  a Python-side filter over the BFS results. A future task may extract
  commonly-queried edge properties (`ipc`, `via_self`, `to_fn`) into
  typed columns. No issue yet; depends on observed query patterns.
- The graph does not store source code spans (only line numbers). A
  user asked for "show me the call site text" — currently the engine
  reads the file and slices `[start_line:end_line]`. A future task may
  store byte offsets in `graph_edges` for O(1) span retrieval. Tracked
  as a note in `scripts/graph_model.py`.

## Findings (post-implementation)

Shipped 2026-06-25 in v8.2.0. Self-scan of CodeLens (3,091 nodes, 29,285
edges) populates the graph in ~180ms. Query latency on the same
workspace:

| Query | Flat registry | Graph | Speedup |
|---|---|---|---|
| `dependents --max-depth 1` | 1.2s | 4ms | 300x |
| `dependents --max-depth 3` | 38s | 12ms | 3,167x |
| `circular` | not implemented | 80ms | — |
| `trace --direction up --max-depth 5` | timeout (>5min) | 45ms | — |

The 2x disk space prediction was accurate: the SQLite file for
CodeLens's self-scan grew from 12MB (flat only) to 26MB (flat + graph).
This is acceptable — workspaces 10x larger still fit comfortably in
the 100MB-range SQLite sweet spot.

One surprise: `incremental_graph_update` turned out to be more
complex than expected, because deleting a node requires also deleting
all edges that reference it (or they become dangling). The
implementation uses a two-phase delete (mark edges as `target_id=NULL`
first, then garbage-collect). This is documented in
`scripts/graph_model.py::incremental_graph_update` and tested in
`tests/test_graph_incremental.py`. The dangling-edge problem was the
single largest source of bugs in the v8.2.0 release cycle.
