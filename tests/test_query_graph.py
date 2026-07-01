"""
Tests for scripts/commands/query_graph.py — the CLI command that wraps
the Cypher parser + evaluator.

Verifies:
  1. Command is registered in the CLI registry as "query-graph".
  2. run_query_graph() returns a structured result dict for valid queries.
  3. Parse errors are returned as ``status: "error"`` (not raised).
  4. Missing database / graph tables are returned as ``status: "error"``.
  5. End-to-end: build a fixture DB, run a query, assert the rows.

Run: python -m pytest tests/test_query_graph.py -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from commands import get_all_commands  # noqa: E402
from commands.query_graph import add_args, execute, run_query_graph  # noqa: E402


# ---------------------------------------------------------------------------
# Command registration
# ---------------------------------------------------------------------------


class TestCommandRegistration:
    def test_query_graph_is_registered(self):
        registry = get_all_commands()
        assert "query-graph" in registry, (
            "'query-graph' must be in the command registry"
        )

    def test_query_graph_has_add_args_and_execute(self):
        registry = get_all_commands()
        cmd = registry["query-graph"]
        assert callable(cmd["add_args"])
        assert callable(cmd["execute"])

    def test_add_args_defines_query_positional(self):
        """The command must take the query string as a positional arg."""
        import argparse
        parser = argparse.ArgumentParser()
        add_args(parser)
        # Parse with a query string + workspace
        args = parser.parse_args(["MATCH (f) RETURN f.name", "/tmp/ws"])
        assert args.query == "MATCH (f) RETURN f.name"
        assert args.workspace == "/tmp/ws"

    def test_add_args_workspace_is_optional(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_args(parser)
        args = parser.parse_args(["MATCH (f) RETURN f.name"])
        assert args.workspace is None

    def test_add_args_db_path_optional(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_args(parser)
        args = parser.parse_args(["MATCH (f) RETURN f.name", "--db-path", "/tmp/x.db"])
        assert args.db_path == "/tmp/x.db"


# ---------------------------------------------------------------------------
# run_query_graph — error cases (must return structured errors, not raise)
# ---------------------------------------------------------------------------


class TestRunQueryGraphErrorCases:
    def test_parse_error_returns_structured_error(self, tmp_path):
        """A malformed query must return status=error, not raise."""
        result = run_query_graph(
            "MATCH (f) WHERE",  # incomplete WHERE
            str(tmp_path),
        )
        assert result["status"] == "error"
        assert "CypherParseError" in result["error"]
        assert result["query"] == "MATCH (f) WHERE"

    def test_missing_database_returns_structured_error(self, tmp_path):
        """When the SQLite database does not exist, return status=error."""
        # Use a workspace path where no .codelens/codelens.db exists
        result = run_query_graph(
            "MATCH (f) RETURN f.name",
            str(tmp_path),
        )
        assert result["status"] == "error"
        assert "database not found" in result["error"]

    def test_missing_graph_tables_returns_structured_error(self, tmp_path):
        """When the database exists but graph tables don't, return error."""
        db_path = tmp_path / "codelens.db"
        # Create an empty SQLite database (no graph tables)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (id INTEGER)")
        conn.commit()
        conn.close()
        result = run_query_graph(
            "MATCH (f) RETURN f.name",
            str(tmp_path),
            db_path=str(db_path),
        )
        assert result["status"] == "error"
        assert "graph tables not initialized" in result["error"]


# ---------------------------------------------------------------------------
# run_query_graph — happy path with a fixture database
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_workspace(tmp_path):
    """Build a workspace dir with a populated codelens.db.

    Returns the workspace path. The database lives at
    ``<workspace>/.codelens/codelens.db`` per the CodeLens convention.
    """
    workspace = tmp_path / "ws"
    codelens_dir = workspace / ".codelens"
    codelens_dir.mkdir(parents=True)
    db_path = codelens_dir / "codelens.db"
    conn = sqlite3.connect(str(db_path))
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
            ('f3', 'function', 'validate', 'utils.py', 5);
        INSERT INTO graph_edges (source_id, target_id, edge_type) VALUES
            ('f1', 'f2', 'CALLS'),
            ('f2', 'f3', 'CALLS');
    """)
    conn.commit()
    conn.close()
    return str(workspace)


class TestRunQueryGraphHappyPath:
    def test_valid_query_returns_rows(self, fixture_workspace):
        result = run_query_graph(
            "MATCH (f:Function) RETURN f.name, f.file",
            fixture_workspace,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 3
        names = {r["name"] for r in result["rows"]}
        assert names == {"handleRequest", "processData", "validate"}

    def test_valid_query_with_where(self, fixture_workspace):
        result = run_query_graph(
            "MATCH (f) WHERE f.name = 'handleRequest' RETURN f.file",
            fixture_workspace,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["file"] == "api.py"

    def test_valid_query_with_relationship(self, fixture_workspace):
        result = run_query_graph(
            "MATCH (f)-[:CALLS]->(g) WHERE f.name = 'handleRequest' RETURN g.name",
            fixture_workspace,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "processData"

    def test_valid_query_with_not_exists(self, fixture_workspace):
        """Dead-code detection: functions with no callers."""
        result = run_query_graph(
            "MATCH (f:Function) WHERE NOT EXISTS { (g)-[:CALLS]->(f) } RETURN f.name",
            fixture_workspace,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "handleRequest"

    def test_valid_query_with_limit(self, fixture_workspace):
        result = run_query_graph(
            "MATCH (f) RETURN f.name LIMIT 2",
            fixture_workspace,
        )
        assert result["status"] == "ok"
        assert result["row_count"] == 2

    def test_result_includes_workspace_abs_path(self, fixture_workspace):
        result = run_query_graph(
            "MATCH (f) RETURN f.name",
            fixture_workspace,
        )
        assert result["workspace"] == os.path.abspath(fixture_workspace)

    def test_result_includes_original_query_string(self, fixture_workspace):
        q = "MATCH (f) RETURN f.name"
        result = run_query_graph(q, fixture_workspace)
        assert result["query"] == q


# ---------------------------------------------------------------------------
# execute() — the command entry point used by the CLI dispatcher
# ---------------------------------------------------------------------------


class TestExecuteEntryPoint:
    def test_execute_calls_run_query_graph(self, fixture_workspace):
        """execute(args, workspace) must produce the same result as
        run_query_graph(args.query, workspace)."""
        args = SimpleNamespace(
            query="MATCH (f) RETURN f.name",
            workspace=None,
            db_path=None,
        )
        result = execute(args, fixture_workspace)
        assert result["status"] == "ok"
        assert result["row_count"] == 3

    def test_execute_with_db_path_override(self, fixture_workspace):
        """When --db-path is supplied, execute() must use it instead of
        the default <workspace>/.codelens/codelens.db path."""
        # Build an alternative database with different content
        alt_db = os.path.join(fixture_workspace, "alt.db")
        conn = sqlite3.connect(alt_db)
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
                file TEXT, line INTEGER,
                confidence REAL NOT NULL DEFAULT 1.0,
                extra_json TEXT
            );
            INSERT INTO graph_nodes (node_id, node_type, name, file, line) VALUES
                ('alt1', 'function', 'altFunction', 'alt.py', 1);
        """)
        conn.commit()
        conn.close()

        args = SimpleNamespace(
            query="MATCH (f) RETURN f.name",
            workspace=None,
            db_path=alt_db,
        )
        result = execute(args, fixture_workspace)
        assert result["status"] == "ok"
        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "altFunction"
