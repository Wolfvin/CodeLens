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

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
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


# ─── Version ────────────────────────────────────────────────

CODELENS_VERSION = "6.4.1"


# ─── Generated File Detection ───────────────────────────────

GENERATED_FILE_PATTERNS = frozenset({
    # Lock files
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lock',
    'Cargo.lock', 'Gemfile.lock', 'poetry.lock', 'uv.lock',
    'composer.lock', 'mix.lock', 'Podfile.lock',
    # Generated/build output
    '.d.ts',  # TypeScript declaration files (auto-generated)
})


def is_generated_file(filename: str) -> bool:
    """Check if a filename looks like a generated or lock file that should be skipped.

    Matches lock files, declaration files, and other auto-generated artifacts
    that are not meaningful for code analysis.

    Args:
        filename: Just the filename (not the full path), e.g. 'Cargo.lock'

    Returns:
        True if the file appears to be generated/lock file.
    """
    lower = filename.lower()
    # Check exact filename matches (lock files)
    if lower in GENERATED_FILE_PATTERNS:
        return True
    # Check extension-based patterns
    if lower.endswith('.d.ts') or lower.endswith('.d.ts.map'):
        return True
    if lower.endswith('.min.js') or lower.endswith('.min.css'):
        return True
    if lower.endswith('.bundle.js') or lower.endswith('.chunk.js'):
        return True
    if lower.endswith('.lock') or lower.endswith('.lock.yml') or lower.endswith('.lock.yaml'):
        return True
    return False


# ─── Bundled File Detection ──────────────────────────────────

BUNDLED_FILE_PATTERNS = (
    '.min.js', '.min.css',       # Minified JS/CSS
    '.bundle.js', '.chunk.js',   # Webpack/Vite bundles
    '.vendor.js',                # Vendor bundles
    '.global.js', '.global.css', # Global bundles (e.g. Ant Design)
    '.pack.js',                  # Packaged bundles
    '.esm.js',                   # ESM bundles (often built)
)

BUNDLED_DIR_SEGMENTS = frozenset({
    'dist', 'build', 'out', 'bundle', 'bundles',
    '.output', '.nuxt', '.next', '.cache',
})


def is_bundled_file(rel_path: str) -> bool:
    """Check if a file is a bundled/compiled artifact that should be skipped.

    Bundled files are build output (minified JS/CSS, vendor bundles, etc.)
    that are not original source code and should not be analyzed for
    quality, complexity, or code smells.

    Args:
        rel_path: Relative file path from workspace root.

    Returns:
        True if the file appears to be a bundled/compiled artifact.
    """
    lower = rel_path.lower()

    # Check file extension patterns
    for pattern in BUNDLED_FILE_PATTERNS:
        if lower.endswith(pattern):
            return True

    # Check if file is in a bundled output directory
    parts = lower.replace('\\', '/').split('/')
    for segment in parts:
        if segment in BUNDLED_DIR_SEGMENTS:
            return True

    # Check for source maps
    if lower.endswith('.map') and (lower.endswith('.js.map') or lower.endswith('.css.map')):
        return True

    # Check for common bundle filename patterns
    filename = parts[-1] if parts else ''
    if filename.startswith('vendor') and filename.endswith('.js'):
        return True
    if filename.startswith('polyfill') and filename.endswith('.js'):
        return True
    # Webpack chunk pattern: [name].[hash].js or [name].[hash].css
    import re
    if re.match(r'.+\.[a-f0-9]{8,}\.(js|css)$', filename):
        return True

    return False
