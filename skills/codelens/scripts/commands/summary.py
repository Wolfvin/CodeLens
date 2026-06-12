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
import re
from typing import Dict, Any, List
from commands import register_command
from utils import logger


def _detect_android_identity(workspace: str) -> Dict[str, Any]:
    """Detect Android project identity from AndroidManifest.xml and build.gradle."""
    identity = {}

    # Extract app name from AndroidManifest.xml
    manifest_paths = [
        os.path.join(workspace, "app", "src", "main", "AndroidManifest.xml"),
        os.path.join(workspace, "src", "main", "AndroidManifest.xml"),
        os.path.join(workspace, "AndroidManifest.xml"),
    ]
    for manifest_path in manifest_paths:
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Look for android:label in <application> tag
                label_match = re.search(
                    r'<application[^>]*android:label=["\']([^"\']+)["\']', content
                )
                if not label_match:
                    label_match = re.search(
                        r'android:label=["\']([^"\']+)["\']', content
                    )
                if label_match:
                    label = label_match.group(1)
                    # Skip resource references like @string/app_name
                    if not label.startswith("@"):
                        identity["name"] = label
            except Exception:
                logger.debug(f"Failed to read AndroidManifest.xml at {manifest_path}")
            break

    # Extract version from build.gradle or build.gradle.kts
    gradle_paths = [
        os.path.join(workspace, "app", "build.gradle.kts"),
        os.path.join(workspace, "app", "build.gradle"),
        os.path.join(workspace, "build.gradle.kts"),
        os.path.join(workspace, "build.gradle"),
    ]
    for gradle_path in gradle_paths:
        if os.path.isfile(gradle_path):
            try:
                with open(gradle_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                # Extract versionName (Groovy and Kotlin DSL syntax)
                version_match = re.search(
                    r'versionName\s+["\']([^"\']+)["\']', content
                )
                if not version_match:
                    version_match = re.search(
                        r'versionName\s*=\s*["\']([^"\']+)["\']', content
                    )
                if version_match:
                    identity["version"] = version_match.group(1)
                # Extract versionCode
                version_code_match = re.search(r'versionCode\s+(\d+)', content)
                if not version_code_match:
                    version_code_match = re.search(r'versionCode\s*=\s*(\d+)', content)
                if version_code_match:
                    identity["versionCode"] = int(version_code_match.group(1))
            except Exception:
                logger.debug(f"Failed to read gradle file at {gradle_path}")
            break

    return identity


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

    v6.3: Added time budget — expensive sub-engines are skipped when the
    budget runs low, preventing timeout on repos with 40k+ nodes.
    """
    import time as _time
    _SUMMARY_BUDGET_SEC = 45  # Total budget for summary generation
    _start = _time.time()
    skipped_engines = []

    def _budget_remaining() -> float:
        return _SUMMARY_BUDGET_SEC - (_time.time() - _start)

    def _can_run(engine_name: str, est_seconds: float = 10) -> bool:
        """Check if we have enough budget to run an engine."""
        if _budget_remaining() >= est_seconds:
            return True
        skipped_engines.append(engine_name)
        logger.info(f"Skipping {engine_name} in summary — time budget low ({_budget_remaining():.1f}s remaining)")
        return False

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

    # ─── 2b. Android identity refinement ───────────────────
    frameworks = result.get("frameworks", [])
    if "android" in frameworks or "android_ndk" in frameworks:
        android_info = _detect_android_identity(workspace)
        # Override type based on framework
        if "android_ndk" in frameworks:
            result["identity"]["type"] = "android_app_native"
        elif "android" in frameworks:
            result["identity"]["type"] = "android_app"
        # Use detected app name if available
        if android_info.get("name"):
            result["identity"]["name"] = android_info["name"]
        # Use detected version if available
        if android_info.get("version"):
            result["identity"]["version"] = android_info["version"]
        # Store versionCode if available
        if android_info.get("versionCode"):
            result["identity"]["versionCode"] = android_info["versionCode"]
        # Check for Android NDK monorepo pattern (app/ + native/)
        if os.path.isdir(os.path.join(workspace, "app")) and \
           os.path.isdir(os.path.join(workspace, "native")):
            result["is_monorepo"] = True

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
        if _can_run("secrets", est_seconds=15):
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

        if _can_run("vuln_scan", est_seconds=10):
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

        if _can_run("dataflow", est_seconds=10):
            try:
                from dataflow_engine import trace_dataflow
                df = trace_dataflow(workspace)
                violations = df.get("stats", {}).get("violations", 0)
                if violations > 0:
                    df_items = df.get("violations", [])
                    # Filter by severity for minimal/standard detail
                    filtered_df = [v for v in df_items
                                   if v.get("severity", "medium") in severity_filter][:max_items]
                    if detail == "full" or filtered_df:
                        findings.append({
                            "category": "dataflow_violations",
                            "total": violations,
                            "top_items": filtered_df if detail != "full" else df_items[:max_items],
                            "action": "Add sanitizers or validators for unsafe data flows",
                        })
            except Exception:
                logger.debug("Dataflow scan failed in summary")

    if focus in ("quality", "all"):
        # Quality findings
        if _can_run("smell", est_seconds=20):
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

        if _can_run("debug_leak", est_seconds=10):
            try:
                from debugleak_engine import detect_debug_leaks
                dl = detect_debug_leaks(workspace)
                dl_stats = dl.get("stats", {})
                if dl_stats.get("total_leaks", 0) > 0:
                    high_leaks = {k: v for k, v in dl_stats.get("by_category", {}).items()
                                  if v > 0}
                    dl_items = dl.get("items", [])
                    filtered_dl = [d for d in dl_items
                                   if d.get("severity", "low") in severity_filter][:max_items]
                    # Skip debug_leaks entirely in minimal mode if no critical items
                    if detail != "minimal" or filtered_dl:
                        findings.append({
                            "category": "debug_leaks",
                            "total": dl_stats.get("total_leaks", 0),
                            "by_category": high_leaks,
                            "top_items": filtered_dl,
                            "action": "Remove console.log, debugger, and TODO/FIXME before production",
                        })
            except Exception:
                logger.debug("Debug leak scan failed in summary")

    if focus in ("architecture", "all"):
        # Architecture findings
        if _can_run("circular", est_seconds=15):
            try:
                from circular_engine import detect_circular
                circ = detect_circular(workspace)
                cycle_count = circ.get("total_cycles", circ.get("cycle_count", 0))
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

        if _can_run("dead_code", est_seconds=15):
            try:
                from deadcode_engine import detect_dead_code
                dc = detect_dead_code(workspace)
                dc_stats = dc.get("stats", {})
                dead_count = dc_stats.get("total_dead_code", 0)
                if dead_count > 0:
                    dc_items = dc.get("results", {}).get("unreachable", [])
                    filtered_dc = [d for d in dc_items
                                   if d.get("severity", "warning") in severity_filter][:max_items]
                    # Skip dead_code in minimal mode if no critical items
                    if detail != "minimal" or filtered_dc:
                        findings.append({
                            "category": "dead_code",
                            "total": dead_count,
                            "by_category": dc_stats.get("by_category", {}),
                            "top_items": filtered_dc,
                            "action": "Remove dead code to reduce maintenance burden",
                        })
            except Exception:
                logger.debug("Dead code scan failed in summary")

    result["findings"] = findings
    result["total_finding_categories"] = len(findings)
    result["skipped_engines"] = skipped_engines if skipped_engines else None
    result["generation_time_ms"] = int((_time.time() - _start) * 1000)

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
