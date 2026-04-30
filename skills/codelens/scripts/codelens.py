#!/usr/bin/env python3
"""
CodeLens v2 — Live Codebase Reference Intelligence (Tree-sitter Edition)

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
    python3 codelens.py outline <file> [workspace]     # Get file structure outline
    python3 codelens.py missing-refs <workspace>       # Detect CSS/HTML mismatches
    python3 codelens.py diff <workspace>               # Compare registry snapshots
    python3 codelens.py circular <workspace>           # Detect circular dependencies
    python3 codelens.py context <name> <workspace>     # Get rich symbol context
    python3 codelens.py dependents <file> <workspace>  # Module-level import tracking
    python3 codelens.py validate <workspace>           # Validate registry vs file system
"""

import sys
import os
import json
import argparse
import time
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
from grammar_loader import get_grammar_loader
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

        # Handle deleted files: need full rescan for now (simplification)
        if deleted:
            incremental = False
            changed_files = None
        else:
            changed_files = set(changed + new)

    # Load parsers (lazy - only load what we need)
    loader = get_grammar_loader()

    # Parse HTML files
    html_data = []
    if files["html"] and not (incremental and changed_files):
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

    # Build backend registry with edge resolution
    all_nodes = []
    all_raw_edges = []
    for item in rust_data + js_backend_data:
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
            "vue": len(files["vue"]),
            "svelte": len(files["svelte"])
        },
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
        for m in re.finditer(r'#([a-zA-Z_][\w-]*)', line):
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
    """Basic regex JS backend parser fallback."""
    import re
    nodes, edges = [], []
    # Simplified fallback
    return {"nodes": nodes, "edges": edges}


def _fallback_rust_parse(content, file_path):
    """Basic regex Rust parser fallback."""
    import re
    nodes, edges = [], []
    # Simplified fallback
    return {"nodes": nodes, "edges": edges}


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
                return {
                    "found": True,
                    "type": "class",
                    "domain": "frontend",
                    "name": cls["name"],
                    "ref_count": cls["ref_count"],
                    "status": cls["status"],
                    "css": cls.get("css", []),
                    "js": cls.get("js", [])
                }

        for id_entry in frontend.get("ids", []):
            if id_entry["name"] == query_name:
                if file_filter and file_filter not in json.dumps(id_entry):
                    continue
                return {
                    "found": True,
                    "type": "id",
                    "domain": "frontend",
                    "name": id_entry["name"],
                    "ref_count": id_entry["ref_count"],
                    "status": id_entry["status"],
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

                result = {
                    "found": True,
                    "type": "function",
                    "domain": "backend",
                    "node": {
                        "id": node["id"],
                        "fn": node["fn"],
                        "ref_count": node.get("ref_count", 0),
                        "status": node.get("status", "active"),
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

    return {"found": False, "query": query_name, "domain": domain or "auto"}


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


# ─── Watch Command ────────────────────────────────────────────

def cmd_watch(workspace: str) -> None:
    """Start file watcher for real-time registry updates."""
    workspace = os.path.abspath(workspace)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("[CodeLens] watchdog not installed. Install with: pip install watchdog")
        print("[CodeLens] Falling back to polling mode (scan every 5 seconds)...")
        _watch_polling(workspace)
        return

    class CodeLensHandler(FileSystemEventHandler):
        def __init__(self, ws):
            self.workspace = ws

        def _check_and_rescan(self, event):
            if event.is_directory:
                return
            ext = os.path.splitext(event.src_path)[1].lower()
            if ext in ('.html', '.htm', '.css', '.scss', '.less', '.sass',
                       '.js', '.jsx', '.ts', '.tsx', '.rs', '.vue', '.svelte'):
                print(f"[CodeLens] File changed: {event.src_path}")
                print("[CodeLens] Re-scanning workspace (incremental)...")
                result = cmd_scan(self.workspace, incremental=True)
                print(f"[CodeLens] Scan complete: {json.dumps(result, indent=2, ensure_ascii=False)}")

        def on_modified(self, event):
            self._check_and_rescan(event)

        def on_created(self, event):
            self._check_and_rescan(event)

        def on_deleted(self, event):
            self._check_and_rescan(event)

    # Initial scan
    print(f"[CodeLens] Starting initial scan of {workspace}...")
    result = cmd_scan(workspace)
    print(f"[CodeLens] Initial scan complete: {json.dumps(result, indent=2, ensure_ascii=False)}")

    # Start watcher
    observer = Observer()
    handler = CodeLensHandler(workspace)
    observer.schedule(handler, workspace, recursive=True)
    observer.start()

    print(f"[CodeLens] Watching {workspace} for changes... (Press Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("[CodeLens] Stopped.")
    observer.join()


def _watch_polling(workspace: str) -> None:
    """Fallback polling-based watcher."""
    print(f"[CodeLens] Starting initial scan of {workspace}...")
    result = cmd_scan(workspace)
    print(f"[CodeLens] Initial scan complete: {json.dumps(result, indent=2, ensure_ascii=False)}")

    print(f"[CodeLens] Watching {workspace} (polling every 5s)... (Press Ctrl+C to stop)")
    try:
        while True:
            result = cmd_scan(workspace, incremental=True)
            if result.get("message") != "No changes detected. Registry is up to date.":
                print(f"[CodeLens] Changes detected: {json.dumps(result, indent=2, ensure_ascii=False)}")
            time.sleep(5)
    except KeyboardInterrupt:
        print("[CodeLens] Stopped.")


# ─── CLI Entry Point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeLens v2 — Live Codebase Reference Intelligence (Tree-sitter Edition)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ─── Original 6 commands ────────────────────────────

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan workspace and build registry")
    scan_parser.add_argument("workspace", help="Path to workspace root")
    scan_parser.add_argument("--incremental", action="store_true",
                              help="Only re-scan changed files")

    # query command
    query_parser = subparsers.add_parser("query", help="Query a specific class/id/function")
    query_parser.add_argument("name", help="Name to query")
    query_parser.add_argument("workspace", help="Path to workspace root")
    query_parser.add_argument("--domain", choices=["frontend", "backend"], default=None,
                              help="Domain to search")
    query_parser.add_argument("--file", default=None, help="Filter by file path")

    # list command
    list_parser = subparsers.add_parser("list", help="List entries with filter")
    list_parser.add_argument("workspace", help="Path to workspace root")
    list_parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                              help="Domain to list")
    list_parser.add_argument("--filter", dest="filter_type",
                              choices=["all", "dead", "duplicate_define", "duplicate_ref", "collision", "active"],
                              default="all", help="Filter by status")

    # watch command
    watch_parser = subparsers.add_parser("watch", help="Start file watcher")
    watch_parser.add_argument("workspace", help="Path to workspace root")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize .codelens with auto-detected config")
    init_parser.add_argument("workspace", help="Path to workspace root")

    # detect command
    detect_parser = subparsers.add_parser("detect", help="Detect frameworks in workspace")
    detect_parser.add_argument("workspace", help="Path to workspace root")

    # ─── P1: Search, Trace, Impact ──────────────────────

    # search command
    search_parser = subparsers.add_parser("search", help="Search code pattern across workspace")
    search_parser.add_argument("pattern", help="Regex pattern to search for")
    search_parser.add_argument("workspace", help="Path to workspace root")
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
    symbols_parser.add_argument("workspace", help="Path to workspace root")
    symbols_parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                                 help="Domain to search")
    symbols_parser.add_argument("--fuzzy", action="store_true", help="Allow partial/fuzzy matching")

    # trace command
    trace_parser = subparsers.add_parser("trace", help="Trace deep call chain from a symbol")
    trace_parser.add_argument("name", help="Symbol name to trace")
    trace_parser.add_argument("workspace", help="Path to workspace root")
    trace_parser.add_argument("--direction", choices=["up", "down", "both"], default="up",
                               help="Trace direction: up=callers, down=callees, both")
    trace_parser.add_argument("--depth", type=int, default=10, help="Max trace depth (default 10)")
    trace_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                               help="Domain to trace")

    # impact command
    impact_parser = subparsers.add_parser("impact", help="Analyze change impact for a symbol")
    impact_parser.add_argument("name", help="Symbol name to analyze")
    impact_parser.add_argument("workspace", help="Path to workspace root")
    impact_parser.add_argument("--action", choices=["modify", "delete"], default="modify",
                                help="Planned action (modify or delete)")
    impact_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                                help="Domain to analyze")
    impact_parser.add_argument("--depth", type=int, default=5, help="Trace depth (default 5)")

    # ─── P2: Outline, Missing-refs, Diff, Circular ─────

    # outline command
    outline_parser = subparsers.add_parser("outline", help="Get file structure outline")
    outline_parser.add_argument("file", help="File path to outline")
    outline_parser.add_argument("workspace", nargs="?", default=None, help="Workspace root (optional)")
    outline_parser.add_argument("--detail", choices=["minimal", "normal", "full"], default="normal",
                                 help="Detail level")
    outline_parser.add_argument("--all", action="store_true", dest="all_files",
                                 help="Outline all files in workspace")

    # missing-refs command
    missing_refs_parser = subparsers.add_parser("missing-refs", help="Detect CSS/HTML mismatch bugs")
    missing_refs_parser.add_argument("workspace", help="Path to workspace root")

    # diff command
    diff_parser = subparsers.add_parser("diff", help="Compare registry snapshots")
    diff_parser.add_argument("workspace", help="Path to workspace root")
    diff_parser.add_argument("--snapshot1", default=None, help="First snapshot ID (default: second-to-last)")
    diff_parser.add_argument("--snapshot2", default=None, help="Second snapshot ID (default: last)")
    diff_parser.add_argument("--list-snapshots", action="store_true", help="List available snapshots")

    # circular command
    circular_parser = subparsers.add_parser("circular", help="Detect circular dependencies")
    circular_parser.add_argument("workspace", help="Path to workspace root")
    circular_parser.add_argument("--domain", choices=["backend", "imports", "css", "all"], default="all",
                                  help="Which dependency types to check")

    # ─── P3: Context, Dependents, Validate ──────────────

    # context command
    context_parser = subparsers.add_parser("context", help="Get rich symbol context (code + callers + callees)")
    context_parser.add_argument("name", help="Symbol name")
    context_parser.add_argument("workspace", help="Path to workspace root")
    context_parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                                 help="Domain")
    context_parser.add_argument("--context-lines", type=int, default=5,
                                 help="Lines of code context around symbol (default 5)")
    context_parser.add_argument("--no-code", action="store_true", help="Skip source code in output")

    # dependents command
    dependents_parser = subparsers.add_parser("dependents", help="Module-level import tracking")
    dependents_parser.add_argument("file", help="File path to check")
    dependents_parser.add_argument("workspace", help="Path to workspace root")
    dependents_parser.add_argument("--direction", choices=["dependents", "dependencies", "graph"],
                                    default="dependents",
                                    help="Show who imports this file, what this file imports, or full graph")
    dependents_parser.add_argument("--depth", type=int, default=3, help="Trace depth (default 3)")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate registry against file system")
    validate_parser.add_argument("workspace", help="Path to workspace root")

    # ─── Parse and dispatch ─────────────────────────────

    args = parser.parse_args()

    if args.command == "scan":
        result = cmd_scan(args.workspace, args.incremental)
        # Auto-save snapshot after scan
        try:
            frontend = load_frontend_registry(args.workspace)
            backend = load_backend_registry(args.workspace)
            save_snapshot(args.workspace, frontend, backend)
        except Exception:
            pass
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "query":
        result = cmd_query(args.name, args.workspace, args.domain, args.file)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "list":
        result = cmd_list(args.workspace, args.domain, args.filter_type)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "watch":
        cmd_watch(args.workspace)

    elif args.command == "init":
        result = cmd_init(args.workspace)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "detect":
        result = cmd_detect(args.workspace)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # ─── P1 Commands ────────────────────────────────────

    elif args.command == "search":
        config = load_config(os.path.abspath(args.workspace))
        result = search_workspace(
            args.workspace, args.pattern,
            file_type=args.file_type,
            file_filter=args.file,
            max_results=args.max_results,
            context_lines=args.context,
            case_sensitive=not args.ignore_case,
            whole_word=args.whole_word,
            config=config
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "symbols":
        result = search_symbols(
            args.workspace, args.name,
            domain=args.domain,
            fuzzy=args.fuzzy
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "trace":
        result = trace_symbol(
            args.name, args.workspace,
            direction=args.direction,
            max_depth=args.depth,
            domain=args.domain
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "impact":
        result = analyze_impact(
            args.name, args.workspace,
            action=args.action,
            domain=args.domain,
            depth=args.depth
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # ─── P2 Commands ────────────────────────────────────

    elif args.command == "outline":
        if args.all_files:
            ws = args.workspace or os.getcwd()
            result = get_workspace_outline(ws)
        else:
            result = get_file_outline(
                args.file,
                workspace=args.workspace,
                detail_level=args.detail
            )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "missing-refs":
        result = detect_missing_refs(args.workspace)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "diff":
        if args.list_snapshots:
            snaps = list_snapshots(args.workspace)
            print(json.dumps({"snapshots": snaps}, indent=2, ensure_ascii=False))
        elif args.snapshot1 or args.snapshot2:
            result = diff_snapshots(args.workspace, args.snapshot1, args.snapshot2)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            result = diff_current_vs_last(args.workspace)
            print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "circular":
        result = detect_circular(args.workspace, domain=args.domain)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    # ─── P3 Commands ────────────────────────────────────

    elif args.command == "context":
        result = get_symbol_context(
            args.name, args.workspace,
            domain=args.domain,
            context_lines=args.context_lines,
            include_code=not args.no_code
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "dependents":
        if args.direction == "graph":
            result = get_dependency_graph(args.workspace)
        elif args.direction == "dependencies":
            result = get_dependencies(args.file, args.workspace, depth=args.depth)
        else:
            result = get_dependents(args.file, args.workspace, depth=args.depth)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    elif args.command == "validate":
        result = validate_registry(args.workspace)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
