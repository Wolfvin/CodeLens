"""Tests for incremental graph update (issue #25).

Verifies that ``incremental_graph_update`` keeps the graph tables in sync
when only a subset of files change, without requiring a full re-population.

Coverage:
1. Empty / no-op cases (empty changed_files, missing db)
2. Equivalence with full population (incremental with all files == full)
3. Idempotency (running twice yields the same state)
4. Slice isolation (unchanged files' nodes/edges are preserved)
5. Reflects file modifications (rename / add / remove a function)
6. Drop cross-file edges into changed files when the target is gone
7. Return value shape (matches populate_graph_tables + extras)
8. End-to-end via ``cmd_scan(incremental=True)`` — graph field present in
   both full-scan and incremental-scan output with matching counts
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time

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
def scanned_clean_app():
    """Copy clean_app fixture to a temp workspace and run a full scan.

    Yields the workspace path. The scan populates backend.json, graph_nodes,
    and graph_edges. Cleanup removes the temp workspace on teardown.
    """
    if not os.path.isdir(FIXTURE_DIR):
        pytest.skip("clean_app fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_inc_graph_")
    for entry in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    from commands.scan import cmd_scan
    cmd_scan(workspace, incremental=False)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


def _db_path(workspace):
    """Return the default graph db path for a workspace."""
    return os.path.join(workspace, ".codelens", "codelens.db")


def _graph_stats(workspace):
    """Return {nodes, edges} count from the workspace's graph db."""
    from graph_model import graph_stats
    return graph_stats(_db_path(workspace))


def _calls_count(workspace):
    """Return the number of CALLS edges in the workspace's graph db."""
    conn = sqlite3.connect(_db_path(workspace))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE edge_type = 'CALLS'"
        ).fetchone()[0]
    finally:
        conn.close()


def _nodes_for_file(workspace, rel_path):
    """Return list of (node_id, name, line) for nodes whose file == rel_path."""
    conn = sqlite3.connect(_db_path(workspace))
    try:
        rows = conn.execute(
            "SELECT node_id, name, line FROM graph_nodes WHERE file = ? "
            "ORDER BY name, line",
            (rel_path,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def _edges_for_file(workspace, rel_path):
    """Return list of (source_id, target_id, edge_type) for edges whose
    originating file == rel_path.
    """
    conn = sqlite3.connect(_db_path(workspace))
    try:
        rows = conn.execute(
            "SELECT source_id, target_id, edge_type FROM graph_edges "
            "WHERE file = ? ORDER BY source_id, target_id, edge_type",
            (rel_path,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def _touch(path):
    """Update mtime of a file so subsequent incremental scans pick it up."""
    # Some filesystems have 1-sec mtime resolution; sleep briefly.
    time.sleep(0.01)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── 1. No-op Cases ───────────────────────────────────────────


class TestNoOpCases:
    """Empty input or missing db must short-circuit cleanly."""

    def test_empty_changed_files_returns_zeros(self, scanned_clean_app):
        """Empty changed_files list returns zero counts and leaves graph untouched."""
        from graph_model import incremental_graph_update

        before = _graph_stats(scanned_clean_app)
        result = incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), []
        )
        after = _graph_stats(scanned_clean_app)

        assert result["nodes"] == 0
        assert result["edges"] == 0
        assert result["edges_refined"] == 0
        assert result["edges_unresolved"] == 0
        assert before == after, "empty changed_files must not modify graph"

    def test_none_changed_files_returns_zeros(self, scanned_clean_app):
        """None as changed_files is treated as empty (defensive)."""
        from graph_model import incremental_graph_update

        before = _graph_stats(scanned_clean_app)
        result = incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), None
        )
        after = _graph_stats(scanned_clean_app)

        assert result["nodes"] == 0
        assert before == after

    def test_missing_db_returns_zeros(self, tmp_path):
        """When db_path points to a nonexistent file, return zeros gracefully."""
        from graph_model import incremental_graph_update

        workspace = str(tmp_path)
        nonexistent_db = os.path.join(workspace, "missing.db")
        result = incremental_graph_update(
            workspace, nonexistent_db, ["/some/file.py"]
        )
        assert result["nodes"] == 0
        assert result["edges"] == 0


# ─── 2. Equivalence With Full Population ──────────────────────


class TestEquivalenceWithFullPopulate:
    """Running incremental with ALL files must match a fresh full populate."""

    def test_all_files_matches_full_repopulate_nodes(self, scanned_clean_app):
        """incremental_graph_update with all backend files produces the same
        node set as a fresh populate_graph_tables call.
        """
        from graph_model import (
            incremental_graph_update, populate_graph_tables,
            clear_graph_tables,
        )

        # Enumerate all backend files from the flat registry.
        from registry import load_backend_registry
        backend = load_backend_registry(scanned_clean_app)
        all_files_rel = {
            n.get("file", "") for n in backend.get("nodes", []) if n.get("file")
        }
        all_files_abs = [
            os.path.join(scanned_clean_app, rel) for rel in all_files_rel
        ]
        assert all_files_abs, "fixture should have backend files"

        # Run incremental_graph_update with ALL backend files.
        inc_result = incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), all_files_abs
        )

        # Snapshot the node set after the incremental update.
        conn = sqlite3.connect(_db_path(scanned_clean_app))
        try:
            inc_nodes = conn.execute(
                "SELECT node_id, name, file, line FROM graph_nodes ORDER BY node_id"
            ).fetchall()
        finally:
            conn.close()

        # Wipe and re-populate via the full-scan path.
        clear_graph_tables(_db_path(scanned_clean_app))
        populate_graph_tables(scanned_clean_app, _db_path(scanned_clean_app))

        conn = sqlite3.connect(_db_path(scanned_clean_app))
        try:
            full_nodes = conn.execute(
                "SELECT node_id, name, file, line FROM graph_nodes ORDER BY node_id"
            ).fetchall()
        finally:
            conn.close()

        # Node sets must be identical — incremental with all files rebuilds
        # every node from the flat registry, just like full populate.
        assert inc_nodes == full_nodes, (
            "incremental with all files must produce same node set as full"
        )
        # And the count must match the return value.
        assert inc_result["nodes"] == len(inc_nodes)

    def test_all_files_calls_edges_match_full_scan(self, scanned_clean_app):
        """CALLS edge set after incremental with all files matches a full scan.

        Both paths run ``refine_call_edges`` (full scan runs it as a
        separate post-pass; incremental runs it inside
        ``incremental_graph_update``). The resulting CALLS edge sets
        — including ``target_id`` refinements — must be identical.
        """
        from graph_model import (
            incremental_graph_update, populate_graph_tables,
            clear_graph_tables,
        )
        from hybrid_type_resolver import refine_call_edges

        from registry import load_backend_registry
        backend = load_backend_registry(scanned_clean_app)
        all_files_rel = {
            n.get("file", "") for n in backend.get("nodes", []) if n.get("file")
        }
        all_files_abs = [
            os.path.join(scanned_clean_app, rel) for rel in all_files_rel
        ]

        # Path A: incremental_graph_update with all files (runs refine
        # internally as step 6).
        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), all_files_abs
        )
        conn = sqlite3.connect(_db_path(scanned_clean_app))
        try:
            inc_calls = conn.execute(
                "SELECT source_id, target_id, file, line FROM graph_edges "
                "WHERE edge_type = 'CALLS' ORDER BY source_id, target_id"
            ).fetchall()
        finally:
            conn.close()

        # Path B: full populate + refine (matches the full-scan pipeline).
        clear_graph_tables(_db_path(scanned_clean_app))
        populate_graph_tables(scanned_clean_app, _db_path(scanned_clean_app))
        refine_call_edges(scanned_clean_app, _db_path(scanned_clean_app))

        conn = sqlite3.connect(_db_path(scanned_clean_app))
        try:
            full_calls = conn.execute(
                "SELECT source_id, target_id, file, line FROM graph_edges "
                "WHERE edge_type = 'CALLS' ORDER BY source_id, target_id"
            ).fetchall()
        finally:
            conn.close()

        # CALLS edge sets must be identical (both paths ran refine).
        assert inc_calls == full_calls, (
            "incremental with all files must produce same CALLS edge set "
            "as full populate + refine"
        )


# ─── 3. Idempotency ───────────────────────────────────────────


class TestIdempotency:
    """Running incremental_graph_update twice must yield the same graph state."""

    def test_idempotent_same_files(self, scanned_clean_app):
        """Running twice with the same changed_files yields the same state."""
        from graph_model import incremental_graph_update
        from registry import load_backend_registry

        backend = load_backend_registry(scanned_clean_app)
        all_files_rel = {n.get("file", "") for n in backend.get("nodes", []) if n.get("file")}
        all_files_abs = [
            os.path.join(scanned_clean_app, rel) for rel in all_files_rel
        ]

        # Run 1
        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), all_files_abs
        )
        snap1_nodes = _nodes_for_file(scanned_clean_app, "src/db_queries.py")
        snap1_edges = _edges_for_file(scanned_clean_app, "src/db_queries.py")
        snap1_stats = _graph_stats(scanned_clean_app)

        # Run 2 (same input)
        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), all_files_abs
        )
        snap2_nodes = _nodes_for_file(scanned_clean_app, "src/db_queries.py")
        snap2_edges = _edges_for_file(scanned_clean_app, "src/db_queries.py")
        snap2_stats = _graph_stats(scanned_clean_app)

        assert snap1_nodes == snap2_nodes, (
            "node rows must be identical after idempotent re-run"
        )
        assert snap1_edges == snap2_edges, (
            "edge rows must be identical after idempotent re-run"
        )
        assert snap1_stats == snap2_stats, (
            "graph stats must be identical after idempotent re-run"
        )


# ─── 4. Slice Isolation ───────────────────────────────────────


class TestSliceIsolation:
    """Updating one file must NOT touch another file's nodes/edges."""

    def test_unrelated_file_nodes_preserved(self, scanned_clean_app):
        """Updating src/utils.py must not change src/db_queries.py's nodes."""
        from graph_model import incremental_graph_update

        target_file = os.path.join(scanned_clean_app, "src", "utils.py")
        unrelated_file = "src/db_queries.py"

        before_nodes = _nodes_for_file(scanned_clean_app, unrelated_file)
        before_edges = _edges_for_file(scanned_clean_app, unrelated_file)

        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), [target_file]
        )

        after_nodes = _nodes_for_file(scanned_clean_app, unrelated_file)
        after_edges = _edges_for_file(scanned_clean_app, unrelated_file)

        # db_queries.py's own nodes must be untouched.
        assert before_nodes == after_nodes, (
            "incremental update of utils.py must not change db_queries.py nodes"
        )
        # db_queries.py's CALLS edges that originate in db_queries.py
        # must also be untouched.
        # Note: edges from OTHER files INTO db_queries.py may change
        # (e.g., if db_queries.py symbols were renamed). But edges whose
        # `file` is db_queries.py are originated from db_queries.py
        # itself and are untouched when db_queries.py is unchanged.
        assert before_edges == after_edges, (
            "incremental update of utils.py must not change db_queries.py's "
            "originating edges"
        )

    def test_total_node_count_unchanged_when_nothing_changed(
        self, scanned_clean_app
    ):
        """Re-running incremental on the same files preserves total node count."""
        from graph_model import incremental_graph_update

        target_file = os.path.join(scanned_clean_app, "main.py")
        before = _graph_stats(scanned_clean_app)

        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), [target_file]
        )

        after = _graph_stats(scanned_clean_app)
        # Total node count must be the same — we deleted main.py's nodes
        # and re-inserted the same nodes from the unchanged flat registry.
        assert before["nodes"] == after["nodes"], (
            "re-running incremental on unchanged content must preserve node count"
        )


# ─── 5. Reflects File Modifications ───────────────────────────


class TestReflectsModifications:
    """After modifying a file's content, incremental update reflects the change."""

    def test_renamed_function_reflected_in_graph(self, scanned_clean_app):
        """Renaming a function in a file updates the graph node's name."""
        from commands.scan import cmd_scan

        target_file_rel = "src/utils.py"
        target_file_abs = os.path.join(scanned_clean_app, target_file_rel)

        # utils.py defines `format_text` (per main.py calls).
        # We rename `format_text` to `format_text_renamed`.
        with open(target_file_abs, "r", encoding="utf-8") as f:
            original = f.read()
        modified = original.replace("format_text", "format_text_renamed")
        assert modified != original, "fixture must contain 'format_text'"
        with open(target_file_abs, "w", encoding="utf-8") as f:
            f.write(modified)

        # Re-run the full scan's parse pipeline so backend.json reflects
        # the new file content (incremental_graph_update reads from
        # backend.json, not from the file system directly).
        cmd_scan(scanned_clean_app, incremental=True)

        # Verify the graph reflects the renamed function via EXACT name
        # match (find_nodes_by_name falls back to substring match, which
        # would also match format_text_renamed for query "format_text").
        db = _db_path(scanned_clean_app)
        conn = sqlite3.connect(db)
        try:
            renamed_rows = conn.execute(
                "SELECT name, file, line FROM graph_nodes "
                "WHERE name = 'format_text_renamed' AND file = ?",
                (target_file_rel,),
            ).fetchall()
            assert len(renamed_rows) >= 1, (
                "renamed function must appear in graph after incremental scan"
            )

            old_rows = conn.execute(
                "SELECT name, file FROM graph_nodes "
                "WHERE name = 'format_text' AND file = ?",
                (target_file_rel,),
            ).fetchall()
            assert old_rows == [], (
                "old function name must not remain in utils.py after rename"
            )
        finally:
            conn.close()

    def test_added_function_reflected_in_graph(self, scanned_clean_app):
        """Adding a new function to a file creates a new graph node."""
        from graph_model import incremental_graph_update, find_nodes_by_name

        target_file_rel = "src/utils.py"
        target_file_abs = os.path.join(scanned_clean_app, target_file_rel)

        # Append a new function to utils.py.
        with open(target_file_abs, "r", encoding="utf-8") as f:
            original = f.read()
        new_function = "\n\ndef brand_new_helper_function():\n    return 42\n"
        with open(target_file_abs, "w", encoding="utf-8") as f:
            f.write(original + new_function)

        # Re-scan incrementally to update backend.json.
        from commands.scan import cmd_scan
        cmd_scan(scanned_clean_app, incremental=True)

        # The new function should appear in the graph.
        nodes = find_nodes_by_name(
            "brand_new_helper_function", _db_path(scanned_clean_app)
        )
        assert len(nodes) >= 1, (
            "newly added function must appear in graph after incremental scan"
        )
        assert nodes[0]["file"] == target_file_rel

    def test_removed_function_reflected_in_graph(self, scanned_clean_app):
        """Removing a function from a file removes its graph node."""
        from graph_model import find_nodes_by_name

        target_file_rel = "src/utils.py"
        target_file_abs = os.path.join(scanned_clean_app, target_file_rel)

        # Find a function in utils.py to remove.
        nodes_before = find_nodes_by_name("format_text", _db_path(scanned_clean_app))
        utils_nodes_before = [n for n in nodes_before if n.get("file") == target_file_rel]
        assert len(utils_nodes_before) >= 1, (
            "format_text should exist in utils.py before removal"
        )

        # Remove the function definition from utils.py.
        with open(target_file_abs, "r", encoding="utf-8") as f:
            content = f.read()
        # Remove the line(s) defining format_text.
        new_lines = []
        skip_block = False
        for line in content.split("\n"):
            if line.startswith("def format_text"):
                skip_block = True
                continue
            if skip_block:
                if line and not line.startswith(" ") and not line.startswith("\t"):
                    skip_block = False
                    new_lines.append(line)
                # else: skip indented body lines
            else:
                new_lines.append(line)
        with open(target_file_abs, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        # Re-scan incrementally.
        from commands.scan import cmd_scan
        cmd_scan(scanned_clean_app, incremental=True)

        # The function should no longer exist in utils.py.
        nodes_after = find_nodes_by_name("format_text", _db_path(scanned_clean_app))
        utils_nodes_after = [n for n in nodes_after if n.get("file") == target_file_rel]
        assert utils_nodes_after == [], (
            "removed function must not remain in utils.py after incremental scan"
        )


# ─── 6. Drop Stale Cross-File Edges ───────────────────────────


class TestStaleEdgeDropping:
    """Edges from unchanged files into changed files must be re-resolved."""

    def test_graph_has_no_orphan_edges_after_removal(self, scanned_clean_app):
        """After removing a function, no edge may point to a nonexistent node.

        When ``format_text`` is removed from utils.py, the incremental
        update must drop the old CALLS edge that pointed to it. The
        flat registry's ``merge_backend_data`` then has a chance to
        re-resolve cross-file edges (e.g., another call site may now
        resolve to a different function at the same line). The end
        state must have no orphan edges — every non-null ``target_id``
        must reference an existing ``graph_nodes`` row.
        """
        from graph_model import find_nodes_by_name, query_callers

        # main.py calls format_text (defined in src/utils.py).
        # Verify the caller exists before the change.
        nodes = find_nodes_by_name("format_text", _db_path(scanned_clean_app))
        utils_node = next(n for n in nodes if n.get("file") == "src/utils.py")
        callers_before = query_callers(
            utils_node["node_id"], _db_path(scanned_clean_app), max_depth=1
        )
        caller_names_before = {c["name"] for c in callers_before}
        assert "main" in caller_names_before, (
            "main() calls format_text — caller must exist before change"
        )

        # Remove format_text from utils.py.
        target_file = os.path.join(scanned_clean_app, "src", "utils.py")
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()
        new_lines = []
        skip_block = False
        for line in content.split("\n"):
            if line.startswith("def format_text"):
                skip_block = True
                continue
            if skip_block:
                if line and not line.startswith(" ") and not line.startswith("\t"):
                    skip_block = False
                    new_lines.append(line)
            else:
                new_lines.append(line)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        from commands.scan import cmd_scan
        cmd_scan(scanned_clean_app, incremental=True)

        # format_text node must no longer exist in utils.py.
        db = _db_path(scanned_clean_app)
        conn = sqlite3.connect(db)
        try:
            # 1. No graph_node named format_text in utils.py.
            stale_nodes = conn.execute(
                "SELECT name FROM graph_nodes "
                "WHERE name = 'format_text' AND file = 'src/utils.py'"
            ).fetchall()
            assert stale_nodes == [], (
                "removed function's node must not exist after incremental scan"
            )

            # 2. No orphan CALLS edges — every non-null target_id must
            #    reference an existing graph_nodes row. This is the core
            #    invariant the incremental update must preserve: deleting
            #    a node must not leave dangling edges pointing to it.
            orphan_edges = conn.execute(
                "SELECT COUNT(*) FROM graph_edges ge "
                "WHERE ge.target_id IS NOT NULL "
                "AND NOT EXISTS ("
                "    SELECT 1 FROM graph_nodes gn "
                "    WHERE gn.node_id = ge.target_id"
                ")"
            ).fetchone()[0]
            assert orphan_edges == 0, (
                "no CALLS/IMPORTS edge may point to a nonexistent node "
                "after incremental update (found {} orphans)".format(
                    orphan_edges
                )
            )

            # 3. No CALLS edge should have extra_json.to_fn = 'format_text'
            #    with a target pointing into utils.py — that would indicate
            #    a stale edge that wasn't cleaned up. (target_id may be NULL
            #    for unresolved edges, which is fine.)
            stale_to_fn = conn.execute(
                "SELECT COUNT(*) FROM graph_edges "
                "WHERE edge_type = 'CALLS' "
                "AND extra_json LIKE '%\"to_fn\": \"format_text\"%' "
                "AND file = 'src/utils.py'"
            ).fetchone()[0]
            assert stale_to_fn == 0, (
                "no edge from utils.py may reference the removed function"
            )
        finally:
            conn.close()


# ─── 7. Return Value Shape ────────────────────────────────────


class TestReturnShape:
    """incremental_graph_update's return value must match the documented shape."""

    def test_return_dict_has_required_keys(self, scanned_clean_app):
        """Return value must contain nodes, edges, edges_refined, edges_unresolved."""
        from graph_model import incremental_graph_update

        target_file = os.path.join(scanned_clean_app, "main.py")
        result = incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), [target_file]
        )

        assert isinstance(result, dict)
        for key in ("nodes", "edges", "edges_refined", "edges_unresolved"):
            assert key in result, "missing key: {}".format(key)
            assert isinstance(result[key], int)

    def test_return_nodes_matches_graph_stats(self, scanned_clean_app):
        """Return value's 'nodes' must equal graph_stats()['nodes'] after update."""
        from graph_model import incremental_graph_update

        target_file = os.path.join(scanned_clean_app, "main.py")
        result = incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), [target_file]
        )
        stats = _graph_stats(scanned_clean_app)

        assert result["nodes"] == stats["nodes"]
        assert result["edges"] == stats["edges"]


# ─── 8. End-to-end via cmd_scan ───────────────────────────────


class TestScanIncrementalIntegration:
    """End-to-end: scan --incremental must include a graph field with matching counts."""

    def test_full_scan_output_has_graph_field(self, scanned_clean_app):
        """cmd_scan(incremental=False) output must include a graph field."""
        from commands.scan import cmd_scan

        result = cmd_scan(scanned_clean_app, incremental=False)
        assert "graph" in result, "full scan output must include graph field"
        assert "nodes" in result["graph"]
        assert "edges" in result["graph"]
        assert result["graph"]["nodes"] > 0
        assert result["graph"]["edges"] > 0

    def test_incremental_scan_no_changes_output_has_graph_field(
        self, scanned_clean_app
    ):
        """cmd_scan(incremental=True) with no changes must include a graph field."""
        from commands.scan import cmd_scan

        # No file modifications — incremental scan should detect no changes.
        result = cmd_scan(scanned_clean_app, incremental=True)
        assert "graph" in result, (
            "incremental scan (no changes) output must include graph field"
        )
        assert result["graph"]["nodes"] > 0
        assert result["graph"]["edges"] > 0

    def test_full_and_incremental_matching_counts(self, scanned_clean_app):
        """Full scan and subsequent incremental scan must report matching graph counts."""
        from commands.scan import cmd_scan

        full_result = cmd_scan(scanned_clean_app, incremental=False)
        inc_result = cmd_scan(scanned_clean_app, incremental=True)

        assert full_result["graph"]["nodes"] == inc_result["graph"]["nodes"], (
            "graph node count must match between full and incremental scan"
        )
        assert full_result["graph"]["edges"] == inc_result["graph"]["edges"], (
            "graph edge count must match between full and incremental scan"
        )

    def test_incremental_scan_with_modification_updates_graph(
        self, scanned_clean_app
    ):
        """After modifying a file, incremental scan must update the graph."""
        from graph_model import find_nodes_by_name
        from commands.scan import cmd_scan

        # Rename format_text → format_text_renamed in utils.py.
        target_file = os.path.join(scanned_clean_app, "src", "utils.py")
        with open(target_file, "r", encoding="utf-8") as f:
            original = f.read()
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(original.replace("format_text", "format_text_renamed"))

        # Run incremental scan.
        result = cmd_scan(scanned_clean_app, incremental=True)

        # Graph field must be present and reflect the modification.
        assert "graph" in result
        assert result["graph"]["nodes"] > 0
        assert result["incremental"] is True
        assert result["changed_files_count"] > 0, (
            "incremental scan must detect the modified file"
        )

        # The renamed function must appear in the graph.
        nodes = find_nodes_by_name(
            "format_text_renamed", _db_path(scanned_clean_app)
        )
        assert len(nodes) >= 1, (
            "renamed function must be in graph after incremental scan"
        )


# ─── 9. Performance ───────────────────────────────────────────


class TestPerformance:
    """Incremental graph update for a small changed-file set must be fast."""

    def test_under_200ms_for_5_changed_files(self, scanned_clean_app):
        """For ≤5 changed files, the slice update completes in <200ms.

        The target in the issue spec is <100ms; we allow <200ms headroom
        for the test environment (CI runners, slow disks, etc.).
        """
        import time as _time

        from graph_model import incremental_graph_update

        # Pick 5 files from the fixture (it has main.py + 4 src/*.py +
        # 1 src/*.js + 1 config/settings.py — 7 backend files total).
        target_files = [
            os.path.join(scanned_clean_app, "main.py"),
            os.path.join(scanned_clean_app, "src", "utils.py"),
            os.path.join(scanned_clean_app, "src", "db_queries.py"),
            os.path.join(scanned_clean_app, "src", "routes.py"),
            os.path.join(scanned_clean_app, "src", "system_ops.py"),
        ]
        assert len(target_files) == 5

        start = _time.perf_counter()
        incremental_graph_update(
            scanned_clean_app, _db_path(scanned_clean_app), target_files
        )
        elapsed_ms = (_time.perf_counter() - start) * 1000

        # <200ms in the test env (issue spec targets <100ms).
        assert elapsed_ms < 200.0, (
            "incremental_graph_update for 5 files took {:.1f}ms (>200ms)".format(
                elapsed_ms
            )
        )
