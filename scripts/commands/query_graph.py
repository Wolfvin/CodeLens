# @WHO:   scripts/commands/query_graph.py
# @WHAT:  Cypher-subset graph query — MATCH/WHERE/RETURN/LIMIT over graph_nodes + graph_edges
# @PART:  commands
# @ENTRY: execute()

"""
Query-graph command — Cypher-subset structural queries over the code graph (issue #9).

Agents can express structural questions in a single expressive query
instead of chaining ``trace`` + ``impact`` + ``context`` tool calls.
One query replaces 3-5 tool calls for typical structural questions
("who calls handleRequest", "dead code with no callers", "classes
inheriting from BaseModel").

Supported Cypher subset (per issue #9 "minimal viable" scope):

    MATCH (f:Function)-[:CALLS]->(g)
    WHERE f.name = 'handleRequest'
    RETURN g.name, g.file

    MATCH (c:Class)-[:INHERITS]->(p)
    WHERE p.name = 'BaseModel'
    RETURN c.name

    MATCH (f:Function)
    WHERE NOT EXISTS { ()-[:CALLS]->(f) }
    RETURN f.name                     -- dead code (no callers)

Clauses: MATCH, WHERE, RETURN, LIMIT
Predicates: =, !=, <, >, <=, >=, CONTAINS, IS NULL, IS NOT NULL,
            EXISTS { pattern }, NOT EXISTS { pattern }, AND, OR, NOT
Node labels: Function, Class, File, Module, Route, Type, Interface
Edge types: CALLS, IMPORTS, DEFINES, INHERITS, IMPLEMENTS, USES_TYPE

Read-only — no CREATE / SET / DELETE clauses. Default LIMIT 100, hard
cap 1000 to prevent runaway queries.

Example:
    codelens query-graph \\
        'MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = \\'handleRequest\\' RETURN g.name, g.file' \\
        /path/to/workspace

    codelens query-graph --query 'MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name' /path/to/workspace
"""

from typing import Optional

from commands import register_command
from cypher_query_engine import query_graph, CypherParseError


def add_args(parser):
    """Add query-graph arguments to the parser."""
    parser.add_argument(
        "query",
        help=(
            "Cypher-subset query string. Must contain MATCH ... RETURN. "
            "Example: \"MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name\""
        ),
    )
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="Custom path for SQLite database file (default: <workspace>/.codelens/codelens.db)",
    )
    parser.add_argument(
        "--explain", action="store_true",
        help="Show the translated SQL and parameters without executing the query",
    )


def execute(args, workspace):
    """Execute the query-graph command.

    @FLOW: QUERY_GRAPH
    @CALLS: cypher_query_engine.query_graph() -> result_dict
    @MUTATES: none (read-only graph query)
    """
    db_path = getattr(args, "db_path", None)

    if getattr(args, "explain", False):
        # Parse + translate only, don't execute.
        from cypher_query_engine import parse, translate
        try:
            ast = parse(args.query)
            sql, params, ret = translate(ast)
        except CypherParseError as e:
            return {
                "status": "error",
                "error": f"Parse error: {e}",
                "query": args.query,
            }
        return {
            "status": "ok",
            "query": args.query,
            "sql": sql,
            "params": params,
            "return_items": [r.display_name() for r in ret],
        }

    return query_graph(args.query, workspace, db_path=db_path)


register_command(
    "query-graph",
    "Cypher-subset structural query over graph_nodes + graph_edges (MATCH/WHERE/RETURN/LIMIT, read-only)",
    add_args,
    execute,
)
