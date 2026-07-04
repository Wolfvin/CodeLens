"""Tests for the hybrid type resolver (issue #13).

Verifies:
1. ``build_import_registry`` parses Python ``from X import Y``,
   ``import X.Y``, ``import X.Y as Z``.
2. ``build_import_registry`` parses TS ``import {Y} from 'X'``,
   ``import * as X from 'Y'``, ``import X from 'Y'``.
3. ``resolve_receiver_type`` resolves a simple imported name.
4. ``resolve_receiver_type`` returns None for an unknown name (no crash).
5. ``refine_call_edges`` updates ``target_id`` on resolvable edges.
6. ``refine_call_edges`` leaves unresolvable edges unchanged (adds
   ``resolution_attempted`` flag).
7. ``resolve-types`` command returns correct stats.
8. IMPORTS edges are written to ``graph_edges`` during
   ``build_import_registry``.
9. End-to-end on clean_app fixture: scan -> resolve-types -> verify some
   edges have ``resolved_type`` in ``extra_json``.
10. Synthetic fixture (models.py + main.py + cache.py): scan ->
    refine -> verify ``user.profile.update()`` edge refines to
    ``Profile.update``.
"""

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

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "tests", "fixtures", "type_resolution",
)

CLEAN_APP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "fixtures", "clean_app",
)


# ─── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def tmp_db_path():
    """Return a path to a fresh temp .db file (not created)."""
    tmpdir = tempfile.mkdtemp(prefix="codelens_type_test_")
    db_path = os.path.join(tmpdir, "test.db")
    yield db_path
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def scanned_type_resolution_fixture():
    """Copy the type_resolution fixture to a temp workspace and scan it.

    Yields the workspace path. The scan populates the flat backend.json
    registry, the graph_nodes + graph_edges tables, AND runs the hybrid
    type resolver (issue #13) so import_registry + IMPORTS edges are
    also populated.
    """
    if not os.path.isdir(FIXTURE_DIR):
        pytest.skip("type_resolution fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_tr_fixture_")
    for entry in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    from commands.scan import cmd_scan
    cmd_scan(workspace, incremental=False)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def scanned_clean_app():
    """Copy clean_app fixture to a temp workspace and run a full scan."""
    if not os.path.isdir(CLEAN_APP_DIR):
        pytest.skip("clean_app fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_clean_app_")
    for entry in os.listdir(CLEAN_APP_DIR):
        src = os.path.join(CLEAN_APP_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    from commands.scan import cmd_scan
    cmd_scan(workspace, incremental=False)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


# ─── 1. Python Import Parsing ────────────────────────────────


class TestPythonImportParsing:
    """Verify build_import_registry parses Python import forms."""

    def test_from_import(self, tmp_db_path):
        """``from X import Y`` should produce local_name=Y, module=X."""
        from hybrid_type_resolver import _parse_py_imports
        content = "from models import User\n"
        bindings = _parse_py_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "User"
        assert module == "models"
        assert symbol == "User"
        assert line == 1

    def test_from_import_as(self, tmp_db_path):
        """``from X import Y as Z`` should produce local_name=Z."""
        from hybrid_type_resolver import _parse_py_imports
        content = "from models import User as U\n"
        bindings = _parse_py_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "U"
        assert module == "models"
        assert symbol == "User"

    def test_from_import_multi(self, tmp_db_path):
        """``from X import A, B as C`` should produce two bindings."""
        from hybrid_type_resolver import _parse_py_imports
        content = "from utils import format_text, process_data as pd\n"
        bindings = _parse_py_imports(content)
        assert len(bindings) == 2
        names = {b[0]: (b[1], b[2]) for b in bindings}
        assert names["format_text"] == ("utils", "format_text")
        assert names["pd"] == ("utils", "process_data")

    def test_import_dotted(self, tmp_db_path):
        """``import X.Y`` should produce local_name=X, module=X.Y."""
        from hybrid_type_resolver import _parse_py_imports
        content = "import os.path\n"
        bindings = _parse_py_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "os"
        assert module == "os.path"
        assert symbol == "path"

    def test_import_dotted_as(self, tmp_db_path):
        """``import X.Y as Z`` should produce local_name=Z."""
        from hybrid_type_resolver import _parse_py_imports
        content = "import os.path as osp\n"
        bindings = _parse_py_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "osp"
        assert module == "os.path"
        assert symbol == "path"

    def test_from_import_parenthesized(self, tmp_db_path):
        """``from X import (A, B)`` (multi-line) should parse all names."""
        from hybrid_type_resolver import _parse_py_imports
        content = "from utils import (\n    format_text,\n    process_data,\n)\n"
        bindings = _parse_py_imports(content)
        names = {b[0] for b in bindings}
        assert "format_text" in names
        assert "process_data" in names


# ─── 2. TS/JS Import Parsing ─────────────────────────────────


class TestTSImportParsing:
    """Verify build_import_registry parses TS/JS import forms."""

    def test_named_import(self, tmp_db_path):
        """``import {Y} from 'X'`` should produce local_name=Y, module=X."""
        from hybrid_type_resolver import _parse_ts_imports
        content = "import { User } from './models';\n"
        bindings = _parse_ts_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "User"
        assert module == "./models"
        assert symbol == "User"

    def test_named_import_as(self, tmp_db_path):
        """``import {Y as Z} from 'X'`` should produce local_name=Z."""
        from hybrid_type_resolver import _parse_ts_imports
        content = "import { User as U } from './models';\n"
        bindings = _parse_ts_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "U"
        assert symbol == "User"

    def test_namespace_import(self, tmp_db_path):
        """``import * as X from 'Y'`` should produce local_name=X, symbol=*."""
        from hybrid_type_resolver import _parse_ts_imports
        content = "import * as React from 'react';\n"
        bindings = _parse_ts_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "React"
        assert module == "react"
        assert symbol == "*"

    def test_default_import(self, tmp_db_path):
        """``import X from 'Y'`` should produce local_name=X, symbol=default."""
        from hybrid_type_resolver import _parse_ts_imports
        content = "import DefaultExport from './default';\n"
        bindings = _parse_ts_imports(content)
        assert len(bindings) == 1
        local, module, symbol, line = bindings[0]
        assert local == "DefaultExport"
        assert module == "./default"
        assert symbol == "default"

    def test_multiline_named_import(self, tmp_db_path):
        """Multi-line ``import { A, B } from 'X'`` should parse all names."""
        from hybrid_type_resolver import _parse_ts_imports
        content = (
            "import {\n"
            "  Foo,\n"
            "  Bar,\n"
            "} from './utils';\n"
        )
        bindings = _parse_ts_imports(content)
        names = {b[0] for b in bindings}
        assert "Foo" in names
        assert "Bar" in names


# ─── 3 & 4. resolve_receiver_type ────────────────────────────


class TestResolveReceiverType:
    """Verify resolve_receiver_type for simple + unknown receivers."""

    def test_resolves_simple_imported_name(self):
        """A receiver that is directly imported should resolve to its qualified name."""
        from hybrid_type_resolver import resolve_receiver_type
        import_registry = {"main.py": {"User": "models.User"}}
        resolved = resolve_receiver_type("main.py", "User", import_registry)
        assert resolved == "models.User"

    def test_returns_none_for_unknown_name(self):
        """An unknown receiver (not imported, not a local var) should return None."""
        from hybrid_type_resolver import resolve_receiver_type
        import_registry = {"main.py": {"User": "models.User"}}
        resolved = resolve_receiver_type(
            "main.py", "unknown_obj", import_registry,
            local_var_types={},
        )
        assert resolved is None

    def test_resolves_local_var(self):
        """A local variable assigned from an imported constructor should resolve."""
        from hybrid_type_resolver import resolve_receiver_type
        import_registry = {"main.py": {"User": "models.User"}}
        local_types = {"user": "models.User"}
        resolved = resolve_receiver_type(
            "main.py", "user", import_registry,
            local_var_types=local_types,
        )
        assert resolved == "models.User"

    def test_no_crash_on_empty_inputs(self):
        """Empty receiver or empty registry must not raise."""
        from hybrid_type_resolver import resolve_receiver_type
        assert resolve_receiver_type("", "User", {}) is None
        assert resolve_receiver_type("main.py", "", {}) is None
        assert resolve_receiver_type("main.py", "User", {}) is None


# ─── 5, 6, 8. refine_call_edges + IMPORTS edges ──────────────


class TestRefineCallEdges:
    """Verify refine_call_edges on the synthetic type_resolution fixture."""

    def test_refines_user_profile_update_edge(self, scanned_type_resolution_fixture):
        """``user.profile.update()`` should refine to Profile.update.

        After scan + refine, the CALLS edge from main() whose ``to_fn`` is
        ``update`` must have:
          * ``target_id`` pointing to the ``update`` node in ``models.py``
            (NOT ``cache.py`` — disambiguation).
          * ``resolved_type`` = ``models.Profile`` in ``extra_json``.
          * ``resolution_method`` = ``import_registry`` in ``extra_json``.
        """
        import json
        from graph_model import _default_db_path
        workspace = scanned_type_resolution_fixture
        db_path = _default_db_path(workspace)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        # Find the update edge from main.py.
        rows = conn.execute(
            "SELECT id, source_id, target_id, extra_json FROM graph_edges "
            "WHERE edge_type = 'CALLS' AND source_id LIKE 'main.py%' "
            "ORDER BY id"
        ).fetchall()
        conn.close()

        # Find the edge whose target's name is "update" (after refinement).
        update_edge = None
        for row in rows:
            extra = json.loads(row["extra_json"] or "{}")
            if extra.get("resolved_type") == "models.Profile":
                update_edge = row
                break
        assert update_edge is not None, (
            "expected a refined edge with resolved_type='models.Profile'"
        )

        # The target must be the update function in models.py, NOT cache.py.
        target_id = update_edge["target_id"]
        assert target_id is not None
        assert "models.py" in target_id, (
            "target_id must point to models.py (Profile.update), got: {}".format(
                target_id
            )
        )

        # Verify the target node's name is "update".
        conn = sqlite3.connect(db_path)
        target_row = conn.execute(
            "SELECT name, file FROM graph_nodes WHERE node_id = ?",
            (target_id,),
        ).fetchone()
        conn.close()
        assert target_row[0] == "update"
        assert target_row[1] == "models.py"

    def test_refines_user_greet_edge(self, scanned_type_resolution_fixture):
        """``user.greet()`` should refine to User.greet with resolved_type=models.User."""
        import json
        from graph_model import _default_db_path
        workspace = scanned_type_resolution_fixture
        db_path = _default_db_path(workspace)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, source_id, target_id, extra_json FROM graph_edges "
            "WHERE edge_type = 'CALLS' AND source_id LIKE 'main.py%' "
            "ORDER BY id"
        ).fetchall()
        conn.close()

        greet_edge = None
        for row in rows:
            extra = json.loads(row["extra_json"] or "{}")
            if extra.get("resolved_type") == "models.User":
                greet_edge = row
                break
        assert greet_edge is not None, (
            "expected a refined edge with resolved_type='models.User'"
        )

        target_id = greet_edge["target_id"]
        assert target_id is not None
        assert "models.py" in target_id

    def test_unresolvable_edge_gets_resolution_attempted_flag(self):
        """An unresolvable call should keep target_id NULL and gain resolution_attempted."""
        import json
        workspace = tempfile.mkdtemp(prefix="codelens_unresolvable_")
        try:
            # Write a tiny Python file with an unresolvable call.
            with open(os.path.join(workspace, "main.py"), "w") as f:
                f.write(
                    "def main():\n"
                    "    obj.unknown_method()\n"  # obj is not imported, no local type
                    "    return None\n"
                )
            from commands.scan import cmd_scan
            cmd_scan(workspace, incremental=False)

            from hybrid_type_resolver import refine_call_edges
            from graph_model import _default_db_path
            db_path = _default_db_path(workspace)
            stats = refine_call_edges(workspace, db_path)

            # At least one edge should be unresolved.
            assert stats["edges_unresolved"] >= 1, (
                "expected at least one unresolved edge, got stats={}".format(stats)
            )

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, target_id, extra_json FROM graph_edges "
                "WHERE edge_type = 'CALLS' AND target_id IS NULL"
            ).fetchall()
            conn.close()

            # At least one unresolved edge should have resolution_attempted=True.
            found_flag = False
            for row in rows:
                extra = json.loads(row["extra_json"] or "{}")
                if extra.get("resolution_attempted") is True:
                    found_flag = True
                    break
            assert found_flag, (
                "expected at least one edge with resolution_attempted=True"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_imports_edges_are_written(self, scanned_type_resolution_fixture):
        """IMPORTS edges must be present in graph_edges after scan + refine."""
        from graph_model import _default_db_path
        workspace = scanned_type_resolution_fixture
        db_path = _default_db_path(workspace)

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE edge_type = 'IMPORTS'"
        ).fetchone()[0]
        conn.close()

        # The fixture's main.py imports User from models — at least 1 IMPORTS edge.
        assert count >= 1, (
            "expected at least 1 IMPORTS edge, got {}".format(count)
        )

    def test_imports_edge_target_resolves_to_symbol_node(
        self, scanned_type_resolution_fixture
    ):
        """IMPORTS edge for ``from models import User`` must target the User class node."""
        import json
        from graph_model import _default_db_path
        workspace = scanned_type_resolution_fixture
        db_path = _default_db_path(workspace)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source_id, target_id, extra_json FROM graph_edges "
            "WHERE edge_type = 'IMPORTS'"
        ).fetchall()
        conn.close()

        # Find the IMPORTS edge for `from models import User`.
        user_import_edge = None
        for row in rows:
            extra = json.loads(row["extra_json"] or "{}")
            if (extra.get("module_path") == "models"
                    and extra.get("symbol_name") == "User"):
                user_import_edge = row
                break
        assert user_import_edge is not None, (
            "expected an IMPORTS edge for `from models import User`"
        )

        # The target should be the User class node.
        target_id = user_import_edge["target_id"]
        assert target_id is not None, (
            "IMPORTS edge for User should have a resolvable target_id"
        )
        conn = sqlite3.connect(db_path)
        target_row = conn.execute(
            "SELECT name, node_type FROM graph_nodes WHERE node_id = ?",
            (target_id,),
        ).fetchone()
        conn.close()
        assert target_row[0] == "User"
        assert target_row[1] == "class"


# ─── 7. resolve-types command ────────────────────────────────
# Issue #195: resolve-types was dropped as a standalone command.
# The underlying HybridTypeResolver engine is still tested above.
# Skip the command-level tests since the command no longer exists.


import pytest as _pytest


@_pytest.mark.skip(reason="resolve-types command dropped in issue #195 consolidation")
class TestResolveTypesCommand:
    """Verify the resolve-types CLI command."""

    def test_returns_correct_stats(self, scanned_type_resolution_fixture):
        """resolve-types must return {status, edges_total, edges_refined, edges_unresolved, import_registry_size}."""
        import argparse
        from commands import get_command
        workspace = scanned_type_resolution_fixture

        cmd = get_command("resolve-types")
        assert cmd is not None, "resolve-types command must be registered"

        args = argparse.Namespace(workspace=None, db_path=None)
        result = cmd["execute"](args, workspace)

        assert result["status"] == "ok"
        assert "edges_total" in result
        assert "edges_refined" in result
        assert "edges_unresolved" in result
        assert "import_registry_size" in result
        assert result["edges_total"] > 0
        assert result["edges_refined"] >= 1, (
            "expected at least 1 refined edge on the type_resolution fixture"
        )
        assert result["import_registry_size"] >= 1

    def test_auto_scans_when_db_missing(self):
        """resolve-types must auto-scan when the database doesn't exist."""
        import argparse
        from commands import get_command
        workspace = tempfile.mkdtemp(prefix="codelens_rt_autoscan_")
        try:
            # Copy the fixture in.
            for entry in os.listdir(FIXTURE_DIR):
                src = os.path.join(FIXTURE_DIR, entry)
                dst = os.path.join(workspace, entry)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)

            cmd = get_command("resolve-types")
            args = argparse.Namespace(workspace=None, db_path=None)
            result = cmd["execute"](args, workspace)

            assert result["status"] == "ok"
            assert result["edges_total"] > 0
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 9. End-to-end on clean_app fixture ──────────────────────


class TestCleanAppEndToEnd:
    """Verify scan -> resolve-types produces refined edges on clean_app."""

    def test_some_edges_have_resolved_type(self, scanned_clean_app):
        """After scan + resolve-types, at least one CALLS edge must have resolved_type."""
        import json
        from graph_model import _default_db_path
        from hybrid_type_resolver import refine_call_edges
        workspace = scanned_clean_app
        db_path = _default_db_path(workspace)

        # Run refine again (scan already ran it, but this verifies idempotency).
        stats = refine_call_edges(workspace, db_path)

        assert stats["edges_total"] > 0, "clean_app should have CALLS edges"
        assert stats["edges_refined"] >= 1, (
            "expected at least 1 refined edge on clean_app, got: {}".format(stats)
        )

        # Verify at least one edge has resolved_type in extra_json.
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT extra_json FROM graph_edges "
            "WHERE edge_type = 'CALLS' AND extra_json LIKE '%resolved_type%' "
            "LIMIT 5"
        ).fetchall()
        conn.close()

        assert len(rows) >= 1, "expected at least one edge with resolved_type"
        # Verify the resolved_type field is actually present in the JSON.
        for row in rows:
            extra = json.loads(row["extra_json"] or "{}")
            assert "resolved_type" in extra
            assert extra["resolved_type"]  # non-empty

    def test_imports_edges_populated_on_clean_app(self, scanned_clean_app):
        """IMPORTS edges must be populated on clean_app (it has many imports)."""
        from graph_model import _default_db_path
        workspace = scanned_clean_app
        db_path = _default_db_path(workspace)

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM graph_edges WHERE edge_type = 'IMPORTS'"
        ).fetchone()[0]
        conn.close()

        # clean_app's main.py imports ~20 symbols — expect many IMPORTS edges.
        assert count >= 10, (
            "expected at least 10 IMPORTS edges on clean_app, got {}".format(count)
        )

    def test_import_registry_table_populated(self, scanned_clean_app):
        """import_registry table must have rows after scan."""
        from graph_model import _default_db_path
        from hybrid_type_resolver import import_registry_size
        workspace = scanned_clean_app
        db_path = _default_db_path(workspace)

        size = import_registry_size(db_path)
        assert size >= 10, (
            "expected at least 10 import_registry rows on clean_app, got {}".format(size)
        )
