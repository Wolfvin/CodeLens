#!/usr/bin/env python3
"""
CodeLens — Live Codebase Reference Intelligence
CLI tool for scanning, querying, and listing code references.

Usage:
    python3 codelens.py scan <workspace>           # Scan workspace and build registry
    python3 codelens.py query <name> <workspace>   # Query a specific class/id/function
    python3 codelens.py list <workspace> [filter]   # List entries with filter
    python3 codelens.py watch <workspace>           # Start file watcher
    python3 codelens.py init <workspace>            # Initialize .codelens config
"""

import sys
import os
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from parsers.html_parser import extract_html_references, detect_id_collisions
from parsers.css_parser import extract_css_references
from parsers.js_frontend_parser import extract_js_frontend_references
from parsers.js_backend_parser import extract_js_backend_references
from parsers.rust_parser import extract_rust_references
from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, save_frontend_registry,
    load_backend_registry, save_backend_registry,
    build_frontend_registry, build_backend_registry,
    compute_frontend_status, compute_backend_status
)


# ─── File Discovery ───────────────────────────────────────────

def is_frontend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a frontend path."""
    frontend_paths = config.get("frontend_paths", [])
    for fp in frontend_paths:
        if fp in file_path:
            return True
    return False


def is_backend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a backend path."""
    backend_paths = config.get("backend_paths", [])
    for bp in backend_paths:
        if bp in file_path:
            return True
    return False


def should_ignore(file_path: str, config: Dict) -> bool:
    """Check if a file should be ignored."""
    ignore_patterns = config.get("ignore", ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"])
    for pattern in ignore_patterns:
        if pattern in file_path:
            return True
    return False


def discover_files(workspace: str, config: Dict) -> Dict[str, List[str]]:
    """
    Discover all relevant source files in the workspace.

    Returns:
        {
            "html": [paths],
            "css": [paths],
            "js_frontend": [paths],
            "js_backend": [paths],
            "rust": [paths]
        }
    """
    files = {
        "html": [],
        "css": [],
        "js_frontend": [],
        "js_backend": [],
        "rust": []
    }

    for root, dirs, filenames in os.walk(workspace):
        # Filter out ignored directories
        rel_root = os.path.relpath(root, workspace)
        if should_ignore(rel_root + "/", config):
            dirs.clear()  # Don't descend into ignored directories
            continue

        # Also check absolute path
        if should_ignore(root, config):
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
            elif ext == '.js' or ext == '.jsx' or ext == '.ts' or ext == '.tsx':
                if is_frontend_file(rel_path, config):
                    files["js_frontend"].append(file_path)
                elif is_backend_file(rel_path, config):
                    files["js_backend"].append(file_path)
                else:
                    # Default: JS Backend Parser (safer assumption per spec)
                    files["js_backend"].append(file_path)
            elif ext == '.rs':
                files["rust"].append(file_path)

    return files


# ─── Scan Command ─────────────────────────────────────────────

def cmd_scan(workspace: str) -> Dict[str, Any]:
    """
    Scan the entire workspace and build/update the registry.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)

    # Ensure .codelens directory exists
    ensure_codelens_dir(workspace)
    save_config(workspace, config)

    # Discover files
    files = discover_files(workspace, config)

    # Parse HTML files
    html_data = []
    all_html_ids = []  # For collision detection across files
    for path in files["html"]:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        refs = extract_html_references(content, os.path.relpath(path, workspace))
        # Detect ID collisions within this file
        refs["ids"] = detect_id_collisions(refs["ids"])
        html_data.append({
            "path": os.path.relpath(path, workspace),
            "classes": refs["classes"],
            "ids": refs["ids"]
        })
        all_html_ids.extend(refs["ids"])

    # Parse CSS files
    css_data = []
    for path in files["css"]:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        refs = extract_css_references(content, os.path.relpath(path, workspace))
        css_data.append({
            "path": os.path.relpath(path, workspace),
            "classes": refs["classes"],
            "ids": refs["ids"]
        })

    # Parse JS Frontend files
    js_frontend_data = []
    for path in files["js_frontend"]:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        refs = extract_js_frontend_references(content, os.path.relpath(path, workspace))
        js_frontend_data.append({
            "path": os.path.relpath(path, workspace),
            "classes": refs["classes"],
            "ids": refs["ids"]
        })

    # Build frontend registry
    frontend_registry = build_frontend_registry(workspace, html_data, css_data, js_frontend_data)
    save_frontend_registry(workspace, frontend_registry)

    # Parse JS Backend files
    js_backend_data = []
    for path in files["js_backend"]:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        refs = extract_js_backend_references(content, os.path.relpath(path, workspace))
        js_backend_data.append({
            "path": os.path.relpath(path, workspace),
            "nodes": refs["nodes"],
            "edges": refs["edges"]
        })

    # Parse Rust files
    rust_data = []
    for path in files["rust"]:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        refs = extract_rust_references(content, os.path.relpath(path, workspace))
        rust_data.append({
            "path": os.path.relpath(path, workspace),
            "nodes": refs["nodes"],
            "edges": refs["edges"]
        })

    # Build backend registry
    backend_registry = build_backend_registry(workspace, rust_data, js_backend_data)
    save_backend_registry(workspace, backend_registry)

    # Summary
    result = {
        "status": "ok",
        "workspace": workspace,
        "files_scanned": {
            "html": len(files["html"]),
            "css": len(files["css"]),
            "js_frontend": len(files["js_frontend"]),
            "js_backend": len(files["js_backend"]),
            "rust": len(files["rust"])
        },
        "frontend": {
            "classes": len(frontend_registry["classes"]),
            "ids": len(frontend_registry["ids"])
        },
        "backend": {
            "nodes": len(backend_registry["nodes"]),
            "edges": len(backend_registry["edges"])
        }
    }

    return result


# ─── Query Command ────────────────────────────────────────────

def cmd_query(query_name: str, workspace: str, domain: str = None, file_filter: str = None) -> Dict[str, Any]:
    """
    Query a specific class/id/function from the registry.
    Returns a single entry with all references, locations, and status.
    """
    workspace = os.path.abspath(workspace)

    # Try frontend first if domain is "frontend" or auto-detect
    if domain in (None, "frontend"):
        frontend = load_frontend_registry(workspace)

        # Search in classes
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

        # Search in ids
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

    # Try backend if domain is "backend" or auto-detect
    if domain in (None, "backend"):
        backend = load_backend_registry(workspace)

        # Search in nodes
        for node in backend.get("nodes", []):
            if node["fn"] == query_name:
                if file_filter and file_filter not in node.get("file", ""):
                    continue

                # Find callers (incoming edges)
                callers = []
                for edge in backend.get("edges", []):
                    if edge.get("to") == node["id"]:
                        callers.append({"from": edge["from"]})

                # Find callees (outgoing edges)
                callees = []
                for edge in backend.get("edges", []):
                    if edge.get("from") == node["id"]:
                        to_id = edge.get("to", "")
                        to_fn = edge.get("to_fn", "")
                        # Look up callee status
                        callee_status = "unknown"
                        for n in backend.get("nodes", []):
                            if n["id"] == to_id:
                                callee_status = n.get("status", "unknown")
                                break
                        callee_entry = {"to": to_id or to_fn}
                        if callee_status != "unknown":
                            callee_entry["status"] = callee_status
                        callees.append(callee_entry)

                result = {
                    "found": True,
                    "type": "function",
                    "domain": "backend",
                    "node": {
                        "id": node["id"],
                        "fn": node["fn"],
                        "ref_count": node["ref_count"],
                        "status": node["status"],
                        "file": node.get("file", ""),
                        "line": node.get("line", 0),
                        "async": node.get("async", False)
                    },
                    "callers": callers,
                    "callees": callees
                }

                if node.get("impl_for"):
                    result["node"]["impl_for"] = node["impl_for"]
                if node.get("duplicate_define"):
                    result["node"]["duplicate_define"] = True

                return result

    # Not found
    return {
        "found": False,
        "query": query_name,
        "domain": domain or "auto"
    }


# ─── List Command ─────────────────────────────────────────────

def cmd_list(workspace: str, domain: str, filter_type: str = "all") -> Dict[str, Any]:
    """
    List all entries with optional filter.

    Filters: all | dead | duplicate_define | duplicate_ref | collision | active
    """
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
            # Get first definition location
            if cls.get("css"):
                entry["defined_in"] = f"{cls['css'][0]['path']}:{cls['css'][0]['line']}"
            elif cls.get("js"):
                entry["defined_in"] = f"{cls['js'][0]['path']}:{cls['js'][0]['line']}"

            # Apply filter
            if filter_type == "all" or cls["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define":
                # Check if any CSS ref has duplicate_define flag
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
                "ref_count": node["ref_count"],
                "status": node["status"],
                "defined_in": f"{node['file']}:{node['line']}"
            }

            if filter_type == "all" or node["status"] == filter_type:
                results.append(entry)
            elif filter_type == "duplicate_define" and node.get("duplicate_define"):
                results.append(entry)

    return {
        "domain": domain,
        "filter": filter_type,
        "count": len(results),
        "results": results
    }


# ─── Init Command ─────────────────────────────────────────────

def cmd_init(workspace: str) -> Dict[str, Any]:
    """Initialize .codelens directory with default config."""
    workspace = os.path.abspath(workspace)
    codelens_dir = ensure_codelens_dir(workspace)
    config = load_config(workspace)
    save_config(workspace, config)

    return {
        "status": "ok",
        "workspace": workspace,
        "codelens_dir": codelens_dir,
        "config": config
    }


# ─── Watch Command ────────────────────────────────────────────

def cmd_watch(workspace: str) -> None:
    """
    Start file watcher for real-time registry updates.
    Uses watchdog library if available, falls back to polling.
    """
    workspace = os.path.abspath(workspace)

    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        print("watchdog not installed. Install with: pip install watchdog")
        print("Falling back to polling mode (scan every 5 seconds)...")
        _watch_polling(workspace)
        return

    class CodeLensHandler(FileSystemEventHandler):
        def __init__(self, ws):
            self.workspace = ws

        def on_modified(self, event):
            if event.is_directory:
                return
            ext = os.path.splitext(event.src_path)[1].lower()
            if ext in ('.html', '.htm', '.css', '.js', '.jsx', '.ts', '.tsx', '.rs'):
                print(f"[CodeLens] File changed: {event.src_path}")
                print("[CodeLens] Re-scanning workspace...")
                result = cmd_scan(self.workspace)
                print(f"[CodeLens] Scan complete: {json.dumps(result, indent=2)}")

        def on_created(self, event):
            if event.is_directory:
                return
            ext = os.path.splitext(event.src_path)[1].lower()
            if ext in ('.html', '.htm', '.css', '.js', '.jsx', '.ts', '.tsx', '.rs'):
                print(f"[CodeLens] File created: {event.src_path}")
                print("[CodeLens] Re-scanning workspace...")
                result = cmd_scan(self.workspace)
                print(f"[CodeLens] Scan complete: {json.dumps(result, indent=2)}")

        def on_deleted(self, event):
            if event.is_directory:
                return
            ext = os.path.splitext(event.src_path)[1].lower()
            if ext in ('.html', '.htm', '.css', '.js', '.jsx', '.ts', '.tsx', '.rs'):
                print(f"[CodeLens] File deleted: {event.src_path}")
                print("[CodeLens] Re-scanning workspace...")
                result = cmd_scan(self.workspace)
                print(f"[CodeLens] Scan complete: {json.dumps(result, indent=2)}")

    # Initial scan
    print(f"[CodeLens] Starting initial scan of {workspace}...")
    result = cmd_scan(workspace)
    print(f"[CodeLens] Initial scan complete: {json.dumps(result, indent=2)}")

    # Start watcher
    observer = Observer()
    handler = CodeLensHandler(workspace)
    observer.schedule(handler, workspace, recursive=True)
    observer.start()

    print(f"[CodeLens] Watching {workspace} for changes... (Press Ctrl+C to stop)")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("[CodeLens] Stopped.")
    observer.join()


def _watch_polling(workspace: str) -> None:
    """Fallback polling-based watcher."""
    import time

    print(f"[CodeLens] Starting initial scan of {workspace}...")
    result = cmd_scan(workspace)
    print(f"[CodeLens] Initial scan complete: {json.dumps(result, indent=2)}")

    # Track file modification times
    file_mtimes: Dict[str, float] = {}

    print(f"[CodeLens] Watching {workspace} (polling every 5s)... (Press Ctrl+C to stop)")
    try:
        while True:
            config = load_config(workspace)
            files = discover_files(workspace, config)
            all_files = (
                files["html"] + files["css"] +
                files["js_frontend"] + files["js_backend"] +
                files["rust"]
            )

            changed = False
            for f in all_files:
                try:
                    mtime = os.path.getmtime(f)
                    if f not in file_mtimes:
                        file_mtimes[f] = mtime
                    elif mtime > file_mtimes[f]:
                        file_mtimes[f] = mtime
                        changed = True
                        print(f"[CodeLens] File changed: {f}")
                except OSError:
                    pass

            if changed:
                print("[CodeLens] Re-scanning workspace...")
                result = cmd_scan(workspace)
                print(f"[CodeLens] Scan complete: {json.dumps(result, indent=2)}")

            time.sleep(5)
    except KeyboardInterrupt:
        print("[CodeLens] Stopped.")


# ─── CLI Entry Point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeLens — Live Codebase Reference Intelligence"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan command
    scan_parser = subparsers.add_parser("scan", help="Scan workspace and build registry")
    scan_parser.add_argument("workspace", help="Path to workspace root")

    # query command
    query_parser = subparsers.add_parser("query", help="Query a specific class/id/function")
    query_parser.add_argument("name", help="Name to query")
    query_parser.add_argument("workspace", help="Path to workspace root")
    query_parser.add_argument("--domain", choices=["frontend", "backend"], default=None,
                              help="Domain to search (auto-detect if not specified)")
    query_parser.add_argument("--file", default=None,
                              help="Filter by file path")

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
    init_parser = subparsers.add_parser("init", help="Initialize .codelens config")
    init_parser.add_argument("workspace", help="Path to workspace root")

    args = parser.parse_args()

    if args.command == "scan":
        result = cmd_scan(args.workspace)
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

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
