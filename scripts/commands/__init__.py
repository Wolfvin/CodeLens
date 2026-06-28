"""Command registry for CodeLens CLI."""

COMMAND_REGISTRY = {}


def register_command(name, help_text, add_args_fn, execute_fn):
    """Register a command with the CLI."""
    COMMAND_REGISTRY[name] = {
        "help": help_text,
        "add_args": add_args_fn,
        "execute": execute_fn,
    }


def get_command(name):
    """Get a registered command by name."""
    return COMMAND_REGISTRY.get(name)


def get_all_commands():
    """Get all registered commands."""
    return COMMAND_REGISTRY


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
