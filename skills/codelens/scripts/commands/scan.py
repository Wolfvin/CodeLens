"""Scan command — Scan workspace and build registry."""

import os
import json
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from utils import logger
from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, save_frontend_registry,
    load_backend_registry, save_backend_registry,
    build_frontend_registry
)
from framework_detect import detect_frameworks, get_recommended_config
from incremental import (
    find_changed_files, update_mtimes_cache, remove_from_mtimes_cache,
    merge_frontend_data, merge_backend_data
)
from edge_resolver import resolve_edges, resolve_tauri_ipc_from_apimap
from parsers.fallback_html import parse_html_fallback
from parsers.fallback_css import parse_css_fallback
from parsers.fallback_js_frontend import parse_js_frontend_fallback
from parsers.fallback_js_backend import parse_js_backend_fallback
from parsers.fallback_rust import parse_rust_fallback
from parsers.fallback_python import parse_python_fallback
from parsers.fallback_java import parse_java_fallback
from parsers.fallback_c import parse_c_fallback
from parsers.fallback_go import parse_go_fallback
from parsers.fallback_lua import parse_lua_fallback
from parsers.fallback_csharp import parse_csharp_fallback

from commands import register_command


def add_args(parser):
    """Add scan-specific arguments to the parser."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only re-scan changed files")


def execute(args, workspace):
    """Execute the scan command."""
    incremental = getattr(args, 'incremental', False)
    # Only auto-enable incremental if the user didn't explicitly request a full scan
    # and the registry already exists. We check for explicit --incremental flag.
    # Note: When user runs "scan" without --incremental, they expect a full scan.
    # Auto-incremental was causing confusion where 2nd scan would miss changes.
    # Now: explicit --incremental for incremental, bare "scan" for full scan.
    return cmd_scan(workspace, incremental)


def cmd_scan(workspace: str, incremental: bool = False) -> Dict[str, Any]:
    """
    Scan the workspace and build/update the registry.
    If incremental=True, only re-scan changed files.
    """
    workspace = os.path.abspath(workspace)
    config = load_config(workspace)
    ensure_codelens_dir(workspace)

    # Always detect frameworks for lang_note / unsupported_langs
    fw = detect_frameworks(workspace)

    # Auto-detect frameworks if not configured
    if not config.get("frameworks"):
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
            # Load existing registry counts
            existing_backend = load_backend_registry(workspace)
            existing_frontend = load_frontend_registry(workspace)
            be_nodes = existing_backend.get("nodes", [])
            be_edges = existing_backend.get("edges", [])
            fe_classes = existing_frontend.get("classes", [])
            fe_ids = existing_frontend.get("ids", [])

            return {
                "status": "ok",
                "workspace": workspace,
                "message": "No changes detected. Registry is up to date.",
                "files_scanned": {k: 0 for k in files},
                "incremental": True,
                "backend": {
                    "nodes": len(be_nodes) if isinstance(be_nodes, list) else be_nodes,
                    "edges": len(be_edges) if isinstance(be_edges, list) else be_edges
                },
                "frontend": {
                    "classes": len(fe_classes) if isinstance(fe_classes, list) else fe_classes,
                    "ids": len(fe_ids) if isinstance(fe_ids, list) else fe_ids
                },
                "frameworks": config.get("frameworks", [])
            }

        # Handle deleted files: remove from mtimes cache and clean registry
        if deleted:
            remove_from_mtimes_cache(workspace, deleted)
            # Remove deleted files from existing registry instead of full rescan
            existing_backend = load_backend_registry(workspace)
            existing_frontend = load_frontend_registry(workspace)

            # Filter out nodes/edges from deleted files
            del_set = set()
            for df in deleted:
                rel = os.path.relpath(df, workspace)
                del_set.add(rel)

            # Clean backend nodes
            be_nodes = existing_backend.get("nodes", [])
            if isinstance(be_nodes, list):
                existing_backend["nodes"] = [n for n in be_nodes if n.get("file", "") not in del_set]
                # Clean edges that reference deleted nodes
                remaining_ids = {n["id"] for n in existing_backend["nodes"] if "id" in n}
                existing_backend["edges"] = [e for e in existing_backend.get("edges", [])
                                              if (e.get("from", "") in remaining_ids
                                                  and (e.get("to", "") in remaining_ids or not e.get("to", "")))]
                save_backend_registry(workspace, existing_backend)

            # Clean frontend data — remove entries whose only references are in deleted files.
            # Class schema: {name, ref_count, status, css: [{path, ...}], js: [{path, ...}]}
            # ID schema: {name, ref_count, status, defined_in_html: [{path, ...}], css: [{path, ...}], js: [{path, ...}]}
            fe_classes = existing_frontend.get("classes", [])
            if isinstance(fe_classes, list):
                cleaned_classes = []
                for c in fe_classes:
                    # Strip refs from deleted files, keep refs from surviving files
                    surviving_css = [r for r in c.get("css", []) if r.get("path", "") not in del_set]
                    surviving_js = [r for r in c.get("js", []) if r.get("path", "") not in del_set]
                    if surviving_css or surviving_js:
                        c["css"] = surviving_css
                        c["js"] = surviving_js
                        c["ref_count"] = len(surviving_css) + len(surviving_js)
                        c["status"] = "active" if c["ref_count"] > 0 else "dead"
                        cleaned_classes.append(c)
                    # else: all refs were in deleted files → drop the entry
                existing_frontend["classes"] = cleaned_classes

                fe_ids = existing_frontend.get("ids", [])
                cleaned_ids = []
                for i in fe_ids:
                    surviving_html = [r for r in i.get("defined_in_html", []) if r.get("path", "") not in del_set]
                    surviving_css = [r for r in i.get("css", []) if r.get("path", "") not in del_set]
                    surviving_js = [r for r in i.get("js", []) if r.get("path", "") not in del_set]
                    if surviving_html or surviving_css or surviving_js:
                        i["defined_in_html"] = surviving_html
                        i["css"] = surviving_css
                        i["js"] = surviving_js
                        i["ref_count"] = len(surviving_css) + len(surviving_js)
                        i["status"] = "active" if i["ref_count"] > 0 else ("dead" if not surviving_html else "active")
                        cleaned_ids.append(i)
                    # else: all refs were in deleted files → drop the entry
                existing_frontend["ids"] = cleaned_ids
                save_frontend_registry(workspace, existing_frontend)

            # Continue with incremental scan for changed/new files
            changed_files = set(changed + new)
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
            logger.debug("HTML tree-sitter parser not available, using fallback")

        for path in files["html"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if html_parser:
                    refs = html_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = parse_html_fallback(content, os.path.relpath(path, workspace))
                html_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                logger.debug(f"Failed to read HTML file: {path}")

    # Parse CSS files
    css_data = []
    if files["css"]:
        css_parser = None
        try:
            from parsers.css_parser import CSSParser
            css_parser = CSSParser()
        except Exception:
            logger.debug("CSS tree-sitter parser not available, using fallback")

        for path in files["css"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if css_parser:
                    refs = css_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = parse_css_fallback(content, os.path.relpath(path, workspace))
                css_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                logger.debug(f"Failed to read CSS file: {path}")

    # Parse JS Frontend files
    js_frontend_data = []
    if files["js_frontend"]:
        js_fe_parser = None
        try:
            from parsers.js_frontend_parser import JSFrontendParser
            js_fe_parser = JSFrontendParser()
        except Exception:
            logger.debug("JS frontend tree-sitter parser not available, using fallback")

        for path in files["js_frontend"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if js_fe_parser:
                    refs = js_fe_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = parse_js_frontend_fallback(content, os.path.relpath(path, workspace))
                js_frontend_data.append({
                    "path": os.path.relpath(path, workspace),
                    "classes": refs.get("classes", []),
                    "ids": refs.get("ids", [])
                })
            except IOError:
                logger.debug(f"Failed to read JS frontend file: {path}")

    # Parse TSX/JSX files
    tsx_data = []
    tsx_backend_data = []
    if files["tsx"]:
        tsx_parser = None
        try:
            from parsers.tsx_parser import TSXParser
            tsx_parser = TSXParser()
        except Exception:
            logger.debug("TSX tree-sitter parser not available, using fallback")

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
                    # Fallback: use BOTH frontend and backend parsers
                    fb_refs = parse_js_frontend_fallback(content, os.path.relpath(path, workspace))
                    tsx_data.append({
                        "path": os.path.relpath(path, workspace),
                        "frontend": fb_refs,
                    })
                    # Also extract backend data (functions, imports) from TSX
                    be_refs = parse_js_backend_fallback(content, os.path.relpath(path, workspace))
                    if be_refs.get("nodes") or be_refs.get("edges"):
                        tsx_backend_data.append({
                            "path": os.path.relpath(path, workspace),
                            "nodes": be_refs.get("nodes", []),
                            "edges": be_refs.get("edges", [])
                        })
            except IOError:
                logger.debug(f"Failed to read TSX/JSX file: {path}")

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
                logger.debug(f"Failed to read Vue file: {path}")

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
                logger.debug(f"Failed to read Svelte file: {path}")

    # Tailwind analysis
    # In incremental mode, skip tailwind re-analysis since we only have
    # classes from changed files — the merge will preserve existing tailwind info
    tailwind_info = None
    if not (incremental and changed_files):
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
                logger.debug("Tailwind analysis failed", exc_info=True)

    # Build frontend registry
    if incremental and changed_files:
        # Incremental: merge new parsed data into existing registry
        existing_frontend = load_frontend_registry(workspace)
        frontend_registry = merge_frontend_data(
            existing_frontend, html_data, css_data, js_frontend_data,
            tsx_data, vue_data, svelte_data, tailwind_info,
            changed_files, workspace, config.get("frameworks", [])
        )
    else:
        # Full scan: build from scratch
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
            logger.debug("JS backend tree-sitter parser not available, using fallback")

        ts_be_parser = None
        try:
            from parsers.ts_backend_parser import TSBackendParser
            ts_be_parser = TSBackendParser()
        except (ImportError, RuntimeError) as e:
            logger.warning(f"TSBackendParser init failed, using JS fallback: {e}")

        for path in files["js_backend"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                rel_path = os.path.relpath(path, workspace)
                ext = os.path.splitext(path)[1].lower()
                if ext == '.ts' and ts_be_parser:
                    refs = ts_be_parser.extract_references(content, rel_path)
                elif js_be_parser:
                    refs = js_be_parser.extract_references(content, rel_path)
                else:
                    refs = parse_js_backend_fallback(content, rel_path)
                js_backend_data.append({
                    "path": rel_path,
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read JS backend file: {path}")

    # Parse Rust files
    rust_data = []
    if files["rust"]:
        rust_parser = None
        try:
            from parsers.rust_parser import RustParser
            rust_parser = RustParser()
        except Exception:
            logger.debug("Rust tree-sitter parser not available, using fallback")

        for path in files["rust"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if rust_parser:
                    refs = rust_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = parse_rust_fallback(content, os.path.relpath(path, workspace))
                rust_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Rust file: {path}")

    # Parse Python files
    python_data = []
    if files["python"]:
        py_parser = None
        try:
            from parsers.python_parser import PythonParser
            py_parser = PythonParser()
        except Exception:
            logger.debug("Python tree-sitter parser not available, using fallback")

        for path in files["python"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                if py_parser:
                    refs = py_parser.extract_references(content, os.path.relpath(path, workspace))
                else:
                    refs = parse_python_fallback(content, os.path.relpath(path, workspace))
                python_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Python file: {path}")

    # Parse Java/Kotlin files
    java_data = []
    if files["java"]:
        for path in files["java"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_java_fallback(content, os.path.relpath(path, workspace))
                java_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Java file: {path}")

    # Parse C/C++ files
    c_cpp_data = []
    if files["c_cpp"]:
        for path in files["c_cpp"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_c_fallback(content, os.path.relpath(path, workspace))
                c_cpp_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read C/C++ file: {path}")

    # Parse Go files
    go_data = []
    if files["go"]:
        for path in files["go"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_go_fallback(content, os.path.relpath(path, workspace))
                go_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Go file: {path}")

    # Parse Lua files
    lua_data = []
    if files["lua"]:
        for path in files["lua"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_lua_fallback(content, os.path.relpath(path, workspace))
                lua_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Lua file: {path}")

    # Parse C# files
    csharp_data = []
    if files["csharp"]:
        for path in files["csharp"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_csharp_fallback(content, os.path.relpath(path, workspace))
                csharp_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read C# file: {path}")

    # All new language data combined
    _new_lang_data = java_data + c_cpp_data + go_data + lua_data + csharp_data

    # Normalize nodes: ensure 'fn' key exists for edge_resolver compatibility
    for item in _new_lang_data:
        for node in item.get("nodes", []):
            if "fn" not in node and "name" in node:
                node["fn"] = node["name"]

    # Build backend registry with edge resolution
    if incremental and changed_files:
        existing_backend = load_backend_registry(workspace)
        new_parsed_data = rust_data + js_backend_data + python_data + _new_lang_data
        backend_registry = merge_backend_data(
            existing_backend, new_parsed_data,
            changed_files, workspace
        )
        resolved_nodes = backend_registry["nodes"]
        resolved_edges = backend_registry["edges"]
    else:
        all_nodes = []
        all_raw_edges = []
        for item in rust_data + js_backend_data + python_data + _new_lang_data:
            all_nodes.extend(item.get("nodes", []))
            all_raw_edges.extend(item.get("edges", []))

        resolved_nodes, resolved_edges = resolve_edges(all_nodes, all_raw_edges)

        # ─── Tauri IPC cross-language edge resolution ─────────────
        # After resolving same-language edges, add cross-language edges
        # for Tauri IPC: TypeScript invoke('commandName') → Rust handler.
        # This is critical for Tauri apps where frontend calls Rust backend
        # via the IPC bridge. Without this, Rust #[tauri::command] handlers
        # appear "dead" because no Rust code calls them directly.
        if 'tauri' in config.get("frameworks", []):
            try:
                from apimap_engine import map_api_routes
                api_result = map_api_routes(workspace)
                api_routes = api_result.get("routes", [])
                resolved_edges = resolve_tauri_ipc_from_apimap(
                    resolved_nodes, resolved_edges, api_routes
                )
                # Recompute ref_counts with the new IPC edges
                incoming_count = {}
                for node in resolved_nodes:
                    incoming_count[node["id"]] = 0
                for edge in resolved_edges:
                    to_id = edge.get("to")
                    if to_id and to_id in incoming_count:
                        incoming_count[to_id] += 1
                for node in resolved_nodes:
                    node["ref_count"] = incoming_count.get(node["id"], 0)
                    if node.get("is_tauri_command") and node["ref_count"] == 0:
                        node["status"] = "ipc_exposed"
                    else:
                        node["status"] = "dead" if node["ref_count"] == 0 else "active"
            except Exception:
                logger.warning("Failed to resolve Tauri IPC edges", exc_info=True)

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
            "svelte": len(files["svelte"]),
            "java": len(files["java"]),
            "c_cpp": len(files["c_cpp"]),
            "go": len(files["go"]),
            "lua": len(files["lua"]),
            "csharp": len(files["csharp"]),
        },
        "python_parsed": len(python_data),
        "java_parsed": len(java_data),
        "c_cpp_parsed": len(c_cpp_data),
        "go_parsed": len(go_data),
        "lua_parsed": len(lua_data),
        "csharp_parsed": len(csharp_data),
        "frontend": {
            "classes": len(frontend_registry["classes"]),
            "ids": len(frontend_registry["ids"])
        },
        "backend": {
            "nodes": len(resolved_nodes),
            "edges": len(resolved_edges)
        },
        "frameworks": config.get("frameworks", []),
        "incremental": incremental,
        "changed_files_count": len(changed_files) if changed_files else 0,
        "unsupported_langs": fw.get("unsupported_langs", []) if fw else [],
        "lang_note": _build_lang_note(fw) if fw else None,
    }


def _build_lang_note(fw: Dict) -> Optional[str]:
    """Build a note about unsupported languages detected in the workspace."""
    unsupported = fw.get("unsupported_langs", [])
    if not unsupported:
        return None
    supported = {"html", "css", "javascript", "typescript", "tsx", "python", "rust", "vue", "svelte"}
    lang_names = {
        "go": "Go",
        "java": "Java",
        "kotlin": "Kotlin",
        "c": "C",
        "cpp": "C++",
        "csharp": "C#",
        "swift": "Swift",
        "ruby": "Ruby",
    }
    parts = [lang_names.get(l, l) for l in unsupported]
    return f"Detected {', '.join(parts)} source files — these languages are not yet supported by tree-sitter parsers. Analysis will be limited to frontend assets (JS/TS/CSS/HTML) and any supported backend code."


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
        "svelte": [],
        "java": [],
        "c_cpp": [],
        "go": [],
        "lua": [],
        "csharp": [],
    }

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        
        if should_ignore(rel_root, config):
            dirs.clear()
            continue

        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if should_ignore(rel_path, config):
                continue

            ext = os.path.splitext(filename)[1].lower()

            # Skip TypeScript declaration files (auto-generated, no runtime code)
            if filename.endswith('.d.ts') or filename.endswith('.d.tsx'):
                continue

            if ext in ('.html', '.htm'):
                files["html"].append(file_path)
            elif ext == '.css':
                files["css"].append(file_path)
            elif ext in ('.jsx',):
                files["tsx"].append(file_path)
            elif ext == '.tsx':
                files["tsx"].append(file_path)
            elif ext in ('.js', '.ts'):
                if ext == '.ts' and is_frontend_file(rel_path, config):
                    files["tsx"].append(file_path)
                elif is_frontend_file(rel_path, config):
                    files["js_frontend"].append(file_path)
                elif is_backend_file(rel_path, config):
                    files["js_backend"].append(file_path)
                else:
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
            elif ext in ('.java', '.kt'):
                files["java"].append(file_path)
            elif ext in ('.c', '.cpp', '.h', '.hpp', '.cc', '.cxx', '.hxx'):
                files["c_cpp"].append(file_path)
            elif ext == '.go':
                files["go"].append(file_path)
            elif ext == '.lua':
                files["lua"].append(file_path)
            elif ext in ('.cs',):
                files["csharp"].append(file_path)

    return files


def is_frontend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a frontend path."""
    # Normalize to forward slashes
    normalized = file_path.replace('\\', '/')
    for fp in config.get("frontend_paths", []):
        fp_norm = fp.replace('\\', '/')
        # Match as path segment prefix
        if normalized.startswith(fp_norm) or f"/{fp_norm}" in normalized or normalized == fp_norm:
            return True
    return False


def is_backend_file(file_path: str, config: Dict) -> bool:
    """Check if a file is in a backend path."""
    # Normalize to forward slashes
    normalized = file_path.replace('\\', '/')
    for bp in config.get("backend_paths", []):
        bp_norm = bp.replace('\\', '/')
        # Match as path segment prefix
        if normalized.startswith(bp_norm) or f"/{bp_norm}" in normalized or normalized == bp_norm:
            return True
    return False


def should_ignore(file_path: str, config: Dict) -> bool:
    """Check if a file should be ignored.
    
    Uses path-segment-aware matching to avoid false positives.
    For example, pattern "target/" matches "project/target/" but NOT
    "project/test-target/" because "target" must be a complete path segment.
    
    The pattern is expected to have a trailing slash (e.g., "node_modules/").
    Matching checks if any path segment starts with the pattern prefix.
    """
    # Normalize to forward slashes for consistent matching
    normalized = file_path.replace('\\', '/')
    
    for pattern in config.get("ignore", []):
        # Normalize pattern too
        pat = pattern.replace('\\', '/')
        
        # Strip trailing slash for segment matching
        pat_prefix = pat.rstrip('/')
        
        # Check if the pattern appears as a path segment
        # A segment is preceded by '/' or is at the start of the path
        # Pattern "target" should match "/target/" or start with "target/"
        # but NOT "/test-target/" or "/my_target/"
        
        # Check 1: pattern is at the start of the path (e.g., "node_modules/pkg/")
        if normalized.startswith(pat_prefix + '/'):
            return True
        
        # Check 2: pattern appears as a full segment (preceded by '/')
        if '/' + pat_prefix + '/' in normalized:
            return True
        
        # Check 3: pattern matches the entire last segment (e.g., path ends with "/.git")
        if normalized.endswith('/' + pat_prefix):
            return True
        
        # Check 4: exact match
        if normalized == pat_prefix:
            return True
    
    return False


register_command("scan", "Scan workspace and build registry", add_args, execute)
