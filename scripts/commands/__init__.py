"""Command registry for CodeLens CLI.

Issue #195 consolidation: commands carry two optional metadata fields:

- ``hidden`` (bool, default False) — hidden commands are still callable but
  do not appear in ``--help`` output and are excluded from ``--command-count``
  and the MCP tool count. Used for deprecated aliases that point at the new
  umbrella commands.

- ``deprecated_alias_for`` (str|None, default None) — when set, invoking this
  command prints a deprecation warning to stderr that redirects the user to
  the named umbrella command. The old command still executes normally
  (backward compat for one version per issue #195 DoD point 2).
"""

COMMAND_REGISTRY = {}


def register_command(name, help_text, add_args_fn, execute_fn,
                     hidden=False, deprecated_alias_for=None):
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
        excluded from the runtime command count (issue #195).
    deprecated_alias_for : str, optional
        If set, the command is a deprecated alias for the named umbrella
        command. A deprecation warning is printed to stderr before execute.
    """
    COMMAND_REGISTRY[name] = {
        "help": help_text,
        "add_args": add_args_fn,
        "execute": execute_fn,
        "hidden": hidden,
        "deprecated_alias_for": deprecated_alias_for,
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
    umbrella commands rather than the full deprecated-alias set.
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
