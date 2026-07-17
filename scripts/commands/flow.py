# @WHO:   scripts/commands/flow.py
# @WHAT:  `context --check flow` — collect a named flow's scattered functions
# @PART:  command (sub-check of `context`)
# @ENTRY: execute()
"""`context --check flow [--name X]` — the named-flow view.

Agents author `@FLOW: NAME` tags in the source; this reads them back and
collects every function carrying a given flow name into one view, so a chain
that is scattered across files reads as a single list. Pure read-only — it
never invents a tag, it only serves what an agent wrote (the tags are the
source of truth; CodeLens owns the graph and the query).

Without ``--name`` it lists every named flow and its size. The tag parsing
lives in ``tag_audit_engine``; this only reshapes it flow-first.
"""

import os
from typing import Any, Dict, List

from tag_audit_engine import audit_tags


def _flow_edges(members: List[Dict], workspace, db_path) -> List[Dict[str, str]]:
    """Call-edges among a flow's members, from the graph if it is populated.

    Graceful by design: a workspace that was never scanned (no graph DB) simply
    yields no edges and the flat member list stands. Reuses the read-only graph
    queries — nothing here touches the scan/parser pipeline.
    """
    try:
        from utils import default_db_path
        import graph_model as gm
    except Exception:
        return []

    path = db_path or default_db_path(workspace)
    if not path or not os.path.exists(path):
        return []

    # Resolve each member (symbol, file) to a node id. (symbol, file) rather
    # than symbol alone so two functions sharing a name don't collide.
    id_to_symbol: Dict[str, str] = {}
    for m in members:
        symbol, mfile = m.get("symbol"), m.get("file")
        if not symbol:
            continue
        for node in gm.find_nodes_by_name(symbol, path):
            if (node.get("file") or "").replace("\\", "/") == mfile:
                nid = node.get("node_id")
                if nid:
                    id_to_symbol[nid] = symbol
                break

    edges = []
    seen = set()
    for nid, from_sym in id_to_symbol.items():
        for callee in gm.query_callees(nid, path, max_depth=1):
            cid = callee.get("node_id")
            if cid in id_to_symbol:  # keep only edges that stay inside the flow
                pair = (from_sym, id_to_symbol[cid])
                if pair not in seen:
                    seen.add(pair)
                    edges.append({"from": pair[0], "to": pair[1]})
    return sorted(edges, key=lambda e: (e["from"], e["to"]))


def add_args(parser):
    """Register CLI arguments (workspace + name are carried by the umbrella)."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def execute(args, workspace) -> Dict[str, Any]:
    """Collect the named flow(s) for ``workspace``.

    @FLOW:    FLOW_VIEW
    @CALLS:   tag_audit_engine.audit_tags() -> dict
    @MUTATES: nothing (read-only)
    """
    audit = audit_tags(workspace)
    if audit.get("status") == "error":
        return audit

    flows = audit.get("flows", [])
    name = getattr(args, "name", None)

    if not name:
        # Inventory: every flow and its member count.
        return {
            "status": "ok",
            "workspace": workspace,
            "flows": [
                {"name": f["name"], "count": f["count"], "members": f["members"]}
                for f in flows
            ],
            "summary": {"distinct_flows": len(flows)},
        }

    # A single named flow: its scattered members, collected.
    match = next((f for f in flows if f["name"] == name), None)
    if match is None:
        available = [f["name"] for f in flows]
        return {
            "status": "ok",
            "workspace": workspace,
            "flow": name,
            "found": False,
            "members": [],
            "count": 0,
            "available_flows": available,
            "message": f"No @FLOW: {name} tag found. Known flows: "
                       + (", ".join(available) if available else "(none)"),
        }

    return {
        "status": "ok",
        "workspace": workspace,
        "flow": name,
        "found": True,
        "count": match["count"],
        "members": match["members"],
        # Intra-flow call-edges when the graph is populated; [] otherwise.
        "edges": _flow_edges(match["members"], workspace,
                             getattr(args, "db_path", None)),
    }
