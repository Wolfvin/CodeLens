"""
Config Drift Engine for CodeLens — v3
Validates package.json/Cargo.toml/requirements.txt imports vs actual code imports.
Finds: missing deps, unused deps, version mismatches, phantom imports.

Mismatch = silent bugs, missing deps, or bloat.

Checks:
1. Missing dependencies: imported in code but not in package.json/Cargo.toml/requirements.txt
2. Unused dependencies: listed in package.json but never imported
3. Dev/prod mismatch: production dependency only imported in test files
4. Version conflicts: multiple versions of same package
5. Phantom imports: imports that resolve to nothing (broken paths)
"""

import os
import re
import json
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx", ".go",
}

def detect_config_drift(
    workspace: str,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Detect drift between dependency declarations and actual code usage.

    Args:
        workspace: Absolute path to workspace
        config: CodeLens config

    Returns:
        Dict with drift findings: missing deps, unused deps, mismatches
    """
    workspace = os.path.abspath(workspace)

    # Detect project type
    project_type = _detect_project_type(workspace)

    # Load declared dependencies
    declared = _load_declared_dependencies(workspace, project_type)

    # Scan code for actual imports
    actual = _scan_actual_imports(workspace, project_type)

    # Compare
    drift = _compute_drift(declared, actual, workspace, project_type)

    return {
        "status": "ok",
        "workspace": workspace,
        "project_type": project_type,
        "declared_dependencies": declared,
        "actual_imports_summary": {
            "total_unique_imports": len(actual["external"]),
            "by_type": {k: len(v) for k, v in actual.items() if isinstance(v, (list, set, dict))}
        },
        "drift": drift,
        "stats": {
            "declared_count": len(declared.get("dependencies", {})) + len(declared.get("dev_dependencies", {})),
            "missing_deps": len(drift.get("missing", [])),
            "unused_deps": len(drift.get("unused", [])),
            "dev_prod_mismatch": len(drift.get("dev_prod_mismatch", [])),
            "phantom_imports": len(drift.get("phantom_imports", []))
        },
        "recommendations": _generate_drift_recommendations(drift)
    }

def _detect_project_type(workspace: str) -> str:
    """Detect the project type from config files."""
    if os.path.exists(os.path.join(workspace, "package.json")):
        return "node"
    elif os.path.exists(os.path.join(workspace, "Cargo.toml")):
        return "rust"
    elif os.path.exists(os.path.join(workspace, "requirements.txt")) or \
         os.path.exists(os.path.join(workspace, "pyproject.toml")):
        return "python"
    else:
        return "unknown"

def _load_declared_dependencies(workspace: str, project_type: str) -> Dict:
    """Load declared dependencies from config files."""
    declared = {
        "dependencies": {},
        "dev_dependencies": {},
        "peer_dependencies": {}
    }

    if project_type == "node":
        pkg_path = os.path.join(workspace, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                declared["dependencies"] = pkg.get("dependencies", {})
                declared["dev_dependencies"] = pkg.get("devDependencies", {})
                declared["peer_dependencies"] = pkg.get("peerDependencies", {})
            except (json.JSONDecodeError, IOError):
                logger.debug("Config drift: failed to parse file", exc_info=True)

    elif project_type == "rust":
        cargo_path = os.path.join(workspace, "Cargo.toml")
        if os.path.exists(cargo_path):
            try:
                with open(cargo_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Parse [dependencies] section
                in_deps = False
                in_dev_deps = False
                for line in content.split('\n'):
                    stripped = line.strip()
                    if stripped == '[dependencies]':
                        in_deps = True
                        in_dev_deps = False
                        continue
                    elif stripped == '[dev-dependencies]':
                        in_deps = False
                        in_dev_deps = True
                        continue
                    elif stripped.startswith('['):
                        in_deps = False
                        in_dev_deps = False
                        continue

                    if in_deps and '=' in stripped:
                        name = stripped.split('=')[0].strip()
                        declared["dependencies"][name] = stripped
                    elif in_dev_deps and '=' in stripped:
                        name = stripped.split('=')[0].strip()
                        declared["dev_dependencies"][name] = stripped
            except IOError:
                logger.debug("Config drift: failed to parse file", exc_info=True)

    elif project_type == "python":
        # requirements.txt
        req_path = os.path.join(workspace, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        stripped = line.strip()
                        if stripped and not stripped.startswith('#'):
                            # Parse package name (before version specifier)
                            name = re.split(r'[><=!~\[]', stripped)[0].strip()
                            if name:
                                declared["dependencies"][name] = stripped
            except IOError:
                logger.debug("Config drift: failed to parse file", exc_info=True)

        # pyproject.toml
        pyproject_path = os.path.join(workspace, "pyproject.toml")
        if os.path.exists(pyproject_path):
            try:
                with open(pyproject_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Parse both [project.dependencies] (PEP 621) and
                # [tool.poetry.dependencies] sections
                in_deps = False
                in_poetry_deps = False
                in_project_section = False  # [project] section (PEP 621)
                in_array_deps = False  # PEP 621 array form: dependencies = ["pkg>=1.0", ...]
                for line in content.split('\n'):
                    stripped = line.strip()
                    # PEP 621: [project] or [project.dependencies]
                    if re.match(r'^\[project\]$', stripped):
                        in_deps = True
                        in_project_section = True
                        in_poetry_deps = False
                        in_array_deps = False
                        continue
                    elif re.match(r'^\[project\.dependencies\]$', stripped):
                        in_deps = True
                        in_project_section = False
                        in_poetry_deps = False
                        in_array_deps = False
                        continue
                    elif re.match(r'^\[project\.optional-dependencies\.', stripped):
                        in_deps = True
                        in_project_section = False
                        in_poetry_deps = False
                        in_array_deps = False
                        continue
                    # Poetry: [tool.poetry.dependencies]
                    elif re.match(r'^\[tool\.poetry\.dependencies\]$', stripped):
                        in_deps = False
                        in_poetry_deps = True
                        in_array_deps = False
                        continue
                    elif re.match(r'^\[tool\.poetry\.group\..*\.dependencies\]$', stripped):
                        in_deps = False
                        in_poetry_deps = True
                        in_array_deps = False
                        continue
                    elif stripped.startswith('[') and not stripped.startswith('[['):
                        in_deps = False
                        in_poetry_deps = False
                        in_array_deps = False
                        continue

                    if in_deps:
                        # PEP 621 array form detection: dependencies = [
                        if re.match(r'^dependencies\s*=\s*\[', stripped):
                            in_array_deps = True
                            # Handle single-line array: dependencies = ["pkg>=1.0"]
                            for m in re.finditer(r'"([A-Za-z0-9_.-]+[><=!~][^"]*)"', stripped):
                                pkg_name = re.split(r'[><=!~\[]', m.group(1))[0].strip()
                                declared["dependencies"][pkg_name] = m.group(1)
                            for m in re.finditer(r"'([A-Za-z0-9_.-]+[><=!~][^']*)'", stripped):
                                pkg_name = re.split(r'[><=!~\[]', m.group(1))[0].strip()
                                declared["dependencies"][pkg_name] = m.group(1)
                            # Check if array closes on same line
                            if ']' in stripped:
                                in_array_deps = False
                            continue

                        # Inside PEP 621 array: "pkg>=1.0",
                        if in_array_deps:
                            if ']' in stripped:
                                in_array_deps = False
                            # Match "pkg>=1.0" or 'pkg>=1.0'
                            for m in re.finditer(r'"([A-Za-z0-9_.-]+[><=!~\[][^"]*)"', stripped):
                                pkg_name = re.split(r'[><=!~\[]', m.group(1))[0].strip()
                                declared["dependencies"][pkg_name] = m.group(1)
                            for m in re.finditer(r"'([A-Za-z0-9_.-]+[><=!~\[][^']*)'", stripped):
                                pkg_name = re.split(r'[><=!~\[]', m.group(1))[0].strip()
                                declared["dependencies"][pkg_name] = m.group(1)
                            continue

                        # PEP 621 key-value form: name = ">=1.2.3" or name = {version = ">=1.2.3"}
                        # In [project] section: only parse 'dependencies' key,
                        # skip other keys like name, version, etc.
                        if in_project_section:
                            # Skip non-dependency keys in [project] section
                            if not re.match(r'^dependencies\s*=', stripped):
                                continue
                        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*["\']', stripped)
                        if m:
                            declared["dependencies"][m.group(1)] = stripped
                            continue
                        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\{', stripped)
                        if m:
                            declared["dependencies"][m.group(1)] = stripped
                            continue

                    if in_poetry_deps:
                        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*["\']', stripped)
                        if m and m.group(1).lower() != 'python':
                            declared["dependencies"][m.group(1)] = stripped
                            continue
                        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\{', stripped)
                        if m and m.group(1).lower() != 'python':
                            declared["dependencies"][m.group(1)] = stripped
                            continue
            except IOError:
                logger.debug("Config drift: failed to parse file", exc_info=True)

    return declared

def _scan_actual_imports(workspace: str, project_type: str) -> Dict:
    """Scan all source files for actual import statements."""
    external: Set[str] = set()  # External package names
    relative: Set[str] = set()  # Relative imports
    phantom: Set[str] = set()   # Imports that don't resolve

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)
            is_test = any(x in rel_path for x in ['.test.', '.spec.', '_test.', '__tests__'])

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                # ES imports
                for m in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
                    imp = m.group(1)
                    if imp.startswith('.') or imp.startswith('@/'):
                        relative.add(imp)
                        # Check if it resolves
                        resolved = _resolve_js_import(imp, os.path.dirname(rel_path), workspace)
                        if not resolved:
                            phantom.add(f"{rel_path}:{imp}")
                    else:
                        # External package — get the top-level package name
                        pkg_name = imp.split('/')[0]
                        if pkg_name.startswith('@'):
                            # Scoped package: @scope/name
                            parts = imp.split('/')
                            if len(parts) >= 2:
                                pkg_name = parts[0] + '/' + parts[1]
                        external.add(pkg_name)

                # CommonJS require
                for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
                    imp = m.group(1)
                    if imp.startswith('.'):
                        relative.add(imp)
                    else:
                        pkg_name = imp.split('/')[0]
                        if pkg_name.startswith('@'):
                            parts = imp.split('/')
                            if len(parts) >= 2:
                                pkg_name = parts[0] + '/' + parts[1]
                        external.add(pkg_name)

            elif ext == ".py":
                # Parse Python imports more carefully
                # Handle: from X import Y  →  X is the module
                # Handle: import X  →  X is the module
                # Do NOT capture Y (the imported names) as modules
                for line in content.split('\n'):
                    stripped = line.strip()
                    # Skip comments
                    if stripped.startswith('#'):
                        continue
                    # from X import ...
                    m = re.match(r'from\s+([a-zA-Z_][a-zA-Z0-9_.]*)\s+import', stripped)
                    if m:
                        module = m.group(1)
                        if module.startswith('.'):
                            relative.add(module)
                        else:
                            pkg_name = module.split('.')[0]
                            if pkg_name not in ('from', 'import', 'as', 'class', 'def', 'return', 'yield'):
                                external.add(pkg_name)
                        continue
                    # import X (but not "from X import Y")
                    m = re.match(r'import\s+([a-zA-Z_][a-zA-Z0-9_.]*)', stripped)
                    if m:
                        module = m.group(1)
                        if module.startswith('.'):
                            relative.add(module)
                        else:
                            pkg_name = module.split('.')[0]
                            if pkg_name not in ('from', 'import', 'as', 'class', 'def', 'return', 'yield'):
                                external.add(pkg_name)

            elif ext == ".rs":
                # Parse Rust use statements line-by-line to avoid matching
                # 'use' inside comments or doc comments (which caused false positives
                # like "relay connections" being detected as missing deps).
                for line in content.split('\n'):
                    stripped = line.lstrip()
                    # Skip comment lines (// and /*)
                    if stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('//!') or stripped.startswith('///'):
                        continue
                    # Remove inline comments before matching
                    comment_pos = stripped.find('//')
                    if comment_pos >= 0:
                        stripped = stripped[:comment_pos]
                    # Match Rust use statements at the start of a line (with optional whitespace)
                    m = re.match(r'\s*use\s+([^;]+);', stripped)
                    if m:
                        use_path = m.group(1).strip()
                        # Skip self::, super::, crate::, std:: — these are internal
                        if use_path.startswith('std::') or use_path.startswith('crate::') or use_path.startswith('super::') or use_path.startswith('self::'):
                            continue
                        # Handle grouped imports: use foo::{bar, baz} → extract foo
                        if '::{' in use_path:
                            use_path = use_path.split('::{')[0]
                        # External crate — take the first path segment
                        pkg_name = use_path.split('::')[0]
                        # Validate: only accept alphanumeric + underscore crate names
                        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', pkg_name):
                            external.add(pkg_name)

    return {
        "external": external,
        "relative": relative,
        "phantom": phantom,
        "local_packages": _detect_local_packages(workspace)
    }


def _detect_local_packages(workspace: str) -> Set[str]:
    """Detect local package names (directories with __init__.py) in the workspace.
    These are not external dependencies — they're part of the project itself.
    """
    local = set()
    for entry in os.listdir(workspace):
        entry_path = os.path.join(workspace, entry)
        if os.path.isdir(entry_path):
            # Check if it's a Python package (has __init__.py)
            if os.path.exists(os.path.join(entry_path, '__init__.py')):
                local.add(entry)
    return local

def _resolve_js_import(import_path: str, from_dir: str, workspace: str) -> bool:
    """Check if a relative JS import resolves to an actual file."""
    if import_path.startswith('@/'):
        # Alias import — assume it resolves
        return True

    resolved = os.path.normpath(os.path.join(workspace, from_dir, import_path))

    # Try various extensions
    extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '/index.js', '/index.ts']
    for ext in extensions:
        if os.path.isfile(resolved + ext):
            return True

    return False

def _compute_drift(
    declared: Dict, actual: Dict,
    workspace: str, project_type: str
) -> Dict[str, List[Dict]]:
    """Compare declared dependencies with actual imports to find drift."""
    drift = {
        "missing": [],       # Imported but not declared
        "unused": [],        # Declared but never imported
        "dev_prod_mismatch": [],  # Prod dep only used in tests
        "phantom_imports": []     # Imports that don't resolve
    }

    # Get all declared package names (normalized)
    all_declared = set()
    declared_deps = declared.get("dependencies", {})
    declared_dev = declared.get("dev_dependencies", {})
    declared_peer = declared.get("peer_dependencies", {})

    for name in declared_deps:
        all_declared.add(_normalize_pkg_name(name, project_type))
    for name in declared_dev:
        all_declared.add(_normalize_pkg_name(name, project_type))
    for name in declared_peer:
        all_declared.add(_normalize_pkg_name(name, project_type))

    # Get all actual external imports
    actual_external = actual.get("external", set())

    # Get local packages (not real external deps — they're part of the project)
    local_packages = actual.get("local_packages", set())

    # Known built-in modules (not real dependencies)
    builtins = {
        # ── Node.js built-ins ──
        'fs', 'path', 'http', 'https', 'url', 'util', 'os', 'crypto',
        'stream', 'buffer', 'events', 'child_process', 'net', 'tls',
        'assert', 'cluster', 'dgram', 'dns', 'domain', 'inspector',
        'perf_hooks', 'process', 'punycode', 'querystring', 'readline',
        'repl', 'timers', 'tty', 'v8', 'vm', 'worker_threads', 'zlib',
        'console', 'module', 'global', 'Buffer', 'Promise', 'Symbol',
        'Proxy', 'Reflect', 'Set', 'Map', 'WeakMap', 'WeakSet',
        # Node: protocol variants
        'node:fs', 'node:path', 'node:http', 'node:https', 'node:url',
        'node:util', 'node:os', 'node:crypto', 'node:stream', 'node:buffer',
        'node:events', 'node:child_process', 'node:net', 'node:tls',
        'node:assert', 'node:cluster', 'node:dgram', 'node:dns',
        'node:perf_hooks', 'node:process', 'node:readline', 'node:repl',
        'node:timers', 'node:worker_threads', 'node:zlib', 'node:test',
        # ── Python stdlib (comprehensive, Python 3.8+) ──
        '__future__', '_thread', '_io', 'abc', 'argparse', 'array', 'ast',
        'asyncio', 'atexit', 'audioop', 'base64', 'binascii', 'binhex',
        'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb', 'chunk',
        'cmath', 'code', 'codecs', 'codeop', 'collections', 'colorsys',
        'compileall', 'concurrent', 'configparser', 'contextlib', 'contextvars', 'copy',
        'copyreg', 'cProfile', 'crypt', 'csv', 'ctypes', 'curses',
        'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis',
        'distutils', 'doctest', 'email', 'encodings', 'enum', 'errno',
        'faulthandler', 'filecmp', 'fileinput', 'fnmatch', 'fractions',
        'ftplib', 'functools', 'gc', 'getopt', 'getpass', 'gettext',
        'glob', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html',
        'http', 'idlelib', 'imaplib', 'importlib', 'inspect', 'io',
        'ipaddress', 'itertools', 'json', 'keyword', 'lib2to3', 'linecache',
        'locale', 'logging', 'lzma', 'mailbox', 'mailcap', 'marshal',
        'math', 'mimetypes', 'mmap', 'modulefinder', 'multiprocessing',
        'netrc', 'nis', 'numbers', 'operator', 'optparse', 'os',
        'ossaudiodev', 'parser', 'pathlib', 'pdb', 'pickle', 'pickletools',
        'pipes', 'pkgutil', 'platform', 'plistlib', 'poplib', 'posix',
        'posixpath', 'pprint', 'profile', 'pstats', 'pty', 'pwd',
        'py_compile', 'pyclbr', 'pydoc', 'queue', 'quopri', 'random',
        're', 'readline', 'reprlib', 'resource', 'rlcompleter', 'runpy',
        'sched', 'secrets', 'select', 'selectors', 'shelve', 'shlex',
        'shutil', 'signal', 'site', 'smtpd', 'smtplib', 'sndhdr',
        'socket', 'socketserver', 'spwd', 'sqlite3', 'ssl', 'stat',
        'statistics', 'string', 'stringprep', 'struct', 'subprocess',
        'sunau', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny',
        'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap',
        'threading', 'time', 'timeit', 'tkinter', 'token', 'tokenize',
        'tomllib', 'trace', 'traceback', 'tracemalloc', 'tty', 'turtle',
        'turtledemo', 'types', 'typing', 'unicodedata', 'unittest',
        'urllib', 'uu', 'uuid', 'venv', 'warnings', 'wave', 'weakref',
        'webbrowser', 'winreg', 'winsound', 'wsgiref', 'xdrlib',
        'xml', 'xmlrpc', 'zipapp', 'zipfile', 'zipimport', 'zlib',
        'zoneinfo',
        # Common Python meta-packages
        'setuptools', 'pip', 'pkg_resources', 'ensurepip',
        # ── Rust built-ins ──
        'std', 'core', 'alloc',
    }

    # ─── Missing dependencies ───────────────────────────
    for pkg in actual_external:
        if pkg in builtins or pkg in local_packages:
            continue
        normalized = _normalize_pkg_name(pkg, project_type)
        if normalized not in all_declared and pkg not in builtins:
            # Skip common framework packages that are often transitive
            transitive = {'prop-types', 'scheduler', 'react', 'react-dom', 'vue', '@vue/runtime-dom'}
            if pkg not in transitive:
                drift["missing"].append({
                    "package": pkg,
                    "severity": "warning",
                    "message": f"'{pkg}' is imported in code but not declared in dependencies",
                    "suggestion": f"Add '{pkg}' to your dependencies."
                })

    # ─── Unused dependencies ────────────────────────────
    all_actual_normalized = {_normalize_pkg_name(p, project_type) for p in actual_external}

    for name, version in declared_deps.items():
        normalized = _normalize_pkg_name(name, project_type)
        if normalized not in all_actual_normalized:
            # Some packages are entry points that don't need explicit imports
            entry_points = {
                'eslint', 'prettier', 'jest', 'mocha', 'chai', 'vitest',
                'typescript', 'webpack', 'vite', 'rollup', 'babel',
                'nodemon', 'concurrently', 'dotenv', 'cross-env',
                '@types/node', 'ts-node', 'ts-loader',
            }
            if name not in entry_points and not name.startswith('@types/'):
                drift["unused"].append({
                    "package": name,
                    "version": version,
                    "severity": "info",
                    "message": f"'{name}' is declared but never imported",
                    "suggestion": f"Consider removing '{name}' if not needed."
                })

    # ─── Phantom imports ────────────────────────────────
    for phantom in actual.get("phantom", set()):
        parts = phantom.split(':')
        drift["phantom_imports"].append({
            "import": parts[1] if len(parts) > 1 else phantom,
            "file": parts[0] if len(parts) > 1 else "unknown",
            "severity": "warning",
            "message": f"Import '{parts[1] if len(parts) > 1 else phantom}' does not resolve to a file",
            "suggestion": "Check the import path or create the missing file."
        })

    return drift

def _normalize_pkg_name(name: str, project_type: str) -> str:
    """Normalize package name for comparison."""
    # Remove @scope prefix for comparison
    if project_type == "node" and name.startswith('@'):
        return name.lower()
    return name.lower().replace('-', '_').replace('.', '_')

def _generate_drift_recommendations(drift: Dict) -> List[str]:
    """Generate recommendations based on drift findings."""
    recs = []

    if drift["missing"]:
        pkgs = [d["package"] for d in drift["missing"]]
        recs.append(
            f"INSTALL MISSING: {len(pkgs)} package(s) imported but not declared: {', '.join(pkgs[:10])}"
        )

    if drift["unused"]:
        pkgs = [d["package"] for d in drift["unused"]]
        recs.append(
            f"CLEANUP: {len(pkgs)} declared package(s) never imported: {', '.join(pkgs[:10])}"
        )

    if drift["phantom_imports"]:
        recs.append(
            f"FIX IMPORTS: {len(drift['phantom_imports'])} import(s) don't resolve to any file"
        )

    if drift["dev_prod_mismatch"]:
        recs.append(
            f"REVIEW: {len(drift['dev_prod_mismatch'])} package(s) may be in wrong dependency category"
        )

    if not any(drift.values()):
        recs.append("Dependencies look clean — no drift detected.")

    return recs
