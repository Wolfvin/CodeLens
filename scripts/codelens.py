#!/usr/bin/env python3
"""
CodeLens — Live Codebase Reference Intelligence (Tree-sitter Edition)

Usage:
    python3 codelens.py scan <workspace>              # Scan workspace and build registry
    python3 codelens.py query <name> <workspace>      # Query a specific class/id/function
    python3 codelens.py list <workspace> [filter]      # List entries with filter
    python3 codelens.py watch <workspace>              # Start file watcher
    python3 codelens.py init <workspace>               # Initialize .codelens config
    python3 codelens.py detect <workspace>             # Detect frameworks
    python3 codelens.py search <pattern> <workspace>   # Search code pattern across workspace
    python3 codelens.py trace <name> <workspace>       # Trace deep call chain
    python3 codelens.py impact <name> <workspace>      # Analyze change impact
    python3 codelens.py outline <workspace> [--file path]    # Get file structure outline
    python3 codelens.py missing-refs <workspace>       # Detect CSS/HTML mismatches
    python3 codelens.py diff <workspace>               # Compare registry snapshots
    python3 codelens.py circular <workspace>           # Detect circular dependencies
    python3 codelens.py context <name> <workspace>     # Get rich symbol context
    python3 codelens.py dependents <file> <workspace>  # Module-level import tracking
    python3 codelens.py validate <workspace>           # Validate registry vs file system
    python3 codelens.py dataflow <workspace>           # Trace data flow source→sink
    python3 codelens.py smell <workspace>              # Detect code smells
    python3 codelens.py side-effect <workspace> [--name func]  # Analyze function side effects
    python3 codelens.py refactor-safe <name> <workspace> # Pre-flight rename/move check
    python3 codelens.py dead-code <workspace>          # Enhanced dead code detection
    python3 codelens.py stack-trace <name> <workspace> # Error propagation simulation
    python3 codelens.py test-map <workspace>           # Test coverage mapping
    python3 codelens.py config-drift <workspace]       # Dependency drift detection
    python3 codelens.py type-infer <workspace>         # Lightweight type inference
    python3 codelens.py ownership <workspace>          # Git blame code ownership
    python3 codelens.py secrets <workspace>            # Detect hardcoded secrets/API keys
    python3 codelens.py entrypoints <workspace>        # Map execution entry points
    python3 codelens.py api-map <workspace>            # Map REST/GraphQL routes to handlers
    python3 codelens.py state-map <workspace>          # Track global state management
    python3 codelens.py env-check <workspace>          # Audit environment variables
    python3 codelens.py debug-leak <workspace>         # Detect leftover debug code
    python3 codelens.py complexity <workspace>         # Compute cyclomatic/cognitive complexity
    python3 codelens.py regex-audit <workspace>        # Audit regex for ReDoS and issues
    python3 codelens.py a11y <workspace>               # Detect accessibility issues
    python3 codelens.py vuln-scan <workspace>          # Scan dependencies for known CVEs
    python3 codelens.py perf-hint <workspace>          # Detect performance anti-patterns
    python3 codelens.py css-deep <workspace]           # Deep CSS analysis (vars, keyframes, specificity)
    python3 codelens.py handbook <workspace>           # Generate project handbook for AI agents
    python3 codelens.py ask <question> [workspace]     # Ask a natural language question about the codebase
    python3 codelens.py migrate <workspace>            # Migrate JSON registry to SQLite
    python3 codelens.py lsp-status                     # Check LSP server availability

AI-Optimized Flags (work with any command):
    --top N          Limit list/array results to top N items (smart default: 20 for list commands)
    --max-tokens N   Truncate output to fit within N tokens (~4 chars/token)
    --lite           Minimal output mode (command-specific: query={found,action}, smell={health_score,action}, etc.)
    --format ai      Normalized schema: {stats, items[], truncated}
    --deep           Enable LSP-enhanced deep analysis (requires language server installed)

Smart Defaults:
    - List commands auto-apply --top 20 (smell, complexity, dead-code, etc.)
    - --top sorts by relevance before truncating (severity for quality, cyclomatic for complexity)
    - --lite has tailored output for 10+ commands, not just query
    - Override smart --top with --top 0 for unlimited results
    - Auto-setup caps at 3000 files to prevent timeout (run 'scan' manually for full)
    - Set CODELENS_AI_MODE=1 to make --format ai the default output
"""

import sys
import os
import json
import argparse
from typing import Optional, Dict, Any, List

# Add scripts directory to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from commands import get_all_commands
from formatters import format_output
from registry import load_frontend_registry, load_backend_registry
from diff_engine import save_snapshot
from outline_engine import get_workspace_outline
from utils import write_output_files, CODELENS_VERSION, logger


# ─── Error Suggestion Helper ──────────────────────────────────

def _suggest_fix(command: str, error: Exception) -> str:
    """Return a helpful suggestion based on the command and error type."""
    error_type = type(error).__name__ if isinstance(error, Exception) else str(type(error))
    error_msg = str(error).lower()

    # Import errors
    if isinstance(error, ImportError) or 'import' in error_msg or 'module' in error_msg:
        return "A required module is missing. Check that all dependencies are installed (e.g., tree-sitter for your language)."

    # File not found errors
    if isinstance(error, FileNotFoundError) or 'no such file' in error_msg or 'not found' in error_msg:
        return "Check that the workspace path is correct and the directory exists."

    # Command-specific suggestions
    if command == "scan":
        if 'incremental' in error_msg:
            return "Try running without --incremental first, or delete .codelens/ and re-scan."
        return "Try running without --incremental, or check that the workspace contains source files."

    if command in ("query", "trace", "impact", "context", "dependents"):
        return "Make sure you've run 'scan' first to build the registry."

    if command in ("circular", "dead-code", "smell", "complexity", "api-map", "entrypoints"):
        return "Make sure you've run 'scan' first to build the registry, or check the workspace path."

    if command in ("secrets", "vuln-scan"):
        return "Check that the workspace path is correct and contains source files to scan."

    if command == "diff":
        return "Make sure you've run 'scan' at least twice to create snapshots for comparison."

    if command == "watch":
        return "Check that the workspace path is correct and watchdog is installed (pip install watchdog)."

    if command in ("test-map", "perf-hint"):
        return "Make sure you've run 'scan' first, or check that source files are present."

    if command == "ask":
        return "Try rephrasing your question, or run 'scan' first to build the codebase registry."

    if command == "handbook":
        return "Run 'scan' first, or check that the workspace contains a valid project."

    # Default suggestion
    return "Run with a different workspace path or check the command syntax with --help."


# ─── Workspace Auto-Detect ─────────────────────────────────────

LAST_WORKSPACE_FILE = ".codelens_last_workspace"


def _save_last_workspace(workspace: str) -> None:
    """Save the last used workspace path to a global cache file."""
    cache_dir = os.path.join(os.path.expanduser("~"), ".codelens")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, LAST_WORKSPACE_FILE)
    try:
        with open(cache_path, 'w', encoding='utf-8') as f:
            f.write(os.path.abspath(workspace))
    except IOError:
        pass


def _load_last_workspace() -> Optional[str]:
    """Load the last used workspace path from global cache."""
    cache_path = os.path.join(os.path.expanduser("~"), ".codelens", LAST_WORKSPACE_FILE)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                ws = f.read().strip()
            if ws and os.path.isdir(ws):
                return ws
        except IOError:
            pass
    return None


def _detect_workspace() -> Optional[str]:
    """Auto-detect workspace from current directory or project markers."""
    cwd = os.getcwd()

    markers = [
        'package.json', 'Cargo.toml', 'pyproject.toml', 'requirements.txt',
        'go.mod', 'pom.xml', 'build.gradle', 'Gemfile',
        '.git', '.codelens', 'tsconfig.json', 'next.config.js',
        'next.config.ts', 'vite.config.ts', 'vite.config.js',
        'composer.json', 'artisan',
    ]

    # Check cwd first
    for marker in markers:
        if os.path.exists(os.path.join(cwd, marker)):
            return cwd

    # Walk up from cwd to find a project root (max 10 levels)
    parent = os.path.dirname(cwd)
    depth = 0
    while parent != os.path.dirname(parent) and depth < 10:
        for marker in markers:
            if os.path.exists(os.path.join(parent, marker)):
                return parent
        parent = os.path.dirname(parent)
        depth += 1

    # Use cwd as fallback if it has source files
    for ext in ('.py', '.js', '.ts', '.tsx', '.rs', '.html', '.css', '.vue', '.svelte', '.php'):
        if any(f.endswith(ext) for f in os.listdir(cwd) if os.path.isfile(os.path.join(cwd, f))):
            return cwd

    # Use last workspace
    last = _load_last_workspace()
    if last:
        return last

    return None


def resolve_workspace(workspace_arg: Optional[str] = None) -> str:
    """Resolve workspace path with auto-detect fallback chain."""
    if workspace_arg:
        ws = os.path.abspath(workspace_arg)
        if os.path.isdir(ws):
            _save_last_workspace(ws)
            return ws
        else:
            print(f"[CodeLens] Warning: '{workspace_arg}' is not a valid directory. Attempting auto-detect...", file=sys.stderr)

    # Try last used workspace first
    last = _load_last_workspace()
    if last:
        _save_last_workspace(last)
        return last

    detected = _detect_workspace()
    if detected:
        _save_last_workspace(detected)
        return detected

    return os.getcwd()


# ─── Auto-Setup: Registry Bootstrap ────────────────────────────

def _registry_exists(workspace: str) -> bool:
    """Check if a valid registry exists for the workspace."""
    codelens_dir = os.path.join(workspace, ".codelens")
    if not os.path.isdir(codelens_dir):
        return False
    # Check for at least one registry file
    backend_json = os.path.join(codelens_dir, "backend.json")
    frontend_json = os.path.join(codelens_dir, "frontend.json")
    return os.path.exists(backend_json) or os.path.exists(frontend_json)


def _auto_setup(workspace: str) -> Dict[str, Any]:
    """Auto-run init + scan when no registry exists. Returns scan result or error info.
    
    Includes timeout protection: if the workspace has many source files,
    limits scan to --max-files 3000 to prevent long auto-setup times.
    """
    from commands.init import cmd_init
    from commands.scan import cmd_scan

    # Cap to prevent 5+ minute auto-setup on large repos
    _AUTO_SETUP_MAX_FILES = 3000
    _AUTO_SETUP_TIMEOUT_MSG = (
        "Auto-setup running with --max-files 3000 to prevent timeout. "
        "For full analysis, run: $CLI scan"
    )

    print("[CodeLens] No registry found. Auto-running init + scan...", file=sys.stderr)

    # Step 1: Init
    try:
        init_result = cmd_init(workspace)
        if init_result.get("status") != "ok":
            return {"auto_setup": "failed", "stage": "init", "error": init_result}
    except Exception as e:
        return {"auto_setup": "failed", "stage": "init", "error": str(e)}

    # Step 2: Scan (with max-files cap for auto-setup)
    try:
        print(f"[CodeLens] {_AUTO_SETUP_TIMEOUT_MSG}", file=sys.stderr)
        # Use subprocess to run scan with --max-files flag
        # This avoids coupling to cmd_scan's internal signature
        scan_cmd = [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
                     "scan", workspace, "--max-files", str(_AUTO_SETUP_MAX_FILES)]
        scan_proc = __import__("subprocess").run(
            scan_cmd, capture_output=True, text=True, timeout=120
        )
        if scan_proc.returncode != 0:
            # Fallback: try without max-files
            try:
                scan_result = cmd_scan(workspace, incremental=False)
                if scan_result.get("status") != "ok":
                    return {"auto_setup": "failed", "stage": "scan", "error": scan_result}
            except Exception as e2:
                return {"auto_setup": "failed", "stage": "scan", "error": str(e2)}
        else:
            scan_result = json.loads(scan_proc.stdout) if scan_proc.stdout.strip() else {"status": "ok"}

        files_scanned = scan_result.get("files_scanned", {})
        total_files = sum(v for v in files_scanned.values() if isinstance(v, int)) if isinstance(files_scanned, dict) else 0
        print(f"[CodeLens] Auto-setup complete. {total_files} files scanned. Registry built.", file=sys.stderr)
        
        result_info = {
            "auto_setup": "ok",
            "files_scanned": total_files,
            "capped": total_files >= _AUTO_SETUP_MAX_FILES,
        }
        if total_files >= _AUTO_SETUP_MAX_FILES:
            result_info["hint"] = "Auto-setup capped at 3000 files. Run 'scan' manually for full analysis."
        return result_info
    except Exception as e:
        return {"auto_setup": "failed", "stage": "scan", "error": str(e)}


# ─── Post-Processing: --top N ──────────────────────────────────

# Keys that commonly contain list results across all commands
_LIST_KEYS = [
    "functions", "findings", "leaks", "hints", "issues", "matches", "results",
    "violations", "entrypoints", "routes", "stores", "callers", "callees",
    "chains", "recommendations", "dependencies", "variables", "ownership",
    "cycles", "by_category",  # smell uses this
    "top_priority", "actionable_items",  # smell adds these
    "affected_direct", "affected_indirect",  # impact
    "risks", "drift",  # refactor-safe, config-drift
]

# Nested containers that may contain category-keyed lists
_NESTED_LIST_KEYS = [
    "results",  # dead-code: results{category:[]}
    "issues",   # missing-refs: issues{type:[]}
    "cycles",   # circular: cycles{type:[]}
]

# Commands that return large lists — get smart default --top
_LIST_COMMANDS = {
    "smell", "complexity", "dead-code", "debug-leak", "perf-hint",
    "secrets", "a11y", "css-deep", "regex-audit", "vuln-scan",
    "side-effect", "missing-refs", "circular", "list", "env-check",
    "test-map", "ownership", "entrypoints", "api-map", "state-map",
    "dataflow", "search", "symbols", "summary",
}

# Sort strategies per command for --top (sort by relevance before truncating)
_SORT_STRATEGIES = {
    "complexity": ("cyclomatic", True),      # sort by cyclomatic desc
    "smell": ("severity", True),              # sort by severity desc
    "debug-leak": ("severity", True),         # sort by severity desc
    "perf-hint": ("severity", True),          # sort by severity desc
    "secrets": ("severity", True),            # sort by severity desc
    "vuln-scan": ("severity", True),          # sort by severity desc
    "a11y": ("severity", True),               # sort by severity desc
    "css-deep": ("severity", True),           # sort by severity desc
    "regex-audit": ("severity", True),        # sort by severity desc
    "side-effect": ("effect_count", True),    # sort by effect_count desc
}

_SEVERITY_ORDER = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4, "info": 5}


def _sort_items(items: list, sort_key: str, descending: bool) -> list:
    """Sort items by a given key before truncation. Returns sorted list."""
    if not items or not isinstance(items[0], dict):
        return items

    def _item_sort_key(item):
        val = item.get(sort_key, 0)
        if sort_key == "severity" and isinstance(val, str):
            # Map severity strings to numeric order for sorting
            return _SEVERITY_ORDER.get(val.lower(), 99)
        if isinstance(val, (int, float)):
            return val
        if isinstance(val, str):
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0
        return 0

    try:
        return sorted(items, key=_item_sort_key, reverse=descending)
    except (TypeError, KeyError):
        return items


def _apply_top_n(result: Dict[str, Any], top_n: int, command: str = "") -> Dict[str, Any]:
    """Limit all list/array results to top N items. Sort by relevance first. Adds truncated flags."""
    if not isinstance(result, dict) or top_n <= 0:
        return result

    # Get sort strategy for this command
    sort_key, sort_desc = _SORT_STRATEGIES.get(command, (None, False))

    for key in _LIST_KEYS:
        val = result.get(key)
        if isinstance(val, list) and len(val) > top_n:
            # Sort by relevance before truncating
            if sort_key:
                val = _sort_items(val, sort_key, sort_desc)
                result[key] = val[:top_n]
            else:
                result[key] = val[:top_n]
            result[f"{key}_truncated"] = True
            result[f"{key}_total"] = len(val)
        elif isinstance(val, dict):
            # Handle category-keyed dicts like by_category{cat: [...]}
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list) and len(sub_val) > top_n:
                    # Sort items within each category
                    if sort_key:
                        sub_val = _sort_items(sub_val, sort_key, sort_desc)
                        val[sub_key] = sub_val[:top_n]
                    else:
                        val[sub_key] = sub_val[:top_n]
                    if "_truncated_categories" not in result:
                        result["_truncated_categories"] = {}
                    result["_truncated_categories"][sub_key] = len(sub_val)

    # Handle nested containers like dead-code's results{category:[]}
    for key in _NESTED_LIST_KEYS:
        val = result.get(key)
        if isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list) and len(sub_val) > top_n:
                    if sort_key:
                        sub_val = _sort_items(sub_val, sort_key, sort_desc)
                        val[sub_key] = sub_val[:top_n]
                    else:
                        val[sub_key] = sub_val[:top_n]
                    if "_truncated_categories" not in result:
                        result["_truncated_categories"] = {}
                    result["_truncated_categories"][sub_key] = len(sub_val)

    # Handle coverage_map in test-map (file:{fn:{...}})
    if "coverage_map" in result and isinstance(result["coverage_map"], dict):
        cm = result["coverage_map"]
        if len(cm) > top_n:
            keys = list(cm.keys())[:top_n]
            result["coverage_map"] = {k: cm[k] for k in keys}
            result["coverage_map_truncated"] = True
            result["coverage_map_total"] = len(cm)

    return result


# ─── Post-Processing: --max-tokens N ───────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for code/JSON."""
    return len(text) // 4


def _apply_max_tokens(result: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    """Truncate output to fit within max_tokens budget. Iteratively removes largest arrays."""
    if max_tokens <= 0:
        return result

    # Quick check: does it already fit?
    text = json.dumps(result, ensure_ascii=False)
    if _estimate_tokens(text) <= max_tokens:
        return result

    # Strategy: progressively truncate the largest lists
    result = dict(result)  # shallow copy to avoid mutating original
    result["_token_truncated"] = True

    # Find all list-valued keys with their sizes
    list_entries = []
    for key, val in result.items():
        if isinstance(val, list) and len(val) > 0:
            list_entries.append((key, len(val)))
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list) and len(sub_val) > 0:
                    list_entries.append((f"{key}.{sub_key}", len(sub_val)))

    # Sort by size descending — truncate largest first
    list_entries.sort(key=lambda x: x[1], reverse=True)

    for key_path, size in list_entries:
        # Try cutting to 10 items
        parts = key_path.split(".", 1)
        if len(parts) == 1:
            container = result
            k = parts[0]
        else:
            container = result.get(parts[0], {})
            k = parts[1]

        if isinstance(container, dict) and k in container:
            val = container[k]
            if isinstance(val, list) and len(val) > 10:
                container[k] = val[:10]
                container[f"{k}_truncated"] = True
                container[f"{k}_total"] = len(val)

        # Check if we fit now
        text = json.dumps(result, ensure_ascii=False)
        if _estimate_tokens(text) <= max_tokens:
            return result

    # Still too large? Strip all lists to 3 items max
    for key_path, _ in list_entries:
        parts = key_path.split(".", 1)
        if len(parts) == 1:
            container = result
            k = parts[0]
        else:
            container = result.get(parts[0], {})
            k = parts[1]

        if isinstance(container, dict) and k in container:
            val = container[k]
            if isinstance(val, list) and len(val) > 3:
                container[k] = val[:3]
                container[f"{k}_truncated"] = True

        text = json.dumps(result, ensure_ascii=False)
        if _estimate_tokens(text) <= max_tokens:
            return result

    # Last resort: strip everything except status and stats
    minimal = {"status": result.get("status", "ok")}
    for key in ("workspace", "found", "action", "action_reason", "risk", "health_score",
                "stats", "summary", "identity", "query"):
        if key in result:
            minimal[key] = result[key]
    minimal["_token_truncated_heavy"] = True
    return minimal


# ─── Post-Processing: --lite ───────────────────────────────────

def _apply_lite(result: Dict[str, Any], command: str) -> Dict[str, Any]:
    """Reduce output to minimum viable for AI decision-making."""
    if not isinstance(result, dict):
        return result

    # ─── Command-specific lite modes ────────────────────

    if command == "query":
        # Query lite: just the decision
        return {
            "status": result.get("status", "ok"),
            "found": result.get("found", False),
            "action": result.get("action", "CREATE"),
            "action_reason": result.get("action_reason", ""),
        }

    if command in ("impact", "refactor-safe"):
        return {
            "status": result.get("status", "ok"),
            "risk": result.get("risk") or result.get("safety"),
            "action": result.get("recommended_action") or result.get("action"),
        }

    if command == "smell":
        # Smell lite: health score + top 5 actionable items + action
        lite = {
            "status": result.get("status", "ok"),
            "health_score": result.get("health_score"),
            "total_findings": result.get("total_findings", 0),
            "action": "REVIEW" if result.get("health_score", 100) < 70 else "MONITOR",
        }
        # Include top actionable items (already sorted by severity)
        actionable = result.get("actionable_items", result.get("top_priority", []))
        if actionable:
            lite["top_findings"] = actionable[:5]
            if len(actionable) > 5:
                lite["top_findings_total"] = len(actionable)
        if result.get("stats"):
            lite["stats"] = result["stats"]
        return lite

    if command == "complexity":
        # Complexity lite: stats + top 5 most complex functions
        lite = {
            "status": result.get("status", "ok"),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        funcs = result.get("functions", [])
        if funcs:
            # Sort by cyclomatic complexity desc, take top 5
            sorted_funcs = sorted(funcs, key=lambda f: f.get("cyclomatic", 0), reverse=True)
            lite["top_complex"] = sorted_funcs[:5]
            lite["high_complexity_count"] = result["stats"].get("high_complexity", 0) if "stats" in result else 0
            if len(funcs) > 5:
                lite["functions_total"] = len(funcs)
        return lite

    if command == "dead-code":
        # Dead-code lite: totals + removal safety + top items
        lite = {
            "status": result.get("status", "ok"),
            "removal_safety": result.get("removal_safety", "unknown"),
            "recommended_action": result.get("recommended_action", ""),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        # Flatten all categories and take top 5
        all_items = []
        for cat_items in result.get("results", {}).values():
            if isinstance(cat_items, list):
                all_items.extend(cat_items)
        if all_items:
            lite["top_items"] = all_items[:5]
            lite["total_dead"] = len(all_items)
        return lite

    if command == "debug-leak":
        # Debug-leak lite: total + top 5 leaks by severity
        lite = {
            "status": result.get("status", "ok"),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        leaks = result.get("leaks", [])
        if leaks:
            sorted_leaks = sorted(leaks, key=lambda l: _SEVERITY_ORDER.get(l.get("severity", "info").lower(), 99))
            lite["top_leaks"] = sorted_leaks[:5]
            if len(leaks) > 5:
                lite["leaks_total"] = len(leaks)
        return lite

    if command == "perf-hint":
        # Perf-hint lite: risk + top 5 hints
        lite = {
            "status": result.get("status", "ok"),
            "risk": result.get("risk", "unknown"),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        hints = result.get("hints", [])
        if hints:
            sorted_hints = sorted(hints, key=lambda h: _SEVERITY_ORDER.get(h.get("severity", "info").lower(), 99))
            lite["top_hints"] = sorted_hints[:5]
            if len(hints) > 5:
                lite["hints_total"] = len(hints)
        return lite

    if command == "secrets":
        # Secrets lite: risk + top 5 findings
        lite = {
            "status": result.get("status", "ok"),
            "risk": result.get("risk", "unknown"),
            "action": "FIX_IMMEDIATELY" if result.get("risk") == "critical" else "REVIEW",
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        findings = result.get("findings", [])
        if findings:
            sorted_f = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "info").lower(), 99))
            lite["top_findings"] = sorted_f[:5]
        return lite

    if command in ("a11y", "css-deep", "regex-audit", "vuln-scan"):
        # Generic quality lite: stats + top 5 findings
        lite = {
            "status": result.get("status", "ok"),
            "risk": result.get("risk"),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        # Try findings, issues, hints in order
        for key in ("findings", "issues", "hints"):
            items = result.get(key, [])
            if items:
                sorted_items = sorted(items, key=lambda i: _SEVERITY_ORDER.get(i.get("severity", "info").lower(), 99))
                lite[f"top_{key}"] = sorted_items[:5]
                if len(items) > 5:
                    lite[f"{key}_total"] = len(items)
                break
        if result.get("recommendations"):
            lite["recommendations"] = result["recommendations"][:3]
        return lite

    # ─── Generic lite fallback ──────────────────────────
    lite = {
        "status": result.get("status", "ok"),
    }

    # Carry essential scalar fields
    for key in ("found", "action", "risk", "health_score", "query", "symbol", "workspace"):
        if key in result:
            lite[key] = result[key]

    # Carry stats if present
    if "stats" in result:
        lite["stats"] = result["stats"]

    # Carry recommendations (most actionable field)
    if result.get("recommendations"):
        lite["recommendations"] = result["recommendations"][:3]

    # Carry first 5 items from the primary result list
    for key in _LIST_KEYS:
        val = result.get(key)
        if isinstance(val, list) and len(val) > 0:
            # Sort by severity/relevance if applicable
            sort_key, sort_desc = _SORT_STRATEGIES.get(command, (None, False))
            if sort_key:
                val = _sort_items(val, sort_key, sort_desc)
            lite[key] = val[:5]
            if len(val) > 5:
                lite[f"{key}_total"] = len(val)
                lite[f"{key}_truncated"] = True
            break  # Only take the first matching list
        elif isinstance(val, dict):
            # Handle category-keyed dicts (smell's by_category, etc.)
            all_items = []
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, list):
                    for item in sub_val:
                        if isinstance(item, dict) and "_category" not in item:
                            item["_category"] = sub_key
                    all_items.extend(sub_val)
            if all_items:
                sort_key, sort_desc = _SORT_STRATEGIES.get(command, (None, False))
                if sort_key:
                    all_items = _sort_items(all_items, sort_key, sort_desc)
                lite[f"{key}_flat"] = all_items[:5]
                if len(all_items) > 5:
                    lite[f"{key}_total"] = len(all_items)
                break

    return lite


# ─── Confidence Distribution Helper ────────────────────────────

def compute_confidence_distribution_flat(result: Dict[str, Any]) -> Dict[str, int]:
    """Compute confidence distribution across all findings in a result dict."""
    dist = {"high": 0, "medium": 0, "low": 0}
    if not isinstance(result, dict):
        return dist
    for key, val in result.items():
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    c = item.get("confidence", "low")
                    if c in dist:
                        dist[c] += 1
        elif isinstance(val, dict):
            for sub_val in val.values():
                if isinstance(sub_val, list):
                    for item in sub_val:
                        if isinstance(item, dict):
                            c = item.get("confidence", "low")
                            if c in dist:
                                dist[c] += 1
    return dist


# ─── CLI Entry Point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"CodeLens v{CODELENS_VERSION} — Live Codebase Reference Intelligence (Tree-sitter Edition)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Import and register all command modules
    registry = get_all_commands()

    # Build subparsers from the command registry
    # Track which subparsers already have certain args to avoid conflicts
    _existing_subparser_args = {}
    for cmd_name, cmd_info in sorted(registry.items()):
        sub = subparsers.add_parser(cmd_name, help=cmd_info["help"])
        cmd_info["add_args"](sub)

        # Detect which args the command already defines
        existing_dests = set()
        for action in sub._actions:
            if hasattr(action, 'dest'):
                existing_dests.add(action.dest)
        _existing_subparser_args[cmd_name] = existing_dests

        # Add --format to each subparser (safe: no command defines its own --format)
        sub.add_argument("--format", "-f", choices=["json", "markdown", "ai"], default=None,
                         help="Output format: json, markdown, or ai (normalized schema)")

        # Add AI-optimized flags to subparser ONLY if the command doesn't already have them
        if "top" not in existing_dests:
            sub.add_argument("--top", type=int, default=None, metavar="N",
                             help="Limit list results to top N items")
        if "max_tokens" not in existing_dests:
            sub.add_argument("--max-tokens", type=int, default=None, metavar="N",
                             help="Truncate output to fit within N tokens")
        if "lite" not in existing_dests:
            sub.add_argument("--lite", action="store_true", default=False,
                             help="Minimal output mode for AI decision-making")
        if "deep" not in existing_dests:
            sub.add_argument("--deep", action="store_true", default=False,
                             help="Enable LSP-enhanced deep analysis (requires language server)")

    # Global format option (works before subcommand)
    # Default: "ai" if CODELENS_AI_MODE is set (for AI consumers), else "json"
    _default_format = "ai" if os.environ.get("CODELENS_AI_MODE", "").lower() in ("1", "true", "yes") else "json"
    parser.add_argument("--format", "-f", choices=["json", "markdown", "ai"], default=_default_format,
                        help=f"Output format (default: {_default_format}. Set CODELENS_AI_MODE=1 for ai default)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for SQLite database (default: .codelens/codelens.db)")

    # ─── Parse and dispatch ─────────────────────────────

    # Pre-parse to capture global flags before subparser overwrites them
    global_format = None
    global_top = None
    global_max_tokens = None
    global_lite = False

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('-f', '--format') and i + 1 < len(sys.argv):
            next_arg = sys.argv[i + 1]
            if next_arg in ('json', 'markdown', 'ai'):
                global_format = next_arg
        elif arg.startswith('-f=') and arg[3:] in ('json', 'markdown', 'ai'):
            global_format = arg[3:]
        elif arg.startswith('--format=') and arg[9:] in ('json', 'markdown', 'ai'):
            global_format = arg[9:]
        elif arg == '--top' and i + 1 < len(sys.argv):
            try:
                global_top = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg.startswith('--top='):
            try:
                global_top = int(arg.split('=', 1)[1])
            except ValueError:
                pass
        elif arg == '--max-tokens' and i + 1 < len(sys.argv):
            try:
                global_max_tokens = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg.startswith('--max-tokens='):
            try:
                global_max_tokens = int(arg.split('=', 1)[1])
            except ValueError:
                pass
        elif arg == '--lite':
            global_lite = True
        i += 1

    args = parser.parse_args()

    # Resolve format: subparser --format overrides global --format
    # If neither is set, use the parser's default (which may be "ai" if CODELENS_AI_MODE=1)
    subparser_format = getattr(args, 'format', None)
    if subparser_format is not None:
        args.format = subparser_format
    elif global_format is not None:
        args.format = global_format
    else:
        # Neither subparser nor global pre-parse captured a format.
        # Use the parser's default (respects CODELENS_AI_MODE)
        args.format = _default_format

    # Resolve --top: subparser overrides global
    if getattr(args, 'top', None) is None and global_top is not None:
        args.top = global_top

    # Resolve --max-tokens: subparser overrides global
    if getattr(args, 'max_tokens', None) is None and global_max_tokens is not None:
        args.max_tokens = global_max_tokens

    # Resolve --lite: either global or subparser
    if global_lite:
        args.lite = True

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve workspace with auto-detect fallback
    workspace = resolve_workspace(getattr(args, 'workspace', None))
    if workspace != (getattr(args, 'workspace', None) or ""):
        print(f"[CodeLens] Auto-detected workspace: {workspace}", file=sys.stderr)

    # ─── Auto-setup: if command needs registry and none exists, bootstrap it ────
    # Commands that need a registry to work meaningfully
    _REGISTRY_COMMANDS = {
        "query", "trace", "impact", "context", "dependents", "list",
        "symbols", "search", "summary", "smell", "complexity", "dead-code",
        "debug-leak", "circular", "missing-refs", "side-effect", "perf-hint",
        "secrets", "dataflow", "vuln-scan", "env-check", "entrypoints",
        "api-map", "state-map", "handbook", "analyze", "test-map",
        "stack-trace", "config-drift", "type-infer", "ownership",
        "regex-audit", "a11y", "css-deep", "diff", "ask", "validate",
    }

    auto_setup_info = None
    if args.command in _REGISTRY_COMMANDS and not _registry_exists(workspace):
        auto_setup_result = _auto_setup(workspace)
        if auto_setup_result.get("auto_setup") == "ok":
            auto_setup_info = {
                "auto_setup": True,
                "message": "Registry was auto-built. For best results, run 'scan' manually on large repos.",
            }
        else:
            auto_setup_info = {
                "auto_setup": "failed",
                "message": f"Auto-setup failed at {auto_setup_result.get('stage')}: {auto_setup_result.get('error')}",
            }

    try:
        cmd_info = registry[args.command]
        result = cmd_info["execute"](args, workspace)

        # ─── Dispatch enrichment (scan-specific) ──────
        if args.command == "scan":
            # Auto-save snapshot after scan
            try:
                frontend = load_frontend_registry(workspace)
                backend = load_backend_registry(workspace)
                save_snapshot(workspace, frontend, backend)
            except Exception:
                logger.warning("Failed to save snapshot", exc_info=True)
            # Generate outline.json + summary.json
            try:
                summary = write_output_files(workspace, result)
                result["outline_generated"] = bool(summary)
            except Exception:
                logger.warning("Failed to write output files", exc_info=True)
                result["outline_generated"] = False
            # Persist scan results to SQLite if available
            try:
                from persistent_registry import PersistentRegistry, is_sqlite_available
                if is_sqlite_available():
                    db_path = getattr(args, 'db_path', None)
                    pr = PersistentRegistry(workspace, db_path=db_path)
                    pr.store_scan_result(result)
                    result["sqlite_persisted"] = True
                    print("[CodeLens] Scan results persisted to SQLite database.", file=sys.stderr)
            except ImportError:
                pass
            except Exception as e:
                logger.warning(f"Failed to persist to SQLite: {e}", exc_info=True)

        # ─── Watch is a long-running command — it already printed output ──
        if args.command == "watch":
            return

        # ─── Post-processing: --top N (with smart default) ──
        top_n = getattr(args, 'top', None)
        # Smart default: auto-apply --top 20 for list-heavy commands if no explicit --top
        if top_n is None and args.command in _LIST_COMMANDS:
            top_n = 20
        if top_n and isinstance(result, dict):
            result = _apply_top_n(result, top_n, command=args.command)

        # ─── Post-processing: --lite ──
        if getattr(args, 'lite', False) and isinstance(result, dict):
            result = _apply_lite(result, args.command)

        # ─── Post-processing: --deep (hybrid LSP analysis) ──
        if getattr(args, 'deep', False) and isinstance(result, dict):
            try:
                from hybrid_engine import HybridEngine
                engine = HybridEngine(workspace, deep=True)
                if engine.lsp_active:
                    if args.command == "dead-code":
                        items = result.get("results", {})
                        if isinstance(items, dict):
                            for cat, cat_items in items.items():
                                if isinstance(cat_items, list):
                                    items[cat] = engine.verify_dead_code(cat_items)
                        result["deep_analysis"] = True
                        result["confidence_distribution"] = compute_confidence_distribution_flat(result)
                    elif args.command == "query":
                        result = engine.enhance_query(result, getattr(args, 'name', ''))
                        result["deep_analysis"] = True
                    elif args.command == "impact":
                        result = engine.enhance_impact(result, getattr(args, 'name', ''))
                        result["deep_analysis"] = True
                    elif args.command == "smell":
                        findings = result.get("findings", [])
                        if findings:
                            result["findings"] = engine.verify_dead_code(findings)
                        result["deep_analysis"] = True
                        result["confidence_distribution"] = compute_confidence_distribution_flat(result)
                    else:
                        result["deep_analysis"] = False
                        result["deep_analysis_hint"] = f"--deep not yet supported for {args.command}"
                    engine.cleanup()
                else:
                    result["deep_analysis"] = False
                    result["deep_analysis_hint"] = "No LSP server available. Install one (run: codelens --lsp-status)"
            except ImportError:
                result["deep_analysis"] = False
                result["deep_analysis_hint"] = "Hybrid engine not available (hybrid_engine.py not found)"

        # ─── Post-processing: --max-tokens N ──
        max_tokens = getattr(args, 'max_tokens', None)
        if max_tokens and isinstance(result, dict):
            result = _apply_max_tokens(result, max_tokens)

        # ─── Add auto-setup info if applicable ──
        if auto_setup_info and isinstance(result, dict):
            result["_auto_setup"] = auto_setup_info

        # ─── Determine command name for formatting ──
        format_command = args.command
        if args.command == "ask" and isinstance(result, dict):
            format_command = result.get("query_interpretation", {}).get("interpreted_as", "ask")

        # ─── Format and print output ──
        print(format_output(result, args.format, format_command))

    except FileNotFoundError as e:
        error_result = {
            "status": "error",
            "command": args.command,
            "error": str(e),
            "error_type": "file_not_found",
            "suggestion": "Check that the workspace path is correct and the directory exists."
        }
        print(format_output(error_result, args.format, args.command), file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        error_result = {
            "status": "error",
            "command": args.command,
            "error": str(e),
            "error_type": "import_error",
            "suggestion": "A required module is missing. Check that all dependencies are installed."
        }
        print(format_output(error_result, args.format, args.command), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        error_result = {
            "status": "error",
            "command": args.command,
            "error": str(e),
            "error_type": type(e).__name__,
            "suggestion": _suggest_fix(args.command, e)
        }
        print(format_output(error_result, args.format, args.command), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
