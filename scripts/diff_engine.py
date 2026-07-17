"""
Diff Engine for CodeLens
Compares two registry snapshots to show what changed between scans.
Stores snapshots automatically after each scan.
"""

import json
import os
import copy
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple
from utils import logger


SNAPSHOTS_DIR = ".codelens/snapshots"

# Cap on per-edge detail entries. Counts stay exact; a file rename can shift
# thousands of pairs at once, which would otherwise flood the output.
EDGE_DETAIL_CAP = 100


def save_snapshot(workspace: str, frontend: Dict, backend: Dict) -> str:
    """
    Save a timestamped snapshot of the current registry.

    Returns the snapshot ID (timestamp string).
    """
    workspace = os.path.abspath(workspace)
    snap_dir = os.path.join(workspace, SNAPSHOTS_DIR)
    os.makedirs(snap_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_file = os.path.join(snap_dir, f"{timestamp}.json")

    snapshot = {
        "timestamp": timestamp,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "frontend": copy.deepcopy(frontend),
        "backend": copy.deepcopy(backend)
    }

    with open(snap_file, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)

    # Clean up old snapshots (keep last 20)
    _cleanup_old_snapshots(snap_dir, keep=20)

    return timestamp


def list_snapshots(workspace: str) -> List[Dict[str, str]]:
    """List all available snapshots."""
    workspace = os.path.abspath(workspace)
    snap_dir = os.path.join(workspace, SNAPSHOTS_DIR)

    if not os.path.exists(snap_dir):
        return []

    snapshots = []
    for filename in sorted(os.listdir(snap_dir)):
        if filename.endswith('.json'):
            filepath = os.path.join(snap_dir, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                snapshots.append({
                    "id": data.get("timestamp", filename.replace('.json', '')),
                    "created_at": data.get("created_at", ""),
                    "file": filename
                })
            except (json.JSONDecodeError, IOError):
                logger.debug("Failed to parse snapshot file", exc_info=True)

    return snapshots


def diff_snapshots(
    workspace: str,
    snapshot_id_1: Optional[str] = None,
    snapshot_id_2: Optional[str] = None
) -> Dict[str, Any]:
    """
    Compare two registry snapshots.

    If snapshot_id_1 is None, uses the second-most-recent snapshot.
    If snapshot_id_2 is None, uses the most recent snapshot.
    If no snapshots exist, compares current registry against empty state.

    Returns additions, removals, and changes.
    """
    workspace = os.path.abspath(workspace)
    snap_dir = os.path.join(workspace, SNAPSHOTS_DIR)

    # Load snapshots
    snapshots = list_snapshots(workspace)

    if not snapshots:
        # No snapshots — compare current registry against empty
        from registry import load_frontend_registry, load_backend_registry
        current_frontend = load_frontend_registry(workspace)
        current_backend = load_backend_registry(workspace)

        snap1 = {"frontend": _empty_frontend(), "backend": _empty_backend()}
        snap2 = {"frontend": current_frontend, "backend": current_backend}
    else:
        # Determine which snapshots to compare
        if snapshot_id_2:
            snap2 = _load_snapshot(snap_dir, snapshot_id_2)
        else:
            snap2 = _load_snapshot(snap_dir, snapshots[-1]["id"])

        if snapshot_id_1:
            snap1 = _load_snapshot(snap_dir, snapshot_id_1)
        elif len(snapshots) >= 2:
            snap1 = _load_snapshot(snap_dir, snapshots[-2]["id"])
        else:
            snap1 = {"frontend": _empty_frontend(), "backend": _empty_backend()}

    # Compute diff
    frontend_diff = _diff_frontend(snap1["frontend"], snap2["frontend"])
    backend_diff = _diff_backend(snap1["backend"], snap2["backend"])

    # Build summary
    summary = {
        "added": frontend_diff["added_count"] + backend_diff["added_count"],
        "removed": frontend_diff["removed_count"] + backend_diff["removed_count"],
        "changed": frontend_diff["changed_count"] + backend_diff["changed_count"],
        "new_collisions": len(frontend_diff.get("new_collisions", [])),
        "new_dead": len(frontend_diff.get("new_dead", [])) + len(backend_diff.get("new_dead", [])),
        "resolved_dead": len(frontend_diff.get("resolved_dead", [])) + len(backend_diff.get("resolved_dead", [])),
        "edges_added": backend_diff.get("added_edge_count", 0),
        "edges_removed": backend_diff.get("removed_edge_count", 0)
    }

    return {
        "status": "ok",
        "workspace": workspace,
        "snapshot_1": snapshots[-2]["id"] if len(snapshots) >= 2 else "empty",
        "snapshot_2": snapshots[-1]["id"] if snapshots else "current",
        "summary": summary,
        "frontend": frontend_diff,
        "backend": backend_diff
    }


def diff_current_vs_last(workspace: str) -> Dict[str, Any]:
    """
    Compare the current registry against the last saved snapshot.
    This is the most common use case.
    """
    workspace = os.path.abspath(workspace)

    from registry import load_frontend_registry, load_backend_registry
    current_frontend = load_frontend_registry(workspace)
    current_backend = load_backend_registry(workspace)

    snapshots = list_snapshots(workspace)

    if not snapshots:
        snap1 = {"frontend": _empty_frontend(), "backend": _empty_backend()}
        snap1_id = "empty"
    else:
        snap1 = _load_snapshot(
            os.path.join(workspace, SNAPSHOTS_DIR),
            snapshots[-1]["id"]
        )
        snap1_id = snapshots[-1]["id"]

    frontend_diff = _diff_frontend(snap1["frontend"], current_frontend)
    backend_diff = _diff_backend(snap1["backend"], current_backend)

    summary = {
        "added": frontend_diff["added_count"] + backend_diff["added_count"],
        "removed": frontend_diff["removed_count"] + backend_diff["removed_count"],
        "changed": frontend_diff["changed_count"] + backend_diff["changed_count"],
        "new_collisions": len(frontend_diff.get("new_collisions", [])),
        "new_dead": len(frontend_diff.get("new_dead", [])) + len(backend_diff.get("new_dead", [])),
        "resolved_dead": len(frontend_diff.get("resolved_dead", [])) + len(backend_diff.get("resolved_dead", [])),
        "edges_added": backend_diff.get("added_edge_count", 0),
        "edges_removed": backend_diff.get("removed_edge_count", 0)
    }

    return {
        "status": "ok",
        "workspace": workspace,
        "last_snapshot": snap1_id,
        "summary": summary,
        "frontend": frontend_diff,
        "backend": backend_diff
    }


# ─── Internal Helpers ────────────────────────────────────

def _load_snapshot(snap_dir: str, snapshot_id: str) -> Dict:
    """Load a snapshot by ID."""
    filepath = os.path.join(snap_dir, f"{snapshot_id}.json")
    if not os.path.exists(filepath):
        return {"frontend": _empty_frontend(), "backend": _empty_backend()}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        logger.debug("Failed to load snapshot, returning empty registry", exc_info=True)
        return {"frontend": _empty_frontend(), "backend": _empty_backend()}


def _empty_frontend() -> Dict:
    return {"classes": [], "ids": []}


def _empty_backend() -> Dict:
    return {"nodes": [], "edges": []}


def _diff_frontend(old: Dict, new: Dict) -> Dict:
    """Diff two frontend registries."""
    old_classes = {c["name"]: c for c in old.get("classes", [])}
    new_classes = {c["name"]: c for c in new.get("classes", [])}
    old_ids = {i["name"]: i for i in old.get("ids", [])}
    new_ids = {i["name"]: i for i in new.get("ids", [])}

    added_classes = []
    removed_classes = []
    changed_classes = []
    new_collisions = []
    new_dead = []
    resolved_dead = []

    # Added/changed/removed classes
    for name in set(new_classes) - set(old_classes):
        cls = new_classes[name]
        added_classes.append({"name": name, "status": cls["status"]})
        if cls["status"] == "dead":
            new_dead.append({"type": "class", "name": name})
        if cls["status"] == "collision":
            new_collisions.append({"type": "class", "name": name})

    for name in set(old_classes) - set(new_classes):
        cls = old_classes[name]
        removed_classes.append({"name": name, "status": cls["status"]})
        if cls["status"] == "dead":
            resolved_dead.append({"type": "class", "name": name, "action": "removed"})

    for name in set(old_classes) & set(new_classes):
        old_cls = old_classes[name]
        new_cls = new_classes[name]
        changes = {}

        if old_cls["status"] != new_cls["status"]:
            changes["status"] = {"from": old_cls["status"], "to": new_cls["status"]}
            if new_cls["status"] == "collision":
                new_collisions.append({"type": "class", "name": name})
            if new_cls["status"] == "dead" and old_cls["status"] != "dead":
                new_dead.append({"type": "class", "name": name})
            if old_cls["status"] == "dead" and new_cls["status"] != "dead":
                resolved_dead.append({"type": "class", "name": name})

        if old_cls["ref_count"] != new_cls["ref_count"]:
            changes["ref_count"] = {"from": old_cls["ref_count"], "to": new_cls["ref_count"]}

        if changes:
            changed_classes.append({"name": name, **changes})

    # Added/changed/removed IDs
    added_ids = []
    removed_ids = []
    changed_ids = []

    for name in set(new_ids) - set(old_ids):
        id_entry = new_ids[name]
        added_ids.append({"name": name, "status": id_entry["status"]})
        if id_entry["status"] == "collision":
            new_collisions.append({"type": "id", "name": name})

    for name in set(old_ids) - set(new_ids):
        removed_ids.append({"name": name})

    for name in set(old_ids) & set(new_ids):
        old_id = old_ids[name]
        new_id = new_ids[name]
        changes = {}

        if old_id["status"] != new_id["status"]:
            changes["status"] = {"from": old_id["status"], "to": new_id["status"]}
            if new_id["status"] == "collision":
                new_collisions.append({"type": "id", "name": name})

        if old_id["ref_count"] != new_id["ref_count"]:
            changes["ref_count"] = {"from": old_id["ref_count"], "to": new_id["ref_count"]}

        if changes:
            changed_ids.append({"name": name, **changes})

    return {
        "added_classes": added_classes,
        "removed_classes": removed_classes,
        "changed_classes": changed_classes,
        "added_ids": added_ids,
        "removed_ids": removed_ids,
        "changed_ids": changed_ids,
        "added_count": len(added_classes) + len(added_ids),
        "removed_count": len(removed_classes) + len(removed_ids),
        "changed_count": len(changed_classes) + len(changed_ids),
        "new_collisions": new_collisions,
        "new_dead": new_dead,
        "resolved_dead": resolved_dead
    }


def _endpoint_key(node_id: str, node_map: Dict) -> Tuple[str, str, str]:
    """
    Line-independent identity for an edge endpoint: (file, owner, fn).

    Node ids embed a line number (`engine.py:167`), so keying edges by raw id
    reports every edge of a function that merely shifted lines as removed and
    re-added. Resolving through the node map to (file, impl_for, fn) drops that
    churn. `impl_for` (the owning class/struct) separates same-named methods
    that share a file. Ids that resolve to no node — module-level synthetic
    sources like `app.py:0:<module>` deliberately carry no node — fall back to
    the id itself, which is already line-independent.
    """
    node = node_map.get(node_id)
    if not node:
        return ("", "", node_id)
    # Normalise to strings: a missing owner must sort against a present one.
    return (
        node.get("file") or "",
        node.get("impl_for") or "",
        node.get("fn") or node_id
    )


def _split_edges(
    registry: Dict,
    node_map: Dict
) -> Tuple[Set[Tuple[Tuple, Tuple]], int]:
    """
    Split a backend registry's edges into resolved call pairs and an
    unresolved tally.

    Resolved edges carry `to` (a node id); unresolved ones carry only `to_fn`
    (a bare name, overwhelmingly stdlib/builtin like `append` or `strip`) and
    are counted rather than enumerated. Pairs form a set, not a multiset: the
    same caller/callee is recorded once per call site, and call-site count is
    not graph shape. `via_self` is a qualifier, so it stays out of identity.
    """
    resolved: Set[Tuple[Tuple, Tuple]] = set()
    unresolved = 0

    for edge in registry.get("edges", []):
        if "to" in edge:
            resolved.add((
                _endpoint_key(edge.get("from"), node_map),
                _endpoint_key(edge["to"], node_map)
            ))
        elif "to_fn" in edge:
            unresolved += 1

    return resolved, unresolved


def _endpoint_label(key: Tuple[str, str, str]) -> str:
    """Render an endpoint key as `Owner.fn`, or just `fn` when unowned."""
    _file, owner, fn = key
    return f"{owner}.{fn}" if owner else fn


def _format_edges(pairs: Set[Tuple[Tuple, Tuple]]) -> Tuple[List[Dict[str, str]], bool]:
    """Render edge pairs as capped, deterministically ordered detail entries."""
    ordered = sorted(pairs)
    detail = [
        {
            "from": _endpoint_label(src),
            "from_file": src[0],
            "to": _endpoint_label(dst),
            "to_file": dst[0]
        }
        for src, dst in ordered[:EDGE_DETAIL_CAP]
    ]
    return detail, len(ordered) > EDGE_DETAIL_CAP


def _diff_backend(old: Dict, new: Dict) -> Dict:
    """Diff two backend registries."""
    old_nodes = {n["id"]: n for n in old.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new.get("nodes", [])}

    added_nodes = []
    removed_nodes = []
    changed_nodes = []
    new_dead = []
    resolved_dead = []

    for nid in set(new_nodes) - set(old_nodes):
        node = new_nodes[nid]
        added_nodes.append({"name": node["fn"], "file": node.get("file", ""), "status": node.get("status", "active")})
        if node.get("status") == "dead":
            new_dead.append({"type": "function", "name": node["fn"], "file": node.get("file", "")})

    for nid in set(old_nodes) - set(new_nodes):
        node = old_nodes[nid]
        removed_nodes.append({"name": node["fn"], "file": node.get("file", "")})
        if node.get("status") == "dead":
            resolved_dead.append({"type": "function", "name": node["fn"], "action": "removed"})

    for nid in set(old_nodes) & set(new_nodes):
        old_n = old_nodes[nid]
        new_n = new_nodes[nid]
        changes = {}

        if old_n.get("status") != new_n.get("status"):
            changes["status"] = {"from": old_n.get("status"), "to": new_n.get("status")}
            if new_n.get("status") == "dead" and old_n.get("status") != "dead":
                new_dead.append({"type": "function", "name": new_n["fn"], "file": new_n.get("file", "")})
            if old_n.get("status") == "dead" and new_n.get("status") != "dead":
                resolved_dead.append({"type": "function", "name": new_n["fn"], "file": new_n.get("file", "")})

        if old_n.get("ref_count", 0) != new_n.get("ref_count", 0):
            changes["ref_count"] = {"from": old_n.get("ref_count", 0), "to": new_n.get("ref_count", 0)}

        if changes:
            changed_nodes.append({"name": new_n["fn"], "file": new_n.get("file", ""), **changes})

    old_edges, old_unresolved = _split_edges(old, old_nodes)
    new_edges, new_unresolved = _split_edges(new, new_nodes)

    added_edge_pairs = new_edges - old_edges
    removed_edge_pairs = old_edges - new_edges

    added_edges, added_truncated = _format_edges(added_edge_pairs)
    removed_edges, removed_truncated = _format_edges(removed_edge_pairs)

    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_count": len(added_nodes),
        "removed_count": len(removed_nodes),
        "changed_count": len(changed_nodes),
        "new_dead": new_dead,
        "resolved_dead": resolved_dead,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
        "added_edges_truncated": added_truncated,
        "removed_edges_truncated": removed_truncated,
        "added_edge_count": len(added_edge_pairs),
        "removed_edge_count": len(removed_edge_pairs),
        "unresolved_edges": {
            "from": old_unresolved,
            "to": new_unresolved,
            "delta": new_unresolved - old_unresolved
        }
    }


def _cleanup_old_snapshots(snap_dir: str, keep: int = 20):
    """Remove old snapshots, keeping only the most recent `keep`."""
    if not os.path.exists(snap_dir):
        return

    files = sorted(
        [f for f in os.listdir(snap_dir) if f.endswith('.json')],
        reverse=True
    )

    for old_file in files[keep:]:
        try:
            os.remove(os.path.join(snap_dir, old_file))
        except OSError:
            pass
