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

from typing import Any, Dict

from tag_audit_engine import audit_tags


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
    }
