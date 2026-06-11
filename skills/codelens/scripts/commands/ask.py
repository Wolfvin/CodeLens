"""Ask command — Natural language query router with score-based matching."""

import os
import re
from typing import Dict, Any, List, Tuple

from context_engine import get_symbol_context
from search_engine import search_symbols
from deadcode_engine import detect_dead_code
from secrets_engine import detect_secrets
from circular_engine import detect_circular
from apimap_engine import map_api_routes
from entrypoints_engine import map_entrypoints
from smell_engine import detect_smells
from complexity_engine import compute_complexity
from impact_engine import analyze_impact
from trace_engine import trace_symbol
from testmap_engine import map_test_coverage
from perfhint_engine import detect_perf_hints
from vulnscan_engine import scan_vulnerabilities
from outline_engine import get_workspace_outline
from envcheck_engine import check_env_vars
from debugleak_engine import detect_debug_leaks
from statemap_engine import map_state
from dependents_engine import get_dependency_graph
from commands import register_command
from commands.scan import cmd_scan
from commands.handbook import cmd_handbook

# ─── Keyword Weight Definitions ──────────────────────────────────
# Technical/specific terms get weight 3, action words get weight 1,
# generic filler words get weight 0.

_KEYWORD_WEIGHTS: Dict[str, int] = {
    # Technical terms (weight 3) — high specificity
    "api route": 3, "api routes": 3, "endpoint": 3, "endpoints": 3,
    "api map": 3, "rest route": 3, "http route": 3, "graphql": 3,
    "circular": 3, "circular dependency": 3, "circular dep": 3, "dependency cycle": 3,
    "dead code": 3, "unused code": 3, "unreachable": 3, "zombie": 3,
    "orphan": 3, "never called": 3,
    "secret": 3, "api key": 3, "password": 3, "token leak": 3,
    "cve": 3, "vuln": 3, "vulnerability": 3, "vulnerable": 3,
    "security hole": 3,
    "code smell": 3, "technical debt": 3,
    "complexity": 3, "cyclomatic": 3, "cognitive complexity": 3,
    "test coverage": 3, "untested": 3, "missing test": 3, "test map": 3,
    "performance": 3, "n+1": 3, "memory leak": 3, "bottleneck": 3,
    "entry point": 3, "entrypoint": 3,
    "env var": 3, "environment variable": 3, ".env": 3, "missing env": 3,
    "console.log": 3, "debugger": 3, "debug code": 3,
    "zustand": 3, "redux": 3, "pinia": 3, "global state": 3,
    "side effect": 3, "pure function": 3, "impure": 3, "side-effect": 3,
    "refactor": 3, "safe to rename": 3, "safe to move": 3,
    "dependents": 3, "import graph": 3, "dependency graph": 3,
    "css issue": 3, "css problem": 3, "css audit": 3,
    "accessibility": 3, "a11y": 3, "aria": 3,
    "regex": 3, "redo": 3, "redos": 3,
    "what changed": 3, "diff": 3, "changes": 3,
    "tech stack": 3, "frameworks": 3, "detect framework": 3,
    "how to configure": 3, "configuration": 3,
    "not used": 3,
    "binary": 3, "exe": 3, "executable": 3, "sidecar": 3,
    "reverse engineer": 3, "tauri command": 3, "ipc command": 3,
    "capabilities": 3, "permissions audit": 3, "webview security": 3,
    "csp": 3, "asset protocol": 3, "deep link": 3,

    # Action words (weight 1) — lower specificity
    "show me": 1, "find": 1, "search for": 1, "look for": 1,
    "trace": 1, "scan": 1, "analyze": 1, "index": 1,
    "where is": 1, "where's": 1, "where does": 1,
    "what is": 1, "what's": 1, "how does": 1, "how is": 1,
    "who imports": 1, "who uses": 1, "who depends": 1,
    "find definition": 1, "find def": 1, "find all": 1, "find symbol": 1,

    # Generic words (weight 0) — ignored for scoring
    "the": 0, "a": 0, "an": 0, "me": 0, "my": 0,
    "this": 0, "that": 0, "it": 0, "is": 0, "are": 0,
    "of": 0, "for": 0, "in": 0, "on": 0, "to": 0,
}

# Default weight for keywords not in the table
_DEFAULT_KEYWORD_WEIGHT = 2


def _get_keyword_weight(kw: str) -> int:
    """Get the weight for a keyword based on specificity."""
    return _KEYWORD_WEIGHTS.get(kw, _DEFAULT_KEYWORD_WEIGHT)


def add_args(parser):
    parser.add_argument("question", help="Natural language question about the codebase")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return cmd_ask(args.question, workspace)


def cmd_ask(question: str, workspace: str) -> Dict[str, Any]:
    """
    Natural language query router.
    Maps a question to the appropriate CodeLens command and returns its result.
    Uses score-based matching to find the best command.
    """
    workspace = os.path.abspath(workspace)
    q = question.lower().strip()

    # Determine which command to run based on score-based matching
    command, args = _parse_ask_question(q, workspace)

    if command is None:
        return {
            "status": "unknown_query",
            "question": question,
            "workspace": workspace,
            "suggestion": "Could not determine the appropriate command. Try: scan, context, trace, impact, smell, dead-code, secrets, circular, api-map, entrypoints, outline, query, complexity, test-map, perf-hint, vuln-scan, dependents, refactor-safe, css-deep, a11y, regex-audit, diff, detect, env-check"
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

    # Fallback: if context returned not_found, try symbol search instead
    if (command == "context" and isinstance(result, dict)
            and result.get("status") == "not_found"):
        symbol = args.get("name", "")
        if symbol:
            search_result = search_symbols(workspace, symbol, domain="all", fuzzy=True)
            if search_result.get("results"):
                search_result["query_interpretation"] = {
                    "question": question,
                    "interpreted_as": "search (fallback from context)",
                    "confidence": "low"
                }
                return search_result

    return result


def _parse_ask_question(q: str, workspace: str) -> tuple:
    """
    Parse a natural language question using score-based matching.

    Instead of first-match, each pattern is scored based on:
    1. Keyword weight (specific technical terms = 3, action words = 1, generic = 0)
    2. Number of keywords matched from the pattern
    3. Coverage bonus for matching multiple keywords from same pattern

    The highest-scoring pattern wins, which correctly routes queries like
    "show me the API routes" to api-map (score from "api route" = 3*2*1.5 = 9)
    instead of context (score from "show me" = 1*1*1.0 = 1).
    """

    patterns = [
        # ─── Specific topic patterns ───────────

        # Dead code
        (["dead code", "unused code", "unreachable", "zombie", "not used", "never called", "orphan"],
         "dead-code", {}, "high"),

        # API routes
        (["api route", "api routes", "endpoint", "endpoints", "api map", "rest route", "http route", "graphql"],
         "api-map", {}, "high"),

        # Circular dependencies
        (["circular", "cycle", "circular dependency", "circular dep", "dependency cycle"],
         "circular", {}, "high"),

        # Entrypoints
        (["entry point", "entrypoint", "main function", "where does it start", "how does it start", "boot"],
         "entrypoints", {}, "high"),

        # Security
        (["security", "secret", "api key", "password", "token leak", "cve", "vuln"],
         "secrets", {}, "high"),

        # Vulnerabilities
        (["vulnerability", "vulnerable", "security hole"],
         "vuln-scan", {}, "high"),

        # Smells / health
        (["code smell", "smell", "health", "code quality", "code health", "technical debt"],
         "smell", {}, "high"),

        # Complexity
        (["complexity", "complex", "complicated", "cyclomatic", "cognitive complexity"],
         "complexity", {}, "high"),

        # Test coverage
        (["test coverage", "tested", "untested", "missing test", "test map"],
         "test-map", {}, "high"),

        # Performance
        (["performance", "slow", "perf", "n+1", "memory leak", "bottleneck"],
         "perf-hint", {}, "high"),

        # Impact analysis
        (["what happens if", "impact of", "what if i change", "what if i delete", "can i change", "can i delete", "safe to"],
         "impact", {"name": _extract_symbol_name, "action": "modify"}, "medium"),

        # Outline
        (["outline", "structure", "file structure", "what's in", "contents of"],
         "outline", {}, "medium"),

        # Environment check
        (["env var", "environment variable", ".env", "missing env", "env check"],
         "env-check", {}, "high"),

        # Debug leak
        (["debug code", "console.log", "debugger", "todo", "fixme", "leftover"],
         "debug-leak", {}, "high"),

        # State management
        (["state", "store", "zustand", "redux", "pinia", "global state"],
         "state-map", {}, "high"),

        # Side effects
        (["side effect", "pure function", "impure", "mutation", "side-effect"],
         "side-effect", {"name": _extract_symbol_name}, "high"),

        # Refactor safety
        (["refactor", "rename", "move", "safe to rename", "safe to move"],
         "refactor-safe", {"name": _extract_symbol_name}, "medium"),

        # ─── Newly added patterns ───────────

        # Dependents / import tracking
        (["dependents", "who imports", "who uses", "who depends", "import graph", "dependency graph",
          "which files import"],
         "dependents", {}, "medium"),

        # Refactor safety (broader)
        (["is this code safe", "safe to change", "safe to remove", "is it safe"],
         "refactor-safe", {"name": _extract_symbol_name}, "medium"),

        # CSS deep analysis
        (["css issue", "css problem", "css audit", "css analysis", "css deep",
          "css variable", "keyframe", "specificity", "z-index"],
         "css-deep", {}, "high"),

        # Accessibility
        (["accessibility", "a11y", "aria", "wcag", "screen reader", "alt text",
          "keyboard nav", "focus", "accessible"],
         "a11y", {}, "high"),

        # Regex audit
        (["regex", "regexp", "regular expression", "redo", "redos", "regex audit",
          "catastrophic backtracking", "regex vulnerabilities", "regex vulnerability",
          "regex issue", "regex problem"],
         "regex-audit", {}, "high"),

        # Diff / changes
        (["what changed", "diff", "changes since", "what's different", "compare"],
         "diff", {}, "high"),

        # Detect / tech stack
        (["tech stack", "frameworks", "detect framework", "what framework", "what libraries",
          "what technologies", "stack"],
         "detect", {}, "high"),

        # Binary scan / reverse engineering
        (["binary", "exe", "executable", "sidecar", "reverse engineer", "tauri command",
          "tauri commands", "ipc command", "capabilities", "permissions audit",
          "webview security", "csp", "asset protocol", "updater", "deep link",
          "build binary", "binary scan", "tauri ipc", "electron binary"],
         "binary-scan", {}, "high"),

        # Env configuration
        (["how to configure", "configuration", "config check", "env setup"],
         "env-check", {}, "high"),

        # ─── Generic patterns (scored lower by keyword weight) ────

        # Context / definition queries
        (["where is", "where's", "where does", "find definition", "find def", "what is", "what's"],
         "context", {"name": _extract_symbol_name}, "high"),

        # Symbol search
        (["search for", "find symbol", "find all", "look for"],
         "symbols", {"name": _extract_symbol_name}, "high"),

        # Trace
        (["how does", "trace", "call chain", "call path", "how is", "connected to", "flows to", "flow from"],
         "trace", {"name": _extract_symbol_name, "direction": "both"}, "medium"),

        # Show me (generic — low weight keywords)
        (["show me"],
         "context", {"name": _extract_symbol_name}, "low"),

        # Scan
        (["scan", "analyze", "index", "build registry", "full analysis"],
         "scan", {}, "high"),

        # Handbook
        (["overview", "handbook", "project brief", "tell me about", "summarize", "summary of"],
         "handbook", {}, "high"),
    ]

    # ─── Score each pattern ────────────────────────────────
    candidates: List[Tuple[float, str, dict, str]] = []

    for keywords, command, extra_args, confidence in patterns:
        score = 0.0
        matched_keywords = 0

        for kw in keywords:
            if kw in q:
                weight = _get_keyword_weight(kw)
                # Multi-word keywords are more specific: "api route" > "api"
                word_bonus = len(kw.split())
                score += weight * word_bonus
                matched_keywords += 1

        if matched_keywords > 0:
            # Coverage bonus: matching more keywords from same pattern is better
            coverage = matched_keywords / len(keywords)
            score *= (1 + coverage)
            candidates.append((score, command, extra_args, confidence))

    if not candidates:
        # Fallback: try to find a symbol name and use context
        symbol = _extract_symbol_name(q, "")
        if symbol:
            return "context", {"name": symbol, "_confidence": "low"}
        return None, {}

    # Sort by score descending, return best match
    candidates.sort(key=lambda x: x[0], reverse=True)
    best_score, command, extra_args, confidence = candidates[0]

    # Adjust confidence based on score margin
    if len(candidates) > 1 and candidates[0][0] <= candidates[1][0] * 1.2:
        # Close match — lower confidence
        if confidence == "high":
            confidence = "medium"

    # Build args dict
    resolved_args = {"_confidence": confidence, "_score": best_score}
    for key, val in extra_args.items():
        if callable(val):
            resolved_args[key] = val(q, "")
        else:
            resolved_args[key] = val

    return command, resolved_args


def _extract_symbol_name(q: str, keyword: str) -> str:
    """Try to extract a symbol name from the question."""
    # Remove common question words
    cleaned = q
    for prefix in ["where is ", "where's ", "where does ", "what is ", "what's ",
                    "show me ", "find definition of ", "find def ", "find ",
                    "search for ", "how does ", "how is ", "trace ", "impact of ",
                    "what happens if i change ", "what happens if i delete ",
                    "can i change ", "can i delete ", "is this code safe ",
                    "is it safe ", "safe to change ", "safe to remove ",
                    "which files import "]:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break

    # Remove trailing question marks and whitespace
    cleaned = cleaned.rstrip("?!. ").strip()

    # Remove common English filler words and type keywords
    for filler in ["the ", "a ", "an ", "this ", "that ", "these ", "those ",
                   "function ", "class ", "method ", "variable ", "const ",
                   "module ", "file ", "component ", "hook ", "type ",
                   "interface ", "enum "]:
        cleaned = re.sub(r'^' + re.escape(filler), '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(re.escape(filler.rstrip()) + r'$', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # Try to extract code-like identifiers
    match = re.search(r'`([^`]+)`', q)
    if match:
        return match.group(1).strip()

    # Look for quoted names
    match = re.search(r'["\']([^"\']+)["\']', q)
    if match:
        return match.group(1).strip()

    # Look for identifier-like patterns
    match = re.search(r'[a-z][a-zA-Z0-9]*_[a-zA-Z0-9_]+', cleaned)
    if match:
        return match.group(0)
    match = re.search(r'[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*', cleaned)
    if match:
        return match.group(0)
    match = re.search(r'[A-Z][a-zA-Z0-9]*(?:[A-Z][a-zA-Z0-9]*)+', cleaned)
    if match:
        return match.group(0)

    # Fallback: any identifier
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
        return compute_complexity(workspace, sort_by="complexity", limit=30)
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
    elif command == "css-deep":
        from cssdeep_engine import analyze_css_deep
        return analyze_css_deep(workspace)
    elif command == "a11y":
        from a11y_engine import audit_accessibility
        return audit_accessibility(workspace)
    elif command == "regex-audit":
        from regexaudit_engine import audit_regex_patterns
        return audit_regex_patterns(workspace)
    elif command == "diff":
        from diff_engine import diff_current_vs_last
        return diff_current_vs_last(workspace)
    elif command == "detect":
        from framework_detect import detect_frameworks
        return detect_frameworks(workspace)
    elif command == "refactor-safe":
        from refactor_safe_engine import check_refactor_safety
        return check_refactor_safety(args.get("name", ""), workspace)
    elif command == "side-effect":
        from sideeffect_engine import analyze_side_effects
        return analyze_side_effects(workspace, function_name=args.get("name", ""))
    elif command == "dataflow":
        from dataflow_engine import analyze_dataflow
        return analyze_dataflow(workspace)
    elif command == "missing-refs":
        from missing_refs import detect_missing_refs
        return detect_missing_refs(workspace)
    elif command == "ownership":
        from ownership_engine import analyze_ownership
        return analyze_ownership(workspace)
    elif command == "config-drift":
        from configdrift_engine import detect_config_drift
        return detect_config_drift(workspace)
    elif command == "stack-trace":
        from stacktrace_engine import simulate_error_propagation
        return simulate_error_propagation(args.get("name", ""), workspace)
    elif command == "type-infer":
        from typeinfer_engine import infer_types
        return infer_types(workspace)
    elif command == "binary-scan":
        from utils import scan_binary_artifacts, scan_tauri_artifacts
        result = scan_binary_artifacts(workspace)
        tauri_result = scan_tauri_artifacts(workspace)
        if tauri_result:
            result["tauri_analysis"] = tauri_result
        return result
    else:
        return {"status": "error", "message": f"Unknown command: {command}"}


register_command("ask", "Ask a question in natural language", add_args, execute)
