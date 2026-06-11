"""Shared utilities for CodeLens."""

import os
import json
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

# ─── Shared Constants (used by multiple engines) ──────────────

# Maximum file size to read (500KB) — used by envcheck_engine and others
MAX_FILE_SIZE = 500 * 1024

# Maximum number of files to scan by default
MAX_FILES_DEFAULT = 3000


# ─── Time Budget Helper ────────────────────────────────────────

def time_budget_expired(start_time: float, budget_seconds: float) -> bool:
    """Check if the time budget has expired.

    Args:
        start_time: Start time from time.time()
        budget_seconds: Maximum allowed seconds

    Returns:
        True if budget expired, False otherwise.
    """
    import time
    return (time.time() - start_time) > budget_seconds


# ─── Generated File Detection ──────────────────────────────────

# Known generated/lock file patterns
_GENERATED_FILE_PATTERNS = frozenset({
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb',
    'Cargo.lock', 'Gemfile.lock', 'poetry.lock', 'pdm.lock',
    'composer.lock', 'mix.lock', 'conan.lock', 'conanfile.lock',
    'go.sum', 'requirements.txt',  # sometimes generated
    '.eslintcache', '.tsbuildinfo',
    'yarn-error.log', 'npm-debug.log', 'yarn-debug.log',
    'pnpm-debug.log', 'lerna-debug.log',
})


def is_generated_file(filename: str) -> bool:
    """Check if a file is a generated/lock file that should be skipped.

    Args:
        filename: Just the filename (not full path), e.g. 'Cargo.lock'

    Returns:
        True if the file appears to be auto-generated.
    """
    if filename in _GENERATED_FILE_PATTERNS:
        return True
    # Minified JS/CSS files
    if '.min.' in filename:
        return True
    # Source maps
    if filename.endswith('.map'):
        return True
    # .d.ts declaration files
    if filename.endswith('.d.ts'):
        return True
    return False


# ─── Binary Artifact Scanner ──────────────────────────────────

# Binary and compiled file extensions
_BINARY_EXTENSIONS = frozenset({
    '.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.o', '.obj',
    '.wasm', '.pyc', '.pyo', '.class', '.jar', '.war',
    '.msi', '.dmg', '.deb', '.rpm', '.apk', '.ipa',
    '.nupkg', '.snap', '.flatpak', '.appimage',
    '.7z', '.zip', '.tar', '.gz', '.bz2', '.xz', '.rar',
})


def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts.

    Detects:
    - Binary executables and libraries (.exe, .dll, .so, .dylib, .wasm, etc.)
    - Compiled Python (.pyc, .pyo)
    - Compiled Java (.class, .jar)
    - Package archives (.msi, .dmg, .deb, etc.)
    - Large vendor directories that inflate repo size

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with found artifacts, counts, and size analysis.
    """
    workspace = os.path.abspath(workspace)
    artifacts = []
    vendor_dirs = []
    total_binary_size = 0

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        # Check for large vendor directories
        for d in dirs:
            if d in ('vendor', 'third_party', '3rdparty', 'external', 'libs', 'lib'):
                dir_path = os.path.join(root, d)
                try:
                    dir_size = sum(
                        os.path.getsize(os.path.join(dp, f))
                        for dp, _, fns in os.walk(dir_path)
                        for f in fns
                        if os.path.isfile(os.path.join(dp, f))
                    )
                    if dir_size > 1024 * 1024:  # > 1MB
                        vendor_dirs.append({
                            "path": os.path.relpath(dir_path, workspace),
                            "size_bytes": dir_size,
                            "size_mb": round(dir_size / (1024 * 1024), 1),
                        })
                except (OSError, PermissionError):
                    pass

        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _BINARY_EXTENSIONS:
                path = os.path.join(root, fn)
                try:
                    size = os.path.getsize(path)
                    total_binary_size += size
                    artifacts.append({
                        "file": os.path.relpath(path, workspace),
                        "type": ext,
                        "size_bytes": size,
                        "size_kb": round(size / 1024, 1),
                    })
                except OSError:
                    pass

    # Sort by size descending
    artifacts.sort(key=lambda a: a["size_bytes"], reverse=True)

    return {
        "status": "ok",
        "workspace": workspace,
        "total_artifacts": len(artifacts),
        "total_binary_size_bytes": total_binary_size,
        "total_binary_size_mb": round(total_binary_size / (1024 * 1024), 1),
        "artifacts": artifacts[:100],  # Cap at 100
        "vendor_dirs": vendor_dirs,
        "summary": {
            "by_type": _count_by_ext(artifacts),
            "large_artifacts": [a for a in artifacts if a["size_bytes"] > 1024 * 1024],
        }
    }


def _count_by_ext(artifacts: List[Dict]) -> Dict[str, int]:
    """Count artifacts by extension."""
    counts: Dict[str, int] = {}
    for a in artifacts:
        ext = a.get("type", "unknown")
        counts[ext] = counts.get(ext, 0) + 1
    return counts


# ─── Tauri Artifact Scanner ───────────────────────────────────

def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Scan Tauri-specific artifacts and configuration.

    Analyzes:
    - tauri.conf.json (window config, security, capabilities)
    - Cargo.toml dependencies (tauri version, features)
    - Sidecar binaries
    - Updater configuration
    - WebView security (CSP, asset protocol)
    - Deep-link / custom protocol schemes
    - Capabilities/permissions (Tauri v2)

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with Tauri analysis, or None if not a Tauri project.
    """
    workspace = os.path.abspath(workspace)

    # Find tauri.conf.json
    tauri_conf_paths = [
        os.path.join(workspace, "src-tauri", "tauri.conf.json"),
        os.path.join(workspace, "tauri.conf.json"),
        os.path.join(workspace, "src", "tauri.conf.json"),
    ]
    # Also search recursively for tauri.conf.json (max depth 3)
    for root, dirs, filenames in os.walk(workspace):
        depth = os.path.relpath(root, workspace).count(os.sep)
        if depth > 3:
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn == "tauri.conf.json":
                path = os.path.join(root, fn)
                if path not in tauri_conf_paths:
                    tauri_conf_paths.append(path)

    tauri_conf_path = None
    for path in tauri_conf_paths:
        if os.path.exists(path):
            tauri_conf_path = path
            break

    if not tauri_conf_path:
        return None

    result: Dict[str, Any] = {
        "status": "ok",
        "tauri_conf": tauri_conf_path,
        "findings": [],
    }

    # Parse tauri.conf.json
    try:
        with open(tauri_conf_path, 'r', encoding='utf-8') as f:
            conf = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        result["findings"].append({
            "severity": "error",
            "category": "config",
            "message": f"Cannot parse tauri.conf.json: {e}",
        })
        return result

    # Extract key information
    # Tauri v1 structure: tauri > windows, tauri > security, etc.
    # Tauri v2 structure: app > windows, app > security, etc.
    tauri_section = conf.get("tauri", conf)  # v1 uses "tauri" key, v2 may not
    app_section = conf.get("app", tauri_section)

    # ─── Window Configuration ────
    windows = app_section.get("windows", [])
    result["window_count"] = len(windows) if isinstance(windows, list) else 0
    result["windows"] = []
    if isinstance(windows, list):
        for w in windows:
            win_info = {
                "label": w.get("label", "main"),
                "title": w.get("title", ""),
                "url": w.get("url", ""),
                "width": w.get("width", 800),
                "height": w.get("height", 600),
                "fullscreen": w.get("fullscreen", False),
                "resizable": w.get("resizable", True),
                "decorations": w.get("decorations", True),
                "transparent": w.get("transparent", False),
            }
            result["windows"].append(win_info)
            # Security: transparent window
            if w.get("transparent"):
                result["findings"].append({
                    "severity": "info",
                    "category": "window",
                    "message": f"Window '{win_info['label']}' is transparent — ensure no sensitive data is visible behind it",
                })
            # Security: fullscreen
            if w.get("fullscreen"):
                result["findings"].append({
                    "severity": "info",
                    "category": "window",
                    "message": f"Window '{win_info['label']}' starts in fullscreen — consider exit mechanism",
                })

    # ─── Security Configuration ────
    security = tauri_section.get("security", {})
    if security:
        csp = security.get("csp", None)
        result["csp"] = csp
        if not csp:
            result["findings"].append({
                "severity": "warning",
                "category": "security",
                "message": "No Content Security Policy (CSP) configured — webview may load arbitrary content",
            })
        else:
            if "unsafe-eval" in str(csp):
                result["findings"].append({
                    "severity": "warning",
                    "category": "security",
                    "message": "CSP contains 'unsafe-eval' — allows eval() which can be a security risk",
                })
            if "unsafe-inline" in str(csp):
                result["findings"].append({
                    "severity": "info",
                    "category": "security",
                    "message": "CSP contains 'unsafe-inline' — consider using nonce-based CSP instead",
                })

        # Asset protocol
        asset_protocol = security.get("assetProtocol", {})
        if isinstance(asset_protocol, dict) and asset_protocol.get("enable", False):
            result["findings"].append({
                "severity": "warning",
                "category": "security",
                "message": "Asset protocol is enabled — allows loading local files via webview",
            })

        # Dangerous remote domain access
        dangerous_remote = security.get("dangerousRemoteDomainIpcAccess", [])
        if dangerous_remote:
            result["findings"].append({
                "severity": "warning",
                "category": "security",
                "message": f"Dangerous remote domain IPC access configured: {dangerous_remote}",
            })
    else:
        result["findings"].append({
            "severity": "info",
            "category": "security",
            "message": "No security section in tauri.conf.json — using defaults",
        })

    # ─── Updater Configuration ────
    updater = tauri_section.get("updater", {})
    if updater and updater.get("active", False):
        result["updater"] = {
            "active": True,
            "endpoints": updater.get("endpoints", []),
            "pubkey": bool(updater.get("pubkey", "")),
        }
        if not updater.get("pubkey"):
            result["findings"].append({
                "severity": "warning",
                "category": "updater",
                "message": "Updater is active but no public key configured — updates could be tampered",
            })

    # ─── Bundle Configuration ────
    bundle = tauri_section.get("bundle", {})
    if bundle:
        result["bundle"] = {
            "identifier": bundle.get("identifier", ""),
            "active": bundle.get("active", True),
            "targets": bundle.get("targets", []),
        }

    # ─── Deep-link / Custom Protocol ────
    # Tauri v2 uses plugins.deep-link
    plugins = conf.get("plugins", {})
    deep_link = plugins.get("deep-link", {})
    if deep_link and deep_link.get("desktop", {}).get("schemes"):
        schemes = deep_link["desktop"]["schemes"]
        result["deep_link_schemes"] = schemes
        result["findings"].append({
            "severity": "info",
            "category": "deep-link",
            "message": f"Custom URL schemes registered: {schemes} — ensure proper input validation",
        })

    # ─── Capabilities (Tauri v2) ────
    capabilities_dir = os.path.join(os.path.dirname(tauri_conf_path), "capabilities")
    if os.path.isdir(capabilities_dir):
        capabilities = []
        for fn in os.listdir(capabilities_dir):
            if fn.endswith('.json'):
                try:
                    with open(os.path.join(capabilities_dir, fn), 'r', encoding='utf-8') as f:
                        cap = json.load(f)
                    capabilities.append({
                        "file": fn,
                        "identifier": cap.get("identifier", ""),
                        "windows": cap.get("windows", []),
                        "permissions": cap.get("permissions", []),
                    })
                except (json.JSONDecodeError, IOError):
                    pass
        if capabilities:
            result["capabilities"] = capabilities
            # Check for dangerous permissions
            for cap in capabilities:
                perms = cap.get("permissions", [])
                dangerous_perms = [p for p in perms if isinstance(p, str) and 'allow' in p.lower()]
                if dangerous_perms:
                    result["findings"].append({
                        "severity": "info",
                        "category": "capabilities",
                        "message": f"Capability '{cap.get('identifier', fn)}' has allow permissions: {dangerous_perms[:5]}",
                    })

    # ─── Cargo.toml analysis ────
    cargo_paths = [
        os.path.join(workspace, "src-tauri", "Cargo.toml"),
        os.path.join(workspace, "Cargo.toml"),
    ]
    for cargo_path in cargo_paths:
        if os.path.exists(cargo_path):
            try:
                with open(cargo_path, 'r', encoding='utf-8') as f:
                    cargo_content = f.read()
                # Extract tauri version/features
                import re
                for m in re.finditer(r'tauri\s*=\s*["{]', cargo_content):
                    idx = m.start()
                    line = cargo_content[idx:cargo_content.find('\n', idx)]
                    result["tauri_dependency"] = line.strip()
                    if 'features' in line:
                        result["findings"].append({
                            "severity": "info",
                            "category": "dependency",
                            "message": f"Tauri dependency with custom features: {line.strip()[:100]}",
                        })
            except IOError:
                pass
            break

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
