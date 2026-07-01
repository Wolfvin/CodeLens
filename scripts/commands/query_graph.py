"""query-graph command — run an openCypher-subset query against the code graph.

Implements the MVP scope of issue #9. Accepts a single Cypher-subset
query string, parses it via :mod:`cypher_parser`, runs it against the
``graph_nodes`` + ``graph_edges`` SQLite tables, and returns rows.

Supported query shapes (see ``scripts/cypher_parser.py`` for the full
grammar):

    codelens query-graph 'MATCH (f:Function) RETURN f.name, f.file'
    codelens query-graph 'MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = \\'handleRequest\\' RETURN g.name, g.file'
    codelens query-graph 'MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) } RETURN f.name'

The command is read-only — it never writes to the database.

Output is a JSON object:
    {
      "status": "ok",
      "query": "<original query string>",
      "rows": [...],
      "row_count": N,
      "workspace": "<abs path>"
    }

On parse error:
    { "status": "error", "error": "CypherParseError: <message>", "query": "..." }
On missing database / graph tables:
    { "status": "error", "error": "graph not initialized; run 'scan' first", ... }
"""

import os
import sqlite3
import sys
from typing import Any, Dict, Optional

# Make scripts/ importable when this module is loaded directly by the
# command registry (which imports commands as ``commands.<name>``).
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(_HERE)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from commands import register_command  # noqa: E402
from cypher_parser import CypherParseError, evaluate, parse_query  # noqa: E402
from utils import default_db_path  # noqa: E402


def add_args(parser):
    """Add query-graph arguments to the parser."""
    parser.add_argument(
        "query",
        help="Cypher-subset query string (quote it on the shell)",
    )
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Custom path for SQLite database file",
    )


def run_query_graph(
    query: str,
    workspace: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a Cypher-subset query against the graph tables.

    Args:
        query: The Cypher query string.
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path override.

    Returns:
        Dict with ``status``, ``query``, ``rows``, ``row_count``, and
        ``workspace`` keys on success. On error, ``status`` is ``"error"``
        and the ``error`` key contains a human-readable message.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)

    result: Dict[str, Any] = {
        "status": "ok",
        "query": query,
        "workspace": workspace,
        "rows": [],
        "row_count": 0,
    }

    # Parse first — parse errors are returned as structured errors, not
    # exceptions, so callers (CLI + MCP) can surface them cleanly.
    try:
        parsed = parse_query(query)
    except CypherParseError as e:
        result["status"] = "error"
        result["error"] = f"CypherParseError: {e}"
        return result

    # Verify the database + graph tables exist before evaluating.
    if not os.path.exists(db_path):
        result["status"] = "error"
        result["error"] = (
            f"database not found at {db_path}; run 'codelens scan' first"
        )
        return result

    try:
        conn = sqlite3.connect(db_path)
        try:
            table_row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('graph_nodes', 'graph_edges') ORDER BY name"
            ).fetchall()
            table_names = {r[0] for r in table_row}
            if "graph_nodes" not in table_names or "graph_edges" not in table_names:
                result["status"] = "error"
                result["error"] = (
                    "graph tables not initialized; run 'codelens scan' first"
                )
                return result
        finally:
            conn.close()
    except sqlite3.Error as e:
        result["status"] = "error"
        result["error"] = f"database error: {e}"
        return result

    # Evaluate the parsed query against the graph tables.
    try:
        rows = evaluate(parsed, db_path)
        result["rows"] = rows
        result["row_count"] = len(rows)
    except (sqlite3.Error, CypherParseError) as e:
        result["status"] = "error"
        result["error"] = f"{type(e).__name__}: {e}"
        return result

    return result


def execute(args, workspace):
    """Execute the query-graph command."""
    db_path = getattr(args, "db_path", None)
    return run_query_graph(args.query, workspace, db_path=db_path)


register_command(
    "query-graph",
    "Run an openCypher-subset query against the code graph (issue #9 MVP)",
    add_args,
    execute,
)
