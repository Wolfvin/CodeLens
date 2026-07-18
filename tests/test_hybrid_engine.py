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
            capture_output=True, text=True, cwd=CODELENS_ROOT, timeout=60
        )
        combined = result.stdout + result.stderr
        assert "pyright" in combined or result.returncode == 0

    @pytest.mark.skip(reason=(
        "The `query` hidden command triggers LSP initialisation that hangs on "
        "headless CI (issue #303) — the single test that made every CI run burn "
        "the 6h ceiling. Its assertion (confidence present without --deep) is "
        "already covered by test_impact_confidence_without_deep via the `impact` "
        "umbrella, which does not touch LSP. Re-enable if `query` is kept and "
        "made LSP-safe when the 13 hidden commands are resolved (issue #200)."
    ))
    def test_query_confidence_without_deep(self):
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "query", "detect_dead_code", CODELENS_ROOT, "--format", "json"],
            capture_output=True, text=True, timeout=60
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            assert "confidence" in data
            assert data["confidence"] in ("high", "medium", "low")

    def test_impact_confidence_without_deep(self):
        # Post-#195 umbrella form: `impact <ws> --name X` (was `impact X <ws>`,
        # which errors — the old form left stdout empty so this test passed
        # vacuously until #315 surfaced the error on stdout).
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "impact", CODELENS_ROOT, "--name", "detect_dead_code", "--format", "json"],
            capture_output=True, text=True, timeout=60,
        )
        idx = result.stdout.find("{")
        assert idx >= 0, result.stdout + result.stderr
        data = json.loads(result.stdout[idx:])
        assert "confidence" in data["r"][0]

    def test_ai_format_confidence_distribution(self):
        # Post-#195: `audit --check dead-code` (was the dropped `dead-code`
        # top-level command). ai stats are namespaced per check (#306).
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "audit", CODELENS_ROOT, "--check", "dead-code", "--format", "ai", "--top", "5"],
            capture_output=True, text=True, timeout=60,
        )
        idx = result.stdout.find("{")
        assert idx >= 0, result.stdout + result.stderr
        data = json.loads(result.stdout[idx:])
        assert "confidence_distribution" in data["stats"]["dead-code"]

    @pytest.mark.skip(reason=(
        "Uses the `query` hidden command, whose LSP init hangs on headless CI "
        "(issue #303). Re-enable when `query` is resolved (issue #200)."
    ))
    def test_deep_with_pyright(self):
        from lsp_client import detect_available_servers
        servers = detect_available_servers()
        if not servers.get("pyright", {}).get("available"):
            pytest.skip("pyright not installed")
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "query", "detect_dead_code", CODELENS_ROOT, "--deep", "--format", "json"],
            capture_output=True, text=True, timeout=60
        )
        idx = result.stdout.find("{")
        if idx >= 0:
            data = json.loads(result.stdout[idx:])
            assert data.get("confidence") == "high"
            assert data.get("lsp_active") is True

    def test_dead_code_confidence_fields(self):
        # Post-#195: `audit --check dead-code`; results live under the sub-check
        # envelope r[0].
        result = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
             "audit", CODELENS_ROOT, "--check", "dead-code", "--format", "json", "--top", "5"],
            capture_output=True, text=True, timeout=60,
        )
        idx = result.stdout.find("{")
        assert idx >= 0, result.stdout + result.stderr
        data = json.loads(result.stdout[idx:])
        results = data["r"][0].get("results", {})
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
            # Issue #199: `dead-code` alias removed — use `audit --check dead-code`
            result = subprocess.run(
                [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
                 "audit", tmpdir, "--check", "dead-code", "--deep"],
                capture_output=True, text=True, timeout=60
            )
            assert result.returncode == 0


# ─── Issue #32: --deep must invoke create_hybrid_engine exactly once ────


class TestDeepSingleInvocation:
    """Regression guard for issue #32.

    Before the fix, ``codelens.py`` had two duplicate ``--deep``
    post-processing blocks that both ran when ``--deep`` was set for
    ``dead-code``, ``query``, ``impact``, ``smell``, ``complexity``.
    Each block instantiated a fresh HybridEngine, so the engine was
    created twice per ``--deep`` invocation — doubling LSP subprocess
    calls and potentially double-counting findings in
    ``confidence_distribution``.

    These tests assert ``create_hybrid_engine`` is invoked exactly once
    per ``--deep`` CLI call, using ``unittest.mock.patch`` to count
    ``call_args``.
    """

    def test_smell_deep_invokes_create_hybrid_engine_once(self):
        """``codelens smell --deep`` must call create_hybrid_engine exactly once.

        Calls ``main()`` in-process (not via subprocess) so the mock is
        visible to the code under test. Subprocess mocks don't work
        across process boundaries.
        """
        import tempfile
        import shutil
        from unittest.mock import patch, MagicMock

        ws = tempfile.mkdtemp()
        try:
            # Minimal Python file so smell has something to analyze
            with open(os.path.join(ws, "test.py"), "w") as f:
                f.write("def foo():\n    pass\n")

            # Pre-build registry so auto-setup doesn't interfere
            from commands.scan import cmd_scan
            cmd_scan(ws)

            # Patch create_hybrid_engine to count calls without actually
            # starting LSP subprocesses (which would be slow + flaky in CI).
            with patch("hybrid_engine.create_hybrid_engine") as mock_create:
                mock_engine = MagicMock()
                mock_engine.lsp_active = False
                mock_create.return_value = mock_engine

                # Call main() in-process with patched argv so the mock
                # is visible. Redirect stdout to suppress JSON output.
                # Issue #199: `smell` alias removed — use `audit --check smell`
                old_argv = sys.argv
                import io
                old_stdout = sys.stdout
                sys.argv = ["codelens.py", "audit", ws, "--check", "smell", "--deep", "--format", "json"]
                sys.stdout = io.StringIO()
                try:
                    from codelens import main
                    main()
                except SystemExit:
                    # smell shouldn't sys.exit, but catch just in case
                    pass
                finally:
                    sys.argv = old_argv
                    sys.stdout = old_stdout

                assert mock_create.call_count == 1, (
                    f"Expected create_hybrid_engine to be called exactly once, "
                    f"got {mock_create.call_count} calls. This indicates the "
                    f"duplicate --deep block from issue #32 has regressed."
                )
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_deep_unsupported_command_sets_hint(self):
        """``--deep`` on an unsupported command must set deep_analysis_hint, not crash."""
        import tempfile
        import shutil

        ws = tempfile.mkdtemp()
        try:
            with open(os.path.join(ws, "test.py"), "w") as f:
                f.write("x = 1\n")

            from commands.scan import cmd_scan
            cmd_scan(ws)

            # Issue #199: `symbols` alias removed — `search --mode symbol`
            # is the post-#199 entry point. search is NOT in the --deep
            # supported list.
            proc = subprocess.run(
                [sys.executable, os.path.join(SCRIPT_DIR, "codelens.py"),
                 "search", "--mode", "symbol", "foo", ws, "--deep", "--format", "json"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONPATH": SCRIPT_DIR},
            )

            # Should not crash, and should include the hint
            assert proc.returncode == 0, f"Command failed: {proc.stderr}"
            import json as _json
            output = _json.loads(proc.stdout)
            assert output.get("deep_analysis") is False, (
                f"deep_analysis should be False for unsupported command, "
                f"got: {output.get('deep_analysis')}"
            )
            assert "deep_analysis_hint" in output, (
                "deep_analysis_hint must be set for unsupported --deep command"
            )
            # The hint should mention the command name (search or symbol)
            hint = output["deep_analysis_hint"]
            assert "search" in hint or "symbol" in hint, (
                f"hint should mention the command name, got: {hint}"
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)
