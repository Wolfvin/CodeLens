"""
Tests for line-independent node identity in the snapshot diff (issue #300).

`_diff_backend()` keyed nodes by `n["id"]`, which embeds a line number, so
adding a comment to a file reported every function in it as added AND removed
and fired false `new_dead` / `resolved_dead`. On the real 4,188-node polyglot
workspace a pure line shift produced 1,137 false adds, 1,137 false removes and
260 false dead-code alarms.

Covers:
- ``_node_key()`` / ``_index_nodes()`` — line independence, owner separation,
  duplicate-define disambiguation.
- ``_diff_backend()`` — no churn on line shift, real adds/removes/dead still
  detected, changed_nodes surviving a shift, output shape unchanged.
"""

from __future__ import annotations

import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from diff_engine import (  # noqa: E402
    _diff_backend,
    _index_nodes,
    _node_key,
)


def _node(node_id, fn, line, ref_count=1, status="active", file=None, **extra):
    node = {
        "id": node_id,
        "fn": fn,
        "file": file if file is not None else node_id.split(":")[0],
        "line": line,
        "ref_count": ref_count,
        "status": status,
    }
    node.update(extra)
    return node


def _backend(nodes, edges=None):
    return {"nodes": nodes, "edges": edges or []}


# ─── identity ────────────────────────────────────────────

def test_node_key_ignores_line_number():
    before = _node("app.py:10", "handler", 10)
    after = _node("app.py:42", "handler", 42)

    assert _node_key(before) == _node_key(after)


def test_node_key_separates_same_name_methods_by_owner():
    a = _node("app.py:10", "copy", 10, impl_for="TaintInfo")
    b = _node("app.py:20", "copy", 20, impl_for="TaintState")

    assert _node_key(a) != _node_key(b)


def test_node_key_separates_same_name_across_files():
    a = _node("a.py:10", "main", 10)
    b = _node("b.py:10", "main", 10)

    assert _node_key(a) != _node_key(b)


def test_index_nodes_disambiguates_duplicate_defines():
    """Closures redefined in one scope must not collapse onto one key."""
    nodes = [
        _node("p.py:10", "visit", 10, impl_for="P"),
        _node("p.py:50", "visit", 50, impl_for="P", duplicate_define=True),
    ]

    index = _index_nodes(nodes)

    assert len(index) == 2


def test_index_nodes_keeps_duplicate_order_stable_under_line_shift():
    before = _index_nodes([
        _node("p.py:10", "visit", 10, impl_for="P"),
        _node("p.py:50", "visit", 50, impl_for="P", duplicate_define=True),
    ])
    after = _index_nodes([
        _node("p.py:15", "visit", 15, impl_for="P"),
        _node("p.py:55", "visit", 55, impl_for="P", duplicate_define=True),
    ])

    assert set(before) == set(after)


# ─── the regression ──────────────────────────────────────

def test_line_shift_reports_no_node_change():
    """Issue #300: a comment at the top of a file changed every node id."""
    old = _backend([
        _node("checkout.py:6", "handle_checkout", 6, ref_count=0, status="dead"),
        _node("checkout.py:12", "send_receipt", 12),
    ])
    new = _backend([
        _node("checkout.py:11", "handle_checkout", 11, ref_count=0, status="dead"),
        _node("checkout.py:17", "send_receipt", 17),
    ])

    result = _diff_backend(old, new)

    assert result["added_nodes"] == []
    assert result["removed_nodes"] == []
    assert result["changed_nodes"] == []
    assert result["added_count"] == 0
    assert result["removed_count"] == 0


def test_already_dead_function_is_not_reported_newly_dead_after_shift():
    """The dangerous one: agents delete code that `new_dead` points at."""
    old = _backend([_node("a.py:1", "entry", 1, ref_count=0, status="dead")])
    new = _backend([_node("a.py:9", "entry", 9, ref_count=0, status="dead")])

    result = _diff_backend(old, new)

    assert result["new_dead"] == []
    assert result["resolved_dead"] == []


# ─── real signals still land ─────────────────────────────

def test_genuinely_added_and_removed_nodes_detected():
    old = _backend([_node("a.py:1", "goneFn", 1)])
    new = _backend([_node("a.py:1", "freshFn", 1)])

    result = _diff_backend(old, new)

    assert [n["name"] for n in result["added_nodes"]] == ["freshFn"]
    assert [n["name"] for n in result["removed_nodes"]] == ["goneFn"]


def test_genuinely_newly_dead_is_detected():
    old = _backend([_node("a.py:1", "f", 1, ref_count=1, status="active")])
    new = _backend([_node("a.py:9", "f", 9, ref_count=0, status="dead")])

    result = _diff_backend(old, new)

    assert [n["name"] for n in result["new_dead"]] == ["f"]


def test_status_and_refcount_change_survives_a_line_shift():
    """
    Previously a shifted node was never compared against its old self, so its
    ref_count/status change vanished. Removing the churn also recovers this.
    """
    old = _backend([_node("a.py:1", "f", 1, ref_count=2, status="active")])
    new = _backend([_node("a.py:9", "f", 9, ref_count=1, status="active")])

    result = _diff_backend(old, new)

    assert len(result["changed_nodes"]) == 1
    assert result["changed_nodes"][0]["ref_count"] == {"from": 2, "to": 1}


def test_deleting_one_of_two_duplicate_defines_is_detected():
    old = _backend([
        _node("p.py:10", "visit", 10, impl_for="P"),
        _node("p.py:50", "visit", 50, impl_for="P", duplicate_define=True),
    ])
    new = _backend([_node("p.py:12", "visit", 12, impl_for="P")])

    result = _diff_backend(old, new)

    assert [n["name"] for n in result["removed_nodes"]] == ["visit"]


def test_function_moved_to_another_file_counts_as_moved():
    """File is part of identity — a cross-file move is a real relocation."""
    old = _backend([_node("a.py:1", "f", 1)])
    new = _backend([_node("b.py:1", "f", 1)])

    result = _diff_backend(old, new)

    assert [n["name"] for n in result["added_nodes"]] == ["f"]
    assert [n["name"] for n in result["removed_nodes"]] == ["f"]


# ─── shape ───────────────────────────────────────────────

def test_output_shape_unchanged():
    old = _backend([_node("a.py:1", "goneFn", 1)])
    new = _backend([_node("a.py:5", "freshFn", 5, status="dead", ref_count=0)])

    result = _diff_backend(old, new)

    for key in (
        "added_nodes", "removed_nodes", "changed_nodes",
        "added_count", "removed_count", "changed_count",
        "new_dead", "resolved_dead",
    ):
        assert key in result

    assert set(result["added_nodes"][0]) == {"name", "file", "status"}
    assert set(result["removed_nodes"][0]) == {"name", "file"}


def test_edge_diff_still_works_through_id_map():
    """Node diffing moved off raw ids; edges must still resolve by id."""
    old = _backend(
        [_node("a.py:1", "caller", 1), _node("a.py:9", "callee", 9)],
        [],
    )
    new = _backend(
        [_node("a.py:1", "caller", 1), _node("a.py:9", "callee", 9)],
        [{"from": "a.py:1", "to": "a.py:9"}],
    )

    result = _diff_backend(old, new)

    assert result["added_edge_count"] == 1
    assert result["added_edges"][0]["from"] == "caller"
    assert result["added_edges"][0]["to"] == "callee"
