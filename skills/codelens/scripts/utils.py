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


def should_ignore_file(filename: str) -> bool:
    """Check if a file should be ignored based on extension patterns.

    Covers minified files, source maps, and type declarations.
    """
    lower = filename.lower()
    for ext in DEFAULT_IGNORE_EXTENSIONS:
        if lower.endswith(ext):
            return True
    # Also check .d.tsx
    if lower.endswith('.d.tsx'):
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

_FILE_PATH_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.css', '.html', '.rs', '.vue', '.svelte', '.php'}


def should_ignore_dir(rel_path: str) -> bool:
    """Check if a relative directory path should be ignored.

    Uses path-segment-aware matching so that a workspace named
    'test-dist' doesn't falsely match the 'dist' ignore rule.
    """
    if rel_path == '.':
        return False
    parts = rel_path.replace(os.sep, '/').split('/')
    for part in parts:
        if part in DEFAULT_IGNORE_DIRS:
            return True
    return False


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


# ─── File Reading Utility ──────────────────────────────────────

def safe_read_file(path: str, max_size: int = 200 * 1024, encoding: str = 'utf-8') -> Optional[str]:
    """Safely read a file with size limit and error handling.

    Args:
        path: Absolute or relative file path.
        max_size: Maximum file size in bytes to read (default 200KB).
        encoding: File encoding (default utf-8).

    Returns:
        File content as string, or None if the file cannot be read
        (missing, too large, encoding error, etc.).
    """
    try:
        file_size = os.path.getsize(path)
        if file_size > max_size:
            logger.debug(f"Skipping large file ({file_size} bytes): {path}")
            return None
        with open(path, 'r', encoding=encoding, errors='ignore') as f:
            return f.read()
    except (OSError, IOError):
        logger.debug(f"Failed to read file: {path}", exc_info=True)
        return None


# ─── Directory Ignore Utility ──────────────────────────────────

def should_ignore_dir(rel_path: str) -> bool:
    """Check if a relative path contains any segment from DEFAULT_IGNORE_DIRS.

    Uses path-segment-aware matching so that a workspace named
    "test-dist" does NOT match "dist".

    Args:
        rel_path: Relative path from workspace root (e.g., "src/components",
                  "node_modules/react", ".git/hooks").

    Returns:
        True if any path segment is in DEFAULT_IGNORE_DIRS.
    """
    if rel_path == '.':
        return False
    # Normalize to forward slashes and split into segments
    segments = rel_path.replace(os.sep, '/').split('/')
    return any(seg in DEFAULT_IGNORE_DIRS for seg in segments)


# ─── Source File Walking ────────────────────────────────────

# Common source extensions used by multiple engines
SOURCE_EXTENSIONS_ALL = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".php",
    ".html", ".css", ".scss", ".less",
}

# Generated / lock / vendored file patterns — should be skipped by engines
_GENERATED_PATTERNS = {
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb', 'bun.lock',
    'composer.lock', 'Gemfile.lock', 'Cargo.lock', 'pipfile.lock', 'poetry.lock',
    'go.sum', '.pnp.cjs', '.pnp.js',
}


def walk_source_files(
    workspace: str,
    extensions: Optional[set] = None,
    max_files: int = MAX_FILES_DEFAULT,
    ignore_dirs: Optional[frozenset] = None,
) -> List[tuple]:
    """Walk the workspace and yield source files matching the given extensions.

    This is a shared utility used by multiple engines (smell, handbook, context,
    ask) to avoid each engine reimplementing file discovery.

    Args:
        workspace: Absolute path to workspace root.
        extensions: Set of file extensions to include (e.g., {'.js', '.ts'}).
                    If None, uses SOURCE_EXTENSIONS_ALL.
        max_files: Maximum number of files to return (performance safeguard).
        ignore_dirs: Override for directories to ignore. Defaults to DEFAULT_IGNORE_DIRS.

    Returns:
        List of (rel_path, extension, content) tuples for each matching file.
    """
    workspace = os.path.abspath(workspace)
    if extensions is None:
        extensions = SOURCE_EXTENSIONS_ALL
    if ignore_dirs is None:
        ignore_dirs = DEFAULT_IGNORE_DIRS

    results: List[tuple] = []
    for root, dirs, filenames in os.walk(workspace):
        # Prune ignored directories
        rel_root = os.path.relpath(root, workspace)
        parts = rel_root.replace('\\', '/').split('/')
        if any(p in ignore_dirs for p in parts):
            dirs.clear()
            continue

        # Don't descend into .codelens
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in extensions:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip generated/lock files
            if is_generated_file(filename):
                continue

            content = safe_read_file(file_path)
            if content is not None:
                results.append((rel_path, ext, content))

            if len(results) >= max_files:
                return results

    return results


def is_generated_file(filename: str) -> bool:
    """Check if a file is a generated/lock/vendored file that should be skipped.

    Args:
        filename: Just the filename (not the full path), e.g. 'package-lock.json'.

    Returns:
        True if the file should be skipped during analysis.
    """
    fname_lower = filename.lower()

    # Exact match for known lock/generated files
    if fname_lower in _GENERATED_PATTERNS:
        return True

    # Minified files: *.min.js, *.min.css
    if '.min.' in fname_lower:
        return True

    # Source maps
    if fname_lower.endswith('.map'):
        return True

    # Declaration files
    if fname_lower.endswith('.d.ts'):
        return True

    # Bundle/chunk files
    if '.bundle.' in fname_lower or '.chunk.' in fname_lower:
        return True

    return False


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "5.7.1"
