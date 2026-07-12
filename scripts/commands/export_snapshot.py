"""Export-snapshot command — Save the CodeLens graph as a portable snapshot.

Companion to ``import-snapshot`` (issue #218): writes the current
``.codelens/codelens.db`` graph tables to a gzip-compressed JSON snapshot
(``.codelens/snapshot.codelens.gz`` by default) that a teammate can load
with ``codelens deps <workspace> --check import-snapshot`` without running
a full ``codelens scan`` themselves.

The snapshot contains graph metadata only (paths, symbols, edges) —
never file content.

Usage::

    codelens deps [workspace] --check export-snapshot [--output path]
"""

# @WHO:   scripts/commands/export_snapshot.py
# @WHAT:  Export the graph DB to a portable .codelens.gz snapshot (issue #218).
# @PART:  commands
# @ENTRY: execute()

import os
import sys
from typing import Any, Dict, Optional

from commands import register_command
from utils import default_db_path, logger
from snapshot_io import (
    build_snapshot,
    default_snapshot_path,
    format_size,
    write_snapshot,
)


def add_args(parser):
    """Add export-snapshot arguments to the parser."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--output", default=None,
                        help="Output path for the snapshot archive "
                             "(default: .codelens/snapshot.codelens.gz)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for the source SQLite database file")


def execute(args, workspace):
    """Execute the export-snapshot command."""
    output_path = getattr(args, "output", None)
    db_path = getattr(args, "db_path", None)
    return cmd_export_snapshot(workspace, output_path=output_path, db_path=db_path)


def cmd_export_snapshot(
    workspace: str,
    output_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the CodeLens SQLite graph tables to a snapshot archive.

    Args:
        workspace: Path to the workspace root.
        output_path: Optional explicit snapshot path. If None, defaults to
            ``<workspace>/.codelens/snapshot.codelens.gz``.
        db_path: Optional source SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys: ``status``, ``message``, ``output_path``,
        ``bytes_written``, ``header``, ``workspace``, ``db_path``.
        On error: ``status="error"`` with an ``error`` message.
    """
    workspace = os.path.abspath(workspace)
    effective_db = db_path or default_db_path(workspace)

    effective_output = output_path if output_path and os.path.isabs(output_path) \
        else os.path.join(workspace, output_path) if output_path \
        else default_snapshot_path(workspace)

    try:
        snapshot = build_snapshot(workspace, db_path=effective_db)
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "workspace": workspace,
        }
    except Exception as exc:
        logger.error(f"export-snapshot: build failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "error": f"Failed to build snapshot: {exc}",
            "workspace": workspace,
        }

    try:
        bytes_written = write_snapshot(snapshot, effective_output)
    except OSError as exc:
        return {
            "status": "error",
            "error": f"Failed to write snapshot: {exc}",
            "workspace": workspace,
        }

    header = snapshot.get("header", {})
    message = f"Snapshot exported: {effective_output} ({format_size(bytes_written)})"
    print(message, file=sys.stderr)

    return {
        "status": "ok",
        "message": message,
        "output_path": effective_output,
        "bytes_written": bytes_written,
        "header": header,
        "workspace": workspace,
        "db_path": effective_db,
    }
