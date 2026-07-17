"""
Tests for call-graph edge comparison in the snapshot diff engine (issue #297).

Covers:
- ``_endpoint_key()`` — line-independent identity, owner disambiguation,
  fallback for ids that resolve to no node.
- ``_diff_backend()`` — added / removed edge detection, line-shift immunity,
  call-site multiplicity ignored, unresolved edges counted not enumerated,
  detail cap with exact counts, legacy node fields left untouched.
- ``diff_snapshots()`` — edge counts surfaced in the summary block.
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from diff_engine import (  # noqa: E402
    EDGE_DETAIL_CAP,
    _diff_backend,
    _endpoint_key,
    _split_edges,
    diff_snapshots,
    save_snapshot,
)


def _node(node_id, fn, file="app.py", **extra):
    node = {"id": node_id, "fn": fn, "file": file, "ref_count": 1, "status": "active"}
    node.update(extra)
    return node


def _backend(nodes, edges):
    return {"nodes": nodes, "edges": edges}


# ─── _endpoint_key ───────────────────────────────────────

def test_endpoint_key_is_line_independent():
    """Same function at a different line yields the same key."""
    before = {"app.py:10": _node("app.py:10", "handler")}
    after = {"app.py:42": _node("app.py:42", "handler")}

    assert _endpoint_key("app.py:10", before) == _endpoint_key("app.py:42", after)


def test_endpoint_key_separates_same_name_methods_by_owner():
    """Two classes in one file, both with `copy`, must not collapse."""
    nodes = {
        "app.py:10": _node("app.py:10", "copy", impl_for="TaintInfo"),
        "app.py:20": _node("app.py:20", "copy", impl_for="TaintState"),
    }

    assert _endpoint_key("app.py:10", nodes) != _endpoint_key("app.py:20", nodes)


def test_endpoint_key_normalises_missing_owner_to_string():
    """A missing owner must stay sortable against a present one."""
    nodes = {
        "app.py:10": _node("app.py:10", "free_fn"),
        "app.py:20": _node("app.py:20", "method", impl_for="Cls"),
    }
    keys = [_endpoint_key("app.py:10", nodes), _endpoint_key("app.py:20", nodes)]

    assert all(isinstance(part, str) for key in keys for part in key)
    sorted(keys)  # must not raise TypeError


def test_endpoint_key_falls_back_to_raw_id_for_unknown_node():
    """Module-level synthetic sources carry no node by design."""
    assert _endpoint_key("app.py:0:<module>", {}) == ("", "", "app.py:0:<module>")


# ─── _diff_backend: the line-shift regression ────────────

def test_line_shift_alone_reports_no_edge_change():
    """
    Issue #297 root cause: node ids embed a line number, so keying edges by
    raw id reported every edge of a shifted function as removed and re-added.
    """
    old = _backend(
        [_node("app.py:10", "caller"), _node("app.py:50", "callee")],
        [{"from": "app.py:10", "to": "app.py:50"}],
    )
    # Identical graph, everything moved down 5 lines.
    new = _backend(
        [_node("app.py:15", "caller"), _node("app.py:55", "callee")],
        [{"from": "app.py:15", "to": "app.py:55"}],
    )

    result = _diff_backend(old, new)

    assert result["added_edge_count"] == 0
    assert result["removed_edge_count"] == 0
    assert result["added_edges"] == []
    assert result["removed_edges"] == []


# ─── _diff_backend: real changes ─────────────────────────

def test_added_edge_is_detected():
    nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
    old = _backend(nodes, [])
    new = _backend(nodes, [{"from": "app.py:10", "to": "app.py:50"}])

    result = _diff_backend(old, new)

    assert result["added_edge_count"] == 1
    assert result["removed_edge_count"] == 0
    assert result["added_edges"] == [
        {"from": "caller", "from_file": "app.py", "to": "callee", "to_file": "app.py"}
    ]


def test_removed_edge_is_detected():
    nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
    old = _backend(nodes, [{"from": "app.py:10", "to": "app.py:50"}])
    new = _backend(nodes, [])

    result = _diff_backend(old, new)

    assert result["removed_edge_count"] == 1
    assert result["added_edge_count"] == 0
    assert result["removed_edges"][0]["to"] == "callee"


def test_owner_qualified_label_in_detail():
    nodes = [
        _node("app.py:10", "charge", impl_for="Checkout"),
        _node("app.py:50", "send", impl_for="Gateway"),
    ]
    new = _backend(nodes, [{"from": "app.py:10", "to": "app.py:50"}])

    result = _diff_backend(_backend(nodes, []), new)

    assert result["added_edges"][0]["from"] == "Checkout.charge"
    assert result["added_edges"][0]["to"] == "Gateway.send"


def test_extra_call_site_is_not_a_graph_change():
    """One edge per call site: multiplicity is not shape."""
    nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
    edge = {"from": "app.py:10", "to": "app.py:50"}
    old = _backend(nodes, [edge])
    new = _backend(nodes, [edge, dict(edge)])

    result = _diff_backend(old, new)

    assert result["added_edge_count"] == 0
    assert result["removed_edge_count"] == 0


def test_via_self_is_a_qualifier_not_an_identity():
    nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
    old = _backend(nodes, [{"from": "app.py:10", "to": "app.py:50"}])
    new = _backend(
        nodes, [{"from": "app.py:10", "to": "app.py:50", "via_self": True}]
    )

    result = _diff_backend(old, new)

    assert result["added_edge_count"] == 0
    assert result["removed_edge_count"] == 0


# ─── _diff_backend: unresolved edges ─────────────────────

def test_unresolved_edges_are_counted_not_enumerated():
    """
    82% of real edges are unresolved stdlib calls (`append`, `strip`, `get`).
    They would drown the signal, so only the tally is reported.
    """
    nodes = [_node("app.py:10", "caller")]
    old = _backend(nodes, [])
    new = _backend(
        nodes,
        [
            {"from": "app.py:10", "to_fn": "append", "resolved": False},
            {"from": "app.py:10", "to_fn": "strip", "resolved": False},
        ],
    )

    result = _diff_backend(old, new)

    assert result["added_edges"] == []
    assert result["added_edge_count"] == 0
    assert result["unresolved_edges"] == {"before": 0, "after": 2, "delta": 2}


def test_split_edges_partitions_resolved_and_unresolved():
    nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
    registry = _backend(
        nodes,
        [
            {"from": "app.py:10", "to": "app.py:50"},
            {"from": "app.py:10", "to_fn": "append", "resolved": False},
        ],
    )
    node_map = {n["id"]: n for n in registry["nodes"]}

    resolved, unresolved = _split_edges(registry, node_map)

    assert len(resolved) == 1
    assert unresolved == 1


# ─── _diff_backend: cap and backward compatibility ───────

def test_detail_is_capped_but_counts_stay_exact():
    total = EDGE_DETAIL_CAP + 25
    nodes = [_node("app.py:1", "root")] + [
        _node(f"app.py:{i + 100}", f"fn{i}") for i in range(total)
    ]
    edges = [{"from": "app.py:1", "to": f"app.py:{i + 100}"} for i in range(total)]

    result = _diff_backend(_backend(nodes, []), _backend(nodes, edges))

    assert result["added_edge_count"] == total
    assert len(result["added_edges"]) == EDGE_DETAIL_CAP
    assert result["added_edges_truncated"] is True


def test_missing_edges_key_does_not_crash():
    """Snapshots predating edge storage must still diff."""
    result = _diff_backend({"nodes": []}, {"nodes": []})

    assert result["added_edge_count"] == 0
    assert result["removed_edge_count"] == 0
    assert result["unresolved_edges"] == {"before": 0, "after": 0, "delta": 0}


def test_legacy_node_fields_are_unchanged():
    """Consumers (commands/diff.py, dashboard, formatters, MCP) read these."""
    old = _backend([_node("app.py:10", "gone")], [])
    new = _backend([_node("app.py:20", "fresh", status="dead")], [])

    result = _diff_backend(old, new)

    for key in (
        "added_nodes", "removed_nodes", "changed_nodes",
        "added_count", "removed_count", "changed_count",
        "new_dead", "resolved_dead",
    ):
        assert key in result, f"legacy field {key} disappeared"

    assert result["added_count"] == 1
    assert result["removed_count"] == 1
    assert len(result["new_dead"]) == 1


# ─── summary wiring ──────────────────────────────────────

def test_summary_exposes_edge_counts():
    with tempfile.TemporaryDirectory() as workspace:
        nodes = [_node("app.py:10", "caller"), _node("app.py:50", "callee")]
        frontend = {"classes": [], "ids": []}

        save_snapshot(workspace, frontend, _backend(nodes, []))
        save_snapshot(
            workspace,
            frontend,
            _backend(nodes, [{"from": "app.py:10", "to": "app.py:50"}]),
        )

        result = diff_snapshots(workspace)

        assert result["summary"]["edges_added"] == 1
        assert result["summary"]["edges_removed"] == 0
