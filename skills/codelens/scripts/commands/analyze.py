"""Analyze command — Full repository analysis in a single command.

The ultimate one-shot command for AI agents who need to understand
an ENTIRE repository immediately. Automatically:

1. Runs init + scan (if no registry exists)
2. Runs all major analysis engines
3. Produces a comprehensive, prioritized report
4. Includes architecture overview, risks, and actionable next steps

This is the "I just cloned a repo, tell me everything" command.

Usage:
    codelens analyze /path/to/repo
    codelens analyze /path/to/repo --focus security
    codelens analyze /path/to/repo --detail full
    codelens analyze /path/to/repo --skip-scan  (use existing registry)
    codelens analyze /path/to/repo --timeout 300  (5 min budget for engines)
    codelens analyze /path/to/repo --exclude-tests  (skip test entry points)
"""

import os
import time
from typing import Dict, Any, List, Optional
from commands import register_command
from utils import logger, CODELENS_VERSION


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--focus", choices=["security", "quality", "architecture", "all"],
                        default="all",
                        help="Focus area for analysis (default: all)")
    parser.add_argument("--detail", choices=["minimal", "standard", "full"],
                        default="standard",
                        help="Detail level: minimal (critical only), standard (critical+high), full (all)")
    parser.add_argument("--skip-scan", action="store_true", default=False,
                        help="Skip init+scan if registry already exists")
    parser.add_argument("--max-items", type=int, default=15,
                        help="Maximum items per category (default: 15)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Total time budget in seconds for analysis engines (default: 300)")
    parser.add_argument("--exclude-tests", action="store_true", default=False,
                        help="Exclude test entry points from entrypoints analysis")


def execute(args, workspace):
    return analyze_repository(
        workspace,
        focus=args.focus,
        detail=args.detail,
        skip_scan=args.skip_scan,
        max_items=args.max_items,
        timeout=args.timeout,
        exclude_tests=args.exclude_tests,
    )


def analyze_repository(
    workspace: str,
    focus: str = "all",
    detail: str = "standard",
    skip_scan: bool = False,
    max_items: int = 15,
    timeout: int = 300,
    exclude_tests: bool = False,
) -> Dict[str, Any]:
    """
    Full repository analysis — the single command to understand an entire codebase.

    This is the primary entry point for AI agents who want to analyze a repository
    they've never seen before. It runs all relevant engines, prioritizes findings,
    and produces a comprehensive report with actionable recommendations.

    The output is designed to give an AI agent everything it needs to:
    - Understand the project's purpose and architecture
    - Identify the most critical issues
    - Know what to fix first
    - Navigate the codebase efficiently
    """
    overall_start = time.time()
    total_budget = float(timeout)
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
        "codelens_version": CODELENS_VERSION,
        "time_budget_seconds": total_budget,
    }

    # ─── Phase 1: Ensure Registry Exists ──────────────────────

    codelens_dir = os.path.join(workspace, ".codelens")
    registry_exists = os.path.exists(os.path.join(codelens_dir, "backend.json"))

    if not skip_scan or not registry_exists:
        try:
            from commands.scan import execute as scan_execute
            import argparse

            # Run init
            from commands.init import execute as init_execute
            init_args = argparse.Namespace(workspace=workspace)
            init_execute(init_args, workspace)

            # Run scan
            scan_args = argparse.Namespace(
                workspace=workspace,
                incremental=False,
                full=False,
                format="json",
            )
            scan_result = scan_execute(scan_args, workspace)
            result["scan"] = {
                "files_scanned": scan_result.get("files_scanned", {}),
                "backend_nodes": scan_result.get("backend", {}).get("nodes", 0)
                    if isinstance(scan_result.get("backend", {}).get("nodes"), int)
                    else len(scan_result.get("backend", {}).get("nodes", [])),
                "backend_edges": scan_result.get("backend", {}).get("edges", 0)
                    if isinstance(scan_result.get("backend", {}).get("edges"), int)
                    else len(scan_result.get("backend", {}).get("edges", [])),
                "frontend_classes": scan_result.get("frontend", {}).get("classes", 0),
                "frontend_ids": scan_result.get("frontend", {}).get("ids", 0),
                "frameworks": scan_result.get("frameworks", []),
                "unsupported_langs": scan_result.get("unsupported_langs", []),
            }
        except Exception as e:
            logger.warning(f"Scan phase failed: {e}")
            result["scan"] = {"error": str(e)}

    # Reset start_time AFTER scan so the engine time budget is independent.
    # The scan phase can take 30-90s on large repos; without this reset,
    # the engine budget would be consumed by scan time, causing remaining
    # engines to be skipped prematurely.
    start_time = time.time()
    scan_elapsed = start_time - overall_start
    result["scan_elapsed_seconds"] = round(scan_elapsed, 2)

    # ─── Phase 2: Project Identity ───────────────────────────

    try:
        from commands.handbook import _extract_project_identity
        identity = _extract_project_identity(workspace)
        result["identity"] = {
            "name": identity.get("name", os.path.basename(workspace)),
            "type": identity.get("type", "unknown"),
            "version": identity.get("version", "0.0.0"),
            "description": identity.get("description", ""),
            "is_monorepo": identity.get("is_monorepo", False),
        }
    except Exception:
        result["identity"] = {
            "name": os.path.basename(workspace),
            "type": "unknown",
            "version": "0.0.0",
        }

    # ─── Phase 3: Frameworks & Languages ─────────────────────

    try:
        from framework_detect import detect_frameworks
        fw = detect_frameworks(workspace)
        result["frameworks"] = fw.get("frameworks", [])
        result["languages"] = fw.get("languages", {})
    except Exception:
        result["frameworks"] = []
        result["languages"] = {}

    # Detect languages from file extensions
    if not result.get("languages"):
        result["languages"] = _detect_languages(workspace)

    # ─── Phase 4: Architecture Overview ──────────────────────

    try:
        from outline_engine import get_workspace_outline
        outline = get_workspace_outline(workspace, max_files=200)
        result["architecture"] = {
            "total_files": outline.get("files_outlined", 0),
            "total_lines": outline.get("total_lines", 0),
            "directories": _extract_directory_structure(workspace),
            "entry_points": [],
            "key_modules": [],
        }

        # Extract key modules from outline
        outlines = outline.get("outlines", [])
        module_summary = []
        for o in outlines[:50]:
            inner = o.get("outline", o)
            fns = inner.get("functions", [])
            classes = inner.get("classes", [])
            if classes or fns:
                module_summary.append({
                    "file": o.get("file", ""),
                    "classes": [c.get("name", "") for c in classes[:5]],
                    "functions": [f.get("name", "") for f in fns[:5]],
                    "language": inner.get("language", "unknown"),
                })
        result["architecture"]["key_modules"] = module_summary[:20]
    except Exception:
        result["architecture"] = {"total_files": 0, "directories": []}

    # ─── Phase 5: Entry Points ──────────────────────────────

    try:
        from entrypoints_engine import map_entrypoints
        ep = map_entrypoints(workspace, exclude_tests=exclude_tests)
        result["architecture"]["entry_points"] = [
            {
                "type": e.get("type", ""),
                "file": e.get("file", ""),
                "handler": e.get("handler", ""),
                "line": e.get("line", 0),
            }
            for e in ep.get("entrypoints", [])[:max_items]
        ]
    except Exception:
        pass

    # ─── Phase 6: API Map ────────────────────────────────────

    try:
        from apimap_engine import map_api_routes
        api = map_api_routes(workspace, production_only=True)
        result["api_map"] = {
            "total_routes": api.get("stats", {}).get("total_routes", 0),
            "routes": [
                {
                    "method": r.get("method", ""),
                    "path": r.get("path", ""),
                    "handler": r.get("handler", ""),
                    "file": r.get("file", ""),
                    "auth": r.get("auth", False),
                }
                for r in api.get("routes", [])[:max_items]
            ],
            "by_method": api.get("stats", {}).get("by_method", {}),
        }
    except Exception:
        result["api_map"] = {"total_routes": 0, "routes": []}

    # ─── Phase 7: Findings (Prioritized) ─────────────────────

    findings = []

    # --- Security ---
    if focus in ("security", "all"):
        _run_engine(findings, "secrets", "Secrets Detection",
                    lambda: _detect_secrets(workspace, severity_filter, max_items),
                    start_time, total_budget)
        _run_engine(findings, "vulnerabilities", "CVE Vulnerabilities",
                    lambda: _detect_vulns(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "dataflow_violations", "Data Flow Violations",
                    lambda: _detect_dataflow(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "env_issues", "Environment Issues",
                    lambda: _detect_env(workspace, max_items),
                    start_time, total_budget)

    # --- Quality ---
    if focus in ("quality", "all"):
        _run_engine(findings, "code_smells", "Code Smells",
                    lambda: _detect_smells(workspace, severity_filter, max_items),
                    start_time, total_budget)
        _run_engine(findings, "debug_leaks", "Debug Code Leaks",
                    lambda: _detect_debug(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "complexity", "Complexity Hotspots",
                    lambda: _detect_complexity(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "dead_code", "Dead Code",
                    lambda: _detect_dead_code(workspace, max_items),
                    start_time, total_budget)

    # --- Architecture ---
    if focus in ("architecture", "all"):
        _run_engine(findings, "circular_dependencies", "Circular Dependencies",
                    lambda: _detect_circular(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "perf_hints", "Performance Hints",
                    lambda: _detect_perf(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "config_drift", "Dependency Drift",
                    lambda: _detect_config_drift(workspace, max_items),
                    start_time, total_budget)
        _run_engine(findings, "binary_artifacts", "Binary Artifacts",
                    lambda: _detect_binaries(workspace, max_items),
                    start_time, total_budget)

    result["findings"] = findings
    result["total_finding_categories"] = len(findings)
    result["total_issues"] = sum(f.get("total", 0) for f in findings)

    # ─── Phase 7b: Skipped Engines Summary ────────────────────

    skipped = [f for f in findings if f.get("skipped")]
    if skipped:
        result["skipped_engines"] = [
            {"category": s["category"], "reason": s.get("skip_reason", "")}
            for s in skipped
        ]

    # ─── Phase 8: Risk Assessment ─────────────────────────────

    risk_score = _compute_risk_score(findings, result)
    result["risk_assessment"] = risk_score

    # ─── Phase 9: Action Plan ─────────────────────────────────

    result["action_plan"] = _generate_action_plan(findings, risk_score)

    # ─── Phase 10: Recommendations ────────────────────────────

    result["recommendations"] = _generate_recommendations(findings, result)

    # ─── Done ─────────────────────────────────────────────────

    engine_elapsed = time.time() - start_time
    total_elapsed = time.time() - overall_start
    result["engine_elapsed_seconds"] = round(engine_elapsed, 2)
    result["elapsed_seconds"] = round(total_elapsed, 2)
    result["analysis_timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    return result


# ─── Engine Runners ────────────────────────────────────────

def _run_engine(findings: List[Dict], category: str, label: str, engine_fn, start_time: float, total_budget: float) -> None:
    """Safely run an analysis engine with time budget check."""
    elapsed = time.time() - start_time
    remaining = total_budget - elapsed

    # Skip if less than 20% of budget remains
    if remaining < total_budget * 0.2:
        logger.debug(f"Skipping engine {category}: time budget nearly exhausted ({remaining:.1f}s remaining)")
        findings.append({
            "category": category,
            "label": label,
            "total": 0,
            "severity": "info",
            "skipped": True,
            "skip_reason": f"Time budget nearly exhausted ({remaining:.1f}s remaining of {total_budget:.0f}s)",
            "action": f"Run '{category}' engine individually for full results",
        })
        return

    try:
        engine_start = time.time()
        result = engine_fn()
        engine_elapsed = time.time() - engine_start
        if result:
            result["elapsed_seconds"] = round(engine_elapsed, 2)
            findings.append(result)
    except Exception as e:
        logger.debug(f"Engine {category} failed: {e}")
        findings.append({
            "category": category,
            "label": label,
            "total": 0,
            "severity": "info",
            "skipped": True,
            "skip_reason": f"Engine error: {type(e).__name__}",
            "action": f"Run '{category}' engine individually for full results",
        })


def _detect_secrets(workspace: str, severity_filter: set, max_items: int) -> Optional[Dict]:
    from secrets_engine import detect_secrets
    sec = detect_secrets(workspace)
    total = sec.get("stats", {}).get("total_secrets", 0)
    if total == 0:
        return None
    items = sec.get("findings", sec.get("items", []))
    filtered = [s for s in items if s.get("severity", "low") in severity_filter][:max_items]
    return {
        "category": "secrets",
        "label": "Hardcoded Secrets",
        "total": total,
        "severity": "critical" if any(s.get("severity") == "critical" for s in items[:20]) else "high",
        "by_severity": sec.get("stats", {}).get("by_severity", {}),
        "top_items": filtered,
        "action": "Move ALL secrets to environment variables or a secret manager (e.g., Vault, AWS Secrets Manager)",
        "impact": "Leaked API keys, database passwords, and encryption keys can lead to unauthorized access and data breaches",
    }


def _detect_vulns(workspace: str, max_items: int) -> Optional[Dict]:
    from vulnscan_engine import scan_vulnerabilities
    vuln = scan_vulnerabilities(workspace)
    total = vuln.get("stats", {}).get("total_vulnerabilities", 0)
    if total == 0:
        return None
    return {
        "category": "vulnerabilities",
        "label": "Known CVEs",
        "total": total,
        "severity": "critical",
        "by_severity": vuln.get("stats", {}).get("by_severity", {}),
        "top_items": vuln.get("vulnerabilities", [])[:max_items],
        "action": "Update vulnerable dependencies immediately — check npm audit, pip audit, cargo audit, or govulncheck",
        "impact": "Known vulnerabilities can be exploited by attackers even without source code access",
    }


def _detect_dataflow(workspace: str, max_items: int) -> Optional[Dict]:
    from dataflow_engine import trace_dataflow
    df = trace_dataflow(workspace)
    all_violations = df.get("violations", [])
    # Only count production violations (test file violations are low severity)
    production_violations = [v for v in all_violations if not v.get("in_test_file", False)]
    total_production = len(production_violations)
    total_all = df.get("stats", {}).get("violations", 0)
    if total_all == 0:
        return None
    return {
        "category": "dataflow_violations",
        "label": "Unsafe Data Flows",
        "total": total_production,
        "total_including_tests": total_all,
        "severity": "high",
        "top_items": production_violations[:max_items],
        "action": "Add input sanitization and output encoding at every source→sink boundary",
        "impact": "Untainted data flows can lead to SQL injection, XSS, and command injection attacks",
    }


def _detect_env(workspace: str, max_items: int) -> Optional[Dict]:
    from envcheck_engine import check_env_vars
    env = check_env_vars(workspace)
    stats = env.get("stats", {})
    # Compute total issues from undocumented + required-but-missing vars
    undocumented = stats.get("undocumented", 0)
    total_vars = stats.get("total_vars", 0)
    issues = undocumented  # Each undocumented var is an issue
    if issues == 0 and total_vars == 0:
        return None
    return {
        "category": "env_issues",
        "label": "Environment Issues",
        "total": issues,
        "severity": "medium",
        "top_items": [{"name": v.get("name"), "is_required": v.get("is_required"),
                         "has_fallback": v.get("has_fallback"),
                         "documentation": v.get("documentation")}
                        for v in env.get("variables", [])[:max_items]
                        if not v.get("documentation")],
        "action": "Review .env files, ensure secrets are not committed, add .env to .gitignore",
        "impact": "Misconfigured environment variables can leak secrets or cause runtime failures",
    }


def _detect_smells(workspace: str, severity_filter: set, max_items: int) -> Optional[Dict]:
    from smell_engine import detect_smells
    smell = detect_smells(workspace)
    total = smell.get("stats", {}).get("total_smells", 0)
    if total == 0:
        return None
    top_items = smell.get("top_priority", [])[:max_items]
    filtered = [s for s in top_items if s.get("severity", "info") in severity_filter]
    health = smell.get("stats", {}).get("health_score", 100)
    return {
        "category": "code_smells",
        "label": "Code Smells",
        "total": total,
        "severity": "critical" if health < 40 else ("high" if health < 60 else "medium"),
        "health_score": health,
        "by_severity": {
            "critical": smell.get("stats", {}).get("critical", 0),
            "warning": smell.get("stats", {}).get("warning", 0),
        },
        "top_items": filtered,
        "action": "Address critical smells first (God Objects, deep nesting), then warnings (long functions, many params)",
        "impact": "Poor code quality leads to bugs, slow development, and difficult maintenance",
    }


def _detect_debug(workspace: str, max_items: int) -> Optional[Dict]:
    from debugleak_engine import detect_debug_leaks
    dl = detect_debug_leaks(workspace)
    total = dl.get("stats", {}).get("total_leaks", 0)
    if total == 0:
        return None
    by_cat = {k: v for k, v in dl.get("stats", {}).get("by_category", {}).items() if v > 0}
    return {
        "category": "debug_leaks",
        "label": "Debug Code Left In",
        "total": total,
        "severity": "high" if by_cat.get("debugger", 0) > 0 else "medium",
        "by_category": by_cat,
        "top_items": dl.get("items", [])[:max_items],
        "action": "Remove all console.log, var_dump, dd(), debugger, and TODO/FIXME before production deployment",
        "impact": "Debug code can leak sensitive information, slow down performance, and confuse users",
    }


def _detect_complexity(workspace: str, max_items: int) -> Optional[Dict]:
    from complexity_engine import compute_complexity
    comp = compute_complexity(workspace)
    hotspots = comp.get("hotspots", [])
    if not hotspots:
        return None
    return {
        "category": "complexity",
        "label": "Complexity Hotspots",
        "total": len(hotspots),
        "severity": "high" if any(h.get("cyclomatic", 0) > 20 for h in hotspots) else "medium",
        "avg_cyclomatic": comp.get("stats", {}).get("avg_cyclomatic", 0),
        "top_items": hotspots[:max_items],
        "action": "Refactor high-complexity functions by extracting helper methods, reducing branches, and simplifying conditionals",
        "impact": "Complex functions are bug magnets — they're hard to test, understand, and maintain",
    }


def _detect_dead_code(workspace: str, max_items: int) -> Optional[Dict]:
    from deadcode_engine import detect_dead_code
    dc = detect_dead_code(workspace)
    total = dc.get("stats", {}).get("total_dead_code", 0)
    if total == 0:
        return None
    return {
        "category": "dead_code",
        "label": "Dead Code",
        "total": total,
        "severity": "medium",
        "by_category": dc.get("stats", {}).get("by_category", {}),
        "top_items": dc.get("results", {}).get("unreachable", [])[:max_items],
        "action": "Remove dead code in batches with testing — start with unreachable code and unused exports",
        "impact": "Dead code increases maintenance burden, confuses new developers, and bloats the codebase",
    }


def _detect_circular(workspace: str, max_items: int) -> Optional[Dict]:
    from circular_engine import detect_circular
    circ = detect_circular(workspace)
    total = circ.get("cycle_count", 0)
    if total == 0:
        return None
    chains = circ.get("cycles", circ.get("chains", {}))
    all_chains = []
    if isinstance(chains, dict):
        for cat, items in chains.items():
            all_chains.extend(items[:3])
    elif isinstance(chains, list):
        all_chains = chains[:5]
    return {
        "category": "circular_dependencies",
        "label": "Circular Dependencies",
        "total": total,
        "severity": "high" if total > 5 else "medium",
        "top_items": all_chains[:max_items],
        "action": "Break circular imports by extracting shared logic into a separate module or using dependency injection",
        "impact": "Circular dependencies cause initialization order issues, make testing hard, and prevent tree-shaking",
    }


def _detect_perf(workspace: str, max_items: int) -> Optional[Dict]:
    from perfhint_engine import detect_perf_hints
    perf = detect_perf_hints(workspace)
    total = perf.get("stats", {}).get("total_hints", 0)
    if total == 0:
        return None
    return {
        "category": "perf_hints",
        "label": "Performance Issues",
        "total": total,
        "severity": perf.get("risk", "low"),
        "by_category": perf.get("stats", {}).get("by_category", {}),
        "top_items": perf.get("hints", [])[:max_items],
        "action": "Address N+1 queries first (critical), then sync blocking, then memory leaks",
        "impact": "Performance issues compound — N+1 queries scale linearly with data size, blocking calls freeze the event loop",
    }


def _detect_config_drift(workspace: str, max_items: int) -> Optional[Dict]:
    from configdrift_engine import detect_config_drift
    drift = detect_config_drift(workspace)
    total = drift.get("stats", {}).get("total_drift_items", 0)
    if total == 0:
        return None
    return {
        "category": "config_drift",
        "label": "Dependency Drift",
        "total": total,
        "severity": "low",
        "top_items": drift.get("drift_items", [])[:max_items],
        "action": "Update outdated dependencies to reduce security risk and get bug fixes",
        "impact": "Outdated dependencies may contain unpatched security vulnerabilities",
    }


def _detect_binaries(workspace: str, max_items: int) -> Optional[Dict]:
    from utils import scan_binary_artifacts
    bins = scan_binary_artifacts(workspace)
    total = bins.get("stats", {}).get("total_artifacts", 0)
    if total == 0:
        return None
    return {
        "category": "binary_artifacts",
        "label": "Binary/Compiled Files",
        "total": total,
        "severity": "low",
        "by_category": bins.get("stats", {}).get("by_category", {}),
        "top_items": bins.get("findings", [])[:max_items],
        "recommendations": bins.get("recommendations", []),
        "action": "Add binary files to .gitignore and use build pipelines instead",
        "impact": "Binary files bloat the repository, make diffs meaningless, and may contain vulnerable code",
    }


# ─── Helper Functions ──────────────────────────────────────

def _detect_languages(workspace: str) -> Dict[str, int]:
    """Detect programming languages by file extension."""
    ext_map = {
        ".php": "php", ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".tsx": "tsx", ".jsx": "jsx", ".rs": "rust", ".go": "golang",
        ".java": "java", ".cs": "csharp", ".rb": "ruby", ".lua": "lua",
        ".dart": "dart", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".html": "html", ".css": "css", ".scss": "scss", ".vue": "vue",
        ".svelte": "svelte", ".sql": "sql", ".sh": "shell",
        ".ex": "elixir", ".exs": "elixir",
        ".swift": "swift", ".scala": "scala", ".kt": "kotlin",
        ".nim": "nim", ".gd": "gdscript",
    }
    languages = {}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in {
            'node_modules', '.git', 'dist', 'build', 'target',
            '__pycache__', '.codelens', 'vendor', '.venv', 'venv',
        } and not d.startswith('.')]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            lang = ext_map.get(ext)
            if lang:
                languages[lang] = languages.get(lang, 0) + 1
    return dict(sorted(languages.items(), key=lambda x: -x[1]))


def _extract_directory_structure(workspace: str, max_depth: int = 3) -> List[str]:
    """Extract top-level directory structure."""
    dirs = []
    for root, dirnames, filenames in os.walk(workspace):
        depth = root.replace(workspace, "").count(os.sep)
        if depth >= max_depth:
            dirnames.clear()
            continue
        dirnames[:] = [d for d in dirnames if d not in {
            'node_modules', '.git', 'dist', 'build', 'target',
            '__pycache__', '.codelens', 'vendor', '.venv', 'venv',
        } and not d.startswith('.')]
        for d in dirnames:
            rel = os.path.relpath(os.path.join(root, d), workspace)
            dirs.append(rel + "/")
    return sorted(dirs)[:50]


def _compute_risk_score(findings: List[Dict], result: Dict) -> Dict[str, Any]:
    """Compute an overall risk score based on all findings.

    Uses logarithmic scaling to prevent saturation to 0 on large projects.
    The formula penalizes critical issues more heavily but uses log scaling
    so that having 10x more issues doesn't mean 10x lower score.

    Scoring:
    - Start at 100
    - Each critical issue costs log2(1 + n) * 8 points (max -25 per category)
    - Each high issue costs log2(1 + n) * 4 points (max -15 per category)
    - Each medium issue costs log2(1 + n) * 2 points (max -10 per category)
    - Each low issue costs log2(1 + n) * 0.5 points (max -5 per category)
    """
    import math

    score = 100  # Start at 100, deduct for issues

    critical_count = 0
    high_count = 0
    medium_count = 0

    for f in findings:
        total = f.get("total", 0)
        sev = f.get("severity", "low")
        if sev == "critical":
            critical_count += total
            # Logarithmic scaling: 1 issue = -8, 10 issues = -27.7, 100 issues = -53.3
            deduction = math.log2(1 + total) * 8
            score -= min(deduction, 25)  # Max -25 per category
        elif sev == "high":
            high_count += total
            deduction = math.log2(1 + total) * 4
            score -= min(deduction, 15)  # Max -15 per category
        elif sev == "medium":
            medium_count += total
            deduction = math.log2(1 + total) * 2
            score -= min(deduction, 10)  # Max -10 per category
        else:
            deduction = math.log2(1 + total) * 0.5
            score -= min(deduction, 5)  # Max -5 per category

    # Apply exponential decay when score goes below 0 to avoid
    # immediate saturation to 0 on projects with many categories.
    # This preserves relative differences: -10 → 72, -35 → 31, -70 → 10, -100 → 4
    if score < 0:
        score = round(100 * math.exp(score / 30))
    score = max(0, min(100, score))

    if score >= 80:
        level = "low"
        emoji = "🟢"
    elif score >= 60:
        level = "moderate"
        emoji = "🟡"
    elif score >= 40:
        level = "high"
        emoji = "🟠"
    else:
        level = "critical"
        emoji = "🔴"

    return {
        "score": score,
        "level": level,
        "emoji": emoji,
        "critical_issues": critical_count,
        "high_issues": high_count,
        "medium_issues": medium_count,
        "summary": f"{emoji} Risk: {level} ({score}/100) — {critical_count} critical, {high_count} high, {medium_count} medium issues",
    }


def _generate_action_plan(findings: List[Dict], risk: Dict) -> List[Dict]:
    """Generate a prioritized action plan."""
    plan = []

    # Sort findings by severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda f: sev_order.get(f.get("severity", "low"), 4))

    for f in sorted_findings:
        if f.get("total", 0) == 0:
            continue
        plan.append({
            "priority": "P0" if f.get("severity") == "critical" else
                       "P1" if f.get("severity") == "high" else
                       "P2" if f.get("severity") == "medium" else "P3",
            "category": f.get("category", ""),
            "label": f.get("label", ""),
            "total": f.get("total", 0),
            "action": f.get("action", ""),
            "impact": f.get("impact", ""),
        })

    return plan


def _generate_recommendations(findings: List[Dict], result: Dict) -> List[str]:
    """Generate contextual recommendations based on findings and project type."""
    recs = []

    # Based on findings
    for f in findings:
        cat = f.get("category", "")
        total = f.get("total", 0)
        if cat == "secrets" and total > 0:
            recs.append("CRITICAL: Hardcoded secrets found — move to environment variables or secret manager IMMEDIATELY before pushing to any remote")
        elif cat == "vulnerabilities" and total > 0:
            recs.append("CRITICAL: Known CVEs detected — update vulnerable dependencies or apply patches")
        elif cat == "debug_leaks" and total > 3:
            recs.append("Multiple debug leaks found — set up a pre-commit hook to catch debug code before it's committed")
        elif cat == "circular_dependencies" and total > 3:
            recs.append("Multiple circular dependencies — consider architectural refactoring or introducing a mediator module")
        elif cat == "dead_code" and total > 50:
            recs.append("High dead code volume — schedule a cleanup sprint, start with unreachable code and unused exports")
        elif cat == "complexity" and total > 5:
            recs.append("Complexity hotspots detected — consider pair programming or mob programming sessions for refactoring")
        elif cat == "perf_hints" and total > 0:
            recs.append("Performance anti-patterns found — profile the application under load to confirm impact")

    # Based on project type
    langs = result.get("languages", {})
    if "php" in langs and langs["php"] > 10:
        recs.append("PHP project detected — consider running 'phpstan analyse' for type checking and 'phpcs' for coding standards")
    if "python" in langs and langs["python"] > 5:
        recs.append("Python project detected — consider adding mypy for type checking and ruff for linting")
    if "go" in langs:
        recs.append("Go project detected — run 'go vet' and 'golangci-lint run' for additional static analysis")

    # Based on architecture
    fws = result.get("frameworks", [])
    if "react" in fws or "nextjs" in fws:
        recs.append("React/Next.js detected — use React DevTools Profiler to identify unnecessary re-renders")
    if "laravel" in fws:
        recs.append("Laravel detected — run 'php artisan route:list' to verify all routes are registered correctly")

    # General recommendations
    if not result.get("api_map", {}).get("total_routes"):
        recs.append("No API routes detected — if this is a backend project, run 'scan --full' and check that route files are in the configured paths")

    return recs[:15]


register_command(
    "analyze",
    "Full repository analysis: init + scan + all engines in one command (v6.0)",
    add_args,
    execute,
)
