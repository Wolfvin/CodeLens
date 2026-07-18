"""
Tests for get-function-source (`context --check source`, issue #316).

The direct replacement for "Read the whole file to see one function". Tests use
--file mode (no graph DB needed) for determinism, plus one graph-resolved case.
"""

import os
import sys

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from commands import source as source_cmd  # noqa: E402


class _Args:
    def __init__(self, name=None, file=None, db_path=None):
        self.name = name
        self.file = file
        self.db_path = db_path


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


SAMPLE = (
    "import os\n"                       # 1
    "\n"                                # 2
    "def first():\n"                    # 3
    '    """First."""\n'                # 4
    "    return 1\n"                    # 5
    "\n"                                # 6
    "\n"                                # 7
    "def second(x):\n"                  # 8
    "    return x + 1\n"                # 9
)


@pytest.fixture
def ws(tmp_path):
    root = str(tmp_path)
    _write(root, "mod.py", SAMPLE)
    return root


# ─── --file mode (no graph) ──────────────────────────────

def test_extracts_just_the_named_function(ws):
    out = source_cmd.execute(_Args(name="first", file="mod.py"), ws)
    assert out["found"] is True
    m = out["matches"][0]
    assert m["start_line"] == 3
    assert m["source"] == 'def first():\n    """First."""\n    return 1'


def test_boundary_stops_before_next_declaration(ws):
    out = source_cmd.execute(_Args(name="first", file="mod.py"), ws)
    m = out["matches"][0]
    assert "def second" not in m["source"]   # must not bleed into the next fn
    assert m["end_line"] == 5                 # trailing blanks trimmed


def test_last_function_runs_to_eof(ws):
    out = source_cmd.execute(_Args(name="second", file="mod.py"), ws)
    m = out["matches"][0]
    assert m["source"] == "def second(x):\n    return x + 1"


def test_unknown_function_is_not_found(ws):
    out = source_cmd.execute(_Args(name="nope", file="mod.py"), ws)
    assert out["found"] is False
    assert "nope" in out["message"]


def test_missing_name_is_an_error(ws):
    out = source_cmd.execute(_Args(name=None, file="mod.py"), ws)
    assert out["status"] == "error"
    assert out["error_type"] == "missing_argument"


# ─── ambiguity ───────────────────────────────────────────

def test_same_name_in_two_files_via_graph(tmp_path):
    root = str(tmp_path)
    _write(root, "a.py", "def handler():\n    return 'a'\n")
    _write(root, "b.py", "def handler():\n    return 'b'\n")

    # Populate the graph so name resolution finds both.
    import json
    cl = os.path.join(root, ".codelens")
    os.makedirs(cl, exist_ok=True)
    with open(os.path.join(cl, "backend.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": [
            {"id": "a.py:1", "fn": "handler", "file": "a.py", "line": 1,
             "ref_count": 0, "status": "active"},
            {"id": "b.py:1", "fn": "handler", "file": "b.py", "line": 1,
             "ref_count": 0, "status": "active"},
        ], "edges": []}, f)
    import graph_model as gm
    gm.populate_graph_tables(root)

    out = source_cmd.execute(_Args(name="handler"), root)
    assert out["found"] is True
    assert out["count"] == 2
    files = {m["file"] for m in out["matches"]}
    assert files == {"a.py", "b.py"}


def test_no_graph_and_no_file_is_a_clear_error(tmp_path):
    """Never scanned, no --file: an explicit error, not silent-empty."""
    out = source_cmd.execute(_Args(name="handler"), str(tmp_path))
    assert out["status"] == "error"
    assert out["error_type"] == "no_graph"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
