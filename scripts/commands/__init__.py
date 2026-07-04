"""Command registry for CodeLens CLI.

Issue #195 consolidated 78 legacy commands into 12 focused umbrella commands.
Each umbrella command accepts a ``--check <category>`` flag to select a
specific sub-analysis. The per-sub-analysis implementations live in sibling
modules under ``scripts/commands/`` and are imported by their umbrella via
:func:`importlib.import_module`.

Commands carry one optional metadata field:

- ``hidden`` (bool, default False) — hidden commands are still callable but
  do not appear in ``--help`` output and are excluded from ``--command-count``
  and the MCP tool count. As of issue #199 the 32 deprecated aliases
  introduced by #195 have been removed entirely (their registrations were
  deleted and the two orphaned modules — ``symbols.py`` and
  ``semantic_query.py`` — were deleted because no umbrella imports them).
  The remaining hidden commands are the 13 pending-decision commands tracked
  by issue #200 (analyze, check, config-drift, deps-audit, entrypoints, lsp,
  list, missing-refs, plugin, query, state-map, test-map, type-infer).
"""

COMMAND_REGISTRY = {}


def register_command(name, help_text, add_args_fn, execute_fn, hidden=False):
    """Register a command with the CLI.

    Parameters
    ----------
    name : str
        Command name as typed on the CLI (e.g. ``"scan"``).
    help_text : str
        One-line description shown in ``--help``. Hidden commands should
        pass ``argparse.SUPPRESS`` so they don't appear in the choices list.
    add_args_fn : callable
        Function ``(parser) -> None`` that adds subparser arguments.
    execute_fn : callable
        Function ``(args, workspace) -> result_dict``.
    hidden : bool, optional
        If True, the command is callable but hidden from ``--help`` and
        excluded from the runtime command count (issues #195/#200).
    """
    COMMAND_REGISTRY[name] = {
        "help": help_text,
        "add_args": add_args_fn,
        "execute": execute_fn,
        "hidden": hidden,
    }


def get_command(name):
    """Get a registered command by name."""
    return COMMAND_REGISTRY.get(name)


def get_all_commands():
    """Get all registered commands (including hidden)."""
    return COMMAND_REGISTRY


def get_visible_commands():
    """Get only non-hidden commands (issue #195).

    Used by ``--command-count``, ``--help`` subparser construction, and
    ``sync_command_count.py`` so the headline count reflects the 12
    umbrella commands rather than the full hidden set.
    """
    return {name: info for name, info in COMMAND_REGISTRY.items()
            if not info.get("hidden", False)}


# Auto-import all command modules to trigger registration
import os
import importlib
import logging

_STRICT_COMMAND_IMPORTS = os.environ.get("CODELENS_STRICT_COMMANDS", "").lower() in {
    "1",
    "true",
    "yes",
}

_commands_dir = os.path.dirname(__file__)
for fname in sorted(os.listdir(_commands_dir)):
    if fname.endswith('.py') and fname != '__init__.py':
        try:
            importlib.import_module(f'.{fname[:-3]}', package='commands')
        except Exception as e:
            if _STRICT_COMMAND_IMPORTS:
                raise
            logging.getLogger('codelens').error(
                f"Failed to import command module '{fname}': {e}"
            )
