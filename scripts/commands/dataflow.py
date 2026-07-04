"""Dataflow command — Trace data flow source→sink (security).

Supports both the original regex-based dataflow engine and the new
cross-file call graph engine with tree-sitter AST parsing.

Use --cross-file to enable cross-file analysis with call graph resolution
(default when tree-sitter is available).
Use --no-cross-file to force single-file regex-based analysis.
"""

from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--source", default=None,
                        help="Source filter (user_input, env_var, file_input, api_response)")
    parser.add_argument("--sink", default=None,
                        help="Sink filter (db_query, html_output, command_exec, file_write, http_header)")
    parser.add_argument("--depth", type=int, default=15, help="Max data flow chain depth (default 15)")
    parser.add_argument("--max-files", type=int, default=3000,
                        help="Max files to scan (default 3000, use 0 for all)")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Time budget in seconds (default 120)")
    parser.add_argument("--cross-file", action="store_true", default=False,
                        help="Enable cross-file analysis with call graph resolution")
    parser.add_argument("--no-cross-file", action="store_true", default=False,
                        help="Disable cross-file analysis, use single-file regex engine")
    parser.add_argument("--language", choices=["python", "javascript", "typescript"], default=None,
                        help="Filter analysis to a specific language")
    parser.add_argument("--call-graph-only", action="store_true", default=False,
                        help="Only build and display the call graph (no taint analysis)")


def execute(args, workspace):
    cross_file = getattr(args, 'cross_file', False)
    no_cross_file = getattr(args, 'no_cross_file', False)
    call_graph_only = getattr(args, 'call_graph_only', False)
    language = getattr(args, 'language', None)

    # Determine engine: cross-file (call graph) vs single-file (regex)
    use_cross_file = False
    if no_cross_file:
        use_cross_file = False
    elif cross_file:
        use_cross_file = True
    else:
        # Default: use cross-file engine when tree-sitter is available
        try:
            from callgraph_engine import is_available
            use_cross_file = is_available()
        except ImportError:
            use_cross_file = False

    if call_graph_only:
        # Just build and display the call graph
        return _execute_call_graph_only(workspace, args, language)

    if use_cross_file:
        return _execute_cross_file(workspace, args, language)
    else:
        return _execute_legacy(workspace, args)


def _execute_cross_file(workspace, args, language):
    """Execute using the enhanced cross-file dataflow engine."""
    try:
        from callgraph_engine import analyze_with_callgraph

        source_filter = getattr(args, 'source', None)
        sink_filter = getattr(args, 'sink', None)

        result = analyze_with_callgraph(
            workspace=workspace,
            language=language,
            max_files=args.max_files,
            timeout_sec=float(args.timeout),
            max_depth=args.depth,
            source_filter=source_filter,
            sink_filter=sink_filter,
        )

        # Ensure engine is tagged
        result["engine"] = "callgraph_engine"

        # Add actionable items for --format ai
        if result.get("status") == "ok" and not result.get("actionable_items"):
            result["actionable_items"] = _generate_actionable_items(result)

        return result

    except ImportError as e:
        # Fallback to legacy engine
        from dataflow_engine import trace_dataflow
        result = trace_dataflow(
            workspace,
            source=args.source,
            sink=args.sink,
            max_depth=args.depth,
            max_files=args.max_files,
            timeout_sec=float(args.timeout),
        )
        result["engine"] = "dataflow_regex_fallback"
        result["fallback_reason"] = f"Call graph engine unavailable: {e}"
        return result


def _execute_call_graph_only(workspace, args, language):
    """Build and display just the call graph."""
    try:
        from callgraph_engine import build_call_graph

        cg = build_call_graph(
            workspace=workspace,
            language=language,
            max_files=args.max_files,
            timeout_sec=float(args.timeout),
        )

        stats = cg.get_stats()

        # Build a readable representation
        functions_by_file = {}
        for qname, fdef in cg.functions.items():
            fp = fdef.file_path
            if fp not in functions_by_file:
                functions_by_file[fp] = []
            functions_by_file[fp].append({
                "name": fdef.short_name,
                "qualified_name": qname,
                "line": fdef.line,
                "params": fdef.params,
                "is_method": fdef.is_method,
                "class_name": fdef.class_name,
            })

        edges_by_caller = {}
        for edge in cg.edges:
            if edge.caller not in edges_by_caller:
                edges_by_caller[edge.caller] = []
            edges_by_caller[edge.caller].append({
                "callee": edge.callee,
                "file": edge.file_path,
                "line": edge.line,
                "type": edge.call_type,
                "confidence": edge.confidence,
            })

        # Import summary
        import_summary = {}
        for fp, imap in cg.import_map.items():
            import_summary[fp] = {
                "from_imports": len(imap.from_imports),
                "module_imports": len(imap.module_imports),
                "star_imports": len(imap.star_imports),
                "re_exports": len(imap.re_exports),
            }

        return {
            "status": "ok",
            "engine": "callgraph_engine",
            "call_graph": stats,
            "functions_by_file": functions_by_file,
            "edges_by_caller": edges_by_caller,
            "import_summary": import_summary,
            "unresolved_calls": [
                {
                    "caller": cs.caller_function,
                    "callee": cs.callee_name,
                    "file": cs.file_path,
                    "line": cs.line,
                    "type": cs.call_type,
                }
                for cs in cg.unresolved_calls[:50]  # Limit output
            ],
        }

    except ImportError as e:
        return {
            "status": "error",
            "message": f"Call graph engine unavailable: {e}",
        }


def _execute_legacy(workspace, args):
    """Execute using the original regex-based dataflow engine."""
    from dataflow_engine import trace_dataflow

    result = trace_dataflow(
        workspace,
        source=args.source,
        sink=args.sink,
        max_depth=args.depth,
        max_files=args.max_files,
        timeout_sec=float(args.timeout),
    )
    result["engine"] = "dataflow_regex"
    return result


def _generate_actionable_items(result):
    """Generate actionable items from analysis results."""
    items = []
    findings = result.get("findings", [])
    crit_high = [f for f in findings if f.get("severity") in ("critical", "high")]

    for f in crit_high[:10]:
        action = "FIX_IMMEDIATELY" if f.get("severity") == "critical" else "REVIEW_AND_FIX"
        items.append({
            "action": action,
            "rule": f.get("rule_id", ""),
            "file": f.get("file", ""),
            "line": f.get("line", 0),
            "message": f.get("message", ""),
            "taint_path": f.get("taint_path", ""),
            "cross_file": f.get("cross_file", False),
            "cross_file_source": f.get("cross_file_source", ""),
            "cross_file_sink": f.get("cross_file_sink", ""),
        })

    return items

# Issue #199: deprecated "dataflow" alias registration removed; this module is now an implementation module imported by the "impact" umbrella command.
