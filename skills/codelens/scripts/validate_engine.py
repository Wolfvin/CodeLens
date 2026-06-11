"""
Validate Engine for CodeLens
Cross-validates the registry against actual files to find inconsistencies:
- Files in registry that no longer exist
- Source files not yet in registry
- Stale references (file exists but line content changed)
- Orphan registry entries
"""

import os
import json
import re
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone


def validate_registry(workspace: str) -> Dict[str, Any]:
    """
    Validate the CodeLens registry against the actual file system.

    Checks:
    1. Files referenced in registry that no longer exist on disk
    2. Source files that exist but aren't in the registry
    3. Stale references (line numbers that don't match actual content)
    4. Orphan entries (entries with no valid file references)

    Returns categorized issues with counts.
    """
    workspace = os.path.abspath(workspace)
    issues = {
        "missing_files": [],         # Files in registry but not on disk
        "unregistered_files": [],    # Source files not in registry
        "stale_references": [],      # Line numbers that don't match
        "orphan_entries": [],        # Entries with no valid file references
    }

    from registry import load_config, load_frontend_registry, load_backend_registry

    config = load_config(workspace)
    frontend = load_frontend_registry(workspace)
    backend = load_backend_registry(workspace)

    # ─── Collect all files referenced in registry ───────
    registry_files: Set[str] = set()

    # Frontend files
    for cls in frontend.get("classes", []):
        for ref in cls.get("css", []) + cls.get("js", []):
            registry_files.add(ref.get("path", ""))
    for id_entry in frontend.get("ids", []):
        for ref in id_entry.get("defined_in_html", []) + id_entry.get("css", []) + id_entry.get("js", []):
            registry_files.add(ref.get("path", ""))

    # Backend files
    for node in backend.get("nodes", []):
        if node.get("file"):
            registry_files.add(node["file"])

    # ─── Check 1: Missing files ────────────────────────
    for rel_path in registry_files:
        if not rel_path:
            continue
        abs_path = os.path.join(workspace, rel_path)
        if not os.path.exists(abs_path):
            # Find which entries reference this missing file
            referrers = _find_referrers(rel_path, frontend, backend)
            issues["missing_files"].append({
                "file": rel_path,
                "referrers": referrers,
                "message": f"File '{rel_path}' referenced in registry but no longer exists"
            })

    # ─── Check 2: Unregistered files ───────────────────
    # Only check source code extensions — config/data files are not expected in the registry
    source_extensions = {
        '.html', '.htm', '.css', '.scss', '.less', '.sass',
        '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
        '.rs', '.py', '.vue', '.svelte',
    }
    ignore_dirs = {"node_modules", ".git", "dist", "build", "target",
                   "__pycache__", ".codelens", ".next", ".cache", "vendor"}
    if config:
        for p in config.get("ignore", []):
            ignore_dirs.add(p.rstrip("/"))

    disk_files: Set[str] = set()
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in source_extensions:
                rel_path = os.path.relpath(os.path.join(root, filename), workspace)
                disk_files.add(rel_path)

    unregistered = disk_files - registry_files
    for rel_path in sorted(unregistered):
        # Skip empty __init__.py files — they have no symbols to register
        if rel_path.endswith('__init__.py'):
            abs_init = os.path.join(workspace, rel_path)
            try:
                with open(abs_init, 'r', encoding='utf-8', errors='ignore') as f:
                    init_content = f.read().strip()
                if not init_content or init_content == '':
                    continue  # Empty __init__.py — not an issue
            except IOError:
                pass
        issues["unregistered_files"].append({
            "file": rel_path,
            "ext": os.path.splitext(rel_path)[1],
            "message": f"File '{rel_path}' exists but is not in the registry (need to re-scan)"
        })

    # ─── Check 3: Stale references ─────────────────────
    # Sample check: verify that the first few line references actually contain
    # the expected symbol name
    stale_limit = 100  # Don't check everything for performance
    checked = 0

    for cls in frontend.get("classes", []):
        if checked >= stale_limit:
            break
        name = cls["name"]
        for ref in cls.get("css", []) + cls.get("js", []):
            if checked >= stale_limit:
                break
            checked += 1
            is_stale = _check_line_reference(workspace, ref.get("path", ""), ref.get("line", 0), name)
            if is_stale:
                issues["stale_references"].append({
                    "type": "class",
                    "name": name,
                    "file": ref.get("path", ""),
                    "line": ref.get("line", 0),
                    "message": f"Class '{name}' not found at line {ref.get('line', 0)} in {ref.get('path', '')} (content may have changed)"
                })

    checked = 0
    for node in backend.get("nodes", []):
        if checked >= stale_limit:
            break
        fn_name = node["fn"]
        if node.get("file") and node.get("line"):
            checked += 1
            is_stale = _check_line_reference(workspace, node["file"], node["line"], fn_name)
            if is_stale:
                issues["stale_references"].append({
                    "type": "function",
                    "name": fn_name,
                    "file": node["file"],
                    "line": node["line"],
                    "message": f"Function '{fn_name}' not found at line {node['line']} in {node['file']}"
                })

    # ─── Check 4: Orphan entries ───────────────────────
    # Frontend entries where ALL referenced files are missing
    for cls in frontend.get("classes", []):
        all_refs = cls.get("css", []) + cls.get("js", [])
        if all_refs and all(
            not os.path.exists(os.path.join(workspace, r.get("path", "__nonexistent__")))
            for r in all_refs
        ):
            issues["orphan_entries"].append({
                "type": "class",
                "name": cls["name"],
                "status": cls["status"],
                "message": f"Class '{cls['name']}' has no valid file references (all files deleted)"
            })

    for id_entry in frontend.get("ids", []):
        all_refs = (id_entry.get("defined_in_html", []) +
                    id_entry.get("css", []) +
                    id_entry.get("js", []))
        if all_refs and all(
            not os.path.exists(os.path.join(workspace, r.get("path", "__nonexistent__")))
            for r in all_refs
        ):
            issues["orphan_entries"].append({
                "type": "id",
                "name": id_entry["name"],
                "status": id_entry["status"],
                "message": f"ID '{id_entry['name']}' has no valid file references"
            })

    for node in backend.get("nodes", []):
        if node.get("file"):
            if not os.path.exists(os.path.join(workspace, node["file"])):
                issues["orphan_entries"].append({
                    "type": "function",
                    "name": node["fn"],
                    "file": node["file"],
                    "status": node.get("status", "active"),
                    "message": f"Function '{node['fn']}' references deleted file '{node['file']}'"
                })

    # ─── Summary ────────────────────────────────────────
    total_issues = sum(len(v) for v in issues.values())

    recommendation = "Registry is healthy."
    if total_issues > 0:
        if issues["missing_files"] or issues["orphan_entries"]:
            recommendation = "Re-scan recommended: files have been deleted since last scan."
        elif issues["unregistered_files"]:
            recommendation = "New files detected. Run a full scan to include them."
        elif issues["stale_references"]:
            recommendation = "Some line references are stale. Run an incremental scan to update."

    return {
        "status": "ok",
        "workspace": workspace,
        "total_issues": total_issues,
        "issues": issues,
        "summary": {
            "missing_files": len(issues["missing_files"]),
            "unregistered_files": len(issues["unregistered_files"]),
            "stale_references": len(issues["stale_references"]),
            "orphan_entries": len(issues["orphan_entries"])
        },
        "recommendation": recommendation,
        "registry_last_updated": frontend.get("last_updated", ""),
        "disk_files_count": len(disk_files),
        "registry_files_count": len(registry_files)
    }


# ─── Helpers ─────────────────────────────────────────────

def _find_referrers(file_path: str, frontend: Dict, backend: Dict) -> List[Dict]:
    """Find all registry entries that reference a given file."""
    referrers = []

    for cls in frontend.get("classes", []):
        for ref in cls.get("css", []) + cls.get("js", []):
            if ref.get("path") == file_path:
                referrers.append({"type": "class", "name": cls["name"]})
                break

    for id_entry in frontend.get("ids", []):
        for ref in id_entry.get("defined_in_html", []) + id_entry.get("css", []) + id_entry.get("js", []):
            if ref.get("path") == file_path:
                referrers.append({"type": "id", "name": id_entry["name"]})
                break

    for node in backend.get("nodes", []):
        if node.get("file") == file_path:
            referrers.append({"type": "function", "name": node["fn"]})
            break

    return referrers


def _check_line_reference(workspace: str, rel_path: str, line_num: int, symbol_name: str) -> bool:
    """
    Check if a symbol name appears at the given line in the file.
    Returns True if the reference is STALE (name NOT found at that line).
    """
    if not rel_path or line_num <= 0:
        return False

    abs_path = os.path.join(workspace, rel_path)
    if not os.path.exists(abs_path):
        return True  # File doesn't exist → definitely stale

    try:
        with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        if line_num > len(lines):
            return True  # Line doesn't exist

        # Check if symbol name appears in the line (or nearby ±2 lines for flexibility)
        check_range = range(max(0, line_num - 3), min(len(lines), line_num + 2))
        for i in check_range:
            if symbol_name in lines[i]:
                return False  # Found — not stale

        return True  # Not found in range → stale

    except IOError:
        return True  # Can't read → assume stale
