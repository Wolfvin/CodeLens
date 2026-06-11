"""
Incremental Scan for CodeLens
Tracks file modification times to avoid re-scanning unchanged files.
Provides partial registry merge so unchanged file data is preserved.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple
from utils import logger


MTIME_CACHE_FILE = ".codelens/mtimes.json"


# ─── Path Helpers ────────────────────────────────────────────────

def _to_rel_paths(changed_files: Set[str], workspace: str) -> Set[str]:
    """Convert a set of absolute file paths to relative paths."""
    rel_paths = set()
    for f in changed_files:
        try:
            rel_paths.add(os.path.relpath(f, workspace))
        except ValueError:
            logger.debug("Path relativity conversion failed", exc_info=True)
    return rel_paths


def load_mtimes(workspace: str) -> Dict[str, float]:
    """Load cached file modification times."""
    path = os.path.join(workspace, MTIME_CACHE_FILE)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.debug("Failed to load mtimes cache", exc_info=True)
    return {}


def save_mtimes(workspace: str, mtimes: Dict[str, float]) -> None:
    """Save file modification times cache."""
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    path = os.path.join(codelens_dir, 'mtimes.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(mtimes, f, indent=2, ensure_ascii=False)


def get_current_mtimes(workspace: str, files: List[str]) -> Dict[str, float]:
    """Get current modification times for a list of files."""
    mtimes = {}
    for f in files:
        try:
            mtime = os.path.getmtime(f)
            # Use relative path as key for portability
            rel_path = os.path.relpath(f, workspace)
            mtimes[rel_path] = mtime
        except OSError:
            logger.debug("File mtime access failed", exc_info=True)
    return mtimes


def find_changed_files(
    workspace: str,
    all_files: List[str]
) -> Tuple[List[str], List[str], List[str]]:
    """
    Compare current mtimes with cached mtimes.
    Returns (changed_files, new_files, deleted_files).
    """
    cached = load_mtimes(workspace)
    current = get_current_mtimes(workspace, all_files)

    changed = []
    new = []
    deleted = []

    current_rel_paths = set(current.keys())
    cached_rel_paths = set(cached.keys())

    # Find new files
    for rel_path in current_rel_paths - cached_rel_paths:
        abs_path = os.path.join(workspace, rel_path)
        new.append(abs_path)

    # Find changed files
    for rel_path in current_rel_paths & cached_rel_paths:
        if current[rel_path] != cached[rel_path]:
            abs_path = os.path.join(workspace, rel_path)
            changed.append(abs_path)

    # Find deleted files
    for rel_path in cached_rel_paths - current_rel_paths:
        deleted.append(rel_path)  # Return relative path for deletion

    return changed, new, deleted


def update_mtimes_cache(workspace: str, all_files: List[str]) -> None:
    """Update the mtimes cache after a scan."""
    current = get_current_mtimes(workspace, all_files)
    save_mtimes(workspace, current)


def remove_from_mtimes_cache(workspace: str, deleted_rel_paths: List[str]) -> None:
    """Remove deleted files from the mtimes cache."""
    cached = load_mtimes(workspace)
    for rel_path in deleted_rel_paths:
        cached.pop(rel_path, None)
    save_mtimes(workspace, cached)


# ─── Partial Registry Merge ─────────────────────────────────────

def _strip_refs_from_changed(refs: List[Dict], changed_rel_paths: Set[str]) -> List[Dict]:
    """Filter out refs whose 'path' field is in changed_rel_paths."""
    return [r for r in refs if r.get("path", "") not in changed_rel_paths]


def _recompute_class_status(entry: Dict) -> None:
    """Recompute ref_count and status for a class entry in-place."""
    from registry import compute_frontend_status
    html_refs = entry.get("defined_in_html", [])
    css_refs = entry.get("css", [])
    js_refs = entry.get("js", [])
    entry["ref_count"] = len(css_refs) + len(js_refs)
    entry["status"] = compute_frontend_status(
        entry["name"], "class", html_refs, css_refs, js_refs
    )


def _recompute_id_status(entry: Dict) -> None:
    """Recompute ref_count and status for an id entry in-place."""
    from registry import compute_frontend_status
    html_refs = entry.get("defined_in_html", [])
    css_refs = entry.get("css", [])
    js_refs = entry.get("js", [])
    entry["ref_count"] = len(css_refs) + len(js_refs)
    entry["status"] = compute_frontend_status(
        entry["name"], "id", html_refs, css_refs, js_refs
    )


def _recompute_duplicate_define(entry: Dict) -> None:
    """Recompute duplicate_define flags on css refs for a class entry."""
    # Clear existing flags first - work on copies to avoid mutation
    new_css = []
    for ref in entry.get("css", []):
        ref_copy = dict(ref)
        ref_copy.pop("flag", None)
        new_css.append(ref_copy)
    
    # Group by path
    css_paths: Dict[str, List[Dict]] = {}
    for ref in new_css:
        p = ref.get("path", "")
        if p not in css_paths:
            css_paths[p] = []
        css_paths[p].append(ref)
    
    # Mark duplicates
    for path, path_refs in css_paths.items():
        if len(path_refs) > 1:
            for i, ref in enumerate(path_refs):
                if i > 0:
                    ref["flag"] = "duplicate_define"
    
    entry["css"] = new_css


def merge_frontend_data(
    existing_registry: Dict[str, Any],
    html_data: List[Dict],
    css_data: List[Dict],
    js_frontend_data: List[Dict],
    tsx_data: List[Dict],
    vue_data: List[Dict],
    svelte_data: List[Dict],
    tailwind_info: Optional[Dict],
    changed_files: Set[str],
    workspace: str,
    frameworks: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Merge new parsed frontend data into an existing frontend registry.

    Strategy:
    1. Strip refs that came from changed files out of existing entries
    2. Remove entries that become completely empty
    3. Build a partial registry from the new (changed-file-only) parsed data
    4. Merge the partial registry entries into the stripped existing entries
    5. Return the merged registry

    This preserves data from unchanged files and only updates entries
    affected by changed files.
    """
    from registry import build_frontend_registry

    changed_rel_paths = _to_rel_paths(changed_files, workspace)

    # ── Step 1: Strip refs from changed files out of existing entries ──

    stripped_classes: List[Dict] = []
    for entry in existing_registry.get("classes", []):
        entry["defined_in_html"] = _strip_refs_from_changed(entry.get("defined_in_html", []), changed_rel_paths)
        entry["css"] = _strip_refs_from_changed(entry.get("css", []), changed_rel_paths)
        entry["js"] = _strip_refs_from_changed(entry.get("js", []), changed_rel_paths)
        _recompute_class_status(entry)
        # Keep entry if it still has any refs (including from HTML side)
        if entry["ref_count"] > 0 or len(entry.get("defined_in_html", [])) > 0:
            stripped_classes.append(entry)

    stripped_ids: List[Dict] = []
    for entry in existing_registry.get("ids", []):
        entry["defined_in_html"] = _strip_refs_from_changed(
            entry.get("defined_in_html", []), changed_rel_paths
        )
        entry["css"] = _strip_refs_from_changed(entry.get("css", []), changed_rel_paths)
        entry["js"] = _strip_refs_from_changed(entry.get("js", []), changed_rel_paths)
        _recompute_id_status(entry)
        # Keep entry if it still has any refs at all
        if entry["ref_count"] > 0 or len(entry.get("defined_in_html", [])) > 0:
            stripped_ids.append(entry)

    # ── Step 2: Build partial registry from new parsed data ──

    partial_registry = build_frontend_registry(
        workspace, html_data, css_data, js_frontend_data,
        tsx_data, vue_data, svelte_data,
        tailwind_info, frameworks or []
    )

    # ── Step 3: Merge partial into stripped existing ──

    existing_class_map = {e["name"]: e for e in stripped_classes}
    existing_id_map = {e["name"]: e for e in stripped_ids}

    for new_entry in partial_registry.get("classes", []):
        name = new_entry["name"]
        if name in existing_class_map:
            existing = existing_class_map[name]
            existing["defined_in_html"].extend(new_entry.get("defined_in_html", []))
            existing["css"].extend(new_entry.get("css", []))
            existing["js"].extend(new_entry.get("js", []))
            _recompute_class_status(existing)
            _recompute_duplicate_define(existing)
        else:
            existing_class_map[name] = new_entry
            stripped_classes.append(new_entry)

    for new_entry in partial_registry.get("ids", []):
        name = new_entry["name"]
        if name in existing_id_map:
            existing = existing_id_map[name]
            existing["defined_in_html"].extend(new_entry.get("defined_in_html", []))
            existing["css"].extend(new_entry.get("css", []))
            existing["js"].extend(new_entry.get("js", []))
            _recompute_id_status(existing)
        else:
            existing_id_map[name] = new_entry
            stripped_ids.append(new_entry)

    # ── Step 4: Build final merged registry ──

    merged: Dict[str, Any] = {
        "classes": sorted(stripped_classes, key=lambda x: x["name"]),
        "ids": sorted(stripped_ids, key=lambda x: x["name"]),
        "frameworks": frameworks if frameworks is not None else existing_registry.get("frameworks", [])
    }

    # Preserve or update tailwind info
    if tailwind_info:
        merged["tailwind"] = tailwind_info
    elif "tailwind" in existing_registry:
        merged["tailwind"] = existing_registry["tailwind"]

    return merged


def merge_backend_data(
    existing_registry: Dict[str, Any],
    new_parsed_data: List[Dict],
    changed_files: Set[str],
    workspace: str
) -> Dict[str, Any]:
    """
    Merge new backend parsed data into an existing backend registry.

    Strategy:
    1. Remove nodes whose 'file' field is in changed_files
    2. Remove edges that reference removed nodes
    3. Try to re-resolve edges from unchanged files → changed files (best-effort)
    4. Add new nodes from changed files
    5. Resolve new raw edges against all nodes (kept + new)
    6. Combine all edges and recompute node statistics
    7. Return the merged registry

    This preserves nodes/edges from unchanged files and only updates
    entries affected by changed files.
    """
    from edge_resolver import resolve_edges

    changed_rel_paths = _to_rel_paths(changed_files, workspace)

    existing_nodes = existing_registry.get("nodes", [])
    existing_edges = existing_registry.get("edges", [])

    # ── Step 1: Identify removed nodes (from changed files) ──

    removed_node_ids: Set[str] = set()
    # Map removed node ID → fn name (for re-resolution)
    removed_node_fn: Dict[str, str] = {}

    for node in existing_nodes:
        if node.get("file", "") in changed_rel_paths:
            removed_node_ids.add(node["id"])
            removed_node_fn[node["id"]] = node.get("fn", "")

    # ── Step 2: Keep nodes from unchanged files ──

    kept_nodes: List[Dict] = []
    for node in existing_nodes:
        if node.get("file", "") not in changed_rel_paths:
            kept_nodes.append(node)

    # ── Step 3: Process existing edges ──

    kept_edges: List[Dict] = []
    re_resolvable_edges: List[Dict] = []  # from unchanged → changed (to be re-resolved)

    for edge in existing_edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        to_fn = edge.get("to_fn", "")
        is_resolved = edge.get("resolved", True) is not False

        # Determine if the from-side is from a changed file
        from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
        from_is_changed = from_file in changed_rel_paths

        if from_is_changed:
            # Edge originates from a changed file — discard it;
            # new raw edges will regenerate these
            continue

        if to_id in removed_node_ids:
            # Edge points to a removed node — try to re-resolve later
            re_resolvable_edges.append(edge)
            continue

        # Edge is between unchanged-file nodes — keep it
        kept_edges.append(edge)

    # ── Step 4: Extract new nodes and raw edges from parsed data ──

    new_nodes: List[Dict] = []
    new_raw_edges: List[Dict] = []
    for item in new_parsed_data:
        new_nodes.extend(item.get("nodes", []))
        new_raw_edges.extend(item.get("edges", []))

    # ── Step 5: Combine kept nodes + new nodes ──

    all_nodes = kept_nodes + new_nodes

    # ── Step 6: Resolve new raw edges against all nodes ──

    _, newly_resolved_edges = resolve_edges(all_nodes, new_raw_edges)
    # Note: resolve_edges modifies all_nodes in place (ref_count, status, duplicate_define)
    # but only counts refs from new_raw_edges. We recompute below.

    # ── Step 7: Re-resolve cross-file edges (unchanged → changed) ──

    # Build fn name → new node lookup for re-resolution
    fn_name_to_new_nodes: Dict[str, List[Dict]] = {}
    for node in new_nodes:
        fn_name = node.get("fn", "")
        if fn_name:
            if fn_name not in fn_name_to_new_nodes:
                fn_name_to_new_nodes[fn_name] = []
            fn_name_to_new_nodes[fn_name].append(node)

    re_resolved_edges: List[Dict] = []
    for edge in re_resolvable_edges:
        from_id = edge.get("from", "")
        old_to_id = edge.get("to", "")

        # Try to find the new node for the old target
        old_fn = removed_node_fn.get(old_to_id, "")

        if old_fn and old_fn in fn_name_to_new_nodes:
            candidates = fn_name_to_new_nodes[old_fn]
            # Prefer same file, then first candidate
            from_file = from_id.rsplit(':', 1)[0] if ':' in from_id else ""
            same_file = [c for c in candidates if c.get("file", "") == from_file]
            target = same_file[0] if same_file else candidates[0]
            re_resolved_edges.append({
                "from": from_id,
                "to": target["id"]
            })
        # If we can't re-resolve, the edge is lost (acceptable for incremental)

    # ── Step 8: Combine all edges ──

    all_edges = kept_edges + newly_resolved_edges + re_resolved_edges

    # ── Step 9: Recompute ref_count and status for ALL nodes ──

    incoming_count: Dict[str, int] = {node["id"]: 0 for node in all_nodes}
    for edge in all_edges:
        to_id = edge.get("to")
        if to_id and to_id in incoming_count:
            incoming_count[to_id] += 1

    for node in all_nodes:
        node["ref_count"] = incoming_count.get(node["id"], 0)
        node["status"] = "dead" if node["ref_count"] == 0 else "active"

    # ── Step 10: Recompute duplicate_define for ALL nodes ──

    fn_name_to_all_nodes: Dict[str, List[Dict]] = {}
    for node in all_nodes:
        fn_name = node.get("fn", "")
        if fn_name not in fn_name_to_all_nodes:
            fn_name_to_all_nodes[fn_name] = []
        fn_name_to_all_nodes[fn_name].append(node)

    for fn_name, nodes in fn_name_to_all_nodes.items():
        if len(nodes) > 1:
            for i, node in enumerate(nodes):
                if i > 0:
                    node["duplicate_define"] = True
                else:
                    node.pop("duplicate_define", None)
        else:
            nodes[0].pop("duplicate_define", None)

    # ── Step 11: Build merged registry ──

    merged: Dict[str, Any] = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "nodes": all_nodes,
        "edges": all_edges
    }

    return merged
