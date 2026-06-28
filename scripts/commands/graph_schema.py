"""Graph-schema command — return the shape of the code graph (issue #17).

Returns node + edge counts, node type distribution, edge type distribution,
and the number of indexes. This is the cheapest way for an agent to
understand the graph shape before issuing structural queries (callers,
callees, blast radius, circular chains). One call replaces 5+ verbose
``trace``/``list`` round-trips during initial codebase orientation.

Example output (compact form):
    {"nodes": 31, "edges": 97, "node_types": {"function": 30, "class": 1},
     "edge_types": {"CALLS": 97}, "indexes": 6, "status": "ok"}
"""

import os
import sqlite3
from typing import Any, Dict, Optional

from commands import register_command
from utils import default_db_path as _default_db_path


def add_args(parser):
    """Add graph-schema arguments to the parser."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for SQLite database file")


def get_graph_schema(workspace: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Return the shape of the graph (node/edge counts + type distribution).

    Reads the ``graph_nodes`` and ``graph_edges`` SQLite tables populated
    during scan. Returns zeros and empty type maps when the database or
    tables don't exist (e.g., pre-8.2 databases or before scan).

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
                 ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys ``nodes``, ``edges``, ``node_types``, ``edge_types``,
        ``indexes``, ``status``, and ``workspace``.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or _default_db_path(workspace)

    schema: Dict[str, Any] = {
        "status": "ok",
        "workspace": workspace,
        "nodes": 0,
        "edges": 0,
        "node_types": {},
        "edge_types": {},
        "indexes": 0,
    }

    if not os.path.exists(db_path):
        # Database doesn't exist yet — graph tables haven't been created.
        # Return the zero-shaped schema so callers can branch on nodes==0
        # without error handling.
        schema["note"] = "database does not exist; run 'scan' first"
        return schema

    conn = sqlite3.connect(db_path)
    try:
        # Check tables exist before querying — sqlite3 raises OperationalError
        # if a table is missing, which we treat as "graph not initialized".
        table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('graph_nodes', 'graph_edges') ORDER BY name"
        ).fetchall()
        table_names = {r[0] for r in table_row}
        if "graph_nodes" not in table_names or "graph_edges" not in table_names:
            schema["note"] = "graph tables not initialized; run 'scan' first"
            return schema

        # Node + edge totals.
        schema["nodes"] = conn.execute(
            "SELECT COUNT(*) FROM graph_nodes"
        ).fetchone()[0]
        schema["edges"] = conn.execute(
            "SELECT COUNT(*) FROM graph_edges"
        ).fetchone()[0]

        # Node type distribution.
        node_type_rows = conn.execute(
            "SELECT node_type, COUNT(*) FROM graph_nodes GROUP BY node_type "
            "ORDER BY COUNT(*) DESC"
        ).fetchall()
        schema["node_types"] = {r[0]: r[1] for r in node_type_rows}

        # Edge type distribution.
        edge_type_rows = conn.execute(
            "SELECT edge_type, COUNT(*) FROM graph_edges GROUP BY edge_type "
            "ORDER BY COUNT(*) DESC"
        ).fetchall()
        schema["edge_types"] = {r[0]: r[1] for r in edge_type_rows}

        # Index count (only graph_* indexes — there are 6 by default).
        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_graph_%'"
        ).fetchall()
        schema["indexes"] = len(idx_rows)
    except sqlite3.Error as exc:
        schema["status"] = "error"
        schema["error"] = str(exc)
    finally:
        conn.close()

    return schema


def execute(args, workspace):
    """Execute the graph-schema command."""
    db_path = getattr(args, "db_path", None)
    return get_graph_schema(workspace, db_path=db_path)


register_command(
    "graph-schema",
    "Return the shape of the code graph (node/edge counts, type distribution, indexes)",
    add_args,
    execute,
)
