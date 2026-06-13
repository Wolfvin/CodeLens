"""Vuln-scan command — Scan dependencies for known CVEs using OSV.dev + native audit tools."""

from vulnscan_engine import scan_vulnerabilities
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity (includes higher)")
    parser.add_argument("--offline", action="store_true", default=False,
                        help="Skip OSV.dev API queries (use cached data only)")
    parser.add_argument("--osv-ttl", type=int, default=86400,
                        help="OSV cache TTL in seconds (default: 86400 = 24h)")


def execute(args, workspace):
    return scan_vulnerabilities(
        workspace,
        severity=args.severity,
        offline=args.offline,
        osv_ttl=args.osv_ttl,
    )


register_command("vuln-scan", "Scan dependencies for known CVEs (OSV.dev + native audit)", add_args, execute)
