# @WHO:   scripts/commands/deps_audit.py
# @WHAT:  deps-audit CLI command — dependency vulnerability scan via OSV.dev
# @PART:  commands
# @ENTRY: execute()
"""Deps-audit command — Scan dependencies for known CVEs via OSV.dev API."""

from dep_audit_engine import audit_dependencies
from commands import register_command


def add_args(parser):
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--severity",
        choices=["critical", "high", "medium", "low"],
        default=None,
        help="Filter by severity (includes higher severities)",
    )
    parser.add_argument(
        "--ecosystem",
        choices=["PyPI", "npm", "crates.io"],
        default=None,
        help="Limit scan to one package ecosystem",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        default=False,
        help="Skip OSV API queries (report packages only, no findings)",
    )


def execute(args, workspace):
    return audit_dependencies(
        workspace,
        severity=args.severity,
        ecosystem=args.ecosystem,
        offline=args.offline,
    )


register_command(
    "deps-audit",
    "Scan dependencies for known CVEs via OSV.dev (PyPI/npm/crates.io)",
    add_args,
    execute,
)
