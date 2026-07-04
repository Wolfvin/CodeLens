"""Staleness command — list files whose index entry is stale (issue #66 Phase 1).

What this command does
-----------------------
``codelens staleness`` walks the workspace's indexed file list (from
``.codelens/mtimes.json``) and compares each file's current ``os.stat()``
against the stored scan-time values. Files whose size/mtime differ — and
whose SHA-256 content hash also differs when ``--confirm-with-hash`` is
set (default) — are reported as stale.

The command is the CLI analogue of the MCP staleness banner (issue #66
Phase 1). Use it to:

* Manually check staleness before running a query (e.g. in a pre-commit hook).
* Get the full list of stale files when the MCP banner truncates to 10.
* Debug why the banner is or isn't appearing.

Output shape (JSON)::

    {
      "status": "ok",
      "workspace": "/abs/path",
      "stale_count": 3,
      "stale_files": [
        {"rel_path": "...", "edit_age_seconds": 12.3, "content_hash_changed": true, ...},
        ...
      ],
      "banner": "⚠️ Some files referenced below ..."
    }

When ``--format text`` (default), prints the banner + a summary line.
"""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict

from commands import register_command


def add_args(parser: argparse.ArgumentParser) -> None:
    # Issue #178: `workspace` MUST stay an optional positional (nargs="?")
    # to remain consistent with every other command (scan, query, trace, …).
    # Removing nargs or making it required regresses the bug. Pinned by
    # TestStalenessWorkspaceArgRegression in tests/test_staleness.py.
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--no-confirm-hash",
        action="store_true",
        default=False,
        help="Skip SHA-256 content-hash confirmation (faster, but "
        "false-positive on `touch` or `git checkout` of identical "
        "content). Default: hash-confirm enabled.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=10_000,
        help="Safety cap on number of indexed files to walk (default: 10000).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max number of stale files to list in the banner (default: 10).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )


def execute(args: argparse.Namespace, workspace: str) -> Dict[str, Any]:
    """Execute the staleness command."""
    if not workspace:
        return {
            "status": "error",
            "error": "workspace is required (pass as arg or set CODELENS_WORKSPACE)",
        }

    # Lazy import so the command module is importable even if the sync
    # subpackage failed to load (defensive — shouldn't happen).
    try:
        from sync.pending import detect_stale_files, format_staleness_banner
    except ImportError as exc:
        return {
            "status": "error",
            "error": f"sync subpackage not importable: {exc}",
        }

    confirm_with_hash = not getattr(args, "no_confirm_hash", False)
    max_files = getattr(args, "max_files", 10_000) or 10_000
    limit = getattr(args, "limit", 10) or 10
    fmt = getattr(args, "format", "text")

    try:
        stale = detect_stale_files(
            workspace,
            confirm_with_hash=confirm_with_hash,
            max_files=max_files,
        )
    except Exception as exc:
        # Defensive: any unexpected error in staleness detection should
        # surface a clear error, not crash the CLI.
        return {
            "status": "error",
            "error": f"staleness detection failed: {exc}",
            "error_type": type(exc).__name__,
        }

    banner = format_staleness_banner(stale, limit=limit)
    stale_dicts = [sf.as_dict() for sf in stale]

    result: Dict[str, Any] = {
        "status": "ok",
        "workspace": os.path.abspath(workspace),
        "stale_count": len(stale),
        "stale_files": stale_dicts,
        "banner": banner,
    }

    if fmt == "text":
        if banner:
            print(banner)
        else:
            print(f"No stale files in {workspace} (index is fresh).")
        print()
        print(f"Total stale: {len(stale)}")

    return result


register_command(
    "staleness",
    "List files whose index entry is stale (issue #66 Phase 1)",
    add_args,
    execute,
hidden=True,
deprecated_alias_for='audit',
)
