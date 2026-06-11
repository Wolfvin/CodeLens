"""Shared utilities for CodeLens."""

import os
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

# ─── Logging ─────────────────────────────────────────────────

def get_logger(name: str = "codelens") -> logging.Logger:
    """Get a configured logger for CodeLens."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '[%(name)s] %(levelname)s: %(message)s'
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.WARNING)  # Only warnings and above by default
    return logger

logger = get_logger()

# ─── Shared Configuration ───────────────────────────────────

DEFAULT_IGNORE_DIRS = frozenset({
    'node_modules', '.git', 'dist', 'build', 'target',
    '__pycache__', '.codelens', '.next', '.nuxt', '.cache',
    'vendor', '.venv', 'venv', 'env', '.idea', '.vscode',
    '_archive', 'coverage', '.pytest_cache', '.tox',
    'bin', 'obj', '.terraform', '.cargo', '.rustup',
    'storybook-static', '.storybook',
})

DEFAULT_IGNORE_EXTENSIONS = frozenset({
    '.min.js', '.min.css', '.map', '.bundle.js',
    '.chunk.js', '.d.ts',  # declaration files
})

# ─── Output File Generation ─────────────────────────────────

def write_output_files(workspace: str, scan_result) -> dict:
    """After a scan, generate outline.json and summary.json into .codelens/."""
    try:
        from outline_engine import get_workspace_outline
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)

        outline_data = get_workspace_outline(workspace)

        outline_path = os.path.join(codelens_dir, 'outline.json')
        with open(outline_path, 'w', encoding='utf-8') as f:
            json.dump(outline_data, f, indent=2, ensure_ascii=False)

        summary = compute_summary(workspace, outline_data, scan_result)

        summary_path = os.path.join(codelens_dir, 'summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return summary
    except Exception:
        logger.warning("Failed to write output files", exc_info=True)
        return {}


def compute_summary(workspace, outline_data, scan_result):
    """Compute an aggregate summary from outline + scan data."""
    total_functions = 0
    total_classes = 0
    total_interfaces = 0
    total_types = 0
    total_exports = 0
    total_components = 0
    total_imports = 0
    files_by_lang = {}

    for outline in outline_data.get('outlines', []):
        # Access the nested outline dict — get_file_outline returns
        # {"status": "ok", "file": ..., "outline": {functions, classes, ...}}
        inner = outline.get('outline', outline)
        lang = inner.get('language', outline.get('language', 'unknown'))
        files_by_lang[lang] = files_by_lang.get(lang, 0) + 1
        total_functions += len(inner.get('functions', []))
        total_classes += len(inner.get('classes', []))
        total_interfaces += len(inner.get('interfaces', []))
        total_types += len(inner.get('types', []))
        total_exports += len(inner.get('exports', []))
        total_components += len(inner.get('components', []))
        total_imports += len(inner.get('imports', []))
        for cls in inner.get('classes', []):
            total_functions += len(cls.get('methods', []))

    be_nodes = scan_result.get('backend', {}).get('nodes', 0)
    be_edges = scan_result.get('backend', {}).get('edges', 0)
    fe_classes = scan_result.get('frontend', {}).get('classes', 0)
    fe_ids = scan_result.get('frontend', {}).get('ids', 0)

    return {
        'workspace': workspace,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'files': outline_data.get('files_outlined', 0),
        'total_lines': outline_data.get('total_lines', 0),
        'functions': total_functions,
        'classes': total_classes,
        'interfaces': total_interfaces,
        'types': total_types,
        'exports': total_exports,
        'components': total_components,
        'imports': total_imports,
        'backend_nodes': be_nodes,
        'backend_edges': be_edges,
        'frontend_classes': fe_classes,
        'frontend_ids': fe_ids,
        'files_by_language': files_by_lang,
    }


# ─── Path and Caller Utilities ───────────────────────────────

_FILE_PATH_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.css', '.html', '.rs', '.vue', '.svelte'}


# ─── Performance Safeguards ────────────────────────────────

MAX_FILE_SIZE = 200 * 1024   # 200KB — skip files larger than this
MAX_FILES_DEFAULT = 5000      # Max source files to scan per engine
GLOBAL_TIMEOUT_SEC = 120      # Default global timeout per engine (seconds)


def should_ignore_dir(rel_root: str) -> bool:
    """Check if a relative directory path should be ignored.

    Uses path-segment-aware matching to avoid false positives
    (e.g., workspace named 'test-dist' shouldn't match 'dist').

    Args:
        rel_root: Relative path from workspace root (e.g., 'src/node_modules/pkg')

    Returns:
        True if the directory should be skipped.
    """
    if rel_root == '.':
        return False
    parts = rel_root.replace('\\', '/').split('/')
    return any(p in DEFAULT_IGNORE_DIRS for p in parts)


def safe_read_file(file_path: str, max_size: int = MAX_FILE_SIZE) -> Optional[str]:
    """Read a file safely with size limit and encoding handling.

    Args:
        file_path: Absolute path to the file.
        max_size: Maximum file size in bytes. Files larger than this are skipped.

    Returns:
        File content as string, or None if the file cannot be read or is too large.
    """
    try:
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            return None
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except (IOError, OSError):
        return None


def time_budget_expired(start_time: float, budget_sec: float = GLOBAL_TIMEOUT_SEC) -> bool:
    """Check if a time budget has expired.

    Useful for engines that walk many files and need a global timeout.

    Args:
        start_time: Start time from time.time().
        budget_sec: Budget in seconds.

    Returns:
        True if the budget has expired.
    """
    return (time.time() - start_time) > budget_sec


def is_file_path(name: str) -> bool:
    """Check if a name looks like a file path."""
    if '/' in name:
        return True
    for ext in _FILE_PATH_EXTENSIONS:
        if name.endswith(ext):
            return True
    return False


def deduplicate_callers(callers: List[Dict]) -> List[Dict]:
    """Deduplicate callers by (file, line) tuple."""
    seen = set()
    unique = []
    for c in callers:
        # Try dict format first (file, line keys)
        if "file" in c and "line" in c:
            key = (c.get("file", ""), c.get("line", 0))
        else:
            # Try 'from' ID format (file:line:fn)
            from_id = c.get("from", "")
            if ":" in from_id:
                parts = from_id.rsplit(":", 2)
                file_part = parts[0] if len(parts) >= 2 else from_id
                line_part = parts[1] if len(parts) >= 2 else "0"
                key = (file_part, line_part)
            else:
                key = (from_id, "0")
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


# ─── Binary Artifact Scanning ────────────────────────────────

def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts."""
    workspace = os.path.abspath(workspace)
    artifacts = []
    total_size = 0
    binary_extensions = {
        '.so', '.dll', '.dylib', '.o', '.obj', '.a', '.lib',
        '.exe', '.app', '.dmg', '.deb', '.rpm',
        '.wasm', '.pyc', '.pyo', '.class', '.jar',
        '.node', '.swiftmodule',
    }

    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in binary_extensions:
                fpath = os.path.join(root, f)
                try:
                    size = os.path.getsize(fpath)
                    total_size += size
                    rel = os.path.relpath(fpath, workspace)
                    artifacts.append({
                        "file": rel,
                        "type": ext[1:],  # Remove the dot
                        "size_bytes": size,
                        "size_human": _human_size(size),
                    })
                except OSError:
                    pass

    by_type = {}
    for a in artifacts:
        t = a["type"]
        by_type[t] = by_type.get(t, 0) + 1

    return {
        "status": "ok",
        "workspace": workspace,
        "total_artifacts": len(artifacts),
        "total_size_bytes": total_size,
        "total_size_human": _human_size(total_size),
        "by_type": by_type,
        "artifacts": artifacts[:200],  # Cap at 200
        "truncated": len(artifacts) > 200,
        "recommendations": [
            "Add binary file patterns to .gitignore to prevent committing build artifacts." if artifacts else "No binary artifacts found in the workspace.",
        ],
    }


def _human_size(size: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "5.7.1"
