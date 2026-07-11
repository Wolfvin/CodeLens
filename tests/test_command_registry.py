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
    """Each commands/*.py module must register at least one CLI command.

    Issue #195: a small allowlist of utility modules (kept for backward
    compat with tests/scripts but not registered as commands) is excluded.

    Issue #199: the 30 deprecated alias modules retained after #195 had
    their register_command() calls removed. They survive as implementation
    modules imported by the 12 umbrella commands via importlib (e.g.
    audit.py imports commands.dead_code, security.py imports
    commands.secrets). Their .py files are kept; only the CLI alias
    registration is gone. The 2 alias modules that no umbrella imports
    (symbols.py, semantic_query.py) were deleted entirely.
    """
    # Issue #195: migrate.py is a utility wrapper around
    # PersistentRegistry.migrate_from_json, kept so existing tests that
    # import cmd_migrate continue to work. It does NOT register a command
    # (migrate was dropped per the consolidation).
    _UTILITY_MODULES = {"migrate"}
    # Issue #199: these modules are implementation-only — their
    # register_command() calls were removed because the CLI alias is gone,
    # but the umbrella commands import them for --check sub-analyses.
    _DEPRECATED_ALIAS_MODULES = {
        "affected", "arch_metrics", "architecture", "binary_scan",
        "circular", "complexity", "dashboard", "dataflow", "dead_code",
        "dependents", "diff", "env_check", "git_status", "graph_schema",
        "import_snapshot", "init", "lsp_status", "orient", "outline",
        "ownership", "perf_hint", "query_graph", "regex_audit", "secrets",
        "side_effect", "smell", "staleness", "taint", "trace", "vuln_scan",
    }
    _UTILITY_MODULES |= _DEPRECATED_ALIAS_MODULES
    missing = []
    for module_path in sorted(COMMANDS_DIR.glob("*.py")):
        if module_path.name == "__init__.py":
            continue
        if module_path.stem in _UTILITY_MODULES:
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
    """CODELENS_STRICT_COMMANDS=1 should surface broken command imports."""
    broken_module = COMMANDS_DIR / "_test_broken_import.py"
    broken_module.write_text("def broken(\n", encoding="utf-8")
    env = os.environ.copy()
    env["CODELENS_STRICT_COMMANDS"] = "1"
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
