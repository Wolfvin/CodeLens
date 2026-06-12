"""Tests for hybrid analysis engine and LSP client."""

import os
import sys
import json
import pytest
import subprocess

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
CODELENS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPT_DIR)


class TestLSPClient:
    def test_detect_available_servers(self):
        from lsp_client import detect_available_servers
        servers = detect_available_servers()
        assert isinstance(servers, dict)
        assert "pyright" in servers
        for name, info in servers.items():
            assert "available" in info
            assert "path" in info

    def test_get_server_for_file_python(self):
        from lsp_client import get_server_for_file
        result = get_server_for_file("test.py")
        if result:
            server_name, config = result
            assert server_name in ("pyright", "pylsp")

    def test_get_server_for_file_unknown(self):
        from lsp_client import get_server_for_file
        result = get_server_for_file("data.xyz")
        assert result is None

    def test_uri_conversion(self):
        from lsp_client import _path_to_uri, _uri_to_path
        path = "/home/user/project/file.py"
        uri = _path_to_uri(path)
        assert uri.startswith("file://")
        back = _uri_to_path(uri)
        assert back == path


class TestHybridEngine:
    def test_confidence_scoring(self):
        from hybrid_engine import compute_confidence, CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW
        assert compute_confidence(True, lsp_verified=True) == CONFIDENCE_HIGH
        assert compute_confidence(True, lsp_verified=None, ast_matched=True) == CONFIDENCE_MEDIUM
        assert compute_confidence(True, lsp_verified=None, ast_matched=False) == CONFIDENCE_LOW
        assert compute_confidence(True, lsp_verified=True, lsp_contradicts=True) == CONFIDENCE_LOW

    def test_confidence_distribution(self):
        from hybrid_engine import compute_confidence_distribution
        findings = [{"confidence": "high"}, {"confidence": "high"}, {"confidence": "medium"}, {"confidence": "low"}]
        dist = compute_confidence_distribution(findings)
        assert dist["high"] == 2
        assert dist["medium"] == 1
        assert dist["low"] == 1

    def test_create_hybrid_engine_no_deep(self):
        from hybrid_engine import create_hybrid_engine
        engine = create_hybrid_engine("/tmp", deep=False)
        assert not engine.lsp_active

    def test_get_lsp_status(self):
        from hybrid_engine import get_lsp_status
        status = get_lsp_status()
        assert status["status"] == "ok"
        assert "lsp_available" in status

    def test_add_confidence_to_result(self):
        from hybrid_engine import add_confidence_to_result
        result = {"status": "ok", "findings": [{"name": "a", "confidence": "high"}, {"name": "b", "confidence": "low"}]}
        result = add_confidence_to_result(result)
        assert "confidence_distribution" in result["stats"]

    def test_add_confidence_default_medium(self):
        from hybrid_engine import add_confidence_to_result
        result = {"status": "ok", "findings": [{"name": "a"}, {"name": "b"}]}
        result = add_confidence_to_result(result)
        assert result["findings"][0]["confidence"] == "medium"


class TestHybridIntegration:
    def test_lsp_status_cli(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"), "--lsp-status"],
            capture_output=True, text=True, cwd=CODELENS_ROOT
        )
        combined = result.stdout + result.stderr
        assert "pyright" in combined or result.returncode == 0

    def test_query_confidence_without_deep(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "query", "detect_dead_code", CODELENS_ROOT, "--format", "json"],
            capture_output=True, text=True
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            assert "confidence" in data
            assert data["confidence"] in ("high", "medium", "low")

    def test_impact_confidence_without_deep(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "impact", "detect_dead_code", CODELENS_ROOT, "--format", "json"],
            capture_output=True, text=True
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            assert "confidence" in data

    def test_ai_format_confidence_distribution(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "dead-code", CODELENS_ROOT, "--format", "ai", "--top", "5"],
            capture_output=True, text=True
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            stats = data.get("stats", {})
            assert "confidence_distribution" in stats

    def test_deep_with_pyright(self):
        from lsp_client import detect_available_servers
        servers = detect_available_servers()
        if not servers.get("pyright", {}).get("available"):
            pytest.skip("pyright not installed")
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "query", "detect_dead_code", CODELENS_ROOT, "--deep", "--format", "json"],
            capture_output=True, text=True
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            assert data.get("confidence") == "high"
            assert data.get("lsp_active") is True

    def test_dead_code_confidence_fields(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "dead-code", CODELENS_ROOT, "--format", "json", "--top", "5"],
            capture_output=True, text=True
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            results = data.get("results", {})
            found_confidence = False
            for cat, items in results.items():
                if isinstance(items, list):
                    for item in items[:3]:
                        if isinstance(item, dict) and "confidence" in item:
                            found_confidence = True
                            break
            assert found_confidence

    def test_deep_graceful_degradation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.xyz")
            with open(test_file, "w") as f:
                f.write("hello")
            result = subprocess.run(
                [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
                 "dead-code", tmpdir, "--deep"],
                capture_output=True, text=True
            )
            assert result.returncode == 0
