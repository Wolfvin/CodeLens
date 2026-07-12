"""Tests for the export-snapshot command (issue #218).

Companion to import-snapshot: import-snapshot was permanently broken since
issue #195 dropped the standalone export-snapshot command without leaving
any way to produce the .codelens.gz file it reads. These tests verify the
new `deps --check export-snapshot` sub-mode writes a snapshot that
`deps --check import-snapshot` can load back (round trip), and that the
bare `codelens deps <workspace>` default does not attempt either
snapshot check (they are side-effecting, opt-in only).
"""

import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from commands.export_snapshot import cmd_export_snapshot  # noqa: E402
from commands.import_snapshot import cmd_import_snapshot  # noqa: E402
from commands.deps import _parse_checks, ALL_CHECKS  # noqa: E402


@pytest.fixture
def scanned_workspace():
    """A workspace with a minimal graph DB already populated."""
    tmpdir = tempfile.mkdtemp(prefix="codelens_export_snapshot_test_")
    codelens_dir = os.path.join(tmpdir, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    db_path = os.path.join(codelens_dir, "codelens.db")

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
    """)
    conn.execute(
        "INSERT INTO graph_nodes (node_id, node_type, name, file, line) "
        "VALUES ('a.py:1:foo', 'function', 'foo', 'a.py', 1)"
    )
    conn.execute(
        "INSERT INTO graph_nodes (node_id, node_type, name, file, line) "
        "VALUES ('a.py:5:bar', 'function', 'bar', 'a.py', 5)"
    )
    conn.execute(
        "INSERT INTO graph_edges (source_id, target_id, edge_type, file, line) "
        "VALUES ('a.py:1:foo', 'a.py:5:bar', 'CALLS', 'a.py', 2)"
    )
    conn.commit()
    conn.close()

    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestExportSnapshot:
    def test_export_creates_gz_file(self, scanned_workspace):
        result = cmd_export_snapshot(scanned_workspace)
        assert result["status"] == "ok"
        assert os.path.isfile(result["output_path"])
        assert result["bytes_written"] > 0
        assert result["header"]["node_count"] == 2
        assert result["header"]["edge_count"] == 1

    def test_export_missing_db_returns_error(self):
        empty_ws = tempfile.mkdtemp(prefix="codelens_export_snapshot_empty_")
        try:
            result = cmd_export_snapshot(empty_ws)
            assert result["status"] == "error"
            assert "error" in result
        finally:
            shutil.rmtree(empty_ws, ignore_errors=True)

    def test_export_custom_output_path(self, scanned_workspace):
        custom_path = os.path.join(scanned_workspace, "custom.codelens.gz")
        result = cmd_export_snapshot(scanned_workspace, output_path=custom_path)
        assert result["status"] == "ok"
        assert result["output_path"] == custom_path
        assert os.path.isfile(custom_path)

    def test_export_then_import_round_trip(self, scanned_workspace):
        """The core issue #218 regression: export must produce a file that
        import-snapshot can actually load, restoring the same node/edge
        counts into a fresh database."""
        export_result = cmd_export_snapshot(scanned_workspace)
        assert export_result["status"] == "ok"

        # Import into a brand-new empty workspace/db (simulates a teammate
        # loading the shared snapshot without ever running `scan`).
        fresh_ws = tempfile.mkdtemp(prefix="codelens_export_snapshot_fresh_")
        try:
            os.makedirs(os.path.join(fresh_ws, ".codelens"), exist_ok=True)
            shutil.copy(
                export_result["output_path"],
                os.path.join(fresh_ws, ".codelens", "snapshot.codelens.gz"),
            )

            import_result = cmd_import_snapshot(fresh_ws)
            assert import_result["status"] == "ok"
            assert import_result["total_inserted"] == 3  # 2 nodes + 1 edge
            assert import_result["header"]["node_count"] == 2
            assert import_result["header"]["edge_count"] == 1
        finally:
            shutil.rmtree(fresh_ws, ignore_errors=True)


class TestDepsDefaultExcludesSnapshotChecks:
    """import-snapshot/export-snapshot must not run in the bare
    `codelens deps <workspace>` default — they are side-effecting and
    always fail with no explicit --input/--output, which would make every
    default `deps` run show a spurious error entry."""

    def test_default_check_list_excludes_snapshot_checks(self):
        checks = _parse_checks(None)
        assert "import-snapshot" not in checks
        assert "export-snapshot" not in checks
        assert "affected" in checks
        assert "dependents" in checks
        assert "circular" in checks

    def test_explicit_check_still_allows_snapshot_checks(self):
        assert _parse_checks("export-snapshot") == ["export-snapshot"]
        assert _parse_checks("import-snapshot") == ["import-snapshot"]

    def test_export_snapshot_registered_in_all_checks(self):
        assert "export-snapshot" in ALL_CHECKS
