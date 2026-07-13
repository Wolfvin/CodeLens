# @WHO:   scripts/commands/symbols_overview.py
# @WHAT:  Token-efficient hierarchical symbols map from graph_nodes (issue #254)
# @PART:  commands
# @ENTRY: execute()
"""symbols_overview — hierarchical top-level symbols fast-path (issue #254).

Queries ``graph_nodes`` in the already-built SQLite registry (no re-parse,
no LSP) and returns a compact per-file map of top-level symbols:
  name + kind + line

Intended use: agent onboarding — understand "what lives in each file" without
reading every line.  Token cost is <<1% of outline-full.

Registered as ``context --check overview``.
"""

import os
import sqlite3
from collections import defaultdict
from typing import Any, Dict, List, Optional

from utils import default_db_path


# Symbol kinds to include in overview.  Omit synthetic / noise kinds.
_INCLUDE_KINDS = frozenset({
    "function", "method", "class", "module", "route",
    "type", "interface", "struct", "enum", "trait",
})

# Max files to include when no --file filter is given.
_DEFAULT_MAX_FILES = 200


def _query_overview(
    db_path: str,
    file_filter: Optional[str] = None,
    max_files: int = _DEFAULT_MAX_FILES,
) -> Dict[str, Any]:
    """Query graph_nodes and return compact per-file symbol map."""
    if not os.path.exists(db_path):
        return {
            "status": "no_registry",
            "note": "Run 'codelens scan <workspace>' first to build the registry.",
        }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if file_filter:
            # Normalize separator for cross-platform matching
            norm = file_filter.replace("\\", "/")
            rows = conn.execute(
                "SELECT name, node_type, file, line FROM graph_nodes "
                "WHERE REPLACE(file,'\\\\','/') LIKE ? "
                "ORDER BY file, line",
                (f"%{norm}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT name, node_type, file, line FROM graph_nodes "
                "ORDER BY file, line"
            ).fetchall()
    finally:
        conn.close()

    by_file: Dict[str, List[Dict]] = defaultdict(list)
    for row in rows:
        kind = row["node_type"] or "function"
        if kind not in _INCLUDE_KINDS:
            continue
        # Normalize file separator
        f = (row["file"] or "").replace("\\", "/")
        by_file[f].append({
            "name": row["name"],
            "kind": kind,
            "line": row["line"],
        })

    # Apply max_files cap (workspace-wide mode only)
    files_sorted = sorted(by_file.keys())
    truncated = False
    if not file_filter and len(files_sorted) > max_files:
        files_sorted = files_sorted[:max_files]
        truncated = True

    overview = {f: by_file[f] for f in files_sorted}
    total_symbols = sum(len(v) for v in overview.values())

    return {
        "status": "ok",
        "stats": {
            "total_files": len(overview),
            "total_symbols": total_symbols,
            "truncated": truncated,
        },
        "overview": overview,
    }


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None,
                        help="Filter to a specific file (substring match)")
    parser.add_argument("--max-files", type=int, default=_DEFAULT_MAX_FILES,
                        dest="max_files",
                        help=f"Max files in workspace-wide mode (default: {_DEFAULT_MAX_FILES})")


def execute(args, workspace):
    """Return token-efficient hierarchical symbols map.

    @FLOW:    SYMBOLS_OVERVIEW
    @CALLS:   _query_overview() -> dict
    @MUTATES: nothing (read-only DB query)
    """
    db_path = getattr(args, "db_path", None) or default_db_path(workspace)
    file_filter = getattr(args, "file", None)
    max_files = getattr(args, "max_files", None) or _DEFAULT_MAX_FILES
    return _query_overview(db_path, file_filter=file_filter, max_files=max_files)

# Issue #254: registered as the `overview` sub-check of the `context` umbrella
# (see commands/context.py), NOT a standalone command — count stays 12.
