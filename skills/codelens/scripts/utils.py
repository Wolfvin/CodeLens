"""Shared utilities for CodeLens."""

import os
import json
import logging
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


def should_ignore_dir(rel_path: str) -> bool:
    """Check if a relative path should be ignored during directory traversal.

    Uses path-segment-aware matching against DEFAULT_IGNORE_DIRS to avoid
    false positives from substring matches. For example, "target" matches
    "src/target/debug" but NOT "test-target/src" because "target" must
    appear as a complete path segment.

    This is the shared utility version used by framework_detect and other
    modules that walk the filesystem without a config-based ignore list.
    For config-based ignore matching, use should_ignore() in commands/scan.py.
    """
    # Normalize to forward slashes for consistent matching
    normalized = rel_path.replace('\\', '/')

    for ignore_dir in DEFAULT_IGNORE_DIRS:
        # Check if the ignore_dir appears as a complete path segment
        # Segment is preceded by '/' or is at the start of the path
        # "target" should match "/target/" or start with "target/"
        # but NOT "/test-target/" or "/my_target/"

        # Check 1: at the start of the path (e.g., "node_modules/pkg")
        if normalized.startswith(ignore_dir + '/'):
            return True

        # Check 2: as a full segment (preceded by '/')
        if '/' + ignore_dir + '/' in normalized:
            return True

        # Check 3: matches the entire last segment (e.g., path ends with "/.git")
        if normalized.endswith('/' + ignore_dir):
            return True

        # Check 4: exact match (path IS the ignore dir)
        if normalized == ignore_dir:
            return True

    return False

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
        lang = outline.get('language', 'unknown')
        files_by_lang[lang] = files_by_lang.get(lang, 0) + 1
        # Outline data may be nested under 'outline' key or at top level
        ol = outline.get('outline', outline)
        total_functions += len(ol.get('functions', []))
        total_classes += len(ol.get('classes', []))
        total_interfaces += len(ol.get('interfaces', []))
        total_types += len(ol.get('types', []))
        total_exports += len(ol.get('exports', []))
        total_components += len(ol.get('components', []))
        total_imports += len(ol.get('imports', []))
        for cls in ol.get('classes', []):
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


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "5.8.0"


# ─── Safe File Reading ──────────────────────────────────────

# Default maximum file size for engines that scan source files.
# Files larger than this are skipped to avoid slow regex/memory issues.
DEFAULT_MAX_FILE_SIZE = 200 * 1024  # 200KB


def safe_read_file(file_path: str, max_size: int = DEFAULT_MAX_FILE_SIZE) -> Optional[str]:
    """
    Safely read a file with size checking.

    Returns file content as string, or None if the file:
    - doesn't exist or can't be read
    - exceeds max_size
    - appears to be minified/bundled (few lines with very long average length)

    This function should be used by all engine scanners instead of raw open()/read().
    """
    try:
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            return None

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Detect minified/bundled files: very few lines with very long average length
        # These are not human-written code and should be skipped
        line_count = content.count('\n') + 1
        if line_count < 50 and len(content) > 0:
            avg_line_len = len(content) / line_count
            if avg_line_len > 500:
                return None

        # Skip files that are almost certainly auto-generated
        first_500 = content[:500].lower()
        minified_markers = ['/*!', 'minified', 'uglify', 'webpack/bootstrap', 'bundled']
        if any(marker in first_500 for marker in minified_markers):
            return None

        return content
    except (IOError, OSError):
        return None
