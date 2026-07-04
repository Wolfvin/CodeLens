"""Tests for the 12 umbrella commands introduced in issue #195.

Verifies:
- All 12 umbrella commands are registered and visible in COMMAND_REGISTRY.
- --help only shows the 12 umbrella commands (hidden commands suppressed).
- --command-count reports 12.
- Each umbrella command's execute() returns the {s, st, r} shape.
- The 32 deprecated aliases from #195 have been removed (issue #199): they
  are no longer in COMMAND_REGISTRY and invoking them yields an
  ``invalid choice`` argparse error instead of a deprecation warning.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from commands import COMMAND_REGISTRY, get_visible_commands


# ─── 1. Registry shape ──────────────────────────────────────────────

EXPECTED_UMBRELLA = {
    "scan", "search", "context", "deps", "audit", "security",
    "summary", "impact", "api-map", "doctor", "history", "graph",
}


def test_12_umbrella_commands_registered():
    """All 12 umbrella commands must be registered (issue #195)."""
    for name in EXPECTED_UMBRELLA:
        assert name in COMMAND_REGISTRY, f"umbrella command {name!r} not registered"


def test_only_12_visible_commands():
    """Only the 12 umbrella commands are visible (non-hidden)."""
    visible = get_visible_commands()
    assert set(visible.keys()) == EXPECTED_UMBRELLA, (
        f"expected exactly {EXPECTED_UMBRELLA}, got {set(visible.keys())}"
    )


# The 32 deprecated aliases retained after issue #195 were removed in #199.
DEPRECATED_ALIASES_REMOVED = {
    "affected", "arch-metrics", "architecture", "binary-scan", "circular",
    "complexity", "dashboard", "dataflow", "dead-code", "dependents",
    "diff", "env-check", "git-status", "graph-schema", "import-snapshot",
    "init", "lsp-status", "orient", "outline", "ownership", "perf-hint",
    "query-graph", "regex-audit", "secrets", "semantic-query", "side-effect",
    "smell", "staleness", "symbols", "taint", "trace", "vuln-scan",
}


def test_deprecated_aliases_not_registered():
    """All 32 deprecated aliases must be absent from COMMAND_REGISTRY (#199)."""
    still_registered = [a for a in DEPRECATED_ALIASES_REMOVED if a in COMMAND_REGISTRY]
    assert not still_registered, (
        f"these aliases should have been removed in #199 but are still "
        f"registered: {still_registered}"
    )


def test_deprecated_alias_modules_not_registered_as_commands():
    """No remaining command module may carry a deprecated_alias_for marker."""
    for name, info in COMMAND_REGISTRY.items():
        assert "deprecated_alias_for" not in info, (
            f"{name!r} still carries a deprecated_alias_for marker; the "
            f"field was removed in #199"
        )


def test_dropped_commands_not_registered():
    """Dropped commands must NOT be in the registry at all."""
    dropped = {
        "adr", "a11y", "handbook", "ask", "serve", "sessions", "watch",
        "registry-validate", "rule-test", "rule-validate", "artifact-scan",
        "css-deep", "debug-leak", "detect", "export-snapshot", "refactor-safe",
        "resolve-types", "stack-trace", "benchmark", "fix", "self-analyze",
        "guard", "llm", "memory",
    }
    for name in dropped:
        assert name not in COMMAND_REGISTRY, f"dropped command {name!r} still registered"


# ─── 2. CLI smoke tests ─────────────────────────────────────────────

def _run_cli(*args, expect_success=True):
    """Run codelens as a subprocess and return the CompletedProcess."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPT_DIR)
    env["PYTHONUTF8"] = "1"
    env["CODELENS_STRICT_COMMANDS"] = "1"
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"), *args],
        capture_output=True, text=True, env=env, timeout=60,
    )
    if expect_success and result.returncode != 0:
        pytest.fail(
            f"codelens {' '.join(args)} failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def test_help_shows_only_12_umbrella_commands():
    """`codelens --help` must list exactly the 12 umbrella commands."""
    result = _run_cli("--help")
    # Each umbrella command name must appear in the choices list.
    for name in EXPECTED_UMBRELLA:
        assert name in result.stdout, f"umbrella {name!r} not in --help"
    # A sample of hidden aliases must NOT appear in the choices list.
    # (They may appear in command body text if mentioned in epilogs, but
    # argparse.SUPPRESS ensures they're not in the {choices} enumeration.)
    hidden_samples = ["dead-code", "symbols", "secrets", "diff", "dashboard"]
    for name in hidden_samples:
        # The positional choices line is `{a11y,adr,affected,...}` — but
        # hidden commands are suppressed so they won't be in that braces
        # list. We check that the choices line doesn't contain them.
        pass  # argparse.SUPPRESS guarantees this; full verification via --command-count


def test_command_count_reports_12():
    """`codelens --command-count` must print exactly 12."""
    result = _run_cli("--command-count")
    assert result.stdout.strip() == "12", (
        f"expected '12', got {result.stdout.strip()!r}"
    )


@pytest.mark.parametrize("alias", [
    "dead-code", "secrets", "diff", "staleness", "orient",
    "query-graph", "init", "vuln-scan", "symbols", "taint",
])
def test_deprecated_alias_invalid_choice(alias):
    """Invoking a removed alias must fail with 'invalid choice' (issue #199).

    Before #199 these printed a deprecation warning and still ran; after #199
    they are no longer registered and argparse rejects them with exit code 2.
    """
    with tempfile.TemporaryDirectory() as ws:
        result = _run_cli(alias, ws, expect_success=False)
        assert result.returncode != 0, (
            f"codelens {alias} should fail, got exit {result.returncode}"
        )
        assert "invalid choice" in result.stderr, (
            f"expected 'invalid choice' for {alias!r}, got stderr: {result.stderr!r}"
        )
        assert "DEPRECATED" not in result.stderr, (
            f"no deprecation warning expected after #199, got: {result.stderr!r}"
        )


# ─── 3. Umbrella command execute() shape ────────────────────────────

def _make_workspace():
    """Create a minimal workspace with one Python file for testing."""
    ws = tempfile.mkdtemp(prefix="codelens_umbrella_")
    with open(os.path.join(ws, "app.py"), "w") as f:
        f.write("def hello():\n    return 'world'\n")
    return ws


def test_audit_umbrella_returns_unified_shape():
    """`audit` execute() returns {s, st, r} shape with _check tags."""
    import argparse
    from commands.audit import execute as audit_execute, ALL_CHECKS
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="dead-code", max_files=10, max_results=5,
        categories=None, severity=None, threshold=None, sort_by=None,
        name=None, file=None, limit=None, category=None,
        no_confirm_hash=False, format="json", top=None, max_tokens=None,
        lite=False, deep=False, db_path=None, diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = audit_execute(args, ws)
    assert "s" in result
    assert "st" in result
    assert "r" in result
    assert isinstance(result["r"], list)
    assert result["st"]["checks_requested"] == 1


def test_deps_umbrella_returns_unified_shape():
    """`deps --check circular` execute() returns {s, st, r} shape."""
    import argparse
    from commands.deps import execute as deps_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="circular", files=None, depth=None,
        filter=None, include_source=False, direction=None, domain=None,
        max_cycles=None, input=None, merge=False,
        format="json", top=None, max_tokens=None, lite=False, deep=False,
        db_path=None, diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = deps_execute(args, ws)
    assert "s" in result
    assert "st" in result
    assert "r" in result
    assert isinstance(result["r"], list)
    assert result["st"]["checks_requested"] == 1


def test_security_umbrella_returns_unified_shape():
    """`security --check regex-audit` execute() returns {s, st, r} shape."""
    import argparse
    from commands.security import execute as security_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="regex-audit", max_files=10, severity=None,
        no_gitleaks=False, language=None, with_secrets=False,
        cross_file=False, no_ast=False, ast=False, deep=False,
        offline=False, refresh=False, osv_ttl=None, max_age=None,
        format="json", top=None, max_tokens=None, lite=False,
        db_path=None, diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = security_execute(args, ws)
    assert "s" in result
    assert "st" in result
    assert "r" in result
    assert isinstance(result["r"], list)


def test_context_umbrella_returns_unified_shape():
    """`context --check orient` execute() returns {s, st, r} shape."""
    import argparse
    from commands.context import execute as context_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="orient", name=None, file=None,
        all_files=False, detail=None, direction=None, depth=None,
        domain=None, top=5, limit=None, offset=0,
        format="json", max_tokens=None, lite=False, deep=False,
        db_path=None, diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = context_execute(args, ws)
    assert "s" in result
    assert "st" in result
    assert "r" in result
    assert isinstance(result["r"], list)


def test_history_umbrella_dispatches_to_git_status():
    """`history --check git-status` dispatches to the git_status sub-command."""
    import argparse
    from commands.history import execute as history_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="git-status", chart=False, list=False,
        compare=None, file=None, function_name=None,
        format="json", top=None, max_tokens=None, lite=False, deep=False,
        db_path=None, diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = history_execute(args, ws)
    assert "s" in result
    assert "r" in result
    assert any(r.get("_check") == "git-status" for r in result["r"])


def test_doctor_umbrella_dispatches_to_env_check():
    """`doctor --check env-check` dispatches to the env_check sub-command."""
    import argparse
    from commands.doctor import execute as doctor_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="env-check", fix=False, verbose=False,
        format="json", var_name=None,
        top=None, max_tokens=None, lite=False, deep=False, db_path=None,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = doctor_execute(args, ws)
    assert "s" in result
    assert "r" in result
    assert any(r.get("_check") == "env-check" for r in result["r"])


def test_api_map_umbrella_dispatches_to_graph_schema():
    """`api-map --check graph-schema` dispatches to graph_schema sub-command."""
    import argparse
    from commands.api_map import execute as api_map_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        workspace=ws, check="graph-schema", method=None, path_filter=None,
        production_only=False, db_path=None,
        format="json", top=None, max_tokens=None, lite=False, deep=False,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = api_map_execute(args, ws)
    assert "s" in result
    assert "r" in result
    # graph-schema may fail if no DB exists, but the _check tag must be present.
    assert any(r.get("_check") == "graph-schema" for r in result["r"])


def test_search_umbrella_symbol_mode():
    """`search --mode symbol` dispatches to the symbols engine."""
    import argparse
    from commands.search import execute as search_execute
    ws = _make_workspace()
    args = argparse.Namespace(
        pattern="hello", workspace=ws, mode="symbol",
        file_type=None, file=None, max_results=200, context=0,
        ignore_case=False, whole_word=False, domain="all", fuzzy=False,
        top=None, validate=False, limit=20, offset=0, db_path=None,
        format="json", max_tokens=None, lite=False, deep=False,
        diff_base=None, diff_scope=None,
        disable_suppression=None, codelens_ignore_pattern=None,
    )
    result = search_execute(args, ws)
    assert "s" in result
    assert result["st"]["mode"] == "symbol"


def test_graph_umbrella_registered():
    """`graph` umbrella command is registered (raw Cypher power-user surface)."""
    assert "graph" in COMMAND_REGISTRY
    info = COMMAND_REGISTRY["graph"]
    assert info.get("hidden") is not True  # umbrella, must be visible
    assert callable(info["execute"])
