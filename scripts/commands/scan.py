"""Scan command — Scan workspace and build registry."""

import argparse
import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

from utils import logger
from registry import (
    load_config, save_config, ensure_codelens_dir,
    load_frontend_registry, save_frontend_registry,
    load_backend_registry, save_backend_registry,
    build_frontend_registry
)
# 3-tier .codelensignore support (issue #55). Module imports pathspec
# lazily and gracefully degrades to fnmatch if pathspec is unavailable.
try:
    from codelensignore import is_ignored as _codelensignore_is_ignored
    from codelensignore import suggest_ignore_directories as _suggest_ignore_dirs
except ImportError:  # pragma: no cover — defensive: module lives in scripts/
    _codelensignore_is_ignored = None
    _suggest_ignore_dirs = None
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
from parsers.fallback_php import parse_php_fallback
from parsers.blade_parser import parse_blade_template
from parsers.fallback_ruby import parse_ruby_fallback
from parsers.fallback_elixir import parse_elixir_fallback
from parsers.fallback_dart_extra import parse_dart_fallback
from parsers.fallback_swift import parse_swift_fallback
from parsers.fallback_scala import parse_scala_fallback
from parsers.fallback_shell import parse_shell_fallback
from parsers.fallback_gdscript import parse_gdscript_fallback
from parsers.fallback_kotlin import parse_kotlin_fallback
from parsers.fallback_objc import parse_objc_fallback

# Issue #56: regex prefilter — skip files that definitely won't match any
# rule before expensive tree-sitter parsing. Conservative: when in doubt,
# scan the file. See scripts/prefilter.py for the guarantee contract.
try:
    from prefilter import build_prefilter, should_scan_file, PrefilterStats
except ImportError:  # pragma: no cover — defensive: module lives in scripts/
    build_prefilter = None
    should_scan_file = None
    PrefilterStats = None

from commands import register_command


def add_args(parser):
    """Add scan-specific arguments to the parser."""
    # Issue #180: surface incremental behavior + noise-reduction flags directly
    # in `codelens scan --help`. The flags themselves are added by the dispatcher
    # in codelens.py; this epilog just points users at them.
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Notes:\n"
        "  First scan builds the SQLite graph (slower). Subsequent scans are\n"
        "  incremental — pass --incremental to only re-scan changed files.\n"
        "  Reduce noise in large repos with --format compact (token-efficient\n"
        "  single-char keys for AI/script consumption) or --lite (minimal output)."
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--incremental", action="store_true",
                        help="Only re-scan changed files")
    parser.add_argument("--plugins", nargs="*", default=None,
                        help="Enable plugin rules: specify plugin names or 'all' for all rule_pack plugins")
    parser.add_argument("--max-files", type=int, default=None,
                        help="Cap total files scanned (default: unlimited). "
                             "Used by auto-setup to prevent timeout on huge repos.")
    parser.add_argument("--suggest-ignore", action="store_true",
                        help="Print the top-10 largest directories (by total file "
                             "size) that are NOT currently ignored by .codelensignore. "
                             "Does not perform a scan; useful for tuning ignore rules.")
    # Issue #56: regex prefilter — skip files that definitely won't match
    # any rule before tree-sitter parsing. Active by default (no-op when no
    # rules are loaded). --no-prefilter disables it entirely.
    parser.add_argument("--no-prefilter", dest="use_prefilter",
                        action="store_false", default=True,
                        help="Disable the regex prefilter (issue #56). By default "
                             "the scan skips files that contain none of the literal "
                             "tokens from loaded rules, before tree-sitter parsing. "
                             "Pass this flag to force-parse every discovered file. "
                             "The prefilter is conservative (no false negatives) — "
                             "use this flag only for debugging or benchmarking.")
    parser.add_argument("--verbose", action="store_true", default=False,
                        help="Print prefilter statistics and other diagnostic "
                             "information to stderr (issue #56).")
    # Issue #10: RAM-first indexing — print a one-line timing breakdown
    # to stderr after the scan completes. Off by default so the default
    # scan output is byte-identical to the pre-#10 behavior (backward
    # compat). The flag is a no-op for incremental scans that detect
    # zero changes (no parse or write work happens in that case, so the
    # stats line is suppressed).
    parser.add_argument("--scan-stats", dest="scan_stats",
                        action="store_true", default=False,
                        help="Print scan timing breakdown to stderr after the "
                             "scan completes (issue #10). Format: "
                             "'Scan stats: N files, M nodes, K edges' + "
                             "'Index time: Xs (parse: Ys, write: Zs)'. "
                             "Off by default — does not affect scan output.")
    # Issue #46: Semgrep-compatible YAML rule engine — additive flag.
    # When supplied, the rule engine (scripts/rule_engine.py) runs after
    # the tree-sitter scan completes and prints one finding per match to
    # stderr. Backward compat: omitting the flag keeps scan output byte-
    # identical to the pre-#46 behavior.
    parser.add_argument("--rule-file", dest="rule_files",
                        action="append", default=None,
                        metavar="<path.yaml>",
                        help="Path to a Semgrep-compatible YAML rule file "
                             "(issue #46). May be passed multiple times. "
                             "Additive — does not change default scan behavior.")


def execute(args, workspace):
    """Execute the scan command."""
    # --suggest-ignore short-circuits the normal scan flow.
    if getattr(args, 'suggest_ignore', False):
        return _run_suggest_ignore(workspace)

    incremental = getattr(args, 'incremental', False)
    plugins = getattr(args, 'plugins', None)
    max_files = getattr(args, 'max_files', None)
    use_prefilter = getattr(args, 'use_prefilter', True)
    verbose = getattr(args, 'verbose', False)
    scan_stats = getattr(args, 'scan_stats', False)
    rule_files = getattr(args, 'rule_files', None)
    # Only auto-enable incremental if the user didn't explicitly request a full scan
    # and the registry already exists. We check for explicit --incremental flag.
    # Note: When user runs "scan" without --incremental, they expect a full scan.
    # Auto-incremental was causing confusion where 2nd scan would miss changes.
    # Now: explicit --incremental for incremental, bare "scan" for full scan.
    result = cmd_scan(workspace, incremental, plugins=plugins, max_files=max_files,
                      use_prefilter=use_prefilter, verbose=verbose,
                      scan_stats=scan_stats)

    # Issue #46: run the Semgrep-compat rule engine after the scan completes.
    # Additive — when --rule-file is omitted, _run_rule_files is a no-op and
    # the scan output stays byte-identical to the pre-#46 behavior.
    if rule_files:
        _run_rule_files(workspace, rule_files, verbose=verbose)

    return result


def _run_rule_files(workspace: str, rule_files: list, verbose: bool = False) -> None:
    """Issue #46 — run the Semgrep-compatible rule engine across the workspace.

    Walks the workspace and runs :mod:`rule_engine` against every Python file.
    Findings are printed to stderr (one per line) so they don't pollute the
    machine-readable scan result on stdout. Failures (parse errors, missing
    rule files) are logged but never crash the scan — the rule engine is
    strictly additive.

    Phase 1: Python-only. Non-Python files are skipped silently.
    """
    try:
        from rule_engine import run_rules_against_file, format_match_for_cli
    except ImportError as exc:
        import sys
        print(f"codelens: rule engine unavailable (--rule-file ignored): {exc}",
              file=sys.stderr)
        return

    workspace = os.path.abspath(workspace)
    py_exts = {".py", ".pyw", ".pyi"}
    for dirpath, _dirs, files in os.walk(workspace):
        # Respect .codelensignore if available — skip ignored dirs entirely
        if _codelensignore_is_ignored is not None:
            try:
                if _codelensignore_is_ignored(dirpath + os.sep, workspace):
                    continue
            except Exception:
                pass
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext not in py_exts:
                continue
            file_path = os.path.join(dirpath, name)
            if _codelensignore_is_ignored is not None:
                try:
                    if _codelensignore_is_ignored(file_path, workspace):
                        continue
                except Exception:
                    pass
            result = run_rules_against_file(file_path, rule_files)
            if result.error:
                import sys
                print(f"codelens: {result.error}", file=sys.stderr)
                continue
            for m in result.matches:
                import sys
                print(format_match_for_cli(m, file_path), file=sys.stderr)
            if verbose and result.matches:
                import sys
                print(f"codelens: {file_path}: {len(result.matches)} rule finding(s)",
                      file=sys.stderr)


def _run_suggest_ignore(workspace: str) -> Dict[str, Any]:
    """Handle ``scan --suggest-ignore`` — print top-10 largest non-ignored dirs.

    Returns a dict suitable for the CLI formatter. Walks the workspace once,
    sums per-directory file sizes (non-recursively), and returns the largest
    directories not matched by the 3-tier ``.codelensignore`` system.
    """
    workspace = os.path.abspath(workspace)
    if _suggest_ignore_dirs is None:  # pragma: no cover — defensive
        return {
            "status": "error",
            "workspace": workspace,
            "error": "codelensignore module unavailable",
        }
    top = _suggest_ignore_dirs(workspace, top_n=10)
    return {
        "status": "ok",
        "workspace": workspace,
        "command": "scan --suggest-ignore",
        "suggestion_count": len(top),
        "suggestions": top,
        "hint": (
            "Add these paths to .codelensignore (workspace or ~/.codelensignore) "
            "to skip them in future scans."
        ),
    }


def cmd_scan(workspace: str, incremental: bool = False, plugins: Optional[list] = None,
             max_files: Optional[int] = None, use_prefilter: bool = True,
             verbose: bool = False, scan_stats: bool = False) -> Dict[str, Any]:
    """
    Scan the workspace and build/update the registry.

    If incremental=True, only re-scan changed files.
    If plugins is provided, load plugin rules for the scan.
    If max_files is provided and > 0, cap the total number of discovered files
    that get parsed (used by auto-setup to prevent timeout on huge repos).
    If use_prefilter=True (default), apply the regex prefilter (issue #56) to
    skip files that definitely won't match any loaded rule before tree-sitter
    parsing. The prefilter is conservative (no false negatives) and a no-op
    when no rules are loaded.
    If verbose=True, print prefilter statistics to stderr.
    If scan_stats=True (issue #10), print a one-line timing breakdown to
    stderr after the scan completes:

        Scan stats: 1240 files, 3091 nodes, 29285 edges
        Index time: 2.3s (parse: 1.8s, write: 0.5s)

    The breakdown is suppressed for incremental scans that detect zero
    changes (no parse or write work happens in that case).
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

    # Apply max_files cap (auto-setup uses this to bound scan time on huge repos).
    # The cap is applied AFTER discovery but BEFORE parsing, so os.walk cost is
    # unchanged but parsing/registry-build cost is bounded.
    if max_files is not None and max_files > 0:
        files = _cap_discovered_files(files, max_files)

    # ─── Issue #56: regex prefilter ──────────────────────────────
    # Build a conservative regex prefilter from loaded rules and skip files
    # that definitely won't match before expensive tree-sitter parsing.
    # The prefilter is a no-op when no rules are loaded (returns None →
    # should_scan_file always returns True). --no-prefilter disables the
    # entire code path. Plugin rules are loaded here (early) so the
    # prefilter can use them; the same rules are reused below for
    # plugin_rules_data so we don't double-load.
    prefilter_stats = PrefilterStats() if PrefilterStats is not None else None
    prefilter = None
    plugin_rules = []  # populated when plugins is set; reused for plugin_rules_data
    if use_prefilter and build_prefilter is not None:
        # Load plugin rules early so the prefilter can use them.
        # We reuse this list later for plugin_rules_data to avoid a
        # double-load. If plugins is falsy, no rules are loaded and the
        # prefilter stays None (no-op).
        if plugins:
            try:
                from plugin_system import get_plugin_manager
                _pf_mgr = get_plugin_manager(workspace)
                _pf_mgr.discover_plugins()
                if "all" in plugins:
                    plugin_rules = _pf_mgr.get_rules()
                else:
                    for _pf_name in plugins:
                        _pf_mgr.load_plugin(_pf_name)
                    plugin_rules = [r for r in _pf_mgr.get_rules()
                                    if r.plugin_name in plugins]
            except Exception as e:
                logger.warning(f"Failed to load plugin rules for prefilter: {e}")
                plugin_rules = []
        # Build the prefilter from whatever rules we have. PluginRule
        # objects expose .to_dict(); raw rule dicts are passed as-is.
        rule_dicts = []
        for r in plugin_rules:
            if hasattr(r, "to_dict"):
                rule_dicts.append(r.to_dict())
            elif isinstance(r, dict):
                rule_dicts.append(r)
        try:
            prefilter = build_prefilter(rule_dicts)
        except Exception:
            # Conservative: never let prefilter build crash the scan.
            logger.debug("build_prefilter failed", exc_info=True)
            prefilter = None

        # Apply the prefilter to each category's file list. We filter the
        # lists in place so the parsing loops below don't need to change.
        # Stats are tracked across all categories.
        if prefilter is not None and should_scan_file is not None:
            _pf_start = time.time()
            for _cat, _file_list in files.items():
                if not _file_list:
                    continue
                _kept = []
                for _path in _file_list:
                    _passed = should_scan_file(_path, prefilter)
                    if prefilter_stats is not None:
                        prefilter_stats.record(_passed)
                    if _passed:
                        _kept.append(_path)
                files[_cat] = _kept
            if prefilter_stats is not None:
                prefilter_stats.elapsed_sec = time.time() - _pf_start
        # If prefilter is None (no rules / no tokens), no filtering happens
        # and prefilter_stats stays at zeros — which is correct: 0 files
        # checked by the prefilter because it was a no-op.

    # Check if incremental scan is possible
    changed_files = None
    if incremental:
        all_discovered = []
        for file_list in files.values():
            all_discovered.extend(file_list)
        # Pass the db_path so find_changed_files can look up the
        # last_indexed_sha bookmark and use git-diff when available
        # (issue #14). Falls back to mtime inside the function.
        from graph_model import _default_db_path as _scan_db_path
        changed, new, deleted = find_changed_files(
            workspace, all_discovered, db_path=_scan_db_path(workspace)
        )

        if not changed and not new and not deleted:
            # Load existing registry counts
            existing_backend = load_backend_registry(workspace)
            existing_frontend = load_frontend_registry(workspace)
            be_nodes = existing_backend.get("nodes", [])
            be_edges = existing_backend.get("edges", [])
            fe_classes = existing_frontend.get("classes", [])
            fe_ids = existing_frontend.get("ids", [])

            # No changes detected → graph tables are unchanged from the
            # previous scan. Report current graph stats so the scan
            # output shape (issue #25) matches the full-scan output:
            # both expose a `graph` field with `{nodes, edges}`.
            graph_stats_existing = {"nodes": 0, "edges": 0}
            try:
                from graph_model import graph_stats as _graph_stats
                from graph_model import _default_db_path as _scan_db_path2
                graph_stats_existing = _graph_stats(_scan_db_path2(workspace))
            except Exception:
                logger.debug(
                    "graph_stats failed in no-changes path", exc_info=True
                )

            return {
                "status": "ok",
                "workspace": workspace,
                "message": "No changes detected. Registry is up to date.",
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
                    "kotlin": len(files["kotlin"]),
                    "c_cpp": len(files["c_cpp"]),
                    "go": len(files["go"]),
                    "lua": len(files["lua"]),
                    "csharp": len(files["csharp"]),
                    "php": len(files["php"]),
                    "blade": len(files["blade"]),
                    "ruby": len(files["ruby"]),
                    "elixir": len(files["elixir"]),
                    "dart": len(files["dart"]),
                    "swift": len(files["swift"]),
                    "scala": len(files["scala"]),
                    "shell": len(files["shell"]),
                    "gdscript": len(files["gdscript"]),
                },
                # In the no-changes case, all discovered files were previously
                # parsed, so *_parsed equals discovered file counts.
                "python_parsed": len(files["python"]),
                "java_parsed": len(files["java"]),
                "kotlin_parsed": len(files["kotlin"]),
                "c_cpp_parsed": len(files["c_cpp"]),
                "go_parsed": len(files["go"]),
                "lua_parsed": len(files["lua"]),
                "csharp_parsed": len(files["csharp"]),
                "php_parsed": len(files["php"]),
                "blade_parsed": len(files["blade"]),
                "ruby_parsed": len(files["ruby"]),
                "elixir_parsed": len(files["elixir"]),
                "dart_parsed": len(files["dart"]),
                "swift_parsed": len(files["swift"]),
                "scala_parsed": len(files["scala"]),
                "shell_parsed": len(files["shell"]),
                "gdscript_parsed": len(files["gdscript"]),
                "incremental": True,
                "changed_files_count": 0,
                "backend": {
                    "nodes": len(be_nodes) if isinstance(be_nodes, list) else be_nodes,
                    "edges": len(be_edges) if isinstance(be_edges, list) else be_edges
                },
                "frontend": {
                    "classes": len(fe_classes) if isinstance(fe_classes, list) else fe_classes,
                    "ids": len(fe_ids) if isinstance(fe_ids, list) else fe_ids
                },
                "frameworks": config.get("frameworks", []),
                "unsupported_langs": fw.get("unsupported_langs", []) if fw else [],
                "lang_note": _build_lang_note(fw) if fw else None,
                # Issue #25: incremental scan output includes graph stats
                # so consumers can verify graph is populated without a
                # separate `graph-schema` call.
                "graph": {
                    "nodes": graph_stats_existing.get("nodes", 0),
                    "edges": graph_stats_existing.get("edges", 0),
                },
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

    # ─── Issue #10: RAM-first indexing — timing breakdown ──────────
    # ``parse_start`` marks the entry into the file-parsing phase (HTML,
    # CSS, JS, Rust, Python, etc.). ``parse_end`` is captured right
    # before the graph-table write phase begins; ``write_end`` is
    # captured after the post-scan refine pass (full scan) or after
    # ``incremental_graph_update`` (incremental scan). The breakdown is
    # only printed when the caller passes ``scan_stats=True`` — the
    # default scan output stays byte-identical to the pre-#10 behavior.
    _scan_stats_parse_start = time.perf_counter()

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

    # Parse Blade templates (Laravel .blade.php files)
    # Blade templates contain HTML classes/IDs that belong in the frontend registry
    blade_data = []
    if files["blade"]:
        for path in files["blade"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_blade_template(content, os.path.relpath(path, workspace))
                # Merge Blade frontend data into html_data format
                fe = refs.get("frontend", {})
                if fe.get("classes") or fe.get("ids"):
                    blade_data.append({
                        "path": os.path.relpath(path, workspace),
                        "classes": fe.get("classes", []),
                        "ids": fe.get("ids", [])
                    })
            except IOError:
                logger.debug(f"Failed to read Blade file: {path}")

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
    # Merge Blade template data into html_data (same format: path, classes, ids)
    html_data_with_blade = html_data + blade_data

    if incremental and changed_files:
        # Incremental: merge new parsed data into existing registry
        existing_frontend = load_frontend_registry(workspace)
        frontend_registry = merge_frontend_data(
            existing_frontend, html_data_with_blade, css_data, js_frontend_data,
            tsx_data, vue_data, svelte_data, tailwind_info,
            changed_files, workspace, config.get("frameworks", [])
        )
    else:
        # Full scan: build from scratch
        frontend_registry = build_frontend_registry(
            workspace, html_data_with_blade, css_data, js_frontend_data,
            tsx_data, vue_data, svelte_data,
            tailwind_info, config.get("frameworks", [])
        )
    save_frontend_registry(workspace, frontend_registry)

    # Parse JS Backend files
    js_backend_data = tsx_backend_data.copy()
    # Issue #163: collect files explicitly skipped by parsers (e.g. files
    # above the absolute hard limit of 10,000 lines). Each parser may
    # return a ``skipped`` list in its refs dict — we aggregate them here
    # so the scan result can report incomplete coverage to the caller
    # instead of silently dropping files.
    skipped_files: list = []
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
                # Issue #163: aggregate explicit skip entries
                skipped_files.extend(refs.get("skipped", []))
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
                # Issue #163: aggregate explicit skip entries
                skipped_files.extend(refs.get("skipped", []))
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
                # Issue #163: aggregate explicit skip entries
                skipped_files.extend(refs.get("skipped", []))
            except IOError:
                logger.debug(f"Failed to read Python file: {path}")

    # Parse Java files
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

    # Parse Kotlin files
    kotlin_data = []
    if files["kotlin"]:
        for path in files["kotlin"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_kotlin_fallback(content, os.path.relpath(path, workspace))
                kotlin_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Kotlin file: {path}")

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

    # Parse PHP files
    php_data = []
    if files["php"]:
        for path in files["php"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_php_fallback(content, os.path.relpath(path, workspace))
                php_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read PHP file: {path}")

    # Parse Ruby files
    ruby_data = []
    if files["ruby"]:
        for path in files["ruby"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_ruby_fallback(content, os.path.relpath(path, workspace))
                ruby_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Ruby file: {path}")

    # Parse Elixir files
    elixir_data = []
    if files["elixir"]:
        for path in files["elixir"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_elixir_fallback(content, os.path.relpath(path, workspace))
                elixir_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Elixir file: {path}")

    # Parse Dart files
    dart_data = []
    if files["dart"]:
        for path in files["dart"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_dart_fallback(content, os.path.relpath(path, workspace))
                dart_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Dart file: {path}")

    # Parse Swift files
    swift_data = []
    if files["swift"]:
        for path in files["swift"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_swift_fallback(content, os.path.relpath(path, workspace))
                swift_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Swift file: {path}")

    # Parse Scala files
    scala_data = []
    if files["scala"]:
        for path in files["scala"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_scala_fallback(content, os.path.relpath(path, workspace))
                scala_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Scala file: {path}")

    # Parse Shell/Bash files
    shell_data = []
    if files["shell"]:
        for path in files["shell"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_shell_fallback(content, os.path.relpath(path, workspace))
                shell_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Shell file: {path}")

    # Parse GDScript files
    gdscript_data = []
    if files["gdscript"]:
        for path in files["gdscript"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_gdscript_fallback(content, os.path.relpath(path, workspace))
                gdscript_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read GDScript file: {path}")

    # Parse Objective-C files (.m/.mm)
    objc_data = []
    if files["objc"]:
        for path in files["objc"]:
            if incremental and changed_files and path not in changed_files:
                continue
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                refs = parse_objc_fallback(content, os.path.relpath(path, workspace))
                objc_data.append({
                    "path": os.path.relpath(path, workspace),
                    "nodes": refs.get("nodes", []),
                    "edges": refs.get("edges", [])
                })
            except IOError:
                logger.debug(f"Failed to read Objective-C file: {path}")


    # All new language data combined
    _new_lang_data = java_data + kotlin_data + c_cpp_data + go_data + lua_data + csharp_data + php_data + ruby_data + elixir_data + dart_data + swift_data + scala_data + shell_data + gdscript_data + objc_data

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

    # ─── Issue #10: RAM-first indexing — parse phase end ─────────
    # All file parsing (HTML, CSS, JS, Rust, Python, etc.) is complete
    # and the flat registries are saved. The next phase writes the
    # graph_nodes + graph_edges tables to SQLite in a single
    # ``BEGIN EXCLUSIVE`` batch — that's the "write" portion of the
    # scan-stats breakdown.
    _scan_stats_parse_end = time.perf_counter()
    _scan_stats_write_start = _scan_stats_parse_end

    # ─── Graph Data Model Population (issue #8 + #25) ────────────
    # After the flat backend registry is built, populate (full scan) or
    # incrementally update (incremental scan) the graph_nodes + graph_edges
    # tables. The incremental path (issue #25) updates only the affected
    # slice — graph stays in sync without a full re-population.
    #
    # In incremental mode, incremental_graph_update also runs
    # refine_call_edges internally (so we skip the redundant full refine
    # call below). In full-scan mode, populate_graph_tables + refine_call_edges
    # run separately (existing flow from #8 + #13).
    #
    # Failures here MUST NOT break the scan — the graph is an optimization
    # layer; engines fall back to the flat registry if it's missing.
    type_resolution = {"edges_refined": 0, "edges_unresolved": 0}
    if incremental and changed_files:
        try:
            from graph_model import (
                incremental_graph_update, _default_db_path,
            )
            db_path = _default_db_path(workspace)
            inc_result = incremental_graph_update(
                workspace, db_path, changed_files
            )
            type_resolution = {
                "edges_refined": inc_result.get("edges_refined", 0),
                "edges_unresolved": inc_result.get("edges_unresolved", 0),
            }
        except Exception:
            logger.warning("Incremental graph update failed", exc_info=True)
    else:
        try:
            from graph_model import populate_graph_tables, _default_db_path
            db_path = _default_db_path(workspace)
            populate_graph_tables(workspace, db_path)
        except Exception:
            logger.warning("Graph table population failed", exc_info=True)

        # ─── Hybrid Type Resolution (issue #13) ──────────────────
        # Post-pass that enriches CALLS edges with receiver type info via
        # an import-aware resolver. Also writes IMPORTS edges to graph_edges
        # and populates the import_registry table. Additive — only refines
        # existing edges in place; never removes or replaces them. Failures
        # here MUST NOT break the scan (type resolution is an optimization
        # layer; unresolved edges fall back to name-based resolution).
        try:
            from hybrid_type_resolver import refine_call_edges
            from graph_model import _default_db_path as _tr_db_path
            tr_stats = refine_call_edges(workspace, _tr_db_path(workspace))
            type_resolution = {
                "edges_refined": tr_stats.get("edges_refined", 0),
                "edges_unresolved": tr_stats.get("edges_unresolved", 0),
            }
        except Exception:
            logger.warning("Hybrid type resolution failed", exc_info=True)

    # ─── Issue #10: RAM-first indexing — write phase end ─────────
    # Both ``populate_graph_tables`` (full scan) and
    # ``incremental_graph_update`` (incremental scan, includes an
    # internal ``refine_call_edges`` call) are now complete. The
    # ``write`` portion of the scan-stats breakdown covers all SQLite
    # batch writes that happen after parsing.
    _scan_stats_write_end = time.perf_counter()

    # ─── Git-aware scan bookmark (issue #14) ─────────────────────
    # After a successful scan, record the current HEAD SHA + branch so the
    # next `scan --incremental` can diff against this bookmark instead of
    # relying solely on filesystem mtimes. Additive — if git is unavailable
    # or the workspace is not a git repo, this is a no-op. Failures here
    # MUST NOT break the scan (git-awareness is an optimization layer).
    git_bookmark = {"sha": None, "branch": None}
    try:
        from git_aware import get_current_sha, get_current_branch, set_last_indexed_sha
        from graph_model import _default_db_path as _git_db_path
        sha = get_current_sha(workspace)
        if sha:
            branch = get_current_branch(workspace)
            set_last_indexed_sha(workspace, _git_db_path(workspace), sha)
            git_bookmark = {"sha": sha, "branch": branch}
    except Exception:
        logger.debug("Git bookmark update failed", exc_info=True)

    # Update mtimes cache
    all_files = []
    for file_list in files.values():
        all_files.extend(file_list)
    update_mtimes_cache(workspace, all_files)

    # ─── Plugin Rules Integration ──────────────────────
    # Note: plugin_rules was already loaded above (early, for the prefilter)
    # when use_prefilter=True and plugins is set. When use_prefilter=False,
    # plugin_rules is empty and we load it here instead. This avoids a
    # double-load in the common (prefilter active) path.
    plugin_rules_data = None
    if plugins:
        try:
            if plugin_rules:
                # Already loaded by the prefilter block — reuse it. We
                # still need a plugin manager for get_rules_yaml().
                from plugin_system import get_plugin_manager
                mgr = get_plugin_manager(workspace)
                mgr.discover_plugins()
                # Make sure the requested plugins are loaded into the
                # manager so get_rules_yaml returns their rules.
                if "all" not in plugins:
                    for plugin_name in plugins:
                        mgr.load_plugin(plugin_name)
            else:
                # Prefilter was disabled (or build_prefilter unavailable) —
                # load plugin rules here for the metadata block below.
                from plugin_system import get_plugin_manager
                mgr = get_plugin_manager(workspace)
                mgr.discover_plugins()
                if "all" in plugins:
                    plugin_rules = mgr.get_rules()
                else:
                    for plugin_name in plugins:
                        mgr.load_plugin(plugin_name)
                    plugin_rules = [r for r in mgr.get_rules() if r.plugin_name in plugins]

            plugin_rules_data = {
                "total_rules": len(plugin_rules),
                "plugins_used": list(set(r.plugin_name for r in plugin_rules)),
                "rules_yaml": mgr.get_rules_yaml(
                    tags=None if "all" in plugins else None
                ),
            }
        except Exception as e:
            logger.warning(f"Failed to load plugin rules: {e}")
            plugin_rules_data = {"error": str(e)}

    # ─── Final graph stats (issue #25) ───────────────────────────
    # Query the actual graph state AFTER all post-scan passes (populate +
    # refine for full scan; incremental_graph_update for incremental scan)
    # so the reported counts reflect the true final state — CALLS + IMPORTS
    # edges, after type resolution. Both full and incremental paths report
    # the same shape so consumers can compare counts across scan modes.
    final_graph_stats = {"nodes": 0, "edges": 0}
    try:
        from graph_model import graph_stats as _final_graph_stats
        from graph_model import _default_db_path as _final_db_path
        final_graph_stats = _final_graph_stats(_final_db_path(workspace))
    except Exception:
        logger.debug("final graph_stats query failed", exc_info=True)

    result = {
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
            "kotlin": len(files["kotlin"]),
            "c_cpp": len(files["c_cpp"]),
            "go": len(files["go"]),
            "lua": len(files["lua"]),
            "csharp": len(files["csharp"]),
            "php": len(files["php"]),
            "blade": len(files["blade"]),
            "ruby": len(files["ruby"]),
            "elixir": len(files["elixir"]),
            "dart": len(files["dart"]),
            "swift": len(files["swift"]),
            "scala": len(files["scala"]),
            "shell": len(files["shell"]),
            "gdscript": len(files["gdscript"]),
            "objc": len(files["objc"]),
        },
        "python_parsed": len(python_data),
        "java_parsed": len(java_data),
        "kotlin_parsed": len(kotlin_data),
        "c_cpp_parsed": len(c_cpp_data),
        "go_parsed": len(go_data),
        "lua_parsed": len(lua_data),
        "csharp_parsed": len(csharp_data),
        "php_parsed": len(php_data),
        "blade_parsed": len(blade_data),
        "ruby_parsed": len(ruby_data),
        "elixir_parsed": len(elixir_data),
        "dart_parsed": len(dart_data),
        "swift_parsed": len(swift_data),
        # Issue #163: files explicitly skipped by parsers (e.g. > 10,000
        # lines). Always present — empty list means no files were skipped
        # and coverage is complete. Each entry: {"file": str, "reason":
        # str, "lines": int}. Replaces the previous silent-skip behavior
        # where large files would vanish from the graph without trace.
        "skipped_files": skipped_files,
        "scala_parsed": len(scala_data),
        "shell_parsed": len(shell_data),
        "gdscript_parsed": len(gdscript_data),
        "objc_parsed": len(objc_data),
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
        # Issue #25: graph field reflects the actual final state of
        # graph_nodes + graph_edges (CALLS + IMPORTS, after type
        # resolution). Both full and incremental scans report the same
        # shape so consumers can compare counts across scan modes.
        "graph": {
            "nodes": final_graph_stats.get("nodes", 0),
            "edges": final_graph_stats.get("edges", 0),
        },
        "type_resolution": {
            "edges_refined": type_resolution.get("edges_refined", 0),
            "edges_unresolved": type_resolution.get("edges_unresolved", 0),
        },
        "git": {
            "last_indexed_sha": git_bookmark.get("sha"),
            "last_indexed_branch": git_bookmark.get("branch"),
        },
        # Issue #56: regex prefilter stats. Always present (even when the
        # prefilter was a no-op) so consumers can tell whether filtering
        # happened. When use_prefilter=False or no rules were loaded,
        # checked/passed/skipped are all 0.
        "prefilter": {
            "enabled": use_prefilter and prefilter is not None,
            "stats": prefilter_stats.to_dict() if prefilter_stats is not None else {
                "checked": 0, "passed": 0, "skipped": 0,
                "skip_percent": 0.0, "elapsed_sec": 0.0,
            },
        },
    }

    # Issue #56: print prefilter stats to stderr when --verbose. Matches
    # the documented one-line format from the issue spec:
    #   Prefilter: 1240 files checked, 387 passed, 853 skipped (68%) in 0.3s
    if verbose and prefilter_stats is not None and prefilter_stats.checked > 0:
        import sys as _sys
        print(prefilter_stats.format_verbose_line(), file=_sys.stderr)

    # ─── Issue #10: RAM-first indexing — scan-stats breakdown ───
    # Print a two-line timing summary to stderr when ``--scan-stats`` was
    # passed. The breakdown is suppressed for incremental scans that
    # detected zero changes (no parse or write work happens in that
    # case — ``_scan_stats_parse_start`` is set unconditionally at the
    # top of the parse phase, but the no-changes short-circuit at L265
    # returns before we get here, so we only need to guard against the
    # ``changed_files is None`` case for incremental scans that DID
    # reach this point with empty ``changed_files``).
    #
    # Output is to stderr so the default scan output (stdout JSON /
    # formatted text) is byte-identical to the pre-#10 behavior.
    if scan_stats:
        _scan_stats_total_files = sum(
            (count if isinstance(count, int) else 0)
            for count in (result.get("files_scanned", {}) or {}).values()
        )
        _scan_stats_graph = result.get("graph", {}) or {}
        _scan_stats_nodes = int(_scan_stats_graph.get("nodes", 0) or 0)
        _scan_stats_edges = int(_scan_stats_graph.get("edges", 0) or 0)
        _scan_stats_parse_s = max(
            0.0, _scan_stats_parse_end - _scan_stats_parse_start
        )
        _scan_stats_write_s = max(
            0.0, _scan_stats_write_end - _scan_stats_write_start
        )
        _scan_stats_total_s = _scan_stats_parse_s + _scan_stats_write_s
        import sys as _scan_stats_sys
        print(
            "Scan stats: {f} files, {n} nodes, {e} edges".format(
                f=_scan_stats_total_files,
                n=_scan_stats_nodes,
                e=_scan_stats_edges,
            ),
            file=_scan_stats_sys.stderr,
        )
        print(
            "Index time: {t:.1f}s (parse: {p:.1f}s, write: {w:.1f}s)".format(
                t=_scan_stats_total_s,
                p=_scan_stats_parse_s,
                w=_scan_stats_write_s,
            ),
            file=_scan_stats_sys.stderr,
        )

    # Add plugin rules data if plugins were requested
    if plugin_rules_data is not None:
        result["plugins"] = plugin_rules_data

    return result


def _build_lang_note(fw: Dict) -> Optional[str]:
    """Build a note about unsupported languages detected in the workspace."""
    unsupported = fw.get("unsupported_langs", [])
    if not unsupported:
        return None
    lang_names = {
        "go": "Go",
        "java": "Java",
        "kotlin": "Kotlin",
        "c": "C",
        "cpp": "C++",
        "csharp": "C#",
        "swift": "Swift",
        "ruby": "Ruby",
        "elixir": "Elixir",
        "dart": "Dart",
        "scala": "Scala",
        "shell": "Shell/Bash",
        "r": "R",
        "haskell": "Haskell",
        "perl": "Perl",
        "clojure": "Clojure",
        "fsharp": "F#",
        "ocaml": "OCaml",
        "zig": "Zig",
        "nim": "Nim",
        "erlang": "Erlang",
        "fortran": "Fortran",
        "gdscript": "GDScript",
        "objc": "Objective-C",
    }
    parts = [lang_names.get(l, l) for l in unsupported]
    return f"Detected {', '.join(parts)} source files — these languages do not have dedicated parsers yet. CodeLens uses regex-based fallback extraction for many languages, but analysis may be less accurate than for fully supported languages (JS/TS/Python/Rust/HTML/CSS). Note: Go, Java, Kotlin, C/C++, C#, Ruby, Elixir, Dart, Swift, Scala, Shell, PHP, GDScript, Lua, and Objective-C all have fallback parsers; they are listed here only when no parser exists."


def _cap_discovered_files(files: Dict[str, List[str]], max_files: int) -> Dict[str, List[str]]:
    """Cap total files across all categories to ``max_files``.

    Truncates per-category lists in dict iteration order until the budget
    is exhausted; remaining categories are emptied. Used by auto-setup to
    bound scan time on huge repos (issue #34).
    """
    capped: Dict[str, List[str]] = {}
    remaining = max_files
    for key, file_list in files.items():
        if not file_list or remaining <= 0:
            capped[key] = []
            continue
        take = file_list[:remaining]
        capped[key] = take
        remaining -= len(take)
    return capped


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
        "kotlin": [],
        "c_cpp": [],
        "go": [],
        "lua": [],
        "csharp": [],
        "php": [],
        "blade": [],
        "ruby": [],
        "elixir": [],
        "dart": [],
        "swift": [],
        "scala": [],
        "shell": [],
        "gdscript": [],
        "objc": [],
    }

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)

        if should_ignore(rel_root, config):
            dirs.clear()
            continue

        # 3-tier .codelensignore check (issue #55). Augments the existing
        # config-based should_ignore() above; builtin patterns cover the
        # historical DEFAULT_IGNORE_DIRS set so backward compat is preserved.
        #
        # Issue #120: do NOT ``dirs.clear()`` when the directory matches a
        # .codelensignore pattern — a ``!``-negation deeper in the tree
        # (e.g. ``src/`` ignored but ``!src/utils.py`` re-included) must
        # still be honored. Per-file checks below will filter individual
        # files; we only prune subdirectories via the config-based
        # ``should_ignore`` above (which has no negation semantics).
        if _codelensignore_is_ignored is not None and _codelensignore_is_ignored(rel_root, workspace):
            # Don't recurse into subdirectories of an ignored directory
            # ONLY when there are no negation patterns that could re-include
            # descendants. Quick heuristic: if any pattern starts with ``!``,
            # keep recursing so per-file negation works. Otherwise prune
            # for performance (avoids walking node_modules/ subtrees).
            _has_negation = False
            try:
                from codelensignore import load_patterns
                _pats = load_patterns(workspace)
                _has_negation = any(p.startswith('!') for p in _pats)
            except Exception:
                _has_negation = True  # Safe default: keep recursing
            if not _has_negation:
                dirs.clear()
                continue
            # Else: fall through and let per-file checks filter

        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if should_ignore(rel_path, config):
                continue

            # 3-tier .codelensignore check for individual files.
            if _codelensignore_is_ignored is not None and _codelensignore_is_ignored(rel_path, workspace):
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
            elif ext == '.java':
                files["java"].append(file_path)
            elif ext == '.kt':
                files["kotlin"].append(file_path)
            elif ext in ('.c', '.cpp', '.h', '.hpp', '.cc', '.cxx', '.hxx'):
                files["c_cpp"].append(file_path)
            elif ext == '.go':
                files["go"].append(file_path)
            elif ext == '.lua':
                files["lua"].append(file_path)
            elif ext in ('.cs',):
                files["csharp"].append(file_path)
            elif ext == '.php':
                if filename.endswith('.blade.php'):
                    files["blade"].append(file_path)
                else:
                    files["php"].append(file_path)
            elif ext == '.rb':
                files["ruby"].append(file_path)
            elif ext in ('.ex', '.exs'):
                files["elixir"].append(file_path)
            elif ext == '.dart':
                files["dart"].append(file_path)
            elif ext == '.swift':
                files["swift"].append(file_path)
            elif ext == '.gd':
                files["gdscript"].append(file_path)
            elif ext in ('.scala', '.sc'):
                files["scala"].append(file_path)
            elif ext in ('.sh', '.bash', '.zsh'):
                files["shell"].append(file_path)
            elif filename == 'Dockerfile' or filename.endswith('.Dockerfile'):
                files["shell"].append(file_path)
            elif ext in ('.m', '.mm'):
                files["objc"].append(file_path)
            elif filename in ('Rakefile', 'Gemfile', 'Capfile', 'Vagrantfile'):
                files["ruby"].append(file_path)
            elif ext == '.rake':
                files["ruby"].append(file_path)
            elif filename == 'mix.exs':
                files["elixir"].append(file_path)
            else:
                # ─── Issue #18: universal grammar loader fallback ──────
                # For extensions/filenames not in the curated dispatch
                # above, defer to ``universal_grammar_loader.detect_language``.
                # Detected files are bucketed under their canonical language
                # name (e.g. ``sql``, ``yaml``, ``toml``, ``terraform`` …)
                # so downstream consumers can pick them up without modifying
                # this hardcoded chain. Files with no detectable language
                # are silently skipped (graceful degradation).
                try:
                    from universal_grammar_loader import detect_language as _detect_lang
                except ImportError:  # pragma: no cover — module lives in scripts/
                    _detect_lang = None
                if _detect_lang is not None:
                    detected = _detect_lang(file_path)
                    if detected:
                        files.setdefault(detected, []).append(file_path)

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
