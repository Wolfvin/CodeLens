"""Self-analyze command — Run CodeLens on its own codebase for meta-analysis.

This is a fun meta-command that shows CodeLens eating its own dog food.
It runs multiple analysis commands on the CodeLens source tree itself
and presents a consolidated health report.
"""

import os
import sys
import argparse
from typing import Any, Dict


def add_args(parser: argparse.ArgumentParser) -> None:
    """Add self-analyze-specific arguments."""
    parser.add_argument(
        "--quick", action="store_true", default=False,
        help="Quick mode: only run fast analyses"
    )
    parser.add_argument(
        "--focus", choices=["smell", "security", "complexity", "dead-code", "all"],
        default="all", help="Focus area for self-analysis"
    )


def execute(args: argparse.Namespace, workspace: str) -> Dict[str, Any]:
    """Run CodeLens on its own codebase."""
    # Determine the CodeLens source directory
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    codelens_root = os.path.dirname(scripts_dir)

    results = {
        "status": "ok",
        "command": "self-analyze",
        "workspace": codelens_root,
        "focus": args.focus if hasattr(args, 'focus') else 'all',
        "analyses": {},
    }

    analyses_to_run = _get_analyses(args)

    for analysis_name, analysis_fn in analyses_to_run:
        try:
            result = analysis_fn(codelens_root, quick=getattr(args, 'quick', False))
            results["analyses"][analysis_name] = result
        except Exception as e:
            results["analyses"][analysis_name] = {
                "status": "error",
                "error": str(e),
            }

    # Compute overall health
    results["overall"] = _compute_overall_health(results["analyses"])
    results["dogfood"] = True  # 😋 We're eating our own dog food

    return results


def _get_analyses(args: argparse.Namespace):
    """Get list of analyses to run based on focus."""
    focus = getattr(args, 'focus', 'all')
    all_analyses = [
        ("smell", _run_smell),
        ("complexity", _run_complexity),
        ("dead-code", _run_dead_code),
        ("security", _run_security),
        ("circular", _run_circular),
    ]

    if focus == "all":
        return all_analyses

    return [(name, fn) for name, fn in all_analyses if name == focus]


def _run_smell(workspace: str, quick: bool = False) -> Dict[str, Any]:
    """Run smell analysis on self."""
    try:
        from smell_engine import detect_smells
        max_files = 500 if quick else 3000
        return detect_smells(workspace, max_files=max_files)
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _run_complexity(workspace: str, quick: bool = False) -> Dict[str, Any]:
    """Run complexity analysis on self."""
    try:
        from complexity_engine import compute_complexity
        max_files = 500 if quick else 3000
        return compute_complexity(workspace, max_files=max_files)
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _run_dead_code(workspace: str, quick: bool = False) -> Dict[str, Any]:
    """Run dead-code detection on self."""
    try:
        from deadcode_engine import detect_dead_code
        max_files = 500 if quick else 3000
        return detect_dead_code(workspace, max_files=max_files)
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _run_security(workspace: str, quick: bool = False) -> Dict[str, Any]:
    """Run security analysis (secrets + taint) on self."""
    results = {}
    try:
        from secrets_engine import detect_secrets
        results["secrets"] = detect_secrets(workspace, max_files=3000)
    except Exception as e:
        results["secrets"] = {"status": "error", "error": str(e)}

    try:
        from semantic_engine import analyze_workspace
        results["taint"] = analyze_workspace(workspace, language="python")
    except Exception as e:
        results["taint"] = {"status": "error", "error": str(e)}

    return results


def _run_circular(workspace: str, quick: bool = False) -> Dict[str, Any]:
    """Run circular dependency detection on self."""
    try:
        from circular_engine import detect_circular
        return detect_circular(workspace)
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _compute_overall_health(analyses: Dict[str, Any]) -> Dict[str, Any]:
    """Compute an overall health assessment from all analysis results."""
    health_score = 100
    issues = []

    # Deduct for smells
    smell = analyses.get("smell", {})
    if isinstance(smell, dict) and smell.get("status") != "error":
        hs = smell.get("health_score", 100)
        health_score = min(health_score, hs)
        findings = smell.get("total_findings", 0)
        if findings > 0:
            issues.append(f"Smell: {findings} code smell(s) detected")

    # Deduct for complexity
    complexity = analyses.get("complexity", {})
    if isinstance(complexity, dict) and complexity.get("status") != "error":
        stats = complexity.get("stats", {})
        high = stats.get("high_complexity", 0)
        if high > 0:
            health_score = min(health_score, max(0, health_score - high * 2))
            issues.append(f"Complexity: {high} high-complexity function(s)")

    # Deduct for dead code
    dead_code = analyses.get("dead-code", {})
    if isinstance(dead_code, dict) and dead_code.get("status") != "error":
        stats = dead_code.get("stats", {})
        dead = stats.get("total_dead_code", 0)
        if dead > 10:
            health_score = min(health_score, max(0, health_score - (dead - 10)))
            issues.append(f"Dead code: {dead} unused item(s)")

    # Deduct for security issues
    security = analyses.get("security", {})
    if isinstance(security, dict):
        secrets = security.get("secrets", {})
        if isinstance(secrets, dict) and secrets.get("status") != "error":
            found = secrets.get("stats", {}).get("total_secrets", 0)
            if found > 0:
                health_score = min(health_score, max(0, health_score - found * 10))
                issues.append(f"Security: {found} potential secret(s) found")

    # Grade
    if health_score >= 90:
        grade = "A"
    elif health_score >= 75:
        grade = "B"
    elif health_score >= 60:
        grade = "C"
    elif health_score >= 40:
        grade = "D"
    else:
        grade = "F"

    return {
        "health_score": health_score,
        "grade": grade,
        "issues": issues,
        "total_analyses": len(analyses),
    }


# ─── Command Registration ─────────────────────────────────────

COMMAND_INFO = {
    "help": "Run CodeLens on its own codebase (dogfooding / meta-analysis)",
    "add_args": add_args,
    "execute": execute,
}
