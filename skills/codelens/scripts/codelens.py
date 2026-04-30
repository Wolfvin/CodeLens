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

    args = parser.parse_args()

    if args.command == "scan":
        result = cmd_scan(args.workspace, args.incremental)
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

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
