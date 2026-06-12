"""Migrate command — Convert JSON registry to SQLite persistent registry."""

import os
from typing import Dict, Any

from utils import logger
from persistent_registry import PersistentRegistry, db_exists, is_sqlite_available
from commands import register_command


def add_args(parser):
    """Add migrate-specific arguments to the parser."""
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--db-path", default=None,
                        help="Custom path for the SQLite database file")
    parser.add_argument("--verify", action="store_true",
                        help="Verify data integrity after migration")


def execute(args, workspace):
    """Execute the migrate command."""
    db_path = getattr(args, 'db_path', None)
    verify = getattr(args, 'verify', False)
    return cmd_migrate(workspace, db_path=db_path, verify=verify)


def cmd_migrate(workspace: str, db_path: str = None, verify: bool = False) -> Dict[str, Any]:
    """Migrate from JSON-based registry to SQLite persistent registry.

    Steps:
    1. Check if SQLite is available
    2. Check if migration is needed (DB doesn't exist yet)
    3. Load data from JSON files
    4. Write data to SQLite
    5. Optionally verify data integrity
    6. Report results

    The migration is additive — it does NOT delete the JSON files,
    ensuring backward compatibility and rollback capability.
    """
    workspace = os.path.abspath(workspace)

    # Step 1: Check SQLite availability
    if not is_sqlite_available():
        return {
            "status": "error",
            "error": "SQLite is not available in this Python installation",
            "suggestion": "Install Python 3 with sqlite3 module support",
        }

    # Step 2: Check if migration is needed
    effective_db_path = db_path or os.path.join(workspace, ".codelens", "codelens.db")
    if os.path.exists(effective_db_path):
        return {
            "status": "ok",
            "message": "SQLite database already exists. Use --verify to check integrity.",
            "db_path": effective_db_path,
            "hint": "To re-migrate, delete the .codelens/codelens.db file first.",
        }

    # Step 3: Check if JSON files exist
    from registry import get_codelens_dir
    codelens_dir = get_codelens_dir(workspace)
    frontend_path = os.path.join(codelens_dir, "frontend.json")
    backend_path = os.path.join(codelens_dir, "backend.json")

    if not os.path.exists(frontend_path) and not os.path.exists(backend_path):
        return {
            "status": "error",
            "error": "No JSON registry files found. Run 'scan' first to create a registry.",
            "workspace": workspace,
        }

    # Step 4: Perform migration
    try:
        reg = PersistentRegistry(workspace, db_path=db_path)
        reg._connect()
        migration_result = reg.migrate_from_json()
        stats = reg.get_stats()
        reg.close()
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": f"Migration failed: {e}",
            "workspace": workspace,
        }

    # Step 5: Optional verification
    verification = None
    if verify:
        verification = _verify_migration(workspace, effective_db_path)

    result = {
        "status": "ok",
        "message": "Migration from JSON to SQLite completed successfully",
        "workspace": workspace,
        "db_path": effective_db_path,
        "migration": migration_result,
        "stats": stats,
    }

    if verification:
        result["verification"] = verification

    return result


def _verify_migration(workspace: str, db_path: str) -> Dict[str, Any]:
    """Verify that migrated data matches the JSON source."""
    from registry import load_frontend_registry, load_backend_registry

    reg = PersistentRegistry(workspace, db_path=db_path)
    reg._connect()

    verification = {"checks": [], "all_passed": True}

    # Check frontend classes count
    frontend = load_frontend_registry(workspace)
    json_class_count = len(frontend.get("classes", []))
    db_class_count = len(reg.get_all_symbols(kind="class"))
    check_passed = json_class_count == db_class_count
    verification["checks"].append({
        "check": "frontend_classes_count",
        "json_count": json_class_count,
        "db_count": db_class_count,
        "passed": check_passed,
    })
    if not check_passed:
        verification["all_passed"] = False

    # Check frontend IDs count
    json_id_count = len(frontend.get("ids", []))
    db_id_count = len(reg.get_all_symbols(kind="id"))
    check_passed = json_id_count == db_id_count
    verification["checks"].append({
        "check": "frontend_ids_count",
        "json_count": json_id_count,
        "db_count": db_id_count,
        "passed": check_passed,
    })
    if not check_passed:
        verification["all_passed"] = False

    # Check backend nodes count
    backend = load_backend_registry(workspace)
    json_node_count = len(backend.get("nodes", []))
    db_node_count = len(reg.get_all_symbols(kind="function"))
    # Note: db_node_count may be larger due to frontend functions being
    # stored as symbols too, so we check >=
    check_passed = db_node_count >= json_node_count
    verification["checks"].append({
        "check": "backend_nodes_count",
        "json_count": json_node_count,
        "db_count": db_node_count,
        "passed": check_passed,
        "note": "DB count may be higher due to other function symbols",
    })
    if not check_passed:
        verification["all_passed"] = False

    # Spot-check: lookup a specific symbol
    if frontend.get("classes"):
        sample_name = frontend["classes"][0].get("name", "")
        if sample_name:
            found = reg.lookup_symbol(sample_name, "class")
            check_passed = len(found) > 0
            verification["checks"].append({
                "check": "symbol_lookup_spot_check",
                "name": sample_name,
                "found": check_passed,
                "passed": check_passed,
            })
            if not check_passed:
                verification["all_passed"] = False

    reg.close()
    return verification


register_command(
    "migrate",
    "Migrate JSON registry to SQLite persistent database",
    add_args,
    execute,
)
