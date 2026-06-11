"""Context command — Get rich symbol context (code + callers + callees)."""

from context_engine import get_symbol_context
from complexity_engine import compute_complexity
from sideeffect_engine import analyze_side_effects
from smell_engine import detect_smells
from testmap_engine import map_test_coverage
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
    result = get_symbol_context(
        args.name, workspace,
        domain=args.domain,
        context_lines=args.context_lines,
        include_code=not args.no_code
    )
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
