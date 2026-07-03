"""
Tests for issue #177: TS node IDs use backslash paths — breaks affected,
query-graph, semantic-query.

Verifies that node IDs and file paths written to the SQLite graph tables
are normalized to forward slashes at write time, regardless of the
platform's native path separator. This ensures downstream commands
(``affected``, ``query-graph``, ``semantic-query``) that use forward-slash
input can find nodes stored from a Windows scan (which produces backslash
paths via ``os.path.relpath``).
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def tmp_workspace():
    """Create a temp workspace with a fake .codelens/backend.json that
    simulates a Windows scan (backslash path separators in node IDs)."""
    tmpdir = tempfile.mkdtemp(prefix="codelens_issue177_")
    codelens_dir = os.path.join(tmpdir, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)

    # Simulate a Windows scan: node IDs and file paths use backslashes.
    # This is what os.path.relpath produces on Windows. On Unix the
    # normalization is a no-op (no backslashes), so we inject backslashes
    # manually to test the fix cross-platform.
    backend = {
        "nodes": [
            {
                "id": "auth\\google-auth-cache.ts:10:verifyToken",
                "fn": "verifyToken",
                "file": "auth\\google-auth-cache.ts",
                "line": 10,
                "type": "function",
            },
            {
                "id": "auth\\google-auth-cache.ts:45:refreshToken",
                "fn": "refreshToken",
                "file": "auth\\google-auth-cache.ts",
                "line": 45,
                "type": "function",
            },
            {
                "id": "src\\app.ts:5:main",
                "fn": "main",
                "file": "src\\app.ts",
                "line": 5,
                "type": "function",
            },
        ],
        "edges": [
            {
                "from": "src\\app.ts:5:main",
                "to": "auth\\google-auth-cache.ts:10:verifyToken",
                "to_fn": "verifyToken",
                "resolved": True,
            },
            {
                "from": "auth\\google-auth-cache.ts:10:verifyToken",
                "to": "auth\\google-auth-cache.ts:45:refreshToken",
                "to_fn": "refreshToken",
                "resolved": True,
            },
        ],
    }

    with open(os.path.join(codelens_dir, "backend.json"), "w") as f:
        json.dump(backend, f)

    yield tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Tests ────────────────────────────────────────────────────


class TestNodeIDNormalization:
    """Issue #177: node IDs in SQLite must use forward slashes on all
    platforms, even when the flat registry contains backslash paths
    (as produced by os.path.relpath on Windows)."""

    def test_node_ids_use_forward_slashes(self, tmp_workspace):
        """After populate_graph_tables, no node_id should contain a
        backslash — all must be forward-slash normalized."""
        from graph_model import populate_graph_tables, default_db_path

        db_path = default_db_path(tmp_workspace)
        stats = populate_graph_tables(tmp_workspace, db_path)

        assert stats["nodes"] == 3, f"expected 3 nodes, got {stats['nodes']}"

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT node_id FROM graph_nodes")
            node_ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

        assert len(node_ids) == 3
        for nid in node_ids:
            assert "\\" not in nid, (
                f"node_id {nid!r} contains backslash — should be forward-slash normalized"
            )

        # Spot-check: the verifyToken node should have a forward-slash ID
        expected_id = "auth/google-auth-cache.ts:10:verifyToken"
        assert expected_id in node_ids, (
            f"expected normalized ID {expected_id!r} in {node_ids}"
        )

    def test_file_column_uses_forward_slashes(self, tmp_workspace):
        """The ``file`` column of graph_nodes must also be normalized."""
        from graph_model import populate_graph_tables, default_db_path

        db_path = default_db_path(tmp_workspace)
        populate_graph_tables(tmp_workspace, db_path)

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT file FROM graph_nodes")
            files = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

        for f in files:
            assert "\\" not in f, (
                f"file {f!r} contains backslash — should be normalized"
            )

    def test_edge_endpoints_use_forward_slashes(self, tmp_workspace):
        """source_id and target_id in graph_edges must be normalized."""
        from graph_model import populate_graph_tables, default_db_path

        db_path = default_db_path(tmp_workspace)
        stats = populate_graph_tables(tmp_workspace, db_path)

        assert stats["edges"] == 2, f"expected 2 edges, got {stats['edges']}"

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT source_id, target_id FROM graph_edges")
            rows = cursor.fetchall()
        finally:
            conn.close()

        for source_id, target_id in rows:
            assert "\\" not in source_id, (
                f"source_id {source_id!r} contains backslash"
            )
            assert "\\" not in target_id, (
                f"target_id {target_id!r} contains backslash"
            )

    def test_query_graph_contains_finds_normalized_ids(self, tmp_workspace):
        """DoD: query-graph CONTAINS query must find the node after
        normalization. This simulates the issue #177 reproduction:

            query-graph "MATCH (n) WHERE n.id CONTAINS 'google-auth-cache'
                        RETURN n.id LIMIT 5"
        """
        from graph_model import populate_graph_tables, default_db_path

        db_path = default_db_path(tmp_workspace)
        populate_graph_tables(tmp_workspace, db_path)

        conn = sqlite3.connect(db_path)
        try:
            # Simulate the CONTAINS query that query-graph would run
            cursor = conn.execute(
                "SELECT node_id FROM graph_nodes "
                "WHERE node_id LIKE '%google-auth-cache%' LIMIT 5"
            )
            matches = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

        assert len(matches) >= 1, (
            "CONTAINS query returned 0 results — node ID normalization failed"
        )
        for m in matches:
            assert "google-auth-cache" in m
            assert "\\" not in m

    def test_affected_lookup_succeeds_with_forward_slash_input(
        self, tmp_workspace
    ):
        """DoD: affected must find dependents when given a forward-slash
        input path. This verifies the dependents_engine graph keys are
        normalized too."""
        from graph_model import populate_graph_tables, default_db_path
        from dependents_engine import _build_import_graph

        # Populate graph tables (normalizes node IDs)
        db_path = default_db_path(tmp_workspace)
        populate_graph_tables(tmp_workspace, db_path)

        # Create a real TS file so _build_import_graph can walk it.
        # The import graph is file-system based (not SQLite-based), so
        # we need actual files to test the affected command's lookup.
        auth_dir = os.path.join(tmp_workspace, "auth")
        os.makedirs(auth_dir, exist_ok=True)
        with open(os.path.join(auth_dir, "google-auth-cache.ts"), "w") as f:
            f.write("export function verifyToken() {}\n")
            f.write("export function refreshToken() {}\n")

        src_dir = os.path.join(tmp_workspace, "src")
        os.makedirs(src_dir, exist_ok=True)
        with open(os.path.join(src_dir, "app.ts"), "w") as f:
            f.write("import { verifyToken } from '../auth/google-auth-cache';\n")
            f.write("export function main() { verifyToken(); }\n")

        import_graph, reverse_graph = _build_import_graph(tmp_workspace)

        # All keys must be forward-slash normalized
        for key in list(import_graph.keys()) + list(reverse_graph.keys()):
            assert "\\" not in key, (
                f"import graph key {key!r} contains backslash"
            )

        # The forward-slash input must resolve against the graph
        all_known = set(import_graph.keys()) | set(reverse_graph.keys())
        assert "auth/google-auth-cache.ts" in all_known, (
            f"forward-slash path not in graph keys: {all_known}"
        )


class TestIncrementalUpdateNormalization:
    """Issue #177: incremental_graph_update must also normalize node IDs
    so partial re-scans don't introduce backslash IDs into a graph that
    was previously clean."""

    def test_incremental_update_normalizes_backslash_paths(
        self, tmp_workspace
    ):
        """Simulate a Windows incremental scan: changed_files contain
        backslash paths, flat registry has backslash node IDs. After
        incremental_graph_update, the SQLite graph must contain only
        forward-slash IDs."""
        from graph_model import (
            populate_graph_tables,
            incremental_graph_update,
            default_db_path,
        )

        db_path = default_db_path(tmp_workspace)

        # Initial full populate (normalizes everything)
        populate_graph_tables(tmp_workspace, db_path)

        # Now simulate an incremental update on a "changed" file with
        # a backslash path (as os.path.relpath would produce on Windows)
        changed_file = os.path.join(tmp_workspace, "auth", "google-auth-cache.ts")
        stats = incremental_graph_update(
            tmp_workspace, db_path, [changed_file]
        )

        # Verify no backslash IDs remain in the graph
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT node_id FROM graph_nodes")
            node_ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

        for nid in node_ids:
            assert "\\" not in nid, (
                f"node_id {nid!r} contains backslash after incremental update"
            )


class TestNormalizePathSeparators:
    """Unit tests for the _normalize_path_separators helper."""

    def test_backslash_replaced_with_forward_slash(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("auth\\file.ts") == "auth/file.ts"

    def test_forward_slash_unchanged(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("auth/file.ts") == "auth/file.ts"

    def test_mixed_separators(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("src\\auth/file.ts") == "src/auth/file.ts"

    def test_node_id_with_backslash(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("auth\\file.ts:42:fn") == "auth/file.ts:42:fn"

    def test_empty_string_unchanged(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("") == ""

    def test_none_like_unchanged(self):
        from graph_model import _normalize_path_separators
        assert _normalize_path_separators("") == ""
