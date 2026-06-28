"""Tests for command module registration and strict import behavior."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
COMMANDS_DIR = SCRIPT_DIR / "commands"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from commands import COMMAND_REGISTRY


def test_every_command_module_registers():
    """Each commands/*.py module must register at least one CLI command."""
    missing = []
    for module_path in sorted(COMMANDS_DIR.glob("*.py")):
        if module_path.name == "__init__.py":
            continue

        module_name = f"commands.{module_path.stem}"
        registered = [
            name
            for name, info in COMMAND_REGISTRY.items()
            if getattr(info["execute"], "__module__", None) == module_name
        ]
        if not registered:
            missing.append(module_path.name)

    assert not missing, (
        "Command modules without register_command(): "
        + ", ".join(missing)
    )


def test_strict_command_imports_fail_fast_on_broken_module():
    """CODELLENS_STRICT_COMMANDS=1 should surface broken command imports."""
    broken_module = COMMANDS_DIR / "_test_broken_import.py"
    broken_module.write_text("def broken(\n", encoding="utf-8")
    env = os.environ.copy()
    env["CODELLENS_STRICT_COMMANDS"] = "1"
    env["PYTHONPATH"] = str(SCRIPT_DIR)

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import importlib; importlib.import_module('commands')",
            ],
            cwd=SCRIPT_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
    finally:
        broken_module.unlink(missing_ok=True)

    assert result.returncode != 0
    assert "SyntaxError" in result.stderr or "_test_broken_import" in result.stderr
