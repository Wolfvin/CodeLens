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

def write_output_files(workspace: str, scan_result, max_files: int = 3000) -> dict:
    """After a scan, generate outline.json and summary.json into .codelens/."""
    try:
        from outline_engine import get_workspace_outline
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)

        outline_data = get_workspace_outline(workspace, max_files=max_files)

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


# ─── Source File Walking ─────────────────────────────────────

# Default source extensions for walking
DEFAULT_SOURCE_EXTENSIONS = {
    '.html', '.htm', '.css', '.scss', '.less', '.sass',
    '.js', '.mjs', '.cjs', '.jsx', '.ts', '.tsx',
    '.rs', '.py', '.vue', '.svelte', '.php',
}


def walk_source_files(
    workspace: str,
    extensions: Optional[set] = None,
    max_files: int = MAX_FILES_DEFAULT,
    ignore_dirs: Optional[frozenset] = None,
) -> List[tuple]:
    """Walk workspace source files with ignore/extension/max_files filtering.

    Performs a single-pass walk over all source files in the workspace,
    yielding (rel_path, ext, content) tuples. Provides consistent ignore-dir
    filtering, extension filtering, and max_files limiting.

    Args:
        workspace: Absolute path to workspace root.
        extensions: Set of file extensions to include (e.g., {'.js', '.ts'}).
                    If None, uses DEFAULT_SOURCE_EXTENSIONS.
        max_files: Maximum number of files to scan. Stops after this many.
        ignore_dirs: Set of directory names to ignore. If None, uses DEFAULT_IGNORE_DIRS.

    Returns:
        List of (rel_path, ext, content) tuples for each file found.
    """
    if extensions is None:
        extensions = DEFAULT_SOURCE_EXTENSIONS
    if ignore_dirs is None:
        ignore_dirs = DEFAULT_IGNORE_DIRS

    results = []
    count = 0

    for root, dirs, files in os.walk(workspace):
        # Filter out ignored directories (in-place to prevent os.walk from descending)
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]

        for fname in sorted(files):
            if count >= max_files:
                return results

            ext = os.path.splitext(fname)[1].lower()
            if ext not in extensions:
                continue

            file_path = os.path.join(root, fname)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip generated/minified files
            if is_generated_file(fname):
                continue

            content = safe_read_file(file_path)
            if content is not None:
                results.append((rel_path, ext, content))
                count += 1

    return results


# ─── Generated File Detection ─────────────────────────────────

_GENERATED_FILE_PATTERNS = {
    # Lock files
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb',
    'Cargo.lock', 'Gemfile.lock', 'poetry.lock', 'uv.lock',
    'composer.lock', 'pip-lock.txt',
    # Generated directories/files
    '.d.ts',  # TypeScript declaration files
}

_GENERATED_FILE_SUFFIXES = (
    '.min.js', '.min.css', '.bundle.js', '.chunk.js',
    '.map',  # source maps
    '.generated.ts', '.generated.js', '.generated.py',
    '.d.ts',  # TypeScript declarations
    '.lock',
)


def is_generated_file(filename: str) -> bool:
    """Check if a filename is a generated/lock file that should be skipped.

    Matches patterns like:
    - Lock files: package-lock.json, yarn.lock, Cargo.lock
    - Minified files: *.min.js, *.min.css
    - Source maps: *.map
    - Declaration files: *.d.ts
    - Bundle/chunk files: *.bundle.js, *.chunk.js

    Args:
        filename: Just the filename (not full path), e.g., 'package-lock.json'.

    Returns:
        True if the file is generated/lock and should be skipped.
    """
    basename = os.path.basename(filename)

    # Exact match
    if basename in _GENERATED_FILE_PATTERNS:
        return True

    # Suffix match
    for suffix in _GENERATED_FILE_SUFFIXES:
        if basename.endswith(suffix):
            return True

    return False


# ─── Binary Artifact Scanning ─────────────────────────────────

_BINARY_EXTENSIONS = {
    '.exe', '.dll', '.so', '.dylib', '.bin', '.app',
    '.dmg', '.msi', '.deb', '.rpm', '.apk', '.ipa',
    '.wasm', '.pyc', '.pyd', '.pyo', '.o', '.obj',
    '.class', '.jar', '.war', '.ear',
    '.node', '.pdb', '.ilk', '.lib',
    '.ttf', '.otf', '.woff', '.woff2', '.eot',
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
}

_BINARY_SIZE_THRESHOLD = 500 * 1024  # 500KB — files above this in src dirs are suspicious

_ELECTRON_MARKERS = ['electron', 'electron-builder', 'electron-forge', 'electron-packager']

_TAURI_CONFIG_FILES = [
    'tauri.conf.json', 'tauri.conf.json5', 'Tauri.toml',
]


def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts.

    Detects:
    - Binary files in source directories
    - Large files that might be accidentally committed
    - Electron app indicators
    - Build artifact directories

    Args:
        workspace: Absolute path to workspace root.

    Returns:
        Dict with scan results including lists of found artifacts.
    """
    binary_files = []
    large_files = []
    electron_detected = False
    build_dirs = []

    for root, dirs, files in os.walk(workspace):
        # Filter ignored dirs
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

        rel_root = os.path.relpath(root, workspace)

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            file_path = os.path.join(root, fname)

            if ext in _BINARY_EXTENSIONS:
                try:
                    size = os.path.getsize(file_path)
                    rel_path = os.path.relpath(file_path, workspace)
                    binary_files.append({
                        "path": rel_path,
                        "type": ext,
                        "size_kb": round(size / 1024, 1),
                    })
                except OSError:
                    pass
            else:
                # Check for suspiciously large source files
                try:
                    size = os.path.getsize(file_path)
                    if size > _BINARY_SIZE_THRESHOLD:
                        rel_path = os.path.relpath(file_path, workspace)
                        large_files.append({
                            "path": rel_path,
                            "size_kb": round(size / 1024, 1),
                        })
                except OSError:
                    pass

        # Check for Electron markers in package.json
        if not electron_detected:
            pkg_json = os.path.join(root, 'package.json')
            if os.path.exists(pkg_json):
                try:
                    with open(pkg_json, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read().lower()
                        if any(marker in content for marker in _ELECTRON_MARKERS):
                            electron_detected = True
                except (IOError, OSError):
                    pass

    # Check for common build output directories
    for build_dir in ('dist', 'build', 'out', 'target', 'bin'):
        full_path = os.path.join(workspace, build_dir)
        if os.path.isdir(full_path):
            try:
                file_count = sum(1 for _, _, files in os.walk(full_path) for _ in files)
                build_dirs.append({"path": build_dir, "file_count": file_count})
            except OSError:
                pass

    return {
        "status": "ok",
        "workspace": workspace,
        "binary_files": binary_files[:100],  # Cap results
        "binary_count": len(binary_files),
        "large_files": large_files[:50],
        "large_file_count": len(large_files),
        "electron_detected": electron_detected,
        "build_dirs": build_dirs,
    }


def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Scan workspace for Tauri-specific artifacts and configurations.

    Detects:
    - Tauri configuration files (tauri.conf.json, Tauri.toml)
    - Tauri Rust source commands (#[tauri::command])
    - Tauri IPC invoke calls in JS/TS
    - Capabilities/permissions
    - Sidecar binaries
    - Updater configuration
    - WebView security settings (CSP, asset protocol)

    Args:
        workspace: Absolute path to workspace root.

    Returns:
        Dict with Tauri analysis results, or None if Tauri is not detected.
    """
    import re

    tauri_detected = False
    config_files = []
    commands = []
    invoke_calls = []
    capabilities = []
    sidecars = []
    updater_config = {}
    webview_security = {}
    src_dir = None

    # 1. Detect Tauri config files
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

        for fname in files:
            if fname in _TAURI_CONFIG_FILES:
                tauri_detected = True
                file_path = os.path.join(root, fname)
                rel_path = os.path.relpath(file_path, workspace)
                config_files.append(rel_path)

                # Parse config for security-relevant settings
                if fname.endswith('.json') or fname.endswith('.json5'):
                    content = safe_read_file(file_path)
                    if content:
                        try:
                            # Simple JSON parse (skip comments for json5)
                            import json
                            clean = re.sub(r'//.*?\n', '\n', content)
                            clean = re.sub(r'/\*.*?\*/', '', clean, flags=re.DOTALL)
                            config = json.loads(clean)

                            # Check security settings
                            security = config.get("security", {})
                            if security:
                                webview_security = {
                                    "csp": security.get("csp", "not set"),
                                    "asset_protocol": security.get("assetProtocol", {}).get("enable", False),
                                    "dangerous_disable_asset_csp_modification": security.get("dangerousDisableAssetCspModification", False),
                                    "freeze_prototype": security.get("freezePrototype", False),
                                }

                            # Check updater config
                            updater = config.get("updater", {})
                            if updater:
                                updater_config = {
                                    "active": updater.get("active", False),
                                    "endpoints": updater.get("endpoints", []),
                                    "pubkey": "present" if updater.get("pubkey") else "missing",
                                }

                            # Check sidecars
                            bundle = config.get("bundle", {})
                            external_bin = bundle.get("externalBin", [])
                            if external_bin:
                                sidecars = external_bin

                            # Check capabilities
                            caps = config.get("capabilities", [])
                            for cap in caps:
                                if isinstance(cap, dict):
                                    capabilities.append({
                                        "identifier": cap.get("identifier", "unknown"),
                                        "permissions": cap.get("permissions", []),
                                    })
                                elif isinstance(cap, str):
                                    capabilities.append({"identifier": cap, "permissions": []})

                        except (json.JSONDecodeError, ValueError):
                            pass

            # Check for Tauri Cargo.toml dependency
            if fname == 'Cargo.toml' and not tauri_detected:
                file_path = os.path.join(root, fname)
                content = safe_read_file(file_path)
                if content and 'tauri' in content.lower():
                    tauri_detected = True

    if not tauri_detected:
        return None

    # 2. Scan Rust source for #[tauri::command] functions
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

        for fname in files:
            if not fname.endswith('.rs'):
                continue

            file_path = os.path.join(root, fname)
            content = safe_read_file(file_path)
            if not content:
                continue

            # Find #[tauri::command] annotated functions
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if '#[tauri::command]' in line or '#[tauri::command(' in line:
                    # Look for the function definition on the next few lines
                    for j in range(i + 1, min(i + 5, len(lines))):
                        match = re.match(r'\s*(?:pub\s+)?fn\s+(\w+)', lines[j])
                        if match:
                            fn_name = match.group(1)
                            rel_path = os.path.relpath(file_path, workspace)
                            commands.append({
                                "name": fn_name,
                                "file": rel_path,
                                "line": j + 1,
                            })
                            break

    # 3. Scan JS/TS source for invoke() calls
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

        for fname in files:
            if not (fname.endswith('.ts') or fname.endswith('.tsx') or
                    fname.endswith('.js') or fname.endswith('.jsx')):
                continue

            file_path = os.path.join(root, fname)
            content = safe_read_file(file_path)
            if not content:
                continue

            # Find invoke('commandName') or invoke({ cmd: 'commandName' })
            for match in re.finditer(r'invoke\s*\(\s*["\'](\w+)["\']', content):
                cmd_name = match.group(1)
                rel_path = os.path.relpath(file_path, workspace)
                # Find line number
                line_num = content[:match.start()].count('\n') + 1
                invoke_calls.append({
                    "command": cmd_name,
                    "file": rel_path,
                    "line": line_num,
                })

    # 4. Check for capabilities files in src-tauri/capabilities/
    cap_dir = os.path.join(workspace, 'src-tauri', 'capabilities')
    if os.path.isdir(cap_dir):
        for fname in os.listdir(cap_dir):
            if fname.endswith('.json'):
                file_path = os.path.join(cap_dir, fname)
                content = safe_read_file(file_path)
                if content:
                    try:
                        import json
                        cap_data = json.loads(content)
                        capabilities.append({
                            "identifier": cap_data.get("identifier", fname),
                            "permissions": cap_data.get("permissions", []),
                            "file": f"src-tauri/capabilities/{fname}",
                        })
                    except (json.JSONDecodeError, ValueError):
                        pass

    return {
        "status": "ok",
        "tauri_detected": True,
        "config_files": config_files,
        "rust_commands": commands,
        "rust_command_count": len(commands),
        "invoke_calls": invoke_calls,
        "invoke_call_count": len(invoke_calls),
        "capabilities": capabilities,
        "sidecars": sidecars,
        "updater_config": updater_config if updater_config else None,
        "webview_security": webview_security if webview_security else None,
    }


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "6.0.0"
