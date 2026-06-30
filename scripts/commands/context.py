"""context command — DEPRECATED alias for ``query``.

The ``context <symbol>`` command returned a subset of what
``query <symbol>`` already provides (code + callers + callees + quality
metrics). It added no new information, so it was redundant (issue #99).

``context`` still works for backward compatibility but prints a
deprecation warning to stderr and delegates to ``query``'s handler with
the same args. It will be removed in a future release — switch to
``codelens query``.
"""

import sys

from commands import register_command

# Deprecation notice — printed once per invocation to stderr (NOT stdout,
# which is reserved for JSON/machine-readable output). Surfaced in both
# interactive and CI usage so users notice and migrate before the alias
# is removed.
_DEPRECATION_WARNING = (
    "DEPRECATED: codelens context is renamed to codelens query. "
    "Use query instead.\n"
)


def add_args(parser):
    """Register context (deprecated alias) arguments.

    Kept compatible with the legacy ``context`` interface so existing
    scripts keep parsing. Flags that ``query`` does not understand
    (``--context-lines``, ``--no-code``) are accepted but ignored —
    output now comes from ``query``.
    """
    parser.add_argument("name", help="Symbol name")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend", "auto"], default="auto",
                        help="Domain")
    parser.add_argument("--context-lines", type=int, default=5,
                        help="Lines of code context around symbol (default 5)")
    parser.add_argument("--no-code", action="store_true", help="Skip source code in output")


def execute(args, workspace):
    """Execute the deprecated context command.

    Prints a deprecation warning to stderr, then delegates to
    ``query``'s handler with the same args.

    Args:
        args: Parsed argparse namespace (``name``, ``workspace``, ...).
        workspace: Resolved workspace root path.

    Returns:
        Dict with the query result.
    """
    print(_DEPRECATION_WARNING, file=sys.stderr, end="")

    # Lazy import to avoid module-load-order coupling between command
    # modules (commands/__init__.py auto-imports all of them in sorted
    # order, and ``context`` sorts before ``query``).
    from commands import query as query_cmd

    # Normalize args for query compatibility. ``query.execute`` reads
    # ``args.file`` directly and treats ``args.domain`` of None as
    # "search both domains". ``context`` allowed ``--domain auto``
    # (default) which query does not understand — map it to None.
    # query uses getattr-with-default for ``all``/``limit``/``fuzzy`` so
    # those are safe, but ``file`` must exist as an attribute.
    if not hasattr(args, "file"):
        args.file = None
    if getattr(args, "domain", None) == "auto":
        args.domain = None

    return query_cmd.execute(args, workspace)


register_command(
    "context",
    "DEPRECATED — use `query` instead",
    add_args,
    execute,
)
