"""Architecture command — single-call codebase overview for AI agents (issue #19).

Registers the `architecture` CLI command and `codelens_architecture` MCP tool.
The heavy lifting lives in `architecture_engine.get_architecture`.

Examples:
    # Full overview (default) — ~2-4k tokens
    python3 codelens.py architecture /path/to/workspace

    # Lite overview — under 1k tokens (omits routes/packages/hotspots)
    python3 codelens.py architecture /path/to/workspace --lite
"""

from commands import register_command
from architecture_engine import get_architecture


def add_args(parser):
    """Register architecture command arguments with the argparse parser."""
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--lite",
        action="store_true",
        default=False,
        help="Lite mode: only return languages, frameworks, entry_points, "
             "and total_symbols (omits routes/packages/hotspots). "
             "Targets <1k tokens output for cheap agent orientation.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Ignore any existing .codelens/architecture_cache.json and "
             "rebuild the overview from scratch. The cache is rewritten.",
    )


def execute(args, workspace):
    """Run the architecture command and return its payload.

    Args:
        args: Parsed argparse Namespace with .lite and .no_cache attributes.
        workspace: Resolved workspace path.

    Returns:
        Dict payload from architecture_engine.get_architecture.
    """
    lite = bool(getattr(args, "lite", False))
    no_cache = bool(getattr(args, "no_cache", False))

    if no_cache:
        # Bust the cache by removing the file before building.
        import os
        cache_path = os.path.join(workspace, ".codelens", "architecture_cache.json")
        try:
            if os.path.isfile(cache_path):
                os.remove(cache_path)
        except OSError:
            pass

    return get_architecture(workspace, lite=lite)


register_command(
    "architecture",
    "Single-call codebase overview for AI agents (languages, frameworks, "
    "entry points, packages, routes, hotspots, total symbols)",
    add_args,
    execute,
)
