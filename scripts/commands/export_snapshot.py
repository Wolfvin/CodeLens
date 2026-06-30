"""Export-snapshot command — Export the CodeLens graph as a compressed archive.

Issue #12: each developer previously had to ``codelens scan`` separately.
``export-snapshot`` packages the SQLite graph tables (``graph_nodes``,
``graph_edges``, ``symbols``, ``refs``, ``files``) as a gzip-compressed
archive that can be committed to the repo and shared with the team via
``codelens import-snapshot``.

The snapshot contains **graph metadata only** — file paths, symbol
names/kinds/line spans, edge relationships, content hashes, timestamps.
It NEVER contains file content.

Usage::

    codelens export-snapshot [workspace] [--output path] [--db-path path]

Example output (the human-readable message is also embedded in the JSON
result under the ``message`` key and printed to stderr so stdout stays
machine-parseable)::

    Snapshot exported: .codelens/snapshot.codelens.gz (1.2 MB)
"""

import os
import sys
from typing import Any, Dict, Optional

from commands import register_command
from utils import default_db_path, logger
from snapshot_io import (
    DEFAULT_SNAPSHOT_FILENAME,
    SNAPSHOT_TABLES,
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
    output = getattr(args, "output", None)
    db_path = getattr(args, "db_path", None)
    return cmd_export_snapshot(workspace, output_path=output, db_path=db_path)


def cmd_export_snapshot(
    workspace: str,
    output_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export the CodeLens graph database to a compressed snapshot archive.

    Reads the SQLite graph tables (graph_nodes, graph_edges, symbols,
    refs, files) and writes them as gzip-compressed JSON to
    ``output_path`` (default: ``<workspace>/.codelens/snapshot.codelens.gz``).

    Args:
        workspace: Path to the workspace root.
        output_path: Optional explicit output path. If None, defaults to
            ``<workspace>/.codelens/snapshot.codelens.gz``.
        db_path: Optional source SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys: ``status``, ``message``, ``snapshot_path``,
        ``size_bytes``, ``size_human``, ``header``, ``workspace``.
        On error: ``status="error"`` with an ``error`` message.
    """
    workspace = os.path.abspath(workspace)

    # Resolve source db path
    effective_db = db_path or default_db_path(workspace)

    # Resolve output path. If the user gave a relative path, resolve it
    # against the workspace root so the default ``.codelens/...`` form
    # works regardless of cwd.
    if output_path:
        effective_output = output_path if os.path.isabs(output_path) \
            else os.path.join(workspace, output_path)
    else:
        effective_output = default_snapshot_path(workspace)

    # Build the snapshot (reads the DB, raises FileNotFoundError if absent)
    try:
        snapshot = build_snapshot(workspace, db_path=effective_db)
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "workspace": workspace,
        }
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"export-snapshot: build failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "error": f"Failed to build snapshot: {exc}",
            "workspace": workspace,
        }

    header = snapshot.get("header", {})

    # Write gzip-compressed JSON to disk
    try:
        size_bytes = write_snapshot(snapshot, effective_output)
    except OSError as exc:
        return {
            "status": "error",
            "error": f"Failed to write snapshot to {effective_output}: {exc}",
            "workspace": workspace,
        }

    size_human = format_size(size_bytes)

    # Human-readable message — also surfaced in the JSON result so
    # scripted consumers can read it. Matches the issue #12 format:
    #   "Snapshot exported: .codelens/snapshot.codelens.gz (1.2 MB)"
    # Use a workspace-relative path in the message when possible so the
    # message is portable across machines (the snapshot is meant to be
    # committed to the repo and shared).
    try:
        rel_output = os.path.relpath(effective_output, workspace)
        # If the output lives outside the workspace, relpath produces
        # something with '..' — fall back to the absolute path in that case.
        if rel_output.startswith(".."):
            display_path = effective_output
        else:
            display_path = rel_output
    except (ValueError, OSError):
        display_path = effective_output

    message = f"Snapshot exported: {display_path} ({size_human})"

    # Print the message to stderr so stdout (JSON) stays machine-clean,
    # matching the convention used by scan's status messages.
    print(message, file=sys.stderr)

    return {
        "status": "ok",
        "message": message,
        "snapshot_path": effective_output,
        "display_path": display_path,
        "size_bytes": size_bytes,
        "size_human": size_human,
        "header": header,
        "workspace": workspace,
        "tables": list(SNAPSHOT_TABLES),
    }


register_command(
    "export-snapshot",
    "Export the CodeLens graph as a compressed snapshot archive (.codelens.gz) "
    "for team sharing (issue #12)",
    add_args,
    execute,
)
