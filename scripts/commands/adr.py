# @WHO:   scripts/commands/adr.py
# @WHAT:  Architecture Decision Records CLI command (issue #16)
# @PART:  commands
# @ENTRY: execute()
"""ADR command — Architecture Decision Records manager (issue #16).

Provides persistent memory of *why* the codebase is structured the way it is,
so AI agents don't propose refactors that violate intentional constraints.
Backed by SQLite at ``.codelens/adrs.db``.

Usage::

    codelens adr create --title "Use SQLite over PostgreSQL" \\
        --context "Deployment simplicity for single-node setups" \\
        --decision "SQLite with WAL mode" --status accepted

    codelens adr list                       # list all ADRs
    codelens adr list --status accepted     # filter by status
    codelens adr get --id 3                 # fetch a single ADR
    codelens adr update --id 3 --status deprecated
    codelens adr deprecate --id 3 --superseded-by 7
    codelens adr delete --id 3

The storage layer and programmatic API live in :mod:`adr_engine` — this module
is a thin argparse wrapper that calls :func:`adr_engine.manage_adr`.
"""

from __future__ import annotations

from typing import Any, Dict

from commands import register_command


def add_args(parser):
    """Add ADR subcommand arguments to the parser."""
    sub = parser.add_subparsers(dest="adr_action", help="ADR action")

    # adr create
    create = sub.add_parser(
        "create",
        help="Create a new Architecture Decision Record",
        description=(
            "Create a new ADR at .codelens/adrs.db. Required: --title. "
            "Optional: --context, --decision, --status (default: proposed). "
            "Returns the freshly-inserted record with its assigned id."
        ),
    )
    create.add_argument(
        "--title", required=True,
        help="Short title for the decision (e.g. 'Use SQLite over PostgreSQL')",
    )
    create.add_argument(
        "--context", default="",
        help="Why is this decision needed? Background and constraints.",
    )
    create.add_argument(
        "--decision", default="",
        help="The decision itself (what was chosen and why).",
    )
    create.add_argument(
        "--status", default="proposed",
        choices=["proposed", "accepted", "deprecated", "rejected"],
        help="Initial status (default: proposed)",
    )

    # adr list
    list_p = sub.add_parser(
        "list",
        help="List all ADRs (optionally filtered by status)",
        description=(
            "List all ADRs in the workspace, sorted by id ascending. "
            "Pass --status to filter (proposed/accepted/deprecated/rejected)."
        ),
    )
    list_p.add_argument(
        "--status", default=None,
        choices=["proposed", "accepted", "deprecated", "rejected"],
        help="Filter by status (default: all statuses)",
    )

    # adr get
    get_p = sub.add_parser(
        "get",
        help="Get a single ADR by id",
        description="Fetch a single ADR record by its numeric id.",
    )
    get_p.add_argument(
        "--id", required=True, type=int,
        help="ADR id (positive integer)",
    )

    # adr update
    update = sub.add_parser(
        "update",
        help="Update one or more fields of an ADR",
        description=(
            "Patch an existing ADR. Only fields explicitly passed are "
            "updated; updated_at is always refreshed. At least one of "
            "--title, --context, --decision, --status must be provided."
        ),
    )
    update.add_argument("--id", required=True, type=int, help="ADR id")
    update.add_argument("--title", default=None, help="New title")
    update.add_argument("--context", default=None, help="New context")
    update.add_argument("--decision", default=None, help="New decision")
    update.add_argument(
        "--status", default=None,
        choices=["proposed", "accepted", "deprecated", "rejected"],
        help="New status",
    )

    # adr deprecate
    deprecate = sub.add_parser(
        "deprecate",
        help="Mark an ADR as deprecated (optionally link to a replacement)",
        description=(
            "Set status=deprecated. If --superseded-by is provided, the "
            "replacement ADR must exist and must not be the same id. "
            "Prefer this over `delete` — it preserves history."
        ),
    )
    deprecate.add_argument("--id", required=True, type=int, help="ADR id to deprecate")
    deprecate.add_argument(
        "--superseded-by", default=None, type=int,
        help="Id of the ADR that supersedes this one (optional)",
    )

    # adr delete
    delete = sub.add_parser(
        "delete",
        help="Hard-delete an ADR (prefer 'deprecate' to preserve history)",
        description=(
            "Permanently remove an ADR record. Also clears any "
            "superseded_by references pointing at the deleted id. "
            "Prefer 'deprecate' for normal workflow — use 'delete' only "
            "for records created in error."
        ),
    )
    delete.add_argument("--id", required=True, type=int, help="ADR id to delete")


def execute(args, workspace):
    """Dispatch the ADR subcommand."""
    action = getattr(args, "adr_action", None)
    if not action:
        return {
            "status": "error",
            "error": "no_action",
            "message": "No ADR action specified.",
            "usage": "codelens adr <create|list|get|update|deprecate|delete> [args]",
            "examples": [
                "codelens adr create --title 'Use SQLite' --decision 'WAL mode'",
                "codelens adr list --status accepted",
                "codelens adr get --id 3",
                "codelens adr update --id 3 --status deprecated",
                "codelens adr deprecate --id 3 --superseded-by 7",
                "codelens adr delete --id 3",
            ],
        }

    # Lazy import so a broken adr_engine never breaks command discovery.
    from adr_engine import manage_adr

    # Read arguments defensively — MCP calls pass through _ArgsNamespace which
    # may not have every attribute set.
    kwargs: Dict[str, Any] = {}

    if action == "create":
        kwargs["title"] = getattr(args, "title", None)
        kwargs["context"] = getattr(args, "context", None)
        kwargs["decision"] = getattr(args, "decision", None)
        kwargs["status"] = getattr(args, "status", None) or "proposed"
    elif action == "list":
        kwargs["status_filter"] = getattr(args, "status", None)
    elif action in {"get", "update", "deprecate", "delete"}:
        kwargs["id"] = getattr(args, "id", None)
        if action == "update":
            kwargs["title"] = getattr(args, "title", None)
            kwargs["context"] = getattr(args, "context", None)
            kwargs["decision"] = getattr(args, "decision", None)
            kwargs["status"] = getattr(args, "status", None)
        elif action == "deprecate":
            kwargs["superseded_by"] = getattr(args, "superseded_by", None)

    return manage_adr(workspace, action, **kwargs)


register_command(
    "adr",
    "Architecture Decision Records manager (create/list/get/update/deprecate/delete)",
    add_args,
    execute,
)
