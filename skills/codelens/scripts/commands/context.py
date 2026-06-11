"""Context command — Get rich symbol context (code + callers + callees)."""

import os
from typing import Any, Dict, List

from context_engine import get_symbol_context
from complexity_engine import compute_complexity
from sideeffect_engine import analyze_side_effects
from smell_engine import detect_smells
from testmap_engine import map_test_coverage
from commands import register_command


# Known file extensions used to detect file path queries
_FILE_PATH_EXTENSIONS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.css', '.html', '.rs', '.vue', '.svelte'}


def _is_file_path(name: str) -> bool:
    """Check if a name looks like a file path."""
    if '/' in name:
        return True
    for ext in _FILE_PATH_EXTENSIONS:
        if name.endswith(ext):
            return True
    return False


def _deduplicate_callers(callers: List[Dict]) -> List[Dict]:
    """Deduplicate callers by (file, line) tuple."""
    seen = set()
    unique = []
    for c in callers:
        key = (c.get("file", ""), c.get("line", 0))
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def add_args(parser):
    parser.add_argument("name", help="Symbol name")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                        help="Domain")
    parser.add_argument("--context-lines", type=int, default=5,
                        help="Lines of code context around symbol (default 5)")
    parser.add_argument("--no-code", action="store_true", help="Skip source code in output")


def execute(args, workspace):
    symbol = args.name

    # ─── File path lookup ─────────────────────────────
    if _is_file_path(symbol):
        from registry import load_backend_registry
        workspace_abs = os.path.abspath(workspace)
        backend = load_backend_registry(workspace_abs)
        matching_nodes = [n for n in backend.get("nodes", []) if n.get("file", "") == symbol]

        if matching_nodes:
            symbols = []
            for node in matching_nodes:
                symbols.append({
                    "fn": node["fn"],
                    "line": node.get("line", 0),
                    "status": node.get("status", "active"),
                    "async": node.get("async", False),
                    "ref_count": node.get("ref_count", 0)
                })
            return {
                "found": True,
                "context": {
                    "type": "file",
                    "file": symbol,
                    "symbols": symbols
                }
            }
        else:
            return {
                "found": False,
                "symbol": symbol,
                "context": None
            }

    # ─── Normal symbol lookup ──────────────────────────
    result = get_symbol_context(
        args.name, workspace,
        domain=args.domain,
        context_lines=args.context_lines,
        include_code=not args.no_code
    )

    # Deduplicate callers
    if result.get("found") and result.get("context"):
        result["context"]["callers"] = _deduplicate_callers(result["context"].get("callers", []))

    # Enrich with quality metrics
    if result.get("found") and result.get("context"):
        quality = {}
        try:
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
            smells = detect_smells(workspace)
            for s in smells.get("top_priority", []):
                fn_name = s.get("fn", "")
                if fn_name == args.name:
                    quality.setdefault("smells", []).append(s.get("category", ""))
        except Exception:
            pass

        # Test coverage hint
        try:
            tc = map_test_coverage(workspace, function_name=args.name)
            if tc.get("status") == "ok":
                coverage = tc.get("coverage", {})
                quality["test_coverage"] = "covered" if coverage.get("has_tests") else "untested"
        except Exception:
            pass

        if quality:
            result["context"]["quality"] = quality
    return result


register_command("context", "Get rich symbol context (code + callers + callees)", add_args, execute)
