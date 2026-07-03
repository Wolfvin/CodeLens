"""Secrets command — Detect hardcoded secrets and API keys.

Issue #159: When gitleaks is installed, use it as the primary backend
(600+ maintained rules, entropy scoring). Fall back to the built-in
regex scanner when gitleaks is unavailable or ``--no-gitleaks`` is set.
"""

import sys

from secrets_engine import detect_secrets
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000)")
    # Issue #159: force regex backend even if gitleaks is available.
    # Useful for testing, offline environments, or when gitleaks produces
    # unexpected results.
    parser.add_argument("--no-gitleaks", action="store_true", default=False,
                        help="Force the built-in regex scanner even if "
                             "gitleaks is available (issue #159)")


def execute(args, workspace):
    """Run the secrets scan, preferring gitleaks when available.

    @FLOW:    SECRETS_SCAN
    @CALLS:   gitleaks_backend.scan_with_gitleaks() -> result | None
    @CALLS:   secrets_engine.detect_secrets() -> result (fallback)
    @MUTATES: none (read-only scan; gitleaks writes only to temp file)
    """
    # Issue #159: try gitleaks first unless --no-gitleaks
    use_gitleaks = not getattr(args, "no_gitleaks", False)
    if use_gitleaks:
        try:
            from gitleaks_backend import scan_with_gitleaks, _gitleaks_available
        except ImportError:
            # gitleaks_backend module unavailable — fall through to regex
            use_gitleaks = False
        else:
            if _gitleaks_available():
                try:
                    result = scan_with_gitleaks(
                        workspace,
                        severity=args.severity,
                    )
                except Exception as exc:
                    # Gitleaks failed — fall back to regex with a warning.
                    # Never crash the command; gitleaks is opt-in.
                    print(
                        f"[CodeLens] gitleaks backend failed: {exc}. "
                        f"Falling back to regex scanner.",
                        file=sys.stderr,
                    )
                    result = None
                if result is not None:
                    return result
                # result is None → gitleaks not available, fall through
            # else: gitleaks not installed, fall through to regex

    # Regex backend (existing behavior)
    result = detect_secrets(
        workspace,
        severity=args.severity,
        max_files=args.max_files,
    )
    # Tag the backend so consumers can tell which scanner ran
    if isinstance(result, dict):
        result["backend"] = "regex"
        if use_gitleaks:
            # We tried gitleaks but it wasn't available — surface install hint
            result["gitleaks_hint"] = (
                "gitleaks not found — using built-in regex scanner (lower "
                "accuracy). Install gitleaks for 600+ maintained rules and "
                "entropy scoring: https://github.com/gitleaks/gitleaks"
            )
            # Surface in stats too so compact/ai formatters pick it up
            stats = result.get("stats")
            if isinstance(stats, dict):
                stats["backend"] = "regex"
    return result


register_command("secrets", "Detect hardcoded secrets and API keys", add_args, execute)
