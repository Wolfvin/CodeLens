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
    # Add decision tree fields — derive risk_level from the engine's risk assessment
    # to avoid contradictory "risk" vs "risk_level" values
    if result.get("status") == "ok":
        engine_risk = result.get("risk", "low")
        stats = result.get("stats", {})
        direct_dependents = stats.get("direct_dependents", 0)
        indirect_dependents = stats.get("indirect_dependents", 0)
        affected_files = stats.get("affected_files", 0)

        # Use the engine's risk as the authoritative risk_level
        result["risk_level"] = engine_risk

        # Set recommended_action consistent with risk_level
        if engine_risk == "critical":
            result["recommended_action"] = "Critical risk. Consider refactoring to reduce dependencies first."
        elif engine_risk == "high":
            result["recommended_action"] = "High risk. Thoroughly test all affected code after changes."
        elif engine_risk == "medium":
            result["recommended_action"] = "Proceed with caution. Review affected code before changing."
        else:
            result["recommended_action"] = "Safe to proceed. No dependent code found."

        # Attach baseline confidence (medium = AST-based analysis per hybrid_engine.py
        # docstring).  HybridEngine.enhance_impact sets confidence=MEDIUM when LSP is
        # not active (deep=False).  When --deep is later applied in codelens.py
        # post-processing, LSP verification may override this to HIGH or LOW.
        try:
            from hybrid_engine import create_hybrid_engine
            engine = create_hybrid_engine(workspace, deep=False)
            engine.enhance_impact(result, args.name)
            engine.cleanup()
        except Exception:
            result.setdefault("confidence", "medium")
    return result


register_command("impact", "Analyze change impact for a symbol", add_args, execute)
