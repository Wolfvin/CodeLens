"""
Missing References Detector for CodeLens
Cross-validates frontend registry entries to find mismatches:
- HTML/JSX classes with no CSS definition
- CSS selectors with no HTML/JSX usage
- IDs referenced in JS but not defined in HTML
- Possible typos (similar names that differ by 1-2 chars)
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


def detect_missing_refs(workspace: str) -> Dict[str, Any]:
    """
    Detect all missing reference issues in the workspace.

    Returns categorized issues:
    - css_no_html: CSS class defined but never used in HTML/JSX
    - html_no_css: HTML/JSX class used but never defined in CSS
    - js_id_no_html: JS references an ID not defined in HTML
    - possible_typos: Similar names that might be typos
    - css_id_no_html: CSS styles an ID not defined in HTML
    """
    workspace = os.path.abspath(workspace)

    from registry import load_frontend_registry
    frontend = load_frontend_registry(workspace)

    issues = {
        "css_no_html": [],      # CSS class defined, no HTML usage
        "html_no_css": [],      # HTML class used, no CSS definition
        "css_id_no_html": [],   # CSS styles ID, no HTML definition
        "js_id_no_html": [],    # JS references ID, no HTML definition
        "possible_typos": [],   # Similar names (likely typos)
    }

    # Build lookup sets
    html_classes = set()
    css_classes = set()
    js_classes = set()
    html_ids = set()
    css_ids = set()
    js_ids = set()

    # Class analysis
    for cls in frontend.get("classes", []):
        name = cls["name"]

        has_css = len(cls.get("css", [])) > 0
        has_js = len(cls.get("js", [])) > 0

        # Track which "domain" references this class
        for css_ref in cls.get("css", []):
            css_classes.add(name)
        for js_ref in cls.get("js", []):
            js_classes.add(name)
            # Also track as HTML usage if source is jsx_classname or similar
            src = js_ref.get("source", "")
            if src in ("jsx_classname", "jsx_template", "vue_class", "vue_binding",
                       "svelte_class", "svelte_directive", "html_class"):
                html_classes.add(name)

        # CSS class with no HTML/JSX usage
        if has_css and not has_js and cls["status"] == "dead":
            css_locs = [f"{r['path']}:{r['line']}" for r in cls.get("css", [])]
            issues["css_no_html"].append({
                "name": name,
                "status": cls["status"],
                "css_locations": css_locs,
                "message": f"Class '.{name}' defined in CSS but never used in HTML/JS"
            })

        # HTML/JSX class with no CSS definition
        if has_js and not has_css:
            js_locs = [f"{r['path']}:{r['line']}" for r in cls.get("js", [])]
            sources = set(r.get("source", "") for r in cls.get("js", []))
            # Only flag if it looks like a CSS class (not Tailwind utility)
            is_tailwind = _is_likely_tailwind(name)
            if not is_tailwind:
                issues["html_no_css"].append({
                    "name": name,
                    "status": cls["status"],
                    "js_locations": js_locs,
                    "sources": list(sources),
                    "message": f"Class '{name}' used in HTML/JSX but has no CSS definition"
                })

    # ID analysis
    for id_entry in frontend.get("ids", []):
        name = id_entry["name"]

        has_html = len(id_entry.get("defined_in_html", [])) > 0
        has_css = len(id_entry.get("css", [])) > 0
        has_js = len(id_entry.get("js", [])) > 0

        if has_html:
            html_ids.add(name)
        if has_css:
            css_ids.add(name)
        if has_js:
            js_ids.add(name)

        # CSS styles an ID not defined in HTML
        if has_css and not has_html:
            css_locs = [f"{r['path']}:{r['line']}" for r in id_entry.get("css", [])]
            issues["css_id_no_html"].append({
                "name": name,
                "status": id_entry["status"],
                "css_locations": css_locs,
                "message": f"ID '#{name}' styled in CSS but not defined in HTML"
            })

        # JS references an ID not defined in HTML
        if has_js and not has_html:
            js_locs = [f"{r['path']}:{r['line']}" for r in id_entry.get("js", [])]
            issues["js_id_no_html"].append({
                "name": name,
                "status": id_entry["status"],
                "js_locations": js_locs,
                "message": f"ID '#{name}' referenced in JS but not defined in HTML"
            })

    # ─── Typo Detection ─────────────────────────────────
    all_class_names = set()
    for cls in frontend.get("classes", []):
        all_class_names.add(cls["name"])

    dead_classes = {cls["name"] for cls in frontend.get("classes", []) if cls["status"] == "dead"}
    active_classes = all_class_names - dead_classes

    # Check if a dead class is similar to an active class (likely typo)
    for dead_name in dead_classes:
        for active_name in active_classes:
            distance = _levenshtein_distance(dead_name, active_name)
            if 0 < distance <= 2 and len(dead_name) > 3 and len(active_name) > 3:
                # Also check prefix similarity
                if dead_name[:3] == active_name[:3] or dead_name[-3:] == active_name[-3:]:
                    dead_cls = next(c for c in frontend.get("classes", []) if c["name"] == dead_name)
                    active_cls = next(c for c in frontend.get("classes", []) if c["name"] == active_name)
                    issues["possible_typos"].append({
                        "dead_name": dead_name,
                        "active_name": active_name,
                        "distance": distance,
                        "dead_locations": [f"{r['path']}:{r['line']}" for r in dead_cls.get("css", []) + dead_cls.get("js", [])],
                        "active_locations": [f"{r['path']}:{r['line']}" for r in active_cls.get("css", []) + active_cls.get("js", [])],
                        "message": f"'{dead_name}' (dead) might be a typo of '{active_name}' (active)"
                    })

    # Total counts
    total_issues = sum(len(v) for v in issues.values())

    return {
        "status": "ok",
        "workspace": workspace,
        "total_issues": total_issues,
        "issues": issues,
        "summary": {
            "css_no_html": len(issues["css_no_html"]),
            "html_no_css": len(issues["html_no_css"]),
            "css_id_no_html": len(issues["css_id_no_html"]),
            "js_id_no_html": len(issues["js_id_no_html"]),
            "possible_typos": len(issues["possible_typos"])
        }
    }


def _is_likely_tailwind(class_name: str) -> bool:
    """Heuristic to detect Tailwind utility classes."""
    tailwind_prefixes = [
        'flex', 'grid', 'block', 'inline', 'hidden', 'visible',
        'w-', 'h-', 'p-', 'm-', 'mt-', 'mb-', 'ml-', 'mr-', 'mx-', 'my-',
        'pt-', 'pb-', 'pl-', 'pr-', 'px-', 'py-',
        'text-', 'bg-', 'border-', 'rounded-', 'shadow-',
        'gap-', 'space-', 'justify-', 'items-',
        'font-', 'tracking-', 'leading-',
        'opacity-', 'z-', 'overflow-',
        'hover:', 'focus:', 'active:', 'dark:', 'sm:', 'md:', 'lg:', 'xl:', '2xl:',
        'transition-', 'duration-', 'ease-',
        'scale-', 'rotate-', 'translate-',
        'ring-', 'outline-',
        'cursor-', 'select-', 'pointer-',
    ]

    for prefix in tailwind_prefixes:
        if class_name.startswith(prefix) or class_name == prefix.rstrip('-'):
            return True

    # Pure number patterns like "w4", "h8"
    if re.match(r'^[whmp][\d]+$', class_name):
        return True

    return False


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]
