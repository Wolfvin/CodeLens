"""Shared utilities for CodeLens."""

import os
import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set, Tuple

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


# ─── File I/O Utilities ────────────────────────────────────────

def safe_read_file(filepath: str, max_size: int = 500 * 1024, encoding: str = 'utf-8') -> Optional[str]:
    """Safely read a file with size limit and error handling.

    Args:
        filepath: Path to the file to read.
        max_size: Maximum file size in bytes to read (default 500KB).
        encoding: File encoding (default utf-8).

    Returns:
        File contents as string, or None if the file cannot be read
        (too large, missing, encoding error, etc.).
    """
    try:
        if not os.path.isfile(filepath):
            return None
        file_size = os.path.getsize(filepath)
        if file_size > max_size:
            logger.debug(f"Skipping large file ({file_size} bytes): {filepath}")
            return None
        with open(filepath, 'r', encoding=encoding, errors='ignore') as f:
            return f.read()
    except (IOError, OSError, PermissionError):
        logger.debug(f"Cannot read file: {filepath}")
        return None


def should_ignore_dir(rel_path: str) -> bool:
    """Check if a directory path should be ignored during scanning.

    Uses path-segment-aware matching to avoid false positives
    (e.g., a workspace named "test-dist" should not match "dist").

    Args:
        rel_path: Relative path from workspace root (use '.' for workspace root).

    Returns:
        True if the path should be ignored.
    """
    if rel_path == '.':
        return False
    # Normalize path separators
    parts = rel_path.replace('\\', '/').split('/')
    for part in parts:
        if part in DEFAULT_IGNORE_DIRS:
            return True
    return False


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

CODELENS_VERSION = "5.10.0"


# ─── Performance Constants ──────────────────────────────────

# Maximum file size to read (500KB) — used by env_check and other engines
MAX_FILE_SIZE = 500 * 1024

# Default max files to scan per run — used by env_check and debug_leak
MAX_FILES_DEFAULT = 3000


def time_budget_expired(start_time: float, budget_sec: float = 90.0) -> bool:
    """Check if the time budget has expired.

    Used by engines that need to limit execution time on large codebases.

    Args:
        start_time: The start time from time.time().
        budget_sec: Maximum allowed seconds (default 90s).

    Returns:
        True if the budget has expired.
    """
    return (time.time() - start_time) > budget_sec


def is_generated_file(filename: str) -> bool:
    """Check if a file is auto-generated and should be skipped in analysis.

    Generated files include lock files, minified files, compiled outputs,
    and vendor directories. Analyzing these produces false positives and
    wastes time.

    Args:
        filename: Just the filename (not full path), e.g. "package-lock.json".

    Returns:
        True if the file is auto-generated.
    """
    generated_patterns = {
        # Lock files
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'Cargo.lock', 'Gemfile.lock', 'composer.lock', 'poetry.lock',
        'pdm.lock', 'uv.lock',
        # Generated/minified
        '.min.js', '.min.css', '.bundle.js', '.chunk.js',
        # Build outputs
        '.d.ts',  # TypeScript declaration files
    }
    for pattern in generated_patterns:
        if filename.endswith(pattern) or filename == pattern:
            return True
    return False


def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts.

    Detects:
    - Compiled binaries (.exe, .dll, .so, .dylib, .wasm)
    - Electron apps (dist/electron-* directories)
    - Build output directories
    - Large asset files

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with detected artifacts categorized by type.
    """
    workspace = os.path.abspath(workspace)
    binaries = []
    electron_apps = []
    build_outputs = []
    large_assets = []
    LARGE_ASSET_THRESHOLD = 5 * 1024 * 1024  # 5MB

    binary_extensions = {
        '.exe', '.dll', '.so', '.dylib', '.wasm', '.o', '.obj',
        '.pyc', '.pyo', '.class', '.jar', '.war',
    }

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [
            d for d in dirs
            if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')
        ]
        if '.codelens' in root:
            dirs.clear()
            continue

        rel_root = os.path.relpath(root, workspace)

        # Detect Electron app directories
        if 'dist' in rel_root.split(os.sep) and 'electron' in rel_root.lower():
            electron_apps.append(rel_root)

        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            file_path = os.path.join(root, fn)
            rel_path = os.path.relpath(file_path, workspace)

            # Binary files
            if ext in binary_extensions:
                try:
                    size = os.path.getsize(file_path)
                    binaries.append({
                        "path": rel_path,
                        "size_bytes": size,
                        "type": ext,
                    })
                except OSError:
                    pass

            # Large asset files
            try:
                size = os.path.getsize(file_path)
                if size > LARGE_ASSET_THRESHOLD and ext not in binary_extensions:
                    large_assets.append({
                        "path": rel_path,
                        "size_bytes": size,
                        "type": ext,
                    })
            except OSError:
                pass

    return {
        "status": "ok",
        "workspace": workspace,
        "binaries": binaries[:50],
        "electron_apps": electron_apps[:10],
        "build_outputs": build_outputs[:20],
        "large_assets": large_assets[:30],
        "stats": {
            "total_binaries": len(binaries),
            "total_electron_apps": len(electron_apps),
            "total_large_assets": len(large_assets),
        }
    }


def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Scan workspace for Tauri-specific artifacts.

    Detects:
    - src-tauri/ directory structure
    - tauri.conf.json configuration
    - Cargo.toml with tauri dependency
    - Tauri capabilities/permissions
    - Sidecar binaries
    - Updater configuration

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with Tauri analysis, or None if not a Tauri project.
    """
    workspace = os.path.abspath(workspace)
    src_tauri = os.path.join(workspace, "src-tauri")
    tauri_conf = os.path.join(src_tauri, "tauri.conf.json")

    if not os.path.isdir(src_tauri):
        return None

    result = {
        "src_tauri_found": True,
        "tauri_conf_exists": os.path.isfile(tauri_conf),
        "capabilities": [],
        "sidecars": [],
        "security_notes": [],
    }

    # Parse tauri.conf.json if present
    if os.path.isfile(tauri_conf):
        try:
            with open(tauri_conf, 'r', encoding='utf-8') as f:
                conf = json.load(f)

            # Check security settings
            security = conf.get("security", {})
            if security.get("dangerousDisableAssetCspModification"):
                result["security_notes"].append({
                    "severity": "high",
                    "message": "dangerousDisableAssetCspModification is enabled — CSP is weakened"
                })
            if security.get("assetProtocol", {}).get("enableScope", True) is False:
                result["security_notes"].append({
                    "severity": "high",
                    "message": "Asset protocol scope is disabled — all files accessible"
                })

            # Check for sidecars
            bundle = conf.get("bundle", {})
            external_bin = bundle.get("externalBin", [])
            result["sidecars"] = external_bin

        except (json.JSONDecodeError, IOError):
            result["tauri_conf_parse_error"] = True

    # Check capabilities directory
    caps_dir = os.path.join(src_tauri, "capabilities")
    if os.path.isdir(caps_dir):
        for fn in os.listdir(caps_dir):
            if fn.endswith('.json'):
                result["capabilities"].append(fn)

    return result


# ─── File Cache (Single-Pass Workspace Scanner) ──────────────

# Source extensions used across engines for file filtering
SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".html", ".htm",
    ".css", ".scss", ".pcss", ".less",
}

# Max file size to read into cache (500KB)
_MAX_CACHED_FILE_SIZE = 500 * 1024


class FileCache:
    """Single-pass workspace scanner that caches file contents.

    Instead of each engine doing its own os.walk + f.read(), a shared
    FileCache reads every source file once and provides content to all
    engines. This collapses 20+ workspace walks into 1 for commands
    like `handbook`.

    Usage:
        cache = FileCache(workspace)
        for rel_path, ext, content in cache.iter_files():
            # process file
        # Or:
        files = cache.get_files()  # Dict[rel_path, content]
    """

    def __init__(self, workspace: str, max_files: int = 3000,
                 extensions: Optional[Set[str]] = None,
                 config: Optional[Dict] = None):
        self.workspace = os.path.abspath(workspace)
        self.max_files = max_files
        self.extensions = extensions or SOURCE_EXTENSIONS
        self.config = config or {}
        self.truncated = False

        self._files: Optional[Dict[str, str]] = None  # {rel_path: content}
        self._file_meta: Optional[List[Tuple[str, str]]] = None  # [(rel_path, ext)]

    def scan(self) -> Dict[str, str]:
        """Single os.walk pass. Returns {rel_path: content}."""
        if self._files is not None:
            return self._files

        self._files = {}
        self._file_meta = []
        count = 0

        for root, dirs, filenames in os.walk(self.workspace):
            # Filter ignored directories
            dirs[:] = [
                d for d in dirs
                if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')
            ]
            if '.codelens' in root:
                dirs.clear()
                continue

            for fn in filenames:
                if count >= self.max_files:
                    self.truncated = True
                    logger.info(f"FileCache: truncated at {self.max_files} files")
                    return self._files

                # Skip ignored extensions
                if any(fn.endswith(ext) for ext in DEFAULT_IGNORE_EXTENSIONS):
                    continue

                ext = os.path.splitext(fn)[1].lower()
                if ext not in self.extensions:
                    continue

                path = os.path.join(root, fn)
                rel = os.path.relpath(path, self.workspace)

                # Skip large files
                try:
                    file_size = os.path.getsize(path)
                    if file_size > _MAX_CACHED_FILE_SIZE:
                        continue
                except OSError:
                    continue

                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        self._files[rel] = f.read()
                    self._file_meta.append((rel, ext))
                except (IOError, OSError):
                    continue

                count += 1

        logger.info(f"FileCache: scanned {count} files from {self.workspace}")
        return self._files

    def iter_files(self, extensions: Optional[Set[str]] = None) -> List[Tuple[str, str, str]]:
        """Returns [(rel_path, ext, content)] for cached files.

        Args:
            extensions: Optional filter by file extensions (e.g., {'.ts', '.tsx'}).
        """
        self.scan()
        results = []
        for rel, ext in (self._file_meta or []):
            if extensions and ext not in extensions:
                continue
            content = self._files.get(rel)
            if content is not None:
                results.append((rel, ext, content))
        return results

    def get_files(self, extensions: Optional[Set[str]] = None) -> Dict[str, str]:
        """Returns {rel_path: content} for cached files, optionally filtered by extension."""
        self.scan()
        if not extensions:
            return dict(self._files)
        return {
            rel: content for rel, content in self._files.items()
            if os.path.splitext(rel)[1].lower() in extensions
        }

    def get_file_count(self) -> int:
        """Return number of cached files."""
        self.scan()
        return len(self._files)

    def get_content(self, rel_path: str) -> Optional[str]:
        """Get content for a specific file by relative path."""
        self.scan()
        return self._files.get(rel_path)


def walk_source_files(workspace: str, extensions: Optional[Set[str]] = None,
                      max_files: int = 3000) -> List[Tuple[str, str, str]]:
    """Convenience function: walk workspace and return [(rel_path, ext, content)].

    This is a lightweight alternative to FileCache for engines that only
    need a single pass and don't need caching across calls.

    Args:
        workspace: Absolute path to workspace.
        extensions: Source file extensions to include (default: SOURCE_EXTENSIONS).
        max_files: Maximum number of files to scan (default: 3000).

    Returns:
        List of (rel_path, ext, content) tuples.
    """
    workspace = os.path.abspath(workspace)
    exts = extensions or SOURCE_EXTENSIONS
    results = []
    count = 0

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [
            d for d in dirs
            if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')
        ]
        if '.codelens' in root:
            dirs.clear()
            continue

        for fn in filenames:
            if count >= max_files:
                return results

            if any(fn.endswith(ext) for ext in DEFAULT_IGNORE_EXTENSIONS):
                continue

            ext = os.path.splitext(fn)[1].lower()
            if ext not in exts:
                continue

            path = os.path.join(root, fn)
            rel = os.path.relpath(path, workspace)

            try:
                file_size = os.path.getsize(path)
                if file_size > _MAX_CACHED_FILE_SIZE:
                    continue
            except OSError:
                continue

            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                results.append((rel, ext, content))
                count += 1
            except (IOError, OSError):
                continue

    return results
