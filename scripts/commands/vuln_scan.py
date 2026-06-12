"""Vuln-scan command — Scan dependencies for known CVEs."""

from vulnscan_engine import scan_vulnerabilities
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity (includes higher)")


def execute(args, workspace):
    return scan_vulnerabilities(workspace, severity=args.severity)


register_command("vuln-scan", "Scan dependencies for known CVEs", add_args, execute)
