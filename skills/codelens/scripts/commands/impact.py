"""Impact command — Analyze change impact for a symbol."""

from impact_engine import analyze_impact
from commands import register_command


def add_args(parser):
    parser.add_argument("name", help="Symbol name to analyze")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--action", choices=["modify", "delete"], default="modify",
                        help="Planned action (modify or delete)")
    parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                        help="Domain to analyze")
    parser.add_argument("--depth", type=int, default=5, help="Trace depth (default 5)")


def execute(args, workspace):
    result = analyze_impact(
        args.name, workspace,
        action=args.action,
        domain=args.domain,
        depth=args.depth
    )
    # Add decision tree fields
    if result.get("status") == "ok":
        affected = result.get("affected", {})
        # Count actual items: direct + indirect dependents, not dict keys
        if isinstance(affected, dict):
            affected_count = len(affected.get("direct", [])) + len(affected.get("indirect", []))
        elif isinstance(affected, list):
            affected_count = len(affected)
        else:
            affected_count = 0
        if affected_count == 0:
            result["risk_level"] = "low"
            result["recommended_action"] = "Safe to proceed. No dependent code found."
        elif affected_count <= 3:
            result["risk_level"] = "medium"
            result["recommended_action"] = "Proceed with caution. Review affected code before changing."
        elif affected_count <= 10:
            result["risk_level"] = "high"
            result["recommended_action"] = "High risk. Thoroughly test all affected code after changes."
        else:
            result["risk_level"] = "critical"
            result["recommended_action"] = "Critical risk. Consider refactoring to reduce dependencies first."
    return result


register_command("impact", "Analyze change impact for a symbol", add_args, execute)
