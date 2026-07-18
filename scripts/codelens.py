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
    python3 codelens.py registry-validate <workspace>  # Validate registry vs file system
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
    python3 codelens.py taint <workspace>              # Semantic taint analysis for vulnerability detection
    python3 codelens.py perf-hint <workspace>          # Detect performance anti-patterns
    python3 codelens.py css-deep <workspace]           # Deep CSS analysis (vars, keyframes, specificity)
    python3 codelens.py handbook <workspace>           # Generate project handbook for AI agents
    python3 codelens.py ask <question> [workspace]     # Ask a natural language question about the codebase
    python3 codelens.py migrate <workspace>            # Migrate JSON registry to SQLite
    python3 codelens.py lsp-status                     # Check LSP server availability
    python3 codelens.py taint <workspace>              # Semantic taint analysis for vulnerability detection
    python3 codelens.py dashboard <workspace>           # Generate HTML visualization dashboard
    python3 codelens.py history <workspace>             # Show historical trend data
    python3 codelens.py benchmark <workspace>          # Run accuracy and performance benchmarks

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
import io


def _force_utf8_stdio() -> None:
    """Force UTF-8 encoding on ``sys.stdout`` and ``sys.stderr``.

    Without this, Windows crashes with ``UnicodeEncodeError`` when commands
    emit Unicode characters like ``'\u2192'`` (the ``\u2192`` arrow used in
    trace paths such as ``sidepanel.ts \u2192 auth/google-auth-cache.ts``).
    The default Windows stdout encoding (``cp1252`` or similar) cannot
    represent those characters (issue #179).

    Behaviour:

    - On Linux/macOS ``sys.stdout.encoding`` is already ``utf-8`` \u2014 no-op.
    - Under pytest's ``capsys`` capture, ``encoding`` is also ``utf-8`` \u2014 no-op.
    - On Windows without ``PYTHONUTF8=1``, both streams are re-wrapped as
      ``TextIOWrapper(buffer, encoding='utf-8', errors='replace')``. The
      ``errors='replace'`` policy means any byte that still cannot be
      rendered by the terminal becomes ``?`` instead of raising.
    - Streams without a ``.buffer`` attribute (IDLE REPL, some custom
      capture objects) are skipped to avoid breaking those environments.

    The old stream's buffer is ``detach()``-ed before the new wrapper is
    built, so that garbage-collection of the old ``TextIOWrapper`` does
    not close the underlying buffer (which would make the new wrapper
    unusable with ``ValueError: I/O operation on closed file``).

    Runs unconditionally at module import time, before any user-code
    imports that might emit Unicode output.
    """
    for _name in ('stdout', 'stderr'):
        _stream = getattr(sys, _name, None)
        if _stream is None:
            continue
        _encoding = (getattr(_stream, 'encoding', None) or '').lower().replace('-', '')
        if _encoding == 'utf8':
            continue
        _buffer = getattr(_stream, 'buffer', None)
        if _buffer is None:
            continue
        # Detach the buffer from the old wrapper so its __del__/close
        # does not close the buffer out from under the new wrapper.
        # Best-effort: some custom stream classes lack detach() or
        # raise on it; in that case we proceed anyway (the new wrapper
        # is still created and the old wrapper's close, if any, will
        # simply no-op on a NULLed buffer).
        _detach = getattr(_stream, 'detach', None)
        if callable(_detach):
            try:
                _detach()
            except Exception:
                pass
        setattr(
            sys,
            _name,
            # newline='' disables TextIOWrapper's default write-side
            # translation of '\n' to os.linesep. Without it, every '\n' in
            # JSON/text output becomes '\r\n' on Windows even though the
            # source strings only ever contain '\n' — silently breaking
            # byte-exact comparisons and any downstream tool that assumes
            # Unix line endings (matches the already-UTF-8 no-op path
            # above, which never translates on Linux/macOS since
            # os.linesep is '\n' there).
            io.TextIOWrapper(_buffer, encoding='utf-8', errors='replace', newline=''),
        )


# Run before any other imports that might emit Unicode output to stdout/stderr.
_force_utf8_stdio()


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

    if command in ("secrets", "vuln-scan", "taint"):
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

# Canonical set of ``--format`` choices, in dispatch order. The first six are
# the JSON-family / graph formats (issue #17, #59). The final five are the
# Phase 2 developer-tool formats (issue #52): ``text``, ``junit-xml``,
# ``emacs``, ``vim``, ``gitlab-sast`` — all implemented in
# ``formatters.format_output`` and each verified to produce output. This single
# tuple is the source of truth for every argparse ``choices=`` list and the
# manual pre-parse guard below, so the CLI can never expose fewer formats than
# it actually supports.
_FORMAT_CHOICES = (
    "json", "markdown", "ai", "sarif", "compact", "graphml",
    "text", "junit-xml", "emacs", "vim", "gitlab-sast",
)


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
    """Check if a valid registry exists for the workspace.

    A registry is considered valid when at least one of these is true:

    1. A legacy JSON registry file exists (``backend.json`` or
       ``frontend.json``) — the pre-migration state used by older
       workspaces. Preserved so unmigrated workspaces keep working.
    2. A populated SQLite database exists at ``.codelens/codelens.db``
       — the post-migration state. "Populated" means the file exists
       AND the ``symbols`` table has at least one row, so an empty or
       corrupt db is NOT treated as a valid registry (issue #35).

    Without path 2, a workspace that ran ``migrate`` and then deleted
    its JSON files was treated as having no registry, triggering an
    unnecessary ``init + scan`` on every command and discarding the
    migrated SQLite data.
    """
    codelens_dir = os.path.join(workspace, ".codelens")
    if not os.path.isdir(codelens_dir):
        return False

    # Path 1: legacy JSON registry — still works for unmigrated workspaces.
    backend_json = os.path.join(codelens_dir, "backend.json")
    frontend_json = os.path.join(codelens_dir, "frontend.json")
    if os.path.exists(backend_json) or os.path.exists(frontend_json):
        return True

    # Path 2: migrated SQLite registry — must exist AND be populated,
    # so an empty/corrupt db does not falsely satisfy the check (issue #35).
    from persistent_registry import db_is_populated
    db_path = os.path.join(codelens_dir, "codelens.db")
    return db_is_populated(db_path)


def _auto_setup(workspace: str) -> Dict[str, Any]:
    """Auto-run init + scan when no registry exists. Returns scan result or error info.

    Applies a hard cap of ``_AUTO_SETUP_MAX_FILES`` (3000) files on BOTH the
    subprocess path and the in-process fallback path, so auto-setup can never
    silently hang on huge repos (issue #34).

    Returns a dict with:
      - ``auto_setup``: "ok" | "failed"
      - ``capped``: True iff the 3000-file cap was reached (only on success)
      - ``fallback``: True iff the in-process fallback path was taken (only on success)
      - ``files_scanned``: total files scanned (only on success)
      - ``hint``: human-readable note (only present when ``capped`` is True)
      - ``stage`` / ``error``: failure details (only on failure)
    """
    from commands.init import cmd_init
    from commands.scan import cmd_scan
    import subprocess

    # Cap to prevent 5+ minute auto-setup on large repos.
    # Applied to BOTH the subprocess path and the in-process fallback.
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

    # Step 2: Scan (with --max-files cap on BOTH paths)
    try:
        print(f"[CodeLens] {_AUTO_SETUP_TIMEOUT_MSG}", file=sys.stderr)
        # Primary path: subprocess with --max-files flag (timeout=120s).
        # This isolates the scan in a child process so we can enforce a
        # hard wall-clock timeout on top of the file-count cap.
        scan_cmd = [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
                     "scan", workspace, "--max-files", str(_AUTO_SETUP_MAX_FILES)]
        fallback_taken = False
        scan_result: Optional[Dict[str, Any]] = None
        try:
            scan_proc = subprocess.run(
                scan_cmd, capture_output=True, text=True, timeout=120
            )
            if scan_proc.returncode == 0:
                scan_result = (
                    json.loads(scan_proc.stdout)
                    if scan_proc.stdout.strip()
                    else {"status": "ok"}
                )
        except Exception as e:
            print(f"[CodeLens] Scan subprocess error: {e}; "
                  "falling back to in-process scan.", file=sys.stderr)

        # Fallback path: in-process scan with the SAME max_files cap.
        # The cap is enforced by cmd_scan(max_files=...) so huge repos
        # cannot hang auto-setup even when the subprocess path fails.
        if scan_result is None:
            fallback_taken = True
            print(f"[CodeLens] Falling back to in-process scan "
                  f"with max_files={_AUTO_SETUP_MAX_FILES}.", file=sys.stderr)
            scan_result = cmd_scan(
                workspace, incremental=False, max_files=_AUTO_SETUP_MAX_FILES
            )
            if scan_result.get("status") != "ok":
                return {"auto_setup": "failed", "stage": "scan", "error": scan_result}

        files_scanned = scan_result.get("files_scanned", {})
        total_files = sum(v for v in files_scanned.values() if isinstance(v, int)) if isinstance(files_scanned, dict) else 0
        capped = total_files >= _AUTO_SETUP_MAX_FILES
        print(f"[CodeLens] Auto-setup complete. {total_files} files scanned. "
              f"Registry built. (fallback={fallback_taken}, capped={capped})",
              file=sys.stderr)

        result_info: Dict[str, Any] = {
            "auto_setup": "ok",
            "files_scanned": total_files,
            "capped": capped,
            "fallback": fallback_taken,
        }
        if capped:
            result_info["hint"] = "Auto-setup capped at 3000 files. Run 'scan' manually for full analysis."
        return result_info
    except Exception as e:
        return {"auto_setup": "failed", "stage": "scan", "error": str(e)}


# ─── Post-Processing: --top N ──────────────────────────────────

# Keys that commonly contain list results across all commands.
# Used by _apply_lite to find the "primary result list" for lite mode output.
# NOTE: _apply_top_n no longer relies on this list — it auto-discovers all
# list-valued keys at runtime (issue #36). This list is kept solely for
# _apply_lite's priority-ordered lookup.
_LIST_KEYS = [
    "functions", "findings", "leaks", "hints", "issues", "matches", "results",
    "violations", "entrypoints", "routes", "stores", "callers", "callees",
    "chains", "recommendations", "dependencies", "variables", "ownership",
    "cycles", "by_category",  # smell uses this
    "top_priority", "actionable_items",  # smell adds these
    "affected_direct", "affected_indirect",  # impact
    "risks", "drift",  # refactor-safe, config-drift
]

# Keys whose values should NEVER be truncated by --top, even if they're lists.
# These are structural/metadata keys (command names, engine names, etc.) that
# are not "result lists" in the --top N contract sense. Adding a key here is
# an explicit opt-out — the default is to truncate all list-valued keys (issue #36).
_NO_TOP_KEYS = frozenset({
    "available_commands",  # help/list-commands: metadata, not results
    "engines",             # analyze: engine list is structural
    "supported_languages", # setup/info: metadata
    "categories",          # category names are metadata
    "tags",                # tag names are metadata
})

# Commands that return large lists — get smart default --top
_LIST_COMMANDS = {
    "smell", "complexity", "dead-code", "debug-leak", "perf-hint",
    "secrets", "a11y", "css-deep", "regex-audit", "vuln-scan",
    "side-effect", "missing-refs", "circular", "list", "env-check",
    "test-map", "ownership", "entrypoints", "api-map", "state-map",
    "dataflow", "search", "symbols", "summary", "taint", "deps-audit",
}

# Sort strategies per command for --top (sort by relevance before truncating)
_SORT_STRATEGIES = {
    "complexity": ("cyclomatic", True),      # sort by cyclomatic desc
    "smell": ("severity", True),              # sort by severity desc
    "debug-leak": ("severity", True),         # sort by severity desc
    "perf-hint": ("severity", True),          # sort by severity desc
    "secrets": ("severity", True),            # sort by severity desc
    "vuln-scan": ("severity", True),          # sort by severity desc
    "deps-audit": ("severity", True),         # sort by severity desc (issue #158)
    "a11y": ("severity", True),               # sort by severity desc
    "css-deep": ("severity", True),           # sort by severity desc
    "regex-audit": ("severity", True),        # sort by severity desc
    "side-effect": ("effect_count", True),    # sort by effect_count desc
    "taint": ("severity", True),               # sort by severity desc
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
    """Limit all list/array results to top N items. Sort by relevance first. Adds truncated flags.

    Auto-discovers ALL list-valued keys at runtime — no allowlist needed (issue #36).
    This ensures --top N is a universal contract: any command, present or future,
    that returns a list under any key name will be truncated. Keys in _NO_TOP_KEYS
    are exempt (structural/metadata keys like ``available_commands``).

    Also handles category-keyed dicts (e.g., ``by_category{cat: [...]}``) and
    nested containers (e.g., ``results{category: [...]}``) by scanning dict
    values for lists.
    """
    if not isinstance(result, dict) or top_n <= 0:
        return result

    # Get sort strategy for this command
    sort_key, sort_desc = _SORT_STRATEGIES.get(command, (None, False))

    # Auto-discover: iterate ALL top-level keys (snapshot to allow in-place additions).
    # Truncate every list-valued key except those in _NO_TOP_KEYS or starting with '_'.
    # Also scan dict-valued keys for category-keyed lists.
    for key in list(result.keys()):
        if key in _NO_TOP_KEYS or key.startswith("_"):
            continue
        val = result[key]

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
            # Handle category-keyed dicts like by_category{cat: [...]} and
            # nested containers like dead-code's results{category:[]}
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

    # Handle coverage_map in test-map (file:{fn:{...}}) — dict-of-dicts, not
    # dict-of-lists, so the auto-discover above doesn't catch it.
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
    """Reduce output to minimum viable for AI decision-making.

    Umbrella commands (issue #195) wrap sub-analysis output as
    ``{"s":.., "st":.., "r":[{"_check": name, ...}, ...]}``. The per-check
    reducers below (``_apply_lite_single``) were written against the old
    pre-umbrella leaf commands (``smell``, ``dead-code``, ``query``, ...)
    and keyed off the top-level command name. Since #195/#199/#200,
    ``command`` is always one of the 12 umbrella names (``context``,
    ``audit``, ``security``, ...) which never match any branch below —
    every umbrella command's --lite output silently collapsed to
    ``{"status": "ok"}`` with all data dropped. Fix: unwrap the envelope,
    apply the existing per-check reducer to each item keyed by its own
    ``_check`` name, then re-wrap.
    """
    if isinstance(result, dict) and isinstance(result.get("r"), list) and "_check" in (
        result["r"][0] if result["r"] and isinstance(result["r"][0], dict) else {}
    ):
        lite_items = [
            _apply_lite_single(item, item.get("_check", command)) if isinstance(item, dict) else item
            for item in result["r"]
        ]
        for lite_item, orig_item in zip(lite_items, result["r"]):
            if isinstance(lite_item, dict) and isinstance(orig_item, dict) and "_check" in orig_item:
                lite_item["_check"] = orig_item["_check"]
        return {"s": result.get("s", "ok"), "st": result.get("st"), "r": lite_items}
    return _apply_lite_single(result, command)


def _apply_lite_single(result: Dict[str, Any], command: str) -> Dict[str, Any]:
    """Reduce a single (non-enveloped) sub-result to minimum viable output."""
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

    if command == "history":
        # Same class of bug as "summary" above: history's real payload
        # (snapshots count, latest snapshot's health metrics, trends,
        # deltas) lives under keys the generic fallback doesn't know about
        # (only checks a fixed scalar-key allowlist plus a couple of
        # well-known list keys), so --lite collapsed to just
        # {"status", "workspace"} with zero actual history data.
        lite = {
            "status": result.get("status", "ok"),
            "workspace": result.get("workspace"),
            "snapshots": result.get("snapshots"),
        }
        latest = result.get("latest")
        if isinstance(latest, dict):
            lite["latest"] = {
                k: latest[k] for k in (
                    "timestamp", "health_score", "total_findings",
                    "findings_by_severity", "avg_complexity",
                    "high_complexity_count",
                ) if k in latest
            }
        if result.get("trends"):
            lite["trends"] = result["trends"]
        if result.get("deltas"):
            lite["deltas"] = result["deltas"]
        return lite

    if command == "summary":
        # Summary's own job is "anti-overload prioritized findings" (its
        # --help description), so --lite must actually be minimal. The
        # generic fallback below only trims the outer `findings` list, not
        # each finding's nested `top_items` (and dataflow findings nest a
        # full flow_chain per item) — a --lite summary on a real workspace
        # was coming back with thousands of tokens of untouched detail,
        # defeating the point of the flag.
        lite = {
            "status": result.get("status", "ok"),
        }
        for key in ("workspace", "identity", "frameworks", "is_monorepo"):
            if key in result:
                lite[key] = result[key]
        if result.get("recommendations"):
            lite["recommendations"] = result["recommendations"][:3]
        findings = result.get("findings", [])
        if findings:
            lite_findings = []
            for f in findings:
                if not isinstance(f, dict):
                    continue
                lf = {k: v for k, v in f.items() if k != "top_items"}
                top_items = f.get("top_items")
                if isinstance(top_items, list) and top_items:
                    trimmed = []
                    for item in top_items[:3]:
                        if isinstance(item, dict) and "flow_chain" in item:
                            item = {k: v for k, v in item.items() if k != "flow_chain"}
                        trimmed.append(item)
                    lf["top_items"] = trimmed
                    if len(top_items) > 3:
                        lf["top_items_total"] = len(top_items)
                lite_findings.append(lf)
            lite["findings"] = lite_findings
        return lite

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

    if command == "taint":
        # Taint lite: risk + stats + top 5 findings + key actionable items
        lite = {
            "status": result.get("status", "ok"),
            "risk": result.get("risk"),
        }
        if "stats" in result:
            lite["stats"] = result["stats"]
        findings = result.get("findings", [])
        if findings:
            sorted_f = sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.get("severity", "info").lower(), 99))
            lite["top_findings"] = sorted_f[:5]
            if len(findings) > 5:
                lite["findings_total"] = len(findings)
        if result.get("recommendations"):
            lite["recommendations"] = result["recommendations"][:3]
        if result.get("by_rule"):
            lite["by_rule"] = result["by_rule"]
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


# ─── Always-Warm Registry (issue #237) ─────────────────────────

_AUTO_RESCAN_FILE_THRESHOLD = 20


def _check_staleness(workspace: str, args) -> Optional[Dict[str, Any]]:
    """Check registry staleness vs git HEAD and auto-rescan small diffs.

    Registry staleness vs git HEAD was previously only surfaced passively via
    `history --check git-status`'s "re-scan recommendation" field — nothing
    else read it. Every other analysis command could silently answer from a
    stale graph. Note: deliberately NOT gated on the same _REGISTRY_COMMANDS
    set as the auto-setup block in main() — that set still lists pre-#195
    leaf command names and is missing several current umbrella commands
    (audit, security, deps, doctor — see issue #244); "every command except
    scan itself" is simpler and correct without depending on that list
    being fixed.

    Returns:
        None if not stale (or staleness can't be determined — e.g. not a
        git repo, git unavailable, no registry yet). Otherwise a dict with
        ``was_stale``, ``auto_rescanned``, ``changed_files_count``, and
        (when not auto-rescanned) a ``hint`` field.
    """
    if args.command == "scan" or not _registry_exists(workspace):
        return None
    try:
        import git_aware
        from utils import default_db_path
        db_path = getattr(args, "db_path", None) or default_db_path(workspace)
        if not git_aware.rescan_recommended(workspace, db_path):
            return None
        last_sha = git_aware.get_last_indexed_sha(workspace, db_path)
        changed_files = (
            git_aware.get_changed_files(workspace, since_sha=last_sha)
            if last_sha else []
        )
        changed_count = len(changed_files)
        if 0 < changed_count <= _AUTO_RESCAN_FILE_THRESHOLD:
            from commands.scan import cmd_scan
            cmd_scan(workspace, incremental=True)
            return {
                "was_stale": True,
                "auto_rescanned": True,
                "changed_files_count": changed_count,
            }
        return {
            "was_stale": True,
            "auto_rescanned": False,
            "changed_files_count": changed_count,
            "hint": (
                "Registry may be stale vs current git HEAD "
                f"(>{_AUTO_RESCAN_FILE_THRESHOLD} files changed or "
                "branch switch detected). Run 'scan --incremental' "
                "to refresh before trusting these results."
            ),
        }
    except Exception:
        # Best-effort — never block the actual command on staleness
        # detection failing (e.g. not a git repo, git binary missing).
        return None


# ─── CLI Entry Point ──────────────────────────────────────────

# Formats an agent parses off stdout. For these, a CLI arg error must appear
# on stdout as JSON — not on stderr with an empty stdout, which reads as
# "no results" and silently misleads the agent (issue #315).
_MACHINE_FORMATS = frozenset({
    "json", "compact", "ai", "sarif", "graphml", "junit-xml", "gitlab-sast",
})


def _argv_format(argv):
    """The --format value from a raw argv, or None."""
    for i, a in enumerate(argv):
        if a == "--format" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--format="):
            return a.split("=", 1)[1]
    return None


class _StdoutErrorParser(argparse.ArgumentParser):
    """ArgumentParser that reports arg errors on stdout as JSON for machine
    formats, so an agent can always tell an error from an empty result."""

    def error(self, message):
        if _argv_format(sys.argv) in _MACHINE_FORMATS:
            import json as _json
            print(_json.dumps({
                "s": "error",
                "error": message,
                "error_type": "cli_argument",
                "usage": self.format_usage().strip(),
            }))
            self.exit(2)
        super().error(message)


def main():
    # Command count is derived from the visible (non-hidden) command set at
    # runtime so it can never drift from the actual number of umbrella
    # commands (issue #38). Hidden commands are excluded from the headline
    # count per issue #195 consolidation (78 → 12 focused commands). The 32
    # deprecated aliases introduced by #195 were removed in issue #199; the
    # remaining hidden commands are the 13 pending-decision commands tracked
    # by issue #200.
    # The `--command-count` flag below prints it for scripts / CI; the
    # description also includes it so `--help` is self-documenting.
    from commands import get_visible_commands as _get_visible_commands
    _visible_registry = _get_visible_commands()
    _command_count = len(_visible_registry)

    parser = _StdoutErrorParser(
        description=(
            f"CodeLens v{CODELENS_VERSION} — Live Codebase Reference Intelligence "
            f"(Tree-sitter Edition). {_command_count} commands available; run "
            f"`codelens --command-count` to print just the count."
        )
    )
    # Quick introspection flag — prints the runtime command count and exits.
    # Used by tests / CI / sync_command_count.py to verify the registry size.
    parser.add_argument(
        "--command-count",
        action="store_true",
        default=False,
        help="Print the runtime command count (len of visible COMMAND_REGISTRY) "
             "and exit. Single source of truth for issue #38 reconciliation. "
             "Hidden commands are excluded (issues #195/#199/#200).",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        parser_class=_StdoutErrorParser,
        help="Available commands",
        # Issue #195: the default metavar lists every choice including
        # hidden commands. Override with only the 12 visible umbrella
        # command names so --help is clean. Hidden commands are still
        # dispatchable (intercepted below) but don't clutter the usage line.
        metavar="{" + ",".join(sorted(_visible_registry.keys())) + "}",
    )

    # Import and register all command modules
    registry = get_all_commands()

    # Build subparsers from the command registry.
    # Issue #195: hidden commands are NOT registered as subparsers at all —
    # that way they don't appear in --help choices, body, or usage line. They
    # are still dispatchable via the manual intercept in the dispatch block
    # below (we pre-parse sys.argv[1] and if it matches a hidden command, we
    # build a synthetic namespace and execute directly). The 32 deprecated
    # aliases from #195 were removed in #199; the only hidden commands left
    # are the 13 pending-decision commands tracked by #200.
    _existing_subparser_args = {}
    _hidden_commands = {}
    for cmd_name, cmd_info in sorted(registry.items()):
        _is_hidden = cmd_info.get("hidden", False)
        if _is_hidden:
            # Track for manual dispatch, but don't register a subparser.
            _hidden_commands[cmd_name] = cmd_info
            continue
        sub = subparsers.add_parser(cmd_name, help=cmd_info["help"])
        cmd_info["add_args"](sub)

        # Detect which args the command already defines
        existing_dests = set()
        existing_option_strings = set()
        for action in sub._actions:
            if hasattr(action, 'dest'):
                existing_dests.add(action.dest)
            if hasattr(action, 'option_strings'):
                existing_option_strings.update(action.option_strings)
        _existing_subparser_args[cmd_name] = existing_dests

        # Add --format to each subparser (UNLESS the command defines its own).
        # Issue #64: ``doctor`` defines its own ``--format`` with choices
        # ``["text", "json"]`` because its default human-readable output is
        # a text table, not JSON. Skipping the global add here lets that
        # command-specific format work without an argparse conflict.
        # Issue #59 Phase 3: ``graphml`` emits a GraphML 1.0 XML document for
        # graph-producing commands (scan/trace/impact/circular); other commands
        # produce a single-node placeholder so the format is always valid.
        # Issue #62 Phase 1: ``affected`` command uses ``-f`` for ``--filter``.
        # Avoid the ``-f`` shortcut clash by only adding the global ``-f``
        # shortcut when the command doesn't already claim it. The long form
        # ``--format`` is always safe.
        #
        # Issue #174: This guard is critical. The global parser also registers
        # ``--format/-f`` (see line ~934). Without this guard, subparsers that
        # don't define ``-f`` themselves would get ``-f`` added here, causing
        # ``argparse.ArgumentError: conflicting option string: -f``. PR #153
        # (graphml) accidentally dropped this guard and broke every CLI
        # invocation; commit 23487af restored it. The regression test
        # ``test_no_argparse_f_conflict_regression`` in test_cli.py locks this
        # behavior so it cannot be dropped again.
        if "format" not in existing_dests:
            format_args = ["--format"]
            if "-f" not in existing_option_strings:
                format_args.append("-f")
            sub.add_argument(*format_args, choices=list(_FORMAT_CHOICES), default=None,
                             help="Output format: json, markdown, ai (normalized schema), sarif (GitHub/VS Code), compact (token-efficient single-char keys), graphml (GraphML 1.0 XML for graph-producing commands), text, junit-xml, emacs, vim, or gitlab-sast")

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

        # Add --deep flag for LSP-enhanced hybrid analysis (skip if command already defines --deep)
        if "deep" not in existing_dests:
            sub.add_argument("--deep", action="store_true", default=False,
                             help="Enable LSP-enhanced deep analysis (requires language server)")

        # Add --db-path flag for persistent registry (if command doesn't define it)
        if "db_path" not in existing_dests:
            sub.add_argument("--db-path", default=None, metavar="PATH",
                             help="Custom path for SQLite database file")

        # Issue #157: --diff-base <ref> on every subparser so it works both
        # before and after the subcommand (matches --db-path / --format pattern).
        if "diff_base" not in existing_dests:
            sub.add_argument("--diff-base", default=None, metavar="REF",
                             help="Git ref to diff against — only findings from "
                                  "changed files are reported (issue #157)")

    # Global format option (works before subcommand)
    # Default: "ai" if CODELENS_AI_MODE is set (for AI consumers), else "json"
    _default_format = "ai" if os.environ.get("CODELENS_AI_MODE", "").lower() in ("1", "true", "yes") else "json"
    parser.add_argument("--format", "-f", choices=list(_FORMAT_CHOICES), default=_default_format,
                        help=f"Output format (default: {_default_format}. Set CODELENS_AI_MODE=1 for ai default. compact = token-efficient single-char keys. graphml = GraphML XML for graph-producing commands. Also: text, junit-xml, emacs, vim, gitlab-sast)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for SQLite database (default: .codelens/codelens.db)")
    # Issue #157: --diff-base <ref> restricts analysis to files changed
    # relative to <ref>. Pre-filter layer: commands still scan the full
    # workspace, but findings from unchanged files are filtered out of
    # the result. Empty diff → early exit with a clear message.
    parser.add_argument("--diff-base", default=None, metavar="REF",
                        help="Git ref (branch/tag/SHA/HEAD~1) to diff against. "
                             "Only findings from files changed relative to REF "
                             "are reported. Useful for CI PR checks. (issue #157)")

    # ─── Parse and dispatch ─────────────────────────────

    # Handle --lsp-status as a special top-level flag (not a subcommand)
    if "--lsp-status" in sys.argv:
        try:
            from hybrid_engine import get_lsp_status
            status = get_lsp_status()
            print(format_output(status, _default_format, "lsp-status"))
        except Exception as e:
            print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        sys.exit(0)

    # Handle --command-count as a special top-level flag (issue #38):
    # prints just the runtime command count and exits. Used by tests, CI,
    # and sync_command_count.py to verify the registry size without parsing
    # the full --help output.
    if "--command-count" in sys.argv:
        print(_command_count)
        sys.exit(0)

    # Pre-parse to capture global flags before subparser overwrites them
    global_format = None
    global_top = None
    global_max_tokens = None
    global_lite = False
    global_deep = False
    global_disable_suppression = False
    global_ignore_pattern = None
    global_diff_base = None  # issue #157

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg in ('-f', '--format') and i + 1 < len(sys.argv):
            next_arg = sys.argv[i + 1]
            if next_arg in _FORMAT_CHOICES:
                global_format = next_arg
        elif arg.startswith('-f=') and arg[3:] in _FORMAT_CHOICES:
            global_format = arg[3:]
        elif arg.startswith('--format=') and arg[9:] in _FORMAT_CHOICES:
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
        elif arg == '--deep':
            global_deep = True
        elif arg == '--disable-suppression':
            global_disable_suppression = True
        elif arg == '--codelens-ignore-pattern' and i + 1 < len(sys.argv):
            global_ignore_pattern = sys.argv[i + 1]
        elif arg.startswith('--codelens-ignore-pattern='):
            global_ignore_pattern = arg.split('=', 1)[1]
        # Issue #157: --diff-base <ref> (space form)
        elif arg == '--diff-base' and i + 1 < len(sys.argv):
            global_diff_base = sys.argv[i + 1]
        # Issue #157: --diff-base=<ref> (equals form)
        elif arg.startswith('--diff-base='):
            global_diff_base = arg.split('=', 1)[1]
        i += 1

    # Issue #195/#200: intercept hidden commands BEFORE argparse rejects
    # them as "invalid choice". Hidden commands are not registered as
    # subparsers (so they don't appear in --help), but they remain callable
    # (the 13 pending-decision commands from issue #200). We detect them by
    # scanning sys.argv for the first non-flag token that matches a hidden
    # command name, then build a synthetic namespace and dispatch directly.
    # Issue #199 removed the 32 deprecated aliases, so they are no longer
    # here and now fall through to argparse's "invalid choice" error.
    _hidden_cmd_name = None
    _hidden_cmd_args = None
    if _hidden_commands:
        # Find the first positional token (skip global flags + their values).
        _skip_next_value = False
        _global_value_flags = {
            "--format", "-f", "--top", "--max-tokens", "--db-path",
            "--diff-base", "--codelens-ignore-pattern",
        }
        for _idx, _tok in enumerate(sys.argv[1:], start=1):
            if _skip_next_value:
                _skip_next_value = False
                continue
            if _tok in _global_value_flags:
                _skip_next_value = True
                continue
            if _tok.startswith("-"):
                # Could be --flag=value or -fX; skip either way.
                continue
            # First positional token.
            if _tok in _hidden_commands:
                _hidden_cmd_name = _tok
                # Remaining tokens after the command name are its args.
                _hidden_cmd_args = sys.argv[1 + _idx:]
            break

    if _hidden_cmd_name:
        # Build a synthetic namespace by parsing the hidden command's args
        # with a dedicated parser (not the main parser, which doesn't know
        # this command).
        _h_info = _hidden_commands[_hidden_cmd_name]
        _h_parser = argparse.ArgumentParser(
            prog=f"codelens {_hidden_cmd_name}",
            description=_h_info["help"],
            add_help=True,
        )
        _h_info["add_args"](_h_parser)
        # Add the standard global flags the dispatcher expects.
        if not any(a.dest == "format" for a in _h_parser._actions):
            _h_parser.add_argument("--format", "-f", default=None)
        if not any(a.dest == "top" for a in _h_parser._actions):
            _h_parser.add_argument("--top", type=int, default=None)
        if not any(a.dest == "max_tokens" for a in _h_parser._actions):
            _h_parser.add_argument("--max-tokens", type=int, default=None)
        if not any(a.dest == "lite" for a in _h_parser._actions):
            _h_parser.add_argument("--lite", action="store_true", default=False)
        if not any(a.dest == "deep" for a in _h_parser._actions):
            _h_parser.add_argument("--deep", action="store_true", default=False)
        if not any(a.dest == "db_path" for a in _h_parser._actions):
            _h_parser.add_argument("--db-path", default=None)
        if not any(a.dest == "diff_base" for a in _h_parser._actions):
            _h_parser.add_argument("--diff-base", default=None)
        args = _h_parser.parse_args(_hidden_cmd_args)
        args.command = _hidden_cmd_name
    else:
        args = parser.parse_args()

    # Apply global flags to args
    if getattr(args, 'disable_suppression', None) is None:
        args.disable_suppression = globals().get('global_disable_suppression', False)
    if getattr(args, 'codelens_ignore_pattern', None) is None:
        args.codelens_ignore_pattern = globals().get('global_ignore_pattern', None)

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

    # Resolve --deep: either global or subparser
    if global_deep:
        args.deep = True
    elif not hasattr(args, 'deep') or getattr(args, 'deep', None) is None:
        args.deep = False

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve workspace with auto-detect fallback
    workspace = resolve_workspace(getattr(args, 'workspace', None))
    if workspace != (getattr(args, 'workspace', None) or ""):
        print(f"[CodeLens] Auto-detected workspace: {workspace}", file=sys.stderr)

    # ─── Issue #157: --diff-base <ref> ───────────────────────────
    # Build the DiffScope once, before command execution. If the diff is
    # empty, early-exit with a clear message. The scope is attached to
    # ``args`` so commands that want to do in-engine pre-filtering can
    # access it (none do yet — this is a post-filter layer for now).
    diff_scope = None
    # Resolve --diff-base: global pre-parse value or subparser value.
    # argparse stores --diff-base as ``diff_base`` on the subparser too,
    # but since it's a global flag, the pre-parse value is authoritative.
    diff_base_ref = global_diff_base or getattr(args, 'diff_base', None)
    if diff_base_ref:
        from diff_scope import DiffScope, DiffScopeError
        try:
            diff_scope = DiffScope.from_ref(workspace, diff_base_ref)
        except DiffScopeError as exc:
            error_result = {
                "status": "error",
                "command": args.command,
                "error": str(exc),
                "error_type": "diff_scope_error",
                "suggestion": (
                    "Ensure the workspace is a git repository and the ref "
                    "exists. Use `git rev-parse --verify <ref>` to check."
                ),
            }
            print(format_output(error_result, args.format, args.command), file=sys.stderr)
            sys.exit(1)
        if diff_scope.is_empty:
            # Empty diff → early exit per issue #157 DoD
            empty_result = {
                "status": "ok",
                "command": args.command,
                "message": f"No changed files relative to {diff_base_ref!r}",
                "diff_scope": diff_scope.summary(),
                "stats": {},
                "findings": [],
            }
            print(format_output(empty_result, args.format, args.command, workspace))
            sys.exit(0)
        # Attach to args so commands can opt-in to in-engine pre-filtering
        args.diff_scope = diff_scope
        print(
            f"[CodeLens] --diff-base {diff_base_ref!r}: {diff_scope.changed_count} "
            f"file(s) in scope",
            file=sys.stderr,
        )

    # ─── Auto-setup: if command needs registry and none exists, bootstrap it ────
    # The 11 registry-consuming umbrellas (all except `scan`, which BUILDS it) plus
    # the hidden leaf commands that read the registry directly (list/query/symbols).
    # NOTE: keep this an explicit allowlist, NOT "every command except a few" — an
    # over-broad gate makes EVERY command invocation auto-scan its workspace, which
    # ballooned the test suite from ~164s to hours (each command-test scanning its
    # fixture). #244 needed the umbrellas added; it did not need the whole hidden
    # surface (check/analyze/entrypoints/...) to trigger scans.
    _REGISTRY_COMMANDS = {
        "search", "context", "deps", "audit", "security",
        "summary", "impact", "api-map", "doctor", "history", "graph",
        "list", "query", "symbols",
    }

    auto_setup_info = None
    if args.command in _REGISTRY_COMMANDS and not _registry_exists(workspace):
        auto_setup_result = _auto_setup(workspace)
        if auto_setup_result.get("auto_setup") == "ok":
            auto_setup_info = {
                "auto_setup": True,
                "message": "Registry was auto-built. For best results, run 'scan' manually on large repos.",
                # Issue #34: surface which path produced the registry and
                # whether the 3000-file cap was hit, so MCP clients / agents
                # can decide whether to trust the registry or re-scan.
                "capped": bool(auto_setup_result.get("capped", False)),
                "fallback": bool(auto_setup_result.get("fallback", False)),
            }
        else:
            auto_setup_info = {
                "auto_setup": "failed",
                "message": f"Auto-setup failed at {auto_setup_result.get('stage')}: {auto_setup_result.get('error')}",
            }

    staleness_info = _check_staleness(workspace, args)

    try:
        cmd_info = registry[args.command]

        result = cmd_info["execute"](args, workspace)

        if staleness_info and isinstance(result, dict):
            result["_staleness"] = staleness_info

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
            # Auto-save history snapshot for trend tracking
            try:
                from history_engine import save_snapshot as save_history_snapshot
                hist_result = save_history_snapshot(workspace, result)
                result["history_snapshot_saved"] = True
                result["history_snapshot_file"] = hist_result.get("_snapshot_file", "")
            except Exception:
                logger.debug("Failed to save history snapshot", exc_info=True)
                result["history_snapshot_saved"] = False

        # ─── Watch/Serve are long-running commands — they already printed output ──
        if args.command in ("watch", "serve"):
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

        # ─── Post-processing: --max-tokens N ──
        max_tokens = getattr(args, 'max_tokens', None)
        if max_tokens and isinstance(result, dict):
            result = _apply_max_tokens(result, max_tokens)

        # ─── Add auto-setup info if applicable ──
        if auto_setup_info and isinstance(result, dict):
            result["_auto_setup"] = auto_setup_info

        # ─── Post-processing: --deep (hybrid LSP analysis) ──
        # Single consolidated block (issue #32: previously two duplicate blocks
        # ran in sequence, double-instantiating HybridEngine and overwriting
        # deep_analysis/lsp_active fields. Block 1 used HybridEngine() directly;
        # Block 2 used create_hybrid_engine() + add_confidence_to_result().
        # Block 2 is strictly more capable (handles complexity, adds confidence
        # distribution), so Block 1 was deleted and the "unsupported command"
        # hint was folded into the else branch below.)
        deep = getattr(args, 'deep', False)
        # Issue #199: the --deep supported list used the old alias command
        # names (smell, dead-code, complexity). After #199 these are reached
        # via the ``audit`` umbrella with ``--check <category>``. Map the
        # umbrella+check combination back to the alias name so the existing
        # enhancement logic keeps working.
        _DEEP_SUPPORTED_ALIASES = ("dead-code", "query", "impact", "smell", "complexity")
        _AUDIT_DEEP_CHECK_MAP = {
            "dead-code": "dead-code",
            "smell": "smell",
            "complexity": "complexity",
        }
        _deep_effective_command = args.command
        if args.command == "audit" and getattr(args, "check", None):
            _check_first = str(args.check).split(",")[0].strip()
            _deep_effective_command = _AUDIT_DEEP_CHECK_MAP.get(_check_first, args.command)
        if deep and isinstance(result, dict) and _deep_effective_command in _DEEP_SUPPORTED_ALIASES:
            try:
                from hybrid_engine import create_hybrid_engine, add_confidence_to_result
                hybrid = create_hybrid_engine(workspace, deep=True)

                # Issue #199: umbrella commands wrap sub-results under
                # result["r"][i]["_check"] == <check_name>. Find the sub-result
                # matching _deep_effective_command so the enhancement targets
                # the right dict. Non-umbrella commands use the top-level result.
                _deep_target = result
                if isinstance(result.get("r"), list):
                    for _sub in result["r"]:
                        if isinstance(_sub, dict) and _sub.get("_check") == _deep_effective_command:
                            _deep_target = _sub
                            break

                if _deep_effective_command == "dead-code":
                    # Enhance dead-code findings with LSP verification
                    all_findings = []
                    for cat_items in _deep_target.get("results", {}).values():
                        if isinstance(cat_items, list):
                            all_findings.extend(cat_items)
                    if all_findings:
                        verified = hybrid.verify_dead_code(all_findings)
                        _deep_target["lsp_verified"] = True
                        _deep_target["lsp_active"] = hybrid.lsp_active

                elif _deep_effective_command == "query" and _deep_target.get("found"):
                    _deep_target = hybrid.enhance_query(_deep_target, _deep_target.get("query", ""))
                    _deep_target["lsp_active"] = hybrid.lsp_active

                elif _deep_effective_command == "impact":
                    _deep_target = hybrid.enhance_impact(_deep_target, _deep_target.get("symbol", ""))
                    _deep_target["lsp_active"] = hybrid.lsp_active

                elif _deep_effective_command == "smell":
                    all_findings = []
                    for cat_items in _deep_target.get("by_category", {}).values():
                        if isinstance(cat_items, list):
                            all_findings.extend(cat_items)
                    if all_findings:
                        hybrid.enhance_smell(all_findings)
                    _deep_target["lsp_active"] = hybrid.lsp_active

                elif _deep_effective_command == "complexity":
                    funcs = _deep_target.get("functions", [])
                    if funcs:
                        hybrid.enhance_complexity(funcs)
                    _deep_target["lsp_active"] = hybrid.lsp_active

                # Add confidence distribution to stats
                result = add_confidence_to_result(result)
                hybrid.cleanup()

            except Exception as e:
                logger.warning(f"Deep analysis failed, using fast-path results: {e}", exc_info=True)
                if isinstance(result, dict):
                    result["lsp_active"] = False
                    result["deep_error"] = str(e)
        elif deep and isinstance(result, dict):
            # --deep set but command not in the supported list — surface a hint
            # so the user knows --deep was a no-op for this command. (Folded in
            # from deleted Block 1 — see issue #32.)
            result["deep_analysis"] = False
            result["deep_analysis_hint"] = f"--deep not yet supported for {args.command}"
        elif not deep and isinstance(result, dict) and _deep_effective_command in _DEEP_SUPPORTED_ALIASES:
            # Auto-detect: if LSP available and --deep not specified, show hint
            try:
                from hybrid_engine import get_lsp_status
                status = get_lsp_status()
                if status.get("lsp_available"):
                    print(
                        f"[CodeLens] Hint: LSP servers detected ({status['available_count']} available). "
                        f"Use --deep for higher accuracy analysis.",
                        file=sys.stderr,
                    )
            except Exception:
                pass

        # ─── Determine command name for formatting ──
        format_command = args.command
        if args.command == "ask" and isinstance(result, dict):
            format_command = result.get("query_interpretation", {}).get("interpreted_as", "ask")

        # ─── Apply inline suppressions ──
        if not getattr(args, 'disable_suppression', False) and isinstance(result, dict):
            try:
                from suppression import apply_suppressions, update_stats_with_suppressions, DEFAULT_KEYWORD_PATTERN

                keyword_pattern = getattr(args, 'codelens_ignore_pattern', None) or DEFAULT_KEYWORD_PATTERN

                # Collect source files from the result
                source_files = {}
                finding_keys = ("findings", "leaks", "hints", "issues", "violations", "matches", "chains")
                for key in finding_keys:
                    val = result.get(key)
                    if isinstance(val, list):
                        for f in val:
                            if isinstance(f, dict):
                                fp = f.get("file") or f.get("defined_in") or ""
                                if fp and fp not in source_files:
                                    try:
                                        with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                                            source_files[fp] = fh.read()
                                    except (IOError, OSError):
                                        pass
                    elif isinstance(val, dict):
                        for sub_val in val.values():
                            if isinstance(sub_val, list):
                                for f in sub_val:
                                    if isinstance(f, dict):
                                        fp = f.get("file") or f.get("defined_in") or ""
                                        if fp and fp not in source_files:
                                            try:
                                                with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
                                                    source_files[fp] = fh.read()
                                            except (IOError, OSError):
                                                pass

                if source_files:
                    # Collect all findings from result
                    all_findings = []
                    for key in finding_keys:
                        val = result.get(key)
                        if isinstance(val, list):
                            all_findings.extend(val)
                        elif isinstance(val, dict):
                            for sub_val in val.values():
                                if isinstance(sub_val, list):
                                    all_findings.extend(sub_val)

                    if all_findings:
                        apply_suppressions(all_findings, source_files, keyword_pattern=keyword_pattern)
                        update_stats_with_suppressions(result)

            except ImportError:
                pass  # suppression module not available
            except Exception as e:
                logger.warning(f"Suppression processing failed: {e}", exc_info=True)

        # ─── Issue #157: --diff-base post-filter ──
        # Drop findings from files not in the changed-file allowlist. This
        # is a post-filter layer — commands still scan the full workspace,
        # but findings from unchanged files are removed before output.
        # Commands that produce graph data (trace, impact, circular, scan)
        # are NOT filtered because their results are structural (node/edge
        # graphs) rather than file-keyed findings — filtering them would
        # silently corrupt the graph.
        #
        # Issue #199: the old alias command names (secrets, smell, dead-code,
        # etc.) were removed from the CLI; the same analyses are now reached
        # via the 12 umbrella commands (security, audit, etc.) with a
        # ``--check <category>`` flag. The post-filter now also runs for the
        # umbrella commands — when the result has the umbrella shape
        # (``{"s":..., "st":..., "r":[...]}``), each sub-result in ``r`` is
        # filtered individually and the ``diff_scope`` summary is attached
        # at the top level so consumers see what was filtered.
        _DIFF_BASE_FILTERABLE_UMBRELLAS = {
            "security", "audit", "impact", "context", "deps",
        }
        _is_filterable_command = args.command in (
            "secrets", "smell", "complexity", "dead-code", "debug-leak",
            "circular", "taint", "vuln-scan", "check", "analyze",
            "missing-refs", "side-effect", "perf-hint", "regex-audit",
            "a11y", "css-deep", "dataflow", "stack-trace", "config-drift",
            "ownership", "test-map",
        ) or args.command in _DIFF_BASE_FILTERABLE_UMBRELLAS
        if diff_scope is not None and isinstance(result, dict) and _is_filterable_command:
            _FILTER_KEYS = (
                "findings", "leaks", "hints", "issues", "violations",
                "matches", "chains", "results",
            )

            def _filter_one(sub_result):
                """Filter findings in a single sub-result dict; return (before, after)."""
                nonlocal total_before, total_after
                if not isinstance(sub_result, dict):
                    return
                for key in _FILTER_KEYS:
                    val = sub_result.get(key)
                    if isinstance(val, list):
                        before = len(val)
                        sub_result[key] = diff_scope.filter_findings(val)
                        total_before += before
                        total_after += len(sub_result[key])
                    elif isinstance(val, dict):
                        # Category-keyed (dead-code by_category, smell by_category)
                        for sub_key, sub_val in val.items():
                            if isinstance(sub_val, list):
                                before = len(sub_val)
                                val[sub_key] = diff_scope.filter_findings(sub_val)
                                total_before += before
                                total_after += len(val[sub_key])

            total_before = 0
            total_after = 0
            # Issue #199: umbrella commands return {"s":..., "st":..., "r":[...]}.
            # Filter each sub-result in ``r`` so the post-filter respects the
            # umbrella structure. Non-umbrella commands are filtered at the
            # top level (the original pre-#199 behavior).
            if "r" in result and isinstance(result["r"], list):
                for sub_result in result["r"]:
                    _filter_one(sub_result)
            else:
                _filter_one(result)
            # Attach diff_scope summary so consumers can see what was filtered
            result["diff_scope"] = diff_scope.summary()
            result["diff_scope"]["findings_before_filter"] = total_before
            result["diff_scope"]["findings_after_filter"] = total_after
            if total_before != total_after:
                print(
                    f"[CodeLens] --diff-base: {total_before - total_after} "
                    f"finding(s) from unchanged files filtered out",
                    file=sys.stderr,
                )

        # ─── Format and print output ──
        # Some commands (doctor issue #64 Phase 1, sessions issue #64
        # Phase 2) print their own human-readable output directly and
        # signal via ``_doctor_printed_text`` / ``_sessions_printed_text``
        # so the dispatcher skips the generic JSON formatter (which
        # would otherwise dump the result dict a second time). In
        # ``--format json`` mode these commands do NOT print themselves,
        # and the normal formatter handles the JSON serialization.
        _already_printed = (
            isinstance(result, dict)
            and (result.get("_doctor_printed_text") or result.get("_sessions_printed_text") or result.get("_orient_printed_text"))
        )
        if not (args.command in ("doctor", "sessions", "orient") and _already_printed):
            print(format_output(result, args.format, format_command, workspace))

        # ─── Exit codes for CI-quality-gate commands ──
        if args.command == "check" and isinstance(result, dict):
            if result.get("gate") == "failed":
                sys.exit(1)
        # doctor (issue #64): exit 0=ok / 1=warning / 2=critical.
        # The exit code lets CI pipelines gate on doctor failures.
        if args.command == "doctor" and isinstance(result, dict):
            exit_code = result.get("exit_code", 0)
            if exit_code:
                sys.exit(exit_code)

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
    # Issue #54 Phase 1: ``python3 scripts/codelens.py`` is the legacy
    # invocation. After ``pip install codelens`` the ``codelens`` console
    # script (or ``python -m codelens``) is preferred. This legacy entry
    # point remains fully supported — the warning is informational only.
    import warnings as _w
    _w.warn(
        "Running codelens via 'python3 scripts/codelens.py' is the legacy "
        "mode. For a better experience, 'pip install codelens' and use the "
        "'codelens' command directly (issue #54 Phase 1). This legacy mode "
        "will continue to work.",
        DeprecationWarning,
        stacklevel=1,
    )
    main()
