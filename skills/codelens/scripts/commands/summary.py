"""Summary command — Auto-summary with prioritized, condensed output.

The primary "anti-overload" command for AI agents. Instead of running
multiple commands and getting flooded with data, this single command:

1. Auto-detects what matters most in the codebase
2. Prioritizes findings by severity and impact
3. Returns a condensed summary with actionable items only
4. Adapts detail level to codebase size (more detail for small, less for large)

This prevents the common pattern where agents run 10+ commands and get
overwhelmed with thousands of findings, most of which are low-priority.
"""

import os
from typing import Dict, Any, List
from commands import register_command
from utils import logger


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--focus", choices=["security", "quality", "architecture", "all"],
                        default="all",
                        help="Focus area for the summary (default: all)")
    parser.add_argument("--max-items", type=int, default=10,
                        help="Maximum items per category (default: 10)")
    parser.add_argument("--detail", choices=["minimal", "standard", "full"],
                        default="standard",
                        help="Detail level: minimal (critical only), standard (critical+high), full (all)")


def execute(args, workspace):
    return generate_summary(
        workspace,
        focus=args.focus,
        max_items=args.max_items,
        detail=args.detail,
    )


def generate_summary(
    workspace: str,
    focus: str = "all",
    max_items: int = 10,
    detail: str = "standard",
) -> Dict[str, Any]:
    """
    Generate an auto-summary with prioritized, condensed output.

    This is the single entry point for agents who want to understand a
    codebase without information overload. It runs multiple engines
    internally but filters and prioritizes the output.
    """
    workspace = os.path.abspath(workspace)

    # Severity filter based on detail level
    if detail == "minimal":
        severity_filter = {"critical"}
    elif detail == "standard":
        severity_filter = {"critical", "high"}
    else:
        severity_filter = {"critical", "high", "medium", "low"}

    result = {
        "status": "ok",
        "workspace": workspace,
        "focus": focus,
        "detail": detail,
    }

    # ─── 1. Quick Identity ────────────────────────────────
    try:
        from commands.handbook import _extract_project_identity
        identity = _extract_project_identity(workspace)
        result["identity"] = {
            "name": identity.get("name", os.path.basename(workspace)),
            "type": identity.get("type", "unknown"),
            "version": identity.get("version", "0.0.0"),
        }
        result["is_monorepo"] = identity.get("is_monorepo", False)
    except Exception:
        result["identity"] = {"name": os.path.basename(workspace)}

    # ─── 2. Frameworks (always useful) ────────────────────
    try:
        from framework_detect import detect_frameworks
        fw = detect_frameworks(workspace)
        result["frameworks"] = fw.get("frameworks", [])
    except Exception:
        result["frameworks"] = []

    # ─── 3. Registry Stats (from existing scan) ──────────
    registry_stats = {}
    try:
        from registry import load_backend_registry, load_frontend_registry
        backend = load_backend_registry(workspace)
        frontend = load_frontend_registry(workspace)
        nodes = backend.get("nodes", [])
        edges = backend.get("edges", [])
        registry_stats = {
            "backend_nodes": len(nodes) if isinstance(nodes, list) else 0,
            "backend_edges": len(edges) if isinstance(edges, list) else 0,
            "frontend_classes": len(frontend.get("classes", [])),
            "frontend_ids": len(frontend.get("ids", [])),
            "dead_nodes": sum(1 for n in (nodes if isinstance(nodes, list) else [])
                              if n.get("status") == "dead"),
            "active_nodes": sum(1 for n in (nodes if isinstance(nodes, list) else [])
                                if n.get("status") == "active"),
        }
    except Exception:
        pass
    result["registry_stats"] = registry_stats

    # ─── 4. Prioritized Findings ─────────────────────────
    findings = []

    if focus in ("security", "all"):
        # Security findings
        try:
            from secrets_engine import detect_secrets
            sec = detect_secrets(workspace)
            sec_stats = sec.get("stats", {})
            if sec_stats.get("total_secrets", 0) > 0:
                # Get only the highest severity items
                sec_items = sec.get("findings", sec.get("items", []))
                filtered = [s for s in sec_items
                            if s.get("severity", "low") in severity_filter][:max_items]
                findings.append({
                    "category": "secrets",
                    "total": sec_stats.get("total_secrets", 0),
                    "by_severity": sec_stats.get("by_severity", {}),
                    "top_items": filtered,
                    "action": "Review and move secrets to environment variables or secret manager",
                })
        except Exception:
            logger.debug("Secrets scan failed in summary")

        try:
            from vulnscan_engine import scan_vulnerabilities
            vuln = scan_vulnerabilities(workspace)
            vuln_count = vuln.get("stats", {}).get("total_vulnerabilities", 0)
            if vuln_count > 0:
                findings.append({
                    "category": "vulnerabilities",
                    "total": vuln_count,
                    "by_severity": vuln.get("stats", {}).get("by_severity", {}),
                    "top_items": vuln.get("vulnerabilities", [])[:max_items],
                    "action": "Update vulnerable dependencies or apply patches",
                })
        except Exception:
            logger.debug("Vuln scan failed in summary")

        try:
            from dataflow_engine import trace_dataflow
            df = trace_dataflow(workspace)
            violations = df.get("stats", {}).get("violations", 0)
            if violations > 0:
                findings.append({
                    "category": "dataflow_violations",
                    "total": violations,
                    "top_items": df.get("violations", [])[:max_items],
                    "action": "Add sanitizers or validators for unsafe data flows",
                })
        except Exception:
            logger.debug("Dataflow scan failed in summary")

    if focus in ("quality", "all"):
        # Quality findings
        try:
            from smell_engine import detect_smells
            smell = detect_smells(workspace)
            smell_stats = smell.get("stats", {})
            if smell_stats.get("total_smells", 0) > 0:
                top_items = smell.get("top_priority", [])[:max_items]
                filtered = [s for s in top_items
                            if s.get("severity", "info") in severity_filter]
                findings.append({
                    "category": "code_smells",
                    "total": smell_stats.get("total_smells", 0),
                    "health_score": smell_stats.get("health_score", 0),
                    "by_severity": {
                        "critical": smell_stats.get("critical", 0),
                        "warning": smell_stats.get("warning", 0),
                    },
                    "top_items": filtered,
                    "action": "Address critical smells first, then warnings",
                })
        except Exception:
            logger.debug("Smell scan failed in summary")

        try:
            from debugleak_engine import detect_debug_leaks
            dl = detect_debug_leaks(workspace)
            dl_stats = dl.get("stats", {})
            if dl_stats.get("total_leaks", 0) > 0:
                high_leaks = {k: v for k, v in dl_stats.get("by_category", {}).items()
                              if v > 0}
                findings.append({
                    "category": "debug_leaks",
                    "total": dl_stats.get("total_leaks", 0),
                    "by_category": high_leaks,
                    "top_items": dl.get("items", [])[:max_items],
                    "action": "Remove console.log, debugger, and TODO/FIXME before production",
                })
        except Exception:
            logger.debug("Debug leak scan failed in summary")

    if focus in ("architecture", "all"):
        # Architecture findings
        try:
            from circular_engine import detect_circular
            circ = detect_circular(workspace)
            cycle_count = circ.get("cycle_count", 0)
            if cycle_count > 0:
                chains = circ.get("cycles", circ.get("chains", {}))
                all_chains = []
                if isinstance(chains, dict):
                    for cat, items in chains.items():
                        all_chains.extend(items[:3])
                elif isinstance(chains, list):
                    all_chains = chains[:5]
                findings.append({
                    "category": "circular_dependencies",
                    "total": cycle_count,
                    "top_items": all_chains[:max_items],
                    "action": "Break circular imports to improve modularity",
                })
        except Exception:
            logger.debug("Circular detection failed in summary")

        try:
            from deadcode_engine import detect_dead_code
            dc = detect_dead_code(workspace)
            dc_stats = dc.get("stats", {})
            dead_count = dc_stats.get("total_dead_code", 0)
            if dead_count > 0:
                findings.append({
                    "category": "dead_code",
                    "total": dead_count,
                    "by_category": dc_stats.get("by_category", {}),
                    "top_items": dc.get("results", {}).get("unreachable", [])[:max_items],
                    "action": "Remove dead code to reduce maintenance burden",
                })
        except Exception:
            logger.debug("Dead code scan failed in summary")

    result["findings"] = findings
    result["total_finding_categories"] = len(findings)

    # ─── 5. Actionable Summary ───────────────────────────
    actions = []
    for f in findings:
        cat = f.get("category", "")
        total = f.get("total", 0)
        action = f.get("action", "")
        if total > 0 and action:
            actions.append(f"[{cat}] {total} issues — {action}")
    result["actions"] = actions

    # ─── 6. Auto-Recommendations ─────────────────────────
    recommendations = []
    registry_stats = result.get("registry_stats", {})
    if registry_stats.get("dead_nodes", 0) > registry_stats.get("active_nodes", 0) * 0.3:
        recommendations.append(
            "High dead code ratio (>30%) — run `dead-code` for details and cleanup"
        )
    if not result.get("frameworks"):
        recommendations.append(
            "No frameworks detected — run `init` and `scan` first"
        )
    if any(f["category"] == "secrets" and f["total"] > 0 for f in findings):
        recommendations.append(
            "Hardcoded secrets found — move to environment variables immediately"
        )
    if any(f["category"] == "circular_dependencies" and f["total"] > 3 for f in findings):
        recommendations.append(
            "Multiple circular dependencies — consider architectural refactoring"
        )
    result["recommendations"] = recommendations

    return result


register_command("summary", "Auto-summary with prioritized findings (anti-overload)", add_args, execute)
