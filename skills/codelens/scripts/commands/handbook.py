"""Handbook command — Generate project handbook for AI agents."""

import os
import json
import re
from datetime import datetime, timezone
from typing import Dict, Any, Optional

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
    parser.add_argument("--quick", "-q", action="store_true",
                        help="Quick mode — skip expensive engines (secrets, vuln-scan, circular, dead-code)")


def execute(args, workspace):
    quick_mode = getattr(args, 'quick', False)
    return cmd_handbook(workspace, quick_mode=quick_mode)


def cmd_handbook(workspace: str, quick_mode: bool = False) -> Dict[str, Any]:
    """
    Generate a comprehensive project handbook for AI agents.
    Aggregates data from multiple engines into one output.
    Also writes .codelens/handbook.json and .codelens/AGENT.md.

    Args:
        workspace: Absolute path to workspace root.
        quick_mode: If True, skip expensive engines for faster results.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    # Track engine success/failure for status propagation
    engines_ok = []
    engines_failed = []

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
        engines_ok.append("frameworks")
    except Exception:
        logger.warning("Framework detection failed", exc_info=True)
        frameworks = config.get("frameworks", [])
        engines_failed.append("frameworks")

    # 5. Health (from smell engine)
    try:
        smell_result = detect_smells(workspace)
        health = {
            "score": smell_result.get("stats", {}).get("health_score", 0),
            "smells_count": smell_result.get("stats", {}).get("total_smells", 0),
            "critical": smell_result.get("stats", {}).get("critical", 0),
            "warning": smell_result.get("stats", {}).get("warning", 0),
        }
        engines_ok.append("smell")
    except Exception:
        logger.warning("Health detection failed", exc_info=True)
        health = {"score": 0, "smells_count": 0, "critical": 0, "warning": 0}
        engines_failed.append("smell")

    # 6. Entrypoints
    try:
        ep_result = map_entrypoints(workspace)
        entrypoints = [
            {"type": e.get("type"), "file": e.get("file"), "line": e.get("line"), "label": e.get("label")}
            for e in ep_result.get("entrypoints", [])[:30]
        ]
        engines_ok.append("entrypoints")
    except Exception:
        logger.warning("Entrypoint mapping failed", exc_info=True)
        entrypoints = []
        engines_failed.append("entrypoints")

    # 7. API Routes
    try:
        api_result = map_api_routes(workspace)
        api_routes = [
            {"method": r.get("method"), "path": r.get("path"), "handler": r.get("handler_name"), "file": r.get("file")}
            for r in api_result.get("routes", [])[:50]
        ]
        # v6.2: Extract Tauri IPC bridge information
        tauri_ipc_bridge = _extract_tauri_ipc_bridge(api_result)
        engines_ok.append("api-map")
    except Exception:
        logger.warning("API route mapping failed", exc_info=True)
        api_routes = []
        tauri_ipc_bridge = None
        engines_failed.append("api-map")

    # 8. State management
    try:
        state_result = map_state(workspace)
        state_stores = [
            {"name": s.get("name"), "type": s.get("type"), "framework": s.get("framework"), "file": s.get("defined_in")}
            for s in state_result.get("stores", [])[:20]
        ]
        engines_ok.append("state-map")
    except Exception:
        logger.warning("State management mapping failed", exc_info=True)
        state_stores = []
        engines_failed.append("state-map")

    # 9. Risks (circular deps, dead code, secrets) — skipped in quick mode
    risks = []
    if not quick_mode:
        try:
            circ_result = detect_circular(workspace)
            for chain in circ_result.get("chains", [])[:5]:
                risks.append({"type": "circular_dep", "description": f"{' → '.join(chain.get('path', []))}"})
            engines_ok.append("circular")
        except Exception:
            logger.warning("Circular dependency detection failed", exc_info=True)
            engines_failed.append("circular")
        try:
            dead_result = detect_dead_code(workspace)
            dead_count = dead_result.get("stats", {}).get("total_dead", 0)
            if dead_count > 0:
                risks.append({"type": "dead_code", "count": dead_count})
            engines_ok.append("dead-code")
        except Exception:
            logger.warning("Dead code detection failed", exc_info=True)
            engines_failed.append("dead-code")
        try:
            secrets_result = detect_secrets(workspace)
            secrets_count = secrets_result.get("stats", {}).get("total_secrets", 0)
            if secrets_count > 0:
                risks.append({"type": "secrets", "count": secrets_count})
            engines_ok.append("secrets")
        except Exception:
            logger.warning("Secrets detection failed", exc_info=True)
            engines_failed.append("secrets")
        try:
            vuln_result = scan_vulnerabilities(workspace)
            vuln_count = vuln_result.get("stats", {}).get("total_vulnerabilities", 0)
            if vuln_count > 0:
                risks.append({"type": "vulnerabilities", "count": vuln_count})
            engines_ok.append("vuln-scan")
        except Exception:
            logger.warning("Vulnerability scan failed", exc_info=True)
            engines_failed.append("vuln-scan")
    else:
        risks.append({"type": "quick_mode", "note": "Risk engines skipped. Use without --quick for full analysis."})

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
    overall_status = "ok" if not engines_failed else ("degraded" if engines_ok else "error")
    handbook = {
        "status": overall_status,
        "meta": {
            "workspace": workspace,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "codelens_version": CODELENS_VERSION,
            "quick_mode": quick_mode,
            "engines_ok": engines_ok,
            "engines_failed": engines_failed,
        },
        "identity": identity,
        "frameworks": frameworks,
        "structure": {
            "directory_map": directory_map,
            "entrypoints": entrypoints,
            "api_routes": api_routes,
            "state_management": state_stores,
            **({"tauri_ipc_bridge": tauri_ipc_bridge} if tauri_ipc_bridge else {}),
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
                    logger.debug("Sub-directory package.json parsing failed", exc_info=True)
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

    # v6: Combined type detection — handle polyglot projects
    active_types = [t for t in [js_type, python_type, rust_type] if t is not None]

    # Check for Tauri desktop app pattern
    has_tauri = False
    for root, dirs, files in os.walk(workspace):
        skip = False
        for ignore in DEFAULT_IGNORE_DIRS:
            if ignore in root:
                skip = True
                break
        if skip or '.codelens' in root:
            continue
        if 'src-tauri' in dirs or any(f in files for f in ('tauri.conf.json', 'Tauri.toml')):
            has_tauri = True
            break
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]

    if len(active_types) >= 2:
        # Polyglot project — build a combined type string
        type_parts = []
        if rust_type:
            type_parts.append("rust")
        if js_type:
            type_parts.append("typescript" if "typescript" in (js_type or "") else "js")
        if python_type:
            type_parts.append("python")
        if has_tauri:
            type_parts.append("tauri")
        identity["type"] = "-".join(type_parts) + "-monorepo" if identity["is_monorepo"] else "-".join(type_parts) + "-polyglot"
    elif len(active_types) == 1:
        identity["type"] = active_types[0]
        # v6: If monorepo indicators found, append -monorepo suffix
        if identity["is_monorepo"]:
            identity["type"] = active_types[0] + "-monorepo"
        # Tauri app: even single-type projects get tauri label
        if has_tauri:
            identity["type"] = "tauri-" + identity["type"]
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


def _extract_tauri_ipc_bridge(api_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract Tauri IPC bridge information from the API map result.

    Returns a dict with:
    - ipc_calls: List of invoke() calls from the frontend
    - ipc_handlers: List of #[tauri::command] handlers from Rust
    - matched_pairs: invoke() calls matched to their Rust handlers
    - unmatched_calls: Frontend invoke() calls with no matching Rust handler
    - unmatched_handlers: Rust commands with no matching invoke() call

    Returns None if no Tauri IPC routes were detected.
    """
    routes = api_result.get("routes", [])
    frameworks = api_result.get("frameworks_detected", [])

    # Check if Tauri IPC was detected
    is_tauri_ipc = any(
        f == "tauri_ipc" or (isinstance(f, str) and "tauri" in f.lower())
        for f in (frameworks if isinstance(frameworks, (list, set)) else [])
    )

    ipc_calls = [r for r in routes if r.get("method") == "IPC_CALL"]
    ipc_handlers = [r for r in routes if r.get("method") == "IPC_HANDLER"]

    # Also check for IPC patterns in regular routes (legacy path)
    if not ipc_calls and not ipc_handlers:
        return None

    # Match IPC calls to handlers
    # Handles both standard Tauri naming (camelCase invoke → camelCase ipc_name)
    # and non-standard naming (snake_case invoke → matches Rust fn_name directly)
    matched_pairs = []
    matched_call_files = set()
    matched_handler_files = set()
    matched_handler_indices = set()

    def _snake_to_camel(name):
        """Convert snake_case to camelCase."""
        if '_' not in name:
            return name
        parts = name.split('_')
        return parts[0] + ''.join(p.capitalize() for p in parts[1:] if p)

    for call in ipc_calls:
        call_name = call.get("handler_name_ipc", call.get("handler_name", ""))
        matched_handler = None

        for idx, handler in enumerate(ipc_handlers):
            if idx in matched_handler_indices:
                continue

            handler_ipc_name = handler.get("handler_name_ipc", handler.get("handler_name", ""))
            handler_fn_name = handler.get("rust_fn_name", handler.get("handler_name", ""))

            # Try multiple matching strategies
            if (call_name == handler_ipc_name or              # Direct match
                call_name == handler_fn_name or                # snake_case match
                _snake_to_camel(call_name) == handler_ipc_name or  # snake→camel match
                call_name == handler_fn_name.replace('_', '')):    # Fuzzy match
                matched_handler = handler
                matched_handler_indices.add(idx)
                break

        if matched_handler:
            matched_pairs.append({
                "ipc_name": call_name,
                "frontend_call": {"file": call.get("file"), "line": call.get("line")},
                "rust_handler": {"file": matched_handler.get("file"), "line": matched_handler.get("line"), "fn": matched_handler.get("rust_fn_name", matched_handler.get("handler_name", ""))},
            })
            matched_call_files.add(call.get("file", ""))
            matched_handler_files.add(matched_handler.get("file", ""))

    # Find unmatched
    matched_call_names = {p["ipc_name"] for p in matched_pairs}
    matched_handler_names = {h.get("handler_name_ipc", h.get("handler_name", "")) for idx, h in enumerate(ipc_handlers) if idx in matched_handler_indices}
    unmatched_calls = [
        {"ipc_name": c.get("handler_name_ipc", c.get("handler_name", "")), "file": c.get("file"), "line": c.get("line")}
        for c in ipc_calls
        if c.get("handler_name_ipc", c.get("handler_name", "")) not in matched_call_names
    ]
    unmatched_handlers = [
        {"ipc_name": h.get("handler_name_ipc", h.get("handler_name", "")), "rust_fn": h.get("rust_fn_name", h.get("handler_name", "")), "file": h.get("file"), "line": h.get("line")}
        for idx, h in enumerate(ipc_handlers)
        if idx not in matched_handler_indices
    ]

    return {
        "total_ipc_calls": len(ipc_calls),
        "total_ipc_handlers": len(ipc_handlers),
        "matched_pairs": matched_pairs[:50],
        "unmatched_calls": unmatched_calls[:20],
        "unmatched_handlers": unmatched_handlers[:20],
        "call_source_files": sorted(matched_call_files),
        "handler_source_files": sorted(matched_handler_files),
    }


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
