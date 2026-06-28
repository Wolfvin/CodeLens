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
