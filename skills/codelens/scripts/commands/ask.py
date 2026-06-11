"""Ask command — Natural language query router."""

import os
import re
from typing import Dict, Any

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

    patterns = [
        # ─── Specific topic patterns (checked first) ───────────

        # Dead code (very specific — must come before "show me")
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

        # ─── Generic patterns (checked last) ────────────────────

        # Context / definition queries
        (["where is", "where's", "where does", "find definition", "find def", "what is", "what's"],
         "context", {"name": _extract_symbol_name}, "high"),

        # Symbol search
        (["search for", "find symbol", "find all", "look for"],
         "symbols", {"name": _extract_symbol_name}, "high"),

        # Trace
        (["how does", "trace", "call chain", "call path", "how is", "connected to", "flows to", "flow from"],
         "trace", {"name": _extract_symbol_name, "direction": "both"}, "medium"),

        # Show me
        (["show me"],
         "context", {"name": _extract_symbol_name}, "low"),

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


register_command("ask", "Ask a question in natural language", add_args, execute)
