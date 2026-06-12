"""Shared utilities for CodeLens."""

import os
import re
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


# ─── Binary Artifact Scanning ──────────────────────────────

BINARY_EXTENSIONS = frozenset({
    '.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.o', '.obj',
    '.wasm', '.pyc', '.pyo', '.class', '.jar', '.war',
    '.dylib', '.bundle', '.ko', '.msi', '.dmg', '.pkg', '.deb', '.rpm',
    '.nupkg', '.whl', '.egg', '.tar.gz', '.zip', '.7z',
})

BINARY_MIME_SIGNATURES = {
    b'\x7fELF': 'elf_binary',
    b'MZ': 'pe_binary',
    b'\xfe\xed\xfa': 'macho_binary',
    b'\xcf\xfa\xed\xfe': 'macho_binary',
    b'\xce\xfa\xed\xfe': 'macho_binary',
    b'PK\x03\x04': 'zip_archive',
    b'\x1f\x8b': 'gzip_archive',
    b'BZh': 'bzip2_archive',
    b'\xfd7zXZ': 'xz_archive',
    b'\x89PNG': 'png_image',
    b'\xff\xd8\xff': 'jpeg_image',
    b'GIF8': 'gif_image',
    b'RIFF': 'riff_media',
    b'\x00asm': 'wasm_binary',
}

MAX_BINARY_SCAN_SIZE = 64 * 1024  # Only read first 64KB for signature detection


def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary and compiled artifacts.

    Detects files by:
    1. Known binary extensions (.exe, .dll, .so, .wasm, .pyc, etc.)
    2. MIME signature detection (ELF, PE, Mach-O, etc.)

    Args:
        workspace: Absolute path to workspace

    Returns:
        Dict with stats, findings list, and recommendations.
    """
    workspace = os.path.abspath(workspace)
    findings = []
    files_scanned = 0
    by_category: Dict[str, int] = {}

    # Directories that contain binary artifacts - don't skip these in binary scan
    RE_DIRS = {'dist', 'build', 'out', 'bin', 'target', 'output', 'release', 'pkg', 'compiled', 'bundle'}

    for root, dirs, filenames in os.walk(workspace):
        # Skip ignored dirs but allow RE_DIRS (which commonly contain binaries)
        filtered_dirs = []
        for d in dirs:
            if d.startswith('.'):
                continue
            if d in DEFAULT_IGNORE_DIRS and d not in RE_DIRS:
                continue
            filtered_dirs.append(d)
        dirs[:] = filtered_dirs
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            file_path = os.path.join(root, filename)
            ext = os.path.splitext(filename)[1].lower()
            files_scanned += 1

            finding = None

            # Check by extension
            if ext in BINARY_EXTENSIONS:
                cat = _binary_category(ext)
                rel_path = os.path.relpath(file_path, workspace)
                try:
                    fsize = os.path.getsize(file_path)
                except OSError:
                    fsize = 0
                finding = {
                    "path": rel_path,
                    "category": cat,
                    "extension": ext,
                    "size_bytes": fsize,
                    "detection_method": "extension",
                }
            else:
                # Check by MIME signature for extensionless or unknown files
                # Only check non-source files to avoid false positives
                if ext not in {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.html',
                               '.css', '.vue', '.svelte', '.json', '.md', '.yaml', '.yml',
                               '.toml', '.cfg', '.ini', '.txt', '.sh', '.bash', '.zsh',
                               '.gitignore', '.env', '.lock', '.map', '.d.ts'}:
                    sig = _read_file_signature(file_path)
                    if sig:
                        sig_type = _identify_signature(sig)
                        if sig_type:
                            rel_path = os.path.relpath(file_path, workspace)
                            try:
                                fsize = os.path.getsize(file_path)
                            except OSError:
                                fsize = 0
                            finding = {
                                "path": rel_path,
                                "category": sig_type,
                                "extension": ext,
                                "size_bytes": fsize,
                                "detection_method": "signature",
                            }

            if finding:
                findings.append(finding)
                cat = finding["category"]
                by_category[cat] = by_category.get(cat, 0) + 1

    # Compute total size
    total_size = sum(f.get("size_bytes", 0) for f in findings)

    # Recommendations
    recommendations = []
    if by_category.get("compiled_binary", 0) > 0:
        recommendations.append("Found compiled binaries in the workspace. Consider adding them to .gitignore and using a build pipeline instead.")
    if by_category.get("python_bytecode", 0) > 0:
        recommendations.append("Found Python bytecode files (.pyc/.pyo). Add '**/__pycache__/' and '*.pyc' to .gitignore.")
    if by_category.get("archive", 0) > 5:
        recommendations.append("Found many archive files. Consider storing large assets externally (S3, CDN) instead of in the repository.")
    if by_category.get("image", 0) > 10:
        recommendations.append("Found many image files. Consider optimizing or moving to an asset CDN to reduce repo size.")
    if total_size > 50 * 1024 * 1024:
        recommendations.append(f"Binary artifacts total {total_size / (1024*1024):.1f}MB. Consider using Git LFS for large files.")

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "files_scanned": files_scanned,
            "total_artifacts": len(findings),
            "total_size_bytes": total_size,
            "by_category": by_category,
        },
        "findings": findings[:50],
        "recommendations": recommendations,
    }


# ─── Generated File Detection ──────────────────────────────

GENERATED_FILE_PATTERNS = frozenset({
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb',
    'Cargo.lock', 'Gemfile.lock', 'poetry.lock', 'uv.lock',
    'go.sum', 'composer.lock', 'mix.lock',
    '.DS_Store', 'Thumbs.db', 'desktop.ini',
    'yarn-error.log', 'npm-debug.log',
})

GENERATED_FILE_PREFIXES = (
    '.eslintcache', '.stylelintcache',
)


def is_generated_file(filename: str) -> bool:
    """Check if a file is auto-generated and should be skipped during analysis.

    Detects lock files, OS-generated files, and other artifacts that
    are not hand-written source code.

    Args:
        filename: Just the filename (not the full path).

    Returns:
        True if the file appears to be auto-generated.
    """
    if filename in GENERATED_FILE_PATTERNS:
        return True
    for prefix in GENERATED_FILE_PREFIXES:
        if filename.startswith(prefix):
            return True
    # .min.js / .min.css are generated (minified) files
    lower = filename.lower()
    if '.min.js' in lower or '.min.css' in lower:
        return True
    return False


# ─── Tauri Artifact Scanning ────────────────────────────────

def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Scan workspace for Tauri application artifacts.

    Detects Tauri applications by looking for tauri.conf.json,
    src-tauri/ directory, and Cargo.toml with tauri dependency.
    Extracts IPC command/handler mappings, capabilities, and
    security configuration.

    Args:
        workspace: Absolute path to workspace

    Returns:
        Dict with Tauri analysis results, or None if no Tauri app detected.
    """
    workspace = os.path.abspath(workspace)

    # Check for Tauri markers
    tauri_conf = None
    src_tauri_dir = None
    cargo_toml_path = None

    # Check root-level tauri.conf.json
    root_conf = os.path.join(workspace, 'tauri.conf.json')
    if os.path.isfile(root_conf):
        tauri_conf = root_conf

    # Check src-tauri directory
    root_src_tauri = os.path.join(workspace, 'src-tauri')
    if os.path.isdir(root_src_tauri):
        src_tauri_dir = root_src_tauri
        nested_conf = os.path.join(root_src_tauri, 'tauri.conf.json')
        if os.path.isfile(nested_conf) and not tauri_conf:
            tauri_conf = nested_conf
        nested_cargo = os.path.join(root_src_tauri, 'Cargo.toml')
        if os.path.isfile(nested_cargo):
            cargo_toml_path = nested_cargo

    # Also check apps/* subdirectories for monorepo
    if not tauri_conf and not src_tauri_dir:
        for subdir_name in ('apps', 'packages', 'src'):
            subdir = os.path.join(workspace, subdir_name)
            if not os.path.isdir(subdir):
                continue
            try:
                for entry in os.listdir(subdir):
                    entry_path = os.path.join(subdir, entry)
                    if not os.path.isdir(entry_path):
                        continue
                    st = os.path.join(entry_path, 'src-tauri')
                    if os.path.isdir(st):
                        src_tauri_dir = st
                        tc = os.path.join(st, 'tauri.conf.json')
                        if os.path.isfile(tc):
                            tauri_conf = tc
                        ct = os.path.join(st, 'Cargo.toml')
                        if os.path.isfile(ct):
                            cargo_toml_path = ct
                        break
            except OSError:
                pass
        if src_tauri_dir:
            pass  # found it

    if not tauri_conf and not src_tauri_dir:
        return None

    result: Dict[str, Any] = {
        "is_tauri_app": True,
        "tauri_conf_path": os.path.relpath(tauri_conf, workspace) if tauri_conf else None,
        "src_tauri_dir": os.path.relpath(src_tauri_dir, workspace) if src_tauri_dir else None,
        "ipc_commands": [],
        "capabilities": [],
        "security": {},
        "sidecar_binaries": [],
    }

    # Parse tauri.conf.json
    if tauri_conf:
        try:
            with open(tauri_conf, 'r', encoding='utf-8') as f:
                conf = json.load(f)

            # Extract app info
            app_info = conf.get('app', conf.get('package', {}))
            if isinstance(app_info, dict):
                result["app_name"] = app_info.get('title', app_info.get('name', ''))

            # Security: CSP headers
            security = conf.get('app', {}).get('security', {})
            if security:
                result["security"]["csp"] = security.get('csp', 'not set')
                result["security"]["asset_protocol"] = security.get(
                    'assetProtocol', {}).get('enableScope', 'not set')
                result["security"]["dangerous_disable_asset_csp_modification"] = \
                    security.get('dangerousDisableAssetCspModification', False)

            # Sidecar binaries
            external_bin = conf.get('plugins', {}).get('updater', {}).get('endpoints', [])
            if external_bin:
                result["sidecar_binaries"] = external_bin

            # Check for window configuration
            windows = conf.get('app', {}).get('windows', [])
            if windows:
                result["windows_count"] = len(windows)
                result["security"]["devtools"] = any(
                    w.get('devtools', False) for w in windows
                )

        except (json.JSONDecodeError, IOError):
            pass

    # Parse Cargo.toml for tauri dependency
    if cargo_toml_path:
        try:
            with open(cargo_toml_path, 'r', encoding='utf-8') as f:
                cargo_content = f.read()
            if 'tauri' in cargo_content:
                result["has_tauri_dependency"] = True
                # Extract tauri features
                import re
                features_match = re.search(
                    r'tauri\s*=.*features\s*=\s*\[([^\]]+)\]', cargo_content)
                if features_match:
                    result["tauri_features"] = [
                        f.strip().strip('"').strip("'")
                        for f in features_match.group(1).split(',')
                    ]
        except IOError:
            pass

    # Scan for IPC command handlers in Rust source
    if src_tauri_dir:
        src_dir = os.path.join(src_tauri_dir, 'src')
        if os.path.isdir(src_dir):
            import re
            for root, dirs, files in os.walk(src_dir):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS]
                for fname in files:
                    if not fname.endswith('.rs'):
                        continue
                    fpath = os.path.join(root, fname)
                    content = safe_read_file(fpath)
                    if not content:
                        continue
                    # Find .invoke_handler() commands
                    for m in re.finditer(
                        r'#\[tauri::command\]\s*(?:\n\s*pub\s+async\s+fn|\n\s*pub\s+fn)\s+(\w+)',
                        content
                    ):
                        result["ipc_commands"].append({
                            "name": m.group(1),
                            "file": os.path.relpath(fpath, workspace),
                        })
                    # Find .generate_handler! macro calls
                    for m in re.finditer(
                        r'generate_handler!\[([^\]]+)\]', content
                    ):
                        handlers = [h.strip().strip(',') for h in m.group(1).split() if h.strip().strip(',')]
                        for h in handlers:
                            if h and not any(c["name"] == h for c in result["ipc_commands"]):
                                result["ipc_commands"].append({
                                    "name": h,
                                    "file": os.path.relpath(fpath, workspace),
                                    "from_macro": True,
                                })

    # Scan for capabilities/permissions
    if src_tauri_dir:
        caps_dir = os.path.join(src_tauri_dir, 'capabilities')
        if os.path.isdir(caps_dir):
            for fname in os.listdir(caps_dir):
                if fname.endswith('.json'):
                    try:
                        with open(os.path.join(caps_dir, fname), 'r', encoding='utf-8') as f:
                            cap = json.load(f)
                        result["capabilities"].append({
                            "file": fname,
                            "permissions": cap.get('permissions', []),
                        })
                    except (json.JSONDecodeError, IOError):
                        pass

    return result


def _binary_category(ext: str) -> str:
    """Map file extension to binary category."""
    if ext in {'.exe', '.dll', '.so', '.dylib', '.a', '.lib', '.o', '.obj',
               '.bundle', '.ko', '.wasm'}:
        return "compiled_binary"
    if ext in {'.pyc', '.pyo', '.class'}:
        return "python_bytecode"
    if ext in {'.jar', '.war', '.nupkg', '.whl', '.egg'}:
        return "package_archive"
    if ext in {'.tar.gz', '.zip', '.7z', '.gz', '.rpm', '.deb', '.msi', '.dmg', '.pkg'}:
        return "archive"
    if ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.svg', '.bmp'}:
        return "image"
    return "other_binary"


def _read_file_signature(file_path: str) -> Optional[bytes]:
    """Read the first few bytes of a file for signature detection."""
    try:
        fsize = os.path.getsize(file_path)
        if fsize == 0 or fsize > 100 * 1024 * 1024:  # Skip empty or >100MB
            return None
        with open(file_path, 'rb') as f:
            return f.read(16)
    except (IOError, OSError):
        return None


def _identify_signature(sig: bytes) -> Optional[str]:
    """Identify file type from its binary signature."""
    for magic, file_type in BINARY_MIME_SIGNATURES.items():
        if sig.startswith(magic):
            return file_type
    return None


# ─── Generated File Detection ──────────────────────────────

GENERATED_FILE_PATTERNS = [
    re.compile(r'(^|/)generated/', re.IGNORECASE),
    re.compile(r'(^|/)gen-', re.IGNORECASE),
    re.compile(r'\.generated\.', re.IGNORECASE),
    re.compile(r'(^|/)auto_', re.IGNORECASE),
    re.compile(r'(^|/)autogenerated/', re.IGNORECASE),
    re.compile(r'^# (auto[- ]?generated|DO NOT EDIT|generated.*do not modify)', re.IGNORECASE),
    re.compile(r'^// (auto[- ]?generated|DO NOT EDIT|generated.*do not modify)', re.IGNORECASE),
    re.compile(r'(^|/)vendor/', re.IGNORECASE),
    re.compile(r'(^|/)third_party/', re.IGNORECASE),
    re.compile(r'(^|/)\.pb\.', re.IGNORECASE),      # protobuf generated
    re.compile(r'(^|/)_pb2\.py$', re.IGNORECASE),    # protobuf Python
    re.compile(r'(^|/)_pb\.rs$', re.IGNORECASE),     # protobuf Rust
    re.compile(r'\.min\.(js|css)$', re.IGNORECASE),
    re.compile(r'(^|/)dist/', re.IGNORECASE),
    re.compile(r'(^|/)build/', re.IGNORECASE),
    re.compile(r'\.d\.ts$', re.IGNORECASE),           # TypeScript declarations
]


def is_generated_file(file_path: str, content: Optional[str] = None) -> bool:
    """Check if a file is auto-generated and should be skipped for analysis.

    Detection strategies:
    1. Path patterns (generated/, vendor/, .pb., etc.)
    2. First-line comment markers (DO NOT EDIT, auto-generated, etc.)
    3. File extension patterns (.min.js, .d.ts, _pb2.py)

    Args:
        file_path: Relative or absolute file path
        content: Optional file content to check first-line markers

    Returns:
        True if the file appears to be auto-generated.
    """
    # Normalize to forward slashes
    normalized = file_path.replace('\\', '/')

    for pattern in GENERATED_FILE_PATTERNS:
        if pattern.search(normalized):
            return True

    # Check first few lines for generated markers
    if content:
        for line in content.split('\n')[:5]:
            stripped = line.strip()
            if not stripped:
                continue
            # Check common generated file headers
            lower = stripped.lower()
            if any(marker in lower for marker in [
                'auto-generated', 'autogenerated', 'do not edit',
                'generated by', 'do not modify', 'code generated',
                'this file is generated', 'this file was auto-generated',
            ]):
                return True
            break  # Only check first non-empty line

    return False


# ─── Tauri Artifact Scanning ──────────────────────────────

def scan_tauri_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for Tauri-specific artifacts and configuration.

    Detects Tauri app configuration, capabilities, and built artifacts
    in a Tauri project.

    Args:
        workspace: Absolute path to workspace

    Returns:
        Dict with Tauri project info and findings.
    """
    workspace = os.path.abspath(workspace)
    findings = []
    has_tauri = False
    tauri_config = None

    # Check for tauri.conf.json or Tauri.toml
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue
        for f in files:
            if f in ('tauri.conf.json', 'Tauri.toml'):
                has_tauri = True
                config_path = os.path.join(root, f)
                rel_path = os.path.relpath(config_path, workspace)
                findings.append({
                    "path": rel_path,
                    "type": "tauri_config",
                    "description": "Tauri application configuration file"
                })
                # Try to parse the config
                if f == 'tauri.conf.json':
                    try:
                        with open(config_path, 'r', encoding='utf-8') as fh:
                            tauri_config = json.load(fh)
                    except (json.JSONDecodeError, IOError):
                        pass
                break
        if has_tauri:
            break

    # Check for src-tauri directory
    src_tauri = os.path.join(workspace, 'src-tauri')
    if os.path.isdir(src_tauri):
        has_tauri = True
        # Walk src-tauri for Rust source files and capabilities
        for root, dirs, files in os.walk(src_tauri):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
            for f in files:
                if f.endswith('.rs'):
                    rel = os.path.relpath(os.path.join(root, f), workspace)
                    findings.append({
                        "path": rel,
                        "type": "tauri_rust_source",
                        "description": "Tauri Rust backend source file"
                    })
                elif f in ('capabilities.json', 'default.conf'):
                    rel = os.path.relpath(os.path.join(root, f), workspace)
                    findings.append({
                        "path": rel,
                        "type": "tauri_capability",
                        "description": "Tauri security capability configuration"
                    })

    return {
        "status": "ok",
        "workspace": workspace,
        "is_tauri_project": has_tauri,
        "config": tauri_config,
        "artifacts_found": len(findings),
        "findings": findings,
    }


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "6.1.0"
