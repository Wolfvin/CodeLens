#!/usr/bin/env python3
"""
CodeLens v5 — Live Codebase Reference Intelligence (Tree-sitter Edition)

Usage:
    python3 codelens.py scan <workspace>              # Scan workspace and build registry
    python3 codelens.py query <name> <workspace>      # Query a specific class/id/function
    python3 codelens.py list <workspace> [filter]      # List entries with filter
    python3 codelens.py watch <workspace>              # Start file watcher
    python3 codelens.py init <workspace>               # Initialize .codelens config
    python3 codelens.py detect <workspace>             # Detect frameworks
    python3 codelens.py search <pattern> <workspace>   # Search code pattern across workspace
    python3 codelens.py trace <name> <workspace>       # Trace deep call chain
    python3 codelens.py impact <name> <workspace>      # Analyze change impact
    python3 codelens.py outline <workspace> [--file path]    # Get file structure outline
    python3 codelens.py missing-refs <workspace>       # Detect CSS/HTML mismatches
    python3 codelens.py diff <workspace>               # Compare registry snapshots
    python3 codelens.py circular <workspace>           # Detect circular dependencies
    python3 codelens.py context <name> <workspace>     # Get rich symbol context
    python3 codelens.py dependents <file> <workspace>  # Module-level import tracking
    python3 codelens.py validate <workspace>           # Validate registry vs file system
    python3 codelens.py dataflow <workspace>           # Trace data flow source→sink
    python3 codelens.py smell <workspace>              # Detect code smells
    python3 codelens.py side-effect <workspace> [--name func]  # Analyze function side effects
    python3 codelens.py refactor-safe <name> <workspace> # Pre-flight rename/move check
    python3 codelens.py dead-code <workspace>          # Enhanced dead code detection
    python3 codelens.py stack-trace <name> <workspace> # Error propagation simulation
    python3 codelens.py test-map <workspace>           # Test coverage mapping
    python3 codelens.py config-drift <workspace>       # Dependency drift detection
    python3 codelens.py type-infer <workspace>         # Lightweight type inference
    python3 codelens.py ownership <workspace>          # Git blame code ownership
    python3 codelens.py secrets <workspace>            # Detect hardcoded secrets/API keys
    python3 codelens.py entrypoints <workspace>        # Map execution entry points
    python3 codelens.py api-map <workspace>            # Map REST/GraphQL routes to handlers
    python3 codelens.py state-map <workspace>          # Track global state management
    python3 codelens.py env-check <workspace>          # Audit environment variables
    python3 codelens.py debug-leak <workspace>         # Detect leftover debug code
    python3 codelens.py complexity <workspace>         # Compute cyclomatic/cognitive complexity
    python3 codelens.py regex-audit <workspace>        # Audit regex for ReDoS and issues
    python3 codelens.py a11y <workspace>               # Detect accessibility issues
    python3 codelens.py vuln-scan <workspace>          # Scan dependencies for known CVEs
    python3 codelens.py perf-hint <workspace>          # Detect performance anti-patterns
    python3 codelens.py css-deep <workspace>           # Deep CSS analysis (vars, keyframes, specificity)
    python3 codelens.py handbook <workspace>           # Generate project handbook for AI agents
    python3 codelens.py ask <question> [workspace]     # Ask a natural language question about the codebase
"""

import sys
import os
import json
import argparse
import time
import threading
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, save_frontend_registry,
    load_backend_registry, save_backend_registry,
    build_frontend_registry, compute_frontend_status
)
from grammar_loader import get_grammar_loader  # noqa: F401 — used by tree-sitter parsers
from framework_detect import detect_frameworks, get_recommended_config
from incremental import find_changed_files, update_mtimes_cache, remove_from_mtimes_cache
from edge_resolver import resolve_edges, get_callers, get_callees
from search_engine import search_workspace, search_symbols
from trace_engine import trace_symbol
from impact_engine import analyze_impact
from outline_engine import get_file_outline, get_workspace_outline
from missing_refs import detect_missing_refs
from diff_engine import diff_current_vs_last, diff_snapshots, save_snapshot, list_snapshots
from circular_engine import detect_circular
from context_engine import get_symbol_context
from dependents_engine import get_dependents, get_dependencies, get_dependency_graph
from validate_engine import validate_registry
from dataflow_engine import trace_dataflow
from smell_engine import detect_smells
from sideeffect_engine import analyze_side_effects
from refactor_safe_engine import check_refactor_safety
from deadcode_engine import detect_dead_code
from stacktrace_engine import trace_error_propagation
from testmap_engine import map_test_coverage
from configdrift_engine import detect_config_drift
from typeinfer_engine import infer_types
from ownership_engine import analyze_ownership
from secrets_engine import detect_secrets
from entrypoints_engine import map_entrypoints
from apimap_engine import map_api_routes
from statemap_engine import map_state
from envcheck_engine import check_env_vars
from debugleak_engine import detect_debug_leaks
from complexity_engine import compute_complexity
from regexaudit_engine import audit_regex_patterns
from a11y_engine import audit_accessibility
from vulnscan_engine import scan_vulnerabilities
from perfhint_engine import detect_perf_hints
from cssdeep_engine import analyze_css_deep


# ─── Workspace Auto-Detect ─────────────────────────────────────

LAST_WORKSPACE_FILE = ".codelens_last_workspace"


def _save_last_workspace(workspace: str) -> None:
    """Save the last used workspace path to a global cache file."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".codelens")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, LAST_WORKSPACE_FILE)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(os.path.abspath(workspace))
    except IOError:
        pass


def _load_last_workspace() -> Optional[str]:
    """Load the last used workspace path from global cache."""
    cache_path = os.path.join(os.path.expanduser("~"), ".codelens", LAST_WORKSPACE_FILE)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                ws = f.read().strip()
            if ws and os.path.isdir(ws):
                return ws
        except IOError:
            pass
    return None


def _detect_workspace() -> Optional[str]:
    """Auto-detect workspace from current directory or project markers."""
    # Strategy 1: Current working directory if it looks like a project
    cwd = os.getcwd()

    # Project markers that indicate a workspace root
    markers = [
        'package.json', 'Cargo.toml', 'pyproject.toml', 'requirements.txt',
        'go.mod', 'pom.xml', 'build.gradle', 'Gemfile',
        '.git', '.codelens', 'tsconfig.json', 'next.config.js',
        'next.config.ts', 'vite.config.ts', 'vite.config.js',
    ]

    # Check cwd first
    for marker in markers:
        if os.path.exists(os.path.join(cwd, marker)):
            return cwd

    # Strategy 2: Walk up from cwd to find a project root
    parent = os.path.dirname(cwd)
    while parent != os.path.dirname(parent):  # Stop at filesystem root
        for marker in markers:
            if os.path.exists(os.path.join(parent, marker)):
                return parent
        parent = os.path.dirname(parent)

    # Strategy 3: Use cwd as fallback if it has source files
    for ext in ('.py', '.js', '.ts', '.tsx', '.rs', '.html', '.css', '.vue', '.svelte'):
        if any(f.endswith(ext) for f in os.listdir(cwd) if os.path.isfile(os.path.join(cwd, f))):
            return cwd

    # Strategy 4: Use last workspace
    last = _load_last_workspace()
    if last:
        return last

    return None


def resolve_workspace(workspace_arg: Optional[str] = None) -> str:
    """Resolve workspace path with auto-detect fallback chain."""
    if workspace_arg:
        ws = os.path.abspath(workspace_arg)
        if os.path.isdir(ws):
            _save_last_workspace(ws)
            return ws
        else:
            print(f"[CodeLens] Warning: '{workspace_arg}' is not a valid directory. Attempting auto-detect...", file=sys.stderr)

    # Try auto-detect
    detected = _detect_workspace()
    if detected:
        _save_last_workspace(detected)
        return detected

    # Last resort: current directory
    return os.getcwd()


# ─── File Discovery ───────────────────────────────────────────

def is_frontend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a frontend path."""
    for fp in config.get("frontend_paths", []):
        if fp in file_path:
            return True
    return False


def is_backend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a backend path."""
    for bp in config.get("backend_paths", []):
        if bp in file_path:
            return True
    return False


def should_ignore(file_path: str, config: Dict) -> bool:
    """Check if a file should be ignored."""
    for pattern in config.get("ignore", []):
        if pattern in file_path:
            return True
    return False


def discover_files(workspace: str, config: Dict) -> Dict[str, List[str]]:
    """
    Discover all relevant source files in the workspace.

    Returns categorized file lists.
    """
    files = {
        "html": [],
        "css": [],
        "js_frontend": [],
        "js_backend": [],
        "tsx": [],
        "rust": [],
        "python": [],
        "vue": [],
        "svelte": []
    }

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore(rel_root + "/", config) or should_ignore(root, config):
            dirs.clear()
            continue

        # Don't descend into .codelens
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if should_ignore(rel_path, config):
                continue

            ext = os.path.splitext(filename)[1].lower()

            if ext in ('.html', '.htm'):
                files["html"].append(file_path)
            elif ext == '.css':
                files["css"].append(file_path)
            elif ext in ('.jsx',):
                # .jsx files → use TSX parser
                files["tsx"].append(file_path)
            elif ext == '.tsx':
                files["tsx"].append(file_path)
            elif ext in ('.js', '.ts'):
                # .ts files in frontend → TSX parser, .ts in backend → JS backend
                if ext == '.ts' and is_frontend_file(rel_path, config):
                    files["tsx"].append(file_path)
                elif is_frontend_file(rel_path, config):
                    files["js_frontend"].append(file_path)
                elif is_backend_file(rel_path, config):
                    files["js_backend"].append(file_path)
                else:
                    # Default: backend (safer assumption per spec)
                    files["js_backend"].append(file_path)
            elif ext == '.rs':
                files["rust"].append(file_path)
            elif ext == '.py':
                files["python"].append(file_path)
            elif ext == '.vue':
                files["vue"].append(file_path)
            elif ext == '.svelte':
                files["svelte"].append(file_path)
            elif ext in ('.scss', '.less', '.sass'):
                files["css"].append(file_path)

    return files


# ─── Scan Command ─────────────────────────────────────────────

def cmd_scan(workspace: str, incremental: bool = False) -> Dict[str, Any]:
    """
    Scan the workspace and build/update the registry.
    If incremental=True, only re-scan changed files.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    # Auto-detect frameworks if not configured
    if not config.get("frameworks"):
        fw = detect_frameworks(workspace)
        recommended = get_recommended_config(workspace)
        config.update(recommended)
        save_config(workspace, config)

    # Discover files
    files = discover_files(workspace, config)

    # Check if incremental scan is possible
    changed_files = None
    if incremental:
        all_discovered = []
        for file_list in files.values():
            all_discovered.extend(file_list)
        changed, new, deleted = find_changed_files(workspace, all_discovered)

        if not changed and not new and not deleted:
            return {
                "status": "ok",
                "workspace": workspace,
                "message": "No changes detected. Registry is up to date.",
                "files_scanned": {k: 0 for k in files},
                "incremental": True
            }

        # Handle deleted files: remove from mtimes cache and do full rescan
        if deleted:
            remove_from_mtimes_cache(workspace, deleted)
            incremental = False
            changed_files = None
        else:
            changed_files = set(changed + new)

    # Parsers are loaded lazily per-category below

    # Parse HTML files
    html_data = []
    if files["html"]:
        html_parser = None
        try:
            from parsers.html_parser import HTMLParser
            html_parser = HTMLParser()
        except Exception:
            pass

        for path in files["html"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if html_parser:
                    refs = html_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    # Fallback to basic regex
                    refs = _fallback_html_parse(content, os.path.relpath(path, workspace))
                html_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                pass

    # Parse CSS files
    css_data = []
    if files["css"]:
        css_parser = None
        try:
            from parsers.css_parser import CSSParser
            css_parser = CSSParser()
        except Exception:
            pass

        for path in files["css"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if css_parser:
                    refs = css_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = _fallback_css_parse(content, os.path.relpath(path, workspace))
                css_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                pass

    # Parse JS Frontend files
    js_frontend_data = []
    if files["js_frontend"]:
        js_fe_parser = None
        try:
            from parsers.js_frontend_parser import JSFrontendParser
            js_fe_parser = JSFrontendParser()
        except Exception:
            pass

        for path in files["js_frontend"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if js_fe_parser:
                    refs = js_fe_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = _fallback_js_frontend_parse(content, os.path.relpath(path, workspace))
                js_frontend_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                pass

    # Parse TSX/JSX files
    tsx_data = []
    tsx_backend_data = []
    if files["tsx"]:
        tsx_parser = None
        try:
            from parsers.tsx_parser import TSXParser
            tsx_parser = TSXParser()
        except Exception:
            pass

        for path in files["tsx"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if tsx_parser:
                    refs = tsx_parser.extract_references(content, os.path.relpath(path, workspace))
                    tsx_data.append({
                        "path": os.path.relpath(path, workspace),
                        "frontend": refs.get("frontend", {}),
                    })
                    # Also collect backend data from TSX
                    if refs.get("backend"):
                        tsx_backend_data.append({
                            "path": os.path.relpath(path, workspace),
                            "nodes": refs["backend"].get("nodes", []),
                            "edges": refs["backend"].get("edges", [])
                        })
                else:
                    # Fallback: treat as JS frontend
                    fb_refs = _fallback_js_frontend_parse(content, os.path.relpath(path, workspace))
                    tsx_data.append({
                        "path": os.path.relpath(path, workspace),
                        "frontend": fb_refs,
                    })
            except IOError:
                pass

    # Parse Vue files
    vue_data = []
    if files["vue"]:
        try:
            from parsers.vue_parser import parse_vue_sfc
        except ImportError:
            parse_vue_sfc = None

        for path in files["vue"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if parse_vue_sfc:
                    refs = parse_vue_sfc(content, os.path.relpath(path, workspace))
                    vue_data.append(refs)
            except IOError:
                pass

    # Parse Svelte files
    svelte_data = []
    if files["svelte"]:
        try:
            from parsers.svelte_parser import parse_svelte_component
        except ImportError:
            parse_svelte_component = None

        for path in files["svelte"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if parse_svelte_component:
                    refs = parse_svelte_component(content, os.path.relpath(path, workspace))
                    svelte_data.append(refs)
            except IOError:
                pass

    # Tailwind analysis
    tailwind_info = None
    if config.get("tailwind_mode") or config.get("has_tailwind"):
        try:
            from parsers.tailwind_detector import analyze_tailwind_usage
            all_classes = []
            for item in html_data:
                all_classes.extend(item.get("classes", []))
            for item in css_data:
                all_classes.extend(item.get("classes", []))
            for item in js_frontend_data:
                all_classes.extend(item.get("classes", []))
            for item in tsx_data:
                all_classes.extend(item.get("frontend", {}).get("classes", []))

            tailwind_info = analyze_tailwind_usage(workspace, all_classes)
        except Exception:
            pass

    # Build frontend registry
    frontend_registry = build_frontend_registry(
        workspace, html_data, css_data, js_frontend_data,
        tsx_data, vue_data, svelte_data,
        tailwind_info, config.get("frameworks", [])
    )
    save_frontend_registry(workspace, frontend_registry)

    # Parse JS Backend files
    js_backend_data = tsx_backend_data.copy()
    if files["js_backend"]:
        js_be_parser = None
        try:
            from parsers.js_backend_parser import JSBackendParser
            js_be_parser = JSBackendParser()
        except Exception:
            pass

        for path in files["js_backend"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if js_be_parser:
                    refs = js_be_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = _fallback_js_backend_parse(content, os.path.relpath(path, workspace))
                js_backend_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                pass

    # Parse Rust files
    rust_data = []
    if files["rust"]:
        rust_parser = None
        try:
            from parsers.rust_parser import RustParser
            rust_parser = RustParser()
        except Exception:
            pass

        for path in files["rust"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if rust_parser:
                    refs = rust_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = _fallback_rust_parse(content, os.path.relpath(path, workspace))
                rust_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                pass

    # Parse Python files
    python_data = []
    if files["python"]:
        py_parser = None
        try:
            from parsers.python_parser import PythonParser
            py_parser = PythonParser()
        except Exception:
            pass

        for path in files["python"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if py_parser:
                    refs = py_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = _fallback_python_parse(content, os.path.relpath(path, workspace))
                python_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                pass

    # Build backend registry with edge resolution
    all_nodes = []
    all_raw_edges = []
    for item in rust_data + js_backend_data + python_data:
        all_nodes.extend(item.get("nodes", []))
        all_raw_edges.extend(item.get("edges", []))

    resolved_nodes, resolved_edges = resolve_edges(all_nodes, all_raw_edges)

    backend_registry = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "workspace": workspace,
        "nodes": resolved_nodes,
        "edges": resolved_edges
    }
    save_backend_registry(workspace, backend_registry)

    # Update mtimes cache
    all_files = []
    for file_list in files.values():
        all_files.extend(file_list)
    update_mtimes_cache(workspace, all_files)

    return {
        "status": "ok",
        "workspace": workspace,
        "files_scanned": {
            "html": len(files["html"]),
            "css": len(files["css"]),
            "js_frontend": len(files["js_frontend"]),
            "js_backend": len(files["js_backend"]),
            "tsx": len(files["tsx"]),
            "rust": len(files["rust"]),
            "python": len(files["python"]),
            "vue": len(files["vue"]),
            "svelte": len(files["svelte"])
        },
        "python_parsed": len(python_data),
        "frontend": {
            "classes": len(frontend_registry["classes"]),
            "ids": len(frontend_registry["ids"])
        },
        "backend": {
            "nodes": len(resolved_nodes),
            "edges": len(resolved_edges)
        },
        "frameworks": config.get("frameworks", []),
        "incremental": incremental
    }


# ─── Fallback Parsers (when tree-sitter grammars unavailable) ─

def _fallback_html_parse(content, file_path):
    """Basic regex HTML parser fallback."""
    import re
    content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
    ids, classes = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\bid\s*=\s*["\']([^"\']+)["\']', line):
            v = m.group(1).strip()
            if '{{' not in v:
                ids.append({"name": v, "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'\bclass\s*=\s*["\']([^"\']+)["\']', line):
            for cls in m.group(1).split():
                if cls.strip() and '{{' not in cls:
                    classes.append({"name": cls.strip(), "line": line_num, "flag": None, "path": file_path})
    return {"ids": ids, "classes": classes}


def _fallback_css_parse(content, file_path):
    """Basic regex CSS parser fallback."""
    import re
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'@keyframes\s+[^{]+\{[^}]*(?:\{[^}]*\}[^}]*)*\}', '', content, flags=re.DOTALL)
    classes, ids = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'\.([a-zA-Z_][\w-]*)', line):
            classes.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
        # Match # as CSS ID selector only at selector positions (start of line or after whitespace/comma/combinator)
        for m in re.finditer(r'(?:^|[\s,{>+~])#([a-zA-Z_][\w-]*)', line):
            ids.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
    return {"classes": classes, "ids": ids}


def _fallback_js_frontend_parse(content, file_path):
    """Basic regex JS frontend parser fallback."""
    import re
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    classes, ids = [], []
    for line_num, line in enumerate(content.split('\n'), 1):
        for m in re.finditer(r'getElementById\(\s*["\']([^"\']+)["\']\s*\)', line):
            ids.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'querySelector(?:All)?\(\s*["\']([^"\']+)["\']\s*\)', line):
            for cm in re.finditer(r'\.([a-zA-Z_][\w-]*)', m.group(1)):
                classes.append({"name": cm.group(1), "line": line_num, "flag": None, "path": file_path})
            for im in re.finditer(r'#([a-zA-Z_][\w-]*)', m.group(1)):
                ids.append({"name": im.group(1), "line": line_num, "flag": None, "path": file_path})
        for m in re.finditer(r'getElementsByClassName\(\s*["\']([^"\']+)["\']\s*\)', line):
            classes.append({"name": m.group(1), "line": line_num, "flag": None, "path": file_path})
    return {"classes": classes, "ids": ids}


def _fallback_js_backend_parse(content, file_path):
    """Regex-based JS backend parser fallback (when tree-sitter unavailable)."""
    import re
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)

    nodes = []
    edges = []
    fn_map = {}  # name → node_id for edge resolution

    # Skip JS keywords and builtins
    skip_names = {
        'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
        'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
        'async', 'await', 'yield', 'import', 'export', 'from', 'default',
        'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
        'true', 'false', 'null', 'undefined', 'void', 'delete',
        'console', 'require', 'module', 'exports', 'process', 'global',
        'String', 'Number', 'Boolean', 'Array', 'Object', 'Map', 'Set',
        'Promise', 'Error', 'TypeError', 'parseInt', 'parseFloat',
        'JSON', 'Date', 'RegExp', 'Math', 'Buffer',
        'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    }

    # Detect function declarations: function name(...), const name = (), const name = function
    for line_num, line in enumerate(content.split('\n'), 1):
        # function name(
        for m in re.finditer(r'\b(?:async\s+)?function\s+([a-zA-Z_]\w*)\s*\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

        # const/let/var name = ( => arrow function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s*)?\(', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

        # const/let/var name = function
        for m in re.finditer(r'\b(?:const|let|var)\s+([a-zA-Z_]\w*)\s*=\s*(?:async\s+)?function', line):
            name = m.group(1)
            if name not in skip_names and name not in fn_map:
                node_id = f"{file_path}:{line_num}"
                nodes.append({"id": node_id, "fn": name, "file": file_path,
                              "line": line_num, "async": 'async' in line[:m.start()]})
                fn_map[name] = node_id

    # Detect function calls (simplified — within function bodies)
    # For each function found, scan its approximate scope for calls
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1  # 0-indexed
        # Approximate: scan from function start to next function or 50 lines
        end_line = min(start_line + 50, len(lines))
        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    edges.append({"from": node["id"], "to_fn": call_name})

    return {"nodes": nodes, "edges": edges}


def _fallback_rust_parse(content, file_path):
    """Regex-based Rust parser fallback (when tree-sitter unavailable)."""
    import re
    content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)

    nodes = []
    edges = []
    fn_map = {}

    skip_names = {
        'if', 'else', 'for', 'while', 'loop', 'match', 'return', 'break',
        'continue', 'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl',
        'trait', 'use', 'mod', 'crate', 'super', 'self', 'Self',
        'true', 'false', 'as', 'in', 'ref', 'move', 'dyn', 'async', 'await',
        'Some', 'None', 'Ok', 'Err', 'new', 'default',
    }

    current_impl = None

    for line_num, line in enumerate(content.split('\n'), 1):
        # Track impl blocks
        impl_match = re.search(r'\bimpl\s+(?:\w+\s+for\s+)?(\w+)', line)
        if impl_match:
            current_impl = impl_match.group(1)

        # fn name(
        for m in re.finditer(r'\b(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z_]\w*)\s*[\(<]', line):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in line[:m.start()]}
                if current_impl:
                    node_data["impl_for"] = current_impl
                nodes.append(node_data)
                fn_map[name] = node_id

    # Detect function calls (simplified)
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1
        end_line = min(start_line + 50, len(lines))
        for i in range(start_line, end_line):
            if i >= len(lines):
                break
            # Direct calls: name(
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    is_self = bool(re.search(r'\bself\.' + re.escape(call_name), lines[i]))
                    edges.append({"from": node["id"], "to_fn": call_name, "via_self": is_self})

    return {"nodes": nodes, "edges": edges}


def _fallback_python_parse(content, file_path):
    """Regex-based Python parser fallback (when tree-sitter unavailable)."""
    import re

    nodes = []
    edges = []
    fn_map = {}
    current_class = None

    skip_names = {
        'if', 'else', 'elif', 'for', 'while', 'with', 'try', 'except', 'finally',
        'return', 'yield', 'raise', 'break', 'continue', 'pass', 'import', 'from',
        'class', 'def', 'async', 'await', 'lambda', 'global', 'nonlocal',
        'True', 'False', 'None',
        'print', 'len', 'range', 'int', 'str', 'float', 'bool', 'list', 'dict',
        'set', 'tuple', 'type', 'isinstance', 'super', 'property',
        'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
        'iter', 'next', 'abs', 'min', 'max', 'sum', 'any', 'all',
        'self', 'cls',
    }

    for line_num, line in enumerate(content.split('\n'), 1):
        stripped = line.strip()

        # Track class context (dedent = class ended)
        if stripped.startswith('class '):
            class_match = re.match(r'class\s+(\w+)', stripped)
            if class_match:
                current_class = class_match.group(1)

        # Detect indent level to track class scope
        if current_class and not line.startswith(' ') and not line.startswith('\t') and stripped and not stripped.startswith('class '):
            current_class = None

        # def name(
        for m in re.finditer(r'\b(?:async\s+)?def\s+([a-zA-Z_]\w*)\s*\(', stripped):
            name = m.group(1)
            if name not in skip_names:
                node_id = f"{file_path}:{line_num}"
                node_data = {"id": node_id, "fn": name, "file": file_path,
                             "line": line_num, "async": 'async' in stripped[:m.start()]}
                if current_class:
                    node_data["impl_for"] = current_class
                nodes.append(node_data)
                fn_map[name] = node_id

    # Detect function calls (simplified scope scanning)
    lines = content.split('\n')
    for node in nodes:
        start_line = node["line"] - 1
        # Get the indent level of the function definition
        fn_indent = len(lines[start_line]) - len(lines[start_line].lstrip())
        # Scan until dedent back to same or lower level
        end_line = len(lines)
        for i in range(start_line + 1, len(lines)):
            if lines[i].strip() == '':
                continue
            line_indent = len(lines[i]) - len(lines[i].lstrip())
            if line_indent <= fn_indent and lines[i].strip():
                end_line = i
                break

        for i in range(start_line, end_line):
            # Direct calls: name(
            for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', lines[i]):
                call_name = m.group(1)
                if call_name not in skip_names and call_name != node["fn"]:
                    is_self = bool(re.search(r'\bself\.' + re.escape(call_name), lines[i]))
                    edges.append({"from": node["id"], "to_fn": call_name, "via_self": is_self})

    return {"nodes": nodes, "edges": edges}


# ─── Query Decision Tree ────────────────────────────────────────

def _get_query_action(status: str) -> tuple:
    """Return (action, action_reason) based on query result status."""
    if status == "active":
        return ("EXTEND", "Name exists and is active. Do not overwrite — extend or use a different name.")
    elif status == "dead":
        return ("ASK", "Name exists but is dead (unused). Ask user whether to reuse or create new.")
    elif status == "duplicate_ref":
        return ("LIST_FIRST", "Name has duplicate references. List all referrers before making changes.")
    elif status == "collision":
        return ("STOP", "Name collision detected. Fix collision before proceeding.")
    else:
        return ("EXTEND", "Name exists. Proceed with caution.")


# ─── Query Command ────────────────────────────────────────────

def cmd_query(query_name: str, workspace: str, domain: str = None,
               file_filter: str = None) -> Dict[str, Any]:
    """Query a specific class/id/function from the registry."""
    workspace = os.path.abspath(workspace)

    if domain in (None, "frontend"):
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            if cls["name"] == query_name:
                if file_filter and file_filter not in json.dumps(cls):
                    continue
                action, action_reason = _get_query_action(cls["status"])
                return {
                    "found": True,
                    "type": "class",
                    "domain": "frontend",
                    "name": cls["name"],
                    "ref_count": cls["ref_count"],
                    "status": cls["status"],
                    "action": action,
                    "action_reason": action_reason,
                    "css": cls.get("css", []),
                    "js": cls.get("js", [])
                }

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == query_name:
                if file_filter and file_filter not in json.dumps(id_entry):
                    continue
                action, action_reason = _get_query_action(id_entry["status"])
                return {
                    "found": True,
                    "type": "id",
                    "domain": "frontend",
                    "name": id_entry["name"],
                    "ref_count": id_entry["ref_count"],
                    "status": id_entry["status"],
                    "action": action,
                    "action_reason": action_reason,
                    "defined_in_html": id_entry.get("defined_in_html", []),
                    "css": id_entry.get("css", []),
                    "js": id_entry.get("js", [])
                }

    if domain in (None, "backend"):
        backend = load_backend_registry(workspace)

        for node in backend.get("nodes", []):
            if node["fn"] == query_name:
                if file_filter and file_filter not in node.get("file", ""):
                    continue

                callers = get_callers(node["id"], backend.get("edges", []))
                callees = get_callees(node["id"], backend.get("edges", []),
                                       backend.get("nodes", []))

                node_status = node.get("status", "active")
                action, action_reason = _get_query_action(node_status)
                result = {
                    "found": True,
                    "type": "function",
                    "domain": "backend",
                    "action": action,
                    "action_reason": action_reason,
                    "node": {
                        "id": node["id"],
                        "fn": node["fn"],
                        "ref_count": node.get("ref_count", 0),
                        "status": node_status,
                        "file": node.get("file", ""),
                        "line": node.get("line", 0),
                        "async": node.get("async", False)
                    },
                    "callers": callers,
                    "callees": callees
                }

                if node.get("impl_for"):
                    result["node"]["impl_for"] = node["impl_for"]
                if node.get("trait_name"):
                    result["node"]["trait_name"] = node["trait_name"]
                if node.get("component"):
                    result["node"]["component"] = node["component"]
                if node.get("duplicate_define"):
                    result["node"]["duplicate_define"] = True

                return result

    return {
        "found": False,
        "query": query_name,
        "domain": domain or "auto",
        "action": "CREATE",
        "action_reason": "Name does not exist. Safe to create."
    }


# ─── List Command ─────────────────────────────────────────────

def cmd_list(workspace: str, domain: str, filter_type: str = "all") -> Dict[str, Any]:
    """List all entries with optional filter."""
    workspace = os.path.abspath(workspace)
    results = []

    if domain in ("frontend", "all"):
        frontend = load_frontend_registry(workspace)

        for cls in frontend.get("classes", []):
            entry = {
                "type": "class",
                "name": cls["name"],
                "ref_count": cls["ref_count"],
                "status": cls["status"]
            }
            if cls.get("css"):
                entry["defined_in"] = f"{cls['css'][0]['path']}:{cls['css'][0]['line']}"

            if filter_type == "all" or cls["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define":
                for css_ref in cls.get("css", []):
                    if css_ref.get("flag") == "duplicate_define":
                        results.append(entry)
                        break

        for id_entry in frontend.get("ids", []):
            entry = {
                "type": "id",
                "name": id_entry["name"],
                "ref_count": id_entry["ref_count"],
                "status": id_entry["status"]
            }
            if id_entry.get("defined_in_html"):
                entry["defined_in"] = f"{id_entry['defined_in_html'][0]['path']}:{id_entry['defined_in_html'][0]['line']}"

            if filter_type == "all" or id_entry["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define":
                for css_ref in id_entry.get("css", []):
                    if css_ref.get("flag") == "duplicate_define":
                        results.append(entry)
                        break

    if domain in ("backend", "all"):
        backend = load_backend_registry(workspace)

        for node in backend.get("nodes", []):
            entry = {
                "type": "function",
                "name": node["fn"],
                "ref_count": node.get("ref_count", 0),
                "status": node.get("status", "active"),
                "defined_in": f"{node.get('file', '')}:{node.get('line', 0)}"
            }

            if filter_type == "all" or node.get("status") == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define" and node.get("duplicate_define"):
                results.append(entry)

    return {"domain": domain, "filter": filter_type, "count": len(results), "results": results}


# ─── Init Command ─────────────────────────────────────────────

def cmd_init(workspace: str) -> Dict[str, Any]:
    """Initialize .codelens directory with auto-detected config."""
    workspace = os.path.abspath(workspace)
    codelens_dir = ensure_codelens_dir(workspace)

    # Auto-detect frameworks
    recommended = get_recommended_config(workspace)
    save_config(workspace, recommended)

    return {
        "status": "ok",
        "workspace": workspace,
        "codelens_dir": codelens_dir,
        "config": recommended
    }


# ─── Detect Command ──────────────────────────────────────────

def cmd_detect(workspace: str) -> Dict[str, Any]:
    """Detect frameworks and show recommended config."""
    workspace = os.path.abspath(workspace)
    return detect_frameworks(workspace)


# ─── Ask Command (Natural Language Router) ──────────────────────

def cmd_ask(question: str, workspace: str) -> Dict[str, Any]:
    """
    Natural language query router.
    Maps a question to the appropriate CodeLens command and returns its result.
    """
    workspace = os.path.abspath(workspace)
    q = question.lower().strip()

    # Determine which command to run based on keyword patterns
    command, args = _parse_ask_question(q, workspace)

    if command is None:
        return {
            "status": "unknown_query",
            "question": question,
            "workspace": workspace,
            "suggestion": "Could not determine the appropriate command. Try: scan, context, trace, impact, smell, dead-code, secrets, circular, api-map, entrypoints, outline, query, complexity, test-map, perf-hint, vuln-scan"
        }

    # Execute the determined command
    try:
        result = _execute_ask_command(command, args, workspace)
    except Exception as e:
        return {
            "status": "error",
            "question": question,
            "interpreted_as": command,
            "error": str(e)
        }

    # Add interpretation metadata
    if isinstance(result, dict):
        result["query_interpretation"] = {
            "question": question,
            "interpreted_as": command,
            "confidence": args.pop("_confidence", "medium")
        }

    return result


def _parse_ask_question(q: str, workspace: str) -> tuple:
    """Parse a natural language question and determine which command to run."""

    # Patterns: (keyword_patterns, command, extra_args, confidence)
    patterns = [
        # Context / definition queries
        (["where is", "where's", "where does", "find definition", "find def", "show me", "what is", "what's"],
         "context", {"name": _extract_symbol_name}, "high"),

        # Symbol search
        (["search for", "find symbol", "find all", "look for"],
         "symbols", {"name": _extract_symbol_name}, "high"),

        # Dead code
        (["dead code", "unused code", "unreachable", "zombie", "not used", "never called", "orphan"],
         "dead-code", {}, "high"),

        # Security
        (["security", "secret", "api key", "password", "token leak", "vulnerability", "cve", "vuln"],
         "secrets", {}, "high"),

        # Circular dependencies
        (["circular", "cycle", "circular dependency", "circular dep", "dependency cycle"],
         "circular", {}, "high"),

        # API routes
        (["api route", "endpoint", "api map", "rest route", "http route", "graphql"],
         "api-map", {}, "high"),

        # Entrypoints
        (["entry point", "entrypoint", "main function", "where does it start", "how does it start", "boot"],
         "entrypoints", {}, "high"),

        # Smells / health
        (["code smell", "smell", "health", "code quality", "code health", "technical debt"],
         "smell", {}, "high"),

        # Complexity
        (["complexity", "complex", "complicated", "cyclomatic", "cognitive complexity"],
         "complexity", {}, "high"),

        # Impact analysis
        (["what happens if", "impact of", "what if i change", "what if i delete", "can i change", "can i delete", "safe to"],
         "impact", {"name": _extract_symbol_name, "action": "modify"}, "medium"),

        # Trace
        (["how does", "trace", "call chain", "call path", "how is", "connected to", "flows to", "flow from"],
         "trace", {"name": _extract_symbol_name, "direction": "both"}, "medium"),

        # Test coverage
        (["test coverage", "tested", "untested", "missing test", "test map"],
         "test-map", {}, "high"),

        # Performance
        (["performance", "slow", "perf", "n+1", "memory leak", "bottleneck"],
         "perf-hint", {}, "high"),

        # Vulnerabilities
        (["vulnerability", "vulnerable", "cve", "security hole"],
         "vuln-scan", {}, "high"),

        # Outline
        (["outline", "structure", "file structure", "what's in", "contents of"],
         "outline", {}, "medium"),

        # Environment check
        (["env var", "environment variable", ".env", "missing env", "env check"],
         "env-check", {}, "high"),

        # Debug leak
        (["debug code", "console.log", "debugger", "todo", "fixme", "leftover"],
         "debug-leak", {}, "high"),

        # State
        (["state management", "store", "redux", "zustand", "pinia", "global state"],
         "state-map", {}, "high"),

        # Scan
        (["scan", "analyze", "index", "build registry", "full analysis"],
         "scan", {}, "high"),

        # Handbook
        (["overview", "handbook", "project brief", "tell me about", "summarize", "summary of"],
         "handbook", {}, "high"),

        # Dependencies
        (["dependents", "who imports", "who uses", "who depends", "import graph", "dependency graph"],
         "dependents", {}, "medium"),
    ]

    for keywords, command, extra_args, confidence in patterns:
        for kw in keywords:
            if kw in q:
                # Build args dict
                resolved_args = {"_confidence": confidence}
                for key, val in extra_args.items():
                    if callable(val):
                        resolved_args[key] = val(q, kw)
                    else:
                        resolved_args[key] = val
                return command, resolved_args

    # Fallback: try to find a symbol name and use context
    symbol = _extract_symbol_name(q, "")
    if symbol:
        return "context", {"name": symbol, "_confidence": "low"}

    return None, {}


def _extract_symbol_name(q: str, keyword: str) -> str:
    """Try to extract a symbol name from the question."""
    # Remove common question words
    cleaned = q
    for prefix in ["where is ", "where's ", "where does ", "what is ", "what's ",
                    "show me ", "find definition of ", "find def ", "find ",
                    "search for ", "how does ", "how is ", "trace ", "impact of ",
                    "what happens if i change ", "what happens if i delete ",
                    "can i change ", "can i delete "]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Remove trailing question marks and whitespace
    cleaned = cleaned.rstrip("?!. ").strip()

    # Try to extract code-like identifiers (camelCase, snake_case, PascalCase)
    # Look for backticked names first
    match = re.search(r'`([^`]+)`', q)
    if match:
        return match.group(1).strip()

    # Look for quoted names
    match = re.search(r'["\']([^"\']+)["\']', q)
    if match:
        return match.group(1).strip()

    # Look for identifier-like patterns
    match = re.search(r'[a-zA-Z_][a-zA-Z0-9_.]*', cleaned)
    if match:
        return match.group(0)

    return cleaned if cleaned else ""


def _execute_ask_command(command: str, args: dict, workspace: str) -> Dict[str, Any]:
    """Execute the determined command with the given args."""
    if command == "context":
        return get_symbol_context(args.get("name", ""), workspace)
    elif command == "symbols":
        return search_symbols(workspace, args.get("name", ""), domain="all", fuzzy=True)
    elif command == "dead-code":
        return detect_dead_code(workspace)
    elif command == "secrets":
        return detect_secrets(workspace)
    elif command == "circular":
        return detect_circular(workspace)
    elif command == "api-map":
        return map_api_routes(workspace)
    elif command == "entrypoints":
        return map_entrypoints(workspace)
    elif command == "smell":
        return detect_smells(workspace)
    elif command == "complexity":
        return compute_complexity(workspace)
    elif command == "impact":
        return analyze_impact(args.get("name", ""), workspace, action=args.get("action", "modify"))
    elif command == "trace":
        return trace_symbol(args.get("name", ""), workspace, direction=args.get("direction", "both"))
    elif command == "test-map":
        return map_test_coverage(workspace)
    elif command == "perf-hint":
        return detect_perf_hints(workspace)
    elif command == "vuln-scan":
        return scan_vulnerabilities(workspace)
    elif command == "outline":
        return get_workspace_outline(workspace)
    elif command == "env-check":
        return check_env_vars(workspace)
    elif command == "debug-leak":
        return detect_debug_leaks(workspace)
    elif command == "state-map":
        return map_state(workspace)
    elif command == "scan":
        return cmd_scan(workspace)
    elif command == "handbook":
        return cmd_handbook(workspace)
    elif command == "dependents":
        return get_dependency_graph(workspace)
    else:
        return {"status": "error", "message": f"Unknown command: {command}"}


# ─── Symbols Command ────────────────────────────────────────────

def cmd_symbols(args):
    """Search registry symbols by name."""
    workspace = resolve_workspace(args.workspace)
    result = search_symbols(workspace, args.name, domain=args.domain, fuzzy=args.fuzzy)
    print(_format_output(result, getattr(args, 'format', 'json'), getattr(args, 'command', 'symbols')))


# ─── Output Formatting ──────────────────────────────────────────

def _format_output(data: Any, format_type: str = "json", command: str = "") -> str:
    """Format output data as JSON or Markdown."""
    if format_type == "markdown":
        return _to_markdown(data, command)
    # Default: JSON
    return json.dumps(data, indent=2, ensure_ascii=False)


def _to_markdown(data: Any, command: str = "") -> str:
    """Convert command output dict to markdown format."""
    if not isinstance(data, dict):
        return str(data)

    lines = []
    status = data.get("status", "")

    # Error output
    if status == "error":
        lines.append(f"## Error")
        lines.append("")
        lines.append(f"**Command:** `{command}`")
        lines.append(f"**Error:** {data.get('error', 'Unknown error')}")
        lines.append(f"**Type:** {data.get('error_type', '')}")
        return "\n".join(lines)

    # Command-specific formatting
    if command == "scan":
        _md_scan(data, lines)
    elif command == "query":
        _md_query(data, lines)
    elif command == "context":
        _md_context(data, lines)
    elif command == "outline":
        _md_outline(data, lines)
    elif command == "impact":
        _md_impact(data, lines)
    elif command == "trace":
        _md_trace(data, lines)
    elif command == "smell":
        _md_smell(data, lines)
    elif command == "dead-code":
        _md_dead_code(data, lines)
    elif command == "circular":
        _md_circular(data, lines)
    elif command == "handbook":
        _md_handbook(data, lines)
    elif command == "entrypoints":
        _md_entrypoints(data, lines)
    elif command == "api-map":
        _md_api_map(data, lines)
    elif command == "complexity":
        _md_complexity(data, lines)
    elif command == "secrets":
        _md_secrets(data, lines)
    elif command == "side-effect":
        _md_side_effect(data, lines)
    else:
        # Generic markdown for any command
        _md_generic(data, lines)

    return "\n".join(lines)


def _md_generic(data: Dict, lines: list) -> None:
    """Generic markdown output for any command."""
    lines.append(f"## Result")
    lines.append("")
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"- **{key}:** {value}")
        elif isinstance(value, list) and len(value) < 20:
            lines.append(f"- **{key}:** {len(value)} items")
            for item in value[:10]:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("file") or item.get("path") or str(item)[:50]
                    lines.append(f"  - {name}")
                else:
                    lines.append(f"  - {item}")
        elif isinstance(value, dict):
            lines.append(f"- **{key}:** {len(value)} entries")
        elif isinstance(value, list):
            lines.append(f"- **{key}:** {len(value)} items")
    lines.append("")


def _md_scan(data: Dict, lines: list) -> None:
    """Markdown for scan command."""
    lines.append("## Scan Result")
    lines.append("")
    fs = data.get("files_scanned", {})
    lines.append(f"- **Workspace:** `{data.get('workspace', '')}`")
    for ftype, count in fs.items():
        if count > 0:
            lines.append(f"- **{ftype}:** {count} files")
    fe = data.get("frontend", {})
    be = data.get("backend", {})
    lines.append(f"- **Frontend:** {fe.get('classes', 0)} classes, {fe.get('ids', 0)} IDs")
    lines.append(f"- **Backend:** {be.get('nodes', 0)} nodes, {be.get('edges', 0)} edges")
    fws = data.get("frameworks", [])
    if fws:
        lines.append(f"- **Frameworks:** {', '.join(fws)}")
    outline_gen = data.get("outline_generated")
    if outline_gen is not None:
        lines.append(f"- **Outline generated:** {'Yes' if outline_gen else 'No'}")
    lines.append("")


def _md_query(data: Dict, lines: list) -> None:
    """Markdown for query command."""
    name = data.get("name", "")
    found = data.get("found", False)
    status = data.get("status", "")
    action = data.get("action", "")
    action_reason = data.get("action_reason", "")

    icon = "Found" if found else "Not found"
    lines.append(f"## Query: `{name}`")
    lines.append("")
    lines.append(f"**Status:** {icon}" + (f" ({status})" if status and found else ""))
    if action:
        lines.append(f"**Action:** {action}")
    if action_reason:
        lines.append(f"**Reason:** {action_reason}")
    lines.append("")

    refs = data.get("references", [])
    if refs:
        lines.append("### References")
        for ref in refs[:20]:
            rtype = ref.get("type", "")
            rname = ref.get("name", name)
            file_path = ref.get("file", "")
            line = ref.get("line", "")
            status_str = ref.get("status", "")
            lines.append(f"- `{rname}` ({rtype}) — `{file_path}:{line}` [{status_str}]")
        lines.append("")


def _md_context(data: Dict, lines: list) -> None:
    """Markdown for context command."""
    symbol = data.get("symbol", "")
    found = data.get("found", False)
    ctx = data.get("context", {})

    lines.append(f"## Context: `{symbol}`")
    lines.append("")

    if not found or not ctx:
        lines.append("Symbol not found.")
        lines.append("")
        return

    defn = ctx.get("definition") or {}
    lines.append(f"**Type:** {defn.get('type', 'unknown')} | **Status:** {defn.get('status', '')} | **Refs:** {defn.get('ref_count', 0)}")
    lines.append("")

    # Code snippet
    snippet = ctx.get("code_snippet")
    if snippet:
        lines.append("### Definition")
        ext = os.path.splitext(snippet.get("file", ""))[1].lstrip(".")
        lang_map = {"py": "python", "js": "javascript", "ts": "typescript", "tsx": "tsx", "rs": "rust"}
        lang = lang_map.get(ext, ext)
        lines.append(f"```{lang}")
        for line_info in snippet.get("lines", []):
            prefix = ">>>" if line_info.get("is_target") else "   "
            lines.append(f"{prefix} {line_info.get('line', ''):4d} | {line_info.get('content', '')}")
        lines.append("```")
        lines.append("")

    # Callers
    callers = ctx.get("callers", [])
    if callers:
        lines.append("### Callers")
        for c in callers[:10]:
            lines.append(f"- `{c.get('file', '')}:{c.get('line', '')}` — {c.get('source', c.get('fn', ''))}")
        lines.append("")

    # Callees
    callees = ctx.get("callees", [])
    if callees:
        lines.append("### Callees")
        for c in callees[:10]:
            resolved = "resolved" if c.get("resolved") else "unresolved"
            lines.append(f"- {c.get('fn', '')} → `{c.get('file', '')}:{c.get('line', '')}` [{resolved}]")
        lines.append("")

    # Quality (if enriched)
    quality = ctx.get("quality")
    if quality:
        lines.append("### Quality")
        lines.append(f"- **Complexity:** {quality.get('complexity', 'N/A')}")
        lines.append(f"- **Side effects:** {quality.get('side_effects', 'N/A')}")
        lines.append(f"- **Safety:** {quality.get('safety', 'N/A')}")
        smells = quality.get("smells", [])
        if smells:
            lines.append(f"- **Smells:** {', '.join(smells)}")
        lines.append("")


def _md_outline(data: Dict, lines: list) -> None:
    """Markdown for outline command."""
    if "outlines" in data:
        # Workspace outline
        lines.append(f"## Workspace Outline ({data.get('files_outlined', 0)} files)")
        lines.append("")
        for outline in data.get("outlines", []):
            file = outline.get("file", "")
            lang = outline.get("language", "")
            lines.append(f"### `{file}` ({lang})")
            ol = outline.get("outline", {})
            for key, items in ol.items():
                if isinstance(items, list) and items:
                    lines.append(f"- **{key}:** {len(items)}")
            lines.append("")
    else:
        # Single file outline
        file = data.get("file", "")
        lines.append(f"## Outline: `{file}`")
        lines.append("")
        ol = data.get("outline", {})
        for key, items in ol.items():
            if isinstance(items, list) and items:
                lines.append(f"- **{key}:** {len(items)}")


def _md_impact(data: Dict, lines: list) -> None:
    """Markdown for impact command."""
    lines.append(f"## Impact Analysis: `{data.get('symbol', '')}`")
    lines.append("")
    risk = data.get("risk_level", data.get("risk", ""))
    action_plan = data.get("recommended_action", data.get("action", ""))
    if risk:
        lines.append(f"**Risk Level:** {risk}")
    if action_plan:
        lines.append(f"**Recommended Action:** {action_plan}")
    lines.append("")
    affected = data.get("affected", data.get("affected_files", []))
    if affected:
        lines.append("### Affected")
        for a in affected[:20]:
            if isinstance(a, dict):
                lines.append(f"- `{a.get('file', '')}:{a.get('line', '')}` — {a.get('type', a.get('fn', ''))}")
            else:
                lines.append(f"- {a}")
        lines.append("")


def _md_trace(data: Dict, lines: list) -> None:
    """Markdown for trace command."""
    lines.append(f"## Trace: `{data.get('symbol', data.get('name', ''))}`")
    lines.append("")
    direction = data.get("direction", "")
    if direction:
        lines.append(f"**Direction:** {direction}")
    lines.append("")
    chains = data.get("chains", data.get("trace", []))
    if chains:
        for chain in chains[:10]:
            if isinstance(chain, dict):
                path = chain.get("path", [])
                lines.append(f"- {' → '.join(str(p) for p in path)}")
            elif isinstance(chain, list):
                lines.append(f"- {' → '.join(str(p) for p in chain)}")
            else:
                lines.append(f"- {chain}")
        lines.append("")


def _md_smell(data: Dict, lines: list) -> None:
    """Markdown for smell command."""
    stats = data.get("stats", {})
    lines.append("## Code Smells")
    lines.append("")
    lines.append(f"**Health Score:** {stats.get('health_score', 0)}/100")
    lines.append(f"- Critical: {stats.get('critical', 0)} | Warning: {stats.get('warning', 0)} | Info: {stats.get('info', 0)}")
    lines.append("")
    top = data.get("top_priority", [])
    if top:
        lines.append("### Top Priority")
        for smell in top[:10]:
            cat = smell.get("category", "")
            file = smell.get("file", "")
            line = smell.get("line", "")
            msg = smell.get("message", "")
            sev = smell.get("severity", "")
            lines.append(f"- [{sev.upper()}] `{file}:{line}` — {cat}: {msg}")
        lines.append("")


def _md_dead_code(data: Dict, lines: list) -> None:
    """Markdown for dead-code command."""
    stats = data.get("stats", {})
    lines.append("## Dead Code Analysis")
    lines.append("")
    lines.append(f"- Total dead: {stats.get('total_dead', 0)}")
    lines.append(f"- Unreachable: {stats.get('unreachable', 0)} | Unused exports: {stats.get('unused_exports', 0)} | Zombie CSS: {stats.get('zombie_css', 0)}")
    removal_safety = data.get("removal_safety", "")
    if removal_safety:
        lines.append(f"- **Removal safety:** {removal_safety}")
    lines.append("")
    items = data.get("dead_items", data.get("items", []))
    if items:
        lines.append("### Items")
        for item in items[:15]:
            file = item.get("file", "")
            line = item.get("line", "")
            dtype = item.get("type", item.get("category", ""))
            name = item.get("name", item.get("fn", ""))
            lines.append(f"- `{file}:{line}` — {dtype}: {name}")
        lines.append("")


def _md_circular(data: Dict, lines: list) -> None:
    """Markdown for circular command."""
    chains = data.get("chains", [])
    lines.append("## Circular Dependencies")
    lines.append("")
    lines.append(f"**Found:** {len(chains)} circular chain(s)")
    lines.append("")
    for chain in chains[:10]:
        path = chain.get("path", chain) if isinstance(chain, dict) else chain
        if isinstance(path, list):
            lines.append(f"- {' → '.join(str(p) for p in path)}")
        else:
            lines.append(f"- {path}")
    lines.append("")


def _md_handbook(data: Dict, lines: list) -> None:
    """Markdown for handbook command."""
    identity = data.get("identity", {})
    meta = data.get("meta", {})
    health = data.get("health", {})
    structure = data.get("structure", {})
    conventions = data.get("conventions", {})
    risks = data.get("risks", [])
    qr = data.get("quick_reference", {})

    lines.append(f"# Project Handbook: {identity.get('name', 'unknown')}")
    lines.append("")

    desc = identity.get("description", "")
    if desc:
        lines.append(f"**{desc}**")
        lines.append("")

    fws = data.get("frameworks", [])
    lines.append(f"Type: **{identity.get('type', 'unknown')}** | Version: {identity.get('version', '0.0.0')} | Frameworks: {', '.join(fws) if fws else 'none'}")
    lines.append("")

    lines.append(f"## Health: {health.get('score', 0)}/100")
    lines.append(f"- Smells: {health.get('smells_count', 0)} | Critical: {health.get('critical', 0)} | Warning: {health.get('warning', 0)}")
    lines.append("")

    # Structure
    dir_map = structure.get("directory_map", {})
    if dir_map:
        lines.append("## Structure")
        for dir_path, desc in dir_map.items():
            lines.append(f"- `{dir_path}` — {desc}")
        lines.append("")

    # Quick Reference
    lines.append("## Quick Reference")
    lines.append(f"- Files: {qr.get('total_files', 0)} | Functions: {qr.get('total_functions', 0)} | Classes: {qr.get('total_classes', 0)} | Exports: {qr.get('total_exports', 0)}")
    lines.append("")

    # Risks
    if risks:
        lines.append("## Risks")
        for r in risks:
            rtype = r.get("type", "")
            count = r.get("count", 0)
            desc = r.get("description", "")
            if count:
                lines.append(f"- {rtype.replace('_', ' ')}: {count}")
            elif desc:
                lines.append(f"- {desc}")
        lines.append("")

    # Conventions
    naming = conventions.get("naming", {})
    if naming:
        lines.append("## Conventions")
        for key, val in naming.items():
            lines.append(f"- {key}: {val}")
        lines.append("")

    lines.append(f"Generated: {meta.get('generated_at', 'unknown')}")


def _md_entrypoints(data: Dict, lines: list) -> None:
    """Markdown for entrypoints command."""
    lines.append("## Entrypoints")
    lines.append("")
    eps = data.get("entrypoints", [])
    for ep in eps[:20]:
        etype = ep.get("type", "")
        file = ep.get("file", "")
        line = ep.get("line", "")
        label = ep.get("label", "")
        extra = ""
        if etype == "http_handler":
            extra = f" `{ep.get('method', '')} {ep.get('path', '')}`"
        lines.append(f"- [{etype}] `{file}:{line}` — {label}{extra}")
    lines.append("")


def _md_api_map(data: Dict, lines: list) -> None:
    """Markdown for api-map command."""
    lines.append("## API Routes")
    lines.append("")
    routes = data.get("routes", [])
    for r in routes[:30]:
        method = r.get("method", "GET")
        path = r.get("path", "/")
        handler = r.get("handler_name", "")
        file = r.get("file", "")
        auth = " [auth]" if r.get("auth_protected") else ""
        lines.append(f"- **{method}** `{path}` → {handler} (`{file}`){auth}")
    lines.append("")


def _md_complexity(data: Dict, lines: list) -> None:
    """Markdown for complexity command."""
    stats = data.get("stats", {})
    lines.append("## Complexity Analysis")
    lines.append("")
    lines.append(f"- Total functions: {stats.get('total_functions', 0)}")
    lines.append(f"- Avg cyclomatic: {stats.get('avg_cyclomatic', 0):.1f} | Avg cognitive: {stats.get('avg_cognitive', 0):.1f}")
    by_level = stats.get("by_complexity_level", {})
    if by_level:
        parts = [f"{k}: {v}" for k, v in by_level.items() if v > 0]
        lines.append(f"- Levels: {', '.join(parts)}")
    lines.append("")
    hotspots = data.get("hotspots", [])
    if hotspots:
        lines.append("### Hotspots")
        for hs in hotspots[:10]:
            lines.append(f"- `{hs.get('file', '')}:{hs.get('line', '')}` — {hs.get('name', '')} (CC={hs.get('cyclomatic', 0)})")
        lines.append("")


def _md_secrets(data: Dict, lines: list) -> None:
    """Markdown for secrets command."""
    stats = data.get("stats", {})
    lines.append("## Secrets Scan")
    lines.append("")
    lines.append(f"- Total secrets: {stats.get('total_secrets', 0)}")
    lines.append("")
    findings = data.get("findings", [])
    if findings:
        lines.append("### Findings")
        for f in findings[:15]:
            lines.append(f"- [{f.get('severity', '').upper()}] `{f.get('file', '')}:{f.get('line', '')}` — {f.get('type', '')}")
        lines.append("")


def _md_side_effect(data: Dict, lines: list) -> None:
    """Markdown for side-effect command."""
    stats = data.get("stats", {})
    lines.append("## Side Effect Analysis")
    lines.append("")
    lines.append(f"- Pure: {stats.get('pure', 0)} | Impure: {stats.get('impure', 0)} | Purity ratio: {stats.get('purity_ratio', 0):.0%}")
    effects = stats.get("effect_summary", {})
    if effects:
        parts = [f"{k}: {v}" for k, v in effects.items() if v > 0]
        lines.append(f"- Effects: {', '.join(parts)}")
    lines.append("")
    functions = data.get("functions", [])
    if functions:
        lines.append("### Impure Functions")
        for fn in functions[:15]:
            if fn.get("classification") == "impure":
                effects_list = ", ".join(e.get("type", "") for e in fn.get("side_effects", []))
                lines.append(f"- `{fn.get('file', '')}:{fn.get('line', '')}` — {fn.get('name', '')} ({effects_list})")
        lines.append("")


# ─── Handbook Command ────────────────────────────────────────

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
            # Detect type
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
            # Simple extraction without tomllib
            import re as _re
            name_match = _re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = _re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
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
            import re as _re
            name_match = _re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            ver_match = _re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
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
    dir_map = {}
    try:
        for entry in sorted(os.listdir(workspace)):
            full = os.path.join(workspace, entry)
            if os.path.isdir(full) and entry not in ignore_dirs and not entry.startswith('.'):
                # Count source files in dir (one level)
                src_count = 0
                try:
                    for f in os.listdir(full):
                        if os.path.isfile(os.path.join(full, f)):
                            ext = os.path.splitext(f)[1].lower()
                            if ext in {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.html', '.css', '.scss', '.vue', '.svelte'}:
                                src_count += 1
                except Exception:
                    pass
                desc = f"{src_count} source file{'s' if src_count != 1 else ''}" if src_count else "directory"
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
    import re as _re
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

    # Detect file naming convention
    snake_count = sum(1 for f in files if '_' in os.path.splitext(f)[0] and f == f.lower())
    kebab_count = sum(1 for f in files if '-' in os.path.splitext(f)[0] and f == f.lower())
    camel_count = sum(1 for f in files if _re.match(r'^[a-z]+[A-Z]', os.path.splitext(f)[0]))
    pascal_count = sum(1 for f in files if f[0].isupper() and f[0].isalpha())

    if snake_count > kebab_count and snake_count > camel_count:
        conventions["naming"]["files"] = "snake_case"
    elif kebab_count > snake_count and kebab_count > camel_count:
        conventions["naming"]["files"] = "kebab-case"
    elif pascal_count > camel_count:
        conventions["naming"]["files"] = "PascalCase"
    elif camel_count > 0:
        conventions["naming"]["files"] = "camelCase"

    # Detect Python vs JS conventions
    py_files = [f for f in files if f.endswith('.py')]
    js_files = [f for f in files if f.endswith(('.js', '.ts', '.tsx'))]

    if py_files:
        py_snake = sum(1 for f in py_files if '_' in os.path.splitext(f)[0])
        if py_snake > len(py_files) * 0.5:
            conventions["naming"]["python_files"] = "snake_case"

    if js_files:
        js_kebab = sum(1 for f in js_files if '-' in os.path.splitext(f)[0])
        js_camel = sum(1 for f in js_files if _re.match(r'^[a-z]+[A-Z]', os.path.splitext(f)[0]))
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

    # 12. Conventions (from convention_engine if available)
    conventions = _detect_conventions(workspace)

    # Build handbook
    handbook = {
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


# ─── Watch Command ────────────────────────────────────────────

# Extensions that trigger a rescan
_WATCH_EXTENSIONS = frozenset({
    '.html', '.htm', '.css', '.scss', '.less', '.sass',
    '.js', '.jsx', '.ts', '.tsx', '.rs', '.py', '.vue', '.svelte',
})


def _write_output_files(workspace: str, scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """
    After a scan, generate outline.json and summary.json into .codelens/.
    Returns the summary dict for terminal display.
    """
    try:
        codelens_dir = os.path.join(workspace, '.codelens')
        os.makedirs(codelens_dir, exist_ok=True)

        # Generate workspace outline using the existing outline engine
        outline_data = get_workspace_outline(workspace)

        # Write outline.json
        outline_path = os.path.join(codelens_dir, 'outline.json')
        with open(outline_path, 'w', encoding='utf-8') as f:
            json.dump(outline_data, f, indent=2, ensure_ascii=False)

        # Compute aggregate summary
        summary = _compute_summary(workspace, outline_data, scan_result)

        # Write summary.json
        summary_path = os.path.join(codelens_dir, 'summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        return summary
    except Exception:
        # Don't crash the watcher if outline generation fails
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

        # Count class methods
        for cls in outline.get('classes', []):
            total_functions += len(cls.get('methods', []))

    # Get node/edge counts from scan result
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


def _format_watch_summary(summary: Dict[str, Any], changed_count: int = 0) -> str:
    """Format a one-line summary for terminal output."""
    now = datetime.now().strftime('%H:%M:%S')
    files = summary.get('files', 0)
    funcs = summary.get('functions', 0)
    classes = summary.get('classes', 0)
    nodes = summary.get('backend_nodes', 0)
    edges = summary.get('backend_edges', 0)

    parts = [f'{files} files', f'{funcs} funcs', f'{classes} classes']
    if nodes:
        parts.append(f'{nodes} nodes')
    if edges:
        parts.append(f'{edges} edges')
    if changed_count:
        parts.append(f'{changed_count} changed')

    return f'[{now}] \u2713 {" | ".join(parts)}'


def cmd_watch(workspace: str, debounce: float = 0.5) -> None:
    """
    Start file watcher for real-time registry updates.
    Uses debounce to coalesce rapid file changes, prints a clean
    one-line summary, and writes outline.json + summary.json to .codelens/.
    """
    import threading as _threading
    workspace = os.path.abspath(workspace)

    # ─── Debounce state ────────────────────────────────────
    _timer: Optional[_threading.Timer] = None
    _lock = _threading.Lock()
    _changed_files: set = set()

    def _on_file_change(filepath: str) -> None:
        """Called when a source file changes. Debounces rapid events."""
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in _WATCH_EXTENSIONS:
            return
        # Ignore changes inside .codelens output directory
        if '.codelens' in filepath:
            return

        nonlocal _timer
        with _lock:
            _changed_files.add(filepath)
            if _timer:
                _timer.cancel()
            _timer = _threading.Timer(debounce, _do_rescan)
            _timer.daemon = True
            _timer.start()

    def _do_rescan() -> None:
        """Perform the actual rescan after the debounce period."""
        with _lock:
            changed = _changed_files.copy()
            _changed_files.clear()

        if not changed:
            return

        changed_rel = [os.path.relpath(f, workspace) for f in changed]
        for rel in changed_rel:
            print(f'  Changed: {rel}')

        # Run incremental scan
        scan_result = cmd_scan(workspace, incremental=True)

        # Auto-save snapshot
        try:
            frontend = load_frontend_registry(workspace)
            backend = load_backend_registry(workspace)
            save_snapshot(workspace, frontend, backend)
        except Exception:
            pass

        # Generate outline.json + summary.json
        summary = _write_output_files(workspace, scan_result)
        print(_format_watch_summary(summary, changed_count=len(changed)))

    # ─── Initial scan ──────────────────────────────────────
    print(f'[CodeLens] Scanning {workspace}...')
    scan_result = cmd_scan(workspace)

    # Auto-save snapshot
    try:
        frontend = load_frontend_registry(workspace)
        backend = load_backend_registry(workspace)
        save_snapshot(workspace, frontend, backend)
    except Exception:
        pass

    # Generate outline.json + summary.json
    summary = _write_output_files(workspace, scan_result)
    print(_format_watch_summary(summary))

    # ─── Start watcher ─────────────────────────────────────
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print('[CodeLens] watchdog not installed. Install with: pip install watchdog')
        print(f'[CodeLens] Falling back to polling mode (every 2s, debounce: {debounce}s)...')
        _watch_polling(workspace, debounce, _on_file_change)
        return

    class CodeLensHandler(FileSystemEventHandler):
        def on_modified(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

        def on_created(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

        def on_deleted(self, event):
            if not event.is_directory:
                _on_file_change(event.src_path)

    observer = Observer()
    handler = CodeLensHandler()
    observer.schedule(handler, workspace, recursive=True)
    observer.start()

    print(f'[CodeLens] Watching {workspace} (debounce: {debounce}s) — Press Ctrl+C to stop')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print('[CodeLens] Stopped.')
    observer.join()


def _watch_polling(
    workspace: str,
    debounce: float = 0.5,
    on_change_callback=None
) -> None:
    """
    Fallback polling-based watcher with debounce support.
    Checks for file modifications every 2 seconds.
    """
    import threading as _threading

    if on_change_callback is None:
        # Standalone mode: create our own debounce state
        _lock = _threading.Lock()
        _timer = None
        _pending: set = set()

        def _poll_rescan():
            nonlocal _timer
            with _lock:
                changed = _pending.copy()
                _pending.clear()
            if not changed:
                return
            scan_result = cmd_scan(workspace, incremental=True)
            try:
                frontend = load_frontend_registry(workspace)
                backend = load_backend_registry(workspace)
                save_snapshot(workspace, frontend, backend)
            except Exception:
                pass
            summary = _write_output_files(workspace, scan_result)
            print(_format_watch_summary(summary, changed_count=len(changed)))

        def on_change_callback(filepath):
            nonlocal _timer
            ext = os.path.splitext(filepath)[1].lower()
            if ext not in _WATCH_EXTENSIONS:
                return
            if '.codelens' in filepath:
                return
            with _lock:
                _pending.add(filepath)
                if _timer:
                    _timer.cancel()
                _timer = _threading.Timer(debounce, _poll_rescan)
                _timer.daemon = True
                _timer.start()

    # Track file mtimes
    last_mtimes: Dict[str, float] = {}
    ignore_dirs = {
        'node_modules', '.git', 'dist', 'build', 'target',
        '__pycache__', '.codelens', '.next', '.cache',
        'vendor', '.venv', 'venv', 'env',
    }

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in _WATCH_EXTENSIONS:
                filepath = os.path.join(root, filename)
                try:
                    last_mtimes[filepath] = os.path.getmtime(filepath)
                except OSError:
                    pass

    print(f'[CodeLens] Polling {workspace} every 2s (debounce: {debounce}s) — Press Ctrl+C to stop')
    try:
        while True:
            time.sleep(2)

            # Check for modified/deleted files
            for filepath in list(last_mtimes.keys()):
                try:
                    current = os.path.getmtime(filepath)
                    if current != last_mtimes[filepath]:
                        last_mtimes[filepath] = current
                        on_change_callback(filepath)
                except OSError:
                    del last_mtimes[filepath]
                    on_change_callback(filepath)

            # Check for new files
            for root, dirs, filenames in os.walk(workspace):
                dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
                for filename in filenames:
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in _WATCH_EXTENSIONS:
                        filepath = os.path.join(root, filename)
                        if filepath not in last_mtimes:
                            try:
                                last_mtimes[filepath] = os.path.getmtime(filepath)
                                on_change_callback(filepath)
                            except OSError:
                                pass

    except KeyboardInterrupt:
        print('[CodeLens] Stopped.')


# ─── CLI Entry Point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeLens v5 — Live Codebase Reference Intelligence (Tree-sitter Edition)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ─── Original 6 commands ────────────────────────────

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan workspace and build registry")
    scan_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    scan_parser.add_argument("--incremental", action="store_true",
                              help="Only re-scan changed files")

    # query command
    query_parser = subparsers.add_parser("query", help="Query a specific class/id/function")
    query_parser.add_argument("name", help="Name to query")
    query_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    query_parser.add_argument("--domain", choices=["frontend", "backend"], default=None,
                              help="Domain to search")
    query_parser.add_argument("--file", default=None, help="Filter by file path")

    # list command
    list_parser = subparsers.add_parser("list", help="List entries with filter")
    list_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    list_parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                              help="Domain to list")
    list_parser.add_argument("--filter", dest="filter_type",
                              choices=["all", "dead", "duplicate_define", "duplicate_ref", "collision", "active"],
                              default="all", help="Filter by status")

    # watch command
    watch_parser = subparsers.add_parser("watch", help="Start file watcher with debounce")
    watch_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    watch_parser.add_argument("--debounce", "-d", type=float, default=0.5,
                               help="Debounce interval in seconds (default: 0.5)")

    # handbook command
    handbook_parser = subparsers.add_parser("handbook", help="Generate project handbook for AI agents")
    handbook_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # ask command
    ask_parser = subparsers.add_parser("ask", help="Ask a question in natural language")
    ask_parser.add_argument("question", help="Natural language question about the codebase")
    ask_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize .codelens with auto-detected config")
    init_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # detect command
    detect_parser = subparsers.add_parser("detect", help="Detect frameworks in workspace")
    detect_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # ─── P1: Search, Trace, Impact ──────────────────────

    # search command
    search_parser = subparsers.add_parser("search", help="Search code pattern across workspace")
    search_parser.add_argument("pattern", help="Regex pattern to search for")
    search_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    search_parser.add_argument("--type", dest="file_type", default=None,
                                help="File type filter (html, css, js, ts, tsx, rust, python, vue, svelte)")
    search_parser.add_argument("--file", default=None, help="Filter by file path substring")
    search_parser.add_argument("--max-results", type=int, default=200, help="Max results (default 200)")
    search_parser.add_argument("--context", type=int, default=0, help="Context lines around match")
    search_parser.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    search_parser.add_argument("--whole-word", action="store_true", help="Match whole words only")

    # symbols command (search registry instead of files)
    symbols_parser = subparsers.add_parser("symbols", help="Search symbols in registry by name")
    symbols_parser.add_argument("name", help="Symbol name to search")
    symbols_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    symbols_parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                                 help="Domain to search")
    symbols_parser.add_argument("--fuzzy", action="store_true", help="Allow partial/fuzzy matching")
    symbols_parser.set_defaults(func=cmd_symbols)

    # trace command
    trace_parser = subparsers.add_parser("trace", help="Trace deep call chain from a symbol")
    trace_parser.add_argument("name", help="Symbol name to trace")
    trace_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    trace_parser.add_argument("--direction", choices=["up", "down", "both"], default="up",
                               help="Trace direction: up=callers, down=callees, both")
    trace_parser.add_argument("--depth", type=int, default=10, help="Max trace depth (default 10)")
    trace_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                               help="Domain to trace")

    # impact command
    impact_parser = subparsers.add_parser("impact", help="Analyze change impact for a symbol")
    impact_parser.add_argument("name", help="Symbol name to analyze")
    impact_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    impact_parser.add_argument("--action", choices=["modify", "delete"], default="modify",
                                help="Planned action (modify or delete)")
    impact_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                                help="Domain to analyze")
    impact_parser.add_argument("--depth", type=int, default=5, help="Trace depth (default 5)")

    # ─── P2: Outline, Missing-refs, Diff, Circular ─────

    # outline command
    outline_parser = subparsers.add_parser("outline", help="Get file structure outline")
    outline_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    outline_parser.add_argument("--file", default=None, help="Specific file to outline")
    outline_parser.add_argument("--detail", choices=["minimal", "normal", "full"], default="normal",
                                 help="Detail level")
    outline_parser.add_argument("--all", action="store_true", dest="all_files",
                                 help="Outline all files in workspace")

    # missing-refs command
    missing_refs_parser = subparsers.add_parser("missing-refs", help="Detect CSS/HTML mismatch bugs")
    missing_refs_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # diff command
    diff_parser = subparsers.add_parser("diff", help="Compare registry snapshots")
    diff_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    diff_parser.add_argument("--snapshot1", default=None, help="First snapshot ID (default: second-to-last)")
    diff_parser.add_argument("--snapshot2", default=None, help="Second snapshot ID (default: last)")
    diff_parser.add_argument("--list-snapshots", action="store_true", help="List available snapshots")

    # circular command
    circular_parser = subparsers.add_parser("circular", help="Detect circular dependencies")
    circular_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    circular_parser.add_argument("--domain", choices=["backend", "imports", "css", "all"], default="all",
                                  help="Which dependency types to check")

    # ─── P3: Context, Dependents, Validate ──────────────

    # context command
    context_parser = subparsers.add_parser("context", help="Get rich symbol context (code + callers + callees)")
    context_parser.add_argument("name", help="Symbol name")
    context_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    context_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                                 help="Domain")
    context_parser.add_argument("--context-lines", type=int, default=5,
                                 help="Lines of code context around symbol (default 5)")
    context_parser.add_argument("--no-code", action="store_true", help="Skip source code in output")

    # dependents command
    dependents_parser = subparsers.add_parser("dependents", help="Module-level import tracking")
    dependents_parser.add_argument("file", help="File path to check")
    dependents_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    dependents_parser.add_argument("--direction", choices=["dependents", "dependencies", "graph"],
                                    default="dependents",
                                    help="Show who imports this file, what this file imports, or full graph")
    dependents_parser.add_argument("--depth", type=int, default=3, help="Trace depth (default 3)")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate registry against file system")
    validate_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # ─── v3 P0: Dataflow, Smell ─────────────────────────

    # dataflow command
    dataflow_parser = subparsers.add_parser("dataflow", help="Trace data flow source→sink (security)")
    dataflow_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    dataflow_parser.add_argument("--source", default=None,
                                  help="Source filter (user_input, env_var, file_input, api_response)")
    dataflow_parser.add_argument("--sink", default=None,
                                  help="Sink filter (db_query, html_output, command_exec, file_write, http_header)")
    dataflow_parser.add_argument("--depth", type=int, default=15, help="Max data flow chain depth (default 15)")

    # smell command
    smell_parser = subparsers.add_parser("smell", help="Detect code smells across workspace")
    smell_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    smell_parser.add_argument("--categories", nargs="+", default=None,
                               help="Categories: long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent")
    smell_parser.add_argument("--severity", choices=["info", "warning", "critical"], default=None,
                               help="Filter by severity level")

    # ─── v3 P1: Side-effect, Refactor-safe, Dead-code ────

    # side-effect command
    sideeffect_parser = subparsers.add_parser("side-effect", help="Analyze function side effects (pure vs impure)")
    sideeffect_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    sideeffect_parser.add_argument("--name", default=None, help="Specific function to analyze (optional)")
    sideeffect_parser.add_argument("--file", default=None, help="Filter by file path")

    # refactor-safe command
    refactor_parser = subparsers.add_parser("refactor-safe", help="Pre-flight rename/move safety check")
    refactor_parser.add_argument("name", help="Symbol name to rename/move")
    refactor_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    refactor_parser.add_argument("--action", choices=["rename", "move"], default="rename",
                                  help="Action type (rename or move)")
    refactor_parser.add_argument("--new-name", default=None, help="New name (for rename) or new path (for move)")

    # dead-code command
    deadcode_parser = subparsers.add_parser("dead-code", help="Enhanced dead code detection")
    deadcode_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    deadcode_parser.add_argument("--categories", nargs="+", default=None,
                                  help="Categories: unreachable, unused_exports, zombie_css, unused_vars, dead_listeners")

    # ─── v3 P2: Stack-trace, Test-map, Config-drift ──────

    # stack-trace command
    stacktrace_parser = subparsers.add_parser("stack-trace", help="Error propagation simulation")
    stacktrace_parser.add_argument("name", help="Function name that might throw")
    stacktrace_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    stacktrace_parser.add_argument("--error-type", default=None, help="Error type (e.g., TypeError)")
    stacktrace_parser.add_argument("--depth", type=int, default=20, help="Max trace depth (default 20)")

    # test-map command
    testmap_parser = subparsers.add_parser("test-map", help="Map test coverage for functions")
    testmap_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    testmap_parser.add_argument("--function", dest="function_name", default=None,
                                help="Check specific function test coverage")
    testmap_parser.add_argument("--file", default=None, help="Filter by source file path")

    # config-drift command
    configdrift_parser = subparsers.add_parser("config-drift", help="Detect dependency drift (package.json vs code)")
    configdrift_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")

    # ─── v3 P3: Type-infer, Ownership ─────────────────────

    # type-infer command
    typeinfer_parser = subparsers.add_parser("type-infer", help="Lightweight type inference for JS/Python")
    typeinfer_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    typeinfer_parser.add_argument("--file", default=None, help="Specific file to analyze")
    typeinfer_parser.add_argument("--function", dest="function_name", default=None,
                                  help="Specific function to infer types for")

    # ownership command
    ownership_parser = subparsers.add_parser("ownership", help="Git blame-based code ownership")
    ownership_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    ownership_parser.add_argument("--file", default=None, help="Specific file to analyze")
    ownership_parser.add_argument("--function", dest="function_name", default=None,
                                  help="Specific function to check ownership")

    # ─── v4 P0: Secrets, Entrypoints ────────────────────

    # secrets command
    secrets_parser = subparsers.add_parser("secrets", help="Detect hardcoded secrets and API keys")
    secrets_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    secrets_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                                 help="Filter by severity")

    # entrypoints command
    entrypoints_parser = subparsers.add_parser("entrypoints", help="Map execution entry points")
    entrypoints_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    entrypoints_parser.add_argument("--type", dest="entry_type", default=None,
                                     choices=["main", "http_handler", "event_handler", "cli_command",
                                              "cron_job", "worker", "module_export", "test_entry"],
                                     help="Filter by entry point type")

    # ─── v4 P1: API Map, State Map, Env Check ───────────

    # api-map command
    apimap_parser = subparsers.add_parser("api-map", help="Map REST/GraphQL/gRPC routes to handlers")
    apimap_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    apimap_parser.add_argument("--method", choices=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                                default=None, help="Filter by HTTP method")
    apimap_parser.add_argument("--path", dest="path_filter", default=None,
                                help="Filter by route path substring")

    # state-map command
    statemap_parser = subparsers.add_parser("state-map", help="Track global state management")
    statemap_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    statemap_parser.add_argument("--store", dest="store_name", default=None,
                                  help="Filter by store name")

    # env-check command
    envcheck_parser = subparsers.add_parser("env-check", help="Audit environment variables")
    envcheck_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    envcheck_parser.add_argument("--var", dest="var_name", default=None,
                                  help="Filter by variable name")

    # ─── v4 P2: Debug Leak, Complexity ──────────────────

    # debug-leak command
    debugleak_parser = subparsers.add_parser("debug-leak", help="Detect leftover debug code")
    debugleak_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    debugleak_parser.add_argument("--category", choices=["console_log", "print_statement", "debugger",
                                    "todo_fixme", "commented_code", "test_skip", "mock_data", "dev_only"],
                                   default=None, help="Filter by leak category")

    # complexity command
    complexity_parser = subparsers.add_parser("complexity", help="Compute cyclomatic/cognitive complexity")
    complexity_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    complexity_parser.add_argument("--name", default=None, help="Specific function to analyze")
    complexity_parser.add_argument("--file", default=None, help="Filter by file path")
    complexity_parser.add_argument("--threshold", type=int, default=None,
                                    help="Minimum complexity threshold to report")

    # ─── v4 P3: Regex Audit, A11y ───────────────────────

    # regex-audit command
    regexaudit_parser = subparsers.add_parser("regex-audit", help="Audit regex for ReDoS and issues")
    regexaudit_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    regexaudit_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                                    help="Filter by severity")

    # a11y command
    a11y_parser = subparsers.add_parser("a11y", help="Detect accessibility issues")

    # ─── v5 P1: Vuln-scan, Perf-hint, CSS-deep ─────────

    # vuln-scan command
    vulnscan_parser = subparsers.add_parser("vuln-scan", help="Scan dependencies for known CVEs")
    vulnscan_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    vulnscan_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                                    help="Filter by severity (includes higher)")

    # perf-hint command
    perfhint_parser = subparsers.add_parser("perf-hint", help="Detect performance anti-patterns")
    perfhint_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    perfhint_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                                  help="Filter by severity")
    perfhint_parser.add_argument("--category", default=None,
                                  help="Filter by category (n_plus_one, sync_blocking, memory_leak, expensive_renders, large_bundle, inefficient_iteration, unoptimized_images, cache_miss)")

    # css-deep command
    cssdeep_parser = subparsers.add_parser("css-deep", help="Deep CSS analysis (vars, keyframes, specificity)")
    cssdeep_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    cssdeep_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                                 help="Filter by severity")
    cssdeep_parser.add_argument("--category", default=None,
                                 help="Filter by category (unused_vars, orphan_keyframes, specificity_wars, duplicate_props, unused_media, z_index_abuse)")
    a11y_parser.add_argument("workspace", nargs="?", default=None, help="Path to workspace root (auto-detected if omitted)")
    a11y_parser.add_argument("--category", choices=["missing_alt", "missing_label", "aria_issues",
                              "keyboard_nav", "semantic_html", "color_contrast", "heading_order",
                              "link_text", "focus_management"], default=None,
                              help="Filter by a11y category")
    a11y_parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                              help="Filter by severity")

    # Global format option
    parser.add_argument("--format", "-f", choices=["json", "markdown"], default="json",
                        help="Output format (default: json)")

    # ─── Parse and dispatch ─────────────────────────────

    args = parser.parse_args()

    # ─── Dispatch ────────────────────────────────────────
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve workspace with auto-detect fallback
    workspace = resolve_workspace(args.workspace)
    if workspace != (args.workspace or ""):
        print(f"[CodeLens] Auto-detected workspace: {workspace}", file=sys.stderr)

    try:
        if args.command == "scan":
            result = cmd_scan(workspace, args.incremental)
            # Auto-save snapshot after scan
            try:
                frontend = load_frontend_registry(workspace)
                backend = load_backend_registry(workspace)
                save_snapshot(workspace, frontend, backend)
            except Exception:
                pass
            # Generate outline.json + summary.json
            try:
                _write_output_files(workspace, result)
                result["outline_generated"] = True
            except Exception:
                result["outline_generated"] = False
            print(_format_output(result, args.format, args.command))

        elif args.command == "query":
            result = cmd_query(args.name, workspace, args.domain, args.file)
            print(_format_output(result, args.format, args.command))

        elif args.command == "list":
            result = cmd_list(workspace, args.domain, args.filter_type)
            print(_format_output(result, args.format, args.command))

        elif args.command == "watch":
            cmd_watch(workspace, debounce=args.debounce)

        elif args.command == "handbook":
            result = cmd_handbook(workspace)
            print(_format_output(result, args.format, args.command))

        elif args.command == "init":
            result = cmd_init(workspace)
            print(_format_output(result, args.format, args.command))

        elif args.command == "detect":
            result = cmd_detect(workspace)
            print(_format_output(result, args.format, args.command))

        # ─── P1 Commands ────────────────────────────────────

        elif args.command == "search":
            config = load_config(os.path.abspath(workspace))
            result = search_workspace(
                workspace, args.pattern,
                file_type=args.file_type,
                file_filter=args.file,
                max_results=args.max_results,
                context_lines=args.context,
                case_sensitive=not args.ignore_case,
                whole_word=args.whole_word,
                config=config
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "symbols":
            args.workspace = workspace
            cmd_symbols(args)

        elif args.command == "trace":
            result = trace_symbol(
                args.name, workspace,
                direction=args.direction,
                max_depth=args.depth,
                domain=args.domain
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "impact":
            result = analyze_impact(
                args.name, workspace,
                action=args.action,
                domain=args.domain,
                depth=args.depth
            )
            # Add decision tree fields
            if result.get("status") == "ok":
                affected_count = len(result.get("affected", result.get("affected_files", [])))
                if affected_count == 0:
                    result["risk_level"] = "low"
                    result["recommended_action"] = "Safe to proceed. No dependent code found."
                elif affected_count <= 3:
                    result["risk_level"] = "medium"
                    result["recommended_action"] = "Proceed with caution. Review affected code before changing."
                elif affected_count <= 10:
                    result["risk_level"] = "high"
                    result["recommended_action"] = "High risk. Thoroughly test all affected code after changes."
                else:
                    result["risk_level"] = "critical"
                    result["recommended_action"] = "Critical risk. Consider refactoring to reduce dependencies first."
            print(_format_output(result, args.format, args.command))

        # ─── P2 Commands ────────────────────────────────────

        elif args.command == "outline":
            if args.all_files:
                result = get_workspace_outline(workspace)
            elif args.file:
                result = get_file_outline(args.file, workspace, detail_level=args.detail)
            else:
                result = get_workspace_outline(workspace)
            print(_format_output(result, args.format, args.command))

        elif args.command == "missing-refs":
            result = detect_missing_refs(workspace)
            print(_format_output(result, args.format, args.command))

        elif args.command == "diff":
            if args.list_snapshots:
                snaps = list_snapshots(workspace)
                result = {"snapshots": snaps}
                print(_format_output(result, args.format, args.command))
            elif args.snapshot1 or args.snapshot2:
                result = diff_snapshots(workspace, args.snapshot1, args.snapshot2)
                print(_format_output(result, args.format, args.command))
            else:
                result = diff_current_vs_last(workspace)
                print(_format_output(result, args.format, args.command))

        elif args.command == "circular":
            result = detect_circular(workspace, domain=args.domain)
            print(_format_output(result, args.format, args.command))

        # ─── P3 Commands ────────────────────────────────────

        elif args.command == "context":
            result = get_symbol_context(
                args.name, workspace,
                domain=args.domain,
                context_lines=args.context_lines,
                include_code=not args.no_code
            )
            # Enrich with quality metrics
            if result.get("found") and result.get("context"):
                quality = {}
                try:
                    from complexity_engine import compute_complexity
                    comp = compute_complexity(workspace, function_name=args.name)
                    if comp.get("status") == "ok" and comp.get("result"):
                        fn_data = comp["result"]
                        if isinstance(fn_data, dict):
                            quality["complexity"] = fn_data.get("cyclomatic", "N/A")
                            quality["complexity_level"] = fn_data.get("complexity_level", "N/A")
                        elif isinstance(fn_data, list) and fn_data:
                            quality["complexity"] = fn_data[0].get("cyclomatic", "N/A")
                            quality["complexity_level"] = fn_data[0].get("complexity_level", "N/A")
                except Exception:
                    pass

                try:
                    from sideeffect_engine import analyze_side_effects
                    se = analyze_side_effects(workspace, function_name=args.name)
                    if se.get("status") == "ok":
                        analyses = se.get("analyses", [])
                        if analyses:
                            fn_se = analyses[0]
                            quality["side_effects"] = fn_se.get("classification", "unknown") != "pure"
                            quality["side_effect_types"] = [e.get("type") for e in fn_se.get("side_effects", [])]
                        else:
                            quality["side_effects"] = False
                            quality["side_effect_types"] = []
                except Exception:
                    pass

                # Determine safety from existing data
                defn = result["context"].get("definition") or {}
                status = defn.get("status", "")
                ref_count = defn.get("ref_count", 0)

                if status == "dead":
                    quality["safety"] = "safe_to_remove"
                elif ref_count == 0:
                    quality["safety"] = "safe_to_modify"
                elif ref_count <= 2:
                    quality["safety"] = "caution"
                else:
                    quality["safety"] = "high_impact"

                # Check if in smell top_priority
                try:
                    from smell_engine import detect_smells
                    smells = detect_smells(workspace)
                    for s in smells.get("top_priority", []):
                        fn_name = s.get("fn", "")
                        if fn_name == args.name:
                            quality.setdefault("smells", []).append(s.get("category", ""))
                except Exception:
                    pass

                # Test coverage hint
                try:
                    from testmap_engine import map_test_coverage
                    tc = map_test_coverage(workspace, function_name=args.name)
                    if tc.get("status") == "ok":
                        coverage = tc.get("coverage", {})
                        quality["test_coverage"] = "covered" if coverage.get("has_tests") else "untested"
                except Exception:
                    pass

                if quality:
                    result["context"]["quality"] = quality
            print(_format_output(result, args.format, args.command))

        elif args.command == "dependents":
            if args.direction == "graph":
                result = get_dependency_graph(workspace)
            elif args.direction == "dependencies":
                result = get_dependencies(args.file, workspace, depth=args.depth)
            else:
                result = get_dependents(args.file, workspace, depth=args.depth)
            print(_format_output(result, args.format, args.command))

        elif args.command == "validate":
            result = validate_registry(workspace)
            print(_format_output(result, args.format, args.command))

        # ─── v3 P0 Commands ─────────────────────────────────

        elif args.command == "dataflow":
            result = trace_dataflow(
                workspace,
                source=args.source,
                sink=args.sink,
                max_depth=args.depth
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "smell":
            result = detect_smells(
                workspace,
                categories=args.categories,
                severity_filter=args.severity
            )
            # Add actionable priority list
            if result.get("status") == "ok":
                top = result.get("top_priority", [])
                actionable = []
                for item in top[:10]:
                    severity = item.get("severity", "info")
                    if severity == "critical":
                        action = "FIX_IMMEDIATELY"
                    elif severity == "warning":
                        action = "PLAN_FIX"
                    else:
                        action = "CONSIDER"
                    actionable.append({
                        "action": action,
                        "category": item.get("category", ""),
                        "file": item.get("file", ""),
                        "line": item.get("line", 0),
                        "message": item.get("message", ""),
                        "suggestion": item.get("suggestion", "")
                    })
                result["actionable_items"] = actionable
            print(_format_output(result, args.format, args.command))

        # ─── v3 P1 Commands ─────────────────────────────────

        elif args.command == "side-effect":
            result = analyze_side_effects(
                workspace,
                function_name=args.name,
                file_filter=args.file
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "refactor-safe":
            result = check_refactor_safety(
                args.name, workspace,
                action=args.action,
                new_name=args.new_name
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "dead-code":
            result = detect_dead_code(
                workspace,
                categories=args.categories
            )
            # Add removal safety assessment
            if result.get("status") == "ok":
                total_dead = result.get("stats", {}).get("total_dead", 0)
                if total_dead == 0:
                    result["removal_safety"] = "n/a"
                    result["dependency_count"] = 0
                else:
                    # Count items with references (riskier to remove)
                    items = result.get("dead_items", result.get("items", []))
                    with_refs = sum(1 for item in items if item.get("ref_count", 0) > 0)
                    if with_refs == 0:
                        result["removal_safety"] = "safe"
                    elif with_refs < total_dead * 0.3:
                        result["removal_safety"] = "mostly_safe"
                    else:
                        result["removal_safety"] = "caution"
                    result["dependency_count"] = with_refs
                    result["recommended_action"] = "Review before removing. Some dead code may still be referenced indirectly." if with_refs > 0 else "Safe to remove. No references found."
            print(_format_output(result, args.format, args.command))

        # ─── v3 P2 Commands ─────────────────────────────────

        elif args.command == "stack-trace":
            result = trace_error_propagation(
                args.name, workspace,
                error_type=args.error_type,
                max_depth=args.depth
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "test-map":
            result = map_test_coverage(
                workspace,
                function_name=args.function_name,
                file_filter=args.file
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "config-drift":
            result = detect_config_drift(workspace)
            print(_format_output(result, args.format, args.command))

        # ─── v3 P3 Commands ─────────────────────────────────

        elif args.command == "type-infer":
            result = infer_types(
                workspace,
                file_path=args.file,
                function_name=args.function_name
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "ownership":
            result = analyze_ownership(
                workspace,
                file_path=args.file,
                function_name=args.function_name
            )
            print(_format_output(result, args.format, args.command))

        elif args.command == "secrets":
            result = detect_secrets(workspace, severity=args.severity)
            print(_format_output(result, args.format, args.command))
        elif args.command == "entrypoints":
            result = map_entrypoints(workspace, entry_type=args.entry_type)
            print(_format_output(result, args.format, args.command))
        elif args.command == "api-map":
            result = map_api_routes(workspace, method=args.method, path_filter=args.path_filter)
            print(_format_output(result, args.format, args.command))
        elif args.command == "state-map":
            result = map_state(workspace, store_name=args.store_name)
            print(_format_output(result, args.format, args.command))
        elif args.command == "env-check":
            result = check_env_vars(workspace, var_name=args.var_name)
            print(_format_output(result, args.format, args.command))
        elif args.command == "debug-leak":
            result = detect_debug_leaks(workspace, category=args.category)
            print(_format_output(result, args.format, args.command))
        elif args.command == "complexity":
            result = compute_complexity(workspace, function_name=args.name,
                                         file_filter=args.file, threshold=args.threshold)
            print(_format_output(result, args.format, args.command))
        elif args.command == "regex-audit":
            result = audit_regex_patterns(workspace, severity=args.severity)
            print(_format_output(result, args.format, args.command))
        elif args.command == "a11y":
            result = audit_accessibility(workspace, category=args.category, severity=args.severity)
            print(_format_output(result, args.format, args.command))

        elif args.command == "vuln-scan":
            result = scan_vulnerabilities(workspace, severity=args.severity)
            print(_format_output(result, args.format, args.command))

        elif args.command == "perf-hint":
            result = detect_perf_hints(workspace, severity=args.severity, category=args.category)
            print(_format_output(result, args.format, args.command))

        elif args.command == "css-deep":
            result = analyze_css_deep(workspace, severity=args.severity, category=args.category)
            print(_format_output(result, args.format, args.command))

        elif args.command == "ask":
            result = cmd_ask(args.question, workspace)
            print(_format_output(result, args.format, result.get("query_interpretation", {}).get("interpreted_as", "ask")))

        else:
            parser.print_help()
            sys.exit(1)
    except Exception as e:
        error_result = {
            "status": "error",
            "command": args.command,
            "error": str(e),
            "error_type": type(e).__name__
        }
        print(_format_output(error_result, args.format, args.command), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
