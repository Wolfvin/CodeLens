"""
Tests for the named-flow view (`context --check flow`, issue #309).

Covers, against a synthetic fixture tree:
- enclosing-symbol resolution: docstring idiom, comment-above-def idiom,
  file-header fallback, and look-ahead not binding across real code.
- cross-language collection of one flow.
- the `flow` command: --name filter (found + not-found), bare inventory.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from tag_audit_engine import audit_tags  # noqa: E402
from commands import flow as flow_cmd  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


@pytest.fixture
def tree(tmp_path):
    root = str(tmp_path)
    # Docstring idiom: tag inside the function body -> enclosing def above.
    _write(root, "routes.py",
           'def checkout_route(req):\n'
           '    """Entry.\n'
           '    @FLOW: PAYMENT\n'
           '    """\n'
           '    return validate(req)\n')
    # Comment-above-def idiom (JS): tag one line above the declaration.
    _write(root, "gateway.js",
           '// @FLOW: PAYMENT\n'
           'export function charge(amount) {\n'
           '  return stripe(amount);\n'
           '}\n')
    # File-header idiom: tag at the very top, no def near -> file fallback.
    _write(root, "types.d.ts",
           '// @WHO:   types.d.ts\n'
           '// @FLOW:  PURE (declarations only)\n'
           '\n'
           'export type Money = number;\n')
    return root


def _flows(root):
    return {f["name"]: f for f in audit_tags(root)["flows"]}


# ─── enclosing-symbol resolution ─────────────────────────

def test_docstring_tag_binds_to_enclosing_function(tree):
    members = {(m["file"], m["symbol"]) for m in _flows(tree)["PAYMENT"]["members"]}
    assert ("routes.py", "checkout_route") in members


def test_comment_above_def_binds_to_def_below(tree):
    members = {(m["file"], m["symbol"]) for m in _flows(tree)["PAYMENT"]["members"]}
    assert ("gateway.js", "charge") in members


def test_file_header_tag_falls_back_to_file(tree):
    pure = _flows(tree)["PURE"]["members"]
    assert len(pure) == 1
    assert pure[0]["symbol"] == ""          # no enclosing symbol -> file-level
    assert pure[0]["file"] == "types.d.ts"


def test_lookahead_does_not_cross_real_code(tmp_path):
    """A docstring tag must not bind to a nested def a few lines down."""
    root = str(tmp_path)
    _write(root, "a.py",
           'def outer():\n'
           '    """\n'
           '    @FLOW: OUTER\n'
           '    """\n'
           '    x = 1\n'
           '    def inner():\n'
           '        pass\n')
    members = _flows(root)["OUTER"]["members"]
    assert members[0]["symbol"] == "outer"   # not "inner"


def test_flow_collected_across_languages(tree):
    payment = _flows(tree)["PAYMENT"]
    assert payment["count"] == 2
    files = {m["file"] for m in payment["members"]}
    assert files == {"routes.py", "gateway.js"}


# ─── the flow command ────────────────────────────────────

def _run(root, name=None):
    args = argparse.Namespace(name=name)
    return flow_cmd.execute(args, root)


def test_named_flow_returns_only_that_flow(tree):
    out = _run(tree, "PAYMENT")
    assert out["found"] is True
    assert out["flow"] == "PAYMENT"
    assert out["count"] == 2
    assert {m["symbol"] for m in out["members"]} == {"checkout_route", "charge"}


def test_unknown_flow_is_not_found_with_available_list(tree):
    out = _run(tree, "NOPE")
    assert out["found"] is False
    assert out["count"] == 0
    assert "PAYMENT" in out["available_flows"]


def test_bare_flow_lists_every_flow(tree):
    out = _run(tree)
    names = {f["name"] for f in out["flows"]}
    assert {"PAYMENT", "PURE"} <= names
    assert out["summary"]["distinct_flows"] == len(out["flows"])


# ─── subgraph: call-edges among members (issue #311) ─────

def test_no_graph_db_degrades_to_flat_list(tree):
    """A workspace that was never scanned yields members but no edges."""
    out = _run(tree, "PAYMENT")
    assert out["members"]                 # still collected
    assert out["edges"] == []             # graceful: no DB, no edges


def _populate_graph(root, nodes, edges):
    cl = os.path.join(root, ".codelens")
    os.makedirs(cl, exist_ok=True)
    with open(os.path.join(cl, "backend.json"), "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f)
    import graph_model as gm
    gm.populate_graph_tables(root)


def test_subgraph_edges_among_members(tmp_path):
    root = str(tmp_path)
    _write(root, "routes.py",
           'def checkout(req):\n    """\n    @FLOW: PAY\n    """\n    return validate(req)\n')
    _write(root, "cart.py",
           'def validate(c):\n    """\n    @FLOW: PAY\n    """\n    return charge(c)\n')
    _write(root, "gw.py",
           'def charge(c):\n    """\n    @FLOW: PAY\n    """\n    return 1\n')
    _populate_graph(
        root,
        nodes=[
            {"id": "routes.py:1", "fn": "checkout", "file": "routes.py", "line": 1,
             "ref_count": 0, "status": "active"},
            {"id": "cart.py:1", "fn": "validate", "file": "cart.py", "line": 1,
             "ref_count": 1, "status": "active"},
            {"id": "gw.py:1", "fn": "charge", "file": "gw.py", "line": 1,
             "ref_count": 1, "status": "active"},
        ],
        edges=[
            {"from": "routes.py:1", "to": "cart.py:1"},
            {"from": "cart.py:1", "to": "gw.py:1"},
        ],
    )

    out = _run(root, "PAY")
    pairs = {(e["from"], e["to"]) for e in out["edges"]}
    assert pairs == {("checkout", "validate"), ("validate", "charge")}


def test_subgraph_excludes_edges_leaving_the_flow(tmp_path):
    """An edge to a function outside the flow must not appear."""
    root = str(tmp_path)
    _write(root, "a.py",
           'def a():\n    """\n    @FLOW: F\n    """\n    return helper()\n')
    _write(root, "h.py", 'def helper():\n    return 1\n')  # not tagged
    _populate_graph(
        root,
        nodes=[
            {"id": "a.py:1", "fn": "a", "file": "a.py", "line": 1,
             "ref_count": 0, "status": "active"},
            {"id": "h.py:1", "fn": "helper", "file": "h.py", "line": 1,
             "ref_count": 1, "status": "active"},
        ],
        edges=[{"from": "a.py:1", "to": "h.py:1"}],
    )

    out = _run(root, "F")
    assert out["edges"] == []             # helper is outside the flow


if __name__ == "__main__":
    import pytest as _p
    _p.main([__file__, "-v"])
