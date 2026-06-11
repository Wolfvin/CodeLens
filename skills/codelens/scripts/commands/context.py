"""Context command — Get rich symbol context (code + callers + callees)."""

import os
from typing import Any, Dict, List

from context_engine import get_symbol_context
from complexity_engine import compute_complexity
from sideeffect_engine import analyze_side_effects
from smell_engine import detect_smells
from testmap_engine import map_test_coverage
from utils import is_file_path, deduplicate_callers, logger
from commands import register_command


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
    if is_file_path(symbol):
        from registry import load_backend_registry
        workspace_abs = os.path.abspath(workspace)
        backend = load_backend_registry(workspace_abs)
        # Try exact match first
        matching_nodes = [n for n in backend.get("nodes", []) if n.get("file", "") == symbol]

        # If no exact match, try substring/partial match
        if not matching_nodes:
            # Match by end-of-path (e.g., "layout.tsx" matches "apps/web/app/layout.tsx")
            matching_nodes = [n for n in backend.get("nodes", [])
                              if n.get("file", "").endswith(symbol)
                              or n.get("file", "").endswith('/' + symbol)]

        if matching_nodes:
            # Group by file if multiple files match
            file_groups = {}
            for node in matching_nodes:
                f = node.get("file", "")
                if f not in file_groups:
                    file_groups[f] = []
                file_groups[f].append({
                    "fn": node["fn"],
                    "line": node.get("line", 0),
                    "status": node.get("status", "active"),
                    "async": node.get("async", False),
                    "ref_count": node.get("ref_count", 0)
                })

            # If single file, return flat; if multiple, return grouped
            if len(file_groups) == 1:
                f, syms = list(file_groups.items())[0]
                return {
                    "status": "ok",
                    "found": True,
                    "context": {
                        "type": "file",
                        "file": f,
                        "symbols": syms
                    }
                }
            else:
                return {
                    "status": "ok",
                    "found": True,
                    "context": {
                        "type": "files",
                        "files": [{"file": f, "symbols": syms} for f, syms in file_groups.items()]
                    }
                }
        else:
            return {
                "status": "ok",
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
        result["context"]["callers"] = deduplicate_callers(result["context"].get("callers", []))

    # Enrich with quality metrics — skip on large codebases (>10K nodes) to prevent timeout
    _LARGE_CODEBASE_THRESHOLD = 10000
    is_large = False
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        is_large = len(backend.get("nodes", [])) > _LARGE_CODEBASE_THRESHOLD
    except Exception:
        pass

    if result.get("found") and result.get("context") and not is_large:
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
            logger.debug("Complexity analysis failed for %s", args.name, exc_info=True)

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
            logger.debug("Side-effect analysis failed for %s", args.name, exc_info=True)

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
            logger.debug("Smell detection failed for %s", args.name, exc_info=True)

        # Test coverage hint
        try:
            tc = map_test_coverage(workspace, function_name=args.name)
            if tc.get("status") == "ok":
                coverage = tc.get("coverage", {})
                quality["test_coverage"] = "covered" if coverage.get("has_tests") else "untested"
        except Exception:
            logger.debug("Test coverage check failed for %s", args.name, exc_info=True)

        if quality:
            result["context"]["quality"] = quality
    return result


register_command("context", "Get rich symbol context (code + callers + callees)", add_args, execute)
