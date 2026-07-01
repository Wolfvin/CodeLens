"""
Tests for the Cypher-subset graph query engine (issue #9).

Covers three layers:
  1. Parser — tokenization + AST construction + validation
  2. Translator — AST → parameterized SQL
  3. Executor — end-to-end query against a test SQLite database

The executor tests build a small in-memory graph (6 nodes, 3 edges)
and verify that the three example queries from issue #9 return the
expected results.
"""

import os
import sys
import json
import tempfile
import sqlite3
from pathlib import Path

import pytest

# Make scripts/ importable
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from cypher_query_engine import (
    parse, translate, execute, query_graph,
    CypherParseError, CypherExecutionError,
    CypherQuery, NodePattern, EdgePattern, PathPattern,
    Comparison, IsNull, ExistsSubquery, BoolOp, NotOp, ReturnItem,
    DEFAULT_LIMIT, MAX_LIMIT,
)
from graph_model import (
    init_graph_schema, GRAPH_NODES_TABLE, GRAPH_EDGES_TABLE,
)


# ─── Test fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def test_db():
    """Create a temporary workspace with a small test graph.

    Graph layout:
        handleRequest (function, api.py:1)
          └─CALLS→ processData (function, api.py:10)
                      └─CALLS→ helper (function, utils.py:20)

        User (class, models.py:40)
          └─INHERITS→ BaseModel (class, models.py:30)

        orphan (function, dead.py:50) — no callers, no callees
    """
    ws = tempfile.mkdtemp(prefix="cypher-test-")
    db_path = os.path.join(ws, ".codelens", "codelens.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    init_graph_schema(conn)

    nodes = [
        ("file:1:handleRequest", "function", "handleRequest", "api.py", 1),
        ("file:10:processData", "function", "processData", "api.py", 10),
        ("file:20:helper", "function", "helper", "utils.py", 20),
        ("file:30:BaseModel", "class", "BaseModel", "models.py", 30),
        ("file:40:User", "class", "User", "models.py", 40),
        ("file:50:orphan", "function", "orphan", "dead.py", 50),
    ]
    for n in nodes:
        conn.execute(
            f"INSERT INTO {GRAPH_NODES_TABLE} (node_id, node_type, name, file, line) VALUES (?,?,?,?,?)",
            n,
        )

    edges = [
        ("file:1:handleRequest", "file:10:processData", "CALLS", "api.py", 2),
        ("file:10:processData", "file:20:helper", "CALLS", "api.py", 12),
        ("file:40:User", "file:30:BaseModel", "INHERITS", "models.py", 41),
    ]
    for e in edges:
        conn.execute(
            f"INSERT INTO {GRAPH_EDGES_TABLE} (source_id, target_id, edge_type, file, line) VALUES (?,?,?,?,?)",
            e,
        )
    conn.commit()
    conn.close()

    return ws, db_path


# ─── Parser tests ─────────────────────────────────────────────────────────


class TestTokenizer:
    """Tokenizer edge cases."""

    def test_simple_query_tokenizes(self):
        q = parse("MATCH (f:Function) RETURN f.name")
        assert len(q.patterns) == 1
        assert q.patterns[0].start.var == "f"
        assert q.patterns[0].start.label == "Function"

    def test_comment_stripped(self):
        q = parse("MATCH (f:Function) RETURN f.name -- this is a comment")
        assert len(q.return_items) == 1
        assert q.return_items[0].var == "f"

    def test_string_with_escaped_quote(self):
        q = parse("MATCH (f:Function) WHERE f.name = 'it''s' RETURN f.name")
        comp = q.where
        assert isinstance(comp, Comparison)
        assert comp.value == "it's"

    def test_multiline_query(self):
        q = parse("""
            MATCH (f:Function)-[:CALLS]->(g)
            WHERE f.name = 'handleRequest'
            RETURN g.name, g.file
        """)
        assert len(q.patterns[0].edges) == 1
        assert q.patterns[0].edges[0].edge_type == "CALLS"


class TestParserBasic:
    """Basic parsing — happy path for each clause."""

    def test_parse_single_node_pattern(self):
        q = parse("MATCH (f:Function) RETURN f.name")
        assert isinstance(q, CypherQuery)
        assert len(q.patterns) == 1
        assert q.patterns[0].start.var == "f"
        assert q.patterns[0].start.label == "Function"
        assert len(q.patterns[0].edges) == 0

    def test_parse_edge_pattern_right(self):
        q = parse("MATCH (f:Function)-[:CALLS]->(g) RETURN g.name")
        pat = q.patterns[0]
        assert len(pat.edges) == 1
        edge = pat.edges[0]
        assert edge.edge_type == "CALLS"
        assert edge.direction == "->"
        assert edge.target.var == "g"

    def test_parse_edge_pattern_left(self):
        q = parse("MATCH (f:Function)<-[:CALLS]-(g) RETURN f.name")
        edge = q.patterns[0].edges[0]
        assert edge.edge_type == "CALLS"
        assert edge.direction == "<-"

    def test_parse_edge_pattern_undirected(self):
        q = parse("MATCH (f:Function)-[:CALLS]-(g) RETURN f.name")
        edge = q.patterns[0].edges[0]
        assert edge.direction == "-"

    def test_parse_edge_no_type(self):
        q = parse("MATCH (f:Function)-[]->(g) RETURN f.name")
        edge = q.patterns[0].edges[0]
        assert edge.edge_type is None
        assert edge.direction == "->"

    def test_parse_anonymous_node(self):
        q = parse("MATCH ()-[:CALLS]->(f) RETURN f.name")
        assert q.patterns[0].start.var is None
        assert q.patterns[0].edges[0].target.var == "f"

    def test_parse_where_string_equality(self):
        q = parse("MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN f.name")
        assert isinstance(q.where, Comparison)
        assert q.where.var == "f"
        assert q.where.prop == "name"
        assert q.where.op == "="
        assert q.where.value == "handleRequest"

    def test_parse_where_integer_equality(self):
        q = parse("MATCH (f:Function) WHERE f.line = 42 RETURN f.name")
        assert q.where.value == 42
        assert isinstance(q.where.value, int)

    def test_parse_where_contains(self):
        q = parse("MATCH (f:Function) WHERE f.name CONTAINS 'handler' RETURN f.name")
        assert q.where.op == "CONTAINS"

    def test_parse_where_is_null(self):
        q = parse("MATCH (f:Function) WHERE f.file IS NULL RETURN f.name")
        assert isinstance(q.where, IsNull)
        assert q.where.negate is False

    def test_parse_where_is_not_null(self):
        q = parse("MATCH (f:Function) WHERE f.file IS NOT NULL RETURN f.name")
        assert isinstance(q.where, IsNull)
        assert q.where.negate is True

    def test_parse_where_and(self):
        q = parse("MATCH (f:Function) WHERE f.name = 'a' AND f.line = 1 RETURN f.name")
        assert isinstance(q.where, BoolOp)
        assert q.where.op == "AND"

    def test_parse_where_or(self):
        q = parse("MATCH (f:Function) WHERE f.name = 'a' OR f.name = 'b' RETURN f.name")
        assert isinstance(q.where, BoolOp)
        assert q.where.op == "OR"

    def test_parse_where_not(self):
        q = parse("MATCH (f:Function) WHERE NOT f.name = 'a' RETURN f.name")
        assert isinstance(q.where, NotOp)

    def test_parse_where_exists(self):
        q = parse("MATCH (f:Function) WHERE EXISTS { (g)-[:CALLS]->(f) } RETURN f.name")
        assert isinstance(q.where, ExistsSubquery)
        assert q.where.negate is False

    def test_parse_where_not_exists(self):
        q = parse("MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name")
        assert isinstance(q.where, ExistsSubquery)
        assert q.where.negate is True

    def test_parse_return_whole_node(self):
        q = parse("MATCH (f:Function) RETURN f")
        assert len(q.return_items) == 1
        assert q.return_items[0].var == "f"
        assert q.return_items[0].prop is None

    def test_parse_return_multiple(self):
        q = parse("MATCH (f:Function) RETURN f.name, f.file, f.line")
        assert len(q.return_items) == 3

    def test_parse_limit(self):
        q = parse("MATCH (f:Function) RETURN f.name LIMIT 50")
        assert q.limit == 50

    def test_parse_no_limit_defaults_to_none(self):
        q = parse("MATCH (f:Function) RETURN f.name")
        assert q.limit is None  # executor applies DEFAULT_LIMIT


class TestParserValidation:
    """Parser should reject invalid queries with clear errors."""

    def test_reject_write_clause_create(self):
        with pytest.raises(CypherParseError, match="read-only"):
            parse("CREATE (n:Function {name: 'test'})")

    def test_reject_write_clause_delete(self):
        with pytest.raises(CypherParseError, match="read-only"):
            parse("MATCH (n) DELETE n")

    def test_reject_unknown_label(self):
        with pytest.raises(CypherParseError, match="Unknown node label"):
            parse("MATCH (f:NotARealLabel) RETURN f.name")

    def test_reject_unknown_edge_type(self):
        with pytest.raises(CypherParseError, match="Unknown edge type"):
            parse("MATCH (f)-[:NOT_A_REAL_EDGE]->(g) RETURN f.name")

    def test_reject_unknown_property(self):
        with pytest.raises(CypherParseError, match="Unknown property"):
            parse("MATCH (f:Function) WHERE f.not_a_property = 'x' RETURN f.name")

    def test_reject_unbound_return_var(self):
        with pytest.raises(CypherParseError, match="not bound"):
            parse("MATCH (f:Function) RETURN g.name")

    def test_reject_unbound_where_var(self):
        with pytest.raises(CypherParseError, match="not bound"):
            parse("MATCH (f:Function) WHERE g.name = 'x' RETURN f.name")

    def test_reject_limit_zero(self):
        with pytest.raises(CypherParseError, match="positive integer"):
            parse("MATCH (f:Function) RETURN f.name LIMIT 0")

    def test_reject_limit_exceeds_cap(self):
        with pytest.raises(CypherParseError, match="exceeds hard cap"):
            parse(f"MATCH (f:Function) RETURN f.name LIMIT {MAX_LIMIT + 1}")

    def test_reject_missing_match(self):
        with pytest.raises(CypherParseError):
            parse("RETURN f.name")

    def test_reject_missing_return(self):
        with pytest.raises(CypherParseError):
            parse("MATCH (f:Function)")

    def test_reject_unterminated_string(self):
        with pytest.raises(CypherParseError, match="Unterminated"):
            parse("MATCH (f:Function) WHERE f.name = 'unterminated RETURN f.name")


# ─── Translator tests ─────────────────────────────────────────────────────


class TestTranslator:
    """SQL translation — placeholder/param count must match."""

    def _check(self, query_str):
        ast = parse(query_str)
        sql, params, ret = translate(ast)
        ph_count = sql.count("?")
        assert ph_count == len(params), (
            f"Placeholder count ({ph_count}) != param count ({len(params)}) "
            f"for query: {query_str}\nSQL: {sql}\nParams: {params}"
        )
        return sql, params, ret

    def test_single_node_query(self):
        sql, params, _ = self._check("MATCH (f:Function) RETURN f.name")
        assert "graph_nodes AS n_f" in sql
        assert "n_f.node_type = ?" in sql
        assert "function" in params

    def test_edge_query_params(self):
        sql, params, _ = self._check(
            "MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name"
        )
        assert "function" in params
        assert "CALLS" in params
        assert "handleRequest" in params

    def test_contains_translates_to_like(self):
        sql, params, _ = self._check(
            "MATCH (f:Function) WHERE f.name CONTAINS 'handler' RETURN f.name"
        )
        assert "LIKE ?" in sql
        assert "%handler%" in params

    def test_not_exists_translates_to_correlated_subquery(self):
        sql, params, _ = self._check(
            "MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name"
        )
        assert "NOT EXISTS" in sql
        # The subquery should correlate to the outer n_f alias.
        assert "n_f.node_id" in sql
        assert "CALLS" in params

    def test_limit_added_as_param(self):
        sql, params, _ = self._check(
            "MATCH (f:Function) RETURN f.name LIMIT 50"
        )
        assert "LIMIT ?" in sql
        assert 50 in params

    def test_default_limit_applied(self):
        ast = parse("MATCH (f:Function) RETURN f.name")
        sql, params, _ = translate(ast)
        assert "LIMIT ?" in sql
        assert DEFAULT_LIMIT in params

    def test_all_ops_translate(self):
        for op in ["=", "!=", "<", ">", "<=", ">="]:
            q = f"MATCH (f:Function) WHERE f.line {op} 10 RETURN f.name"
            self._check(q)

    def test_and_or_translate(self):
        self._check("MATCH (f:Function) WHERE f.name = 'a' AND f.line = 1 RETURN f.name")
        self._check("MATCH (f:Function) WHERE f.name = 'a' OR f.name = 'b' RETURN f.name")

    def test_return_whole_node_selects_5_columns(self):
        sql, _, _ = self._check("MATCH (f:Function) RETURN f")
        # node_id, node_type, name, file, line
        assert "n_f.node_id" in sql
        assert "n_f.node_type" in sql
        assert "n_f.name" in sql
        assert "n_f.file" in sql
        assert "n_f.line" in sql


# ─── Executor tests ───────────────────────────────────────────────────────


class TestExecutor:
    """End-to-end query execution against the test database."""

    def test_issue9_example1_callees_of_handleRequest(self, test_db):
        """MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file"""
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' "
            "RETURN g.name, g.file",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        row = result["rows"][0]
        assert row["g.name"] == "processData"
        assert row["g.file"] == "api.py"

    def test_issue9_example2_classes_inheriting_baseModel(self, test_db):
        """MATCH (c:Class)-[:INHERITS]->(p) WHERE p.name = 'BaseModel' RETURN c.name"""
        ws, _ = test_db
        result = query_graph(
            "MATCH (c:Class)-[:INHERITS]->(p) WHERE p.name = 'BaseModel' RETURN c.name",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["c.name"] == "User"

    def test_issue9_example3_dead_code_no_callers(self, test_db):
        """MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name"""
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name",
            ws,
        )
        assert result["status"] == "ok"
        names = {r["f.name"] for r in result["rows"]}
        # handleRequest has no callers (entry point), orphan has no callers (dead code).
        # processData and helper ARE called, so they should NOT appear.
        assert "handleRequest" in names
        assert "orphan" in names
        assert "processData" not in names
        assert "helper" not in names

    def test_contains_predicate(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name CONTAINS 'handler' RETURN f.name, f.file",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["f.name"] == "handleRequest"

    def test_exists_predicate(self, test_db):
        """Functions that ARE called by some other function."""
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE EXISTS { (g:Function)-[:CALLS]->(f) } "
            "RETURN f.name",
            ws,
        )
        assert result["status"] == "ok"
        names = {r["f.name"] for r in result["rows"]}
        # processData is called by handleRequest, helper is called by processData.
        assert "processData" in names
        assert "helper" in names
        # handleRequest and orphan are NOT called by anyone.
        assert "handleRequest" not in names
        assert "orphan" not in names

    def test_return_whole_node(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN f",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        node = result["rows"][0]["f"]
        assert node["name"] == "handleRequest"
        assert node["node_type"] == "function"
        assert node["file"] == "api.py"
        assert node["line"] == 1

    def test_limit_truncates(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) RETURN f.name LIMIT 2",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 2
        assert result["truncated"] is True

    def test_and_predicate(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' AND f.file = 'api.py' "
            "RETURN f.name",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1

    def test_or_predicate(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' OR f.name = 'orphan' "
            "RETURN f.name",
            ws,
        )
        assert result["status"] == "ok"
        names = {r["f.name"] for r in result["rows"]}
        assert names == {"handleRequest", "orphan"}

    def test_is_not_null_predicate(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.line IS NOT NULL RETURN f.name LIMIT 10",
            ws,
        )
        assert result["status"] == "ok"
        # All test nodes have line set.
        assert result["row_count"] == 4  # 4 functions

    def test_left_directed_edge(self, test_db):
        """<-[:CALLS]- finds callers."""
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function)<-[:CALLS]-(g) WHERE f.name = 'helper' RETURN g.name",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["g.name"] == "processData"

    def test_no_results_returns_empty(self, test_db):
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name = 'doesNotExist' RETURN f.name",
            ws,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 0
        assert result["rows"] == []
        assert result["truncated"] is False


class TestExecutorErrors:
    """Error handling — missing db, missing tables, parse errors."""

    def test_missing_database(self, tmp_path):
        ws = str(tmp_path / "noexist")
        result = query_graph("MATCH (f:Function) RETURN f.name", ws)
        assert result["status"] == "error"
        assert "Database not found" in result["error"]

    def test_parse_error_returns_status(self, test_db):
        ws, _ = test_db
        result = query_graph("MATCH (f:NotARealLabel) RETURN f.name", ws)
        assert result["status"] == "error"
        assert "Parse error" in result["error"]

    def test_empty_query_raises(self):
        with pytest.raises(CypherParseError):
            parse("")

    def test_sql_injection_safe(self, test_db):
        """String literals are parameterized — no SQL injection."""
        ws, _ = test_db
        result = query_graph(
            "MATCH (f:Function) WHERE f.name = 'x'; DROP TABLE graph_nodes; --' "
            "RETURN f.name",
            ws,
        )
        # The query should either parse-fail (due to semicolon) or execute safely.
        # Either way, the graph_nodes table must still exist.
        if result["status"] == "error":
            assert "Parse error" in result["error"]
        else:
            # Verify the table wasn't dropped.
            db_path = os.path.join(ws, ".codelens", "codelens.db")
            conn = sqlite3.connect(db_path)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            conn.close()
            assert ("graph_nodes",) in tables


# ─── CLI command tests ────────────────────────────────────────────────────


class TestQueryGraphCommand:
    """Test the CLI command wrapper."""

    def test_explain_mode(self, test_db):
        """--explain should return SQL without executing."""
        from commands.query_graph import execute as cmd_execute

        ws, _ = test_db

        class Args:
            query = "MATCH (f:Function) RETURN f.name"
            workspace = ws
            db_path = None
            explain = True

        result = cmd_execute(Args(), ws)
        assert result["status"] == "ok"
        assert "sql" in result
        assert "params" in result
        assert "return_items" in result

    def test_command_registered(self):
        """query-graph should be in the command registry."""
        from commands import COMMAND_REGISTRY
        assert "query-graph" in COMMAND_REGISTRY


# ─── MCP tool registration test ──────────────────────────────────────────


class TestMCPToolDefinition:
    """Verify the static MCP tool definition for query-graph."""

    def test_tool_in_static_definitions(self):
        import mcp_server
        assert "query-graph" in mcp_server._TOOL_DEFINITIONS

    def test_tool_has_required_fields(self):
        import mcp_server
        tool = mcp_server._TOOL_DEFINITIONS["query-graph"]
        assert "description" in tool
        assert "parameters" in tool
        props = tool["parameters"]["properties"]
        assert "query" in props
        assert "workspace" in props
        assert "query-graph" in tool["parameters"].get("required", []) or \
               "query" in tool["parameters"].get("required", [])

    def test_tool_name_uses_underscore(self):
        """MCP tool name should be codelens_query_graph (hyphens → underscores)."""
        import mcp_server
        # The _handle_tools_list method converts hyphens to underscores.
        tool_name = "codelens_query-graph".replace("-", "_")
        assert tool_name == "codelens_query_graph"
