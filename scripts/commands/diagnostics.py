# @WHO:   scripts/commands/diagnostics.py
# @WHAT:  Surface LSP diagnostics (lint/errors/warnings) per file (issue #253)
# @PART:  commands
# @ENTRY: execute()
"""diagnostics command — LSP lint/errors/warnings for a file (issue #253).

Gap vs Serena MCP: Serena surfaces contextual diagnostics (language-server
lint/errors per file/symbol) so an agent can find and fix bugs without
shelling out to a linter manually. CodeLens had the LSP infrastructure
(``lsp_client.py`` already registered the ``publishDiagnostics`` capability
at init) but never exposed the diagnostics themselves.

This runs the workspace's language server against a single file and returns
its diagnostics. Diagnostics inherently require an LSP server — there is no
regex/graph fallback for "what does the type-checker think is wrong here" —
so this command turns LSP on internally rather than requiring the caller to
pass ``--deep``. If no server is installed it degrades gracefully to an
empty result with ``lsp_available: false`` (never errors, never hangs).

Exposed as ``context --check diagnostics --file <path>``.
"""

import os
from typing import Any, Dict

from commands import register_command

# LSP severity (1..4) → human label.
_SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None,
                        help="File to get diagnostics for (required)")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Seconds to wait for the language server to push "
                             "diagnostics (default: 3.0)")


def execute(args, workspace):
    file_path = getattr(args, "file", None)
    if not file_path:
        return {
            "status": "error",
            "error": "diagnostics requires --file <path>",
        }

    abs_file = file_path if os.path.isabs(file_path) else os.path.join(workspace, file_path)
    if not os.path.isfile(abs_file):
        return {
            "status": "error",
            "error": f"file not found: {file_path}",
        }

    wait_timeout = getattr(args, "timeout", None) or 3.0

    try:
        from hybrid_engine import create_hybrid_engine
        # Diagnostics have no non-LSP fallback, so enable LSP unconditionally
        # (deep=True) regardless of the global --deep flag.
        engine = create_hybrid_engine(workspace, deep=True)
    except Exception as exc:
        return {
            "status": "ok",
            "file": file_path,
            "lsp_available": False,
            "diagnostics": [],
            "note": f"LSP engine unavailable ({exc}); no diagnostics. "
                    "Install a language server for your file's language.",
        }

    if not engine.lsp_active:
        engine.cleanup()
        return {
            "status": "ok",
            "file": file_path,
            "lsp_available": False,
            "diagnostics": [],
            "note": "No LSP server available for this workspace/language. "
                    "Run `codelens doctor --check lsp-status` to see options.",
        }

    try:
        raw = engine.get_diagnostics(abs_file, wait_timeout=wait_timeout)
    finally:
        engine.cleanup()

    if raw is None:
        return {
            "status": "ok",
            "file": file_path,
            "lsp_available": False,
            "diagnostics": [],
            "note": "LSP server did not handle this file (unsupported language?).",
        }

    findings = []
    by_severity: Dict[str, int] = {}
    for d in raw:
        sev_num = d.get("severity", 3)
        sev = _SEVERITY.get(sev_num, "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        rng = d.get("range", {}).get("start", {})
        findings.append({
            "severity": sev,
            "line": rng.get("line", 0) + 1,          # LSP is 0-indexed; report 1-indexed
            "character": rng.get("character", 0),
            "message": d.get("message", ""),
            "source": d.get("source", ""),
            "code": d.get("code", ""),
        })

    return {
        "status": "ok",
        "file": file_path,
        "lsp_available": True,
        "total": len(findings),
        "by_severity": by_severity,
        "diagnostics": findings,
    }

# Issue #253: registered as the `diagnostics` sub-check of the `context`
# umbrella (see commands/context.py), NOT a standalone command — command
# count stays 12. Imported by context.py, not self-registering.
