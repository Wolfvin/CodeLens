"""Shared utilities for CodeLens."""

import os
import json
import logging
import re
import struct
import time
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

CODELENS_VERSION = "5.7.1"

# ─── Shared Limits ───────────────────────────────────────────

MAX_FILE_SIZE = 500 * 1024  # 500KB — skip files larger than this
MAX_FILES_DEFAULT = 3000    # Default max files to scan per engine


def time_budget_expired(start_time: float, budget_sec: float) -> bool:
    """Check if the time budget has expired.

    Args:
        start_time: Start time from time.time().
        budget_sec: Budget in seconds.

    Returns:
        True if the budget has been exceeded.
    """
    import time
    return (time.time() - start_time) > budget_sec


def is_generated_file(filename: str) -> bool:
    """Check if a file is a generated/lock file that should be skipped.

    Covers lock files, generated output, and vendored artifacts.

    Args:
        filename: Just the filename (not the full path).

    Returns:
        True if the file should be skipped as generated.
    """
    generated_patterns = (
        # Lock files
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml', 'bun.lockb',
        'cargo.lock', 'gemfile.lock', 'composer.lock', 'poetry.lock',
        'pdm.lock', 'uv.lock',
        # Generated files
        'go.sum', 'mix.lock', 'conan.lock', 'pip-wheel-metadata',
        # Minified / bundled
        '.min.js', '.min.css', '.bundle.js', '.chunk.js',
    )
    fl = filename.lower()
    for pattern in generated_patterns:
        if fl.endswith(pattern) or fl == pattern:
            return True
    # Auto-generated suffixes
    if fl.endswith('.generated.ts') or fl.endswith('.generated.js'):
        return True
    if fl.endswith('.g.dart') or fl.endswith('.g.py'):
        return True
    if fl.endswith('.pb.go') or fl.endswith('_pb2.py'):
        return True
    # snapshot files
    if fl.endswith('.snap') or fl.endswith('.snapshot'):
        return True
    return False


# ─── Binary Artifact Scanning ────────────────────────────────

_BINARY_EXTENSIONS = frozenset({
    '.so', '.dylib', '.dll', '.exe', '.bin', '.o', '.obj',
    '.wasm', '.pyc', '.pyo', '.class', '.jar', '.war',
    '.node', '.efi', '.app', '.dmg', '.iso', '.msi',
    '.nupkg', '.deb', '.rpm', '.apk', '.aab',
})

_ELECTRON_MARKERS = frozenset({
    'electron', 'electron.exe', 'Electron Framework.framework',
})

_TAURI_CONFIG_FILES = frozenset({
    'tauri.conf.json', 'tauri.conf.json5', 'tauri.config.json',
})


def scan_binary_artifacts(workspace: str) -> Dict[str, Any]:
    """Scan workspace for binary/compiled artifacts with RE analysis.

    Detects shared libraries, executables, WASM modules, and other
    compiled files. For each artifact, extracts:
    - File size and type classification
    - PE/Mach-O/ELF header info (platform, architecture)
    - Whether it's likely a Tauri/Electron app based on binary signatures

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with findings, stats, and recommendations.
    """
    workspace = os.path.abspath(workspace)
    artifacts = []
    total_size = 0
    electron_detected = False
    artifacts_by_type: Dict[str, int] = {}

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in _BINARY_EXTENSIONS:
                path = os.path.join(root, fn)
                rel_path = os.path.relpath(path, workspace)
                try:
                    size = os.path.getsize(path)
                    total_size += size

                    # Classify artifact type
                    artifact_type = _classify_binary(ext)
                    artifacts_by_type[artifact_type] = artifacts_by_type.get(artifact_type, 0) + 1

                    # Extract binary header metadata
                    metadata = _extract_binary_metadata(path, ext)

                    # Detect Tauri/Electron framework signatures
                    app_framework = _detect_app_framework(path, ext, metadata)
                    if app_framework == "electron":
                        electron_detected = True

                    artifact_info = {
                        "file": rel_path,
                        "type": artifact_type,
                        "extension": ext,
                        "size_bytes": size,
                        "size_human": _human_readable_size(size),
                        "platform": metadata.get("platform", "unknown"),
                        "architecture": metadata.get("architecture", "unknown"),
                        "app_framework": app_framework,
                    }

                    if metadata.get("sections"):
                        artifact_info["sections_count"] = len(metadata["sections"])

                    artifacts.append(artifact_info)
                except OSError:
                    pass

            # Detect Electron markers
            if fn.lower() in _ELECTRON_MARKERS:
                electron_detected = True

    return {
        "status": "ok",
        "workspace": workspace,
        "total_artifacts": len(artifacts),
        "total_size_bytes": total_size,
        "total_size_human": _human_readable_size(total_size),
        "artifacts_by_type": artifacts_by_type,
        "electron_detected": electron_detected,
        "artifacts": artifacts[:200],
        "recommendation": (
            "Consider adding binary files to .gitignore to keep the repo clean."
            if artifacts else "No binary artifacts found in source directories."
        ),
    }


def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Scan workspace for Tauri-specific artifacts and configuration.

    Detects and analyzes:
    - tauri.conf.json configuration (app identity, window settings, security)
    - Tauri capabilities/permissions (filesystem, shell, http, etc.)
    - Tauri IPC command definitions (#[tauri::command] handlers)
    - Sidecar binary configuration
    - Updater configuration and security
    - WebView security settings (CSP, asset protocol)
    - Build configuration (targets, bundler settings)
    - Deep-link/custom protocol schemes
    - Security risk assessment

    Args:
        workspace: Absolute path to workspace.

    Returns:
        Dict with Tauri analysis, or None if not a Tauri project.
    """
    workspace = os.path.abspath(workspace)

    # Find all tauri config files
    tauri_config_paths = []
    is_tauri = False

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if fn in _TAURI_CONFIG_FILES:
                is_tauri = True
                tauri_config_paths.append(os.path.join(root, fn))

    # Also check Cargo.toml for tauri dependency
    if not is_tauri:
        cargo_path = os.path.join(workspace, 'Cargo.toml')
        if os.path.isfile(cargo_path):
            try:
                with open(cargo_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if 'tauri' in content.lower():
                    is_tauri = True
            except IOError:
                pass

    if not is_tauri:
        return None

    result: Dict[str, Any] = {
        "is_tauri_project": True,
        "config_files": tauri_config_paths,
        "app_identity": {},
        "capabilities": [],
        "ipc_commands": [],
        "sidecars": [],
        "updater": {},
        "webview_security": {},
        "build_config": {},
        "deep_links": [],
    }

    for conf_path in tauri_config_paths:
        config_data = _parse_json_file(conf_path)
        if config_data:
            result["app_identity"] = _extract_tauri_identity(config_data)
            result["build_config"] = _extract_tauri_build_config(config_data)
            result["updater"] = _extract_tauri_updater(config_data)
            result["webview_security"] = _extract_tauri_webview_security(config_data)
            result["deep_links"] = _extract_tauri_deep_links(config_data)
            result["sidecars"] = _extract_tauri_sidecars(config_data)

    # Scan for capabilities
    result["capabilities"] = _scan_tauri_capabilities(workspace)

    # Scan for IPC command definitions in Rust source
    result["ipc_commands"] = _scan_tauri_ipc_commands(workspace)

    # Compute security summary
    result["security_summary"] = _compute_tauri_security_summary(result)

    return result


# ─── Binary & Tauri Helper Functions ────────────────────────

def _parse_json_file(path: str) -> Optional[Dict]:
    """Parse a JSON file safely."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def _classify_binary(ext: str) -> str:
    """Classify a binary file by its extension."""
    classification = {
        '.exe': 'executable', '.dll': 'shared_library', '.so': 'shared_library',
        '.dylib': 'shared_library', '.a': 'static_library', '.o': 'object_file',
        '.obj': 'object_file', '.wasm': 'webassembly', '.pyc': 'python_compiled',
        '.pyo': 'python_compiled', '.class': 'java_compiled', '.jar': 'java_archive',
        '.war': 'java_archive', '.node': 'native_addon', '.efi': 'firmware',
        '.app': 'application_bundle', '.dmg': 'installer', '.iso': 'disk_image',
        '.msi': 'installer', '.nupkg': 'nuget_package', '.deb': 'package',
        '.rpm': 'package', '.apk': 'android_package', '.aab': 'android_bundle',
        '.bin': 'raw_binary',
    }
    return classification.get(ext, 'unknown_binary')


def _extract_binary_metadata(file_path: str, ext: str) -> Dict[str, Any]:
    """Extract metadata from binary file headers (PE, ELF, Mach-O, WASM)."""
    metadata: Dict[str, Any] = {}
    try:
        with open(file_path, 'rb') as f:
            header = f.read(512)
            if len(header) < 4:
                return metadata

            # PE format (Windows .exe, .dll)
            if header[:2] == b'MZ':
                metadata["platform"] = "windows"
                metadata["format"] = "PE"
                try:
                    pe_offset = struct.unpack_from('<I', header, 0x3C)[0]
                    if pe_offset < len(header) - 4 and header[pe_offset:pe_offset+4] == b'PE\x00\x00':
                        machine = struct.unpack_from('<H', header, pe_offset + 4)[0]
                        arch_map = {0x14c: "x86", 0x8664: "x86_64", 0xaa64: "arm64", 0x1c0: "arm"}
                        metadata["architecture"] = arch_map.get(machine, f"unknown(0x{machine:x})")
                        num_sections = struct.unpack_from('<H', header, pe_offset + 6)[0]
                        metadata["sections"] = [{"index": i} for i in range(min(num_sections, 50))]
                except (struct.error, IndexError):
                    pass

            # ELF format (Linux)
            elif header[:4] == b'\x7fELF':
                metadata["format"] = "ELF"
                ei_class = header[4]
                metadata["platform"] = "linux"
                metadata["architecture"] = {1: "x86", 2: "x86_64"}.get(ei_class, "unknown")
                if len(header) >= 20:
                    e_machine = struct.unpack_from('<H', header, 18)[0]
                    machine_map = {0x03: "x86", 0x3E: "x86_64", 0xB7: "arm64", 0x28: "arm", 0xF3: "riscv"}
                    if e_machine in machine_map:
                        metadata["architecture"] = machine_map[e_machine]

            # Mach-O format (macOS)
            elif header[:4] in (b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf',
                                b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe'):
                metadata["format"] = "Mach-O"
                metadata["platform"] = "macos"
                magic = struct.unpack_from('<I', header, 0)[0]
                if magic in (0xfeedface, 0xcefaedfe):
                    metadata["architecture"] = "x86"
                elif magic in (0xfeedfacf, 0xcffaedfe):
                    metadata["architecture"] = "x86_64"

            # WASM
            elif header[:4] == b'\x00asm':
                metadata["format"] = "WASM"
                metadata["platform"] = "web"
                metadata["architecture"] = "wasm"

    except (IOError, OSError):
        pass
    return metadata


def _detect_app_framework(file_path: str, ext: str, metadata: Dict) -> Optional[str]:
    """Detect if a binary is a Tauri or Electron application by scanning for signatures."""
    if ext not in ('.exe', '.dll', '.so', '.dylib', '.app', '.bin'):
        return None
    try:
        with open(file_path, 'rb') as f:
            chunk_size = min(os.path.getsize(file_path), 2 * 1024 * 1024)
            data = f.read(chunk_size)
            text = data.decode('ascii', errors='ignore')
            has_tauri = 'tauri' in text.lower()
            has_webview2 = 'webview2' in text.lower() or 'WebView2' in text
            has_electron = 'electron' in text.lower() or 'chrome.dll' in text.lower()
            has_node = 'node.dll' in text.lower() or 'libnode' in text.lower()
            if has_tauri:
                return "tauri"
            if has_electron or has_node:
                return "electron"
    except (IOError, OSError):
        pass
    return None


def _human_readable_size(size_bytes: float) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _extract_tauri_identity(conf: Dict) -> Dict[str, Any]:
    """Extract app identity from Tauri configuration."""
    return {
        "name": conf.get("productName", conf.get("name", "unknown")),
        "version": conf.get("version", "unknown"),
        "identifier": conf.get("identifier", ""),
    }


def _extract_tauri_build_config(conf: Dict) -> Dict[str, Any]:
    """Extract build configuration from Tauri configuration."""
    build = conf.get("build", {})
    bundle = conf.get("bundle", {})
    return {
        "dev_path": build.get("devPath", build.get("devUrl", "")),
        "dist_dir": build.get("distDir", build.get("frontendDist", "")),
        "before_dev_command": build.get("beforeDevCommand", ""),
        "before_build_command": build.get("beforeBuildCommand", ""),
        "targets": bundle.get("targets", []),
        "external_bin": bundle.get("externalBin", []),
    }


def _extract_tauri_updater(conf: Dict) -> Dict[str, Any]:
    """Extract updater configuration from Tauri configuration."""
    updater = conf.get("updater", {})
    if not updater:
        plugins = conf.get("plugins", {})
        updater = plugins.get("updater", {})
    if not updater:
        return {"enabled": False}
    return {
        "enabled": updater.get("active", updater.get("enabled", False)),
        "endpoints": updater.get("endpoints", []),
        "pubkey": bool(updater.get("pubkey", "")),
    }


def _extract_tauri_webview_security(conf: Dict) -> Dict[str, Any]:
    """Extract WebView security settings from Tauri configuration."""
    security = conf.get("security", {})
    if not security:
        app = conf.get("app", {})
        security = app.get("security", {})
    if not security:
        tauri = conf.get("tauri", {})
        security = tauri.get("security", {})
    return {
        "csp": security.get("csp", None),
        "dangerous_disable_asset_csp_modification": security.get(
            "dangerousDisableAssetCspModification",
            security.get("dangerous_disable_asset_csp_modification", False)
        ),
    }


def _extract_tauri_deep_links(conf: Dict) -> List[Dict[str, Any]]:
    """Extract deep-link/custom protocol schemes from Tauri configuration."""
    deep_links = []
    plugins = conf.get("plugins", {})
    deep_link_config = plugins.get("deep-link", {})
    if deep_link_config:
        for scheme in deep_link_config.get("schemes", []):
            deep_links.append({
                "scheme": scheme if isinstance(scheme, str) else scheme.get("scheme", ""),
                "source": "plugins.deep-link",
            })
    tauri = conf.get("tauri", {})
    protocol = tauri.get("bundle", {}).get("protocol", {})
    if protocol:
        scheme = protocol.get("scheme", "")
        if scheme:
            deep_links.append({"scheme": scheme, "source": "tauri.bundle.protocol"})
    return deep_links


def _extract_tauri_sidecars(conf: Dict) -> List[Dict[str, Any]]:
    """Extract sidecar binary configurations from Tauri configuration."""
    sidecars = []
    tauri = conf.get("tauri", {})
    external_bin = tauri.get("bundle", {}).get("externalBin", conf.get("bundle", {}).get("externalBin", []))
    for sb in external_bin:
        if isinstance(sb, str):
            sidecars.append({"name": sb, "source": "bundle.externalBin"})
    return sidecars


def _scan_tauri_capabilities(workspace: str) -> List[Dict[str, Any]]:
    """Scan for Tauri capability/permission definitions."""
    capabilities = []
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if os.path.basename(root) == 'capabilities':
            for filename in filenames:
                if filename.endswith('.json'):
                    file_path = os.path.join(root, filename)
                    cap_data = _parse_json_file(file_path)
                    if cap_data:
                        permissions = cap_data.get("permissions", [])
                        capabilities.append({
                            "file": os.path.relpath(file_path, workspace),
                            "identifier": cap_data.get("identifier", ""),
                            "description": cap_data.get("description", ""),
                            "windows": cap_data.get("windows", []),
                            "permissions": permissions,
                            "permission_count": len(permissions),
                            "permission_categories": _classify_permissions(permissions),
                        })
    return capabilities


def _classify_permissions(permissions: List) -> Dict[str, List[str]]:
    """Classify Tauri permissions by security category."""
    categories: Dict[str, List[str]] = {
        "filesystem": [], "shell": [], "http": [], "window": [],
        "notification": [], "clipboard": [], "global_shortcut": [], "other": [],
    }
    for perm in permissions:
        if isinstance(perm, str):
            perm_str = perm.lower()
            if any(k in perm_str for k in ('fs', 'file', 'path', 'directory')):
                categories["filesystem"].append(perm)
            elif any(k in perm_str for k in ('shell', 'execute', 'process')):
                categories["shell"].append(perm)
            elif any(k in perm_str for k in ('http', 'request', 'fetch')):
                categories["http"].append(perm)
            elif any(k in perm_str for k in ('window', 'webview')):
                categories["window"].append(perm)
            elif 'notif' in perm_str:
                categories["notification"].append(perm)
            elif 'clip' in perm_str:
                categories["clipboard"].append(perm)
            elif any(k in perm_str for k in ('shortcut', 'global')):
                categories["global_shortcut"].append(perm)
            else:
                categories["other"].append(perm)
        elif isinstance(perm, dict):
            categories["other"].append(perm.get("identifier", ""))
    return {k: v for k, v in categories.items() if v}


def _scan_tauri_ipc_commands(workspace: str) -> List[Dict[str, Any]]:
    """Scan Rust source files for Tauri IPC command definitions."""
    commands = []
    tauri_cmd_pattern = re.compile(
        r'#\[tauri::command\s*(?:\([^)]*\))?\s*\]'
        r'(?:\s*#\[[^\]]*\])*'
        r'\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)',
        re.MULTILINE
    )
    invoke_handler_pattern = re.compile(
        r'\.invoke_handler\s*\(\s*tauri::generate_handler\s*!\s*\[([^\]]+)\]',
        re.DOTALL
    )
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        for fn in filenames:
            if not fn.endswith('.rs'):
                continue
            path = os.path.join(root, fn)
            content = safe_read_file(path)
            if content is None:
                continue
            for m in tauri_cmd_pattern.finditer(content):
                fn_name = m.group(1)
                line_num = content[:m.start()].count('\n') + 1
                parts = fn_name.split('_')
                cmd_name = parts[0] + ''.join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else fn_name
                commands.append({
                    "rust_fn": fn_name,
                    "ipc_command": cmd_name,
                    "file": os.path.relpath(path, workspace),
                    "line": line_num,
                    "invoke_syntax": f"invoke('{cmd_name}')",
                })
            for m in invoke_handler_pattern.finditer(content):
                for cmd_match in re.finditer(r'(\w+::)*(\w+)', m.group(1)):
                    cmd_name = cmd_match.group(2)
                    if cmd_name in ('tauri', 'generate_handler', 'Box', 'Fn'):
                        continue
                    if not any(c.get("rust_fn") == cmd_name for c in commands):
                        parts = cmd_name.split('_')
                        ipc_name = parts[0] + ''.join(p.capitalize() for p in parts[1:]) if len(parts) > 1 else cmd_name
                        commands.append({
                            "rust_fn": cmd_name,
                            "ipc_command": ipc_name,
                            "file": os.path.relpath(path, workspace),
                            "line": content[:m.start()].count('\n') + 1,
                            "invoke_syntax": f"invoke('{ipc_name}')",
                            "registered_in": "generate_handler!",
                        })
    return commands


def _compute_tauri_security_summary(analysis: Dict) -> Dict[str, Any]:
    """Compute a security summary from Tauri analysis results."""
    concerns: List[Dict[str, str]] = []
    risk_level = "low"
    for cap in analysis.get("capabilities", []):
        categories = cap.get("permission_categories", {})
        if categories.get("shell"):
            concerns.append({
                "category": "shell_access", "severity": "high",
                "detail": f"Shell execution permission in {cap['file']}: {', '.join(categories['shell'][:5])}",
            })
            risk_level = "high"
        if categories.get("filesystem"):
            concerns.append({
                "category": "filesystem_access", "severity": "medium",
                "detail": f"Filesystem permission in {cap['file']}: {len(categories['filesystem'])} permissions",
            })
            if risk_level == "low":
                risk_level = "medium"
    webview = analysis.get("webview_security", {})
    if webview.get("dangerous_disable_asset_csp_modification"):
        concerns.append({"category": "csp_bypass", "severity": "high",
                        "detail": "CSP modification is disabled — potential security risk"})
        risk_level = "high"
    if not webview.get("csp"):
        concerns.append({"category": "missing_csp", "severity": "medium",
                        "detail": "No Content Security Policy (CSP) configured"})
        if risk_level == "low":
            risk_level = "medium"
    updater = analysis.get("updater", {})
    if updater.get("enabled") and not updater.get("pubkey"):
        concerns.append({"category": "insecure_updater", "severity": "high",
                        "detail": "Updater is enabled without public key — susceptible to MITM attacks"})
        risk_level = "high"
    sidecars = analysis.get("sidecars", [])
    if sidecars:
        concerns.append({"category": "sidecar_binaries", "severity": "medium",
                        "detail": f"{len(sidecars)} sidecar binary(ies) bundled — verify their security"})
        if risk_level == "low":
            risk_level = "medium"
    return {"risk_level": risk_level, "concern_count": len(concerns), "concerns": concerns}


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
