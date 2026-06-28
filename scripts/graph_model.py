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
- All 56 existing CLI commands continue to work unchanged.

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
from typing import Any, Dict, List, Optional, Set, Tuple

from utils import logger


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

# Edge types (per issue #8 spec)
EDGE_TYPE_CALLS = "CALLS"
EDGE_TYPE_IMPORTS = "IMPORTS"
EDGE_TYPE_DEFINES = "DEFINES"
EDGE_TYPE_INHERITS = "INHERITS"
EDGE_TYPE_IMPLEMENTS = "IMPLEMENTS"
EDGE_TYPE_USES_TYPE = "USES_TYPE"

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

def _default_db_path(workspace: str) -> str:
    """Return the default SQLite db path for a workspace."""
    return os.path.join(workspace, ".codelens", "codelens.db")


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
    db_path = db_path or _default_db_path(workspace)

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

    # Wipe existing rows so re-scans don't accumulate duplicates.
    try:
        conn.execute("DELETE FROM {}".format(GRAPH_EDGES_TABLE))
        conn.execute("DELETE FROM {}".format(GRAPH_NODES_TABLE))
    except sqlite3.Error as e:
        logger.warning(f"populate_graph_tables: clear error: {e}")
        conn.rollback()
        conn.close()
        return {"nodes": 0, "edges": 0}

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

    try:
        if node_rows:
            conn.executemany(
                "INSERT INTO {t} (node_id, node_type, name, file, line, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?)".format(t=GRAPH_NODES_TABLE),
                node_rows,
            )
        if edge_rows:
            conn.executemany(
                "INSERT INTO {t} (source_id, target_id, edge_type, file, line, confidence, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)".format(t=GRAPH_EDGES_TABLE),
                edge_rows,
            )
        conn.commit()
    except sqlite3.Error as e:
        logger.warning(f"populate_graph_tables: insert error: {e}")
        conn.rollback()
        conn.close()
        return {"nodes": 0, "edges": 0}

    conn.close()
    return {"nodes": len(node_rows), "edges": len(edge_rows)}


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
