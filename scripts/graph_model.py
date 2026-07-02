"""
Graph Data Model for CodeLens — true node + edge graph backed by SQLite.

This module introduces a proper graph data model (nodes + edges) that lives
ALONGSIDE the existing flat registry (backend.json / frontend.json). The flat
registry remains the source of truth during scan; this graph is populated from
it in a single bulk transaction so engines can issue structural graph queries
("who calls this function across the entire codebase", "blast radius if I
rename this class", "circular dependency chains") without reimplementing
ad-hoc traversal logic.

NON-BREAKING by design:
- New tables `graph_nodes` and `graph_edges` are additive (prefixed `graph_`
  to avoid colliding with any existing table name).
- The flat registry tables and JSON files are untouched.
- All 78 existing CLI commands continue to work unchanged.

Schema:
    graph_nodes(
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id         TEXT NOT NULL UNIQUE,   -- matches flat registry node "id" (file:line:fn)
        node_type       TEXT NOT NULL,          -- function|class|file|module|route|type|interface
        name            TEXT NOT NULL,          -- symbol name (flat registry "fn")
        file            TEXT,
        line            INTEGER,
        extra_json      TEXT                    -- preserves original "type", "status", etc.
    )

    graph_edges(
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id       TEXT NOT NULL,          -- references graph_nodes.node_id
        target_id       TEXT,                   -- NULL for unresolved external calls
        edge_type       TEXT NOT NULL,          -- CALLS|IMPORTS|DEFINES|INHERITS|IMPLEMENTS|USES_TYPE
        file            TEXT,                   -- file where the edge originates
        line            INTEGER,                -- line where the edge originates
        confidence      REAL NOT NULL DEFAULT 1.0,
        extra_json      TEXT                    -- preserves "ipc", "via_self", "to_fn", etc.
    )

Indexes (for O(log n) BFS lookups):
    idx_graph_nodes_type_name      ON graph_nodes(node_type, name)
    idx_graph_nodes_name           ON graph_nodes(name)
    idx_graph_edges_source_type    ON graph_edges(source_id, edge_type)
    idx_graph_edges_target_type    ON graph_edges(target_id, edge_type)
"""

import json
import os
import sqlite3
from collections import deque
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from utils import default_db_path, logger


# ─── Schema Constants ─────────────────────────────────────────

GRAPH_NODES_TABLE = "graph_nodes"
GRAPH_EDGES_TABLE = "graph_edges"

# Node types (per issue #8 spec)
NODE_TYPE_FUNCTION = "function"
NODE_TYPE_CLASS = "class"
NODE_TYPE_FILE = "file"
NODE_TYPE_MODULE = "module"
NODE_TYPE_ROUTE = "route"
NODE_TYPE_TYPE = "type"
NODE_TYPE_INTERFACE = "interface"
# Dependency vulnerability node (issue #158: deps-audit stores findings as
# graph nodes linked to the lock file that contained the vulnerable package).
NODE_TYPE_DEPENDENCY_VULN = "dependency_vuln"

# Edge types (per issue #8 spec)
EDGE_TYPE_CALLS = "CALLS"
EDGE_TYPE_IMPORTS = "IMPORTS"
EDGE_TYPE_DEFINES = "DEFINES"
EDGE_TYPE_INHERITS = "INHERITS"
EDGE_TYPE_IMPLEMENTS = "IMPLEMENTS"
EDGE_TYPE_USES_TYPE = "USES_TYPE"
# Edge from a file node to a dependency_vuln node (issue #158). The source is
# the lock file / manifest path, the target is the vuln node_id.
EDGE_TYPE_HAS_VULN = "HAS_VULN"

# Map flat-registry node "type" values to graph node_type.
# Anything not in this map defaults to NODE_TYPE_FUNCTION.
_FLAT_TYPE_TO_NODE_TYPE: Dict[str, str] = {
    "function": NODE_TYPE_FUNCTION,
    "method": NODE_TYPE_FUNCTION,
    "component": NODE_TYPE_FUNCTION,  # React component is still a function
    "class": NODE_TYPE_CLASS,
    "interface": NODE_TYPE_INTERFACE,
    "type": NODE_TYPE_TYPE,
    "pinia_store": NODE_TYPE_MODULE,
    "module": NODE_TYPE_MODULE,
    "route": NODE_TYPE_ROUTE,
}


# ─── SQL Statements ───────────────────────────────────────────

_CREATE_GRAPH_NODES = """
CREATE TABLE IF NOT EXISTS {table} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL UNIQUE,
    node_type   TEXT NOT NULL DEFAULT 'function',
    name        TEXT NOT NULL,
    file        TEXT,
    line        INTEGER,
    extra_json  TEXT
)
""".format(table=GRAPH_NODES_TABLE)

_CREATE_GRAPH_EDGES = """
CREATE TABLE IF NOT EXISTS {table} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    target_id   TEXT,
    edge_type   TEXT NOT NULL DEFAULT 'CALLS',
    file        TEXT,
    line        INTEGER,
    confidence  REAL NOT NULL DEFAULT 1.0,
    extra_json  TEXT
)
""".format(table=GRAPH_EDGES_TABLE)

_CREATE_GRAPH_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_type_name "
    "ON {t}(node_type, name)".format(t=GRAPH_NODES_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_name "
    "ON {t}(name)".format(t=GRAPH_NODES_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_graph_nodes_file "
    "ON {t}(file)".format(t=GRAPH_NODES_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_source_type "
    "ON {t}(source_id, edge_type)".format(t=GRAPH_EDGES_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_target_type "
    "ON {t}(target_id, edge_type)".format(t=GRAPH_EDGES_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_graph_edges_type "
    "ON {t}(edge_type)".format(t=GRAPH_EDGES_TABLE),
]


# ─── Schema Initialization ────────────────────────────────────

def init_graph_schema(conn: sqlite3.Connection) -> None:
    """Create graph_nodes + graph_edges tables and indexes if they don't exist.

    Safe to call repeatedly (CREATE TABLE IF NOT EXISTS). Called automatically
    by PersistentRegistry during database initialization so the graph tables
    always exist by the time any engine tries to query them.

    Args:
        conn: An open sqlite3.Connection. Caller owns the connection and is
              responsible for committing/closing.
    """
    try:
        conn.execute(_CREATE_GRAPH_NODES)
        conn.execute(_CREATE_GRAPH_EDGES)
        for idx_sql in _CREATE_GRAPH_INDEXES:
            conn.execute(idx_sql)
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"graph_model schema init error: {e}")


# ─── Population ───────────────────────────────────────────────

# Single source of truth for the default db path lives in utils.default_db_path
# (see issue #40). The private alias below is kept for backward compatibility
# with tests and callers that import ``graph_model._default_db_path`` directly;
# it delegates to the canonical helper so logic never drifts.
_default_db_path = default_db_path


def _parse_file_line_from_node_id(node_id: str) -> Tuple[str, int]:
    """Extract (file, line) from a flat-registry node id like 'path/file.py:42:fn_name'.

    Returns ("", 0) if the format doesn't match. Handles multi-colon formats
    (Rust, C++) where the file path itself may contain colons on Windows.
    """
    if not node_id or ":" not in node_id:
        return ("", 0)
    parts = node_id.split(":")
    if len(parts) >= 3:
        # file:line:name — rejoin everything except last two parts as the file path
        file_part = ":".join(parts[:-2])
        try:
            line_part = int(parts[-2])
        except (ValueError, TypeError):
            line_part = 0
        return (file_part, line_part)
    return (parts[0], 0)


def _map_node_type(flat_type: str) -> str:
    """Map a flat-registry node 'type' value to a graph node_type.

    Args:
        flat_type: The value of node['type'] from the flat registry. May be
                   any string produced by the parsers (function, method, class,
                   component, pinia_store, etc.).

    Returns:
        One of the NODE_TYPE_* constants. Defaults to 'function' for unknown
        types so we never insert NULL or empty node_type values.
    """
    if not flat_type:
        return NODE_TYPE_FUNCTION
    return _FLAT_TYPE_TO_NODE_TYPE.get(flat_type, NODE_TYPE_FUNCTION)


def clear_graph_tables(db_path: str) -> None:
    """Delete all rows from graph_nodes and graph_edges.

    Used before re-populating so re-scans don't accumulate duplicate rows.
    Runs both deletes in a single transaction.

    Args:
        db_path: Absolute path to the SQLite database file.
    """
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM {}".format(GRAPH_EDGES_TABLE))
        conn.execute("DELETE FROM {}".format(GRAPH_NODES_TABLE))
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"clear_graph_tables error: {e}")
        conn.rollback()
    finally:
        conn.close()


def populate_graph_tables(workspace: str, db_path: Optional[str] = None) -> Dict[str, int]:
    """Populate graph_nodes + graph_edges from the flat backend registry.

    Reads `.codelens/backend.json` (the flat registry) and bulk-inserts all
    nodes and edges into the graph tables in a single transaction. Existing
    graph rows are cleared first (via clear_graph_tables) so re-scans produce
    no duplicates.

    Population is additive to the SQLite database only — the flat JSON registry
    is never modified. If backend.json doesn't exist or is empty, this is a
    no-op returning zero counts.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
                 `<workspace>/.codelens/codelens.db`.

    Returns:
        Dict with keys 'nodes' and 'edges' giving the number of rows inserted.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)

    # Lazy import to avoid circular dependency at module load time.
    from registry import load_backend_registry

    backend = load_backend_registry(workspace)
    flat_nodes = backend.get("nodes", [])
    flat_edges = backend.get("edges", [])

    if not flat_nodes and not flat_edges:
        # Nothing to populate. Still clear stale rows from a previous scan.
        clear_graph_tables(db_path)
        return {"nodes": 0, "edges": 0}

    # Ensure the schema exists (idempotent — safe if PersistentRegistry already
    # created the tables during scan).
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)
    except sqlite3.Error:
        # init_graph_schema already logged; continue anyway
        pass

    node_rows: List[Tuple[Any, ...]] = []
    for node in flat_nodes:
        node_id = node.get("id", "")
        if not node_id:
            continue  # skip malformed nodes without an id
        name = node.get("fn", node.get("name", ""))
        flat_type = node.get("type", "function")
        node_type = _map_node_type(flat_type)
        file_val = node.get("file", "")
        line_val = node.get("line", 0)
        # Preserve original fields that engines may still want (status, async, etc.)
        extra_keys = {k: v for k, v in node.items()
                      if k not in ("id", "fn", "name", "type", "file", "line")}
        extra_json = json.dumps(extra_keys, default=str) if extra_keys else None
        node_rows.append((node_id, node_type, name, file_val, line_val, extra_json))

    edge_rows: List[Tuple[Any, ...]] = []
    for edge in flat_edges:
        source_id = edge.get("from", "")
        if not source_id:
            continue  # skip malformed edges
        target_id = edge.get("to")  # may be None for unresolved
        to_fn = edge.get("to_fn", "")
        resolved = edge.get("resolved")
        via_self = edge.get("via_self", False)
        ipc = edge.get("ipc", False)

        # Confidence scoring:
        #   - resolved direct call: 1.0
        #   - IPC cross-language call: 0.9 (resolved but indirect)
        #   - unresolved external call: 0.5 (target not in codebase)
        if target_id:
            confidence = 0.9 if ipc else 1.0
        else:
            confidence = 0.5

        # Edge file/line: parse from source id (where the call originates)
        src_file, src_line = _parse_file_line_from_node_id(source_id)

        extra: Dict[str, Any] = {}
        if to_fn:
            extra["to_fn"] = to_fn
        if via_self:
            extra["via_self"] = True
        if ipc:
            extra["ipc"] = True
        if resolved is not None:
            extra["resolved"] = resolved
        extra_json = json.dumps(extra, default=str) if extra else None

        edge_rows.append((
            source_id, target_id, EDGE_TYPE_CALLS,
            src_file, src_line, confidence, extra_json,
        ))

    # ── Issue #114: dedupe node_rows by node_id.
    # The flat registry can produce multiple nodes with the same
    # ``node_id`` (file:line:fn) when e.g. a class and its __init__
    # method share the same line, or when two declarations collide on
    # the same line number. The graph_nodes.node_id column has a UNIQUE
    # constraint, so a bare INSERT would raise sqlite3.IntegrityError
    # and roll back the entire batch — leaving the graph empty.
    # Dedupe by node_id (last occurrence wins, matching the "last match
    # wins" semantics of the flat registry) before the batch insert.
    if node_rows:
        seen: Dict[str, Tuple[Any, ...]] = {}
        for row in node_rows:
            # row[0] is node_id
            seen[row[0]] = row
        node_rows = list(seen.values())

    # ── Issue #10: RAM-first indexing — batch write in a single
    # ``BEGIN EXCLUSIVE`` transaction. The node_rows + edge_rows are
    # collected fully in memory (above) BEFORE opening the transaction;
    # SQLite then holds an EXCLUSIVE write lock for the shortest possible
    # window: one DELETE pass + one ``executemany`` for nodes + one for
    # edges, all committed atomically. This replaces the previous flow
    # where the schema-clear and the inserts lived in separate implicit
    # transactions, doubling the lock-cycle count and interleaving
    # poorly with concurrent readers.
    #
    # We disable the sqlite3 module's implicit BEGIN (isolation_level=None)
    # so we can issue the EXCLUSIVE lock explicitly before any DML —
    # otherwise the first DELETE would trigger a deferred BEGIN and the
    # EXCLUSIVE upgrade would happen later under contention.
    try:
        conn.isolation_level = None  # autocommit; we manage BEGIN/COMMIT
        conn.execute("BEGIN EXCLUSIVE")
        # Wipe existing CALLS rows so re-scans don't accumulate duplicates.
        # Only CALLS edges are managed by populate_graph_tables (they come
        # from the flat backend registry). Other edge types (IMPORTS, etc.)
        # are managed by their own builders and must survive re-population.
        conn.execute(
            "DELETE FROM {} WHERE edge_type = 'CALLS'".format(GRAPH_EDGES_TABLE)
        )
        conn.execute("DELETE FROM {}".format(GRAPH_NODES_TABLE))
        if node_rows:
            # Issue #114: use INSERT OR REPLACE as defense-in-depth
            # against UNIQUE constraint violations even after dedup.
            conn.executemany(
                "INSERT OR REPLACE INTO {t} (node_id, node_type, name, file, line, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?)".format(t=GRAPH_NODES_TABLE),
                node_rows,
            )
        if edge_rows:
            conn.executemany(
                "INSERT INTO {t} (source_id, target_id, edge_type, file, line, confidence, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)".format(t=GRAPH_EDGES_TABLE),
                edge_rows,
            )
        conn.execute("COMMIT")
    except sqlite3.Error as e:
        logger.warning(f"populate_graph_tables: batch write error: {e}")
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        return {"nodes": 0, "edges": 0}

    conn.close()
    return {"nodes": len(node_rows), "edges": len(edge_rows)}


# ─── Incremental Update (issue #25) ──────────────────────────


def incremental_graph_update(
    workspace: str,
    db_path: Optional[str],
    changed_files: Iterable[str],
) -> Dict[str, int]:
    """Update graph_nodes + graph_edges for a set of changed files only.

    Used by ``scan --incremental`` to keep the graph tables in sync without
    a full re-population (issue #25). Performs a slice-level update:

    1. Convert ``changed_files`` (absolute paths) to workspace-relative paths.
       Empty input is a no-op (returns zero counts).
    2. Identify ``graph_nodes`` rows whose ``file`` is in the changed set —
       these are the stale node ids whose definitions must be replaced.
    3. Delete ``graph_edges`` rows that touch any changed file:
       - edges whose ``file`` (originating file) is in the changed set
         (covers both CALLS edges from changed files and IMPORTS edges
         whose importing file changed), AND
       - edges whose ``source_id`` or ``target_id`` references a stale
         node id from step 2 (covers cross-file edges from an unchanged
       file into a changed file — the target may have been renamed or
       moved, so the edge must be dropped and re-resolved).
    4. Delete the stale ``graph_nodes`` rows themselves.
    5. Re-read the flat backend registry (already updated by
       ``merge_backend_data`` in the scan pipeline) and INSERT only the
       nodes whose ``file`` is in the changed set, plus CALLS edges that
       touch the changed set (either endpoint's file is in the set).
    6. Call ``refine_call_edges(workspace, db_path)`` so IMPORTS edges
       and import-aware CALLS-edge refinement are rebuilt for the
       affected slice. ``refine_call_edges`` is idempotent (it clears
       and rebuilds the ``import_registry`` table and IMPORTS edges
       from scratch each call), so invoking it here is safe regardless
       of whether a previous scan already ran it.

    Idempotent: running twice with the same ``changed_files`` yields the
    same final graph state (steps 2–4 wipe the affected slice before
    step 5 re-inserts; step 6 rebuilds IMPORTS + refinement deterministically).

    Performance: O(changed_nodes + changed_edges) for steps 2–5; step 6
    is O(total_edges) because ``refine_call_edges`` is not parameterized
    by file. On the ``clean_app`` fixture (31 nodes / 97 edges), the
    whole function completes in well under 200 ms.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.
        changed_files: Iterable of absolute file paths that changed since
            the last scan. May be empty — empty input is a no-op.

    Returns:
        Dict with keys:

        * ``nodes`` — total ``graph_nodes`` row count AFTER the update
          (matches the shape returned by :func:`populate_graph_tables`
          so scan output stays consistent between full and incremental
          scans).
        * ``edges`` — total ``graph_edges`` row count AFTER the update
          (includes CALLS + IMPORTS edges).
        * ``edges_refined`` — number of CALLS edges refined by
          :func:`refine_call_edges` (0 if the post-pass is skipped).
        * ``edges_unresolved`` — number of CALLS edges that remain
          unresolved after the post-pass.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)

    # Normalize changed_files to workspace-relative paths. We accept any
    # iterable (list, set, tuple) and de-duplicate via a set.
    changed_rel_paths: Set[str] = set()
    for f in changed_files or []:
        if not f:
            continue
        try:
            rel = os.path.relpath(os.path.abspath(f), workspace)
        except (ValueError, OSError):
            continue
        if rel and rel != ".":
            changed_rel_paths.add(rel)

    zero_result: Dict[str, int] = {
        "nodes": 0,
        "edges": 0,
        "edges_refined": 0,
        "edges_unresolved": 0,
    }
    if not changed_rel_paths:
        return zero_result
    if not os.path.exists(db_path):
        # No database yet — nothing to update. The full-scan path will
        # create and populate the tables on the next non-incremental scan.
        return zero_result

    # Ensure the schema exists (idempotent — safe if PersistentRegistry
    # already created the tables).
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        init_graph_schema(conn)
    except sqlite3.Error:
        # init_graph_schema already logged; continue anyway
        pass

    # Lazy import to avoid circular dependency at module load time, and
    # to keep hybrid_type_resolver optional for downstream forks that
    # remove it.
    from registry import load_backend_registry

    backend = load_backend_registry(workspace)
    flat_nodes = backend.get("nodes", [])
    flat_edges = backend.get("edges", [])

    # Build a node_id → file lookup from the flat registry. We use this
    # to decide whether an edge touches a changed file (its source or
    # target node's file is in the changed set). We can't rely on
    # _parse_file_line_from_node_id for this because some node_ids use
    # a 4-segment format (``file:line:class:Name``) that the heuristic
    # mis-parses — the lookup is authoritative because it comes from
    # the parsers' own ``file`` field.
    node_id_to_file: Dict[str, str] = {
        n.get("id", ""): n.get("file", "")
        for n in flat_nodes if n.get("id")
    }

    edges_refined = 0
    edges_unresolved = 0

    # ── Issue #10: RAM-first indexing — collect all rows in memory
    # BEFORE opening the write transaction. The SELECT in step 1 reads
    # stale node_ids (a read-only operation that doesn't need an
    # EXCLUSIVE lock); the rows for steps 4 + 5 are built entirely from
    # the in-memory flat registry (loaded above). Only when all rows are
    # ready do we open ``BEGIN EXCLUSIVE`` and run the DELETE + INSERT
    # batch in one atomic transaction, minimizing lock duration.
    try:
        # ── Step 1: Identify stale node ids ──────────────────────
        # These are nodes whose file is in the changed set. Their ids
        # may have changed (line numbers shifted, symbols renamed), so
        # we must drop them and re-insert from the flat registry.
        ph_files = ",".join("?" for _ in changed_rel_paths)
        params_files = tuple(changed_rel_paths)

        cursor = conn.execute(
            "SELECT node_id FROM {t} WHERE file IN ({ph})".format(
                t=GRAPH_NODES_TABLE, ph=ph_files
            ),
            params_files,
        )
        affected_node_ids: Set[str] = {row[0] for row in cursor.fetchall()}

        # ── Step 4 (pre-build): Re-insert nodes from changed files ──
        # Built entirely from the in-memory flat registry — no DB reads
        # inside the upcoming EXCLUSIVE transaction.
        node_rows: List[Tuple[Any, ...]] = []
        for node in flat_nodes:
            file_val = node.get("file", "")
            if file_val not in changed_rel_paths:
                continue
            node_id = node.get("id", "")
            if not node_id:
                continue  # skip malformed nodes without an id
            name = node.get("fn", node.get("name", ""))
            flat_type = node.get("type", "function")
            node_type = _map_node_type(flat_type)
            line_val = node.get("line", 0)
            extra_keys = {
                k: v for k, v in node.items()
                if k not in ("id", "fn", "name", "type", "file", "line")
            }
            extra_json = (
                json.dumps(extra_keys, default=str) if extra_keys else None
            )
            node_rows.append(
                (node_id, node_type, name, file_val, line_val, extra_json)
            )

        # ── Step 5 (pre-build): Re-insert CALLS edges touching changed files ─
        # An edge qualifies for re-insertion if EITHER endpoint's file
        # (looked up via the flat registry's node_id → file map) is in
        # the changed set. Edges between two unchanged files are
        # untouched in both the flat registry and the graph — they were
        # preserved by step 2 (not deleted) and don't need re-insertion.
        #
        # The edge's ``file`` and ``line`` columns are populated via
        # _parse_file_line_from_node_id to match populate_graph_tables'
        # behavior exactly (so full and incremental paths produce
        # byte-identical edge rows for the same flat registry).
        edge_rows: List[Tuple[Any, ...]] = []
        for edge in flat_edges:
            source_id = edge.get("from", "")
            if not source_id:
                continue  # skip malformed edges
            target_id = edge.get("to")  # may be None for unresolved

            # Use the authoritative node_id → file map (not the
            # _parse_file_line_from_node_id heuristic) to decide whether
            # this edge touches a changed file. The heuristic mishandles
            # 4-segment class node_ids (``file:line:class:Name``).
            src_file_lookup = node_id_to_file.get(source_id, "")
            tgt_file_lookup = (
                node_id_to_file.get(target_id, "") if target_id else ""
            )
            if (src_file_lookup not in changed_rel_paths
                    and tgt_file_lookup not in changed_rel_paths):
                continue

            to_fn = edge.get("to_fn", "")
            resolved = edge.get("resolved")
            via_self = edge.get("via_self", False)
            ipc = edge.get("ipc", False)

            # Confidence scoring (mirrors populate_graph_tables).
            if target_id:
                confidence = 0.9 if ipc else 1.0
            else:
                confidence = 0.5

            # Edge file/line: parsed from source id (where the call
            # originates). Matches populate_graph_tables' behavior so
            # the graph_edges.file column is identical between paths.
            src_file, src_line = _parse_file_line_from_node_id(source_id)

            extra: Dict[str, Any] = {}
            if to_fn:
                extra["to_fn"] = to_fn
            if via_self:
                extra["via_self"] = True
            if ipc:
                extra["ipc"] = True
            if resolved is not None:
                extra["resolved"] = resolved
            extra_json = (
                json.dumps(extra, default=str) if extra else None
            )

            edge_rows.append((
                source_id, target_id, EDGE_TYPE_CALLS,
                src_file, src_line, confidence, extra_json,
            ))

        # ── Issue #10: single BEGIN EXCLUSIVE batch write ─────────
        # All rows are now in memory. Open an EXCLUSIVE write lock and
        # run steps 2 + 3 + 4-insert + 5-insert as one atomic batch:
        # DELETE affected edges → DELETE stale nodes → INSERT new nodes
        # → INSERT new edges, then COMMIT. Disabling isolation_level
        # avoids the sqlite3 module's implicit deferred BEGIN so we get
        # the EXCLUSIVE lock upfront (no upgrade deadlock risk).
        conn.isolation_level = None  # autocommit; we manage BEGIN/COMMIT
        conn.execute("BEGIN EXCLUSIVE")

        # ── Step 2: Delete affected edges ────────────────────────
        # An edge is affected if ANY of:
        #   - its originating file (`file` column) is in the changed set
        #     (covers CALLS edges from changed files + IMPORTS edges
        #     whose importer changed), OR
        #   - its source_id references a stale node (covers the rare
        #     case where a CALLS edge has a file column value that
        #     doesn't match its source_id's file — defensive), OR
        #   - its target_id references a stale node (covers cross-file
        #     edges from an unchanged file into a changed file — the
        #     target may have been renamed/moved, so the edge must be
        #     dropped and re-resolved from the flat registry).
        if affected_node_ids:
            ph_nodes = ",".join("?" for _ in affected_node_ids)
            params_nodes = tuple(affected_node_ids)
            conn.execute(
                "DELETE FROM {t} WHERE file IN ({phf}) "
                "OR source_id IN ({phn}) "
                "OR target_id IN ({phn})".format(
                    t=GRAPH_EDGES_TABLE, phf=ph_files, phn=ph_nodes
                ),
                params_files + params_nodes + params_nodes,
            )
        else:
            conn.execute(
                "DELETE FROM {t} WHERE file IN ({phf})".format(
                    t=GRAPH_EDGES_TABLE, phf=ph_files
                ),
                params_files,
            )

        # ── Step 3: Delete stale nodes ───────────────────────────
        conn.execute(
            "DELETE FROM {t} WHERE file IN ({phf})".format(
                t=GRAPH_NODES_TABLE, phf=ph_files
            ),
            params_files,
        )

        # ── Step 4 (insert): Re-insert nodes from changed files ──
        # Issue #114: dedupe + INSERT OR REPLACE to avoid UNIQUE
        # constraint violations on duplicate node_ids.
        if node_rows:
            _seen_inc: Dict[str, Tuple[Any, ...]] = {}
            for _row in node_rows:
                _seen_inc[_row[0]] = _row
            node_rows = list(_seen_inc.values())
            conn.executemany(
                "INSERT OR REPLACE INTO {t} (node_id, node_type, name, file, line, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?)".format(t=GRAPH_NODES_TABLE),
                node_rows,
            )

        # ── Step 5 (insert): Re-insert CALLS edges touching changed files ─
        if edge_rows:
            conn.executemany(
                "INSERT INTO {t} "
                "(source_id, target_id, edge_type, file, line, confidence, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)".format(t=GRAPH_EDGES_TABLE),
                edge_rows,
            )

        conn.execute("COMMIT")
    except sqlite3.Error as e:
        logger.warning("incremental_graph_update: db error: %s", e)
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        conn.close()
        return zero_result

    # ── Step 6: Re-run refine_call_edges ────────────────────────
    # Rebuilds IMPORTS edges + import-aware CALLS-edge refinement for
    # the whole graph. Idempotent — safe to call on every incremental
    # update. Failures MUST NOT break the scan (type resolution is an
    # optimization layer).
    try:
        from hybrid_type_resolver import refine_call_edges
        tr_stats = refine_call_edges(workspace, db_path)
        edges_refined = tr_stats.get("edges_refined", 0)
        edges_unresolved = tr_stats.get("edges_unresolved", 0)
    except Exception:
        logger.warning(
            "refine_call_edges failed during incremental update",
            exc_info=True,
        )

    # Return TOTAL graph stats (not the delta) so the scan output
    # shape matches populate_graph_tables' return value — callers see
    # the current graph size, regardless of full vs incremental path.
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM {t}".format(t=GRAPH_NODES_TABLE)
        ).fetchone()[0]
        e = conn.execute(
            "SELECT COUNT(*) FROM {t}".format(t=GRAPH_EDGES_TABLE)
        ).fetchone()[0]
    except sqlite3.Error:
        n, e = 0, 0
    finally:
        conn.close()

    return {
        "nodes": n,
        "edges": e,
        "edges_refined": edges_refined,
        "edges_unresolved": edges_unresolved,
    }


# ─── Graph Queries (BFS) ──────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    """Open a read-only-friendly sqlite connection with row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_node(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a graph_nodes row to a dict, parsing extra_json if present."""
    d = dict(row)
    extra = d.pop("extra_json", None)
    if extra:
        try:
            d["extra"] = json.loads(extra)
        except (json.JSONDecodeError, TypeError):
            d["extra"] = {}
    else:
        d["extra"] = {}
    return d


def find_nodes_by_name(name: str, db_path: str) -> List[Dict[str, Any]]:
    """Find graph nodes matching a symbol name.

    Matching strategy (mirrors trace_engine flat-registry matching):
      1. Exact case-sensitive match on name.
      2. Case-insensitive exact match.
      3. Case-insensitive substring match on name OR exact match on node_id.

    Args:
        name: Symbol name to search for.
        db_path: Absolute path to the SQLite database file.

    Returns:
        List of node dicts (keys: id, node_id, node_type, name, file, line, extra).
        Empty list if no matches or db/tables don't exist.
    """
    if not os.path.exists(db_path):
        return []
    conn = _connect(db_path)
    try:
        # 1. Exact match
        rows = conn.execute(
            "SELECT * FROM {t} WHERE name = ?".format(t=GRAPH_NODES_TABLE),
            (name,),
        ).fetchall()
        if rows:
            return [_row_to_node(r) for r in rows]

        # 2. Case-insensitive exact match
        rows = conn.execute(
            "SELECT * FROM {t} WHERE name = ? COLLATE NOCASE".format(t=GRAPH_NODES_TABLE),
            (name,),
        ).fetchall()
        if rows:
            return [_row_to_node(r) for r in rows]

        # 3. Case-insensitive substring on name OR exact match on node_id
        name_lower = name.lower()
        all_rows = conn.execute(
            "SELECT * FROM {t}".format(t=GRAPH_NODES_TABLE)
        ).fetchall()
        results = []
        for r in all_rows:
            node = _row_to_node(r)
            if name_lower in node.get("name", "").lower() or name in node.get("node_id", ""):
                results.append(node)
        return results
    except sqlite3.Error as e:
        logger.debug(f"find_nodes_by_name error: {e}")
        return []
    finally:
        conn.close()


def query_callers(node_id: str, db_path: str, max_depth: int = 1) -> List[Dict[str, Any]]:
    """BFS over CALLS edges in reverse — find callers (who calls this node).

    Traverses from `node_id` upward through incoming CALLS edges. At depth 1,
    returns the direct callers. At depth N, returns all callers within N hops.

    Args:
        node_id: The graph_nodes.node_id to find callers for.
        db_path: Absolute path to the SQLite database file.
        max_depth: Maximum BFS depth (1 = direct callers only).

    Returns:
        List of dicts, each representing a caller visit:
            {
                "node_id":   caller node_id,
                "name":      caller symbol name,
                "node_type": caller node type,
                "file":      caller file path,
                "line":      caller line,
                "depth":     1..max_depth,
                "edge_file": file where the call originates,
                "edge_line": line where the call originates,
                "confidence": edge confidence (0.0-1.0),
                "cyclic":    True if revisited (cycle detected),
            }
        Empty list if no callers, db missing, or max_depth <= 0.
    """
    if max_depth <= 0 or not os.path.exists(db_path):
        return []
    conn = _connect(db_path)
    try:
        return _bfs(conn, node_id, db_path, max_depth, direction="caller")
    finally:
        conn.close()


def query_callees(node_id: str, db_path: str, max_depth: int = 1) -> List[Dict[str, Any]]:
    """BFS over CALLS edges forward — find callees (what this node calls).

    Traverses from `node_id` downward through outgoing CALLS edges. At depth 1,
    returns the direct callees. At depth N, returns all callees within N hops.

    Args:
        node_id: The graph_nodes.node_id to find callees for.
        db_path: Absolute path to the SQLite database file.
        max_depth: Maximum BFS depth (1 = direct callees only).

    Returns:
        List of dicts (same shape as query_callers). Unresolved callees
        (target_id NULL) are reported with node_id=None and the to_fn from
        extra_json. Empty list if no callees, db missing, or max_depth <= 0.
    """
    if max_depth <= 0 or not os.path.exists(db_path):
        return []
    conn = _connect(db_path)
    try:
        return _bfs(conn, node_id, db_path, max_depth, direction="callee")
    finally:
        conn.close()


def _bfs(
    conn: sqlite3.Connection,
    start_node_id: str,
    db_path: str,
    max_depth: int,
    direction: str,
) -> List[Dict[str, Any]]:
    """BFS traversal over CALLS edges in one direction.

    Args:
        conn: Open sqlite3.Connection with row_factory set.
        start_node_id: node_id to start BFS from.
        db_path: db path (unused here, kept for API symmetry).
        max_depth: Max BFS depth.
        direction: "caller" (reverse — target_id == current) or
                   "callee" (forward — source_id == current).

    Returns:
        List of visit dicts (see query_callers docstring for shape).
    """
    results: List[Dict[str, Any]] = []
    visited: Set[str] = set()
    reported_cycles: Set[str] = set()
    queue = deque()

    # Pre-load start node info for completeness (caller may want its file/line)
    start_row = conn.execute(
        "SELECT * FROM {t} WHERE node_id = ?".format(t=GRAPH_NODES_TABLE),
        (start_node_id,),
    ).fetchone()

    # We do NOT emit the start node itself — only neighbors. This matches the
    # flat-registry trace engine's BFS behavior (depth 0 = start, depth 1+ = neighbors).
    visited.add(start_node_id)
    queue.append((start_node_id, 1))

    while queue:
        current_id, depth = queue.popleft()
        if depth > max_depth:
            continue

        # Fetch neighbors based on direction
        if direction == "caller":
            # Reverse: find edges where target_id == current_id
            rows = conn.execute(
                "SELECT * FROM {t} WHERE target_id = ? AND edge_type = ?".format(t=GRAPH_EDGES_TABLE),
                (current_id, EDGE_TYPE_CALLS),
            ).fetchall()
        else:
            # Forward: find edges where source_id == current_id
            rows = conn.execute(
                "SELECT * FROM {t} WHERE source_id = ? AND edge_type = ?".format(t=GRAPH_EDGES_TABLE),
                (current_id, EDGE_TYPE_CALLS),
            ).fetchall()

        for edge in rows:
            edge_dict = dict(edge)
            if direction == "caller":
                neighbor_id = edge_dict.get("source_id", "") or ""
            else:
                neighbor_id = edge_dict.get("target_id", "") or ""

            edge_extra: Dict[str, Any] = {}
            if edge_dict.get("extra_json"):
                try:
                    edge_extra = json.loads(edge_dict["extra_json"])
                except (json.JSONDecodeError, TypeError):
                    edge_extra = {}

            # Unresolved callee (target_id NULL): report with to_fn if available
            if not neighbor_id:
                if direction != "callee":
                    continue  # callers always have a source_id
                to_fn = edge_extra.get("to_fn", "unknown")
                results.append({
                    "node_id": None,
                    "name": to_fn,
                    "node_type": "unresolved",
                    "file": edge_dict.get("file", ""),
                    "line": edge_dict.get("line", 0) or 0,
                    "depth": depth,
                    "edge_file": edge_dict.get("file", ""),
                    "edge_line": edge_dict.get("line", 0) or 0,
                    "confidence": edge_dict.get("confidence", 0.5),
                    "resolved": False,
                    "cyclic": False,
                })
                continue

            # Skip self-edges (recursion is not a meaningful trace step)
            if neighbor_id == current_id:
                continue

            # Cycle handling
            if neighbor_id in visited:
                if neighbor_id == start_node_id and depth <= 1:
                    continue
                cycle_key = "{}@{}".format(neighbor_id, depth)
                if cycle_key in reported_cycles:
                    continue
                reported_cycles.add(cycle_key)

                neighbor_row = conn.execute(
                    "SELECT * FROM {t} WHERE node_id = ?".format(t=GRAPH_NODES_TABLE),
                    (neighbor_id,),
                ).fetchone()
                if neighbor_row:
                    nb = _row_to_node(neighbor_row)
                    results.append({
                        "node_id": neighbor_id,
                        "name": nb.get("name", ""),
                        "node_type": nb.get("node_type", "function"),
                        "file": nb.get("file", ""),
                        "line": nb.get("line", 0) or 0,
                        "depth": depth,
                        "edge_file": edge_dict.get("file", ""),
                        "edge_line": edge_dict.get("line", 0) or 0,
                        "confidence": edge_dict.get("confidence", 1.0),
                        "cyclic": True,
                    })
                continue

            visited.add(neighbor_id)
            neighbor_row = conn.execute(
                "SELECT * FROM {t} WHERE node_id = ?".format(t=GRAPH_NODES_TABLE),
                (neighbor_id,),
            ).fetchone()
            if neighbor_row:
                nb = _row_to_node(neighbor_row)
                results.append({
                    "node_id": neighbor_id,
                    "name": nb.get("name", ""),
                    "node_type": nb.get("node_type", "function"),
                    "file": nb.get("file", ""),
                    "line": nb.get("line", 0) or 0,
                    "depth": depth,
                    "edge_file": edge_dict.get("file", ""),
                    "edge_line": edge_dict.get("line", 0) or 0,
                    "confidence": edge_dict.get("confidence", 1.0),
                    "resolved": True,
                    "cyclic": False,
                    "extra": nb.get("extra", {}),
                })
                if depth < max_depth:
                    queue.append((neighbor_id, depth + 1))

    return results


# ─── Introspection Helpers ────────────────────────────────────

def graph_tables_exist(db_path: str) -> bool:
    """Check whether the graph_nodes and graph_edges tables exist in the db."""
    if not os.path.exists(db_path):
        return False
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?)",
            (GRAPH_NODES_TABLE, GRAPH_EDGES_TABLE),
        ).fetchall()
        return len(row) == 2
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def graph_tables_populated(db_path: str) -> bool:
    """Check whether the graph tables exist AND have at least one row.

    Used by trace_engine to decide whether to use the graph backend or fall
    back to the flat registry.
    """
    if not graph_tables_exist(db_path):
        return False
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM {t}".format(t=GRAPH_NODES_TABLE)
        ).fetchone()
        count = row[0] if row else 0
        return count > 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def graph_stats(db_path: str) -> Dict[str, int]:
    """Return row counts for graph_nodes and graph_edges.

    Useful for diagnostics and tests. Returns zeros if db/tables don't exist.
    """
    if not graph_tables_exist(db_path):
        return {"nodes": 0, "edges": 0}
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute("SELECT COUNT(*) FROM {t}".format(t=GRAPH_NODES_TABLE)).fetchone()[0]
        e = conn.execute("SELECT COUNT(*) FROM {t}".format(t=GRAPH_EDGES_TABLE)).fetchone()[0]
        return {"nodes": n, "edges": e}
    except sqlite3.Error:
        return {"nodes": 0, "edges": 0}
    finally:
        conn.close()
