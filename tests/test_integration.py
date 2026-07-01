"""
Integration smoke tests for all 68 CodeLens commands.

Tests that every command:
1. Runs without crash (valid JSON output)
2. Accepts --format markdown without crash
3. Decision tree fields present where expected
4. Health score is never 0 for a functional project
"""

import subprocess
import json
import sys
import os
import tempfile
import shutil
import pytest

# Path to codelens CLI
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
CODELENS = sys.executable + ' ' + os.path.join(SCRIPT_DIR, 'codelens.py')
WORKSPACE = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..'))


def run_command(cmd_str, timeout=120):
    """Run a codelens command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        f'{CODELENS} {cmd_str}',
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=WORKSPACE
    )
    return result.returncode, result.stdout, result.stderr


def parse_json(stdout):
    """Extract JSON from codelens output (skipping [CodeLens] prefix lines)."""
    lines = stdout.strip().split('\n')
    json_lines = []
    for line in lines:
        if line.startswith('[CodeLens]'):
            continue
        json_lines.append(line)
    return json.loads('\n'.join(json_lines))


# ─── Commands that work with just workspace ─────────────────────

NO_ARGS_COMMANDS = [
    "scan", "list", "handbook", "symbols", "trace", "impact",
    "outline", "missing-refs", "circular", "dependents",
    "dataflow", "smell", "side-effect", "dead-code", "test-map",
    "config-drift", "type-infer", "ownership", "secrets",
    "entrypoints", "api-map", "state-map", "env-check", "debug-leak",
    "complexity", "regex-audit", "vuln-scan", "perf-hint", "css-deep",
    "a11y",
]

# Commands that need special arguments
SPECIAL_COMMANDS = {
    "query": "query cmd_scan",
    "context": "context cmd_scan",
    "ask": 'ask "dead code"',
    "search": 'search "def "',
    "refactor-safe": "refactor-safe cmd_scan",
    "stack-trace": "stack-trace cmd_scan",
}

# Commands that need a temp workspace
TEMP_WS_COMMANDS = ["init", "detect"]


# ─── Smoke Tests ────────────────────────────────────────────────

class TestAllCommandsJSON:
    """Every command must produce valid JSON output."""

    @pytest.mark.parametrize("cmd", NO_ARGS_COMMANDS)
    def test_no_args_command_json(self, cmd):
        rc, stdout, stderr = run_command(f'{cmd} .')
        assert rc == 0, f"{cmd} failed with rc={rc}: {stderr[:200]}"
        data = parse_json(stdout)
        # Should have at least one recognizable field
        assert any(k in data for k in ["status", "found", "domain", "total", "meta", "workspace"]), \
            f"{cmd} returned unexpected structure: {list(data.keys())[:5]}"

    @pytest.mark.parametrize("cmd_name,cmd_str", SPECIAL_COMMANDS.items())
    def test_special_command_json(self, cmd_name, cmd_str):
        rc, stdout, stderr = run_command(f'{cmd_str} .')
        assert rc == 0, f"{cmd_name} failed with rc={rc}: {stderr[:200]}"
        data = parse_json(stdout)
        assert isinstance(data, dict), f"{cmd_name} did not return a dict"

    @pytest.mark.parametrize("cmd", TEMP_WS_COMMANDS)
    def test_temp_ws_command_json(self, cmd):
        with tempfile.TemporaryDirectory() as td:
            # Create a minimal source file
            with open(os.path.join(td, 'app.py'), 'w') as f:
                f.write('def hello():\n    print("hello")\n')
            rc, stdout, stderr = run_command(f'{cmd} {td}')
            assert rc == 0, f"{cmd} failed with rc={rc}: {stderr[:200]}"
            data = parse_json(stdout)
            assert isinstance(data, dict), f"{cmd} did not return a dict"


class TestAllCommandsMarkdown:
    """Every command must accept --format markdown without crash."""

    @pytest.mark.parametrize("cmd", NO_ARGS_COMMANDS)
    def test_no_args_command_markdown(self, cmd):
        rc, stdout, stderr = run_command(f'--format markdown {cmd} .')
        assert rc == 0, f"{cmd} --format markdown failed with rc={rc}: {stderr[:200]}"
        assert len(stdout) > 0, f"{cmd} --format markdown produced no output"

    @pytest.mark.parametrize("cmd_name,cmd_str", SPECIAL_COMMANDS.items())
    def test_special_command_markdown(self, cmd_name, cmd_str):
        rc, stdout, stderr = run_command(f'--format markdown {cmd_str} .')
        assert rc == 0, f"{cmd_name} --format markdown failed with rc={rc}: {stderr[:200]}"
        assert len(stdout) > 0, f"{cmd_name} --format markdown produced no output"


# ─── Decision Tree Tests ────────────────────────────────────────

class TestDecisionTrees:
    """Key commands must include actionable decision-tree fields."""

    def test_query_has_action_fields(self):
        rc, stdout, _ = run_command('query cmd_scan .')
        assert rc == 0
        data = parse_json(stdout)
        assert "action" in data, "query missing 'action' field"
        assert "action_reason" in data, "query missing 'action_reason' field"
        assert data["action"] in ("CREATE", "EXTEND", "ASK", "LIST_FIRST", "STOP"), \
            f"query action has unexpected value: {data['action']}"

    def test_query_not_found_has_create(self):
        rc, stdout, _ = run_command('query zzz_nonexistent_xyz .')
        assert rc == 0
        data = parse_json(stdout)
        assert data.get("action") == "CREATE", f"Query for nonexistent name should be CREATE, got {data.get('action')}"

    def test_impact_has_risk_level(self):
        rc, stdout, _ = run_command('impact cmd_scan .')
        assert rc == 0
        data = parse_json(stdout)
        assert "risk_level" in data, "impact missing 'risk_level' field"
        assert data["risk_level"] in ("low", "medium", "high", "critical"), \
            f"impact risk_level has unexpected value: {data['risk_level']}"

    def test_smell_has_actionable_items(self):
        rc, stdout, _ = run_command('smell .')
        assert rc == 0
        data = parse_json(stdout)
        assert "actionable_items" in data, "smell missing 'actionable_items' field"
        if data["actionable_items"]:
            item = data["actionable_items"][0]
            assert "action" in item, "smell actionable_item missing 'action'"
            assert "category" in item, "smell actionable_item missing 'category'"

    def test_dead_code_has_removal_safety(self):
        rc, stdout, _ = run_command('dead-code .')
        assert rc == 0
        data = parse_json(stdout)
        assert "removal_safety" in data, "dead-code missing 'removal_safety' field"
        assert "recommended_action" in data, "dead-code missing 'recommended_action' field"


# ─── Health Score Tests ─────────────────────────────────────────

class TestHealthScore:
    """Health score should never be 0 for a functional project."""

    def test_health_score_not_zero(self):
        rc, stdout, _ = run_command('smell .')
        assert rc == 0
        data = parse_json(stdout)
        score = data.get("stats", {}).get("health_score", 0)
        assert score > 0, f"Health score should be > 0 for a functional project, got {score}"

    def test_health_score_in_handbook(self):
        rc, stdout, _ = run_command('handbook .')
        assert rc == 0
        data = parse_json(stdout)
        score = data.get("health", {}).get("score", 0)
        assert score > 0, f"Handbook health score should be > 0, got {score}"

    def test_health_score_range(self):
        rc, stdout, _ = run_command('smell .')
        assert rc == 0
        data = parse_json(stdout)
        score = data.get("stats", {}).get("health_score", 0)
        assert 0 <= score <= 100, f"Health score should be 0-100, got {score}"


# ─── Context Quality Metrics Tests ─────────────────────────────

class TestContextQuality:
    """Context command should include quality metrics."""

    def test_context_has_quality_block(self):
        rc, stdout, _ = run_command('context cmd_scan .')
        assert rc == 0
        data = parse_json(stdout)
        if data.get("found") and data.get("context"):
            quality = data["context"].get("quality", {})
            assert "safety" in quality, "context quality missing 'safety' field"
            assert quality["safety"] in ("safe_to_remove", "safe_to_modify", "caution", "high_impact"), \
                f"context quality.safety has unexpected value: {quality['safety']}"


# ─── Handbook Tests ─────────────────────────────────────────────

class TestHandbook:
    """Handbook command should produce comprehensive output."""

    def test_handbook_has_all_sections(self):
        rc, stdout, _ = run_command('handbook .')
        assert rc == 0
        data = parse_json(stdout)
        assert "meta" in data, "handbook missing 'meta'"
        assert "identity" in data, "handbook missing 'identity'"
        assert "structure" in data, "handbook missing 'structure'"
        assert "health" in data, "handbook missing 'health'"
        assert "conventions" in data, "handbook missing 'conventions'"

    def test_handbook_writes_files(self):
        run_command('handbook .')
        assert os.path.exists(os.path.join(WORKSPACE, '.codelens', 'handbook.json'))
        assert os.path.exists(os.path.join(WORKSPACE, '.codelens', 'AGENT.md'))

    def test_handbook_conventions_has_naming(self):
        rc, stdout, _ = run_command('handbook .')
        assert rc == 0
        data = parse_json(stdout)
        conventions = data.get("conventions", {})
        assert "naming" in conventions, "handbook conventions missing 'naming'"


# ─── Ask Command Tests ──────────────────────────────────────────

class TestAskCommand:
    """Ask command should route natural language to the right command."""

    def test_ask_dead_code(self):
        rc, stdout, _ = run_command('ask "dead code" .')
        assert rc == 0
        data = parse_json(stdout)
        # Should route to dead-code which has 'stats' key
        assert "stats" in data or "status" in data

    def test_ask_api_routes(self):
        rc, stdout, _ = run_command('ask "API routes" .')
        assert rc == 0
        data = parse_json(stdout)
        # Should route to api-map which has 'routes' key
        assert "routes" in data or "status" in data

    def test_ask_has_interpretation(self):
        rc, stdout, _ = run_command('ask "dead code" .')
        assert rc == 0
        data = parse_json(stdout)
        assert "query_interpretation" in data, "ask output missing query_interpretation"


# ─── Module Structure Tests ─────────────────────────────────────

class TestModuleStructure:
    """Verify the module structure is properly set up."""

    def test_commands_dir_exists(self):
        assert os.path.isdir(os.path.join(SCRIPT_DIR, 'commands'))

    def test_formatters_dir_exists(self):
        assert os.path.isdir(os.path.join(SCRIPT_DIR, 'formatters'))

    def test_command_registry_has_all_commands(self):
        """Strict regression sentinel for command count (issue #38).

        The previous assertion (``>= 41``) was trivially satisfied and would
        not catch silent command loss — every command could disappear and the
        test would still pass. This strict assertion fails whenever the
        command count changes in either direction.

        When this test fails, it means a command was added or removed. To fix:

        1. Confirm the change is intentional (you meant to add/remove a command).
        2. Update ``EXPECTED_COMMAND_COUNT`` below to match the new count.
        3. Run ``python3 scripts/sync_command_count.py --apply`` to propagate
           the new count to all documentation and metadata files
           (README.md, SKILL.md, SKILL-QUICK.md, pyproject.toml, skill.json,
           scripts/mcp_server.py, scripts/graph_model.py, this file's docstring).
        4. Re-run the test suite to confirm green.

        The sentinel is intentionally a literal — it is the one place where
        the count is allowed to be hardcoded, because the test's whole purpose
        is to detect drift against a frozen reference.
        """
        sys.path.insert(0, SCRIPT_DIR)
        from commands import COMMAND_REGISTRY
        # Regression sentinel — see docstring above for update procedure.
        # Bumped 67 → 68 for issue #64 Phase 1: added `doctor` command.
        EXPECTED_COMMAND_COUNT = 68
        actual = len(COMMAND_REGISTRY)
        assert actual == EXPECTED_COMMAND_COUNT, (
            f"Command count drift detected: expected {EXPECTED_COMMAND_COUNT}, "
            f"got {actual}. If intentional: (1) update EXPECTED_COMMAND_COUNT "
            f"in this test, (2) run "
            f"`PYTHONPATH=scripts python3 scripts/sync_command_count.py --apply` "
            f"to sync all docs/metadata."
        )

    def test_fallback_parsers_exist(self):
        fallback_dir = os.path.join(SCRIPT_DIR, 'parsers')
        for name in ['fallback_html.py', 'fallback_css.py', 'fallback_js_frontend.py',
                      'fallback_js_backend.py', 'fallback_rust.py', 'fallback_python.py']:
            assert os.path.exists(os.path.join(fallback_dir, name)), f"Missing fallback parser: {name}"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
