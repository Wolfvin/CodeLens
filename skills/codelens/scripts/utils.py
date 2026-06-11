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

# Generated/lock files that should be excluded from analysis engines
# (refactor-safe, smell, dead-code, etc.) but NOT from file walking.
# These are committed but not human-written source code.
GENERATED_FILE_PATTERNS = frozenset({
    'Cargo.lock', 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    'bun.lock', 'bun.lockb', 'go.sum', 'poetry.lock', 'uv.lock',
    'Gemfile.lock', 'composer.lock', 'pip-wheel-metadata',
    '.pnp.cjs', '.pnp.js',
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


def is_generated_file(file_path: str) -> bool:
    """Check if a file is a generated/lock file that should be excluded from analysis.

    These files (Cargo.lock, package-lock.json, etc.) are committed to VCS
    but are not human-written source code. Analysis engines like refactor-safe,
    smell, and dead-code should skip them.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        True if the file is a generated/lock file, False otherwise.
    """
    basename = os.path.basename(file_path)
    return basename in GENERATED_FILE_PATTERNS


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

CODELENS_VERSION = "5.7.1"


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


# ─── Tauri Reverse Engineering Analysis ──────────────────────────

def scan_tauri_artifacts(workspace: str) -> Optional[Dict[str, Any]]:
    """Perform deep Tauri reverse engineering analysis on a workspace.

    Analyzes:
    - Tauri configuration (tauri.conf.json) for build & security settings
    - IPC commands/handlers registered in Rust source
    - Capabilities/permissions security audit
    - Sidecar binary references
    - Updater configuration (endpoints, signing keys)
    - WebView security (CSP, asset protocol scope)
    - Deep-link schemes
    - Build scripts (build.rs) analysis
    - Tauri plugins usage

    Args:
        workspace: Absolute path to workspace

    Returns:
        Dict with Tauri RE findings, or None if not a Tauri project
    """
    workspace = os.path.abspath(workspace)

    # Find tauri.conf.json — could be at src-tauri/ or in monorepo sub-dirs
    tauri_conf_paths = _find_tauri_configs(workspace)
    if not tauri_conf_paths:
        return None

    analysis: Dict[str, Any] = {
        'configs_analyzed': len(tauri_conf_paths),
        'ipc_commands': [],
        'capabilities': [],
        'sidecars': [],
        'updater': None,
        'webview_security': None,
        'deep_links': [],
        'build_scripts': [],
        'plugins': [],
        'security_audit': [],
    }

    for conf_path in tauri_conf_paths:
        conf_dir = os.path.dirname(conf_path)
        rel_conf = os.path.relpath(conf_path, workspace)

        # ─── Parse tauri.conf.json ───
        try:
            with open(conf_path, 'r', encoding='utf-8') as f:
                conf = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            analysis['security_audit'].append({
                'severity': 'warning',
                'category': 'config_parse_error',
                'message': f"Cannot parse {rel_conf}: {e}",
            })
            continue

        # ─── App identity ───
        product_name = conf.get('productName', 'unknown')
        identifier = conf.get('identifier', 'unknown')
        version = conf.get('version', 'unknown')

        # ─── Sidecar binaries ───
        bundle = conf.get('bundle', {})
        external_bin = bundle.get('externalBin', [])
        if external_bin:
            for sidecar in external_bin:
                sidecar_info = {
                    'name': sidecar,
                    'config': rel_conf,
                    'risk': 'medium',
                    'note': 'Sidecar binaries run alongside the app with full system access',
                }
                # Check if sidecar source exists
                sidecar_src_dir = os.path.join(conf_dir, 'src', 'bin')
                if not os.path.isdir(sidecar_src_dir):
                    sidecar_info['note'] += '. No source found — likely proprietary/closed-source binary'
                    sidecar_info['risk'] = 'high'
                analysis['sidecars'].append(sidecar_info)

                # Security audit
                analysis['security_audit'].append({
                    'severity': 'medium',
                    'category': 'sidecar_binary',
                    'message': f"Sidecar binary '{sidecar}' runs with full system access. "
                               f"Verify it is from a trusted source and properly signed.",
                    'file': rel_conf,
                })

        # ─── Updater configuration ───
        plugins = conf.get('plugins', {})
        updater = plugins.get('updater', None)
        if updater:
            updater_info = {
                'enabled': True,
                'pubkey': updater.get('pubkey', ''),
                'endpoints': updater.get('endpoints', []),
                'install_mode': updater.get('windows', {}).get('installMode', 'unknown'),
            }
            analysis['updater'] = updater_info

            # Audit: updater endpoints
            endpoints = updater.get('endpoints', [])
            for ep in endpoints:
                if 'http://' in ep and 'https://' not in ep:
                    analysis['security_audit'].append({
                        'severity': 'critical',
                        'category': 'insecure_updater',
                        'message': f"Updater endpoint uses insecure HTTP: {ep}. "
                                   f"This allows MITM attacks to deliver malicious updates.",
                        'file': rel_conf,
                    })

            # Audit: pubkey present?
            if not updater.get('pubkey'):
                analysis['security_audit'].append({
                    'severity': 'critical',
                    'category': 'unsigned_updates',
                    'message': "Updater has no public key configured. Updates cannot be verified.",
                    'file': rel_conf,
                })
            else:
                analysis['security_audit'].append({
                    'severity': 'info',
                    'category': 'signed_updates',
                    'message': f"Updater uses signed updates (pubkey length: {len(updater['pubkey'])} chars).",
                    'file': rel_conf,
                })

        # ─── Deep-link schemes ───
        deep_link = plugins.get('deep-link', None)
        if deep_link:
            desktop = deep_link.get('desktop', {})
            schemes = desktop.get('schemes', [])
            for scheme in schemes:
                analysis['deep_links'].append({
                    'scheme': scheme,
                    'config': rel_conf,
                })
                analysis['security_audit'].append({
                    'severity': 'info',
                    'category': 'deep_link',
                    'message': f"Deep-link scheme '{scheme}://' registered. "
                               f"Ensure handlers validate input to prevent URL-scheme injection.",
                    'file': rel_conf,
                })

        # ─── WebView security ───
        app_conf = conf.get('app', {})
        security = app_conf.get('security', {})
        if security:
            wv_security = {
                'csp': security.get('csp'),
                'asset_protocol_enabled': security.get('assetProtocol', {}).get('enable', False),
                'asset_protocol_scope': security.get('assetProtocol', {}).get('scope', {}),
                'capabilities': security.get('capabilities', []),
            }
            analysis['webview_security'] = wv_security

            # Audit: CSP null/missing
            csp = security.get('csp')
            if csp is None:
                analysis['security_audit'].append({
                    'severity': 'high',
                    'category': 'missing_csp',
                    'message': "Content Security Policy (CSP) is not set (null). "
                               "The webview can load any external resources, increasing XSS risk.",
                    'file': rel_conf,
                })

            # Audit: asset protocol with wildcard scope
            asset_proto = security.get('assetProtocol', {})
            if asset_proto.get('enable'):
                scope_allow = asset_proto.get('scope', {}).get('allow', [])
                if '**' in str(scope_allow) or '*' in str(scope_allow):
                    analysis['security_audit'].append({
                        'severity': 'high',
                        'category': 'permissive_asset_protocol',
                        'message': "Asset protocol enabled with wildcard scope (**). "
                                   "Allows reading any file on the system from the webview.",
                        'file': rel_conf,
                    })

        # ─── Build configuration ───
        build_conf = conf.get('build', {})
        if build_conf.get('removeUnusedCommands'):
            analysis['security_audit'].append({
                'severity': 'info',
                'category': 'tree_shaking',
                'message': "removeUnusedCommands is enabled — unused IPC commands are "
                           "stripped from production builds. Good for security.",
                'file': rel_conf,
            })

        # ─── Parse capabilities files ───
        caps_dir = os.path.join(conf_dir, 'capabilities')
        if os.path.isdir(caps_dir):
            for cap_file in sorted(os.listdir(caps_dir)):
                if not cap_file.endswith('.json'):
                    continue
                cap_path = os.path.join(caps_dir, cap_file)
                try:
                    with open(cap_path, 'r', encoding='utf-8') as f:
                        cap_data = json.load(f)
                    cap_entry = {
                        'identifier': cap_data.get('identifier', cap_file),
                        'file': os.path.relpath(cap_path, workspace),
                        'permissions': cap_data.get('permissions', []),
                        'platforms': cap_data.get('platforms', []),
                        'windows': cap_data.get('windows', []),
                    }
                    analysis['capabilities'].append(cap_entry)

                    # Security audit for dangerous permissions
                    perms = cap_data.get('permissions', [])
                    _audit_tauri_permissions(perms, os.path.relpath(cap_path, workspace), analysis['security_audit'])

                except (json.JSONDecodeError, IOError):
                    pass

        # ─── Scan Rust source for IPC command handlers ───
        src_dir = os.path.join(conf_dir, 'src')
        if os.path.isdir(src_dir):
            _scan_tauri_ipc_handlers(src_dir, workspace, analysis)

        # ─── Scan build.rs ───
        build_rs = os.path.join(conf_dir, 'build.rs')
        if os.path.isfile(build_rs):
            try:
                content = safe_read_file(build_rs)
                if content:
                    build_info = {
                        'file': os.path.relpath(build_rs, workspace),
                        'lines': content.count('\n') + 1,
                        'has_runtime_checks': 'println!' in content or 'cargo:' in content,
                    }
                    analysis['build_scripts'].append(build_info)

                    # Audit: dangerous build script patterns
                    if 'std::process::Command' in content or 'std::fs::' in content:
                        analysis['security_audit'].append({
                            'severity': 'info',
                            'category': 'build_script',
                            'message': f"Build script uses filesystem or process operations. "
                                       f"This runs during compilation with full system access.",
                            'file': os.path.relpath(build_rs, workspace),
                        })
            except (IOError, OSError):
                pass

    # ─── Summary ───
    total_ipc = len(analysis['ipc_commands'])
    total_perms = sum(len(c.get('permissions', [])) for c in analysis['capabilities'])
    total_findings = len(analysis['security_audit'])
    critical = sum(1 for f in analysis['security_audit'] if f.get('severity') == 'critical')
    high = sum(1 for f in analysis['security_audit'] if f.get('severity') == 'high')

    analysis['summary'] = {
        'ipc_commands_count': total_ipc,
        'capabilities_count': len(analysis['capabilities']),
        'total_permissions': total_perms,
        'sidecars_count': len(analysis['sidecars']),
        'deep_links_count': len(analysis['deep_links']),
        'security_findings': total_findings,
        'security_findings_by_severity': {
            'critical': critical,
            'high': high,
            'medium': sum(1 for f in analysis['security_audit'] if f.get('severity') == 'medium'),
            'info': sum(1 for f in analysis['security_audit'] if f.get('severity') == 'info'),
        },
        'risk_level': 'critical' if critical > 0 else ('high' if high > 0 else 'moderate'),
    }

    return analysis


def _find_tauri_configs(workspace: str) -> List[str]:
    """Find all tauri.conf.json files in the workspace."""
    results = []
    for root, dirs, files in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue
        if 'tauri.conf.json' in files:
            results.append(os.path.join(root, 'tauri.conf.json'))
    return results


# ─── Dangerous Tauri permission patterns ───
_DANGEROUS_PERMISSIONS = {
    'shell:allow-execute': {
        'severity': 'critical',
        'message': "Allows executing arbitrary system commands from the webview. "
                    "A compromised webview can run any command on the host.",
    },
    'shell:allow-spawn': {
        'severity': 'critical',
        'message': "Allows spawning new processes from the webview. "
                    "Similar risk to shell:allow-execute.",
    },
    'fs:allow-write-file': {
        'severity': 'high',
        'message': "Allows writing files from the webview. "
                    "A compromised webview can modify system files within scope.",
    },
    'fs:allow-read-file': {
        'severity': 'medium',
        'message': "Allows reading files from the webview. "
                    "Can leak sensitive data if scope is too permissive.",
    },
    'clipboard-manager:allow-read-text': {
        'severity': 'medium',
        'message': "Can read clipboard contents. May capture passwords or sensitive data.",
    },
    'http:allow-fetch': {
        'severity': 'medium',
        'message': "Allows HTTP requests from the webview. Can exfiltrate data to external servers.",
    },
    'process:allow-restart': {
        'severity': 'low',
        'message': "Can restart the application process.",
    },
    'process:allow-exit': {
        'severity': 'low',
        'message': "Can exit the application process.",
    },
}


def _audit_tauri_permissions(perms: list, source_file: str, audit_list: list) -> None:
    """Audit Tauri permissions for security-relevant patterns."""
    for perm in perms:
        # Handle both string permissions and object permissions
        perm_str = perm if isinstance(perm, str) else perm.get('identifier', str(perm))

        # Check against known dangerous permissions
        if perm_str in _DANGEROUS_PERMISSIONS:
            info = _DANGEROUS_PERMISSIONS[perm_str]
            audit_list.append({
                'severity': info['severity'],
                'category': 'dangerous_permission',
                'message': f"Permission '{perm_str}': {info['message']}",
                'file': source_file,
            })

        # Check for wildcard scope in object permissions
        if isinstance(perm, dict):
            scope = perm.get('allow', perm.get('scope', {}))
            if isinstance(scope, dict):
                allow_list = scope.get('allow', [])
                if '**' in str(allow_list) or '$APPDATA/**' in str(allow_list):
                    audit_list.append({
                        'severity': 'high',
                        'category': 'permissive_scope',
                        'message': f"Permission '{perm_str}' has very broad scope: {allow_list}. "
                                   f"This may allow access to more files than intended.",
                        'file': source_file,
                    })

        # Flag any fs: scope with **
        if isinstance(perm, dict) and perm.get('identifier', '').startswith('fs:'):
            for key in ('allow', 'scope'):
                val = perm.get(key, {})
                if isinstance(val, dict):
                    for sub_key in ('allow',):
                        sub_val = val.get(sub_key, [])
                        if '**' in str(sub_val):
                            audit_list.append({
                                'severity': 'high',
                                'category': 'permissive_fs_scope',
                                'message': f"Filesystem permission '{perm_str}' with wildcard scope: {sub_val}. "
                                           f"Grants access to the entire filesystem within the scope.",
                                'file': source_file,
                            })


def _scan_tauri_ipc_handlers(src_dir: str, workspace: str, analysis: Dict[str, Any]) -> None:
    """Scan Rust source files for Tauri IPC command handlers.

    Detects patterns:
    - #[tauri::command]
    - .invoke_handler(tauri::generate_handler![...])
    - .register_uri_scheme_protocol(...)
    - .register_asynchronous_uri_scheme_protocol(...)
    """
    import re

    # Pattern for #[tauri::command] attributed functions
    cmd_pattern = re.compile(
        r'#\[tauri::command\]\s*(?:///.*\s*)*\s*pub\s+(?:async\s+)?fn\s+(\w+)'
    )
    # Pattern for generate_handler! macro
    gen_handler_pattern = re.compile(
        r'tauri::generate_handler!\[([^\]]+)\]'
    )
    # Pattern for URI scheme protocols
    uri_scheme_pattern = re.compile(
        r'\.register_(?:asynchronous_)?uri_scheme_protocol\(\s*"([^"]+)"'
    )
    # Pattern for invoke handlers from TypeScript
    invoke_pattern = re.compile(
        r"invoke\s*\(\s*['\"](\w+)['\"]"
    )

    # Track found handlers and registered commands
    found_commands = []
    registered_commands = set()
    uri_schemes = []

    for root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue

        for f in files:
            if not f.endswith('.rs'):
                continue

            file_path = os.path.join(root, f)
            content = safe_read_file(file_path)
            if not content:
                continue

            rel_path = os.path.relpath(file_path, workspace)

            # Find #[tauri::command] functions
            for m in cmd_pattern.finditer(content):
                fn_name = m.group(1)
                # Find the function body to detect if it's async
                start = m.start()
                fn_header = content[start:start + 200]
                is_async = 'async' in fn_header.split('{')[0] if '{' in fn_header else 'async' in fn_header

                # Try to find the line number
                line_num = content[:m.start()].count('\n') + 1

                cmd_entry = {
                    'name': fn_name,
                    'file': rel_path,
                    'line': line_num,
                    'is_async': is_async,
                }
                found_commands.append(cmd_entry)

            # Find generate_handler! macro
            for m in gen_handler_pattern.finditer(content):
                handler_content = m.group(1)
                for cmd_name in re.findall(r'(\w+)', handler_content):
                    registered_commands.add(cmd_name)

            # Find URI scheme protocols
            for m in uri_scheme_pattern.finditer(content):
                uri_schemes.append({
                    'scheme': m.group(1),
                    'file': rel_path,
                })

    # Also scan TypeScript for invoke() calls
    for root, dirs, files in os.walk(os.path.dirname(src_dir)):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue
        for f in files:
            if not f.endswith(('.ts', '.tsx')):
                continue
            file_path = os.path.join(root, f)
            content = safe_read_file(file_path)
            if not content:
                continue
            rel_path = os.path.relpath(file_path, workspace)
            for m in invoke_pattern.finditer(content):
                line_num = content[:m.start()].count('\n') + 1
                # Track which commands are actually called from the frontend
                for cmd in found_commands:
                    if cmd['name'] == m.group(1):
                        cmd.setdefault('called_from', []).append({
                            'file': rel_path,
                            'line': line_num,
                        })

    analysis['ipc_commands'] = found_commands
    analysis['uri_schemes'] = uri_schemes

    # Audit: commands not registered in generate_handler!
    unregistered = [c for c in found_commands if c['name'] not in registered_commands]
    if unregistered:
        for cmd in unregistered:
            analysis['security_audit'].append({
                'severity': 'info',
                'category': 'unregistered_command',
                'message': f"Command '{cmd['name']}' is defined with #[tauri::command] "
                           f"but may not be registered in generate_handler!. "
                           f"Dead code or security oversight?",
                'file': cmd['file'],
            })

    # Audit: URI scheme protocols
    for scheme in uri_schemes:
        analysis['security_audit'].append({
            'severity': 'info',
            'category': 'custom_uri_scheme',
            'message': f"Custom URI scheme protocol '{scheme['scheme']}' registered. "
                       f"Ensure it validates input properly.",
            'file': scheme['file'],
        })

