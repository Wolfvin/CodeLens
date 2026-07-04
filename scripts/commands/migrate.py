"""migrate utility — JSON registry to SQLite (issue #195).

This module is NOT a registered command (``migrate`` was dropped per issue
#195). It is kept as a utility so that existing tests and scripts that
import ``cmd_migrate`` continue to work — the underlying migration logic
lives in ``PersistentRegistry.migrate_from_json``.
"""

from typing import Any, Dict

from persistent_registry import PersistentRegistry


def cmd_migrate(workspace: str, verify: bool = False) -> Dict[str, Any]:
    """Migrate .codelens/ JSON files to SQLite.

    Thin wrapper around ``PersistentRegistry.migrate_from_json`` that
    preserves the legacy result shape (``{"status": ..., "migration": {...}}``)
    expected by tests and older scripts.

    Returns ``{"status": "error", ...}`` if no JSON registry exists or
    if the SQLite registry is already populated.
    """
    try:
        import os
        from registry import get_codelens_dir

        pr = PersistentRegistry(workspace)
        # Check for the "already populated" early-return condition FIRST.
        # Only treat a populated db (existing symbol rows) as "already
        # migrated" — an empty db shell created by scan() must NOT skip
        # the real JSON→SQLite migration (issue #35 regression guard).
        conn = pr._connect()
        cursor = conn.execute("SELECT COUNT(*) FROM symbols")
        existing = cursor.fetchone()[0]
        # Do NOT close conn here — _connect() returns the persistent
        # self._conn, and closing it would break subsequent migrate_from_json()
        # calls. The connection is closed via pr.close() at the end.
        if existing > 0:
            pr.close()
            return {
                "status": "ok",
                "message": "SQLite registry already exists and is populated; skipping migration.",
                "migration": {"already_exists": True, "existing_rows": existing},
            }

        # Pre-check: error if no JSON registry files exist (legacy behavior).
        # load_*_registry returns an empty dict even when the file is missing,
        # so we check file existence directly.
        codelens_dir = get_codelens_dir(workspace)
        frontend_path = os.path.join(codelens_dir, "frontend.json")
        backend_path = os.path.join(codelens_dir, "backend.json")
        if not (os.path.isfile(frontend_path) or os.path.isfile(backend_path)):
            pr.close()
            return {
                "status": "error",
                "error": "No JSON registry found at .codelens/frontend.json or .codelens/backend.json. "
                         "Run 'codelens scan' first.",
            }

        result = pr.migrate_from_json()
        pr.close()
        if result.get("status") != "ok":
            return result
        # Reshape to legacy {status, migration: {...}} form.
        migration = {k: v for k, v in result.items() if k != "status"}
        return {"status": "ok", "migration": migration}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
