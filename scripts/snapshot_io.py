"""Snapshot I/O helpers for CodeLens graph sharing (issue #12).

Single source of truth for the on-disk snapshot format used by both the
``export-snapshot`` and ``import-snapshot`` CLI commands. Keeping the
format definition here (instead of duplicating it across two command
modules) guarantees export and import stay in lockstep.

Snapshot format
---------------
A snapshot is a **gzip-compressed JSON** document with this shape::

    {
        "header": {
            "format_version": 1,
            "codelens_version": "8.2.0",
            "scan_timestamp": 1234567890.0,
            "exported_at": "2024-01-01T00:00:00+00:00",
            "file_count": 31,
            "node_count": 31,
            "edge_count": 97,
            "table_counts": {"graph_nodes": 31, "graph_edges": 97, ...},
            "tables": ["graph_nodes", "graph_edges", "symbols", "refs", "files"],
            "workspace": "/abs/path/to/workspace",
            "note": "Contains graph metadata only — no file content."
        },
        "data": {
            "graph_nodes": {"columns": [...], "rows": [[...], ...]},
            "graph_edges": {"columns": [...], "rows": [[...], ...]},
            ...
        }
    }

Constraint (issue #12): a snapshot MUST NOT contain file content. Only
graph metadata is exported — file paths, symbol names/kinds/line spans,
edge relationships, content hashes, and timestamps. The ``files`` table
stores ``content_hash`` (a digest), never the bytes themselves.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from utils import CODELENS_VERSION, default_db_path, logger


# ─── Format constants ─────────────────────────────────────────

#: Snapshot on-disk format version. Bump on backward-incompatible
#: structural changes; ``import-snapshot`` warns on mismatch.
SNAPSHOT_FORMAT_VERSION = 1

#: Default snapshot filename inside ``.codelens/``.
DEFAULT_SNAPSHOT_FILENAME = "snapshot.codelens.gz"

#: Tables exported, in deterministic order. Only graph metadata —
#: never file content. See module docstring for the constraint.
SNAPSHOT_TABLES: List[str] = [
    "graph_nodes",
    "graph_edges",
    "symbols",
    "refs",
    "files",
]

#: Column order for each exported table. Stored in the snapshot so
#: import can map columns by name (robust to future schema additions)
#: rather than by position.
TABLE_COLUMNS: Dict[str, List[str]] = {
    "graph_nodes": ["id", "node_id", "node_type", "name", "file", "line", "extra_json"],
    "graph_edges": [
        "id", "source_id", "target_id", "edge_type",
        "file", "line", "confidence", "extra_json",
    ],
    "symbols": [
        "id", "name", "kind", "file_path", "line_start", "line_end",
        "language", "signature", "hash", "extra_json",
    ],
    "refs": [
        "id", "source_symbol", "target_symbol", "reference_type",
        "source_file", "extra_json",
    ],
    "files": [
        "id", "file_path", "language", "last_modified",
        "content_hash", "last_scanned",
    ],
}

#: Natural-key columns used to deduplicate rows when importing in
#: ``--merge`` mode (issue #12). Rows whose natural key already
#: exists in the target table are skipped. The autoincrement ``id``
#: column is intentionally NOT part of any natural key — import lets
#: SQLite assign fresh ids to avoid sequence collisions.
NATURAL_KEY_COLUMNS: Dict[str, List[str]] = {
    "graph_nodes": ["node_id"],
    "graph_edges": ["source_id", "target_id", "edge_type", "file", "line"],
    "symbols": ["name", "kind", "file_path", "line_start"],
    "refs": ["source_symbol", "target_symbol", "reference_type", "source_file"],
    "files": ["file_path"],
}


# ─── Path helpers ─────────────────────────────────────────────


def default_snapshot_path(workspace: str) -> str:
    """Return the default snapshot path: ``<workspace>/.codelens/snapshot.codelens.gz``."""
    return os.path.join(workspace, ".codelens", DEFAULT_SNAPSHOT_FILENAME)


# ─── Size formatting ──────────────────────────────────────────


def format_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Examples: ``512`` → ``"512 B"``; ``1500`` → ``"1.5 KB"``;
    ``1250000`` → ``"1.2 MB"``. Used by the export command's
    ``"Snapshot exported: ... (1.2 MB)"`` message.
    """
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


# ─── DB helpers ───────────────────────────────────────────────


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _quote_ident(name: str) -> str:
    """Quote a SQL identifier (table/column) defensively.

    All identifiers here are hard-coded constants, but quoting keeps
    static analyzers happy and is forward-compatible if a future
    schema ever uses a reserved word.
    """
    return '"' + name.replace('"', '""') + '"'


# ─── Snapshot construction (export side) ──────────────────────


def build_snapshot(
    workspace: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Read the SQLite graph tables and return a snapshot dict.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Snapshot dict with ``header`` and ``data`` keys (see module
        docstring).

    Raises:
        FileNotFoundError: if the database file does not exist.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"CodeLens database not found at {db_path}. "
            f"Run 'codelens scan' first to build the graph."
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        data: Dict[str, Any] = {}
        counts: Dict[str, int] = {}
        for table in SNAPSHOT_TABLES:
            cols = TABLE_COLUMNS[table]
            if not _table_exists(conn, table):
                data[table] = {"columns": cols, "rows": []}
                counts[table] = 0
                continue
            col_list = ", ".join(_quote_ident(c) for c in cols)
            rows = conn.execute(
                f"SELECT {col_list} FROM {_quote_ident(table)}"
            ).fetchall()
            data[table] = {
                "columns": cols,
                "rows": [[r[i] for i in range(len(cols))] for r in rows],
            }
            counts[table] = len(rows)

        # Pull the original scan timestamp from scan_metadata (if present)
        # so consumers can tell how stale the graph is.
        scan_ts: float = 0.0
        if _table_exists(conn, "scan_metadata"):
            r = conn.execute(
                "SELECT scan_timestamp FROM scan_metadata WHERE id = 1"
            ).fetchone()
            if r is not None:
                scan_ts = float(r[0] or 0.0)

        header: Dict[str, Any] = {
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "codelens_version": CODELENS_VERSION,
            "scan_timestamp": scan_ts,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "file_count": counts.get("files", 0),
            "node_count": counts.get("graph_nodes", 0),
            "edge_count": counts.get("graph_edges", 0),
            "table_counts": counts,
            "tables": list(SNAPSHOT_TABLES),
            "workspace": workspace,
            "note": "Contains graph metadata only — no file content.",
        }
        return {"header": header, "data": data}
    finally:
        conn.close()


def write_snapshot(snapshot: Dict[str, Any], output_path: str) -> int:
    """Write a snapshot dict to ``output_path`` as gzip-compressed JSON.

    Creates parent directories as needed.

    Returns:
        The size of the written file in bytes.
    """
    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = json.dumps(snapshot, default=str, ensure_ascii=False).encode("utf-8")
    with gzip.open(output_path, "wb") as f:
        f.write(payload)
    return os.path.getsize(output_path)


# ─── Snapshot loading (import side) ───────────────────────────


def read_snapshot(input_path: str) -> Dict[str, Any]:
    """Read a gzip-compressed JSON snapshot from ``input_path``.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file is not a valid snapshot.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Snapshot file not found: {input_path}")
    try:
        with gzip.open(input_path, "rb") as f:
            payload = f.read()
    except OSError as exc:
        raise ValueError(
            f"Failed to decompress snapshot {input_path}: {exc}"
        ) from exc
    try:
        snapshot = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Snapshot {input_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(snapshot, dict) or "header" not in snapshot or "data" not in snapshot:
        raise ValueError(
            f"Snapshot {input_path} is missing required 'header'/'data' keys."
        )
    return snapshot


# ─── Snapshot import ──────────────────────────────────────────


def _ensure_schema(workspace: str, db_path: str) -> None:
    """Create all CodeLens SQLite tables (graph + persistent registry) if absent.

    Delegates to ``PersistentRegistry._init_schema`` (which also calls
    ``graph_model.init_graph_schema``) so the import target always has
    the full schema, even on a fresh workspace that has never been scanned.
    Idempotent — safe to call on an already-initialized database.
    """
    from persistent_registry import PersistentRegistry  # local import avoids cycles
    reg = PersistentRegistry(workspace, db_path=db_path)
    try:
        reg._connect()  # triggers _init_schema on first call
    finally:
        reg.close()


def _existing_natural_keys(
    conn: sqlite3.Connection, table: str
) -> set:
    """Return the set of existing natural-key tuples for ``table``.

    Used by ``--merge`` mode to skip rows whose natural key is already
    present. Returns an empty set if the table doesn't exist.
    """
    if not _table_exists(conn, table):
        return set()
    key_cols = NATURAL_KEY_COLUMNS[table]
    col_list = ", ".join(_quote_ident(c) for c in key_cols)
    rows = conn.execute(
        f"SELECT {col_list} FROM {_quote_ident(table)}"
    ).fetchall()
    return {tuple(r[i] for i in range(len(key_cols))) for r in rows}


def load_snapshot_into_db(
    snapshot: Dict[str, Any],
    workspace: str,
    db_path: Optional[str] = None,
    merge: bool = False,
) -> Dict[str, Any]:
    """Load a snapshot dict into the SQLite database at ``db_path``.

    Args:
        snapshot: Snapshot dict (as returned by :func:`build_snapshot` /
            :func:`read_snapshot`).
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.
        merge: If True, merge with existing data — rows whose natural key
            already exists are skipped (deduplication). If False (default),
            the target tables are cleared before inserting (replace).

    Returns:
        Dict with per-table inserted/skipped counts and the validated
        header, e.g. ``{"inserted": {...}, "skipped": {...}, "header": {...}}``.
    """
    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)
    _ensure_schema(workspace, db_path)

    data = snapshot.get("data", {})
    inserted: Dict[str, int] = {}
    skipped: Dict[str, int] = {}

    conn = sqlite3.connect(db_path)
    try:
        for table in SNAPSHOT_TABLES:
            cols = TABLE_COLUMNS[table]
            # Insert columns exclude the autoincrement ``id`` so SQLite
            # assigns fresh ids (avoids sequence collisions in both merge
            # and replace modes).
            insert_cols = [c for c in cols if c != "id"]
            tbl_data = data.get(table, {})
            # Honor the snapshot's column list if present (forward-compat);
            # otherwise fall back to the current schema's columns.
            snap_cols = tbl_data.get("columns", cols)
            col_index = {c: i for i, c in enumerate(snap_cols)}
            rows = tbl_data.get("rows", [])

            if not rows:
                inserted[table] = 0
                skipped[table] = 0
                continue

            if not merge:
                conn.execute(f"DELETE FROM {_quote_ident(table)}")
                existing_keys: set = set()
            else:
                existing_keys = _existing_natural_keys(conn, table)

            key_cols = NATURAL_KEY_COLUMNS[table]
            key_idx = [col_index[c] for c in key_cols if c in col_index]
            insert_idx = [col_index[c] for c in insert_cols if c in col_index]

            placeholders = ", ".join("?" for _ in insert_cols)
            col_list_sql = ", ".join(_quote_ident(c) for c in insert_cols)
            insert_sql = (
                f"INSERT INTO {_quote_ident(table)} ({col_list_sql}) "
                f"VALUES ({placeholders})"
            )

            to_insert: List[Tuple[Any, ...]] = []
            ins_count = 0
            skip_count = 0
            for row in rows:
                if merge and key_idx:
                    key = tuple(row[i] for i in key_idx)
                    if key in existing_keys:
                        skip_count += 1
                        continue
                    existing_keys.add(key)
                values = tuple(row[i] for i in insert_idx)
                to_insert.append(values)

            if to_insert:
                conn.executemany(insert_sql, to_insert)
                ins_count = len(to_insert)
            inserted[table] = ins_count
            skipped[table] = skip_count

        conn.commit()
    except sqlite3.Error as exc:
        conn.rollback()
        logger.error(f"Snapshot import failed: {exc}", exc_info=True)
        raise
    finally:
        conn.close()

    return {
        "inserted": inserted,
        "skipped": skipped,
        "header": snapshot.get("header", {}),
    }


def validate_header(header: Dict[str, Any]) -> List[str]:
    """Validate a snapshot header; return a list of warning messages.

    An empty list means no warnings. Currently checks:
    - ``format_version`` mismatch (warns on future versions we don't know)
    - ``codelens_version`` mismatch (warns if snapshot came from a
      different CodeLens version — per issue #12 requirement)
    """
    warnings: List[str] = []
    fmt_ver = header.get("format_version")
    if fmt_ver is not None and fmt_ver != SNAPSHOT_FORMAT_VERSION:
        warnings.append(
            f"Snapshot format version is {fmt_ver}, expected "
            f"{SNAPSHOT_FORMAT_VERSION}. Import may be incomplete or inaccurate."
        )
    snap_ver = header.get("codelens_version")
    if snap_ver is not None and snap_ver != CODELENS_VERSION:
        warnings.append(
            f"Snapshot was created with CodeLens v{snap_ver}; current version is "
            f"v{CODELENS_VERSION}. Graph schema may differ — verify results."
        )
    return warnings
