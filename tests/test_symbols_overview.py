"""Tests for context --check overview (issue #254): symbols fast-path."""

import os
import sqlite3
import tempfile
import sys

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


def _make_db(tmp_path, rows):
    """Create a minimal codelens.db with the given graph_nodes rows."""
    db_dir = tmp_path / ".codelens"
    db_dir.mkdir()
    db_path = str(db_dir / "codelens.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE graph_nodes ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  node_id TEXT NOT NULL UNIQUE,"
        "  node_type TEXT NOT NULL DEFAULT 'function',"
        "  name TEXT NOT NULL,"
        "  file TEXT,"
        "  line INTEGER,"
        "  extra_json TEXT"
        ")"
    )
    conn.executemany(
        "INSERT INTO graph_nodes (node_id, node_type, name, file, line) VALUES (?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path, str(tmp_path)


class TestSymbolsOverview:
    def test_overview_no_registry(self, tmp_path):
        """No DB → status no_registry, not a crash."""
        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file=None, max_files=200, db_path=str(tmp_path / ".codelens" / "codelens.db"))
        result = execute(args, str(tmp_path))
        assert result["status"] == "no_registry"

    def test_overview_returns_symbols(self, tmp_path):
        """DB with symbols → status ok, correct grouping."""
        rows = [
            ("auth.py:10", "function", "login", "auth.py", 10),
            ("auth.py:20", "class", "AuthService", "auth.py", 20),
            ("utils.py:5", "function", "hash_pw", "utils.py", 5),
        ]
        db_path, ws = _make_db(tmp_path, rows)

        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file=None, max_files=200, db_path=db_path)
        result = execute(args, ws)

        assert result["status"] == "ok"
        assert result["stats"]["total_files"] == 2
        assert result["stats"]["total_symbols"] == 3
        ov = result["overview"]
        assert "auth.py" in ov
        assert len(ov["auth.py"]) == 2
        names = {s["name"] for s in ov["auth.py"]}
        assert names == {"login", "AuthService"}

    def test_overview_file_filter(self, tmp_path):
        """--file filter restricts to matching files only."""
        rows = [
            ("auth.py:10", "function", "login", "auth.py", 10),
            ("utils.py:5", "function", "hash_pw", "utils.py", 5),
        ]
        db_path, ws = _make_db(tmp_path, rows)

        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file="auth.py", max_files=200, db_path=db_path)
        result = execute(args, ws)

        assert result["status"] == "ok"
        assert result["stats"]["total_files"] == 1
        assert "auth.py" in result["overview"]
        assert "utils.py" not in result["overview"]

    def test_overview_excludes_noise_kinds(self, tmp_path):
        """Unknown node_types are excluded from the overview."""
        rows = [
            ("f.py:1", "function", "good_fn", "f.py", 1),
            ("f.py:2", "import", "os", "f.py", 2),  # excluded
            ("f.py:3", "call", "some_call", "f.py", 3),  # excluded
        ]
        db_path, ws = _make_db(tmp_path, rows)

        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file=None, max_files=200, db_path=db_path)
        result = execute(args, ws)

        names = [s["name"] for s in result["overview"].get("f.py", [])]
        assert "good_fn" in names
        assert "os" not in names
        assert "some_call" not in names

    def test_overview_max_files_truncation(self, tmp_path):
        """max_files cap truncates workspace-wide results and sets truncated=True."""
        rows = [
            (f"file_{i}.py:{i}", "function", f"fn_{i}", f"file_{i}.py", i)
            for i in range(10)
        ]
        db_path, ws = _make_db(tmp_path, rows)

        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file=None, max_files=3, db_path=db_path)
        result = execute(args, ws)

        assert result["stats"]["truncated"] is True
        assert result["stats"]["total_files"] == 3

    def test_no_reparse(self, tmp_path):
        """execute() does not import any parser — read DB only."""
        rows = [("f.py:1", "function", "fn", "f.py", 1)]
        db_path, ws = _make_db(tmp_path, rows)

        import importlib
        before = set(sys.modules.keys())

        from commands.symbols_overview import execute
        import argparse
        args = argparse.Namespace(file=None, max_files=200, db_path=db_path)
        execute(args, ws)

        after = set(sys.modules.keys())
        new_mods = after - before
        parser_mods = {m for m in new_mods if "parser" in m.lower() and "tree" in m.lower()}
        assert not parser_mods, f"Unexpected parser imports: {parser_mods}"
