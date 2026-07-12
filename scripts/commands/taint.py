"""Taint command — Run AST-based or semantic taint analysis for vulnerability detection.

By default, uses the new AST-based taint engine (ast_taint_engine.py) with tree-sitter
when available, falling back to the regex-based semantic_engine.py.
Use --no-ast to force regex-based analysis.
Use --cross-file for cross-file taint analysis with CFG construction.
"""

from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--language", choices=["python", "javascript", "typescript", "rust"], default=None,
                        help="Filter analysis to a specific language. 'rust' runs only the "
                             "#[tauri::command] parameter-to-sink MVP scanner (issue #240) — "
                             "see docs/design/0240-tauri-command-param-taint.md for its scope.")
    parser.add_argument("--with-secrets", action="store_true", default=False,
                        help="Include secrets engine findings as taint sources")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by minimum severity")
    parser.add_argument("--cross-file", action="store_true", default=False,
                        help="Enable cross-file taint analysis with CFG construction")
    parser.add_argument("--no-ast", action="store_true", default=False,
                        help="Disable AST-based engine and use regex-based analysis instead")
    parser.add_argument("--ast", action="store_true", default=False,
                        help="Explicitly request AST-based engine (default when tree-sitter available)")


def execute(args, workspace):
    language = getattr(args, 'language', None)
    cross_file = getattr(args, 'cross_file', False)
    no_ast = getattr(args, 'no_ast', False)
    use_ast = getattr(args, 'ast', False)

    # Issue #240 MVP: --language rust runs ONLY the Rust
    # #[tauri::command]-parameter scanner — ast_taint_engine's
    # get_supported_languages() doesn't include Rust at all, so routing
    # "rust" through it would either error or silently match nothing.
    # See docs/design/0240-tauri-command-param-taint.md for scope.
    if language == "rust":
        from rust_command_taint import scan_workspace as scan_rust_taint
        findings = scan_rust_taint(workspace)
        result = {
            "status": "ok",
            "engine": "rust_command_taint",
            "languages_analyzed": ["rust"],
            "findings": findings,
            "total_findings": len(findings),
        }
        if getattr(args, 'severity', None):
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            min_sev = severity_order.get(args.severity, 3)
            result["findings"] = [f for f in result["findings"]
                                  if severity_order.get(f.get("severity", "low"), 3) <= min_sev]
            result["total_findings"] = len(result["findings"])
        return result

    # Issue #49 Phase 1: unified entry point through ast_taint_engine.
    # The AST engine now handles both intra-file (default) and cross-file
    # (--cross-file flag) modes. The old crossfile_taint_engine and
    # semantic_engine are still available as fallbacks but are deprecated.
    #
    # Engine selection:
    #   --no-ast            -> semantic_engine (regex, deprecated)
    #   --cross-file        -> ast_taint_engine with cross_file=True
    #   default             -> ast_taint_engine (intra-file)
    if no_ast:
        # Explicit regex fallback (deprecated path)
        from semantic_engine import analyze_workspace
        result = analyze_workspace(workspace, language=language)
        result["engine"] = "semantic_regex"
        result["cross_file"] = False
    else:
        try:
            from ast_taint_engine import is_available, analyze_workspace as ast_analyze_workspace
            if is_available():
                result = ast_analyze_workspace(
                    workspace, language=language, cross_file=cross_file
                )
            else:
                # tree-sitter not installed — fall back to semantic_engine
                from semantic_engine import analyze_workspace
                result = analyze_workspace(workspace, language=language)
                result["engine"] = "semantic_regex"
                result["cross_file"] = False
                result["cross_file_fallback"] = cross_file
        except ImportError:
            # ast_taint_engine module unavailable — fall back to semantic_engine
            from semantic_engine import analyze_workspace
            result = analyze_workspace(workspace, language=language)
            result["engine"] = "semantic_regex"
            result["cross_file"] = False
            result["cross_file_fallback"] = cross_file

    # Issue #240 MVP: on a default (no --language filter) scan, also merge
    # in Rust #[tauri::command] parameter-to-sink findings. Only makes
    # sense when the caller didn't restrict to a specific non-Rust
    # language — --language rust itself is handled by the early return
    # above, and --language python/javascript/typescript means the caller
    # wants just that language.
    if language is None and result.get("status") == "ok":
        try:
            from rust_command_taint import scan_workspace as scan_rust_taint
            rust_findings = scan_rust_taint(workspace)
            if rust_findings:
                result.setdefault("findings", []).extend(rust_findings)
                result["total_findings"] = len(result["findings"])
                langs = result.setdefault("languages_analyzed", [])
                if "rust" not in langs:
                    langs.append("rust")
        except Exception:
            pass

    # Optionally enhance with secrets findings
    if getattr(args, 'with_secrets', False):
        try:
            from secrets_engine import scan_secrets
            sr = scan_secrets(workspace)
            if sr.get("status") == "ok" and sr.get("findings"):
                # Add secrets as taint sources
                for finding in sr["findings"][:10]:
                    result["findings"].append({
                        "rule_id": "secret-leak",
                        "rule_name": "Secret in Source Code",
                        "severity": finding.get("severity", "high"),
                        "cwe": "CWE-798",
                        "message": f"Hardcoded {finding.get('type', 'secret')} found — may be logged or exposed",
                        "file": finding.get("file", ""),
                        "line": finding.get("line", 0),
                        "source": finding.get("type", "secret"),
                        "sink": "source_code",
                        "tainted_variable": finding.get("name", "unknown"),
                        "sanitized": False,
                        "confidence": "high",
                        "taint_path": f"secret({finding.get('type', '')}) → source_code",
                    })
                result["total_findings"] = len(result["findings"])
        except Exception:
            pass

    # Filter by severity
    if getattr(args, 'severity', None) and result.get("status") == "ok":
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        min_sev = severity_order.get(args.severity, 3)
        result["findings"] = [f for f in result.get("findings", [])
                              if severity_order.get(f.get("severity", "low"), 3) <= min_sev]
        result["total_findings"] = len(result["findings"])

    # Add actionable items for --format ai
    if result.get("status") == "ok":
        crit = [f for f in result.get("findings", []) if f.get("severity") == "critical"]
        high = [f for f in result.get("findings", []) if f.get("severity") == "high"]
        result["actionable_items"] = []
        for f in crit[:5]:
            result["actionable_items"].append({
                "action": "FIX_IMMEDIATELY",
                "rule": f.get("rule_id", ""),
                "file": f.get("file", ""),
                "line": f.get("line", 0),
                "message": f.get("message", ""),
                "taint_path": f.get("taint_path", ""),
            })
        for f in high[:5]:
            result["actionable_items"].append({
                "action": "REVIEW_AND_FIX",
                "rule": f.get("rule_id", ""),
                "file": f.get("file", ""),
                "line": f.get("line", 0),
                "message": f.get("message", ""),
                "taint_path": f.get("taint_path", ""),
            })

    return result

# Issue #199: deprecated "taint" alias registration removed; this module is now an implementation module imported by the "security" umbrella command.
