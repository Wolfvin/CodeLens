# @WHO:   scripts/adr_engine.py
# @WHAT:  Architecture Decision Records (ADR) SQLite-backed manager (issue #16)
# @PART:  engine
# @ENTRY: manage_adr()
"""Architecture Decision Records (ADR) manager for CodeLens (issue #16).

Provides persistent memory of *why* the codebase is structured the way it is,
so agents don't propose changes that violate intentional constraints.

Storage layout
--------------
- **SQLite DB:** ``<workspace>/.codelens/adrs.db`` — single-table store with
  ``id``, ``title``, ``context``, ``decision``, ``status``, ``superseded_by``,
  ``created_at``, ``updated_at`` columns.

Schema
------
::

    CREATE TABLE adrs (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        title         TEXT NOT NULL,
        context       TEXT NOT NULL DEFAULT '',
        decision      TEXT NOT NULL DEFAULT '',
        status        TEXT NOT NULL DEFAULT 'proposed',
        superseded_by INTEGER,
        created_at    TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        FOREIGN KEY (superseded_by) REFERENCES adrs(id)
    );

Statuses
--------
- ``proposed``  — drafted but not yet accepted
- ``accepted``  — active decision the codebase should follow
- ``deprecated`` — superseded or no longer relevant; ``superseded_by`` should
  point to the replacement ADR id (if any)
- ``rejected``  — proposed and explicitly rejected

Actions
-------
- ``create``    — insert a new ADR, return the new record
- ``list``      — return all ADRs (optionally filtered by status)
- ``get``       — return a single ADR by id
- ``update``    — patch title/context/decision/status fields
- ``deprecate`` — set status=deprecated and link superseded_by
- ``delete``    — hard delete (rare; prefer deprecate)

All actions return a structured dict suitable for JSON / MCP transport.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ─── Constants ─────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1
DB_FILENAME = "adrs.db"

_VALID_STATUSES = {"proposed", "accepted", "deprecated", "rejected"}

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS adrs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    context       TEXT NOT NULL DEFAULT '',
    decision      TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'proposed',
    superseded_by INTEGER,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (superseded_by) REFERENCES adrs(id)
)
"""

_CREATE_INDEX_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_adrs_status ON adrs(status)"
)


# ─── Path helpers ──────────────────────────────────────────────────────────


def adr_db_path(workspace: str) -> str:
    """Return the absolute path to the ADR SQLite DB for a workspace."""
    return os.path.join(workspace, ".codelens", DB_FILENAME)


# ─── DB connection ─────────────────────────────────────────────────────────


def _connect(workspace: str) -> sqlite3.Connection:
    """Open (and lazily initialize) the ADR DB for ``workspace``.

    Creates the ``.codelens/`` directory and the ``adrs`` table if missing.
    Returns a connection with ``row_factory = sqlite3.Row`` so callers can
    index results by column name.
    """
    workspace = os.path.abspath(workspace)
    db_path = adr_db_path(workspace)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(_CREATE_TABLE)
    conn.execute(_CREATE_INDEX_STATUS)
    conn.commit()
    return conn


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ─── Validation ────────────────────────────────────────────────────────────


def _validate_status(status: str) -> None:
    """Raise ``ValueError`` if ``status`` is not a known ADR status."""
    if status not in _VALID_STATUSES:
        raise ValueError(
            f"Invalid ADR status: {status!r}. "
            f"Must be one of: {sorted(_VALID_STATUSES)}"
        )


def _validate_title(title: str) -> None:
    """Raise ``ValueError`` if ``title`` is empty or whitespace-only."""
    if not title or not title.strip():
        raise ValueError("ADR title cannot be empty")


def _validate_id(adr_id: Any) -> int:
    """Coerce ``adr_id`` to int and validate it is positive."""
    try:
        iid = int(adr_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"ADR id must be an integer, got: {adr_id!r}") from exc
    if iid < 1:
        raise ValueError(f"ADR id must be >= 1, got: {iid}")
    return iid


def _validate_superseded_by(superseded_by: Any) -> Optional[int]:
    """Validate ``superseded_by``: ``None`` or a positive int."""
    if superseded_by is None or superseded_by == "":
        return None
    try:
        iid = int(superseded_by)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"superseded_by must be an integer or null, got: {superseded_by!r}"
        ) from exc
    if iid < 1:
        raise ValueError(f"superseded_by must be >= 1, got: {iid}")
    return iid


# ─── Row → dict ────────────────────────────────────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict (JSON-serializable)."""
    return {
        "id": row["id"],
        "title": row["title"],
        "context": row["context"],
        "decision": row["decision"],
        "status": row["status"],
        "superseded_by": row["superseded_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ─── Actions ───────────────────────────────────────────────────────────────


def create_adr(
    workspace: str,
    title: str,
    context: str = "",
    decision: str = "",
    status: str = "proposed",
) -> Dict[str, Any]:
    """Create a new ADR record.

    Returns the freshly-inserted record (with its assigned ``id``).
    """
    _validate_title(title)
    _validate_status(status)
    workspace = os.path.abspath(workspace)

    now = _now_iso()
    conn = _connect(workspace)
    try:
        cur = conn.execute(
            """INSERT INTO adrs (title, context, decision, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title.strip(), context or "", decision or "", status, now, now),
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (new_id,)
        ).fetchone()
    finally:
        conn.close()

    record = _row_to_dict(row)
    return {
        "status": "ok",
        "action": "created",
        "adr": record,
    }


def list_adrs(
    workspace: str,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """List all ADRs, optionally filtered by status.

    Returns a dict with ``total``, ``filtered`` count, and ``adrs`` list
    sorted by id ascending.
    """
    workspace = os.path.abspath(workspace)
    if status_filter is not None:
        _validate_status(status_filter)

    conn = _connect(workspace)
    try:
        if status_filter is not None:
            rows = conn.execute(
                "SELECT * FROM adrs WHERE status = ? ORDER BY id ASC",
                (status_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM adrs ORDER BY id ASC"
            ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS c FROM adrs").fetchone()["c"]
    finally:
        conn.close()

    adrs = [_row_to_dict(r) for r in rows]
    return {
        "status": "ok",
        "action": "list",
        "total": total,
        "filtered": len(adrs),
        "filter": status_filter,
        "adrs": adrs,
    }


def get_adr(workspace: str, adr_id: int) -> Dict[str, Any]:
    """Return a single ADR by id.

    Returns a ``not_found`` result (not an error) when the ADR doesn't exist,
    so callers can distinguish "missing" from "broken".
    """
    iid = _validate_id(adr_id)
    workspace = os.path.abspath(workspace)

    conn = _connect(workspace)
    try:
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (iid,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {
            "status": "not_found",
            "id": iid,
            "message": f"ADR #{iid} not found in workspace {workspace!r}.",
        }

    return {
        "status": "ok",
        "action": "get",
        "adr": _row_to_dict(row),
    }


def update_adr(
    workspace: str,
    adr_id: int,
    title: Optional[str] = None,
    context: Optional[str] = None,
    decision: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Patch one or more fields of an ADR.

    Only fields explicitly passed (non-``None``) are updated. ``updated_at``
    is always refreshed. Returns the updated record.
    """
    iid = _validate_id(adr_id)
    workspace = os.path.abspath(workspace)

    if title is not None:
        _validate_title(title)
    if status is not None:
        _validate_status(status)

    # Build SET clause dynamically.
    updates: List[str] = []
    params: List[Any] = []
    if title is not None:
        updates.append("title = ?")
        params.append(title.strip())
    if context is not None:
        updates.append("context = ?")
        params.append(context)
    if decision is not None:
        updates.append("decision = ?")
        params.append(decision)
    if status is not None:
        updates.append("status = ?")
        params.append(status)

    if not updates:
        # Nothing to update — return current record unchanged.
        return get_adr(workspace, iid)

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(iid)

    conn = _connect(workspace)
    try:
        cur = conn.execute(
            f"UPDATE adrs SET {', '.join(updates)} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            conn.close()
            return {
                "status": "not_found",
                "id": iid,
                "message": f"ADR #{iid} not found — no update performed.",
            }
        conn.commit()
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (iid,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "status": "ok",
        "action": "updated",
        "adr": _row_to_dict(row),
    }


def deprecate_adr(
    workspace: str,
    adr_id: int,
    superseded_by: Optional[int] = None,
) -> Dict[str, Any]:
    """Mark an ADR as deprecated, optionally linking to its replacement.

    Sets ``status = 'deprecated'`` and (if ``superseded_by`` is provided)
    ``superseded_by = <replacement id>``. The replacement ADR must exist
    and must not be the same as the deprecated one (self-reference forbidden).
    """
    iid = _validate_id(adr_id)
    sup_id = _validate_superseded_by(superseded_by)
    workspace = os.path.abspath(workspace)

    if sup_id is not None and sup_id == iid:
        raise ValueError(
            f"ADR #{iid} cannot supersede itself — superseded_by must point "
            "to a different ADR."
        )

    conn = _connect(workspace)
    try:
        # Verify the ADR being deprecated exists.
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (iid,)
        ).fetchone()
        if row is None:
            conn.close()
            return {
                "status": "not_found",
                "id": iid,
                "message": f"ADR #{iid} not found — cannot deprecate.",
            }

        # If a replacement is named, verify it exists and is not deprecated.
        if sup_id is not None:
            sup_row = conn.execute(
                "SELECT * FROM adrs WHERE id = ?", (sup_id,)
            ).fetchone()
            if sup_row is None:
                conn.close()
                return {
                    "status": "error",
                    "error": "superseded_by_not_found",
                    "message": (
                        f"Replacement ADR #{sup_id} not found — cannot link "
                        f"ADR #{iid} to a non-existent record."
                    ),
                    "id": iid,
                    "superseded_by": sup_id,
                }

        now = _now_iso()
        if sup_id is not None:
            conn.execute(
                """UPDATE adrs
                   SET status = 'deprecated',
                       superseded_by = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (sup_id, now, iid),
            )
        else:
            conn.execute(
                """UPDATE adrs
                   SET status = 'deprecated',
                       updated_at = ?
                   WHERE id = ?""",
                (now, iid),
            )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (iid,)
        ).fetchone()
    finally:
        conn.close()

    return {
        "status": "ok",
        "action": "deprecated",
        "adr": _row_to_dict(row),
    }


def delete_adr(workspace: str, adr_id: int) -> Dict[str, Any]:
    """Hard-delete an ADR record.

    Returns ``not_found`` if the id doesn't exist. Also clears any
    ``superseded_by`` references pointing at the deleted id (sets them to
    NULL) so referential integrity is preserved without blocking the delete.
    """
    iid = _validate_id(adr_id)
    workspace = os.path.abspath(workspace)

    conn = _connect(workspace)
    try:
        # Check existence first.
        row = conn.execute(
            "SELECT * FROM adrs WHERE id = ?", (iid,)
        ).fetchone()
        if row is None:
            conn.close()
            return {
                "status": "not_found",
                "id": iid,
                "message": f"ADR #{iid} not found — nothing to delete.",
            }

        # Clear dangling superseded_by references (defensive — we don't want
        # to block deletes, but we also don't want to leave pointers to a
        # deleted row).
        conn.execute(
            "UPDATE adrs SET superseded_by = NULL WHERE superseded_by = ?",
            (iid,),
        )
        conn.execute("DELETE FROM adrs WHERE id = ?", (iid,))
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "action": "deleted",
        "id": iid,
    }


# ─── Top-level dispatcher ──────────────────────────────────────────────────


def manage_adr(
    workspace: str,
    action: str,
    *,
    id: Optional[int] = None,
    title: Optional[str] = None,
    context: Optional[str] = None,
    decision: Optional[str] = None,
    status: Optional[str] = None,
    superseded_by: Optional[int] = None,
    status_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Dispatch an ADR action by name.

    This is the single entry point used by both the CLI command and the MCP
    tool. Keeping the dispatch here (rather than in the command layer) means
    the programmatic API matches the user-facing API 1:1.

    Actions: ``create``, ``list``, ``get``, ``update``, ``deprecate``, ``delete``.
    """
    if action == "create":
        if title is None:
            return {
                "status": "error",
                "error": "missing_required_field",
                "field": "title",
                "message": "create action requires a 'title' argument.",
            }
        return create_adr(
            workspace,
            title=title,
            context=context or "",
            decision=decision or "",
            status=status or "proposed",
        )

    if action == "list":
        return list_adrs(workspace, status_filter=status_filter)

    if action == "get":
        if id is None:
            return {
                "status": "error",
                "error": "missing_required_field",
                "field": "id",
                "message": "get action requires an 'id' argument.",
            }
        return get_adr(workspace, id)

    if action == "update":
        if id is None:
            return {
                "status": "error",
                "error": "missing_required_field",
                "field": "id",
                "message": "update action requires an 'id' argument.",
            }
        return update_adr(
            workspace,
            id,
            title=title,
            context=context,
            decision=decision,
            status=status,
        )

    if action == "deprecate":
        if id is None:
            return {
                "status": "error",
                "error": "missing_required_field",
                "field": "id",
                "message": "deprecate action requires an 'id' argument.",
            }
        return deprecate_adr(workspace, id, superseded_by=superseded_by)

    if action == "delete":
        if id is None:
            return {
                "status": "error",
                "error": "missing_required_field",
                "field": "id",
                "message": "delete action requires an 'id' argument.",
            }
        return delete_adr(workspace, id)

    return {
        "status": "error",
        "error": "unknown_action",
        "action": action,
        "available_actions": [
            "create", "list", "get", "update", "deprecate", "delete"
        ],
    }
