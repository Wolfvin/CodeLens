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

import argparse
import os
import re
import time
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
    # Issue #180: surface noise-reduction flags directly in `codelens summary --help`.
    # summary already auto-adapts detail level to codebase size; the epilog points
    # users at the additional output-shaping flags added by the dispatcher.
    # Issue #195: --check dispatches to absorbed commands (dashboard, arch-metrics,
    # architecture). Without --check, runs the legacy summary aggregator.
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Notes:\n"
        "  For AI/script consumption, use --format compact (token-efficient\n"
        "  single-char keys) or --lite (minimal output). For large repos,\n"
        "  --detail minimal restricts findings to critical severity only.\n"
        "\n"
        "Issue #195 sub-analyses (use --check to dispatch):\n"
        "  dashboard      Generate HTML visualization dashboard\n"
        "  arch-metrics   Architecture metrics (fan-in/out, instability, god-module)\n"
        "  architecture   Single-call codebase overview for AI agents\n"
        "  summary        Legacy auto-summary with prioritized findings (default)\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help="Issue #195: comma-separated sub-analyses. "
                             "Choices: summary, dashboard, arch-metrics, architecture. "
                             "Default: summary (legacy aggregator).")
    parser.add_argument("--focus", choices=["security", "quality", "architecture", "all"],
                        default="all",
                        help="summary: focus area (default: all)")
    parser.add_argument("--max-items", type=int, default=10,
                        help="summary: maximum items per category (default: 10)")
    parser.add_argument("--detail", choices=["minimal", "standard", "full", "auto"],
                        default="auto",
                        help="summary: detail level (default: auto)")
    parser.add_argument("--max-files", type=int, default=2000,
                        help="summary: maximum number of files to scan (default: 2000). "
                             "Prevents timeout on very large repos.")
    parser.add_argument("--timeout", type=int, default=120,
                        help="summary: total time budget in seconds (default: 120)")
    parser.add_argument("--write-agent-md", action="store_true",
                        help="summary: write a condensed AGENT.md file to .codelens/ for AI context")
    parser.add_argument("--max-tokens", type=int, default=8000,
                        help="summary: approximate max output tokens before smart truncation (default: 8000)")
    # dashboard passthroughs
    parser.add_argument("--output", "-o", default=None,
                        help="dashboard: output HTML path")
    parser.add_argument("--open", action="store_true", default=False,
                        help="dashboard: open in browser after generation")
    parser.add_argument("--compare", nargs=2, default=None, metavar=("SNAP1", "SNAP2"),
                        help="dashboard: compare two snapshots")
    # arch-metrics passthroughs
    parser.add_argument("--threshold-fanin", type=int, default=None,
                        help="arch-metrics: fan-in threshold (default 10)")
    parser.add_argument("--threshold-fanout", type=int, default=None,
                        help="arch-metrics: fan-out threshold (default 15)")
    parser.add_argument("--sort-by", default=None,
                        help="arch-metrics: instability|fan-in|fan-out|name (default instability)")
    # architecture passthroughs
    parser.add_argument("--no-cache", action="store_true", default=False,
                        help="architecture: bypass .codelens/architecture_cache.json")


def execute(args, workspace):
    # Issue #195: dispatch to absorbed sub-commands when --check is set.
    check_arg = getattr(args, "check", None)
    if check_arg:
        return _dispatch_subcommands(args, workspace, check_arg)
    # Default: legacy summary aggregator.
    max_files = getattr(args, 'max_files', 2000)
    return generate_summary(
        workspace,
        focus=args.focus,
        max_items=args.max_items,
        detail=args.detail,
        max_files=max_files,
        timeout=getattr(args, 'timeout', 120),
        write_agent_md=getattr(args, 'write_agent_md', False),
        max_tokens=getattr(args, 'max_tokens', 8000),
    )


# Issue #195: sub-command dispatch table for the summary umbrella.
_SUMMARY_SUBCOMMANDS = {
    "summary": "commands.summary",  # self — calls generate_summary directly
    "dashboard": "commands.dashboard",
    "arch-metrics": "commands.arch_metrics",
    "architecture": "commands.architecture",
}


def _dispatch_subcommands(args, workspace, check_arg):
    """Dispatch to one or more absorbed sub-commands per --check."""
    import importlib
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _SUMMARY_SUBCOMMANDS]
    if invalid:
        import sys
        print(
            f"[CodeLens] summary: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(_SUMMARY_SUBCOMMANDS.keys())}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not parts:
        parts = ["summary"]

    results = []
    checks_failed = 0
    for check_name in parts:
        try:
            if check_name == "summary":
                # Avoid recursion: call generate_summary directly.
                sub_result = generate_summary(
                    workspace,
                    focus=args.focus,
                    max_items=args.max_items,
                    detail=args.detail,
                    max_files=getattr(args, "max_files", 2000),
                    timeout=getattr(args, "timeout", 120),
                    write_agent_md=getattr(args, "write_agent_md", False),
                    max_tokens=getattr(args, "max_tokens", 8000),
                )
            else:
                mod = importlib.import_module(_SUMMARY_SUBCOMMANDS[check_name])
                sub_args = _build_subnamespace(args, check_name)
                sub_result = mod.execute(sub_args, workspace)
            if not isinstance(sub_result, dict):
                sub_result = {"status": "ok", "result": sub_result}
            sub_result["_check"] = check_name
            results.append(sub_result)
        except Exception as exc:
            checks_failed += 1
            results.append({
                "_check": check_name,
                "s": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            import sys
            print(f"[CodeLens] summary: --check {check_name} failed: {exc}",
                  file=sys.stderr)

    return {
        "s": "ok" if checks_failed == 0 else "partial",
        "st": {"checks_requested": len(parts), "checks_failed": checks_failed},
        "r": results,
    }


def _build_subnamespace(base_args, check_name):
    """Build a synthetic namespace for the dispatched sub-command."""
    import argparse as _ap
    ns = _ap.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "dashboard":
        ns.output = getattr(base_args, "output", None)
        ns.open = getattr(base_args, "open", False)
        ns.watch = False
        ns.compare = getattr(base_args, "compare", None)
    elif check_name == "arch-metrics":
        ns.threshold_fanin = getattr(base_args, "threshold_fanin", None) or 10
        ns.threshold_fanout = getattr(base_args, "threshold_fanout", None) or 15
        ns.sort_by = getattr(base_args, "sort_by", None) or "instability"
    elif check_name == "architecture":
        ns.lite = getattr(base_args, "lite", False)
        ns.no_cache = getattr(base_args, "no_cache", False)
    return ns


def _time_left(start: float, budget: float = 90) -> float:
    """Return remaining seconds within the time budget."""
    return max(0.0, budget - (time.time() - start))


def _count_source_files(workspace: str) -> int:
    """Quick count of source files for auto-detect sizing."""
    SOURCE_EXTS = {'.ts', '.tsx', '.js', '.jsx', '.py', '.rs', '.go', '.vue', '.svelte',
                   '.html', '.css', '.scss', '.java', '.kt', '.c', '.cpp', '.h', '.php', '.rb'}
    count = 0
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'dist', 'build',
                                                  '__pycache__', '.codelens', 'target', 'vendor'}]
        for f in files:
            if any(f.endswith(ext) for ext in SOURCE_EXTS):
                count += 1
                if count > 5000:  # Early exit for very large repos
                    return count
    return count


def _estimate_tokens(data: Any) -> int:
    """Rough estimate of JSON token count (1 token ~ 4 chars)."""
    try:
        import json
        text = json.dumps(data, default=str)
        return len(text) // 4
    except Exception:
        return 0


def generate_summary(
    workspace: str,
    focus: str = "all",
    max_items: int = 10,
    detail: str = "auto",
    max_files: int = 2000,
    timeout: int = 120,
    write_agent_md: bool = False,
    max_tokens: int = 8000,
) -> Dict[str, Any]:
    """
    Generate an auto-summary with prioritized, condensed output.

    This is the single entry point for agents who want to understand a
    codebase without information overload. It runs multiple engines
    internally but filters and prioritizes the output.
    """
    start = time.time()
    total_budget = float(timeout)
    skipped_engines: List[str] = []
    workspace = os.path.abspath(workspace)

    # ─── Auto-detect detail level based on codebase size ──────────
    if detail == "auto":
        file_count = _count_source_files(workspace)
        if file_count < 100:
            detail = "full"
        elif file_count < 1000:
            detail = "standard"
        else:
            detail = "minimal"

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
        from handbook_helpers import _extract_project_identity
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
        if _time_left(start, total_budget) < 5:
            skipped_engines.append("secrets")
        else:
            try:
                from secrets_engine import detect_secrets
                sec = detect_secrets(workspace, max_files=max_files)
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

        if _time_left(start, total_budget) < 5:
            skipped_engines.append("vulnerabilities")
        else:
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

        if _time_left(start, total_budget) < 5:
            skipped_engines.append("dataflow")
        else:
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
        if _time_left(start, total_budget) < 5:
            skipped_engines.append("code_smells")
        else:
            try:
                from smell_engine import detect_smells
                smell = detect_smells(workspace, max_files=max_files)
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

        if _time_left(start, total_budget) < 5:
            skipped_engines.append("debug_leaks")
        else:
            try:
                from debugleak_engine import detect_debug_leaks
                dl = detect_debug_leaks(workspace, max_files=max_files)
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
        if _time_left(start, total_budget) < 5:
            skipped_engines.append("circular")
        else:
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

        if _time_left(start, total_budget) < 5:
            skipped_engines.append("dead_code")
        else:
            try:
                from deadcode_engine import detect_dead_code
                dc = detect_dead_code(workspace, max_files=max_files)
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
    if skipped_engines:
        result["timed_out_engines"] = skipped_engines

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

    # ─── 7. Smart Truncation (prevent token overflow) ────────
    estimated_tokens = _estimate_tokens(result)
    if estimated_tokens > max_tokens:
        # Progressively truncate: reduce max_items, then drop low-priority items
        while _estimate_tokens(result) > max_tokens and max_items > 2:
            max_items = max(2, max_items - 2)
            for f in result.get("findings", []):
                if "top_items" in f and isinstance(f["top_items"], list):
                    f["top_items"] = f["top_items"][:max_items]
        result["truncated_for_tokens"] = True
        result["estimated_tokens"] = estimated_tokens

    # ─── 8. Write AGENT.md (optional, for AI context) ──────
    if write_agent_md:
        _write_agent_md(workspace, result)

    # ─── 9. Elapsed time ──────────────────────────────────────
    elapsed = time.time() - start
    result["elapsed_seconds"] = round(elapsed, 2)
    result["time_budget_seconds"] = total_budget

    return result


def _write_agent_md(workspace: str, result: Dict[str, Any]) -> None:
    """Write a condensed AGENT.md file to .codelens/ for AI agent context.

    This produces a markdown file optimized for inclusion in AI system prompts,
    with key information in a compact, scannable format.
    """
    codelens_dir = os.path.join(workspace, '.codelens')
    os.makedirs(codelens_dir, exist_ok=True)
    agent_md_path = os.path.join(codelens_dir, 'AGENT.md')

    lines = []
    identity = result.get("identity", {})
    name = identity.get("name", os.path.basename(workspace))
    lines.append(f"# {name} — CodeLens Summary")
    lines.append("")

    # Identity
    ptype = identity.get("type", "unknown")
    version = identity.get("version", "unknown")
    lines.append(f"- **Type**: {ptype}")
    lines.append(f"- **Version**: {version}")
    if result.get("is_monorepo"):
        lines.append("- **Monorepo**: Yes")
    frameworks = result.get("frameworks", [])
    if frameworks:
        lines.append(f"- **Frameworks**: {', '.join(frameworks)}")
    lines.append("")

    # Registry stats
    rs = result.get("registry_stats", {})
    if rs:
        lines.append("## Codebase Size")
        lines.append(f"- Nodes: {rs.get('backend_nodes', 0)} | Edges: {rs.get('backend_edges', 0)} | Dead: {rs.get('dead_nodes', 0)}")
        lines.append("")

    # Priority findings
    findings = result.get("findings", [])
    if findings:
        lines.append("## Priority Findings")
        for f in findings:
            cat = f.get("category", "")
            total = f.get("total", 0)
            action = f.get("action", "")
            if total > 0:
                lines.append(f"- **{cat}**: {total} issues — {action}")
        lines.append("")

    # Actions
    actions = result.get("actions", [])
    if actions:
        lines.append("## Immediate Actions")
        for a in actions[:5]:
            lines.append(f"- {a}")
        lines.append("")

    # Recommendations
    recs = result.get("recommendations", [])
    if recs:
        lines.append("## Recommendations")
        for r in recs:
            lines.append(f"- {r}")
        lines.append("")

    try:
        with open(agent_md_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    except IOError:
        logger.debug("Failed to write AGENT.md")


register_command("summary", "Auto-summary with prioritized findings (anti-overload)", add_args, execute)
