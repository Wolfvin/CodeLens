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


def should_ignore_dir(rel_path: str, extra_ignore: Optional[frozenset] = None) -> bool:
    """Check if a relative directory path should be ignored.

    Uses path-segment-aware matching against DEFAULT_IGNORE_DIRS (plus any
    caller-supplied extra set) to avoid false positives from substring matches.
    For example, 'target' matches 'src/target/debug' but NOT 'test-target/src'.

    Args:
        rel_path: Relative path from workspace root (e.g. 'src/node_modules/pkg').
        extra_ignore: Optional additional directory names to ignore.

    Returns:
        True if the path contains an ignored directory segment, False otherwise.
    """
    # Normalize to forward slashes for consistent matching
    normalized = rel_path.replace('\\', '/')

    # Merge default + extra ignore sets
    ignore_dirs = DEFAULT_IGNORE_DIRS
    if extra_ignore:
        ignore_dirs = ignore_dirs | extra_ignore

    # Split the path into segments and check each against the ignore set
    segments = normalized.split('/')
    for segment in segments:
        if segment in ignore_dirs:
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


# ─── File Reading Utility ──────────────────────────────────

def safe_read_file(file_path: str, max_size: int = 200 * 1024, encoding: str = 'utf-8') -> Optional[str]:
    """Safely read a file's contents with error handling and size limit.

    Args:
        file_path: Absolute or relative path to the file.
        max_size: Maximum file size in bytes to read (default 200KB).
                  Files larger than this are skipped to avoid memory issues.
        encoding: File encoding (default utf-8).

    Returns:
        File contents as string, or None if the file cannot be read,
        doesn't exist, is too large, or is a binary file.
    """
    try:
        if not os.path.isfile(file_path):
            return None

        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            logger.debug(f"Skipping large file ({file_size} bytes): {file_path}")
            return None

        with open(file_path, 'r', encoding=encoding, errors='ignore') as f:
            return f.read()
    except (IOError, OSError, UnicodeDecodeError):
        logger.debug(f"Failed to read file: {file_path}", exc_info=True)
        return None


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "5.8.0"


# ─── Binary Artifact Scanning ──────────────────────────────────

def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts.

    Detects:
    - Executable files (.exe, .msi, .dmg, .AppImage, .deb)
    - Shared libraries (.dll, .so, .dylib)
    - Compiled objects (.o, .pyc, .class)
    - Build output directories (dist/, target/release/)
    - Bundled resources (assets/, resources/)

    Args:
        workspace: Absolute path to workspace

    Returns:
        Dict with binary artifact findings and metadata
    """
    workspace = os.path.abspath(workspace)

    EXECUTABLE_EXTS = {'.exe', '.msi', '.dmg', '.app', '.deb', '.rpm',
                       '.AppImage', '.snap', '.flatpak', '.bin'}
    LIBRARY_EXTS = {'.dll', '.so', '.dylib', '.ko'}
    COMPILED_EXTS = {'.o', '.obj', '.pyc', '.pyo', '.class', '.jar',
                     '.wasm', '.node'}

    BINARY_EXTENSIONS_ALL = EXECUTABLE_EXTS | LIBRARY_EXTS | COMPILED_EXTS

    # Known build output directories
    BUILD_DIRS = {
        'dist', 'target/release', 'target/debug', 'build', 'out',
        'bin', 'output', 'release', 'Debug', 'Release',
    }

    executables = []
    libraries = []
    compiled = []
    build_dirs_found = []
    total_binary_size = 0

    for root, dirs, files in os.walk(workspace):
        # Skip ignored dirs
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        rel_root = os.path.relpath(root, workspace)

        # Check for known build output directories
        for build_dir in BUILD_DIRS:
            if rel_root == build_dir or rel_root.replace('\\', '/').startswith(build_dir + '/'):
                build_dirs_found.append({
                    'path': rel_root,
                    'type': 'build_output',
                })

        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext not in BINARY_EXTENSIONS_ALL:
                continue

            file_path = os.path.join(root, f)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                file_size = os.path.getsize(file_path)
            except OSError:
                file_size = 0

            total_binary_size += file_size

            artifact = {
                'name': f,
                'path': rel_path,
                'size': file_size,
                'size_human': _human_size(file_size),
                'extension': ext,
            }

            if ext in EXECUTABLE_EXTS:
                artifact['type'] = 'executable'
                executables.append(artifact)
            elif ext in LIBRARY_EXTS:
                artifact['type'] = 'shared_library'
                libraries.append(artifact)
            elif ext in COMPILED_EXTS:
                artifact['type'] = 'compiled_object'
                compiled.append(artifact)

    total = len(executables) + len(libraries) + len(compiled)

    # Determine build system
    build_system = _detect_build_system(workspace)

    return {
        'status': 'ok',
        'workspace': workspace,
        'build_system': build_system,
        'stats': {
            'total_artifacts': total,
            'executables': len(executables),
            'shared_libraries': len(libraries),
            'compiled_objects': len(compiled),
            'build_dirs': len(build_dirs_found),
            'total_binary_size': total_binary_size,
            'total_binary_size_human': _human_size(total_binary_size),
        },
        'executables': executables,
        'shared_libraries': libraries,
        'compiled_objects': compiled,
        'build_dirs': build_dirs_found,
        'recommendations': _generate_binary_recommendations(
            executables, libraries, compiled, build_dirs_found, build_system
        ),
    }


def _human_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _detect_build_system(workspace: str) -> Dict[str, Any]:
    """Detect the build system and packaging tools used."""
    systems = []

    # Tauri
    if os.path.exists(os.path.join(workspace, 'src-tauri', 'Cargo.toml')):
        systems.append({'name': 'tauri', 'config': 'src-tauri/Cargo.toml'})
    elif os.path.exists(os.path.join(workspace, 'Cargo.toml')):
        cargo_path = os.path.join(workspace, 'Cargo.toml')
        try:
            with open(cargo_path, 'r', encoding='utf-8', errors='replace') as f:
                if 'tauri' in f.read().lower():
                    systems.append({'name': 'tauri', 'config': 'Cargo.toml'})
        except IOError:
            pass

    # Electron
    if os.path.exists(os.path.join(workspace, 'electron', 'main.js')) or \
       os.path.exists(os.path.join(workspace, 'electron', 'main.ts')):
        systems.append({'name': 'electron', 'config': 'electron/'})
    else:
        pkg_path = os.path.join(workspace, 'package.json')
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                deps = {**pkg.get('dependencies', {}), **pkg.get('devDependencies', {})}
                if 'electron' in deps or 'electron-builder' in deps:
                    systems.append({'name': 'electron', 'config': 'package.json'})
            except (json.JSONDecodeError, IOError):
                pass

    # Cargo (Rust)
    if os.path.exists(os.path.join(workspace, 'Cargo.toml')):
        systems.append({'name': 'cargo', 'config': 'Cargo.toml'})

    # npm/yarn/pnpm/bun
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.exists(pkg_path):
        if os.path.exists(os.path.join(workspace, 'yarn.lock')):
            systems.append({'name': 'yarn', 'config': 'yarn.lock'})
        elif os.path.exists(os.path.join(workspace, 'pnpm-lock.yaml')):
            systems.append({'name': 'pnpm', 'config': 'pnpm-lock.yaml'})
        elif os.path.exists(os.path.join(workspace, 'bun.lock')) or os.path.exists(os.path.join(workspace, 'bun.lockb')):
            systems.append({'name': 'bun', 'config': 'bun.lock'})
        else:
            systems.append({'name': 'npm', 'config': 'package-lock.json'})

    # Python
    if os.path.exists(os.path.join(workspace, 'pyproject.toml')):
        systems.append({'name': 'python', 'config': 'pyproject.toml'})
    elif os.path.exists(os.path.join(workspace, 'setup.py')):
        systems.append({'name': 'python', 'config': 'setup.py'})

    return {
        'detected': [s['name'] for s in systems],
        'details': systems,
    }


def _generate_binary_recommendations(
    executables, libraries, compiled, build_dirs, build_system
) -> List[str]:
    """Generate recommendations based on binary artifact findings."""
    recs = []

    if executables:
        recs.append(
            f"Found {len(executables)} executable(s). "
            f"Ensure these are not committed to version control — "
            f"use CI/CD to build and distribute via releases."
        )

    if libraries:
        recs.append(
            f"Found {len(libraries)} shared library/libraries. "
            f"Verify these are not proprietary or need separate licensing."
        )

    if compiled:
        total_pyc = sum(1 for c in compiled if c['extension'] in ('.pyc', '.pyo'))
        if total_pyc:
            recs.append(
                f"Found {total_pyc} .pyc/.pyo files. "
                f"Add '**/__pycache__/' to .gitignore."
            )

    if build_dirs:
        recs.append(
            f"Found {len(build_dirs)} build output directories. "
            f"Ensure these are in .gitignore and not committed."
        )

    tauri_detected = any(s['name'] == 'tauri' for s in build_system.get('details', []))
    electron_detected = any(s['name'] == 'electron' for s in build_system.get('details', []))

    if tauri_detected:
        recs.append(
            "TAURI: Use 'tauri build' for production builds. "
            "Output goes to src-tauri/target/release/bundle/. "
            "Distribute via GitHub Releases."
        )

    if electron_detected:
        recs.append(
            "ELECTRON: Use 'electron-builder' or 'electron-forge' for packaging. "
            "Add 'dist/' and '*.exe' to .gitignore."
        )

    return recs
