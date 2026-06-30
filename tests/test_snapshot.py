"""Round-trip tests for export-snapshot + import-snapshot (issue #12).

Verifies that exporting a CodeLens graph snapshot and importing it into
a fresh workspace produces a database with identical graph metadata:
same node/edge/symbol/ref/file rows (modulo the autoincrement ``id``
column, which is intentionally not preserved across export/import).

Also covers:
- The export ``"Snapshot exported: ... (N.N MB)"`` message format.
- ``--merge`` deduplication (importing the same snapshot twice does not
  duplicate rows).
- Version-mismatch validation warnings.
- The constraint that the snapshot contains metadata only (no file
  content is stored in any of the exported tables).
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

# Add scripts directory to path (matches other test files).
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402
from snapshot_io import (  # noqa: E402
    DEFAULT_SNAPSHOT_FILENAME,
    SNAPSHOT_TABLES,
    TABLE_COLUMNS,
    default_snapshot_path,
    format_size,
)


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def workspace_a():
    """A temp workspace with a populated CodeLens database.

    The DB schema is initialized via PersistentRegistry (which also
    creates the graph_* tables), then a small known set of rows is
    inserted directly so the round-trip has deterministic data to
    compare against.
    """
    workspace = tempfile.mkdtemp(prefix="codelens_snap_export_")
    try:
        _populate_workspace(workspace)
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def workspace_b():
    """A fresh, empty temp workspace (import target)."""
    workspace = tempfile.mkdtemp(prefix="codelens_snap_import_")
    try:
        yield workspace
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _populate_workspace(workspace: str) -> None:
    """Initialize the DB schema and insert a small known graph."""
    from persistent_registry import PersistentRegistry

    # Initializing the registry creates all tables (symbols, refs, files,
    # analysis_cache, scan_metadata + graph_nodes + graph_edges).
    reg = PersistentRegistry(workspace)
    reg._connect()
    reg.close()

    db_path = os.path.join(workspace, ".codelens", "codelens.db")
    conn = sqlite3.connect(db_path)
    try:
        # graph_nodes — (node_id, node_type, name, file, line, extra_json)
        conn.executemany(
            "INSERT INTO graph_nodes "
            "(node_id, node_type, name, file, line, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("src/app.py:10:main", "function", "main", "src/app.py", 10, None),
                ("src/app.py:20:helper", "function", "helper", "src/app.py", 20,
                 json.dumps({"async": True})),
                ("src/models.py:5:User", "class", "User", "src/models.py", 5, None),
            ],
        )
        # graph_edges — (source_id, target_id, edge_type, file, line, confidence, extra_json)
        conn.executemany(
            "INSERT INTO graph_edges "
            "(source_id, target_id, edge_type, file, line, confidence, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("src/app.py:10:main", "src/app.py:20:helper", "CALLS",
                 "src/app.py", 10, 1.0, None),
                ("src/app.py:10:main", "src/models.py:5:User", "USES_TYPE",
                 "src/app.py", 12, 0.9, json.dumps({"to_fn": "User"})),
            ],
        )
        # symbols — (name, kind, file_path, line_start, line_end, language, signature, hash, extra_json)
        conn.executemany(
            "INSERT INTO symbols "
            "(name, kind, file_path, line_start, line_end, language, signature, hash, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("main", "function", "src/app.py", 10, 15, "python",
                 "def main()", "sha1:abc", None),
                ("User", "class", "src/models.py", 5, 30, "python",
                 "class User", "sha1:def", None),
            ],
        )
        # refs — (source_symbol, target_symbol, reference_type, source_file, extra_json)
        conn.executemany(
            "INSERT INTO refs "
            "(source_symbol, target_symbol, reference_type, source_file, extra_json) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("src/app.py:10:main", "src/app.py:20:helper", "call",
                 "src/app.py", None),
            ],
        )
        # files — (file_path, language, last_modified, content_hash, last_scanned)
        conn.executemany(
            "INSERT INTO files "
            "(file_path, language, last_modified, content_hash, last_scanned) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("src/app.py", "python", 1700000000.0, "sha1:aaa", 1700000000.0),
                ("src/models.py", "python", 1700000001.0, "sha1:bbb", 1700000001.0),
            ],
        )
        # scan_metadata — (id=1, workspace, scan_timestamp, total_files, version)
        conn.execute(
            "INSERT OR REPLACE INTO scan_metadata "
            "(id, workspace, scan_timestamp, total_files, version) "
            "VALUES (1, ?, ?, ?, ?)",
            (workspace, 1700000000.0, 2, 1),
        )
        conn.commit()
    finally:
        conn.close()


def _table_rows(db_path: str, table: str, exclude_id: bool = True):
    """Return rows from ``table`` as a sorted list of tuples.

    The autoincrement ``id`` column is excluded by default so rows can be
    compared across databases (import assigns fresh ids). Rows are sorted
    for deterministic comparison.
    """
    conn = sqlite3.connect(db_path)
    try:
        cols = TABLE_COLUMNS[table]
        if exclude_id:
            cols = [c for c in cols if c != "id"]
        col_list = ", ".join('"' + c + '"' for c in cols)
        rows = conn.execute(f'SELECT {col_list} FROM "{table}"').fetchall()
        # Normalize: convert each row to a tuple of JSON-stringifiable values
        # so json-encoded extra_json strings compare equal.
        return sorted(tuple(r[i] for i in range(len(cols))) for r in rows)
    finally:
        conn.close()


# ─── Registration ─────────────────────────────────────────────


class TestCommandRegistration:
    """Both commands must auto-register via register_command()."""

    def test_export_snapshot_registered(self):
        assert "export-snapshot" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["export-snapshot"]
        assert info["help"]
        assert callable(info["add_args"])
        assert callable(info["execute"])

    def test_import_snapshot_registered(self):
        assert "import-snapshot" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["import-snapshot"]
        assert info["help"]
        assert callable(info["add_args"])
        assert callable(info["execute"])


# ─── Round-trip ───────────────────────────────────────────────


class TestRoundTrip:
    """export → import → query produces the same results."""

    def test_round_trip_preserves_all_tables(self, workspace_a, workspace_b):
        """Export from A, import into B, then every table must match."""
        from commands.export_snapshot import cmd_export_snapshot
        from commands.import_snapshot import cmd_import_snapshot

        snapshot_path = os.path.join(workspace_a, ".codelens",
                                     DEFAULT_SNAPSHOT_FILENAME)

        # ── Export from workspace A ──
        export_result = cmd_export_snapshot(workspace_a)
        assert export_result["status"] == "ok", export_result
        assert os.path.exists(snapshot_path), "snapshot file was not written"

        header = export_result["header"]
        assert header["node_count"] == 3
        assert header["edge_count"] == 2
        assert header["file_count"] == 2
        assert header["format_version"] == 1
        assert header["codelens_version"]  # non-empty

        # ── Import into workspace B (fresh, empty) ──
        import_result = cmd_import_snapshot(
            workspace_b, input_path=snapshot_path, merge=False
        )
        assert import_result["status"] == "ok", import_result
        # Same-version import should produce no warnings.
        assert import_result["warnings"] == []
        assert import_result["mode"] == "replace"

        db_a = os.path.join(workspace_a, ".codelens", "codelens.db")
        db_b = os.path.join(workspace_b, ".codelens", "codelens.db")
        assert os.path.exists(db_b), "import did not create a database"

        # ── Every exported table must round-trip identically ──
        for table in SNAPSHOT_TABLES:
            rows_a = _table_rows(db_a, table)
            rows_b = _table_rows(db_b, table)
            assert rows_a == rows_b, (
                f"Table '{table}' differs after round-trip:\n"
                f"  source rows: {rows_a}\n"
                f"  imported rows: {rows_b}"
            )

    def test_export_message_format(self, workspace_a):
        """Export message must match 'Snapshot exported: <path> (<size>)'."""
        from commands.export_snapshot import cmd_export_snapshot

        result = cmd_export_snapshot(workspace_a)
        assert result["status"] == "ok"
        msg = result["message"]
        assert msg.startswith("Snapshot exported: "), msg
        # Default display path is workspace-relative.
        assert ".codelens/snapshot.codelens.gz" in msg, msg
        # Size appears in parentheses with a unit suffix.
        assert " (" in msg and msg.rstrip().endswith(")"), msg
        assert any(unit in msg for unit in (" B", " KB", " MB", " GB")), msg
        # size_human must match the parenthesized portion.
        assert f"({result['size_human']})" in msg, msg

    def test_graph_schema_command_matches_after_round_trip(
        self, workspace_a, workspace_b
    ):
        """The graph-schema command must report identical stats after import."""
        from commands.export_snapshot import cmd_export_snapshot
        from commands.import_snapshot import cmd_import_snapshot
        from commands.graph_schema import get_graph_schema

        snapshot_path = os.path.join(workspace_a, ".codelens",
                                     DEFAULT_SNAPSHOT_FILENAME)
        assert cmd_export_snapshot(workspace_a)["status"] == "ok"
        assert cmd_import_snapshot(
            workspace_b, input_path=snapshot_path
        )["status"] == "ok"

        schema_a = get_graph_schema(workspace_a)
        schema_b = get_graph_schema(workspace_b)
        # Compare the queryable graph shape (ignore workspace path).
        for key in ("nodes", "edges", "node_types", "edge_types", "indexes"):
            assert schema_a[key] == schema_b[key], (
                f"graph-schema '{key}' differs: {schema_a[key]} vs {schema_b[key]}"
            )


# ─── Merge mode ───────────────────────────────────────────────


class TestMergeMode:
    """--merge deduplicates nodes/edges by their natural key."""

    def test_import_twice_replace_doubles_then_merge_noop(self, workspace_a, workspace_b):
        """Replace import reproduces source; a second merge import adds nothing."""
        from commands.export_snapshot import cmd_export_snapshot
        from commands.import_snapshot import cmd_import_snapshot

        snapshot_path = os.path.join(workspace_a, ".codelens",
                                     DEFAULT_SNAPSHOT_FILENAME)
        assert cmd_export_snapshot(workspace_a)["status"] == "ok"

        # First import (replace) into empty B.
        r1 = cmd_import_snapshot(workspace_b, input_path=snapshot_path, merge=False)
        assert r1["status"] == "ok"
        assert r1["total_inserted"] > 0
        assert r1["total_skipped"] == 0

        db_b = os.path.join(workspace_b, ".codelens", "codelens.db")

        # Row counts after first import.
        counts_after_first = {
            t: len(_table_rows(db_b, t)) for t in SNAPSHOT_TABLES
        }

        # Second import with --merge: every row's natural key already
        # exists, so all rows must be skipped (0 inserted).
        r2 = cmd_import_snapshot(workspace_b, input_path=snapshot_path, merge=True)
        assert r2["status"] == "ok"
        assert r2["mode"] == "merge"
        assert r2["total_inserted"] == 0, (
            f"merge re-import should insert 0 rows, got {r2['total_inserted']}"
        )
        assert r2["total_skipped"] > 0

        # Row counts must be unchanged after the merge re-import.
        counts_after_second = {
            t: len(_table_rows(db_b, t)) for t in SNAPSHOT_TABLES
        }
        assert counts_after_first == counts_after_second, (
            f"merge re-import changed row counts: "
            f"{counts_after_first} -> {counts_after_second}"
        )

    def test_merge_combines_disjoint_graphs(self, workspace_a, workspace_b):
        """Merging a snapshot with extra nodes adds only the new ones."""
        from commands.export_snapshot import cmd_export_snapshot
        from commands.import_snapshot import cmd_import_snapshot

        snapshot_path = os.path.join(workspace_a, ".codelens",
                                     DEFAULT_SNAPSHOT_FILENAME)
        assert cmd_export_snapshot(workspace_a)["status"] == "ok"

        # Seed workspace B with ONE node that is NOT in the snapshot.
        from persistent_registry import PersistentRegistry
        reg = PersistentRegistry(workspace_b)
        reg._connect()
        reg.close()
        db_b = os.path.join(workspace_b, ".codelens", "codelens.db")
        conn = sqlite3.connect(db_b)
        try:
            conn.execute(
                "INSERT INTO graph_nodes "
                "(node_id, node_type, name, file, line, extra_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("src/extra.py:1:only_in_b", "function", "only_in_b",
                 "src/extra.py", 1, None),
            )
            conn.commit()
        finally:
            conn.close()

        # Merge-import the snapshot — the 3 snapshot nodes are new,
        # so they're inserted; the existing B-only node survives.
        r = cmd_import_snapshot(workspace_b, input_path=snapshot_path, merge=True)
        assert r["status"] == "ok"
        assert r["mode"] == "merge"
        # All 3 graph_nodes from the snapshot are new relative to B.
        assert r["inserted"]["graph_nodes"] == 3
        assert r["skipped"]["graph_nodes"] == 0

        # Final node count = 1 (pre-existing) + 3 (merged in) = 4.
        final_nodes = len(_table_rows(db_b, "graph_nodes"))
        assert final_nodes == 4, f"expected 4 nodes after merge, got {final_nodes}"


# ─── Validation ───────────────────────────────────────────────


class TestValidation:
    """Version-mismatch warnings and error handling."""

    def test_version_mismatch_warns(self, workspace_a, workspace_b):
        """A snapshot with a different codelens_version must warn on import."""
        from commands.export_snapshot import cmd_export_snapshot
        from commands.import_snapshot import cmd_import_snapshot
        from snapshot_io import read_snapshot, write_snapshot

        snapshot_path = os.path.join(workspace_a, ".codelens",
                                     DEFAULT_SNAPSHOT_FILENAME)
        assert cmd_export_snapshot(workspace_a)["status"] == "ok"

        # Tamper with the version to simulate a cross-version import.
        snap = read_snapshot(snapshot_path)
        snap["header"]["codelens_version"] = "0.0.0-mock"
        write_snapshot(snap, snapshot_path)

        r = cmd_import_snapshot(
            workspace_b, input_path=snapshot_path, merge=False
        )
        assert r["status"] == "ok"
        assert any("0.0.0-mock" in w for w in r["warnings"]), r["warnings"]
        assert any("different" in w.lower() or "version" in w.lower()
                   for w in r["warnings"]), r["warnings"]

    def test_import_missing_snapshot_returns_error(self, workspace_b):
        """Importing a non-existent snapshot must return a clean error."""
        from commands.import_snapshot import cmd_import_snapshot

        bogus = os.path.join(workspace_b, ".codelens", "nope.codelens.gz")
        r = cmd_import_snapshot(workspace_b, input_path=bogus)
        assert r["status"] == "error"
        assert "not found" in r["error"].lower() or "nope" in r["error"]

    def test_export_missing_db_returns_error(self, workspace_b):
        """Exporting with no database present must return a clean error."""
        from commands.export_snapshot import cmd_export_snapshot

        r = cmd_export_snapshot(workspace_b)
        assert r["status"] == "error"
        assert "not found" in r["error"].lower() or "scan" in r["error"].lower()


# ─── Constraint: no file content ──────────────────────────────


class TestNoFileContent:
    """Issue #12 constraint: the snapshot must NOT contain file content."""

    def test_snapshot_contains_no_content_blobs(self, workspace_a):
        """No exported column may hold raw source content.

        The ``files`` table holds ``content_hash`` (a digest), not bytes.
        ``symbols`` holds ``signature`` (a parsed signature string), not
        source. This test asserts the snapshot's data shape stays free
        of any obvious content-bearing column by checking the exported
        column names against a denylist.
        """
        from commands.export_snapshot import cmd_export_snapshot
        from snapshot_io import read_snapshot, default_snapshot_path

        result = cmd_export_snapshot(workspace_a)
        assert result["status"] == "ok"

        snap = read_snapshot(default_snapshot_path(workspace_a))
        data = snap["data"]

        # Forbidden column names — if any appear, file content is leaking
        # into the snapshot and the issue #12 constraint is violated.
        forbidden = {"content", "source", "body", "text", "raw", "bytes", "code"}
        for table, tbl in data.items():
            cols = set(tbl.get("columns", []))
            leaked = cols & forbidden
            assert not leaked, (
                f"Table '{table}' exports content-bearing columns {leaked} "
                f"— issue #12 forbids file content in snapshots."
            )

        # Spot-check: the files table must export content_hash, not content.
        assert "content_hash" in data["files"]["columns"]
        assert "content" not in data["files"]["columns"]
        # And no row value may be a multi-KB blob (sanity cap).
        for table in SNAPSHOT_TABLES:
            for row in data[table]["rows"]:
                for val in row:
                    if isinstance(val, str):
                        assert len(val) < 8192, (
                            f"Suspiciously large string value ({len(val)} chars) "
                            f"in table '{table}' — possible content leak."
                        )


# ─── format_size helper ───────────────────────────────────────


class TestFormatSize:
    def test_bytes(self):
        assert format_size(512) == "512 B"

    def test_kilobytes(self):
        assert format_size(1500) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1250000) == "1.2 MB"

    def test_zero(self):
        assert format_size(0) == "0 B"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
