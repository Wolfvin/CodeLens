"""
Incremental Scan for CodeLens
Tracks file modification times to avoid re-scanning unchanged files.
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Set, Tuple


MTIME_CACHE_FILE = ".codelens/mtimes.json"


def load_mtimes(workspace: str) -> Dict[str, float]:
    """Load cached file modification times."""
    path = os.path.join(workspace, MTIME_CACHE_FILE)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
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
            pass
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
