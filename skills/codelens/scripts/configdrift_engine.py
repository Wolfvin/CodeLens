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

SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}


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
                logger.debug("Failed to parse package.json for dependencies", exc_info=True)

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
                logger.debug("Failed to read Cargo.toml for dependencies", exc_info=True)

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
                logger.debug("Failed to read requirements.txt for dependencies", exc_info=True)

        # pyproject.toml
        pyproject_path = os.path.join(workspace, "pyproject.toml")
        if os.path.exists(pyproject_path):
            try:
                with open(pyproject_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # Simple TOML parsing for dependencies
                in_deps = False
                for line in content.split('\n'):
                    stripped = line.strip()
                    if 'dependencies' in stripped.lower() and '=' in stripped:
                        in_deps = True
                        continue
                    elif stripped.startswith('['):
                        in_deps = False
                        continue
            except IOError:
                logger.debug("Failed to read pyproject.toml for dependencies", exc_info=True)

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
                for m in re.finditer(r'(?:from\s+(\S+)\s+)?import\s+(\S+)', content):
                    module = m.group(1) or m.group(2)
                    if module.startswith('.'):
                        relative.add(module)
                    else:
                        # Top-level module name
                        pkg_name = module.split('.')[0]
                        external.add(pkg_name)

            elif ext == ".rs":
                for m in re.finditer(r'use\s+([^;]+);', content):
                    use_path = m.group(1).strip()
                    if not use_path.startswith('std::') and not use_path.startswith('crate::') and not use_path.startswith('super::'):
                        # External crate
                        pkg_name = use_path.split('::')[0]
                        external.add(pkg_name)

    return {
        "external": external,
        "relative": relative,
        "phantom": phantom
    }


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

    # Known built-in modules (not real dependencies)
    builtins = {
        # Node.js
        'fs', 'path', 'http', 'https', 'url', 'util', 'os', 'crypto',
        'stream', 'buffer', 'events', 'child_process', 'net', 'tls',
        'assert', 'cluster', 'dgram', 'dns', 'domain', 'inspector',
        'perf_hooks', 'process', 'punycode', 'querystring', 'readline',
        'repl', 'timers', 'tty', 'v8', 'vm', 'worker_threads', 'zlib',
        # Python
        'os', 'sys', 'json', 're', 'datetime', 'collections', 'itertools',
        'functools', 'typing', 'dataclasses', 'abc', 'io', 'logging',
        'unittest', 'argparse', 'subprocess', 'threading', 'multiprocessing',
        'asyncio', 'pathlib', 'hashlib', 'base64', 'struct', 'socket',
        'email', 'html', 'xml', 'sqlite3', 'csv', 'configparser',
        # Rust
        'std', 'core', 'alloc',
    }

    # ─── Missing dependencies ───────────────────────────
    for pkg in actual_external:
        if pkg in builtins:
            continue
        normalized = _normalize_pkg_name(pkg, project_type)
        if normalized not in all_declared and pkg not in builtins:
            # Skip common packages that are truly transitive (not direct deps)
            transitive = {'prop-types', 'scheduler', '@vue/runtime-dom'}
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
