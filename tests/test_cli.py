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
from codelens import _apply_top_n, _NO_TOP_KEYS


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


# ─── --top N universal truncation (issue #36) ──────────────────


class TestTopNUniversalTruncation:
    """Regression guard for issue #36: --top N must truncate ALL list-valued
    keys in command output, not just those in a hardcoded allowlist.

    Before the fix, ``_apply_top_n`` only truncated keys listed in ``_LIST_KEYS``
    (28 names). A new command returning a list under a non-standard key (e.g.,
    ``entities``, ``my_things``, ``nodes``) would silently ignore ``--top N``,
    violating the documented *"Limit list results to top N items"* contract from
    ``SKILL-QUICK.md`` and risking token overflow for MCP clients.

    The fix replaces the allowlist with runtime auto-discovery: every top-level
    list-valued key is truncated, except those in ``_NO_TOP_KEYS`` (structural/
    metadata keys like ``available_commands``).
    """

    def test_non_standard_key_gets_truncated(self):
        """A hypothetical key name not in any allowlist must still be truncated."""
        result = {"status": "ok", "entities": [{"id": i} for i in range(100)]}
        out = _apply_top_n(result, 5)
        assert len(out["entities"]) == 5, (
            f"Expected 5 items after truncation, got {len(out['entities'])}. "
            "Non-standard key 'entities' was not truncated by --top."
        )
        assert out["entities_truncated"] is True
        assert out["entities_total"] == 100

    def test_multiple_non_standard_keys_truncated(self):
        """Multiple non-standard list keys must all be truncated."""
        result = {
            "status": "ok",
            "widgets": [{"id": i} for i in range(50)],
            "gadgets": [{"id": i} for i in range(30)],
        }
        out = _apply_top_n(result, 10)
        assert len(out["widgets"]) == 10
        assert len(out["gadgets"]) == 10
        assert out["widgets_truncated"] is True
        assert out["gadgets_truncated"] is True

    def test_no_top_keys_exempt(self):
        """Keys in _NO_TOP_KEYS must NOT be truncated even if they're lists."""
        result = {
            "status": "ok",
            "available_commands": [f"cmd_{i}" for i in range(50)],
        }
        out = _apply_top_n(result, 5)
        assert len(out["available_commands"]) == 50, (
            "available_commands should NOT be truncated (it's in _NO_TOP_KEYS)"
        )
        assert "available_commands_truncated" not in out

    def test_standard_keys_still_truncated(self):
        """Existing allowlisted keys (e.g., 'findings') must still be truncated."""
        result = {"findings": [{"name": f"f_{i}"} for i in range(50)]}
        out = _apply_top_n(result, 10)
        assert len(out["findings"]) == 10
        assert out["findings_truncated"] is True
        assert out["findings_total"] == 50

    def test_top_zero_means_no_truncation_for_non_standard_key(self):
        """--top 0 (unlimited) must apply to non-standard keys too."""
        result = {"entities": [{"id": i} for i in range(100)]}
        out = _apply_top_n(result, 0)
        assert len(out["entities"]) == 100

    def test_nested_dict_non_standard_key_truncated(self):
        """Non-standard dict-of-lists key must also be truncated."""
        result = {
            "groups": {
                "alpha": [{"id": i} for i in range(30)],
                "beta": [{"id": i} for i in range(5)],
            }
        }
        out = _apply_top_n(result, 10)
        assert len(out["groups"]["alpha"]) == 10
        assert len(out["groups"]["beta"]) == 5  # under limit, no truncation

    def test_underscore_prefixed_keys_skipped(self):
        """Internal keys starting with '_' should not be processed."""
        result = {
            "_meta": [{"x": i} for i in range(50)],
            "findings": [{"name": f"f_{i}"} for i in range(50)],
        }
        out = _apply_top_n(result, 5)
        assert len(out["_meta"]) == 50, "_-prefixed keys should not be truncated"
        assert len(out["findings"]) == 5

    def test_repro_from_issue(self):
        """Exact repro from issue #36: hypothetical command returning 'entities'."""
        # Simulate what a new command might return
        result = {"status": "ok", "entities": [{"id": i} for i in range(1000)]}
        out = _apply_top_n(result, 5)
        # Before fix: len == 1000 (silent --top bypass)
        # After fix: len == 5 (universal truncation)
        assert len(out["entities"]) == 5, (
            "Issue #36 repro: --top 5 did not truncate 'entities' key. "
            "This means a new command returning non-standard keys would "
            "silently bypass --top, risking token overflow for MCP clients."
        )
