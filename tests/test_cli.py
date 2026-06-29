"""
Tests for the CLI entry point — scan, query, list, init commands.
"""

import os
import sys
import json
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from commands.scan import cmd_scan
from commands.query import cmd_query
from commands.list import cmd_list
from commands.init import cmd_init


def _create_sample_workspace():
    """Create a temporary workspace with sample files for testing."""
    ws = tempfile.mkdtemp()

    # Create HTML file
    with open(os.path.join(ws, "index.html"), 'w') as f:
        f.write('''<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <div id="main-content" class="container main-wrapper">
        <h1 class="header-title">Hello</h1>
        <button id="submit-btn" class="btn btn-primary">Submit</button>
    </div>
</body>
</html>''')

    # Create CSS file
    os.makedirs(os.path.join(ws, "styles"), exist_ok=True)
    with open(os.path.join(ws, "styles", "main.css"), 'w') as f:
        f.write('''
.container { max-width: 1200px; margin: 0 auto; }
.main-wrapper { padding: 20px; }
.header-title { font-size: 2rem; }
.btn { padding: 8px 16px; border: none; cursor: pointer; }
.btn-primary { background: blue; color: white; }
#main-content { background: #fff; }
#submit-btn { font-weight: bold; }
''')

    # Create JS file
    with open(os.path.join(ws, "app.js"), 'w') as f:
        f.write('''
const submitBtn = document.getElementById("submit-btn");
const content = document.querySelector("#main-content");
const buttons = document.querySelectorAll(".btn");

function handleClick() {
    console.log("clicked");
}

function processForm() {
    const data = validateInput();
    return data;
}

function validateInput() {
    return true;
}
''')

    # Create Rust file
    os.makedirs(os.path.join(ws, "src"), exist_ok=True)
    with open(os.path.join(ws, "src", "main.rs"), 'w') as f:
        f.write('''
fn main() {
    let result = verify_token("test");
}

fn verify_token(token: &str) -> bool {
    let hash = hash_token(token);
    hash.len() > 0
}

fn hash_token(token: &str) -> String {
    token.to_string()
}
''')

    return ws


class TestCmdInit:
    """Test the init command."""

    def test_init_creates_codelens_dir(self):
        with tempfile.TemporaryDirectory() as ws:
            result = cmd_init(ws)
            assert result["status"] == "ok"
            assert os.path.isdir(os.path.join(ws, ".codelens"))

    def test_init_creates_config(self):
        with tempfile.TemporaryDirectory() as ws:
            result = cmd_init(ws)
            assert "config" in result
            config_path = os.path.join(ws, ".codelens", "codelens.config.json")
            assert os.path.exists(config_path)


class TestCmdScan:
    """Test the scan command."""

    def test_scan_workspace(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["status"] == "ok"
            assert result["files_scanned"]["html"] >= 1
            assert result["files_scanned"]["css"] >= 1
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_creates_registry(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert os.path.exists(os.path.join(ws, ".codelens", "frontend.json"))
            assert os.path.exists(os.path.join(ws, ".codelens", "backend.json"))
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_finds_classes(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["frontend"]["classes"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_finds_ids(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["frontend"]["ids"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestCmdQuery:
    """Test the query command."""

    def test_query_existing_id(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("submit-btn", ws, domain="frontend")
            assert result["found"] is True
            assert result["type"] == "id"
            assert result["name"] == "submit-btn"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_existing_class(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("btn-primary", ws, domain="frontend")
            assert result["found"] is True
            assert result["type"] == "class"
            assert result["name"] == "btn-primary"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_nonexistent(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("nonexistent-xyz", ws)
            assert result["found"] is False
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_backend_function(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("verify_token", ws, domain="backend")
            assert result["found"] is True
            assert result["type"] == "function"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_auto_detect_domain(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            # Frontend name → should find in frontend
            result = cmd_query("btn-primary", ws)
            assert result["found"] is True
            assert result["domain"] == "frontend"

            # Backend name → should find in backend
            result = cmd_query("verify_token", ws)
            assert result["found"] is True
            assert result["domain"] == "backend"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestCmdList:
    """Test the list command."""

    def test_list_all(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="all", filter_type="all")
            assert result["count"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_dead(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="all", filter_type="dead")
            # Just verify it runs without error and has correct structure
            assert "count" in result
            assert "results" in result
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_frontend_only(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="frontend", filter_type="all")
            assert result["domain"] == "frontend"
            for entry in result["results"]:
                assert entry["type"] in ("class", "id")
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_backend_only(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="backend", filter_type="all")
            assert result["domain"] == "backend"
            for entry in result["results"]:
                assert entry["type"] == "function"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


# ─── check command positional workspace arg (issue #78) ─────────────────


class TestCheckCommandArgs:
    """Regression guard for issue #78: ``check`` command must accept an
    optional positional ``workspace`` argument so the CI quality-gate
    workflow command ``codelens check . --severity high --sarif`` works.

    Before the fix, ``check`` only defined optional flags (``--severity``,
    ``--max-findings``, etc.) and no positional, so argparse rejected the
    ``.`` argument with ``error: unrecognized arguments: .``, failing CI
    for every PR.
    """

    def test_check_accepts_positional_workspace(self):
        """``check`` add_args must register a positional ``workspace``."""
        import argparse
        from commands.check import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        # With positional
        args = parser.parse_args(["/tmp/test", "--severity", "high"])
        assert args.workspace == "/tmp/test"
        assert args.severity == "high"

    def test_check_workspace_optional(self):
        """``check`` without positional must still parse (workspace=None)."""
        import argparse
        from commands.check import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        args = parser.parse_args(["--severity", "high"])
        assert args.workspace is None
        assert args.severity == "high"

    def test_check_full_cli_invocation_with_positional(self):
        """End-to-end: ``codelens check <workspace> --severity high`` must not raise."""
        import subprocess
        import sys

        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)  # build registry so check has something to read
            proc = subprocess.run(
                [sys.executable, "scripts/codelens.py",
                 "check", ws, "--severity", "high", "--format", "json"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONPATH": "scripts"},
            )
            # ``check`` exits 1 when gate fails (which it likely will on the
            # sample workspace) — that's fine, we only care that argparse
            # no longer rejects the positional.
            assert "unrecognized arguments" not in proc.stderr, (
                f"argparse still rejects positional workspace: {proc.stderr}"
            )
            # Output should be valid JSON (gate result), not a usage error
            assert proc.stdout.strip().startswith("{"), (
                f"expected JSON output, got: {proc.stdout[:200]}"
            )
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


# ─── Issue #33: --lsp-status flag and lsp-status subcommand must agree ────


class TestLspStatusEntryPointParity:
    """Regression guard for issue #33.

    Before the fix, ``codelens --lsp-status`` (top-level flag, intercepted in
    ``codelens.py``) called ``hybrid_engine.get_lsp_status()`` while
    ``codelens lsp-status`` (subcommand, ``commands/lsp_status.py``) called
    ``lsp_client.detect_available_servers()`` directly. The two payloads had
    different top-level keys, different per-server fields, and different
    hint/recommendation field names — so CLI users and MCP agents got
    different answers to the same question.

    After the fix, both entry points delegate to ``hybrid_engine.get_lsp_status``
    (single source of truth). These tests assert structural parity: the set of
    top-level keys must be identical, and the set of per-server keys must be
    identical. The byte-identical check is covered by the repro diff in the
    PR description; these tests guard against future regressions in the
    test suite itself.
    """

    @staticmethod
    def _run_codelens(extra_args):
        """Run ``codelens <extra_args> --format json`` and return parsed JSON."""
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             *extra_args, "--format", "json"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONPATH": "scripts"},
        )
        assert proc.returncode == 0, (
            f"codelens {' '.join(extra_args)} failed with rc={proc.returncode}:\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        # Strip any leading non-JSON lines (e.g. workspace auto-detect notices
        # on stderr don't affect stdout, but be defensive).
        idx = proc.stdout.find("{")
        assert idx >= 0, f"No JSON in stdout: {proc.stdout!r}"
        return json.loads(proc.stdout[idx:])

    def test_top_level_keys_match(self):
        """``--lsp-status`` and ``lsp-status`` must have identical top-level keys."""
        flag_payload = self._run_codelens(["--lsp-status"])
        sub_payload = self._run_codelens(["lsp-status"])

        flag_keys = set(flag_payload.keys())
        sub_keys = set(sub_payload.keys())

        assert flag_keys == sub_keys, (
            f"Top-level key sets differ between --lsp-status and lsp-status.\n"
            f"  --lsp-status only: {flag_keys - sub_keys}\n"
            f"  lsp-status   only: {sub_keys - flag_keys}\n"
            f"  common            : {flag_keys & sub_keys}"
        )

    def test_per_server_keys_match(self):
        """Per-server field sets must be identical across both entry points."""
        flag_payload = self._run_codelens(["--lsp-status"])
        sub_payload = self._run_codelens(["lsp-status"])

        flag_servers = flag_payload.get("servers", {})
        sub_servers = sub_payload.get("servers", {})

        # Same set of server names
        assert set(flag_servers.keys()) == set(sub_servers.keys()), (
            f"Server name sets differ:\n"
            f"  --lsp-status only: {set(flag_servers) - set(sub_servers)}\n"
            f"  lsp-status   only: {set(sub_servers) - set(flag_servers)}"
        )

        # For each server, same set of field names
        for name in flag_servers:
            flag_fields = set(flag_servers[name].keys())
            sub_fields = set(sub_servers[name].keys())
            assert flag_fields == sub_fields, (
                f"Per-server field sets differ for server {name!r}:\n"
                f"  --lsp-status only: {flag_fields - sub_fields}\n"
                f"  lsp-status   only: {sub_fields - flag_fields}"
            )

    def test_payloads_byte_identical(self):
        """Full payload equality — the strongest possible parity guarantee.

        Both entry points must produce byte-identical JSON (after canonical
        formatting), not just structural parity. This catches any future
        regression that introduces a divergent field value.
        """
        flag_payload = self._run_codelens(["--lsp-status"])
        sub_payload = self._run_codelens(["lsp-status"])

        assert flag_payload == sub_payload, (
            "Payloads differ between --lsp-status and lsp-status:\n"
            f"  --lsp-status: {json.dumps(flag_payload, sort_keys=True, indent=2)}\n"
            f"  lsp-status  : {json.dumps(sub_payload, sort_keys=True, indent=2)}"
        )
