"""security command — vulnerability & secret scanning (issue #195 consolidation).

Umbrella command that absorbs:
  - secrets       Hardcoded secrets and API keys
  - vuln-scan     Dependency CVE scan (OSV.dev + native audit)
  - taint         AST-based taint analysis
  - binary-scan   Binary/compiled artifact reverse-engineering
  - regex-audit   Regex ReDoS and issue audit
  - deps-audit    Dependency vulnerability scan via OSV.dev (issue #200)

Usage:
    codelens security <workspace>                          # all checks
    codelens security <workspace> --check secrets          # only secrets
    codelens security <workspace> --check taint,vuln-scan  # pick subset
    codelens security <workspace> --check binary-scan --deep
    codelens security <workspace> --check deps-audit --offline

Output: ``{"s":"ok", "st":{...}, "r":[...]}``.
"""

# @WHO:   scripts/commands/security.py
# @WHAT:  Umbrella command for security/vulnerability scans.
# @PART:  commands
# @ENTRY: execute()

import argparse
import importlib
import sys
from typing import Any, Dict, List

from commands import register_command


_CHECKS = {
    "secrets": {
        "module": "commands.secrets",
        "help": "Hardcoded secrets and API keys",
    },
    "vuln-scan": {
        "module": "commands.vuln_scan",
        "help": "Dependency CVE scan (OSV.dev + native audit)",
    },
    "taint": {
        "module": "commands.taint",
        "help": "AST-based taint analysis",
    },
    "binary-scan": {
        "module": "commands.binary_scan",
        "help": "Binary/compiled artifact reverse-engineering",
    },
    "regex-audit": {
        "module": "commands.regex_audit",
        "help": "Regex ReDoS and issue audit",
    },
    # Issue #200: absorb the hidden-pending OSV.dev dependency audit.
    "deps-audit": {
        "module": "commands.deps_audit",
        "help": "Dependency vulnerability scan via OSV.dev (PyPI/npm/crates.io)",
    },
}

ALL_CHECKS = list(_CHECKS.keys())


def add_args(parser):
    """Add security-specific arguments to the parser."""
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.epilog = (
        "Sub-analyses (issue #195):\n"
        "  secrets       Hardcoded secrets and API keys\n"
        "  vuln-scan     Dependency CVE scan (OSV.dev + native audit)\n"
        "  taint         AST-based taint analysis\n"
        "  binary-scan   Binary/compiled artifact reverse-engineering\n"
        "  regex-audit   Regex ReDoS and issue audit\n"
        "  deps-audit    Dependency vulnerability scan via OSV.dev (issue #200)\n"
        "\n"
        "Examples:\n"
        "  codelens security .                            # all checks\n"
        "  codelens security . --check secrets            # only secrets\n"
        "  codelens security . --check taint,vuln-scan    # pick subset\n"
        "  codelens security . --check binary-scan --deep # deep binary scan\n"
        "  codelens security . --check deps-audit         # dependency CVEs\n"
    )
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--check", default=None,
                        help=f"Comma-separated sub-analyses. "
                             f"Choices: {', '.join(ALL_CHECKS)}. Default: all.")
    # Common passthroughs.
    parser.add_argument("--max-files", type=int, default=None,
                        help="secrets/regex-audit: file cap")
    parser.add_argument("--severity", default=None,
                        help="secrets/vuln-scan/regex-audit/taint: severity filter")
    parser.add_argument("--no-gitleaks", action="store_true", default=False,
                        help="secrets: force regex fallback (skip gitleaks)")
    parser.add_argument("--language", default=None,
                        help="taint: python|javascript|typescript")
    parser.add_argument("--with-secrets", action="store_true", default=False,
                        help="taint: include secret-leak findings")
    parser.add_argument("--cross-file", action="store_true", default=False,
                        help="taint: enable cross-file analysis")
    parser.add_argument("--no-ast", action="store_true", default=False,
                        help="taint: use semantic engine instead of AST")
    parser.add_argument("--ast", action="store_true", default=False,
                        help="taint: force AST engine")
    parser.add_argument("--deep", action="store_true", default=False,
                        help="binary-scan: parse source maps + extract WASM exports/imports")
    parser.add_argument("--offline", action="store_true", default=False,
                        help="vuln-scan: skip OSV API calls, use cached results")
    parser.add_argument("--refresh", action="store_true", default=False,
                        help="vuln-scan: force-refresh the OSV cache")
    parser.add_argument("--osv-ttl", type=int, default=None,
                        help="vuln-scan: OSV cache TTL in seconds")
    parser.add_argument("--max-age", default=None,
                        help="vuln-scan: max cache age (e.g. 6h, 30m, 2d)")
    # deps-audit passthroughs (issue #200).
    parser.add_argument("--ecosystem", default=None,
                        choices=["PyPI", "npm", "crates.io"],
                        help="deps-audit: limit scan to one package ecosystem")


def _parse_checks(check_arg: str) -> List[str]:
    if not check_arg:
        return list(ALL_CHECKS)
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _CHECKS]
    if invalid:
        print(
            f"[CodeLens] security: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(ALL_CHECKS)}",
            file=sys.stderr,
        )
        sys.exit(1)
    return parts or list(ALL_CHECKS)


def _build_namespace(base_args, check_name: str) -> argparse.Namespace:
    ns = argparse.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "secrets":
        ns.severity = getattr(base_args, "severity", None)
        ns.max_files = getattr(base_args, "max_files", None) or 5000
        ns.no_gitleaks = getattr(base_args, "no_gitleaks", False)
    elif check_name == "vuln-scan":
        ns.severity = getattr(base_args, "severity", None)
        ns.offline = getattr(base_args, "offline", False)
        ns.osv_ttl = getattr(base_args, "osv_ttl", None) or 86400
        ns.refresh = getattr(base_args, "refresh", False)
        ns.max_age = getattr(base_args, "max_age", None)
    elif check_name == "taint":
        ns.language = getattr(base_args, "language", None)
        ns.with_secrets = getattr(base_args, "with_secrets", False)
        ns.severity = getattr(base_args, "severity", None)
        ns.cross_file = getattr(base_args, "cross_file", False)
        ns.no_ast = getattr(base_args, "no_ast", False)
        ns.ast = getattr(base_args, "ast", False)
    elif check_name == "binary-scan":
        # binary-scan reads args.deep via getattr default False, so carry it.
        ns.deep = getattr(base_args, "deep", False)
    elif check_name == "regex-audit":
        ns.severity = getattr(base_args, "severity", None)
        ns.max_files = getattr(base_args, "max_files", None) or 1000
    elif check_name == "deps-audit":
        # Issue #200: deps_audit.execute() reads severity/ecosystem/offline.
        ns.severity = getattr(base_args, "severity", None)
        ns.ecosystem = getattr(base_args, "ecosystem", None)
        ns.offline = getattr(base_args, "offline", False)
    return ns


def execute(args, workspace):
    """Run one or more security checks and merge results.

    @FLOW:    SECURITY_DISPATCH
    @CALLS:   _parse_checks() -> List[str]
              _build_namespace() -> argparse.Namespace
              commands.<sub>.execute() -> dict per sub
    @MUTATES: OSV cache (vuln-scan may refresh it)
    """
    checks = _parse_checks(getattr(args, "check", None))
    results: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"checks_run": 0, "checks_failed": 0}

    for check_name in checks:
        spec = _CHECKS[check_name]
        try:
            mod = importlib.import_module(spec["module"])
            sub_args = _build_namespace(args, check_name)
            sub_result = mod.execute(sub_args, workspace)
            if not isinstance(sub_result, dict):
                sub_result = {"status": "ok", "result": sub_result}
            sub_result["_check"] = check_name
            results.append(sub_result)
            stats["checks_run"] += 1
        except Exception as exc:
            stats["checks_failed"] += 1
            stats["checks_run"] += 1
            results.append({
                "_check": check_name,
                "s": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            print(
                f"[CodeLens] security: --check {check_name} failed: {exc}",
                file=sys.stderr,
            )

    return {
        "s": "ok" if stats["checks_failed"] == 0 else "partial",
        "st": {
            "checks_requested": len(checks),
            **stats,
        },
        "r": results,
    }


register_command(
    "security",
    "Security scans: secrets / vuln-scan / taint / binary-scan / regex-audit",
    add_args,
    execute,
)
