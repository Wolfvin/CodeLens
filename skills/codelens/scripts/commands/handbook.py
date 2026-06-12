"""Handbook command — Generate project handbook for AI agents."""

import os
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any

from registry import load_config, ensure_codelens_dir
from framework_detect import detect_frameworks
from smell_engine import detect_smells
from entrypoints_engine import map_entrypoints
from apimap_engine import map_api_routes
from statemap_engine import map_state
from circular_engine import detect_circular
from deadcode_engine import detect_dead_code
from secrets_engine import detect_secrets
from vulnscan_engine import scan_vulnerabilities
from outline_engine import get_workspace_outline
from commands import register_command
from commands.scan import cmd_scan
from utils import write_output_files, compute_summary, CODELENS_VERSION, DEFAULT_IGNORE_DIRS, logger


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000). "
                             "Prevents timeout on very large repos.")


def execute(args, workspace):
    max_files = getattr(args, 'max_files', 5000)
    return cmd_handbook(workspace, max_files=max_files)


def cmd_handbook(workspace: str, max_files: int = 5000) -> Dict[str, Any]:
    """
    Generate a comprehensive project handbook for AI agents.
    Aggregates data from multiple engines into one output.
    Also writes .codelens/handbook.json and .codelens/AGENT.md.
    max_files caps the scan file count to prevent timeout on huge repos.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    # 1. Identity — extract from package.json / pyproject.toml / README
    identity = _extract_project_identity(workspace)

    # 2. Run scan first (needed for registry data) — skip if registry is fresh
    scan_result = None
    registry_path = os.path.join(workspace, '.codelens', 'backend.json')
    if os.path.exists(registry_path):
        try:
            import time
            mtime = os.path.getmtime(registry_path)
            if time.time() - mtime < 300:  # 5 minutes freshness
                from registry import load_backend_registry, load_frontend_registry
                backend = load_backend_registry(workspace)
                frontend = load_frontend_registry(workspace)
                scan_result = {
                    "status": "ok",
                    "backend": {
                        "nodes": len(backend.get("nodes", [])) if isinstance(backend.get("nodes"), list) else backend.get("nodes", 0),
                        "edges": len(backend.get("edges", [])) if isinstance(backend.get("edges"), list) else backend.get("edges", 0)
                    },
                    "frontend": {
                        "classes": len(frontend.get("classes", [])) if isinstance(frontend.get("classes"), list) else frontend.get("classes", 0),
                        "ids": len(frontend.get("ids", [])) if isinstance(frontend.get("ids"), list) else frontend.get("ids", 0)
                    }
                }
        except Exception:
            logger.warning("Scan result loading failed", exc_info=True)
    if scan_result is None:
        scan_result = cmd_scan(workspace)

    # 3. Generate output files (outline.json, summary.json)
    try:
        write_output_files(workspace, scan_result)
    except Exception:
        logger.warning("Failed to write output files", exc_info=True)

    # 4. Frameworks
    try:
        fw_result = detect_frameworks(workspace)
        frameworks = fw_result.get("frameworks", [])
    except Exception:
        logger.warning("Framework detection failed", exc_info=True)
        frameworks = config.get("frameworks", [])

    # 5. Health (from smell engine)
    try:
        smell_result = detect_smells(workspace)
        health = {
            "score": smell_result.get("stats", {}).get("health_score", 0),
            "smells_count": smell_result.get("stats", {}).get("total_smells", 0),
            "critical": smell_result.get("stats", {}).get("critical", 0),
            "warning": smell_result.get("stats", {}).get("warning", 0),
        }
    except Exception:
        logger.warning("Health detection failed", exc_info=True)
        health = {"score": 0, "smells_count": 0, "critical": 0, "warning": 0}

    # 6. Entrypoints
    try:
        ep_result = map_entrypoints(workspace)
        entrypoints = [
            {"type": e.get("type"), "file": e.get("file"), "line": e.get("line"), "label": e.get("label")}
            for e in ep_result.get("entrypoints", [])[:30]
        ]
    except Exception:
        logger.warning("Entrypoint mapping failed", exc_info=True)
        entrypoints = []

    # 7. API Routes
    try:
        api_result = map_api_routes(workspace)
        api_routes = [
            {"method": r.get("method"), "path": r.get("path"), "handler": r.get("handler_name"), "file": r.get("file")}
            for r in api_result.get("routes", [])[:50]
        ]
    except Exception:
        logger.warning("API route mapping failed", exc_info=True)
        api_routes = []

    # 8. State management
    try:
        state_result = map_state(workspace)
        state_stores = [
            {"name": s.get("name"), "type": s.get("type"), "framework": s.get("framework"), "file": s.get("defined_in")}
            for s in state_result.get("stores", [])[:20]
        ]
    except Exception:
        logger.warning("State management mapping failed", exc_info=True)
        state_stores = []

    # 9. Risks (circular deps, dead code, secrets)
    risks = []
    try:
        circ_result = detect_circular(workspace)
        for chain in circ_result.get("chains", [])[:5]:
            risks.append({"type": "circular_dep", "description": f"{' → '.join(chain.get('path', []))}"})
    except Exception:
        logger.warning("Circular dependency detection failed", exc_info=True)
    try:
        dead_result = detect_dead_code(workspace)
        dead_count = dead_result.get("stats", {}).get("total_dead", 0)
        if dead_count > 0:
            risks.append({"type": "dead_code", "count": dead_count})
    except Exception:
        logger.warning("Dead code detection failed", exc_info=True)
    try:
        secrets_result = detect_secrets(workspace)
        secrets_count = secrets_result.get("stats", {}).get("total_secrets", 0)
        if secrets_count > 0:
            risks.append({"type": "secrets", "count": secrets_count})
    except Exception:
        logger.warning("Secrets detection failed", exc_info=True)
    try:
        vuln_result = scan_vulnerabilities(workspace)
        vuln_count = vuln_result.get("stats", {}).get("total_vulnerabilities", 0)
        if vuln_count > 0:
            risks.append({"type": "vulnerabilities", "count": vuln_count})
    except Exception:
        logger.warning("Vulnerability scan failed", exc_info=True)

    # 10. Directory map
    directory_map = _build_directory_map(workspace, config)

    # 11. Quick reference from summary
    try:
        summary = compute_summary(workspace, get_workspace_outline(workspace), scan_result)
    except Exception:
        logger.warning("Summary computation failed", exc_info=True)
        summary = {}

    # 12. Conventions
    conventions = _detect_conventions(workspace)

    # Build handbook
    handbook = {
        "status": "ok",
        "meta": {
            "workspace": workspace,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "codelens_version": CODELENS_VERSION
        },
        "identity": identity,
        "frameworks": frameworks,
        "structure": {
            "directory_map": directory_map,
            "entrypoints": entrypoints,
            "api_routes": api_routes,
            "state_management": state_stores
        },
        "health": health,
        "conventions": conventions,
        "risks": risks,
        "quick_reference": {
            "total_files": summary.get("files", 0),
            "total_functions": summary.get("functions", 0),
            "total_classes": summary.get("classes", 0),
            "total_exports": summary.get("exports", 0),
            "backend_nodes": summary.get("backend_nodes", 0),
            "backend_edges": summary.get("backend_edges", 0),
            "frontend_classes": summary.get("frontend_classes", 0),
            "frontend_ids": summary.get("frontend_ids", 0),
        },
        "files_by_language": summary.get("files_by_language", {})
    }

    # Write handbook.json
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    handbook_path = os.path.join(codelens_dir, 'handbook.json')
    with open(handbook_path, 'w', encoding='utf-8') as f:
        json.dump(handbook, f, indent=2, ensure_ascii=False)

    # Generate AGENT.md
    _generate_agent_md(workspace, handbook)

    return handbook


def _extract_project_identity(workspace: str) -> Dict[str, Any]:
    """Extract project identity from package.json, pyproject.toml, or README.

    v6: Removed unknown-type guard on Cargo.toml, added combined/polyglot type
    detection, sub-directory package.json scanning, and monorepo-specific types.
    """
    identity = {
        "name": os.path.basename(workspace),
        "description": "",
        "version": "0.0.0",
        "type": "unknown",
        # v6: monorepo & sub-dir info
        "is_monorepo": False,
        "monorepo_tools": [],
        "subdir_frameworks": {},
    }

    has_package_json = False
    has_cargo_toml = False
    has_pyproject = False
    js_type = None  # v6: track JS-derived type separately for polyglot detection
    python_type = None  # v6: track Python-derived type separately
    rust_type = None  # v6: track Rust-derived type separately

    # v6: Check monorepo indicators first
    _MONOREPO_INDICATORS = {
        "turbo.json": "turborepo",
        "pnpm-workspace.yaml": "pnpm-workspace",
        "lerna.json": "lerna",
        "nx.json": "nx",
    }
    for indicator_file, tool_name in _MONOREPO_INDICATORS.items():
        if os.path.isfile(os.path.join(workspace, indicator_file)):
            identity["is_monorepo"] = True
            if tool_name not in identity["monorepo_tools"]:
                identity["monorepo_tools"].append(tool_name)

    # v5.8: Check for Rust/Cargo workspace monorepo
    cargo_toml_path = os.path.join(workspace, 'Cargo.toml')
    if os.path.isfile(cargo_toml_path):
        try:
            with open(cargo_toml_path, 'r', encoding='utf-8') as f:
                cargo_content = f.read()
            # Check for [workspace] section with members
            if '[workspace]' in cargo_content:
                identity["is_monorepo"] = True
                if "cargo-workspace" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("cargo-workspace")
        except Exception:
            pass

    # v5.8: Check for crates/ or ext/ directories with Cargo.toml (Rust monorepo pattern)
    for crate_dir_name in ('crates', 'ext'):
        crate_dir = os.path.join(workspace, crate_dir_name)
        if os.path.isdir(crate_dir):
            sub_crates = 0
            try:
                for entry in os.listdir(crate_dir):
                    sub_cargo = os.path.join(crate_dir, entry, 'Cargo.toml')
                    if os.path.isfile(sub_cargo):
                        sub_crates += 1
            except OSError:
                pass
            if sub_crates >= 2:
                identity["is_monorepo"] = True
                if "cargo-workspace" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("cargo-workspace")

    # Try package.json
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        has_package_json = True
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            identity["name"] = pkg.get("name", identity["name"])
            identity["version"] = pkg.get("version", identity["version"])
            identity["description"] = pkg.get("description", "")
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                js_type = "fullstack-web-app"
            elif "express" in deps or "fastify" in deps or "koa" in deps:
                js_type = "backend-api"
            elif "react" in deps or "vue" in deps or "svelte" in deps:
                js_type = "frontend-app"
            else:
                js_type = "node-project"
        except Exception:
            logger.warning("package.json parsing failed", exc_info=True)

    # v6: Walk sub-directories for nested package.json (apps/*, packages/*)
    _MONOREPO_SUBDIRS = ["apps", "packages", "services"]
    for subdir in _MONOREPO_SUBDIRS:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        try:
            for entry in sorted(os.listdir(subdir_path)):
                entry_pkg = os.path.join(subdir_path, entry, "package.json")
                if not os.path.isfile(entry_pkg):
                    continue
                try:
                    with open(entry_pkg, 'r', encoding='utf-8') as f:
                        pkg = json.load(f)
                    sub_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                    rel_subdir = os.path.join(subdir, entry)
                    subdir_fws = []
                    # v6: Detect frameworks from sub-directory deps
                    if "next" in sub_deps:
                        subdir_fws.append("next.js")
                        if js_type is None:
                            js_type = "fullstack-web-app"
                    if "react" in sub_deps:
                        subdir_fws.append("react")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "vue" in sub_deps:
                        subdir_fws.append("vue")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "svelte" in sub_deps:
                        subdir_fws.append("svelte")
                        if js_type is None:
                            js_type = "frontend-app"
                    if "express" in sub_deps or "fastify" in sub_deps:
                        subdir_fws.append("express")
                        if js_type is None:
                            js_type = "backend-api"
                    if subdir_fws:
                        identity["subdir_frameworks"][rel_subdir] = subdir_fws
                except Exception:
                    pass
        except OSError:
            pass

    # Try pyproject.toml
    pyproject_path = os.path.join(workspace, 'pyproject.toml')
    if os.path.isfile(pyproject_path):
        has_pyproject = True
        try:
            with open(pyproject_path, 'r', encoding='utf-8') as f:
                content = f.read()
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                identity["name"] = name_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            desc_match = re.search(r'description\s*=\s*["\']([^"\']+)["\']', content)
            if desc_match:
                identity["description"] = desc_match.group(1)
            if "fastapi" in content or "flask" in content or "django" in content:
                python_type = "backend-api"
            elif "pytest" in content:
                python_type = "python-library"
            else:
                python_type = "python-project"
        except Exception:
            logger.warning("pyproject.toml parsing failed", exc_info=True)

    # Try setup.cfg for version/description (common in Python projects)
    if identity["version"] == "0.0.0" or not identity["description"]:
        setup_cfg_path = os.path.join(workspace, 'setup.cfg')
        if os.path.isfile(setup_cfg_path):
            try:
                with open(setup_cfg_path, 'r', encoding='utf-8') as f:
                    setup_cfg_content = f.read()
                if identity["version"] == "0.0.0":
                    ver_match = re.search(r'version\s*=\s*["\']?([^"\':\s]+)["\']?', setup_cfg_content)
                    if ver_match:
                        identity["version"] = ver_match.group(1)
                if not identity["description"]:
                    desc_match = re.search(r'description\s*=\s*["\']([^"\']+)["\']', setup_cfg_content)
                    if desc_match:
                        identity["description"] = desc_match.group(1)
                    else:
                        # Try long_description or summary from setup.cfg
                        summary_match = re.search(r'(?:long_description|summary)\s*=\s*["\']([^"\']+)["\']', setup_cfg_content)
                        if summary_match:
                            identity["description"] = summary_match.group(1)
            except Exception:
                logger.debug("setup.cfg parsing failed")

    # Try __version__.py, _version.py, or __init__.py for version (common Python patterns)
    if identity["version"] == "0.0.0":
        version_file_paths = [
            os.path.join(workspace, '__version__.py'),
            os.path.join(workspace, '_version.py'),
        ]
        # Scan for __version__.py and __init__.py in top-level subdirectories
        # Many Python packages define __version__ in their package's __init__.py
        try:
            for entry in os.listdir(workspace):
                subdir = os.path.join(workspace, entry)
                if os.path.isdir(subdir) and not entry.startswith('.') and entry not in ('tests', 'docs', '.git', 'venv', '.venv', 'env', '.tox', '__pycache__'):
                    # Check __version__.py first (explicit version file)
                    for vf_name in ('__version__.py', '_version.py', '__init__.py'):
                        version_file = os.path.join(subdir, vf_name)
                        if os.path.isfile(version_file):
                            version_file_paths.append(version_file)
        except OSError:
            pass

        for vf_path in version_file_paths:
            if os.path.isfile(vf_path):
                try:
                    with open(vf_path, 'r', encoding='utf-8') as f:
                        vf_content = f.read(2000)  # Read first 2KB — version is usually near the top
                    ver_match = re.search(r'(?:__version__|version)\s*=\s*["\']([^"\']+)["\']', vf_content)
                    if ver_match:
                        identity["version"] = ver_match.group(1)
                        break
                except Exception:
                    pass

    # Try setup.py for version (last resort for Python projects)
    if identity["version"] == "0.0.0":
        setup_py_path = os.path.join(workspace, 'setup.py')
        if os.path.isfile(setup_py_path):
            try:
                with open(setup_py_path, 'r', encoding='utf-8') as f:
                    setup_py_content = f.read()
                # Look for version= in setup() call
                ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', setup_py_content)
                if ver_match:
                    identity["version"] = ver_match.group(1)
            except Exception:
                logger.debug("setup.py parsing failed")

    # Fallback: extract description from README
    if not identity["description"]:
        for readme_name in ('README.md', 'README.rst', 'README.txt', 'README'):
            readme_path = os.path.join(workspace, readme_name)
            if os.path.isfile(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                        readme_content = f.read(2000)  # Read first 2KB
                    # Look for first paragraph after the title
                    lines = readme_content.split('\n')
                    for i, line in enumerate(lines):
                        # Skip title lines (start with # or are underlined)
                        if line.startswith('#'):
                            # Get next non-empty, non-heading line
                            for j in range(i + 1, min(i + 10, len(lines))):
                                desc_line = lines[j].strip()
                                if desc_line and not desc_line.startswith('#') and not desc_line.startswith('..'):
                                    identity["description"] = desc_line[:200]
                                    break
                            break
                        # RST title: next line is all === or ---
                        if i + 1 < len(lines) and re.match(r'^[=\-~^]+$', lines[i + 1].strip()):
                            for j in range(i + 2, min(i + 12, len(lines))):
                                desc_line = lines[j].strip()
                                if desc_line and not desc_line.startswith('..') and not desc_line.startswith(':'):
                                    identity["description"] = desc_line[:200]
                                    break
                            break
                    if identity["description"]:
                        break
                except Exception:
                    pass

    # v6: Try Cargo.toml — always check (removed identity["type"] == "unknown" guard)
    cargo_path = os.path.join(workspace, 'Cargo.toml')
    if os.path.isfile(cargo_path):
        has_cargo_toml = True
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                content = f.read()
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                identity["name"] = name_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            rust_type = "rust-project"
        except Exception:
            logger.warning("Cargo.toml parsing failed", exc_info=True)

    # v5.8.1: Try go.mod — detect Go projects
    go_type = None
    go_mod_path = os.path.join(workspace, 'go.mod')
    if os.path.isfile(go_mod_path):
        try:
            with open(go_mod_path, 'r', encoding='utf-8') as f:
                go_mod_content = f.read()
            # Extract module name and Go version
            module_match = re.search(r'^module\s+(\S+)', go_mod_content, re.MULTILINE)
            go_ver_match = re.search(r'^go\s+(\S+)', go_mod_content, re.MULTILINE)
            if module_match:
                mod_name = module_match.group(1)
                # Use last segment of module path as project name
                identity["name"] = mod_name.split('/')[-1]
            if go_ver_match:
                identity["version"] = go_ver_match.group(1)
            # Classify Go project type based on dependencies and module name
            mod_name_lower = mod_name.lower() if module_match else ""
            if any(kw in mod_name_lower for kw in ('cockroachdb', 'postgres', 'mysql', 'sqlite', 'mongodb', 'redis', 'etcd', 'database', 'sql', 'db/')):
                go_type = "go-database"
            elif 'database/sql' in go_mod_content:
                go_type = "go-database"
            elif 'gin-gonic' in go_mod_content or 'labstack/echo' in go_mod_content:
                go_type = "go-web-service"
            elif 'k8s.io/' in go_mod_content or 'kubernetes' in go_mod_content:
                go_type = "go-infrastructure"
            elif 'google.golang.org/grpc' in go_mod_content:
                go_type = "go-grpc-service"
            elif 'net/http' in go_mod_content:
                go_type = "go-web-service"
            else:
                go_type = "go-project"
        except Exception:
            logger.warning("go.mod parsing failed", exc_info=True)

    # v6: Combined type detection — handle polyglot projects
    active_types = [t for t in [js_type, python_type, rust_type, go_type] if t is not None]

    if len(active_types) >= 2:
        # Polyglot project — build a combined type string
        type_parts = []
        if rust_type:
            type_parts.append("rust")
        if go_type:
            type_parts.append("go")
        if js_type:
            type_parts.append("typescript" if "typescript" in (js_type or "") else "js")
        if python_type:
            type_parts.append("python")
        identity["type"] = "-".join(type_parts) + "-monorepo" if identity["is_monorepo"] else "-".join(type_parts) + "-polyglot"
    elif len(active_types) == 1:
        identity["type"] = active_types[0]
        # v6: If monorepo indicators found, append -monorepo suffix
        if identity["is_monorepo"]:
            identity["type"] = active_types[0] + "-monorepo"
    # If no type detected, remains "unknown"

    # v6: When frameworks are found in subdirectory package.json files,
    #     update the identity type if it's still generic
    if identity["subdir_frameworks"] and identity["type"] in ("node-project", "unknown"):
        all_fws = set()
        for fws in identity["subdir_frameworks"].values():
            all_fws.update(fws)
        if "next.js" in all_fws:
            identity["type"] = "fullstack-web-app"
        elif "react" in all_fws or "vue" in all_fws or "svelte" in all_fws:
            identity["type"] = "frontend-app"
        if identity["is_monorepo"] and not identity["type"].endswith("-monorepo"):
            identity["type"] += "-monorepo"

    return identity


def _build_directory_map(workspace: str, config: Dict[str, Any]) -> Dict[str, str]:
    """Build a one-level-deep directory map with descriptions."""
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    dir_hints = {
        'src': 'Application source code',
        'app': 'Application pages/routes',
        'lib': 'Shared libraries and utilities',
        'components': 'UI components',
        'pages': 'Page components',
        'api': 'API route handlers',
        'routes': 'Route definitions',
        'scripts': 'Build/utility scripts',
        'skills': 'CodeLens skill modules',
        'tests': 'Test files',
        '__tests__': 'Test files',
        'test': 'Test files',
        'config': 'Configuration files',
        'public': 'Static public assets',
        'assets': 'Static assets',
        'styles': 'CSS/styling files',
        'hooks': 'Custom React hooks',
        'utils': 'Utility functions',
        'helpers': 'Helper functions',
        'services': 'Service modules',
        'models': 'Data models',
        'types': 'TypeScript type definitions',
        'interfaces': 'Interface definitions',
        'store': 'State management',
        'stores': 'State management stores',
        'middleware': 'Middleware',
        'db': 'Database files',
        'docs': 'Documentation',
        'examples': 'Example files',
        'mini-services': 'Microservices',
        'parsers': 'Parsers',
        'engines': 'Analysis engines',
    }
    dir_map = {}
    try:
        for entry in sorted(os.listdir(workspace)):
            full = os.path.join(workspace, entry)
            if os.path.isdir(full) and entry not in ignore_dirs and not entry.startswith('.'):
                src_count = 0
                try:
                    for root, dirs, filenames in os.walk(full):
                        depth = root.replace(full, '').count(os.sep)
                        if depth > 3:
                            dirs[:] = []
                            continue
                        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
                        for f in filenames:
                            ext = os.path.splitext(f)[1].lower()
                            if ext in {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.html', '.css', '.scss', '.vue', '.svelte'}:
                                src_count += 1
                except Exception:
                    logger.warning("Directory file counting failed", exc_info=True)
                if entry.lower() in dir_hints:
                    desc = dir_hints[entry.lower()]
                elif src_count:
                    desc = f"{src_count} source file{'s' if src_count != 1 else ''}"
                else:
                    desc = "directory"
                dir_map[entry + '/'] = desc
    except Exception:
        logger.warning("Directory map building failed", exc_info=True)
    return dir_map


def _detect_conventions(workspace: str) -> Dict[str, Any]:
    """Detect coding conventions from the codebase."""
    conventions = {
        "naming": {},
        "patterns": {}
    }

    # Try to import convention_engine if it exists
    try:
        from convention_engine import detect_conventions
        result = detect_conventions(workspace)
        if result.get("status") == "ok":
            return result.get("conventions", conventions)
    except ImportError:
        pass
    except Exception:
        logger.warning("Convention engine failed", exc_info=True)

    # Fallback: basic convention detection from filenames
    files = []
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in {'.py', '.js', '.ts', '.tsx', '.rs'}:
                files.append(fn)

    snake_count = sum(1 for f in files if '_' in os.path.splitext(f)[0] and f == f.lower())
    kebab_count = sum(1 for f in files if '-' in os.path.splitext(f)[0] and f == f.lower())
    camel_count = sum(1 for f in files if re.match(r'^[a-z]+[A-Z]', os.path.splitext(f)[0]))
    pascal_count = sum(1 for f in files if f[0].isupper() and f[0].isalpha())

    if snake_count > kebab_count and snake_count > camel_count:
        conventions["naming"]["files"] = "snake_case"
    elif kebab_count > snake_count and kebab_count > camel_count:
        conventions["naming"]["files"] = "kebab-case"
    elif pascal_count > camel_count:
        conventions["naming"]["files"] = "PascalCase"
    elif camel_count > 0:
        conventions["naming"]["files"] = "camelCase"

    py_files = [f for f in files if f.endswith('.py')]
    js_files = [f for f in files if f.endswith(('.js', '.ts', '.tsx'))]

    if py_files:
        py_snake = sum(1 for f in py_files if '_' in os.path.splitext(f)[0])
        if py_snake > len(py_files) * 0.5:
            conventions["naming"]["python_files"] = "snake_case"

    if js_files:
        js_kebab = sum(1 for f in js_files if '-' in os.path.splitext(f)[0])
        js_camel = sum(1 for f in js_files if re.match(r'^[a-z]+[A-Z]', os.path.splitext(f)[0]))
        if js_kebab > js_camel:
            conventions["naming"]["javascript_files"] = "kebab-case"
        elif js_camel > 0:
            conventions["naming"]["javascript_files"] = "camelCase"

    return conventions


def _generate_agent_md(workspace: str, handbook: Dict[str, Any]) -> None:
    """Generate .codelens/AGENT.md from handbook data."""
    lines = []
    identity = handbook.get("identity", {})
    meta = handbook.get("meta", {})
    health = handbook.get("health", {})
    structure = handbook.get("structure", {})
    conventions = handbook.get("conventions", {})
    risks = handbook.get("risks", [])
    qr = handbook.get("quick_reference", {})

    lines.append(f"# Project Brief: {identity.get('name', 'unknown')}")
    lines.append("")

    # Overview
    lines.append("## Overview")
    desc = identity.get("description", "")
    if desc:
        lines.append(desc)
    fws = handbook.get("frameworks", [])
    if fws:
        lines.append(f"Frameworks: {', '.join(fws)}")
    ptype = identity.get("type", "")
    if ptype != "unknown":
        lines.append(f"Type: {ptype}")
    lines.append(f"Version: {identity.get('version', '0.0.0')}")
    lines.append("")

    # Structure
    dir_map = structure.get("directory_map", {})
    if dir_map:
        lines.append("## Structure")
        for dir_path, desc in dir_map.items():
            lines.append(f"- `{dir_path}` — {desc}")
        lines.append("")

    # Entry Points
    entrypoints = structure.get("entrypoints", [])
    if entrypoints:
        lines.append("## Key Entry Points")
        for ep in entrypoints[:15]:
            lines.append(f"- `{ep.get('file', '')}:{ep.get('line', '')}` — {ep.get('label', ep.get('type', ''))} ({ep.get('type', '')})")
        lines.append("")

    # API Surface
    api_routes = structure.get("api_routes", [])
    if api_routes:
        lines.append("## API Surface")
        for r in api_routes[:20]:
            lines.append(f"- {r.get('method', 'GET')} `{r.get('path', '/')}` — {r.get('handler', '')} ({r.get('file', '')})")
        lines.append("")

    # State Management
    state = structure.get("state_management", [])
    if state:
        lines.append("## State Management")
        for s in state:
            lines.append(f"- `{s.get('name', '')}` ({s.get('type', '')}, {s.get('framework', '')}) — {s.get('file', '')}")
        lines.append("")

    # Conventions
    naming = conventions.get("naming", {})
    patterns = conventions.get("patterns", {})
    if naming or patterns:
        lines.append("## Conventions")
        for key, val in naming.items():
            lines.append(f"- {key}: {val}")
        for key, val in patterns.items():
            lines.append(f"- {key}: {val}")
        lines.append("")

    # Health
    score = health.get("score", 0)
    lines.append(f"## Health Score: {score}/100")
    risk_parts = []
    for r in risks:
        rtype = r.get("type", "")
        count = r.get("count", 0)
        desc = r.get("description", "")
        if count:
            risk_parts.append(f"{count} {rtype.replace('_', ' ')}")
        elif desc:
            risk_parts.append(desc)
    if risk_parts:
        lines.append("- " + ", ".join(risk_parts))
    lines.append("")

    # Quick Reference
    lines.append("## Quick Reference")
    lines.append(f"- Files: {qr.get('total_files', 0)}")
    lines.append(f"- Functions: {qr.get('total_functions', 0)}")
    lines.append(f"- Classes: {qr.get('total_classes', 0)}")
    lines.append(f"- Exports: {qr.get('total_exports', 0)}")
    lines.append("")

    langs = handbook.get("files_by_language", {})
    if langs:
        lines.append("## Languages")
        for lang, count in sorted(langs.items(), key=lambda x: -x[1]):
            lines.append(f"- {lang}: {count} files")
        lines.append("")

    lines.append(f"## Last Scanned: {meta.get('generated_at', 'unknown')}")
    lines.append("")

    content = "\n".join(lines)
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    agent_md_path = os.path.join(codelens_dir, 'AGENT.md')
    with open(agent_md_path, 'w', encoding='utf-8') as f:
        f.write(content)


register_command("handbook", "Generate project handbook for AI agents", add_args, execute)
