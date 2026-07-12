"""Dead-code command — Enhanced dead code detection."""

from deadcode_engine import detect_dead_code
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="Categories: unreachable, unused_exports, zombie_css, unused_vars, dead_listeners")
    parser.add_argument("--max-files", type=int, default=3000,
                        help="Max files to scan (default: 3000)")
    parser.add_argument("--max-results", type=int, default=100,
                        help="Max results per category (default: 100)")
    parser.add_argument("--no-verify-impact", dest="verify_impact",
                        action="store_false", default=True,
                        help="Skip per-finding deletion_safety cross-check against "
                             "impact analysis (issue #238). On by default; disable "
                             "on very large result sets if it's too slow.")
    parser.add_argument("--verify-impact-limit", type=int, default=20,
                        help="Max number of findings to cross-check with impact "
                             "analysis per run (default: 20, highest-confidence "
                             "findings first)")


def execute(args, workspace):
    result = detect_dead_code(
        workspace,
        categories=args.categories,
        max_files=args.max_files,
        max_results=args.max_results
    )
    # Add removal safety assessment
    if result.get("status") == "ok":
        total_dead = result.get("stats", {}).get("total_dead_code", 0)
        # If the engine already computed removal_safety, use it
        # Otherwise compute from the results
        if "removal_safety" not in result:
            if total_dead == 0:
                result["removal_safety"] = "n/a"
                result["dependency_count"] = 0
            else:
                # Count items with references (riskier to remove)
                all_items = []
                for category_items in result.get("results", {}).values():
                    all_items.extend(category_items)
                with_refs = sum(1 for item in all_items if item.get("ref_count", 0) > 0)
                if with_refs == 0:
                    result["removal_safety"] = "safe"
                elif with_refs < total_dead * 0.3:
                    result["removal_safety"] = "mostly_safe"
                else:
                    result["removal_safety"] = "caution"
                result["dependency_count"] = with_refs
                result["recommended_action"] = "Review before removing. Some dead code may still be referenced indirectly." if with_refs > 0 else "Safe to remove. No references found."

        # Attach baseline confidence (medium = AST-based analysis per hybrid_engine.py
        # docstring) to each finding and add confidence_distribution to stats.
        # HybridEngine.verify_dead_code sets confidence=MEDIUM on every finding when
        # LSP is not active (deep=False).  add_confidence_to_result backfills any
        # remaining findings and computes the distribution.  When --deep is later
        # applied in codelens.py post-processing, LSP verification may override
        # individual findings to HIGH or LOW.
        try:
            from hybrid_engine import create_hybrid_engine, add_confidence_to_result
            engine = create_hybrid_engine(workspace, deep=False)
            all_findings = []
            for cat_items in result.get("results", {}).values():
                if isinstance(cat_items, list):
                    all_findings.extend(cat_items)
            if all_findings:
                engine.verify_dead_code(all_findings)
            add_confidence_to_result(result)
            engine.cleanup()
        except Exception:
            # Best-effort fallback: manually attach medium confidence + distribution
            all_findings = []
            for cat_items in result.get("results", {}).values():
                if isinstance(cat_items, list):
                    all_findings.extend(cat_items)
            for f in all_findings:
                if isinstance(f, dict) and "confidence" not in f:
                    f["confidence"] = "medium"
            if all_findings:
                dist = {"high": 0, "medium": 0, "low": 0}
                for f in all_findings:
                    c = f.get("confidence", "medium") if isinstance(f, dict) else "medium"
                    if c in dist:
                        dist[c] += 1
                if "stats" not in result:
                    result["stats"] = {}
                result["stats"]["confidence_distribution"] = dist

        # Issue #238: per-finding deletion_safety cross-check.
        #
        # "status: dead" in the registry only means "no CALLS edge found" — it
        # does NOT mean safe to delete (entry points like HTTP handlers, CLI
        # subcommands, and exported APIs routinely have zero inbound edges but
        # are still critical). Previously an agent had to manually chain
        # `audit --check dead-code` -> `context --check trace --direction up`
        # to verify this per finding; analyze_impact() already computes exactly
        # this signal for the "delete" action, it just wasn't wired in here.
        if getattr(args, "verify_impact", True):
            try:
                from impact_engine import analyze_impact
                all_items = []
                for cat_items in result.get("results", {}).values():
                    if isinstance(cat_items, list):
                        all_items.extend(cat_items)
                limit = max(0, getattr(args, "verify_impact_limit", 20) or 0)
                _risk_to_safety = {
                    "low": "safe",
                    "medium": "caution",
                    "high": "entry_point_likely",
                    "critical": "entry_point_likely",
                }
                for item in all_items[:limit]:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name")
                    if not name:
                        continue
                    try:
                        impact_result = analyze_impact(
                            name, workspace, action="delete", depth=3
                        )
                        risk = impact_result.get("risk", "low")
                        item["deletion_safety"] = _risk_to_safety.get(risk, "caution")
                        item["deletion_impact_stats"] = impact_result.get("stats")
                    except Exception:
                        item["deletion_safety"] = "unknown"
            except ImportError:
                pass
    return result

# Issue #199: deprecated "dead-code" alias registration removed; this module is now an implementation module imported by the "audit" umbrella command.
