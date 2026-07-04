"""
Doc-sync enforcement tests for command / MCP tool counts (issue #38).

These tests fail in CI before a PR can merge if any documentation or metadata
file mentions a stale command count. The single source of truth is the runtime
``COMMAND_REGISTRY`` (and ``_TOOL_DEFINITIONS`` for MCP static tool count); the
``scripts/sync_command_count.py`` helper propagates the runtime count into all
docs.

If any test in this file fails, run::

    PYTHONPATH=scripts python3 scripts/sync_command_count.py --apply

and commit the result. The strict sentinel for the command count itself lives
in ``tests/test_integration.py`` (``TestModuleStructure.test_command_registry_has_all_commands``).
"""

import os
import subprocess
import sys

import pytest

# Path to the project root and scripts dir.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")


def _run_sync_check() -> subprocess.CompletedProcess:
    """Run sync_command_count.py --check as a subprocess and return its result."""
    return subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS_DIR, "sync_command_count.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": _SCRIPTS_DIR},
        timeout=60,
    )


def test_command_count_helper_matches_runtime_registry():
    """The sync helper's reported count must equal the visible (non-hidden) count.

    Issue #195: ``get_command_count`` counts only visible umbrella commands
    (12), not the hidden deprecated aliases still present in
    ``COMMAND_REGISTRY`` for backward compat. The headline count must match
    what ``--help`` and ``--command-count`` show.
    """
    sys.path.insert(0, _SCRIPTS_DIR)
    from commands import COMMAND_REGISTRY, get_visible_commands  # type: ignore
    from sync_command_count import get_command_count  # type: ignore

    visible = get_visible_commands()
    assert get_command_count() == len(visible), (
        f"get_command_count()={get_command_count()} != "
        f"len(visible)={len(visible)} (total registry={len(COMMAND_REGISTRY)})"
    )


def test_mcp_tool_count_math_is_consistent():
    """MCP total = (visible commands not in {watch, serve}); static + dynamic = total.

    Issue #195: hidden deprecated aliases are excluded from MCP tool exposure.
    Catches the kind of drift that caused issue #38's MCP tool count
    inconsistency (README said 55, SKILL said 54, SKILL-QUICK said 58).
    """
    sys.path.insert(0, _SCRIPTS_DIR)
    from commands import COMMAND_REGISTRY  # type: ignore
    from sync_command_count import get_mcp_counts, _MCP_EXCLUDED_COMMANDS  # type: ignore

    total, static, dynamic = get_mcp_counts()
    # Expected = visible commands (non-hidden) minus excluded long-running ones.
    expected_total = sum(
        1 for name, info in COMMAND_REGISTRY.items()
        if name not in _MCP_EXCLUDED_COMMANDS
        and not info.get("hidden", False)
    )
    assert total == expected_total, (
        f"MCP total {total} != expected {expected_total} "
        f"(visible commands minus excluded {sorted(_MCP_EXCLUDED_COMMANDS)})"
    )
    assert static + dynamic == total, (
        f"static({static}) + dynamic({dynamic}) != total({total})"
    )
    assert dynamic >= 0, f"dynamic count went negative: {dynamic} (static > total)"


def test_all_docs_in_sync_with_command_registry():
    """Every doc/metadata file must mention the current command/MCP counts.

    Runs ``sync_command_count.py --check`` and fails if any file would be
    changed. This is the test that catches stale numbers before merge.

    Fix failures by running::

        PYTHONPATH=scripts python3 scripts/sync_command_count.py --apply
    """
    result = _run_sync_check()
    assert result.returncode == 0, (
        "Documentation is out of sync with COMMAND_REGISTRY.\n"
        "--- sync_command_count.py --check stdout ---\n"
        f"{result.stdout}\n"
        "--- sync_command_count.py --check stderr ---\n"
        f"{result.stderr}\n"
        "Fix: run `PYTHONPATH=scripts python3 scripts/sync_command_count.py --apply` "
        "and commit the result."
    )


def test_sync_helper_idempotent_after_apply():
    """Running --apply twice must produce zero changes on the second run.

    Guards against the sync script introducing drift of its own (e.g. a regex
    that mangles a previously-synced line into a form the regex no longer
    matches).
    """
    # First apply to ensure baseline (we use --check first to confirm state;
    # if --check passes we're already in sync; if it fails the previous test
    # would have failed too).
    apply1 = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS_DIR, "sync_command_count.py"), "--apply"],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": _SCRIPTS_DIR},
        timeout=60,
    )
    assert apply1.returncode == 0, f"first --apply failed: {apply1.stderr}"

    # Second apply must report 0 files changed.
    apply2 = subprocess.run(
        [sys.executable, os.path.join(_SCRIPTS_DIR, "sync_command_count.py"), "--apply"],
        capture_output=True,
        text=True,
        cwd=_PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": _SCRIPTS_DIR},
        timeout=60,
    )
    assert apply2.returncode == 0, f"second --apply failed: {apply2.stderr}"
    assert "0 file(s)" in apply2.stdout or "All documentation files are in sync" in apply2.stdout, (
        "Second --apply should be a no-op but reported changes:\n"
        f"{apply2.stdout}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
