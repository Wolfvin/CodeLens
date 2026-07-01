"""Tests for the Cypher-subset graph query engine (issue #9).

Covers:
- Tokenizer: strings, numbers, operators, brackets, comments
- Parser: MATCH patterns (node + edge), WHERE predicates, RETURN, LIMIT
- SQL compilation: single-node, multi-node, NOT EXISTS subqueries
- Executor: end-to-end queries against a SQLite graph DB
- Edge cases: anonymous nodes (), undirected edges, AND/OR, IS NULL, CONTAINS
- Error handling: parse errors, unknown labels/edges, missing DB, missing tables
- CLI command registration + MCP tool schema
- File headers per CONTRIBUTING.md convention

The tests build a small in-memory SQLite graph with functions, classes, and
edges (CALLS, INHERITS) to exercise the query engine without needing a full
CodeLens scan.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

# Make scripts/ importable.
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from query_graph_engine import (  # noqa: E402
    execute_query,
    validate_query,
    _tokenize,
    _Parser,
    _Query,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def graph_db():
    """Create a small test graph DB and yield (workspace, db_path).

    Graph structure:
        handleRequest --CALLS--> processData --CALLS--> helper
        User --INHERITS--> BaseModel
        unusedFunc (no incoming CALLS — dead code)
        ConfigClass (file is NULL — tests IS NULL)
    """
    tmpdir = tempfile.mkdtemp(prefix="codelens_qg_test_")
    db_path = os.path.join(tmpdir, "codelens.db")
    ws = tmpdir

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE graph_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL UNIQUE,
            node_type TEXT NOT NULL DEFAULT 'function',
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
        CREATE INDEX idx_graph_nodes_type_name ON graph_nodes(node_type, name);
        CREATE INDEX idx_graph_nodes_name ON graph_nodes(name);
        CREATE INDEX idx_graph_edges_source_type ON graph_edges(source_id, edge_type);
        CREATE INDEX idx_graph_edges_target_type ON graph_edges(target_id, edge_type);
    """)
    nodes = [
        ("app.py:1:handleRequest", "function", "handleRequest", "app.py", 1),
        ("app.py:10:processData", "function", "processData", "app.py", 10),
        ("app.py:20:helper", "function", "helper", "app.py", 20),
        ("models.py:1:BaseModel", "class", "BaseModel", "models.py", 1),
        ("models.py:15:User", "class", "User", "models.py", 15),
        ("utils.py:1:unusedFunc", "function", "unusedFunc", "utils.py", 1),
        ("nopath.py:1:ConfigClass", "class", "ConfigClass", None, 1),
    ]
    for n in nodes:
        conn.execute(
            "INSERT INTO graph_nodes (node_id, node_type, name, file, line) VALUES (?,?,?,?,?)",
            n,
        )
    edges = [
        ("app.py:1:handleRequest", "app.py:10:processData", "CALLS", "app.py", 2),
        ("app.py:10:processData", "app.py:20:helper", "CALLS", "app.py", 11),
        ("models.py:15:User", "models.py:1:BaseModel", "INHERITS", "models.py", 16),
    ]
    for e in edges:
        conn.execute(
            "INSERT INTO graph_edges (source_id, target_id, edge_type, file, line) VALUES (?,?,?,?,?)",
            e,
        )
    conn.commit()
    conn.close()

    yield ws, db_path

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def empty_workspace():
    """Yield a temp workspace with no DB (for testing missing-DB errors)."""
    tmpdir = tempfile.mkdtemp(prefix="codelens_qg_empty_")
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Tokenizer ─────────────────────────────────────────────────────────────


class TestTokenizer:
    """Verify the lexer produces correct tokens."""

    def test_basic_keywords(self):
        tokens = _tokenize("MATCH (f:Function) RETURN f.name")
        kinds = [t.kind for t in tokens]
        assert kinds[0] == "KW" and tokens[0].value == "MATCH"
        assert "LPAREN" in kinds
        assert "RPAREN" in kinds

    def test_string_single_quoted(self):
        tokens = _tokenize("WHERE f.name = 'hello'")
        str_tok = [t for t in tokens if t.kind == "STRING"]
        assert len(str_tok) == 1
        assert str_tok[0].value == "hello"

    def test_string_double_quoted(self):
        tokens = _tokenize('WHERE f.name = "hello"')
        str_tok = [t for t in tokens if t.kind == "STRING"]
        assert len(str_tok) == 1
        assert str_tok[0].value == "hello"

    def test_unterminated_string_raises(self):
        with pytest.raises(ValueError, match="Unterminated string"):
            _tokenize("WHERE f.name = 'hello")

    def test_brackets(self):
        tokens = _tokenize("-[:CALLS]->")
        kinds = [t.kind for t in tokens]
        assert "LBRACKET" in kinds
        assert "RBRACKET" in kinds

    def test_arrows(self):
        tokens = _tokenize("-> <- -")
        assert tokens[0].kind == "RARROW"
        assert tokens[1].kind == "LARROW"
        assert tokens[2].kind == "DASH"

    def test_comments_are_skipped(self):
        tokens = _tokenize("MATCH (f:Function) -- this is a comment\nRETURN f.name")
        # No comment text should appear as tokens
        values = [t.value for t in tokens]
        assert "this" not in values
        assert "comment" not in values

    def test_numbers(self):
        tokens = _tokenize("LIMIT 42")
        assert tokens[1].kind == "NUMBER"
        assert tokens[1].value == "42"

    def test_unexpected_char_raises(self):
        with pytest.raises(ValueError, match="Unexpected character"):
            _tokenize("MATCH @ invalid")


# ─── Parser ────────────────────────────────────────────────────────────────


class TestParser:
    """Verify the parser builds correct ASTs."""

    def _parse(self, query):
        return _Parser(_tokenize(query)).parse()

    def test_simple_match_node(self):
        q = self._parse("MATCH (f:Function) RETURN f.name")
        assert len(q.pattern.nodes) == 1
        assert q.pattern.nodes[0].var == "f"
        assert q.pattern.nodes[0].label == "function"  # normalized to lowercase
        assert not q.return_star
        assert q.return_items == [("f", "name")]

    def test_match_with_edge(self):
        q = self._parse("MATCH (f:Function)-[:CALLS]->(g) RETURN g.name")
        assert len(q.pattern.nodes) == 2
        assert len(q.pattern.edges) == 1
        assert q.pattern.edges[0].edge_type == "CALLS"
        assert q.pattern.edges[0].direction == "right"

    def test_left_arrow_edge(self):
        q = self._parse("MATCH (f)<-[:CALLS]-(g) RETURN f.name")
        assert q.pattern.edges[0].direction == "left"

    def test_undirected_edge(self):
        q = self._parse("MATCH (f)-[:CALLS]-(g) RETURN f.name")
        assert q.pattern.edges[0].direction == "none"

    def test_anonymous_node_allowed(self):
        """Bare () is a valid anonymous node — matches any node."""
        q = self._parse("MATCH () RETURN *")
        assert q.pattern.nodes[0].var is None
        assert q.pattern.nodes[0].label is None

    def test_label_case_insensitive(self):
        q = self._parse("MATCH (f:Function) RETURN f.name")
        assert q.pattern.nodes[0].label == "function"
        q2 = self._parse("MATCH (f:FUNCTION) RETURN f.name")
        assert q2.pattern.nodes[0].label == "function"
        q3 = self._parse("MATCH (f:function) RETURN f.name")
        assert q3.pattern.nodes[0].label == "function"

    def test_where_equals(self):
        q = self._parse("MATCH (f) WHERE f.name = 'handleRequest' RETURN f.name")
        assert q.where is not None

    def test_where_contains(self):
        q = self._parse("MATCH (f) WHERE f.name CONTAINS 'handle' RETURN f.name")
        assert q.where is not None

    def test_where_is_null(self):
        q = self._parse("MATCH (f) WHERE f.file IS NULL RETURN f.name")
        assert q.where is not None

    def test_where_is_not_null(self):
        q = self._parse("MATCH (f) WHERE f.file IS NOT NULL RETURN f.name")
        assert q.where is not None

    def test_where_not_exists(self):
        q = self._parse("MATCH (f) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name")
        assert q.where is not None

    def test_where_and(self):
        q = self._parse("MATCH (f) WHERE f.name = 'a' AND f.file = 'b' RETURN f.name")
        assert q.where is not None

    def test_where_or(self):
        q = self._parse("MATCH (f) WHERE f.name = 'a' OR f.name = 'b' RETURN f.name")
        assert q.where is not None

    def test_limit(self):
        q = self._parse("MATCH (f) RETURN f.name LIMIT 5")
        assert q.limit == 5

    def test_return_star(self):
        q = self._parse("MATCH (f) RETURN *")
        assert q.return_star is True
        assert q.return_items == []

    def test_return_multiple_props(self):
        q = self._parse("MATCH (f) RETURN f.name, f.file, f.line")
        assert q.return_items == [("f", "name"), ("f", "file"), ("f", "line")]

    def test_no_return_defaults_to_star(self):
        q = self._parse("MATCH (f:Function)")
        assert q.return_star is True

    def test_unknown_label_raises(self):
        with pytest.raises(ValueError, match="Unknown node label"):
            self._parse("MATCH (f:BogusLabel) RETURN f.name")

    def test_unknown_edge_type_raises(self):
        with pytest.raises(ValueError, match="Unknown edge type"):
            self._parse("MATCH (f)-[:BOGUS]->(g) RETURN f.name")

    def test_query_must_start_with_match(self):
        with pytest.raises(ValueError, match="must start with MATCH"):
            self._parse("RETURN f.name")

    def test_limit_must_be_nonneg(self):
        """Negative LIMIT is rejected. The tokenizer splits -1 into DASH +
        NUMBER, so the parser rejects it at the NUMBER expectation."""
        with pytest.raises(ValueError):
            self._parse("MATCH (f) RETURN f.name LIMIT -1")


# ─── validate_query ────────────────────────────────────────────────────────


class TestValidateQuery:
    """``validate_query`` checks syntax without touching the DB."""

    def test_valid_query(self):
        r = validate_query("MATCH (f:Function) RETURN f.name")
        assert r["valid"] is True

    def test_invalid_query_no_match(self):
        r = validate_query("SELECT * FROM foo")
        assert r["valid"] is False
        assert "MATCH" in r["error"]

    def test_invalid_query_bad_label(self):
        r = validate_query("MATCH (f:BogusLabel) RETURN f.name")
        assert r["valid"] is False
        assert "label" in r["error"].lower()


# ─── execute_query — single-node queries ───────────────────────────────────


class TestExecuteSingleNode:
    """Single-node MATCH queries (no edges)."""

    def test_match_all_functions(self, graph_db):
        ws, db_path = graph_db
        r = execute_query("MATCH (f:Function) RETURN f.name", ws, db_path=db_path)
        assert r["status"] == "ok"
        assert r["count"] == 4  # handleRequest, processData, helper, unusedFunc
        names = [row["f.name"] for row in r["results"]]
        assert "handleRequest" in names
        assert "unusedFunc" in names

    def test_match_all_classes(self, graph_db):
        ws, db_path = graph_db
        r = execute_query("MATCH (c:Class) RETURN c.name", ws, db_path=db_path)
        assert r["status"] == "ok"
        assert r["count"] == 3  # BaseModel, User, ConfigClass

    def test_where_equals(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN f.name, f.file",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["f.name"] == "handleRequest"
        assert r["results"][0]["f.file"] == "app.py"

    def test_where_contains(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE f.name CONTAINS 'est' RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["f.name"] == "handleRequest"

    def test_where_is_null(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (c:Class) WHERE c.file IS NULL RETURN c.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["c.name"] == "ConfigClass"

    def test_where_is_not_null(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (c:Class) WHERE c.file IS NOT NULL RETURN c.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 2  # BaseModel, User
        names = [row["c.name"] for row in r["results"]]
        assert "BaseModel" in names
        assert "User" in names
        assert "ConfigClass" not in names

    def test_limit(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) RETURN f.name LIMIT 2",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 2
        assert r["truncated"] is True
        assert r["limit"] == 2

    def test_return_star(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' RETURN *",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert "f" in r["results"][0]
        assert r["results"][0]["f"]["name"] == "handleRequest"
        assert r["results"][0]["f"]["file"] == "app.py"

    def test_where_and(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE f.name CONTAINS 'e' AND f.file = 'app.py' RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        names = [row["f.name"] for row in r["results"]]
        # Functions with 'e' in name and file=app.py
        assert "handleRequest" in names
        assert "processData" in names  # has 'e'
        assert "helper" in names  # has 'e'
        assert "unusedFunc" not in names  # different file

    def test_where_or(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE f.name = 'handleRequest' OR f.name = 'unusedFunc' RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 2
        names = [row["f.name"] for row in r["results"]]
        assert "handleRequest" in names
        assert "unusedFunc" in names


# ─── execute_query — multi-node queries (edges) ────────────────────────────


class TestExecuteWithEdges:
    """MATCH queries with edges (CALLS, INHERITS)."""

    def test_calls_edge_right(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["g.name"] == "processData"
        assert r["results"][0]["g.file"] == "app.py"

    def test_calls_edge_left(self, graph_db):
        """Reverse direction: who calls helper?"""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f)<-[:CALLS]-(g) WHERE f.name = 'helper' RETURN g.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["g.name"] == "processData"

    def test_inherits_edge(self, graph_db):
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (c:Class)-[:INHERITS]->(p:Class) RETURN c.name, p.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["c.name"] == "User"
        assert r["results"][0]["p.name"] == "BaseModel"

    def test_multi_hop_calls(self, graph_db):
        """Two-hop CALLS: handleRequest -> processData -> helper."""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (a:Function)-[:CALLS]->(b:Function)-[:CALLS]->(c:Function) "
            "WHERE a.name = 'handleRequest' RETURN c.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["c.name"] == "helper"


# ─── execute_query — NOT EXISTS (dead code) ────────────────────────────────


class TestNotExists:
    """NOT EXISTS subqueries — the dead-code detection pattern from issue #9."""

    def test_dead_code_detection(self, graph_db):
        """Functions with no incoming CALLS = dead code / entry points."""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        names = [row["f.name"] for row in r["results"]]
        # handleRequest (entry point) and unusedFunc (truly dead) have no callers.
        # processData and helper are called, so excluded.
        assert "handleRequest" in names
        assert "unusedFunc" in names
        assert "processData" not in names
        assert "helper" not in names

    def test_exists_positive(self, graph_db):
        """EXISTS (without NOT) returns functions that ARE called."""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE EXISTS { ()-[:CALLS]->(f) } RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        names = [row["f.name"] for row in r["results"]]
        assert "processData" in names
        assert "helper" in names
        assert "handleRequest" not in names
        assert "unusedFunc" not in names


# ─── execute_query — error handling ────────────────────────────────────────


class TestErrorHandling:
    """Malformed queries and missing DB produce structured errors, not crashes."""

    def test_parse_error_no_match(self, graph_db):
        ws, db_path = graph_db
        r = execute_query("SELECT * FROM foo", ws, db_path=db_path)
        assert r["status"] == "error"
        assert r["error"] == "parse_error"
        assert "MATCH" in r["message"]

    def test_parse_error_bad_label(self, graph_db):
        ws, db_path = graph_db
        r = execute_query("MATCH (f:BogusLabel) RETURN f.name", ws, db_path=db_path)
        assert r["status"] == "error"
        assert r["error"] == "parse_error"

    def test_missing_database(self, empty_workspace):
        r = execute_query(
            "MATCH (f:Function) RETURN f.name",
            empty_workspace,
        )
        assert r["status"] == "error"
        assert r["error"] == "database_not_found"

    def test_graph_tables_not_initialized(self, empty_workspace):
        """DB exists but graph tables are missing."""
        db_path = os.path.join(empty_workspace, ".codelens", "codelens.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE other_table (id INTEGER)")
        conn.commit()
        conn.close()
        r = execute_query(
            "MATCH (f:Function) RETURN f.name",
            empty_workspace,
        )
        assert r["status"] == "error"
        assert r["error"] == "graph_not_initialized"

    def test_query_echoed_in_result(self, graph_db):
        ws, db_path = graph_db
        query = "MATCH (f:Function) RETURN f.name LIMIT 1"
        r = execute_query(query, ws, db_path=db_path)
        assert r["query"] == query

    def test_truncated_flag(self, graph_db):
        ws, db_path = graph_db
        r = execute_query("MATCH (f:Function) RETURN f.name LIMIT 2", ws, db_path=db_path)
        assert r["truncated"] is True
        r2 = execute_query("MATCH (f:Function) RETURN f.name", ws, db_path=db_path)
        assert r2["truncated"] is False


# ─── CLI command registration ──────────────────────────────────────────────


class TestCliCommandRegistration:
    """The ``query-graph`` command must auto-register from commands/query_graph.py."""

    def test_command_registered(self):
        from commands import COMMAND_REGISTRY
        assert "query-graph" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["query-graph"]
        assert "help" in info
        assert "add_args" in info
        assert "execute" in info
        assert callable(info["add_args"])
        assert callable(info["execute"])

    def test_command_help_mentions_match(self):
        from commands import COMMAND_REGISTRY
        help_text = COMMAND_REGISTRY["query-graph"]["help"]
        assert "MATCH" in help_text
        assert "Cypher" in help_text

    def test_execute_with_validate_flag(self, graph_db):
        """--validate flag checks syntax without touching the DB."""
        from commands import COMMAND_REGISTRY
        from argparse import Namespace
        ws, _ = graph_db
        info = COMMAND_REGISTRY["query-graph"]
        args = Namespace(
            query="MATCH (f:Function) RETURN f.name",
            workspace=ws,
            db_path=None,
            limit=None,
            validate=True,
        )
        r = info["execute"](args, ws)
        assert r["valid"] is True

    def test_execute_with_cli_limit(self, graph_db):
        """--limit flag on CLI appends LIMIT to query."""
        from commands import COMMAND_REGISTRY
        from argparse import Namespace
        ws, db_path = graph_db
        info = COMMAND_REGISTRY["query-graph"]
        args = Namespace(
            query="MATCH (f:Function) RETURN f.name",
            workspace=ws,
            db_path=db_path,
            limit=2,
            validate=False,
        )
        r = info["execute"](args, ws)
        assert r["status"] == "ok"
        assert r["count"] == 2
        assert r["truncated"] is True


# ─── MCP tool registration ─────────────────────────────────────────────────


class TestMcpToolRegistration:
    """The ``query-graph`` MCP tool must be statically defined."""

    def test_tool_in_definitions(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        assert "query-graph" in _TOOL_DEFINITIONS

    def test_tool_schema_has_required_fields(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        schema = _TOOL_DEFINITIONS["query-graph"]
        assert "description" in schema
        assert "parameters" in schema
        params = schema["parameters"]
        assert params["type"] == "object"
        assert "workspace" in params["properties"]
        assert "query" in params["properties"]
        assert "workspace" in params["required"]
        assert "query" in params["required"]

    def test_tool_description_mentions_clauses(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        desc = _TOOL_DEFINITIONS["query-graph"]["description"]
        for clause in ("MATCH", "WHERE", "RETURN", "LIMIT"):
            assert clause in desc

    def test_tool_description_mentions_examples(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        desc = _TOOL_DEFINITIONS["query-graph"]["description"]
        assert "handleRequest" in desc  # example from issue #9
        assert "dead code" in desc.lower() or "NOT EXISTS" in desc


# ─── File headers ──────────────────────────────────────────────────────────


class TestFileHeaders:
    """CONTRIBUTING.md mandates @WHO/@WHAT/@PART/@ENTRY headers on new files."""

    def test_engine_has_file_header(self):
        path = os.path.join(SCRIPT_DIR, "query_graph_engine.py")
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(500)
        assert "# @WHO:" in head
        assert "# @WHAT:" in head
        assert "# @PART:" in head
        assert "# @ENTRY:" in head

    def test_command_has_file_header(self):
        path = os.path.join(SCRIPT_DIR, "commands", "query_graph.py")
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(500)
        assert "# @WHO:" in head
        assert "# @WHAT:" in head
        assert "# @PART:" in head
        assert "# @ENTRY:" in head


# ─── End-to-end: issue #9 spec examples ────────────────────────────────────


class TestIssueSpecExamples:
    """The three example queries from issue #9 must work."""

    def test_example_1_callers_of_handle_request(self, graph_db):
        """MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file"""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name, g.file",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["g.name"] == "processData"

    def test_example_2_dead_code(self, graph_db):
        """MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name"""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (f:Function) WHERE NOT EXISTS { ()-[:CALLS]->(f) } RETURN f.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] >= 1
        # Must include unusedFunc (truly dead) and handleRequest (entry point)
        names = [row["f.name"] for row in r["results"]]
        assert "unusedFunc" in names

    def test_example_3_class_inheritance(self, graph_db):
        """MATCH (c:Class)-[:INHERITS]->(p:Class) RETURN c.name, p.name"""
        ws, db_path = graph_db
        r = execute_query(
            "MATCH (c:Class)-[:INHERITS]->(p:Class) RETURN c.name, p.name",
            ws, db_path=db_path,
        )
        assert r["status"] == "ok"
        assert r["count"] == 1
        assert r["results"][0]["c.name"] == "User"
        assert r["results"][0]["p.name"] == "BaseModel"
