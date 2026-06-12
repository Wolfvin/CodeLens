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
    python3 codelens.py config-drift <workspace>       # Dependency drift detection
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
    python3 codelens.py css-deep <workspace>           # Deep CSS analysis (vars, keyframes, specificity)
    python3 codelens.py handbook <workspace>           # Generate project handbook for AI agents
    python3 codelens.py ask <question> [workspace]     # Ask a natural language question about the codebase
"""

import sys
import os
import argparse
from typing import Optional

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

    detected = _detect_workspace()
    if detected:
        _save_last_workspace(detected)
        return detected

    return os.getcwd()


# ─── CLI Entry Point ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"CodeLens v{CODELENS_VERSION} — Live Codebase Reference Intelligence (Tree-sitter Edition)"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Import and register all command modules
    registry = get_all_commands()

    # Build subparsers from the command registry
    for cmd_name, cmd_info in sorted(registry.items()):
        sub = subparsers.add_parser(cmd_name, help=cmd_info["help"])
        cmd_info["add_args"](sub)
        # Add --format to each subparser so it works AFTER the subcommand
        # e.g. "codelens.py scan -f markdown" works in addition to
        # "codelens.py -f markdown scan"
        sub.add_argument("--format", "-f", choices=["json", "markdown"], default=None,
                         help="Output format (overrides global --format)")

    # Global format option (works before subcommand)
    parser.add_argument("--format", "-f", choices=["json", "markdown"], default="json",
                        help="Output format (default: json)")

    # ─── Parse and dispatch ─────────────────────────────

    # Pre-parse to capture global --format before subparser overwrites it
    # This handles: codelens -f markdown scan
    global_format = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg in ('-f', '--format') and i + 1 < len(sys.argv):
            next_arg = sys.argv[i + 1]
            if next_arg in ('json', 'markdown'):
                global_format = next_arg
        elif arg.startswith('-f=') and arg[3:] in ('json', 'markdown'):
            global_format = arg[3:]
        elif arg.startswith('--format=') and arg[9:] in ('json', 'markdown'):
            global_format = arg[9:]

    args = parser.parse_args()

    # Resolve format: subparser --format overrides global --format
    # When both are specified, the subparser one wins (more specific).
    # When --format is placed after the subcommand, argparse sets both
    # the global and subparser format attributes. We need to detect this.
    # The subparser's --format has default=None so we can tell if it was set.
    subparser_format = getattr(args, 'format', None)
    if subparser_format is not None:
        args.format = subparser_format
    elif global_format is not None:
        # Global --format was set before subcommand but subparser overwrote it
        args.format = global_format

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve workspace with auto-detect fallback
    workspace = resolve_workspace(getattr(args, 'workspace', None))
    if workspace != (getattr(args, 'workspace', None) or ""):
        print(f"[CodeLens] Auto-detected workspace: {workspace}", file=sys.stderr)

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
                # write_output_files returns {} on failure, or a dict with data on success
                result["outline_generated"] = bool(summary)
            except Exception:
                logger.warning("Failed to write output files", exc_info=True)
                result["outline_generated"] = False

        # ─── Watch is a long-running command — it already printed output ──
        if args.command == "watch":
            return

        # ─── Determine command name for markdown formatting ──
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
