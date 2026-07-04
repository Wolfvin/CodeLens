"""Import-snapshot command — Load a CodeLens graph snapshot into the database.

Issue #12: companion to ``export-snapshot``. Restores a previously
exported snapshot (``.codelens/snapshot.codelens.gz``) into
``.codelens/codelens.db`` so a developer can use the shared team graph
without running a full ``codelens scan``.

Validates the snapshot header and warns if it came from a different
CodeLens version. Supports ``--merge`` to combine the snapshot with the
existing graph (deduplicating nodes/edges by their natural key) instead
of the default replace behavior.

Usage::

    codelens import-snapshot [workspace] [--input path] [--merge] [--db-path path]

The snapshot contains graph metadata only (paths, symbols, edges) —
never file content.
"""

import os
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from commands import register_command
from utils import default_db_path, logger
from snapshot_io import (
    SNAPSHOT_TABLES,
    default_snapshot_path,
    load_snapshot_into_db,
    read_snapshot,
    validate_header,
)


def add_args(parser):
    """Add import-snapshot arguments to the parser."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--input", default=None,
                        help="Input path for the snapshot archive "
                             "(default: .codelens/snapshot.codelens.gz)")
    parser.add_argument("--merge", action="store_true", default=False,
                        help="Merge with existing graph (deduplicate nodes/edges "
                             "by id) instead of replacing the existing graph")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for the target SQLite database file")


def execute(args, workspace):
    """Execute the import-snapshot command."""
    input_path = getattr(args, "input", None)
    merge = getattr(args, "merge", False)
    db_path = getattr(args, "db_path", None)
    return cmd_import_snapshot(
        workspace, input_path=input_path, merge=merge, db_path=db_path
    )


def cmd_import_snapshot(
    workspace: str,
    input_path: Optional[str] = None,
    merge: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a snapshot archive into the CodeLens SQLite database.

    Args:
        workspace: Path to the workspace root.
        input_path: Optional explicit snapshot path. If None, defaults to
            ``<workspace>/.codelens/snapshot.codelens.gz``.
        merge: If True, merge with existing data (deduplicate by natural
            key). If False (default), replace existing graph tables.
        db_path: Optional target SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys: ``status``, ``message``, ``mode``, ``warnings``,
        ``inserted``, ``skipped``, ``header``, ``workspace``, ``db_path``.
        On error: ``status="error"`` with an ``error`` message.
    """
    workspace = os.path.abspath(workspace)
    effective_db = db_path or default_db_path(workspace)

    # Resolve input path (relative paths resolve against the workspace root).
    if input_path:
        effective_input = input_path if os.path.isabs(input_path) \
            else os.path.join(workspace, input_path)
    else:
        effective_input = default_snapshot_path(workspace)

    # Read + parse the snapshot
    try:
        snapshot = read_snapshot(effective_input)
    except FileNotFoundError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "workspace": workspace,
        }
    except ValueError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "workspace": workspace,
        }

    header = snapshot.get("header", {})
    warnings: List[str] = validate_header(header)

    # Print warnings to stderr so they're visible without polluting stdout.
    for w in warnings:
        print(f"[CodeLens] Warning: {w}", file=sys.stderr)

    # Load into the database (creates schema if absent)
    try:
        result = load_snapshot_into_db(
            snapshot, workspace, db_path=effective_db, merge=merge
        )
    except sqlite3.Error as exc:
        return {
            "status": "error",
            "error": f"Failed to import snapshot: {exc}",
            "workspace": workspace,
        }
    except Exception as exc:
        logger.error(f"import-snapshot: load failed: {exc}", exc_info=True)
        return {
            "status": "error",
            "error": f"Failed to import snapshot: {exc}",
            "workspace": workspace,
        }

    inserted = result.get("inserted", {})
    skipped = result.get("skipped", {})
    total_inserted = sum(inserted.values())
    total_skipped = sum(skipped.values())

    mode = "merge" if merge else "replace"
    # Human-readable message; also embedded in the JSON result.
    if merge:
        message = (
            f"Snapshot imported ({mode}): {total_inserted} row(s) inserted, "
            f"{total_skipped} duplicate(s) skipped — "
            f"{total_inserted + total_skipped} total in snapshot."
        )
    else:
        message = (
            f"Snapshot imported ({mode}): {total_inserted} row(s) loaded "
            f"across {len(SNAPSHOT_TABLES)} tables."
        )
    print(message, file=sys.stderr)

    return {
        "status": "ok",
        "message": message,
        "mode": mode,
        "input_path": effective_input,
        "warnings": warnings,
        "inserted": inserted,
        "skipped": skipped,
        "total_inserted": total_inserted,
        "total_skipped": total_skipped,
        "header": header,
        "workspace": workspace,
        "db_path": effective_db,
        "tables": list(SNAPSHOT_TABLES),
    }


register_command(
    "import-snapshot",
    "Import a CodeLens graph snapshot (.codelens.gz) into the database; "
    "use --merge to deduplicate with the existing graph (issue #12)",
    add_args,
    execute,
hidden=True,
deprecated_alias_for='deps',
)
