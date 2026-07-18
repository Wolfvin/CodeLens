"""
Tests for flow-diff — a named flow's shape change (issue #313).

Composes flow membership (#309) with the edge diff (#297), filtered to
intra-flow edges (#311). diff_snapshots itself is covered by #297, so these
tests exercise the compose: the intra-flow filter and execute's branches,
with the two dependencies stubbed for control.
"""

import os
import sys

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from commands import flow_diff  # noqa: E402


# ─── pure helpers ────────────────────────────────────────

def test_fn_of_strips_owner():
    assert flow_diff._fn_of("Checkout.charge") == "charge"
    assert flow_diff._fn_of("charge") == "charge"
    assert flow_diff._fn_of("") == ""


def test_intra_flow_keeps_only_edges_between_members():
    members = {("a.py", "checkout"), ("a.py", "validate"), ("a.py", "charge")}
    edges = [
        {"from": "checkout", "from_file": "a.py", "to": "validate", "to_file": "a.py"},
        {"from": "validate", "from_file": "a.py", "to": "logger", "to_file": "b.py"},  # leaves flow
    ]
    kept = flow_diff._intra_flow(edges, members)
    assert kept == [{"from": "checkout", "to": "validate"}]


def test_intra_flow_matches_owner_qualified_label():
    members = {("a.py", "charge"), ("a.py", "send")}
    edges = [{"from": "Checkout.charge", "from_file": "a.py",
              "to": "Gateway.send", "to_file": "a.py"}]
    kept = flow_diff._intra_flow(edges, members)
    assert kept == [{"from": "Checkout.charge", "to": "Gateway.send"}]


# ─── execute (deps stubbed) ──────────────────────────────

class _Args:
    def __init__(self, name=None, snapshot1=None, snapshot2=None):
        self.name = name
        self.snapshot1 = snapshot1
        self.snapshot2 = snapshot2


def _stub(monkeypatch, flows, diff):
    monkeypatch.setattr(flow_diff, "audit_tags", lambda ws: {"status": "ok", "flows": flows})
    monkeypatch.setattr(flow_diff, "diff_snapshots", lambda ws, s1, s2: diff)


def test_missing_name_is_an_error():
    out = flow_diff.execute(_Args(name=None), "/ws")
    assert out["status"] == "error"
    assert out["error_type"] == "missing_argument"


def test_unknown_flow_lists_available(monkeypatch):
    _stub(monkeypatch, flows=[{"name": "AUTH", "members": []}], diff={})
    out = flow_diff.execute(_Args(name="PAYMENT"), "/ws")
    assert out["found"] is False
    assert "AUTH" in out["available_flows"]


def test_validation_bypass_is_detected(monkeypatch):
    flows = [{
        "name": "PAYMENT",
        "members": [
            {"symbol": "checkout", "file": "a.py", "line": 1},
            {"symbol": "validate", "file": "a.py", "line": 7},
            {"symbol": "charge", "file": "a.py", "line": 13},
        ],
    }]
    diff = {
        "snapshot_1": "S1", "snapshot_2": "S2",
        "backend": {
            "added_edges": [
                {"from": "checkout", "from_file": "a.py", "to": "charge", "to_file": "a.py"},
            ],
            "removed_edges": [
                {"from": "checkout", "from_file": "a.py", "to": "validate", "to_file": "a.py"},
            ],
        },
    }
    _stub(monkeypatch, flows, diff)

    out = flow_diff.execute(_Args(name="PAYMENT"), "/ws")

    assert out["changed"] is True
    assert out["added_edges"] == [{"from": "checkout", "to": "charge"}]
    assert out["removed_edges"] == [{"from": "checkout", "to": "validate"}]
    assert out["member_count"] == 3


def test_no_change_reports_unchanged(monkeypatch):
    flows = [{"name": "PAYMENT", "members": [{"symbol": "a", "file": "a.py", "line": 1}]}]
    diff = {"snapshot_1": "S1", "snapshot_2": "S2",
            "backend": {"added_edges": [], "removed_edges": []}}
    _stub(monkeypatch, flows, diff)

    out = flow_diff.execute(_Args(name="PAYMENT"), "/ws")
    assert out["changed"] is False
    assert out["added_edges"] == []


def test_edge_leaving_flow_is_ignored(monkeypatch):
    """A member calling a non-member is not an intra-flow shape change."""
    flows = [{"name": "F", "members": [{"symbol": "a", "file": "a.py", "line": 1}]}]
    diff = {"snapshot_1": "S1", "snapshot_2": "S2",
            "backend": {
                "added_edges": [
                    {"from": "a", "from_file": "a.py", "to": "ext", "to_file": "z.py"},
                ],
                "removed_edges": [],
            }}
    _stub(monkeypatch, flows, diff)

    out = flow_diff.execute(_Args(name="F"), "/ws")
    assert out["added_edges"] == []
    assert out["changed"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
