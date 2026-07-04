"""Semantic query command — TF-IDF symbol search (issue #11, Option A)."""

import os
from typing import Any, Dict

from semantic_search_engine import semantic_query
from commands import register_command


def add_args(parser):
    parser.add_argument(
        "query",
        help=(
            "Natural-language or code-fragment query "
            "(e.g. 'user authentication flow', 'parse jwt', 'error handler'). "
            "Symbol names, signatures, kinds, and file paths are all searched."
        ),
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of results to return (default: 10; use 0 for all).",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        metavar="PATH",
        help="Custom path for the SQLite registry database "
             "(default: <workspace>/.codelens/codelens.db).",
    )


def execute(args, workspace) -> Dict[str, Any]:
    """Dispatch to :func:`semantic_engine.semantic_query`.

    The CLI ``--top`` flag is the user-facing name; the engine takes the
    same value as ``top_k``. We pass ``workspace`` and ``db_path`` straight
    through so users can override the database location for ad-hoc queries
    against a snapshot.
    """
    top_k = getattr(args, "top", 10)
    if top_k is None:
        top_k = 10
    db_path = getattr(args, "db_path", None)
    return semantic_query(
        workspace=workspace,
        query=args.query,
        top_k=top_k,
        db_path=db_path,
    )


register_command(
    "semantic-query",
    "Semantic symbol search via TF-IDF (find symbols by meaning, not just name)",
    add_args,
    execute,
hidden=True,
deprecated_alias_for='search',
)
