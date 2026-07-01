"""
Tests for scripts/cypher_parser.py — openCypher-subset parser + evaluator.

Covers the MVP scope of issue #9:
  - Tokenizer: parens, colons, identifiers, strings, arrows, operators
  - Parser: MATCH, WHERE, RETURN, LIMIT, NOT EXISTS
  - Evaluator: runs parsed Query against fixture SQLite database,
    verifies returned rows match expectations.

The evaluator tests build a small in-memory SQLite database with the
CodeLens graph_nodes + graph_edges schema and populate it with 5 nodes
+ 3 edges. This mirrors the real graph_model.py schema but is small
enough to assert exact row counts.

Run: python -m pytest tests/test_cypher_parser.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from cypher_parser import (  # noqa: E402
    Comparison,
    CypherParseError,
    NodePattern,
    NotExistsPattern,
    PathPattern,
    Query,
    RelationshipPattern,
    ReturnItem,
    evaluate,
    parse_query,
    tokenize,
)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_simple_query_tokens(self):
        tokens = tokenize("MATCH (f:Function) RETURN f.name")
        kinds = [t[0] for t in tokens]
        assert kinds == [
            "IDENT", "LPAREN", "IDENT", "COLON", "IDENT", "RPAREN",
            "IDENT", "IDENT", "DOT", "IDENT",
        ]

    def test_relationship_tokens(self):
        tokens = tokenize("MATCH (f)-[:CALLS]->(g) RETURN g")
        kinds = [t[0] for t in tokens]
        assert "LBRACKET" in kinds
        assert "RBRACKET" in kinds
        assert kinds.count("DASH") == 2  # one before [:CALLS], one before >
        assert "GT" in kinds

    def test_string_literals_single_and_double_quote(self):
        tokens = tokenize("WHERE f.name = 'hello' AND g.name = \"world\"")
        string_tokens = [t for t in tokens if t[0] == "STRING"]
        assert len(string_tokens) == 2
        assert string_tokens[0][1] == "'hello'"
        assert string_tokens[1][1] == '"world"'

    def test_comments_are_dropped(self):
        tokens = tokenize("MATCH (f) // this is a comment\nRETURN f")
        # No comment text should appear in any token
        for kind, text in tokens:
            assert "comment" not in text.lower()

    def test_unexpected_char_raises(self):
        with pytest.raises(CypherParseError, match="unexpected character"):
            tokenize("MATCH (f) @ RETURN f")


# ---------------------------------------------------------------------------
# Parser — supported query shapes
# ---------------------------------------------------------------------------


class TestParserSupportedShapes:
    def test_single_node_match_with_label(self):
        q = parse_query("MATCH (f:Function) RETURN f.name")
        assert len(q.match) == 1
        assert q.match[0].nodes[0] == NodePattern(variable="f", labels=["Function"])
        assert q.return_items == [ReturnItem(variable="f", property="name")]

    def test_single_node_match_no_label(self):
        q = parse_query("MATCH (n) RETURN n")
        assert q.match[0].nodes[0] == NodePattern(variable="n", labels=[])
        assert q.return_items == [ReturnItem(variable="n", property="")]

    def test_relationship_right_direction(self):
        q = parse_query("MATCH (f)-[:CALLS]->(g) RETURN f.name, g.name")
        rel = q.match[0].relationships[0]
        assert rel.edge_type == "CALLS"
        assert rel.direction == "right"

    def test_relationship_left_direction(self):
        q = parse_query("MATCH (f)<-[:CALLS]-(g) RETURN f.name")
        rel = q.match[0].relationships[0]
        assert rel.edge_type == "CALLS"
        assert rel.direction == "left"

    def test_relationship_no_type(self):
        q = parse_query("MATCH (f)-->(g) RETURN f.name")
        rel = q.match[0].relationships[0]
        assert rel.edge_type == ""
        assert rel.direction == "right"

    def test_where_equality_string(self):
        q = parse_query("MATCH (f) WHERE f.name = 'handleRequest' RETURN f.name")
        pred = q.where[0]
        assert isinstance(pred, Comparison)
        assert pred.variable == "f"
        assert pred.property == "name"
        assert pred.operator == "="
        assert pred.value == "handleRequest"

    def test_where_not_equal(self):
        q = parse_query("MATCH (f) WHERE f.name != 'test' RETURN f.name")
        assert q.where[0].operator == "!="
        assert q.where[0].value == "test"

    def test_where_contains(self):
        q = parse_query("MATCH (n) WHERE n.name CONTAINS 'handler' RETURN n.name")
        assert q.where[0].operator == "CONTAINS"
        assert q.where[0].value == "handler"

    def test_where_is_null(self):
        q = parse_query("MATCH (f) WHERE f.file IS NULL RETURN f.name")
        assert q.where[0].operator == "IS NULL"

    def test_where_is_not_null(self):
        q = parse_query("MATCH (f) WHERE f.file IS NOT NULL RETURN f.name")
        assert q.where[0].operator == "IS NOT NULL"

    def test_where_not_exists(self):
        q = parse_query(
            "MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) } RETURN f.name"
        )
        pred = q.where[0]
        assert isinstance(pred, NotExistsPattern)
        assert len(pred.path.nodes) == 2
        assert len(pred.path.relationships) == 1
        assert pred.path.relationships[0].edge_type == "CALLS"

    def test_limit(self):
        q = parse_query("MATCH (f) RETURN f.name LIMIT 10")
        assert q.limit == 10

    def test_no_limit_defaults_none(self):
        q = parse_query("MATCH (f) RETURN f.name")
        assert q.limit is None

    def test_multiple_return_items(self):
        q = parse_query("MATCH (f) RETURN f.name, f.file, f.line")
        assert len(q.return_items) == 3
        assert q.return_items[0] == ReturnItem(variable="f", property="name")
        assert q.return_items[1] == ReturnItem(variable="f", property="file")
        assert q.return_items[2] == ReturnItem(variable="f", property="line")

    def test_whole_node_return(self):
        q = parse_query("MATCH (f) RETURN f")
        assert q.return_items == [ReturnItem(variable="f", property="")]


# ---------------------------------------------------------------------------
# Parser — error cases (MVP scope boundaries)
# ---------------------------------------------------------------------------


class TestParserErrorCases:
    def test_missing_match_raises(self):
        with pytest.raises(CypherParseError, match="must start with MATCH"):
            parse_query("RETURN f.name")

    def test_missing_return_raises(self):
        with pytest.raises(CypherParseError, match="must have a RETURN"):
            parse_query("MATCH (f) WHERE f.name = 'x'")

    def test_and_not_supported(self):
        with pytest.raises(CypherParseError, match="does not support AND"):
            parse_query(
                "MATCH (f) WHERE f.name = 'a' AND f.file = 'b' RETURN f.name"
            )

    def test_or_not_supported(self):
        with pytest.raises(CypherParseError, match="does not support OR"):
            parse_query(
                "MATCH (f) WHERE f.name = 'a' OR f.name = 'b' RETURN f.name"
            )

    def test_exists_without_not_raises(self):
        with pytest.raises(CypherParseError, match="only supports NOT EXISTS"):
            parse_query(
                "MATCH (f) WHERE EXISTS { (g)-[:CALLS]->(f) } RETURN f.name"
            )

    def test_trailing_tokens_raise(self):
        with pytest.raises(CypherParseError, match="trailing token"):
            parse_query("MATCH (f) RETURN f.name extra-stuff")

    def test_empty_query_raises(self):
        with pytest.raises(CypherParseError, match="empty query"):
            parse_query("")

    def test_unsupported_operator_raises(self):
        with pytest.raises(CypherParseError, match="unsupported operator"):
            parse_query("MATCH (f) WHERE f.name > 'x' RETURN f.name")


# ---------------------------------------------------------------------------
# Evaluator — runs against a fixture SQLite database
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_db():
    """Build a small in-memory SQLite DB with the CodeLens graph schema.

    Topology:
        f1 (handleRequest) -[:CALLS]-> f2 (processData) -[:CALLS]-> f3 (validate)
        c2 (User) -[:INHERITS]-> c1 (BaseModel)

    f1 has no callers (dead-code candidate via NOT EXISTS).
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE graph_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL UNIQUE,
            node_type TEXT NOT NULL,
            name TEXT NOT NULL,
            file TEXT,
            line INTEGER,
            extra_json TEXT
        );
        CREATE TABLE graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT,
            edge_type TEXT NOT NULL,
            file TEXT,
            line INTEGER,
            confidence REAL NOT NULL DEFAULT 1.0,
            extra_json TEXT
        );
        INSERT INTO graph_nodes (node_id, node_type, name, file, line) VALUES
            ('f1', 'function', 'handleRequest', 'api.py', 10),
            ('f2', 'function', 'processData', 'api.py', 20),
            ('f3', 'function', 'validate', 'utils.py', 5),
            ('c1', 'class', 'BaseModel', 'models.py', 1),
            ('c2', 'class', 'User', 'models.py', 10);
        INSERT INTO graph_edges (source_id, target_id, edge_type) VALUES
            ('f1', 'f2', 'CALLS'),
            ('f2', 'f3', 'CALLS'),
            ('c2', 'c1', 'INHERITS');
    """)
    conn.commit()
    conn.close()
    yield db_path
    os.unlink(db_path)


class TestEvaluator:
    def test_match_all_functions(self, fixture_db):
        q = parse_query("MATCH (f:Function) RETURN f.name, f.file")
        rows = evaluate(q, fixture_db)
        assert len(rows) == 3
        names = {r["name"] for r in rows}
        assert names == {"handleRequest", "processData", "validate"}

    def test_match_all_classes(self, fixture_db):
        q = parse_query("MATCH (c:Class) RETURN c.name")
        rows = evaluate(q, fixture_db)
        assert len(rows) == 2
        names = {r["name"] for r in rows}
        assert names == {"BaseModel", "User"}

    def test_match_all_nodes_no_label(self, fixture_db):
        q = parse_query("MATCH (n) RETURN n.name")
        rows = evaluate(q, fixture_db)
        assert len(rows) == 5

    def test_where_equality_filters(self, fixture_db):
        q = parse_query(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN f.file"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 1
        assert rows[0]["file"] == "api.py"

    def test_where_contains(self, fixture_db):
        q = parse_query(
            "MATCH (n) WHERE n.name CONTAINS 'e' RETURN n.name"
        )
        rows = evaluate(q, fixture_db)
        # 'handleRequest', 'processData', 'validate', 'BaseModel', 'User' all contain 'e'
        assert len(rows) == 5

    def test_where_not_equal(self, fixture_db):
        q = parse_query(
            "MATCH (f:Function) WHERE f.name != 'handleRequest' RETURN f.name"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 2
        assert "handleRequest" not in {r["name"] for r in rows}

    def test_where_is_not_null_file(self, fixture_db):
        q = parse_query(
            "MATCH (f:Function) WHERE f.file IS NOT NULL RETURN f.name"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 3  # all 3 functions have non-null file

    def test_relationship_callers_of_handleRequest(self, fixture_db):
        """MATCH (f)-[:CALLS]->(g) WHERE g.name = 'handleRequest' RETURN f.name
        — should return 0 rows (handleRequest has no callers)."""
        q = parse_query(
            "MATCH (f)-[:CALLS]->(g) WHERE g.name = 'handleRequest' RETURN f.name"
        )
        rows = evaluate(q, fixture_db)
        assert rows == []

    def test_relationship_callees_of_handleRequest(self, fixture_db):
        """MATCH (f)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name
        — should return processData."""
        q = parse_query(
            "MATCH (f)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 1
        assert rows[0]["name"] == "processData"

    def test_relationship_inherits_basemodel(self, fixture_db):
        q = parse_query(
            "MATCH (c:Class)-[:INHERITS]->(p) WHERE p.name = 'BaseModel' RETURN c.name"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 1
        assert rows[0]["name"] == "User"

    def test_not_exists_dead_code_detection(self, fixture_db):
        """MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) }
        RETURN f.name — should return handleRequest (no callers)."""
        q = parse_query(
            "MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) } RETURN f.name"
        )
        rows = evaluate(q, fixture_db)
        assert len(rows) == 1
        assert rows[0]["name"] == "handleRequest"

    def test_limit_caps_results(self, fixture_db):
        q = parse_query("MATCH (n) RETURN n.name LIMIT 2")
        rows = evaluate(q, fixture_db)
        assert len(rows) == 2

    def test_whole_node_return_includes_all_fields(self, fixture_db):
        q = parse_query("MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN f")
        rows = evaluate(q, fixture_db)
        assert len(rows) == 1
        row = rows[0]
        # Whole-node RETURN produces columns prefixed with the variable
        assert row["f_node_id"] == "f1"
        assert row["f_name"] == "handleRequest"
        assert row["f_file"] == "api.py"
        assert row["f_line"] == 10
        assert row["f_node_type"] == "function"

    def test_case_insensitive_label(self, fixture_db):
        """Both :Function and :function should match the same rows."""
        q_upper = parse_query("MATCH (f:Function) RETURN f.name")
        q_lower = parse_query("MATCH (f:function) RETURN f.name")
        rows_upper = evaluate(q_upper, fixture_db)
        rows_lower = evaluate(q_lower, fixture_db)
        assert len(rows_upper) == len(rows_lower) == 3

    def test_case_insensitive_edge_type(self, fixture_db):
        """Both :CALLS and :calls should match the same edges."""
        q_upper = parse_query(
            "MATCH (f)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name"
        )
        q_lower = parse_query(
            "MATCH (f)-[:calls]->(g) WHERE f.name = 'handleRequest' RETURN g.name"
        )
        rows_upper = evaluate(q_upper, fixture_db)
        rows_lower = evaluate(q_lower, fixture_db)
        assert len(rows_upper) == len(rows_lower) == 1


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    def test_ast_dataclasses_are_frozen_compatible(self):
        """AST dataclasses must be constructible with keyword args."""
        n = NodePattern(variable="f", labels=["Function"])
        assert n.variable == "f"
        assert n.labels == ["Function"]

        r = RelationshipPattern(edge_type="CALLS", direction="right")
        assert r.edge_type == "CALLS"
        assert r.direction == "right"

        p = PathPattern(nodes=[n], relationships=[r])
        assert len(p.nodes) == 1
        assert len(p.relationships) == 1

        q = Query(match=[p], return_items=[ReturnItem(variable="f", property="name")])
        assert len(q.match) == 1
        assert len(q.return_items) == 1
