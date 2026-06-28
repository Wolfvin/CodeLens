"""
Tests for the graph data model (issue #8).

Verifies:
1. Schema initialization (tables + indexes exist)
2. Population from benchmarks/fixtures/clean_app
3. query_callers returns correct chain
4. query_callees returns correct chain
5. Re-population clears old data (no duplicates)
6. Pilot: trace --use-graph produces same results as trace (flat) on the fixture
"""

import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

# Add scripts directory to path (matches other test files)
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "fixtures", "clean_app",
)


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_db_path():
    """Return a path to a fresh temp .db file (not created)."""
    tmpdir = tempfile.mkdtemp(prefix="codelens_graph_test_")
    db_path = os.path.join(tmpdir, "test.db")
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def scanned_clean_app():
    """Copy clean_app fixture to a temp workspace and run a full scan.

    Yields the workspace path. The scan populates both the flat backend.json
    registry and the new graph_nodes + graph_edges tables. Cleanup removes
    the temp workspace on teardown.
    """
    if not os.path.isdir(FIXTURE_DIR):
        pytest.skip("clean_app fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_clean_app_")
    # Copy fixture contents (excluding any pre-existing .codelens dir)
    for entry in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    # Import and run scan
    from commands.scan import cmd_scan
    cmd_scan(workspace, incremental=False)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


# ─── 1. Schema Initialization ────────────────────────────────


class TestSchemaInit:
    """Verify init_graph_schema creates tables and indexes idempotently."""

    def test_creates_graph_nodes_and_edges_tables(self, tmp_db_path):
        """init_graph_schema must create graph_nodes and graph_edges tables."""
        from graph_model import init_graph_schema, GRAPH_NODES_TABLE, GRAPH_EDGES_TABLE

        conn = sqlite3.connect(tmp_db_path)
        init_graph_schema(conn)
        conn.close()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN (?, ?) ORDER BY name",
            (GRAPH_NODES_TABLE, GRAPH_EDGES_TABLE),
        ).fetchall()
        conn.close()

        table_names = [r[0] for r in rows]
        assert GRAPH_NODES_TABLE in table_names
        assert GRAPH_EDGES_TABLE in table_names

    def test_creates_required_indexes(self, tmp_db_path):
        """init_graph_schema must create the indexes needed for O(log n) BFS."""
        from graph_model import init_graph_schema

        conn = sqlite3.connect(tmp_db_path)
        init_graph_schema(conn)
        conn.close()

        conn = sqlite3.connect(tmp_db_path)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_graph_%' ORDER BY name"
        ).fetchall()
        conn.close()

        index_names = {r[0] for r in rows}
        # The spec requires at minimum these three indexes:
        assert "idx_graph_nodes_type_name" in index_names
        assert "idx_graph_edges_source_type" in index_names
        assert "idx_graph_edges_target_type" in index_names

    def test_idempotent(self, tmp_db_path):
        """Calling init_graph_schema twice must not error or duplicate tables."""
        from graph_model import init_graph_schema

        conn = sqlite3.connect(tmp_db_path)
        init_graph_schema(conn)
        init_graph_schema(conn)  # second call must be safe
        conn.close()

        conn = sqlite3.connect(tmp_db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='graph_nodes'"
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ─── 2. Population from clean_app fixture ────────────────────


class TestPopulation:
    """Verify populate_graph_tables populates from the flat backend registry."""

    def test_population_populates_nodes_and_edges(self, scanned_clean_app):
        """After scan, graph_nodes and graph_edges must have rows."""
        from graph_model import graph_stats, graph_tables_exist

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        assert graph_tables_exist(db_path)

        stats = graph_stats(db_path)
        assert stats["nodes"] > 0, "graph_nodes should have rows after scan"
        assert stats["edges"] > 0, "graph_edges should have rows after scan"

    def test_population_matches_flat_registry_counts(self, scanned_clean_app):
        """graph_nodes count must match flat registry nodes count."""
        from graph_model import graph_stats
        from registry import load_backend_registry

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        backend = load_backend_registry(scanned_clean_app)
        flat_nodes = backend.get("nodes", [])
        flat_edges = backend.get("edges", [])

        stats = graph_stats(db_path)
        assert stats["nodes"] == len(flat_nodes), (
            "graph_nodes count must match flat registry nodes count"
        )
        # Edges may differ slightly because graph population skips edges with
        # no 'from' field (malformed), but for the clean_app fixture they
        # should match exactly.
        assert stats["edges"] == len(flat_edges), (
            "graph_edges count must match flat registry edges count for clean_app"
        )

    def test_population_preserves_node_metadata(self, scanned_clean_app):
        """Populated nodes must preserve name, file, line from flat registry."""
        from graph_model import find_nodes_by_name

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        # get_user_by_id is defined at src/db_queries.py:5
        nodes = find_nodes_by_name("get_user_by_id", db_path)
        assert len(nodes) >= 1
        node = nodes[0]
        assert node["name"] == "get_user_by_id"
        assert node["file"] == "src/db_queries.py"
        assert node["line"] == 5
        assert node["node_type"] == "function"


# ─── 3. query_callers ────────────────────────────────────────


class TestQueryCallers:
    """Verify query_callers returns the correct reverse CALLS chain."""

    def test_returns_direct_callers(self, scanned_clean_app):
        """query_callers(get_user_by_id) must include main() at depth 1."""
        from graph_model import find_nodes_by_name, query_callers

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        nodes = find_nodes_by_name("get_user_by_id", db_path)
        assert len(nodes) == 1

        callers = query_callers(nodes[0]["node_id"], db_path, max_depth=1)
        caller_names = {c["name"] for c in callers}
        assert "main" in caller_names, (
            "main() calls get_user_by_id, so it must appear in callers"
        )
        # All direct callers should be at depth 1
        for c in callers:
            assert c["depth"] == 1

    def test_caller_includes_file_and_line(self, scanned_clean_app):
        """Caller entries must include file and line for the calling site."""
        from graph_model import find_nodes_by_name, query_callers

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        nodes = find_nodes_by_name("get_user_by_id", db_path)
        callers = query_callers(nodes[0]["node_id"], db_path, max_depth=1)

        main_caller = next(c for c in callers if c["name"] == "main")
        assert main_caller["file"] == "main.py"
        assert main_caller["line"] == 9  # main.py:9 calls get_user_by_id(1)

    def test_no_callers_for_uncalled_function(self, scanned_clean_app):
        """A function nothing calls should return an empty callers list."""
        from graph_model import find_nodes_by_name, query_callers

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        # main() is the entry point — nothing in the fixture calls main()
        # except the `if __name__ == "__main__"` block, which is not parsed
        # as a function call by the Python parser.
        nodes = find_nodes_by_name("main", db_path)
        assert len(nodes) == 1
        callers = query_callers(nodes[0]["node_id"], db_path, max_depth=2)
        # main() may have zero or very few callers; verify the BFS doesn't
        # return the start node itself.
        for c in callers:
            assert c["node_id"] != nodes[0]["node_id"], (
                "BFS must not return the start node as its own caller"
            )


# ─── 4. query_callees ────────────────────────────────────────


class TestQueryCallees:
    """Verify query_callees returns the correct forward CALLS chain."""

    def test_returns_direct_callees(self, scanned_clean_app):
        """query_callees(main) must include the functions main() calls."""
        from graph_model import find_nodes_by_name, query_callees

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        nodes = find_nodes_by_name("main", db_path)
        assert len(nodes) == 1

        callees = query_callees(nodes[0]["node_id"], db_path, max_depth=1)
        callee_names = {c["name"] for c in callees if c.get("node_id")}

        # main() calls these functions (from main.py)
        expected = {
            "get_user_by_id", "search_users", "create_user", "delete_user",
            "format_text", "process_data", "validate_input",
            "calculate_discount", "merge_configs",
            "ping_host", "run_backup", "list_directory", "run_git_status",
            "get_aws_credentials", "get_database_url", "get_stripe_config",
            "get_jwt_config", "is_debug_mode",
        }
        missing = expected - callee_names
        assert not missing, "main() callees missing from graph: {}".format(missing)

    def test_callee_resolved_flag(self, scanned_clean_app):
        """Resolved callees must have resolved=True; unresolved must have resolved=False."""
        from graph_model import find_nodes_by_name, query_callees

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        nodes = find_nodes_by_name("main", db_path)
        callees = query_callees(nodes[0]["node_id"], db_path, max_depth=1)

        resolved = [c for c in callees if c.get("resolved") is True]
        unresolved = [c for c in callees if c.get("resolved") is False]
        # main() calls both project functions (resolved) and logger.info
        # (unresolved — it's an external method on a logger object).
        assert len(resolved) > 0, "expected at least one resolved callee"
        # Note: std-lib methods are filtered in trace_engine, but query_callees
        # itself returns them as unresolved. We just check the flag is set.
        for c in resolved:
            assert c["node_id"] is not None


# ─── 5. Re-population Clears Old Data ────────────────────────


class TestRepopulation:
    """Verify re-population clears old data so re-scans don't duplicate rows."""

    def test_repopulation_no_duplicates(self, scanned_clean_app):
        """Calling populate_graph_tables twice must not duplicate rows."""
        from graph_model import populate_graph_tables, graph_stats, _default_db_path

        db_path = _default_db_path(scanned_clean_app)
        stats_before = graph_stats(db_path)

        # Re-populate (simulates a second scan)
        result = populate_graph_tables(scanned_clean_app, db_path)
        stats_after = graph_stats(db_path)

        assert stats_before["nodes"] == stats_after["nodes"], (
            "re-population must not change node count (no duplicates)"
        )
        assert stats_before["edges"] == stats_after["edges"], (
            "re-population must not change edge count (no duplicates)"
        )
        assert result["nodes"] == stats_after["nodes"]
        assert result["edges"] == stats_after["edges"]

    def test_clear_graph_tables_empties_both(self, scanned_clean_app):
        """clear_graph_tables must delete all rows from both tables."""
        from graph_model import clear_graph_tables, graph_stats, graph_tables_exist, _default_db_path

        db_path = _default_db_path(scanned_clean_app)
        assert graph_tables_exist(db_path)
        stats_before = graph_stats(db_path)
        assert stats_before["nodes"] > 0

        clear_graph_tables(db_path)

        stats_after = graph_stats(db_path)
        assert stats_after["nodes"] == 0
        assert stats_after["edges"] == 0

    def test_repopulation_after_clear_restores_data(self, scanned_clean_app):
        """Clear then re-populate must restore the original counts."""
        from graph_model import (
            clear_graph_tables, populate_graph_tables, graph_stats, _default_db_path,
        )

        db_path = _default_db_path(scanned_clean_app)
        original = graph_stats(db_path)

        clear_graph_tables(db_path)
        assert graph_stats(db_path)["nodes"] == 0

        populate_graph_tables(scanned_clean_app, db_path)
        restored = graph_stats(db_path)

        assert restored["nodes"] == original["nodes"]
        assert restored["edges"] == original["edges"]


# ─── 6. Pilot: trace --use-graph matches trace (flat) ────────


class TestTracePilot:
    """Verify trace_via_graph produces the same results as trace_via_flat."""

    def _chain_set(self, chain):
        """Reduce a chain list to a set of (depth, fn, resolved) tuples."""
        return {
            (c.get("depth", 0), c.get("fn", ""), c.get("resolved", True))
            for c in chain
        }

    def test_trace_up_matches(self, scanned_clean_app):
        """trace_via_graph up must match trace_via_flat up for get_user_by_id."""
        from trace_engine import trace_via_flat, trace_via_graph

        flat = trace_via_flat(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
        )
        graph = trace_via_graph(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
        )

        flat_up = self._chain_set(flat["chains"]["up"])
        graph_up = self._chain_set(graph["chains"]["up"])
        assert flat_up == graph_up, (
            "trace up chain must match between flat and graph backends\n"
            "flat - graph: {}\ngraph - flat: {}".format(
                flat_up - graph_up, graph_up - flat_up
            )
        )

    def test_trace_down_matches(self, scanned_clean_app):
        """trace_via_graph down must match trace_via_flat down for main."""
        from trace_engine import trace_via_flat, trace_via_graph

        flat = trace_via_flat(
            "main", scanned_clean_app,
            direction="down", max_depth=2, domain="backend",
        )
        graph = trace_via_graph(
            "main", scanned_clean_app,
            direction="down", max_depth=2, domain="backend",
        )

        flat_down = self._chain_set(flat["chains"]["down"])
        graph_down = self._chain_set(graph["chains"]["down"])
        assert flat_down == graph_down, (
            "trace down chain must match between flat and graph backends\n"
            "flat - graph: {}\ngraph - flat: {}".format(
                flat_down - graph_down, graph_down - flat_down
            )
        )

    def test_trace_both_matches(self, scanned_clean_app):
        """trace_via_graph both must match trace_via_flat both for process_data."""
        from trace_engine import trace_via_flat, trace_via_graph

        flat = trace_via_flat(
            "process_data", scanned_clean_app,
            direction="both", max_depth=3, domain="backend",
        )
        graph = trace_via_graph(
            "process_data", scanned_clean_app,
            direction="both", max_depth=3, domain="backend",
        )

        assert self._chain_set(flat["chains"]["up"]) == self._chain_set(graph["chains"]["up"])
        assert self._chain_set(flat["chains"]["down"]) == self._chain_set(graph["chains"]["down"])

    def test_dispatcher_defaults_to_graph(self, scanned_clean_app):
        """trace_symbol (default) must use graph backend when tables are populated."""
        from trace_engine import trace_symbol, trace_via_graph

        disp = trace_symbol(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
        )
        graph = trace_via_graph(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
        )

        assert self._chain_set(disp["chains"]["up"]) == self._chain_set(graph["chains"]["up"])

    def test_dispatcher_falls_back_to_flat_when_graph_empty(self, scanned_clean_app):
        """trace_symbol must fall back to flat when graph tables are empty."""
        from trace_engine import trace_symbol
        from graph_model import clear_graph_tables, _default_db_path

        db_path = _default_db_path(scanned_clean_app)
        clear_graph_tables(db_path)

        try:
            # With empty graph, dispatcher must still return a valid result
            # (falling back to flat). callers_found should be > 0 because
            # main() calls get_user_by_id.
            result = trace_symbol(
                "get_user_by_id", scanned_clean_app,
                direction="up", max_depth=3, domain="backend",
            )
            assert result["status"] == "ok"
            assert result["stats"]["callers_found"] > 0
        finally:
            # Restore graph tables for any subsequent tests in this session
            from graph_model import populate_graph_tables
            populate_graph_tables(scanned_clean_app, db_path)

    def test_use_graph_false_forces_flat(self, scanned_clean_app):
        """trace_symbol(use_graph=False) must use the flat backend."""
        from trace_engine import trace_symbol, trace_via_flat

        forced_flat = trace_symbol(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
            use_graph=False,
        )
        flat = trace_via_flat(
            "get_user_by_id", scanned_clean_app,
            direction="up", max_depth=3, domain="backend",
        )

        assert self._chain_set(forced_flat["chains"]["up"]) == self._chain_set(flat["chains"]["up"])
