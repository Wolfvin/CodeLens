"""graph command — raw Cypher graph query for power users (issue #195).

This is the power-user entry point that wraps the same query-graph engine
as ``search --mode graph``, but defaults to raw Cypher pass-through with
no niceties. Casual callers should prefer ``search --mode graph``.

Usage:
    codelens graph "MATCH (n:Function) WHERE n.id CONTAINS 'auth' RETURN n LIMIT 10"
    codelens graph "MATCH (n)-[r:CALLS]->(m) RETURN n.id, m.id LIMIT 50"
    codelens graph "MATCH (n) WHERE n.id CONTAINS x" --validate

Output: ``{"s":"ok", "st":{...}, "r":[...]}`` shape (rows under ``r``).
"""

# @WHO:   scripts/commands/graph.py
# @WHAT:  Raw Cypher-subset graph query (power-user mode).
# @PART:  commands
# @ENTRY: execute()

import argparse
from typing import Any, Dict

from commands import register_command


def add_args(parser):
    """Add graph-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Raw Cypher-subset query (issue #195):\n"
        "  Supported clauses: MATCH, WHERE, RETURN, LIMIT, EXISTS\n"
        "  Node types: Function, Class, Module, File, Route, Variable, ...\n"
        "  Edge types: CALLS, IMPORTS, DEFINES, REFERENCES, CONTAINS\n"
        "\n"
        "Examples:\n"
        "  codelens graph \"MATCH (n:Function) WHERE n.id CONTAINS 'auth' RETURN n LIMIT 10\"\n"
        "  codelens graph \"MATCH (n)-[r:CALLS]->(m) RETURN n.id, m.id LIMIT 50\"\n"
        "  codelens graph \"MATCH (n) WHERE n.id CONTAINS x\" --validate\n"
        "\n"
        "Casual callers should prefer ``codelens search <workspace> <query> --mode graph``."
    )
    parser.add_argument("query", help="Cypher-subset query string")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Row cap (appended as LIMIT if not already present)")
    parser.add_argument("--validate", action="store_true", default=False,
                        help="Validate the query without executing it")
    parser.add_argument("--db-path", default=None,
                        help="Custom SQLite database path")


def execute(args, workspace):
    """Execute a raw Cypher-subset query against the graph DB.

    @FLOW:    GRAPH_QUERY
    @CALLS:   commands.query_graph.execute() -> dict
    @MUTATES: nothing (read-only)
    """
    # Delegate to the existing query-graph executor — it already handles
    # LIMIT injection, --validate, and --db-path. ``graph`` is the bare
    # power-user surface; ``search --mode graph`` is the friendly wrapper.
    from commands.query_graph import execute as _qg_execute
    result = _qg_execute(args, workspace)
    # Re-shape to the umbrella-consistent {s, st, r} form.
    if isinstance(result, dict) and "s" in result:
        return result
    if not isinstance(result, dict):
        return {"s": "ok", "st": {}, "r": [{"result": result}]}
    # query-graph returns {"status": "ok", "rows": [...], "query": ..., ...}
    rows = result.pop("rows", None)
    new_result = {
        "s": result.pop("status", "ok"),
        "st": result,
        "r": rows if rows is not None else [],
    }
    return new_result


register_command(
    "graph",
    "Raw Cypher-subset graph query (power-user; casual callers use `search --mode graph`)",
    add_args,
    execute,
)
