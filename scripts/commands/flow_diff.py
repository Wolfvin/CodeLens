# @WHO:   scripts/commands/flow_diff.py
# @WHAT:  `impact --check flow-diff` — did a named flow's shape change
# @PART:  command (sub-check of `impact`)
# @ENTRY: execute()
"""`impact --check flow-diff --name X` — a named flow's shape change.

Composes three things already in the tree: flow membership from the agent's
`@FLOW: X` tags (#309), the call-graph edge diff between two snapshots (#297),
and the intra-flow filter of the subgraph (#311). The result answers a
reviewer's real question — *did the PAYMENT flow's shape change in this PR?* —
e.g. `checkout -> validate` removed and `checkout -> charge` added means
validation was bypassed.

Flow membership is read from the tags **as of now**; the edge changes are
between two graph snapshots. That pairing is exactly "compare the pre-PR
snapshot against the current tree". Pure read-only — no engine, no scan.
"""

from typing import Any, Dict, List, Set, Tuple

from tag_audit_engine import audit_tags
from diff_engine import diff_snapshots


def add_args(parser):
    """Register CLI arguments (workspace/name/snapshots carried by umbrella)."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def _fn_of(label: str) -> str:
    """The function part of an edge label (`Owner.fn` -> `fn`, `fn` -> `fn`)."""
    return label.rsplit(".", 1)[-1] if label else label


def _intra_flow(edges: List[Dict], members: Set[Tuple[str, str]]) -> List[Dict]:
    """Keep only edges whose both endpoints are flow members."""
    kept = []
    for e in edges:
        src = (e.get("from_file", ""), _fn_of(e.get("from", "")))
        dst = (e.get("to_file", ""), _fn_of(e.get("to", "")))
        if src in members and dst in members:
            kept.append({"from": e.get("from", ""), "to": e.get("to", "")})
    return kept


def execute(args, workspace) -> Dict[str, Any]:
    """Diff one named flow's call-graph shape between two snapshots.

    @FLOW:    FLOW_DIFF
    @CALLS:   tag_audit_engine.audit_tags(), diff_engine.diff_snapshots()
    @MUTATES: nothing (read-only)
    """
    name = getattr(args, "name", None)
    if not name:
        return {
            "status": "error",
            "error": "flow-diff needs --name X (the flow to compare)",
            "error_type": "missing_argument",
        }

    audit = audit_tags(workspace)
    if audit.get("status") == "error":
        return audit

    flows = {f["name"]: f for f in audit.get("flows", [])}
    match = flows.get(name)
    if match is None:
        available = sorted(flows)
        return {
            "status": "ok", "flow": name, "found": False,
            "available_flows": available,
            "message": f"No @FLOW: {name} tag found. Known flows: "
                       + (", ".join(available) if available else "(none)"),
        }

    members: Set[Tuple[str, str]] = {
        (m.get("file", ""), m.get("symbol", ""))
        for m in match.get("members", []) if m.get("symbol")
    }

    diff = diff_snapshots(
        workspace,
        getattr(args, "snapshot1", None),
        getattr(args, "snapshot2", None),
    )
    backend = diff.get("backend", {})
    added = _intra_flow(backend.get("added_edges", []), members)
    removed = _intra_flow(backend.get("removed_edges", []), members)

    return {
        "status": "ok",
        "workspace": workspace,
        "flow": name,
        "found": True,
        "snapshot_1": diff.get("snapshot_1"),
        "snapshot_2": diff.get("snapshot_2"),
        "member_count": len(members),
        "added_edges": added,
        "removed_edges": removed,
        "changed": bool(added or removed),
    }
