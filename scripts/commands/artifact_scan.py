"""Artifact-scan command — DEPRECATED alias for binary-scan (issue #98).

The ``artifact-scan`` command has been merged into ``binary-scan``.
``binary-scan`` is now a strict superset: it performs everything this
command used to do (minified-file detection, source-map parsing, WASM deep
analysis, built-output-directory detection) plus the additional
capabilities that were always unique to ``binary-scan`` (MIME-signature
detection for extensionless binaries, Tauri/Electron analysis hook).

This module remains so existing scripts, MCP clients, and muscle memory
keep working. Invoking ``codelens artifact-scan`` prints a deprecation
warning to stderr and then delegates to ``binary-scan``'s handler with the
same arguments, so the output is identical to what ``binary-scan`` now
produces.

Migration path:
    codelens artifact-scan [workspace] [--deep]
    →
    codelens binary-scan  [workspace] [--deep]
"""

import sys

from commands import register_command


def add_args(parser):
    """Add artifact-scan-specific arguments.

    Kept identical to binary-scan's args so delegation is transparent:
    ``workspace`` (positional, optional) and ``--deep``.
    """
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--deep", action="store_true",
                        help="Deep scan: parse source maps and extract WASM exports")


def execute(args, workspace):
    """Deprecated: print warning, then delegate to binary-scan's handler.

    The delegation calls ``binary_scan.execute`` directly (same args
    namespace) so the output is exactly what ``binary-scan`` produces —
    no capability is lost.
    """
    print("DEPRECATED: Use binary-scan instead", file=sys.stderr)
    from commands import binary_scan
    return binary_scan.execute(args, workspace)


register_command(
    "artifact-scan",
    "DEPRECATED: use binary-scan instead — Scan for compiled/built artifacts (reverse engineering mode)",
    add_args,
    execute,
)
