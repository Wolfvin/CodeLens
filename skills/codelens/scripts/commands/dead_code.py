"""Dead-code command — Enhanced dead code detection."""

from deadcode_engine import detect_dead_code
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="Categories: unreachable, unused_exports, zombie_css, unused_vars, dead_listeners")


def execute(args, workspace):
    result = detect_dead_code(
        workspace,
        categories=args.categories
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
    return result


register_command("dead-code", "Enhanced dead code detection", add_args, execute)
