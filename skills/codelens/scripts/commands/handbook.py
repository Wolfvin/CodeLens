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


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return cmd_handbook(workspace)


def cmd_handbook(workspace: str) -> Dict[str, Any]:
    """
    Generate a comprehensive project handbook for AI agents.
    Aggregates data from multiple engines into one output.
    Also writes .codelens/handbook.json and .codelens/AGENT.md.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    # 1. Identity — extract from package.json / pyproject.toml / README
    identity = _extract_project_identity(workspace)

    # 2. Run scan first (needed for registry data)
    scan_result = cmd_scan(workspace)

    # 3. Generate output files (outline.json, summary.json)
    try:
        _write_output_files(workspace, scan_result)
    except Exception:
        pass

    # 4. Frameworks
    try:
        fw_result = detect_frameworks(workspace)
        frameworks = fw_result.get("frameworks", [])
    except Exception:
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
        health = {"score": 0, "smells_count": 0, "critical": 0, "warning": 0}

    # 6. Entrypoints
    try:
        ep_result = map_entrypoints(workspace)
        entrypoints = [
            {"type": e.get("type"), "file": e.get("file"), "line": e.get("line"), "label": e.get("label")}
            for e in ep_result.get("entrypoints", [])[:30]
        ]
    except Exception:
        entrypoints = []

    # 7. API Routes
    try:
        api_result = map_api_routes(workspace)
        api_routes = [
            {"method": r.get("method"), "path": r.get("path"), "handler": r.get("handler_name"), "file": r.get("file")}
            for r in api_result.get("routes", [])[:50]
        ]
    except Exception:
        api_routes = []

    # 8. State management
    try:
        state_result = map_state(workspace)
        state_stores = [
            {"name": s.get("name"), "type": s.get("type"), "framework": s.get("framework"), "file": s.get("defined_in")}
            for s in state_result.get("stores", [])[:20]
        ]
    except Exception:
        state_stores = []

    # 9. Risks (circular deps, dead code, secrets)
    risks = []
    try:
        circ_result = detect_circular(workspace)
        for chain in circ_result.get("chains", [])[:5]:
            risks.append({"type": "circular_dep", "description": f"{' → '.join(chain.get('path', []))}"})
    except Exception:
        pass
    try:
        dead_result = detect_dead_code(workspace)
        dead_count = dead_result.get("stats", {}).get("total_dead", 0)
        if dead_count > 0:
            risks.append({"type": "dead_code", "count": dead_count})
    except Exception:
        pass
    try:
        secrets_result = detect_secrets(workspace)
        secrets_count = secrets_result.get("stats", {}).get("total_secrets", 0)
        if secrets_count > 0:
            risks.append({"type": "secrets", "count": secrets_count})
    except Exception:
        pass
    try:
        vuln_result = scan_vulnerabilities(workspace)
        vuln_count = vuln_result.get("stats", {}).get("total_vulnerabilities", 0)
        if vuln_count > 0:
            risks.append({"type": "vulnerabilities", "count": vuln_count})
    except Exception:
        pass

    # 10. Directory map
    directory_map = _build_directory_map(workspace, config)

    # 11. Quick reference from summary
    try:
        summary = _compute_summary(workspace, get_workspace_outline(workspace), scan_result)
    except Exception:
        summary = {}

    # 12. Conventions
    conventions = _detect_conventions(workspace)

    # Build handbook
    handbook = {
        "status": "ok",
        "meta": {
            "workspace": workspace,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "codelens_version": "5.2.0"
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
    """Extract project identity from package.json, pyproject.toml, or README."""
    identity = {
        "name": os.path.basename(workspace),
        "description": "",
        "version": "0.0.0",
        "type": "unknown"
    }

    # Try package.json
    pkg_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path, 'r', encoding='utf-8') as f:
                pkg = json.load(f)
            identity["name"] = pkg.get("name", identity["name"])
            identity["version"] = pkg.get("version", identity["version"])
            identity["description"] = pkg.get("description", "")
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "next" in deps:
                identity["type"] = "fullstack-web-app"
            elif "express" in deps or "fastify" in deps or "koa" in deps:
                identity["type"] = "backend-api"
            elif "react" in deps or "vue" in deps or "svelte" in deps:
                identity["type"] = "frontend-app"
            else:
                identity["type"] = "node-project"
        except Exception:
            pass

    # Try pyproject.toml
    pyproject_path = os.path.join(workspace, 'pyproject.toml')
    if os.path.isfile(pyproject_path) and identity["type"] == "unknown":
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
                identity["type"] = "backend-api"
            elif "pytest" in content:
                identity["type"] = "python-library"
            else:
                identity["type"] = "python-project"
        except Exception:
            pass

    # Try Cargo.toml
    cargo_path = os.path.join(workspace, 'Cargo.toml')
    if os.path.isfile(cargo_path) and identity["type"] == "unknown":
        try:
            with open(cargo_path, 'r', encoding='utf-8') as f:
                content = f.read()
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                identity["name"] = name_match.group(1)
            if ver_match:
                identity["version"] = ver_match.group(1)
            identity["type"] = "rust-project"
        except Exception:
            pass

    return identity


def _build_directory_map(workspace: str, config: Dict[str, Any]) -> Dict[str, str]:
    """Build a one-level-deep directory map with descriptions."""
    ignore_dirs = {
        'node_modules', '.git', 'dist', 'build', 'target',
        '__pycache__', '.codelens', '.next', '.cache',
        'vendor', '.venv', 'venv', 'env', '.idea', '.vscode',
        '_archive', 'coverage', '.pytest_cache', '.tox',
    }
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
                    pass
                if entry.lower() in dir_hints:
                    desc = dir_hints[entry.lower()]
                elif src_count:
                    desc = f"{src_count} source file{'s' if src_count != 1 else ''}"
                else:
                    desc = "directory"
                dir_map[entry + '/'] = desc
    except Exception:
        pass
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
        pass

    # Fallback: basic convention detection from filenames
    files = []
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {
            'node_modules', '.git', 'dist', 'build', 'target',
            '__pycache__', '.codelens', '.next', '.cache', 'vendor',
            '.venv', 'venv', 'env', '_archive'
        } and not d.startswith('.')]
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


def _write_output_files(workspace: str, scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """After a scan, generate outline.json and summary.json into .codelens/."""
    try:
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)

        outline_data = get_workspace_outline(workspace)

        outline_path = os.path.join(codelens_dir, 'outline.json')
        with open(outline_path, 'w', encoding='utf-8') as f:
            json.dump(outline_data, f, indent=2, ensure_ascii=False)

        summary = _compute_summary(workspace, outline_data, scan_result)

        summary_path = os.path.join(codelens_dir, 'summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return summary
    except Exception:
        return {}


def _compute_summary(
    workspace: str,
    outline_data: Dict[str, Any],
    scan_result: Dict[str, Any]
) -> Dict[str, Any]:
    """Compute an aggregate summary from outline + scan data."""
    total_functions = 0
    total_classes = 0
    total_interfaces = 0
    total_types = 0
    total_exports = 0
    total_components = 0
    total_imports = 0
    files_by_lang: Dict[str, int] = {}

    for outline in outline_data.get('outlines', []):
        lang = outline.get('language', 'unknown')
        files_by_lang[lang] = files_by_lang.get(lang, 0) + 1

        total_functions += len(outline.get('functions', []))
        total_classes += len(outline.get('classes', []))
        total_interfaces += len(outline.get('interfaces', []))
        total_types += len(outline.get('types', []))
        total_exports += len(outline.get('exports', []))
        total_components += len(outline.get('components', []))
        total_imports += len(outline.get('imports', []))

        for cls in outline.get('classes', []):
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


register_command("handbook", "Generate project handbook for AI agents", add_args, execute)
