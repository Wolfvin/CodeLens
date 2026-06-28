"""resolve-types command — manually trigger hybrid type resolution (issue #13).

Runs the hybrid type resolution pass without a full re-scan. Useful for AI
agents who want to refresh type resolution after adding new imports or
modifying class definitions, without paying the cost of a full scan.

Example output::

    {
        "status": "ok",
        "workspace": "/path/to/proj",
        "edges_total": 97,
        "edges_refined": 11,
        "edges_unresolved": 55,
        "import_registry_size": 37
    }
"""

import os
from typing import Any, Dict, Optional

from commands import register_command


def add_args(parser):
    """Add resolve-types arguments to the parser."""
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Custom path for SQLite database file",
    )


def _default_db_path(workspace: str) -> str:
    """Return the default SQLite db path for a workspace."""
    return os.path.join(workspace, ".codelens", "codelens.db")


def execute(args, workspace):
    """Execute the resolve-types command.

    Runs ``hybrid_type_resolver.refine_call_edges`` on the workspace and
    returns a stats dict. If the database doesn't exist (pre-scan), the
    command auto-runs a full scan first so the type resolver has graph
    tables to work with.
    """
    db_path = getattr(args, "db_path", None) or _default_db_path(workspace)

    if not os.path.exists(db_path):
        # Auto-scan so the type resolver has graph tables to read.
        try:
            from commands.scan import cmd_scan
            cmd_scan(workspace, incremental=False)
        except Exception:  # noqa: BLE001 — fail-soft
            return {
                "status": "error",
                "error": "auto-scan failed; run 'scan' manually",
                "workspace": workspace,
            }

    from hybrid_type_resolver import refine_call_edges, import_registry_size

    try:
        stats = refine_call_edges(workspace, db_path)
    except Exception as exc:  # noqa: BLE001 — best-effort, never crash
        return {
            "status": "error",
            "error": str(exc),
            "workspace": workspace,
        }

    return {
        "status": "ok",
        "workspace": workspace,
        "edges_total": stats["edges_total"],
        "edges_refined": stats["edges_refined"],
        "edges_unresolved": stats["edges_unresolved"],
        "import_registry_size": import_registry_size(db_path),
    }


register_command(
    "resolve-types",
    "Run hybrid type resolution: refine CALLS edges with import-aware "
    "receiver types. Auto-scans if graph tables are empty.",
    add_args,
    execute,
)
