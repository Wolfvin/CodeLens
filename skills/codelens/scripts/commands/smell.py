"""Smell command — Detect code smells across workspace."""

from smell_engine import detect_smells
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="Categories: long_fn, deep_nesting, many_params, large_file, callback_hell, magic_values, god_object, complex_conditional, duplicate_pattern, inconsistent")
    parser.add_argument("--severity", choices=["info", "warning", "critical"], default=None,
                        help="Filter by severity level")


def execute(args, workspace):
    result = detect_smells(
        workspace,
        categories=args.categories,
        severity_filter=args.severity
    )
    # Add actionable priority list
    if result.get("status") == "ok":
        top = result.get("top_priority", [])
        actionable = []
        for item in top[:10]:
            severity = item.get("severity", "info")
            if severity == "critical":
                action = "FIX_IMMEDIATELY"
            elif severity == "warning":
                action = "PLAN_FIX"
            else:
                action = "CONSIDER"
            actionable.append({
                "action": action,
                "category": item.get("category", ""),
                "file": item.get("file", ""),
                "line": item.get("line", 0),
                "message": item.get("message", ""),
                "suggestion": item.get("suggestion", "")
            })
        result["actionable_items"] = actionable
    return result


register_command("smell", "Detect code smells across workspace", add_args, execute)
