"""Vuln-scan command — Scan dependencies for known CVEs using OSV.dev + native audit tools."""

import re

from vulnscan_engine import scan_vulnerabilities
from commands import register_command


# --max-age accepts a duration string like "6h", "30m", "2d", or a bare
# integer (interpreted as hours). Returns the value in seconds.
_MAX_AGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([hmsd]?)\s*$", re.IGNORECASE)
_MAX_AGE_UNITS = {
    "": 3600,    # bare number → hours (matches --osv-ttl semantics)
    "h": 3600,
    "m": 60,
    "s": 1,
    "d": 86400,
}


def _parse_max_age(raw):
    """Parse a --max-age duration string into seconds.

    Accepts forms like ``6h`` (6 hours), ``30m`` (30 minutes), ``2d``
    (2 days), ``90s`` (90 seconds), or a bare integer (interpreted as
    hours, matching ``--osv-ttl`` semantics).

    Args:
        raw: The raw string from argparse. May be None.

    Returns:
        int number of seconds, or None if ``raw`` is None.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    if raw is None:
        return None
    match = _MAX_AGE_RE.match(str(raw))
    if match is None:
        raise ValueError(
            f"invalid --max-age value {raw!r} — expected forms like "
            f"'6h', '30m', '2d', '90s', or a bare integer (hours)"
        )
    value = float(match.group(1))
    unit = match.group(2).lower()
    seconds = int(value * _MAX_AGE_UNITS[unit])
    if seconds <= 0:
        raise ValueError(f"--max-age must be positive, got {raw!r}")
    return seconds


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity (includes higher)")
    parser.add_argument("--offline", action="store_true", default=False,
                        help="Skip OSV.dev API queries (use cached data only)")
    parser.add_argument("--osv-ttl", type=int, default=86400,
                        help="OSV cache TTL in seconds (default: 86400 = 24h)")
    parser.add_argument("--refresh", action="store_true", default=False,
                        help="Bypass OSV cache and force fresh API calls for every "
                             "package (issue #30). Updates the cache with new results. "
                             "Ignored in --offline mode.")
    parser.add_argument("--max-age", dest="max_age", default=None,
                        help="Treat OSV cache entries older than this as stale for "
                             "this run only (issue #30). Examples: '6h' (6 hours), "
                             "'30m' (30 minutes), '2d' (2 days), '90s' (90 seconds), "
                             "or a bare integer (interpreted as hours). Overrides the "
                             "default 24h TTL for this run; does not change stored TTL.")


def execute(args, workspace):
    try:
        max_age_seconds = _parse_max_age(getattr(args, "max_age", None))
    except ValueError as exc:
        return {
            "status": "error",
            "error": "invalid_argument",
            "message": str(exc),
        }
    return scan_vulnerabilities(
        workspace,
        severity=args.severity,
        offline=args.offline,
        osv_ttl=args.osv_ttl,
        refresh=args.refresh,
        max_age=max_age_seconds,
    )


register_command("vuln-scan", "Scan dependencies for known CVEs (OSV.dev + native audit)", add_args, execute,

hidden=True,

deprecated_alias_for='security',

)
