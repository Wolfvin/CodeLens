"""LSP command — launch the native CodeLens LSP 3.17 server.

Issue #48 (Phase 1): exposes CodeLens analysis (tree-sitter scan + rule
engine + minimal symbol graph) to editors such as Neovim, Emacs, Helix,
VS Code via the Language Server Protocol.

The server is implemented in ``scripts/lsp_server.py`` (pygls-based).
This file is the thin CLI wrapper that registers the ``lsp`` command,
parses args, and delegates to ``lsp_server.run_stdio`` or
``lsp_server.run_tcp``.

Usage::

    codelens lsp                                  # stdio (default)
    codelens lsp --rule-file my.yaml              # + rule-engine diagnostics
    codelens lsp --tcp --port 2087                # TCP transport (debug)
    codelens lsp --version                        # print version, exit 0

Phase 1 supported LSP methods:

* ``initialize`` / ``initialized`` / ``shutdown`` / ``exit``
* ``textDocument/didOpen``     — parse + scan, publish diagnostics
* ``textDocument/didChange``   — re-parse + re-scan
* ``textDocument/hover``       — return symbol info + callers/callees
* ``textDocument/definition``  — go-to-definition via symbol graph
* ``textDocument/publishDiagnostics`` — auto-sent after didOpen/didChange

Severity mapping (CodeLens → LSP ``DiagnosticSeverity``):

    critical / ERROR     → Error   (1)
    high     / WARNING   → Warning (2)
    medium   / INFO      → Information (3)
    low      / HINT      → Hint    (4)
"""

from __future__ import annotations

import sys

from commands import register_command

VERSION = "0.1.0"


def add_args(parser):
    """Add LSP-server-specific arguments to the parser."""
    parser.add_argument(
        "--rule-file",
        dest="rule_files",
        action="append",
        default=None,
        metavar="<path.yaml>",
        help="Path to a Semgrep-compatible YAML rule file (issue #46). "
             "May be passed multiple times. When set, the LSP server "
             "runs the rule engine on each document and publishes "
             "diagnostics.",
    )
    parser.add_argument(
        "--tcp",
        action="store_true",
        default=False,
        help="Use TCP transport instead of stdio (useful for debugging).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="TCP host to bind to (only used with --tcp). Default: 127.0.0.1.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=2087,
        help="TCP port to bind to (only used with --tcp). Default: 2087.",
    )
    parser.add_argument(
        "--version",
        dest="show_version",
        action="store_true",
        default=False,
        help="Print the CodeLens LSP server version and exit.",
    )


def execute(args, workspace):
    """Launch the LSP server.

    Returns a dict with ``status`` and either ``version`` (for
    ``--version``) or ``transport`` info. The function blocks for the
    lifetime of the server when running in stdio/TCP mode.
    """
    if getattr(args, "show_version", False):
        return {
            "status": "ok",
            "version": VERSION,
            "name": "codelens-lsp",
        }

    try:
        from lsp_server import run_stdio, run_tcp
    except ImportError as exc:
        return {
            "status": "error",
            "error": f"cannot start LSP server: {exc}",
            "hint": "Install optional deps: pip install codelens[lsp]",
        }

    rule_files = list(getattr(args, "rule_files", None) or [])
    try:
        if getattr(args, "tcp", False):
            run_tcp(args.host, args.port, rule_files)
            return {
                "status": "ok",
                "transport": "tcp",
                "host": args.host,
                "port": args.port,
            }
        else:
            run_stdio(rule_files)
            return {
                "status": "ok",
                "transport": "stdio",
            }
    except KeyboardInterrupt:
        return {"status": "ok", "transport": "stdio", "note": "interrupted by user"}
    except Exception as exc:
        return {"status": "error", "error": f"LSP server crashed: {exc}"}


register_command(
    "lsp",
    "Run CodeLens as a native LSP 3.17 server (stdio by default; --tcp for debug)",
    add_args,
    execute,
)
