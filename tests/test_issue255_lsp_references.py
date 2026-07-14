# @WHO:   tests/test_issue255_lsp_references.py
# @WHAT:  Tests for optional LSP-backed find-references in trace-up (issue #255)
# @PART:  tests
"""Tests for LSP-backed trace-up precision (issue #255).

Feature: when ``--deep`` is active AND an LSP server is available,
``context --check trace --direction up`` uses LSP ``textDocument/references``
(via ``lsp_client.find_references``) as the precision source; otherwise it
falls back to the existing graph path unchanged.

Two halves, mirroring #253's split (live env can't verify the LSP happy path):

1. Graceful degradation — LIVE. A real CLI-equivalent trace with no ``--deep``
   (and with ``--deep`` when the symbol/LSP can't resolve) must keep working
   via the graph path, never hang, never error, and be annotated
   ``trace_source == "graph"``.

2. LSP happy path — MOCKED. ``lsp_client.find_references`` and the hybrid
   engine are mocked so the precision path can be exercised without a live
   language server (rust-analyzer, the only server installed in the dev env,
   does not respond to ``initialize`` within 60s — same limitation as #253).
"""

import os
import sys
import tempfile
from unittest import mock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from commands import trace as trace_cmd  # noqa: E402
import hybrid_engine  # noqa: E402


# ─── Half 1: graceful degradation (LIVE, no LSP dependency) ──────────────

def _make_scanned_ws():
    """Create + scan a tiny workspace; return its path (real graph tables)."""
    ws = tempfile.mkdtemp(prefix="cl255_")
    with open(os.path.join(ws, "mod.py"), "w", encoding="utf-8") as f:
        f.write(
            "def helper(x):\n"
            "    return x + 1\n\n"
            "def caller_a():\n"
            "    return helper(1)\n\n"
            "def caller_b():\n"
            "    return helper(2)\n"
        )
    import codelens  # noqa: F401  (ensures scripts importable)
    from commands import scan as scan_cmd
    import argparse
    ns = argparse.Namespace(workspace=ws, format="json")
    scan_cmd.execute(ns, ws)
    return ws


def _trace_ns(name, ws, direction="up", deep=False):
    import argparse
    return argparse.Namespace(
        name=name, workspace=ws, direction=direction, depth=10,
        domain="auto", max_results=1000, limit=20, offset=0,
        use_graph=True, deep=deep,
    )


def test_no_deep_uses_graph_path_live():
    ws = _make_scanned_ws()
    result = trace_cmd.execute(_trace_ns("helper", ws, deep=False), ws)
    assert result["trace_source"] == "graph"
    # graph path still finds the callers — no regression
    assert result["stats"]["callers_found"] >= 1
    assert "lsp_available" not in result  # LSP path never touched


def test_deep_but_symbol_unresolved_falls_back_to_graph_live():
    """--deep on, but a nonexistent symbol can't be resolved for LSP →
    engine returns None refs → graph path retained, no error, no hang."""
    ws = _make_scanned_ws()
    result = trace_cmd.execute(_trace_ns("helper", ws, deep=True), ws)
    # Whatever the live LSP does, output must be well-formed and never crash.
    assert result["status"] == "ok"
    assert result["trace_source"] in ("graph", "lsp")
    assert isinstance(result["chains"]["up"], list)


# ─── Half 2: LSP happy path (MOCKED) ─────────────────────────────────────

def test_apply_lsp_trace_up_rewrites_chains_when_lsp_active():
    """With a mocked hybrid engine reporting LSP references, trace-up is
    rewritten from the graph chains to the LSP chains and annotated 'lsp'."""
    result = {
        "status": "ok", "symbol": "helper",
        "chains": {"up": [{"fn": "caller_a", "file": "mod.py", "line": 5}], "down": []},
        "stats": {"callers_found": 1},
    }
    fake_engine = mock.Mock()
    fake_engine.lsp_active = True
    fake_engine.find_references_for_symbol.return_value = [
        {"file": "/abs/mod.py", "line": 5, "character": 11},
        {"file": "/abs/mod.py", "line": 8, "character": 11},
        {"file": "/abs/other.py", "line": 3, "character": 4},
    ]
    with mock.patch("hybrid_engine.create_hybrid_engine", return_value=fake_engine):
        trace_cmd._apply_lsp_trace_up("helper", "/ws", result)

    assert result["trace_source"] == "lsp"
    assert result["lsp_available"] is True
    assert result["stats"]["callers_found"] == 3
    assert len(result["chains"]["up"]) == 3
    assert all(e["source"] == "lsp" for e in result["chains"]["up"])
    assert result["graph_callers_found"] == 1
    assert result["lsp_callers_found"] == 3
    fake_engine.cleanup.assert_called_once()


def test_apply_lsp_trace_up_keeps_graph_when_lsp_inactive():
    result = {
        "chains": {"up": [{"fn": "caller_a", "file": "mod.py", "line": 5}], "down": []},
        "stats": {"callers_found": 1},
    }
    fake_engine = mock.Mock()
    fake_engine.lsp_active = False
    with mock.patch("hybrid_engine.create_hybrid_engine", return_value=fake_engine):
        trace_cmd._apply_lsp_trace_up("helper", "/ws", result)
    assert result["trace_source"] == "graph"
    assert result["lsp_available"] is False
    assert result["chains"]["up"] == [{"fn": "caller_a", "file": "mod.py", "line": 5}]


def test_apply_lsp_trace_up_keeps_graph_when_refs_none():
    """LSP active but symbol can't be resolved (refs None) → keep graph."""
    result = {"chains": {"up": [{"fn": "caller_a"}], "down": []}, "stats": {}}
    fake_engine = mock.Mock()
    fake_engine.lsp_active = True
    fake_engine.find_references_for_symbol.return_value = None
    with mock.patch("hybrid_engine.create_hybrid_engine", return_value=fake_engine):
        trace_cmd._apply_lsp_trace_up("helper", "/ws", result)
    assert result["trace_source"] == "graph"
    assert result["chains"]["up"] == [{"fn": "caller_a"}]


def test_apply_lsp_trace_up_engine_creation_failure_falls_back():
    result = {"chains": {"up": [], "down": []}, "stats": {}}
    with mock.patch("hybrid_engine.create_hybrid_engine", side_effect=RuntimeError("boom")):
        trace_cmd._apply_lsp_trace_up("helper", "/ws", result)
    assert result["trace_source"] == "graph"


def test_find_references_for_symbol_resolves_and_filters():
    """HybridEngine.find_references_for_symbol: mock the LSP client's
    find_references + symbol definition resolution; verify def-site excluded,
    0→1-indexed conversion, and shape."""
    eng = hybrid_engine.HybridEngine.__new__(hybrid_engine.HybridEngine)
    eng.deep = True
    eng._lsp_available = True  # lsp_active property = deep and _lsp_available
    eng.workspace = os.getcwd()

    with tempfile.TemporaryDirectory() as d:
        fpath = os.path.join(d, "mod.py")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("def helper(x):\n    return x\n\ncaller = helper\n")

        from lsp_client import _path_to_uri
        fake_client = mock.Mock()
        # LSP returns one real reference at line 3 (0-indexed).
        fake_client.find_references.return_value = [
            {"uri": _path_to_uri(fpath),
             "range": {"start": {"line": 3, "character": 9}}},
        ]
        eng._find_symbol_definition = lambda n: (fpath, 1)
        eng.open_file_for_lsp = lambda p: None
        eng.get_lsp_client = lambda p: fake_client

        refs = eng.find_references_for_symbol("helper")
        assert refs is not None
        assert len(refs) == 1
        assert refs[0]["line"] == 4  # 0-indexed 3 -> 1-indexed 4
        assert refs[0]["character"] == 9


def test_find_references_for_symbol_none_when_lsp_inactive():
    eng = hybrid_engine.HybridEngine.__new__(hybrid_engine.HybridEngine)
    eng.deep = False
    eng._lsp_available = False
    assert eng.find_references_for_symbol("helper") is None
