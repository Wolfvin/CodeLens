"""
Registry Module for CodeLens
Reads and writes .codelens/frontend.json and .codelens/backend.json

Design principles:
- No unnecessary nesting — AI traverses flat structures easily
- All fields explicit, no implicit or hidden defaults
- `status` always present on every node — AI doesn't need to infer
- Empty arrays [] preferred over missing fields — schema consistency
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


def get_codelens_dir(workspace: str) -> str:
    """Get the .codelens directory path."""
    return os.path.join(workspace, '.codelens')


def ensure_codelens_dir(workspace: str) -> str:
    """Create .codelens directory if it doesn't exist."""
    codelens_dir = get_codelens_dir(workspace)
    os.makedirs(codelens_dir, exist_ok=True)
    return codelens_dir


def load_config(workspace: str) -> Dict[str, Any]:
    """Load codelens.config.json, or return defaults."""
    config_path = os.path.join(get_codelens_dir(workspace), 'codelens.config.json')
    defaults = {
        "frontend_paths": ["src/client/", "public/", "frontend/", "static/", "templates/"],
        "backend_paths": ["src/server/", "src/api/", "src/"],
        "watch": True,
        "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"]
    }
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            saved = json.load(f)
            defaults.update(saved)
    return defaults


def save_config(workspace: str, config: Dict[str, Any]) -> None:
    """Save codelens.config.json."""
    codelens_dir = ensure_codelens_dir(workspace)
    config_path = os.path.join(codelens_dir, 'codelens.config.json')
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def load_frontend_registry(workspace: str) -> Dict[str, Any]:
    """Load frontend.json registry."""
    path = os.path.join(get_codelens_dir(workspace), 'frontend.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_updated": "",
        "workspace": workspace,
        "classes": [],
        "ids": []
    }


def save_frontend_registry(workspace: str, data: Dict[str, Any]) -> None:
    """Save frontend.json registry."""
    codelens_dir = ensure_codelens_dir(workspace)
    path = os.path.join(codelens_dir, 'frontend.json')
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["workspace"] = workspace
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_backend_registry(workspace: str) -> Dict[str, Any]:
    """Load backend.json registry."""
    path = os.path.join(get_codelens_dir(workspace), 'backend.json')
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_updated": "",
        "workspace": workspace,
        "nodes": [],
        "edges": []
    }


def save_backend_registry(workspace: str, data: Dict[str, Any]) -> None:
    """Save backend.json registry."""
    codelens_dir = ensure_codelens_dir(workspace)
    path = os.path.join(codelens_dir, 'backend.json')
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    data["workspace"] = workspace
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def compute_frontend_status(
    name: str,
    entry_type: str,  # "class" or "id"
    html_refs: List[Dict],
    css_refs: List[Dict],
    js_refs: List[Dict]
) -> str:
    """
    Compute status for a frontend entry.

    Priority:
    - collision (IDs only, same id in >1 HTML element)
    - dead (ref_count == 0 in CSS and JS)
    - duplicate_ref (referenced from 2+ different JS files)
    - active (default, ref_count > 0)
    """
    ref_count = len(css_refs) + len(js_refs)

    # Check collision (ID only) — same ID appears in more than 1 HTML element
    if entry_type == "id":
        if len(html_refs) > 1:
            return "collision"

    # Check dead
    if ref_count == 0:
        return "dead"

    # Check duplicate_ref (referenced from 2+ different JS files)
    js_paths = set()
    for ref in js_refs:
        js_paths.add(ref.get("path", ""))
    if len(js_paths) >= 2:
        return "duplicate_ref"

    return "active"


def compute_backend_status(ref_count: int) -> str:
    """
    Compute status for a backend node.

    - dead: ref_count == 0
    - active: ref_count > 0
    """
    if ref_count == 0:
        return "dead"
    return "active"


def build_frontend_registry(
    workspace: str,
    html_data: List[Dict],   # list of {path, ids, classes} from HTML parser
    css_data: List[Dict],    # list of {path, classes, ids} from CSS parser
    js_data: List[Dict]      # list of {path, classes, ids} from JS frontend parser
) -> Dict[str, Any]:
    """
    Build the complete frontend registry from parsed data.

    Merges all references per class/id name and computes status/flags.
    """
    # Aggregate by name
    class_map: Dict[str, Dict] = {}  # name → {html: [], css: [], js: []}
    id_map: Dict[str, Dict] = {}

    # Process HTML data
    for item in html_data:
        path = item["path"]
        for cls in item.get("classes", []):
            name = cls["name"]
            if name not in class_map:
                class_map[name] = {"html": [], "css": [], "js": []}
            class_map[name]["html"].append({
                "path": path,
                "line": cls["line"],
                "flag": cls.get("flag")
            })
        for id_entry in item.get("ids", []):
            name = id_entry["name"]
            if name not in id_map:
                id_map[name] = {"html": [], "css": [], "js": []}
            id_map[name]["html"].append({
                "path": path,
                "line": id_entry["line"],
                "flag": id_entry.get("flag")
            })

    # Process CSS data
    for item in css_data:
        path = item["path"]
        for cls in item.get("classes", []):
            name = cls["name"]
            if name not in class_map:
                class_map[name] = {"html": [], "css": [], "js": []}
            class_map[name]["css"].append({
                "path": path,
                "line": cls["line"],
                "flag": cls.get("flag")
            })
        for id_entry in item.get("ids", []):
            name = id_entry["name"]
            if name not in id_map:
                id_map[name] = {"html": [], "css": [], "js": []}
            id_map[name]["css"].append({
                "path": path,
                "line": id_entry["line"],
                "flag": id_entry.get("flag")
            })

    # Process JS data
    for item in js_data:
        path = item["path"]
        for cls in item.get("classes", []):
            name = cls["name"]
            if name not in class_map:
                class_map[name] = {"html": [], "css": [], "js": []}
            class_map[name]["js"].append({
                "path": path,
                "line": cls["line"],
                "flag": cls.get("flag")
            })
        for id_entry in item.get("ids", []):
            name = id_entry["name"]
            if name not in id_map:
                id_map[name] = {"html": [], "css": [], "js": []}
            id_map[name]["js"].append({
                "path": path,
                "line": id_entry["line"],
                "flag": id_entry.get("flag")
            })

    # Build final class entries
    classes = []
    for name, refs in sorted(class_map.items()):
        ref_count = len(refs["css"]) + len(refs["js"])
        status = compute_frontend_status(name, "class", refs["html"], refs["css"], refs["js"])

        # Check for duplicate_define across CSS files
        css_define_paths = set()
        for css_ref in refs["css"]:
            css_define_paths.add(css_ref["path"])
        if len(css_define_paths) > 1:
            # Mark all but first CSS file as duplicate_define
            seen_first = False
            for css_ref in refs["css"]:
                if seen_first:
                    css_ref["flag"] = "duplicate_define"
                else:
                    seen_first = True

        entry = {
            "name": name,
            "ref_count": ref_count,
            "status": status,
            "css": refs["css"],
            "js": refs["js"]
        }
        classes.append(entry)

    # Build final id entries
    ids = []
    for name, refs in sorted(id_map.items()):
        ref_count = len(refs["css"]) + len(refs["js"])
        status = compute_frontend_status(name, "id", refs["html"], refs["css"], refs["js"])

        # Check for duplicate_define across CSS files
        css_define_paths = set()
        for css_ref in refs["css"]:
            css_define_paths.add(css_ref["path"])
        if len(css_define_paths) > 1:
            seen_first = False
            for css_ref in refs["css"]:
                if seen_first:
                    css_ref["flag"] = "duplicate_define"
                else:
                    seen_first = True

        entry = {
            "name": name,
            "ref_count": ref_count,
            "status": status,
            "defined_in_html": refs["html"],
            "css": refs["css"],
            "js": refs["js"]
        }
        ids.append(entry)

    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "classes": classes,
        "ids": ids
    }


def build_backend_registry(
    workspace: str,
    rust_data: List[Dict],  # list of {path, nodes, edges} from Rust parser
    js_data: List[Dict]     # list of {path, nodes, edges} from JS backend parser
) -> Dict[str, Any]:
    """
    Build the complete backend registry from parsed data.

    Resolves edge references by matching to_fn to declared function nodes.
    Computes ref_count from incoming edges.
    """
    all_nodes = []
    all_edges = []

    # Collect all nodes and edges
    fn_name_to_node_ids: Dict[str, List[str]] = {}  # fn_name → [node_ids]

    for item in rust_data:
        for node in item.get("nodes", []):
            all_nodes.append(node)
            fn_name = node["fn"]
            if fn_name not in fn_name_to_node_ids:
                fn_name_to_node_ids[fn_name] = []
            fn_name_to_node_ids[fn_name].append(node["id"])

        for edge in item.get("edges", []):
            all_edges.append(edge)

    for item in js_data:
        for node in item.get("nodes", []):
            all_nodes.append(node)
            fn_name = node["fn"]
            if fn_name not in fn_name_to_node_ids:
                fn_name_to_node_ids[fn_name] = []
            fn_name_to_node_ids[fn_name].append(node["id"])

        for edge in item.get("edges", []):
            all_edges.append(edge)

    # Resolve edges: match to_fn to actual node IDs
    resolved_edges = []
    for edge in all_edges:
        from_id = edge["from"]
        to_fn = edge["to_fn"]

        # Find the target node(s)
        if to_fn in fn_name_to_node_ids:
            for to_id in fn_name_to_node_ids[to_fn]:
                resolved_edge = {"from": from_id, "to": to_id}
                resolved_edges.append(resolved_edge)
        else:
            # External/unresolved call — keep as-is with to_fn
            resolved_edge = {"from": from_id, "to_fn": to_fn, "resolved": False}
            resolved_edges.append(resolved_edge)

    # Compute ref_count from incoming edges for each node
    incoming_count: Dict[str, int] = {}
    for node in all_nodes:
        incoming_count[node["id"]] = 0

    for edge in resolved_edges:
        to_id = edge.get("to")
        if to_id and to_id in incoming_count:
            incoming_count[to_id] += 1

    # Update nodes with ref_count and status
    for node in all_nodes:
        node["ref_count"] = incoming_count.get(node["id"], 0)
        node["status"] = compute_backend_status(node["ref_count"])

    # Check for duplicate_define (same fn name in different files)
    for fn_name, node_ids in fn_name_to_node_ids.items():
        if len(node_ids) > 1:
            # Flag all but the first as duplicate_define
            for i, nid in enumerate(node_ids):
                for node in all_nodes:
                    if node["id"] == nid and i > 0:
                        node["duplicate_define"] = True

    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "nodes": all_nodes,
        "edges": resolved_edges
    }
