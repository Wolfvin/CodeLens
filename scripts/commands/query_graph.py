# @WHO:   scripts/commands/query_graph.py
# @WHAT:  Cypher-subset graph query CLI command (issue #9)
# @PART:  commands
# @ENTRY: execute()
"""query-graph command — Cypher-subset graph query (issue #9).

Agents currently must chain multiple MCP tools (trace → impact → context) to
answer structural questions. This command accepts an openCypher-subset query
and returns matching nodes/edges in one call — replacing 3-5 tool calls.

Supported subset (MVP):
    MATCH (var:Label)-[:EDGE_TYPE]->(var2)
    WHERE var.property = 'value'
    WHERE var.name CONTAINS 'substr'
    WHERE var.file IS NULL
    WHERE NOT EXISTS { ()-[:CALLS]->(var) }   -- dead code
    RETURN var.name, var2.file
    LIMIT 10

Usage::

    codelens query-graph "MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file"
    codelens query-graph "MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name" --limit 50
    codelens query-graph "MATCH (c:Class)-[:INHERITS]->(p:Class) RETURN c.name, p.name"

The query language is read-only (no CREATE/DELETE/MERGE). See
:mod:`query_graph_engine` for the grammar and supported clauses.
"""

from __future__ import annotations

from typing import Any, Dict

from commands import register_command


def add_args(parser):
    """Add query-graph arguments to the parser."""
    parser.add_argument(
        "query",
        help=(
            "Cypher-subset query. Must start with MATCH. "
            "Example: \"MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name\""
        ),
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for SQLite database file")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max results to return (overrides LIMIT in query if set)")
    parser.add_argument("--validate", action="store_true",
                        help="Validate query syntax without executing it")


def execute(args, workspace):
    """Execute the query-graph command."""
    db_path = getattr(args, "db_path", None)
    query = args.query

    # If --limit is passed on CLI, append it to the query (CLI limit overrides
    # query LIMIT for convenience — agents can use either).
    cli_limit = getattr(args, "limit", None)
    if cli_limit is not None:
        # Strip any existing LIMIT from the query, then append CLI limit.
        # This is a simple approach — the parser will handle the final LIMIT.
        import re
        query = re.sub(r"\s+LIMIT\s+\d+\s*$", "", query, flags=re.IGNORECASE)
        query = f"{query.rstrip()} LIMIT {cli_limit}"

    # --validate: check syntax only, don't touch the DB
    if getattr(args, "validate", False):
        from query_graph_engine import validate_query
        return validate_query(query)

    from query_graph_engine import execute_query
    return execute_query(query, workspace, db_path=db_path)

# Issue #199: deprecated "query-graph" alias registration removed; this module is now an implementation module imported by the "graph" umbrella command.
