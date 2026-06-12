"""Handbook command — Generate project handbook for AI agents."""

import os
import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, List

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
    parser.add_argument("--timeout", type=int, default=180,
                        help="Total time budget in seconds for handbook generation (default: 180). "
                             "Remaining engines are skipped when budget is nearly exhausted.")


def execute(args, workspace):
    max_files = getattr(args, 'max_files', 5000)
    timeout = getattr(args, 'timeout', 180)
    return cmd_handbook(workspace, max_files=max_files, time_budget=timeout)


def cmd_handbook(workspace: str, max_files: int = 5000, time_budget: int = 180) -> Dict[str, Any]:
    """
    Generate a comprehensive project handbook for AI agents.
    Aggregates data from multiple engines into one output.
    Also writes .codelens/handbook.json and .codelens/AGENT.md.
    max_files caps the scan file count to prevent timeout on huge repos.
    time_budget sets a total wall-clock budget (seconds). When less than 15s
    remain, remaining engines are skipped and partial=True is set in output.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    start_time = time.monotonic()
    engines_skipped: List[str] = []

    def _remaining() -> float:
        """Return remaining seconds before budget expires."""
        return time_budget - (time.monotonic() - start_time)

    def _should_skip(engine_name: str) -> bool:
        """Check if we should skip an engine due to time budget."""
        remaining = time_budget - (time.monotonic() - start_time)
        if remaining < 30:  # Need at least 30s remaining to start an engine
            engines_skipped.append(engine_name)
            logger.warning(f"Skipping {engine_name}: time budget nearly exhausted "
                           f"({remaining:.1f}s remaining)")
            return True
        return False

    # 1. Identity — extract from package.json / pyproject.toml / README
    identity = _extract_project_identity(workspace)

    # 2. Run scan first (needed for registry data) — skip if registry is fresh
    scan_result = None
    registry_path = os.path.join(workspace, '.codelens', 'backend.json')
    if os.path.exists(registry_path):
        try:
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
        if _should_skip('scan'):
            scan_result = {"status": "skipped"}
        else:
            scan_result = cmd_scan(workspace)

    # 3. Generate output files (outline.json, summary.json)
    try:
        write_output_files(workspace, scan_result)
    except Exception:
        logger.warning("Failed to write output files", exc_info=True)

    # 4. Frameworks
    frameworks = config.get("frameworks", [])
    if _should_skip('frameworks'):
        pass  # keep default from config
    else:
        try:
            fw_result = detect_frameworks(workspace)
            frameworks = fw_result.get("frameworks", [])
        except Exception:
            logger.warning("Framework detection failed", exc_info=True)

    # 5. Health (from smell engine)
    health = {"score": 0, "smells_count": 0, "critical": 0, "warning": 0}
    if _should_skip('smell'):
        pass
    else:
        try:
            smell_result = detect_smells(workspace, max_files=max_files)
            health = {
                "score": smell_result.get("stats", {}).get("health_score", 0),
                "smells_count": smell_result.get("stats", {}).get("total_smells", 0),
                "critical": smell_result.get("stats", {}).get("critical", 0),
                "warning": smell_result.get("stats", {}).get("warning", 0),
            }
        except Exception:
            logger.warning("Health detection failed", exc_info=True)

    # 6. Entrypoints
    entrypoints = []
    if _should_skip('entrypoints'):
        pass
    else:
        try:
            ep_result = map_entrypoints(workspace, exclude_tests=True, max_files=max_files)
            entrypoints = [
                {"type": e.get("type"), "file": e.get("file"), "line": e.get("line"), "label": e.get("label")}
                for e in ep_result.get("entrypoints", [])[:30]
            ]
        except Exception:
            logger.warning("Entrypoint mapping failed", exc_info=True)

    # 7. API Routes
    api_routes = []
    if _should_skip('apimap'):
        pass
    else:
        try:
            api_result = map_api_routes(workspace)
            api_routes = [
                {"method": r.get("method"), "path": r.get("path"), "handler": r.get("handler_name"), "file": r.get("file")}
                for r in api_result.get("routes", [])[:50]
            ]
        except Exception:
            logger.warning("API route mapping failed", exc_info=True)

    # 8. State management
    state_stores = []
    if _should_skip('statemap'):
        pass
    else:
        try:
            state_result = map_state(workspace)
            state_stores = [
                {"name": s.get("name"), "type": s.get("type"), "framework": s.get("framework"), "file": s.get("defined_in")}
                for s in state_result.get("stores", [])[:20]
            ]
        except Exception:
            logger.warning("State management mapping failed", exc_info=True)

    # 9. Risks (circular deps, dead code, secrets, vulnscan)
    risks = []
    if not _should_skip('circular'):
        try:
            circ_result = detect_circular(workspace)
            for chain in circ_result.get("chains", [])[:5]:
                risks.append({"type": "circular_dep", "description": f"{' → '.join(chain.get('path', []))}"})
        except Exception:
            logger.warning("Circular dependency detection failed", exc_info=True)
    if not _should_skip('deadcode'):
        try:
            dead_result = detect_dead_code(workspace)
            dead_count = dead_result.get("stats", {}).get("total_dead", 0)
            if dead_count > 0:
                risks.append({"type": "dead_code", "count": dead_count})
        except Exception:
            logger.warning("Dead code detection failed", exc_info=True)
    if not _should_skip('secrets'):
        try:
            secrets_result = detect_secrets(workspace)
            secrets_count = secrets_result.get("stats", {}).get("total_secrets", 0)
            if secrets_count > 0:
                risks.append({"type": "secrets", "count": secrets_count})
        except Exception:
            logger.warning("Secrets detection failed", exc_info=True)
    if not _should_skip('vulnscan'):
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
    summary = {}
    if not _should_skip('summary'):
        try:
            summary = compute_summary(workspace, get_workspace_outline(workspace), scan_result)
        except Exception:
            logger.warning("Summary computation failed", exc_info=True)

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

    # Add partial metadata if any engines were skipped due to time budget
    if engines_skipped:
        handbook["partial"] = True
        handbook["time_budget_used"] = round(time.monotonic() - start_time, 2)
        handbook["time_budget_total"] = time_budget
        handbook["engines_skipped"] = engines_skipped

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
            # v6.1: Detect library vs application from package.json fields
            # Libraries have: main, module, types, files, sideEffects
            # and typically no "scripts.start" or "scripts.dev"
            is_library = (
                "main" in pkg or "module" in pkg or "exports" in pkg
            ) and (
                "files" in pkg or "sideEffects" in pkg
                or "typings" in pkg or "types" in pkg
            )
            # Also check: if there's no "start" or "dev" script, it's likely a library
            scripts = pkg.get("scripts", {})
            # v6.1: Consider script purpose — "start": "yarn storybook" is NOT an app script
            start_script = scripts.get("start", "")
            has_app_script = (
                ("start" in scripts and "storybook" not in start_script.lower())
                or "dev" in scripts
                or "serve" in scripts
            )

            if "next" in deps:
                js_type = "fullstack-web-app"
            elif "express" in deps or "fastify" in deps or "koa" in deps:
                js_type = "backend-api"
            elif is_library and not has_app_script:
                js_type = "frontend-library"
            elif "react" in deps or "vue" in deps or "svelte" in deps:
                js_type = "frontend-app"
            else:
                js_type = "node-project"
        except Exception:
            logger.warning("package.json parsing failed", exc_info=True)

    # v6: Walk sub-directories for nested package.json (apps/*, packages/*)
    _MONOREPO_SUBDIRS = ["apps", "packages", "services"]
    _monorepo_subdir_count = 0  # track how many sub-packages found
    for subdir in _MONOREPO_SUBDIRS:
        subdir_path = os.path.join(workspace, subdir)
        if not os.path.isdir(subdir_path):
            continue
        try:
            for entry in sorted(os.listdir(subdir_path)):
                entry_pkg = os.path.join(subdir_path, entry, "package.json")
                if not os.path.isfile(entry_pkg):
                    continue
                _monorepo_subdir_count += 1
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

    # v6.3: If we found 2+ sub-packages in apps/packages/services, mark as monorepo
    if _monorepo_subdir_count >= 2 and not identity["is_monorepo"]:
        identity["is_monorepo"] = True
        if "yarn-workspace" not in identity["monorepo_tools"]:
            identity["monorepo_tools"].append("yarn-workspace")

    # v6.3: Also check root package.json for "workspaces" field (npm/yarn workspaces)
    if has_package_json and not identity["is_monorepo"]:
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            workspaces = pkg.get("workspaces")
            if workspaces:
                identity["is_monorepo"] = True
                if "npm-workspaces" not in identity["monorepo_tools"]:
                    identity["monorepo_tools"].append("npm-workspaces")
        except Exception:
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
            if "fastapi" in content or "flask" in content or "django" in content:
                python_type = "backend-api"
            elif "pytest" in content:
                python_type = "python-library"
            else:
                python_type = "python-project"
        except Exception:
            logger.warning("pyproject.toml parsing failed", exc_info=True)

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

    # v6.4: Detect PHP projects via composer.json
    php_type = None
    composer_path = os.path.join(workspace, 'composer.json')
    if os.path.isfile(composer_path):
        try:
            with open(composer_path, 'r', encoding='utf-8') as f:
                composer_data = json.load(f)
            php_name = composer_data.get('name', '')
            if php_name:
                identity["name"] = php_name.split('/')[-1]
            php_version = composer_data.get('version', '')
            if php_version:
                identity["version"] = php_version
            # Detect PHP framework from require dependencies
            php_req = composer_data.get('require', {})
            php_req_str = ' '.join(php_req.keys()).lower()
            if 'laravel/framework' in php_req or 'laravel/laravel' in php_req:
                php_type = "laravel-app"
            elif 'symfony/symfony' in php_req or 'symfony/framework-bundle' in php_req:
                php_type = "symfony-app"
            elif 'slim/slim' in php_req:
                php_type = "slim-app"
            elif 'laravel/lumen' in php_req:
                php_type = "lumen-app"
            elif 'cakephp/cakephp' in php_req:
                php_type = "cakephp-app"
            elif 'drupal/core' in php_req or 'drupal/drupal' in php_req:
                php_type = "drupal-app"
            elif 'wordpress' in php_req_str or os.path.isfile(os.path.join(workspace, 'wp-config.php')):
                php_type = "wordpress-app"
            else:
                php_type = "php-project"
        except Exception:
            logger.warning("composer.json parsing failed", exc_info=True)

    # v6.4: Detect C/C++ projects
    c_cpp_type = None
    cmake_path = os.path.join(workspace, 'CMakeLists.txt')
    makefile_path = os.path.join(workspace, 'Makefile')
    gnu_makefile_path = os.path.join(workspace, 'GNUmakefile')
    configure_ac_path = os.path.join(workspace, 'configure.ac')

    # Check for CMake project
    if os.path.isfile(cmake_path):
        try:
            with open(cmake_path, 'r', encoding='utf-8') as f:
                cmake_content = f.read()
            # Extract project name and version from cmake
            proj_match = re.search(r'project\s*\(\s*(\w+)', cmake_content)
            ver_match = re.search(r'project\s*\(\s*\w+\s+VERSION\s+(\S+)', cmake_content)
            if proj_match:
                identity["name"] = proj_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            c_cpp_type = "cmake-project"
        except Exception:
            pass

    # Check for autotools/autoconf project (nginx-style)
    if not c_cpp_type and os.path.isfile(configure_ac_path):
        try:
            with open(configure_ac_path, 'r', encoding='utf-8') as f:
                configure_content = f.read()
            # Extract project name from AC_INIT
            ac_init = re.search(r'AC_INIT\s*\(\s*\[?(\w+)', configure_content)
            ver_init = re.search(r'AC_INIT\s*\(\s*\[?\w+\]?\s*,\s*\[?(\S+?)\]?\s*[,)]', configure_content)
            if ac_init:
                identity["name"] = ac_init.group(1)
            if ver_init:
                identity["version"] = ver_init.group(1)
            c_cpp_type = "autotools-project"
        except Exception:
            pass

    # Check for Makefile-based C/C++ project
    if not c_cpp_type and (os.path.isfile(makefile_path) or os.path.isfile(gnu_makefile_path)):
        # Heuristic: if there are .c/.cpp files and a Makefile, it's a C/C++ project
        c_files = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for f in files:
                if f.endswith(('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp')):
                    c_files += 1
                    if c_files >= 3:
                        break
            if c_files >= 3:
                break
        if c_files >= 3:
            c_cpp_type = "c-cpp-project"

    # Check for C/C++ project with many source files but no build system file
    if not c_cpp_type:
        c_file_count = 0
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            for f in files:
                if f.endswith(('.c', '.cpp', '.cc', '.cxx', '.h', '.hpp')):
                    c_file_count += 1
        if c_file_count >= 10:
            c_cpp_type = "c-cpp-project"

    # v6.4: Detect Lua projects
    lua_type = None
    rockspec_files = [f for f in os.listdir(workspace) if f.endswith('.rockspec')] if os.path.isdir(workspace) else []
    if rockspec_files:
        lua_type = "lua-rockspec-project"
    elif os.path.isfile(os.path.join(workspace, 'init.lua')):
        # Check if it's a Neovim plugin (has lua/ directory with init.lua at root)
        lua_dir = os.path.join(workspace, 'lua')
        if os.path.isdir(lua_dir):
            lua_type = "neovim-plugin"
        else:
            lua_type = "lua-project"

    # v6.5: Detect Elixir projects from mix.exs
    elixir_type = None
    mix_exs_path = os.path.join(workspace, 'mix.exs')
    has_mix_exs = os.path.isfile(mix_exs_path)
    if has_mix_exs:
        try:
            with open(mix_exs_path, 'r', encoding='utf-8') as f:
                mix_content = f.read()
            # Extract app name and version from project function
            # Pattern: app: :atom_name
            app_match = re.search(r'app:\s*:(\w+)', mix_content)
            # Pattern: @version "x.y.z" or version: @version or version: "x.y.z"
            ver_match = re.search(r'@version\s+["\']([^"\']+)["\']', mix_content)
            if not ver_match:
                ver_match = re.search(r'version:\s*["\']([^"\']+)["\']', mix_content)
            # Pattern: description: "..."
            desc_match = re.search(r'description:\s*["\']([^"\']+)["\']', mix_content)
            if app_match:
                identity["name"] = app_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            if desc_match:
                identity["description"] = desc_match.group(1)
            # Detect Elixir framework type from deps
            hex_deps = set()
            for m_dep in re.finditer(r'\{:([\w_]+)\s*,', mix_content):
                hex_deps.add(m_dep.group(1).lower())
            if 'phoenix' in hex_deps or 'phoenix_pubsub' in hex_deps:
                elixir_type = "phoenix-web-framework"
            elif 'ecto' in hex_deps or 'ecto_sql' in hex_deps:
                elixir_type = "elixir-data-app"
            elif 'oban' in hex_deps:
                elixir_type = "elixir-worker-app"
            elif 'nerves' in hex_deps:
                elixir_type = "elixir-embedded-app"
            elif 'plug' in hex_deps:
                elixir_type = "elixir-web-app"
            else:
                # Check if this IS the Phoenix framework source itself
                if os.path.isfile(os.path.join(workspace, 'lib', 'phoenix.ex')):
                    elixir_type = "phoenix-web-framework"
                elif re.search(r'defmodule\s+Phoenix\.', mix_content):
                    elixir_type = "phoenix-web-framework"
                else:
                    elixir_type = "elixir-project"
        except Exception:
            logger.warning("mix.exs parsing failed", exc_info=True)
            elixir_type = "elixir-project"

    # v6.4: Combined type detection — handle polyglot projects
    active_types = [t for t in [js_type, python_type, rust_type, go_type, php_type, c_cpp_type, lua_type, elixir_type] if t is not None]

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
        if php_type:
            type_parts.append("php")
        if c_cpp_type:
            type_parts.append("c-cpp")
        if lua_type:
            type_parts.append("lua")
        if elixir_type:
            type_parts.append("elixir")
        identity["type"] = "-".join(type_parts) + "-monorepo" if identity["is_monorepo"] else "-".join(type_parts) + "-polyglot"
    elif len(active_types) == 1:
        identity["type"] = active_types[0]
        # v6: If monorepo indicators found, append -monorepo suffix
        if identity["is_monorepo"]:
            identity["type"] = active_types[0] + "-monorepo"
    # If no type detected, remains "unknown"

    # v6.5: Priority fix — if Elixir type was detected AND Elixir files outnumber JS files,
    # the Elixir type should take precedence over a JS type derived from a minor package.json
    # (e.g., Phoenix has a package.json for its JS client, but it's primarily an Elixir project)
    if elixir_type and js_type:
        ex_count = 0
        js_count = 0
        try:
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
                if '.codelens' in root:
                    dirs.clear()
                    continue
                for fn in filenames:
                    if fn.endswith(('.ex', '.exs')):
                        ex_count += 1
                    elif fn.endswith(('.js', '.ts', '.tsx', '.jsx', '.mjs', '.cjs')):
                        js_count += 1
        except Exception:
            pass
        if ex_count > js_count:
            # Elixir is the primary language — override the type
            identity["type"] = elixir_type
            if identity["is_monorepo"] and not identity["type"].endswith("-monorepo"):
                identity["type"] += "-monorepo"

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
