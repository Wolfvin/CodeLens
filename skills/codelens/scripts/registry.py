"""
Registry Module for CodeLens — v2 Tree-sitter Edition
Reads and writes .codelens/frontend.json and .codelens/backend.json

Design principles:
- No unnecessary nesting — AI traverses flat structures easily
- All fields explicit, no implicit or hidden defaults
- `status` always present on every node — AI doesn't need to infer
- Empty arrays [] preferred over missing fields — schema consistency
- Supports TSX/Vue/Svelte/Tailwind metadata

v5.8: Added FrontendRegistryInput dataclass to replace 9-param function.
"""

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from utils import logger


# Valid CSS class/id name pattern: starts with letter, underscore, or hyphen,
# followed by word chars or hyphens.
_VALID_CSS_NAME_RE = re.compile(r'^[a-zA-Z_-][\w-]*$')


def _is_valid_css_class_name(name: str) -> bool:
    """Check if a name is a valid CSS class name.

    Rejects Vue template expressions and other non-CSS names that slip through
    parsing, such as '!!hint,', '!==', '!action.completed,', function calls,
    ternary operators, property access, etc.
    """
    if not name:
        return False
    # Quick pattern check
    if not _VALID_CSS_NAME_RE.match(name):
        return False
    # Broader rejection filters for patterns that pass the regex but are
    # clearly not CSS class names
    if len(name) > 80:
        return False
    if name.startswith('!'):
        return False
    if ' ' in name:
        return False
    # These characters indicate expressions, not class names
    for ch in ('(', ')', '?', '.', '>', '<', '=', '+', '*', '/'):
        if ch in name:
            return False
    return True


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
        "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
        "frameworks": [],
        "jsx_mode": False,
        "vue_mode": False,
        "svelte_mode": False,
        "tailwind_mode": False,
        "css_preprocessor": None
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                defaults.update(saved)
        except (json.JSONDecodeError, IOError):
            logger.debug("Failed to parse codelens config, using defaults", exc_info=True)
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
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.debug("Failed to parse frontend registry, returning empty", exc_info=True)
    return {
        "last_updated": "",
        "workspace": workspace,
        "classes": [],
        "ids": [],
        "tailwind": None,
        "frameworks": []
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
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.debug("Failed to parse backend registry, returning empty", exc_info=True)
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
    entry_type: str,
    html_refs: List[Dict],
    css_refs: List[Dict],
    js_refs: List[Dict]
) -> str:
    """
    Compute status for a frontend entry.

    Priority:
    1. collision (IDs only, same id in >1 HTML element)
    2. dead (ref_count == 0 in CSS and JS)
    3. duplicate_ref (referenced from 2+ different files)
    4. active (default, ref_count > 0)
    """
    ref_count = len(css_refs) + len(js_refs)

    # Collision: ID appears in >1 HTML element
    if entry_type == "id" and len(html_refs) > 1:
        return "collision"

    # Dead: no CSS or JS references
    if ref_count == 0:
        return "dead"

    # Duplicate ref: referenced from 2+ different JS/CSS files
    ref_paths = set()
    for ref in js_refs:
        ref_paths.add(ref.get("path", ""))
    for ref in css_refs:
        ref_paths.add(ref.get("path", ""))
    if len(ref_paths) >= 2:
        return "duplicate_ref"

    return "active"


@dataclass
class FrontendRegistryInput:
    """Groups all parsed data needed to build the frontend registry.

    Why a dataclass? The old build_frontend_registry() had 9 positional parameters,
    which is a code smell (many_params). Grouping them into a dataclass:
    - Makes call sites self-documenting
    - Reduces risk of passing arguments in the wrong order
    - Allows easy extension without breaking existing callers
    """
    workspace: str = ""
    html_data: List[Dict] = field(default_factory=list)
    css_data: List[Dict] = field(default_factory=list)
    js_data: List[Dict] = field(default_factory=list)
    tsx_data: List[Dict] = field(default_factory=list)
    vue_data: List[Dict] = field(default_factory=list)
    svelte_data: List[Dict] = field(default_factory=list)
    tailwind_info: Optional[Dict] = None
    frameworks: Optional[List[str]] = None


def build_frontend_registry_from_input(inp: FrontendRegistryInput) -> Dict[str, Any]:
    """Build the frontend registry from a FrontendRegistryInput dataclass.

    This is the canonical implementation. The legacy build_frontend_registry()
    function delegates here. New code should prefer using FrontendRegistryInput.
    """
    return _build_frontend_registry_impl(
        workspace=inp.workspace,
        html_data=inp.html_data,
        css_data=inp.css_data,
        js_data=inp.js_data,
        tsx_data=inp.tsx_data,
        vue_data=inp.vue_data,
        svelte_data=inp.svelte_data,
        tailwind_info=inp.tailwind_info,
        frameworks=inp.frameworks,
    )


def build_frontend_registry(
    workspace: str,
    html_data: List[Dict],
    css_data: List[Dict],
    js_data: List[Dict],
    tsx_data: List[Dict],
    vue_data: List[Dict],
    svelte_data: List[Dict],
    tailwind_info: Optional[Dict] = None,
    frameworks: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Build the complete frontend registry from all parsed data.
    Merges references per class/id name and computes status/flags.

    Accepts individual parameters for backward compatibility with scan commands.
    Internally delegates to build_frontend_registry_from_input().
    """
    inp = FrontendRegistryInput(
        workspace=workspace,
        html_data=html_data,
        css_data=css_data,
        js_data=js_data,
        tsx_data=tsx_data,
        vue_data=vue_data,
        svelte_data=svelte_data,
        tailwind_info=tailwind_info,
        frameworks=frameworks,
    )
    return build_frontend_registry_from_input(inp)


def _build_frontend_registry_impl(
    workspace: str,
    html_data: List[Dict],
    css_data: List[Dict],
    js_data: List[Dict],
    tsx_data: List[Dict],
    vue_data: List[Dict],
    svelte_data: List[Dict],
    tailwind_info: Optional[Dict],
    frameworks: Optional[List[str]]
) -> Dict[str, Any]:
    """Internal implementation of build_frontend_registry."""
    class_map: Dict[str, Dict] = {}
    id_map: Dict[str, Dict] = {}

    # Helper to add references
    def add_refs(entries: List[Dict], entry_type: str, ref_category: str):
        for entry in entries:
            name = entry["name"]

            # Validate CSS class names — skip Vue template expressions and
            # other non-CSS names that slip through parsing.
            if entry_type == "class" and not _is_valid_css_class_name(name):
                logger.debug(f"Skipping invalid CSS class name in frontend registry: {name!r}")
                continue

            target_map = class_map if entry_type == "class" else id_map
            if name not in target_map:
                target_map[name] = {"html": [], "css": [], "js": []}

            ref_entry = {
                "path": entry.get("path", ""),
                "line": entry.get("line", 0),
                "flag": entry.get("flag"),
            }
            # Include source metadata if present
            if "source" in entry:
                ref_entry["source"] = entry["source"]

            target_map[name][ref_category].append(ref_entry)

    # Process HTML data
    for item in html_data:
        add_refs(item.get("classes", []), "class", "html")   # HTML class= is a definition/usage
        add_refs(item.get("ids", []), "id", "html")

    # Process CSS data
    for item in css_data:
        add_refs(item.get("classes", []), "class", "css")
        add_refs(item.get("ids", []), "id", "css")

    # Process JS frontend data
    for item in js_data:
        add_refs(item.get("classes", []), "class", "js")
        add_refs(item.get("ids", []), "id", "js")

    # Process TSX data (has both frontend + backend)
    for item in tsx_data:
        frontend = item.get("frontend", {})
        add_refs(frontend.get("classes", []), "class", "js")
        add_refs(frontend.get("ids", []), "id", "js")

    # Process Vue data
    for item in vue_data:
        frontend = item.get("frontend", {})
        # Vue classes from template → html category (definition)
        for cls in frontend.get("classes", []):
            if cls.get("source", "").startswith("vue_class") or cls.get("source", "").startswith("vue_binding"):
                add_refs([cls], "class", "html")
            elif cls.get("source", "").startswith("vue_style") or cls.get("source", "").startswith("vue_scoped"):
                add_refs([cls], "class", "css")
            else:
                add_refs([cls], "class", "js")

        for id_entry in frontend.get("ids", []):
            if id_entry.get("source", "").startswith("vue_id"):
                add_refs([id_entry], "id", "html")
            elif id_entry.get("source", "").startswith("vue_style"):
                add_refs([id_entry], "id", "css")
            else:
                add_refs([id_entry], "id", "js")

    # Process Svelte data
    for item in svelte_data:
        frontend = item.get("frontend", {})
        for cls in frontend.get("classes", []):
            src = cls.get("source", "")
            if src.startswith("svelte_class") or src.startswith("svelte_directive"):
                add_refs([cls], "class", "html")
            elif src.startswith("svelte_style") or src.startswith("svelte_scoped"):
                add_refs([cls], "class", "css")
            else:
                add_refs([cls], "class", "js")

        for id_entry in frontend.get("ids", []):
            src = id_entry.get("source", "")
            if src.startswith("svelte_id"):
                add_refs([id_entry], "id", "html")
            elif src.startswith("svelte_style"):
                add_refs([id_entry], "id", "css")
            else:
                add_refs([id_entry], "id", "js")

    # Build final entries
    classes = _build_class_entries(class_map)
    ids = _build_id_entries(id_map)

    registry = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "classes": classes,
        "ids": ids,
        "frameworks": frameworks or []
    }

    if tailwind_info:
        registry["tailwind"] = tailwind_info

    return registry


def _build_class_entries(class_map: Dict) -> List[Dict]:
    """Build final class entries from the aggregated map."""
    classes = []
    for name, refs in sorted(class_map.items()):
        ref_count = len(refs["css"]) + len(refs["js"])  # HTML refs are definitions, not usage refs
        status = compute_frontend_status(name, "class", refs["html"], refs["css"], refs["js"])

        # Check duplicate_define across CSS
        css_paths = {}
        for css_ref in refs["css"]:
            p = css_ref.get("path", "")
            if p not in css_paths:
                css_paths[p] = []
            css_paths[p].append(css_ref)

        # Flag duplicate_define: same selector defined in same file 2+ times
        for path, path_refs in css_paths.items():
            if len(path_refs) > 1:
                for i, ref in enumerate(path_refs):
                    if i > 0:
                        ref["flag"] = "duplicate_define"

        entry = {
            "name": name,
            "ref_count": ref_count,
            "status": status,
            "html": refs["html"],
            "css": refs["css"],
            "js": refs["js"]
        }
        classes.append(entry)

    return classes


def _build_id_entries(id_map: Dict) -> List[Dict]:
    """Build final id entries from the aggregated map."""
    ids = []
    for name, refs in sorted(id_map.items()):
        ref_count = len(refs["css"]) + len(refs["js"])
        status = compute_frontend_status(name, "id", refs["html"], refs["css"], refs["js"])

        entry = {
            "name": name,
            "ref_count": ref_count,
            "status": status,
            "defined_in_html": refs["html"],
            "css": refs["css"],
            "js": refs["js"]
        }
        ids.append(entry)

    return ids
