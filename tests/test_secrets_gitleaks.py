"""Tests for scripts/gitleaks_backend.py and commands/secrets.py — issue #159.

Tests the gitleaks backend integration:
- Detection (mocked subprocess)
- Invocation (mocked subprocess + temp file)
- Result normalization (gitleaks JSON → CodeLens schema)
- Severity inference heuristics
- Secret masking
- Fallback behavior when gitleaks unavailable
- --no-gitleaks flag forces regex backend
- stats.backend field provenance

All subprocess calls are mocked — no real gitleaks binary required.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from gitleaks_backend import (
    GitleaksError,
    _compute_risk,
    _compute_stats,
    _generate_recommendations,
    _gitleaks_available,
    _gitleaks_version,
    _infer_severity,
    _mask_secret,
    _normalize_gitleaks_findings,
    _run_gitleaks,
    scan_with_gitleaks,
)


# ─── 1. Detection ────────────────────────────────────────────


class TestGitleaksAvailable(unittest.TestCase):
    """_gitleaks_available() detects the binary correctly."""

    @patch("subprocess.run")
    def test_returns_true_when_gitleaks_version_exits_zero(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="8.18.0")
        self.assertTrue(_gitleaks_available())

    @patch("subprocess.run")
    def test_returns_false_when_gitleaks_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        self.assertFalse(_gitleaks_available())

    @patch("subprocess.run")
    def test_returns_false_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gitleaks", timeout=10)
        self.assertFalse(_gitleaks_available())

    @patch("subprocess.run")
    def test_returns_false_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        self.assertFalse(_gitleaks_available())

    @patch("subprocess.run")
    def test_returns_false_on_unexpected_exception(self, mock_run):
        mock_run.side_effect = RuntimeError("unexpected")
        self.assertFalse(_gitleaks_available())


class TestGitleaksVersion(unittest.TestCase):
    """_gitleaks_version() returns the version string or None."""

    @patch("subprocess.run")
    def test_returns_version_on_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="8.18.0\n")
        self.assertEqual(_gitleaks_version(), "8.18.0")

    @patch("subprocess.run")
    def test_returns_none_on_failure(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        self.assertIsNone(_gitleaks_version())


# ─── 2. Secret masking ───────────────────────────────────────


class TestMaskSecret(unittest.TestCase):
    """_mask_secret() never returns the raw secret."""

    def test_long_secret_masked(self):
        result = _mask_secret("AKIAIOSFODNN7EXAMPLE")
        self.assertEqual(result, "AKIA***")
        self.assertNotIn("IOSFODNN7EXAMPLE", result)

    def test_short_secret_fully_masked(self):
        self.assertEqual(_mask_secret("abc"), "***")

    def test_empty_secret(self):
        self.assertEqual(_mask_secret(""), "***")

    def test_exact_4_chars_fully_masked(self):
        """4-char secrets are fully masked (first 4 + *** would reveal all)."""
        self.assertEqual(_mask_secret("ABCD"), "***")

    def test_5_chars_shows_first_4(self):
        self.assertEqual(_mask_secret("ABCDE"), "ABCD***")


# ─── 3. Severity inference ──────────────────────────────────


class TestInferSeverity(unittest.TestCase):
    """_infer_severity() maps gitleaks rule IDs/tags to CodeLens severity."""

    def test_aws_access_key_is_critical(self):
        self.assertEqual(_infer_severity("aws-access-key", []), "critical")

    def test_aws_secret_is_critical(self):
        self.assertEqual(_infer_severity("aws-secret-key", []), "critical")

    def test_private_key_is_critical(self):
        self.assertEqual(_infer_severity("private-key", []), "critical")

    def test_github_pat_is_critical(self):
        self.assertEqual(_infer_severity("github-pat", []), "critical")

    def test_stripe_secret_is_critical(self):
        self.assertEqual(_infer_severity("stripe-secret-key", []), "critical")

    def test_critical_in_tags_is_critical(self):
        self.assertEqual(_infer_severity("some-rule", ["critical"]), "critical")

    def test_critical_in_rule_id_is_critical(self):
        self.assertEqual(_infer_severity("critical-database-url", []), "critical")

    def test_high_in_tags_is_high(self):
        self.assertEqual(_infer_severity("generic-rule", ["high"]), "high")

    def test_medium_in_tags_is_medium(self):
        self.assertEqual(_infer_severity("generic-rule", ["medium"]), "medium")

    def test_low_in_rule_id_is_low(self):
        self.assertEqual(_infer_severity("some-low-priority-rule", []), "low")

    def test_default_is_high(self):
        """Gitleaks rules are curated — default to high when no signal."""
        self.assertEqual(_infer_severity("generic-api-key", []), "high")

    def test_empty_rule_id_defaults_to_high(self):
        self.assertEqual(_infer_severity("", []), "high")

    def test_tags_as_string_handled(self):
        """Gitleaks sometimes returns tags as a single string, not a list."""
        # _infer_severity receives a list; the normalizer converts strings
        self.assertEqual(_infer_severity("rule", ["critical"]), "critical")


# ─── 4. Normalization ────────────────────────────────────────


class TestNormalizeFindings(unittest.TestCase):
    """_normalize_gitleaks_findings() maps gitleaks JSON to CodeLens schema."""

    def setUp(self):
        self.workspace = "/tmp/work"
        self.raw = [
            {
                "Description": "AWS Access Key",
                "StartLine": 42,
                "EndLine": 42,
                "StartColumn": 12,
                "EndColumn": 51,
                "Match": "AKIAIOSFODNN7EXAMPLE",
                "Secret": "AKIAIOSFODNN7EXAMPLE",
                "File": "src/config.py",
                "RuleID": "aws-access-key",
                "Tags": ["aws", "key"],
                "Fingerprint": "abc123",
            },
        ]

    def test_basic_normalization(self):
        findings = _normalize_gitleaks_findings(self.raw, self.workspace)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["type"], "aws-access-key")
        self.assertEqual(f["file"], "src/config.py")
        self.assertEqual(f["line"], 42)
        self.assertEqual(f["severity"], "critical")
        self.assertEqual(f["category"], "gitleaks")
        self.assertEqual(f["rule_id"], "aws-access-key")
        self.assertEqual(f["fingerprint"], "abc123")
        self.assertEqual(f["backend"], "gitleaks")

    def test_secret_is_masked(self):
        findings = _normalize_gitleaks_findings(self.raw, self.workspace)
        self.assertEqual(findings[0]["match"], "AKIA***")
        self.assertEqual(findings[0]["value"], "AKIA***")
        self.assertNotIn("IOSFODNN7EXAMPLE", findings[0]["match"])

    def test_absolute_file_path_normalized_to_relative(self):
        raw = [{
            "RuleID": "test-rule",
            "File": "/tmp/work/src/app.py",
            "StartLine": 1,
            "Secret": "sk_live_abcdef",
        }]
        findings = _normalize_gitleaks_findings(raw, self.workspace)
        self.assertEqual(findings[0]["file"], "src/app.py")

    def test_tags_as_string_converted_to_list(self):
        raw = [{
            "RuleID": "test-rule",
            "File": "app.py",
            "StartLine": 1,
            "Secret": "secret",
            "Tags": "aws,key",  # string, not list
        }]
        findings = _normalize_gitleaks_findings(raw, self.workspace)
        self.assertEqual(findings[0]["tags"], ["aws,key"])

    def test_empty_findings_list(self):
        findings = _normalize_gitleaks_findings([], self.workspace)
        self.assertEqual(findings, [])

    def test_non_dict_entries_skipped(self):
        raw = [{"RuleID": "ok"}, "not a dict", None, {"RuleID": "ok2"}]
        findings = _normalize_gitleaks_findings(raw, self.workspace)
        self.assertEqual(len(findings), 2)

    def test_missing_fields_use_defaults(self):
        raw = [{}]  # completely empty finding
        findings = _normalize_gitleaks_findings(raw, self.workspace)
        self.assertEqual(len(findings), 1)
        f = findings[0]
        self.assertEqual(f["type"], "unknown")
        self.assertEqual(f["file"], "")
        self.assertEqual(f["line"], 0)
        self.assertEqual(f["severity"], "high")  # default


# ─── 5. Stats / Risk / Recommendations ──────────────────────


class TestStatsRiskRecs(unittest.TestCase):
    """_compute_stats / _compute_risk / _generate_recommendations."""

    def setUp(self):
        self.findings = [
            {"severity": "critical", "file": "a.py"},
            {"severity": "critical", "file": "b.py"},
            {"severity": "high", "file": "a.py"},
            {"severity": "medium", "file": "c.py"},
        ]

    def test_stats_counts_by_severity(self):
        stats = _compute_stats(self.findings)
        self.assertEqual(stats["total"], 4)
        self.assertEqual(stats["by_severity"]["critical"], 2)
        self.assertEqual(stats["by_severity"]["high"], 1)
        self.assertEqual(stats["by_severity"]["medium"], 1)
        self.assertEqual(stats["by_severity"]["low"], 0)

    def test_stats_files_with_findings(self):
        stats = _compute_stats(self.findings)
        self.assertEqual(stats["files_with_findings"], 3)  # a.py, b.py, c.py

    def test_stats_empty_findings(self):
        stats = _compute_stats([])
        self.assertEqual(stats["total"], 0)
        self.assertEqual(stats["files_with_findings"], 0)

    def test_risk_critical_when_any_critical(self):
        self.assertEqual(_compute_risk(self.findings), "critical")

    def test_risk_high_when_no_critical_but_high(self):
        findings = [{"severity": "high", "file": "a.py"}]
        self.assertEqual(_compute_risk(findings), "high")

    def test_risk_medium_when_only_medium(self):
        findings = [{"severity": "medium", "file": "a.py"}]
        self.assertEqual(_compute_risk(findings), "medium")

    def test_risk_low_when_no_findings(self):
        self.assertEqual(_compute_risk([]), "low")

    def test_recommendations_for_critical(self):
        stats = _compute_stats(self.findings)
        recs = _generate_recommendations(self.findings, stats)
        self.assertTrue(any("CRITICAL" in r for r in recs))
        self.assertTrue(any("Rotate" in r for r in recs))

    def test_recommendations_for_no_findings(self):
        recs = _generate_recommendations([], {"total": 0, "by_severity": {}})
        self.assertTrue(any("No secrets found" in r for r in recs))


# ─── 6. _run_gitleaks (mocked subprocess) ───────────────────


class TestRunGitleaks(unittest.TestCase):
    """_run_gitleaks() invokes gitleaks and parses JSON output."""

    @patch("subprocess.run")
    def test_parses_json_findings(self, mock_run):
        """Gitleaks writes JSON to a temp file; we read it back."""
        findings_json = json.dumps([
            {"RuleID": "aws-key", "File": "app.py", "StartLine": 1, "Secret": "AKIA1234"},
        ])

        def fake_run(cmd, **kwargs):
            # Extract --report-path from cmd and write JSON to it
            report_idx = cmd.index("--report-path")
            report_path = cmd[report_idx + 1]
            with open(report_path, "w") as f:
                f.write(findings_json)
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_gitleaks(tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["RuleID"], "aws-key")

    @patch("subprocess.run")
    def test_empty_findings_when_report_file_missing(self, mock_run):
        """If gitleaks finds nothing, it may not write the report file."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_gitleaks(tmpdir)
        self.assertEqual(result, [])

    @patch("subprocess.run")
    def test_empty_findings_when_report_file_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        def fake_run(cmd, **kwargs):
            report_idx = cmd.index("--report-path")
            with open(cmd[report_idx + 1], "w") as f:
                f.write("")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_gitleaks(tmpdir)
        self.assertEqual(result, [])

    @patch("subprocess.run")
    def test_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=2, stdout="", stderr="config error")
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(GitleaksError) as ctx:
                _run_gitleaks(tmpdir)
            self.assertIn("config error", str(ctx.exception))

    @patch("subprocess.run")
    def test_raises_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gitleaks", timeout=120)
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(GitleaksError) as ctx:
                _run_gitleaks(tmpdir)
            self.assertIn("timed out", str(ctx.exception))

    @patch("subprocess.run")
    def test_raises_on_invalid_json(self, mock_run):
        def fake_run(cmd, **kwargs):
            report_idx = cmd.index("--report-path")
            with open(cmd[report_idx + 1], "w") as f:
                f.write("not valid json{{{")
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(GitleaksError) as ctx:
                _run_gitleaks(tmpdir)
            self.assertIn("Failed to parse", str(ctx.exception))

    @patch("subprocess.run")
    def test_handles_dict_with_results_key(self, mock_run):
        """Older gitleaks versions wrap findings in {Results: [...]}."""
        wrapped = json.dumps({"Results": [
            {"RuleID": "r1", "File": "a.py", "StartLine": 1, "Secret": "s"},
        ]})

        def fake_run(cmd, **kwargs):
            report_idx = cmd.index("--report-path")
            with open(cmd[report_idx + 1], "w") as f:
                f.write(wrapped)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _run_gitleaks(tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["RuleID"], "r1")


# ─── 7. scan_with_gitleaks (full integration, mocked) ──────


class TestScanWithGitleaks(unittest.TestCase):
    """scan_with_gitleaks() — the public entry point, fully mocked."""

    @patch("gitleaks_backend._gitleaks_available", return_value=False)
    def test_returns_none_when_gitleaks_unavailable(self, _mock):
        result = scan_with_gitleaks("/tmp/nonexistent")
        self.assertIsNone(result)

    @patch("gitleaks_backend._gitleaks_version", return_value="8.18.0")
    @patch("gitleaks_backend._gitleaks_available", return_value=True)
    @patch("subprocess.run")
    def test_full_scan_produces_result_dict(self, mock_run, _mock_avail, _mock_ver):
        findings_json = json.dumps([
            {"RuleID": "aws-access-key", "File": "app.py", "StartLine": 1,
             "Secret": "AKIAIOSFODNN7EXAMPLE", "Tags": ["aws"]},
            {"RuleID": "generic-api-key", "File": "lib.py", "StartLine": 5,
             "Secret": "sk_live_1234567890", "Tags": []},
        ])

        def fake_run(cmd, **kwargs):
            if "version" in cmd:
                return MagicMock(returncode=0, stdout="8.18.0")
            report_idx = cmd.index("--report-path")
            with open(cmd[report_idx + 1], "w") as f:
                f.write(findings_json)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_with_gitleaks(tmpdir)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["backend"], "gitleaks")
        self.assertEqual(result["gitleaks_version"], "8.18.0")
        self.assertEqual(len(result["findings"]), 2)
        self.assertEqual(result["findings"][0]["severity"], "critical")
        self.assertEqual(result["findings"][1]["severity"], "high")
        self.assertIn("total", result["stats"])
        self.assertIn("by_severity", result["stats"])
        self.assertEqual(result["stats"]["by_severity"]["critical"], 1)
        self.assertEqual(result["stats"]["by_severity"]["high"], 1)

    @patch("gitleaks_backend._gitleaks_version", return_value="8.18.0")
    @patch("gitleaks_backend._gitleaks_available", return_value=True)
    @patch("subprocess.run")
    def test_severity_filter_applied(self, mock_run, _mock_avail, _mock_ver):
        findings_json = json.dumps([
            {"RuleID": "aws-access-key", "File": "app.py", "StartLine": 1, "Secret": "AKIA..."},
            {"RuleID": "generic-rule", "File": "lib.py", "StartLine": 5, "Secret": "sk_..."},
        ])

        def fake_run(cmd, **kwargs):
            if "version" in cmd:
                return MagicMock(returncode=0, stdout="8.18.0")
            report_idx = cmd.index("--report-path")
            with open(cmd[report_idx + 1], "w") as f:
                f.write(findings_json)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_run

        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_with_gitleaks(tmpdir, severity="critical")

        # Only the critical finding should remain
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["severity"], "critical")

    @patch("gitleaks_backend._gitleaks_available", return_value=True)
    @patch("subprocess.run")
    def test_nonexistent_workspace_raises(self, mock_run, _mock_avail):
        with self.assertRaises(GitleaksError):
            scan_with_gitleaks("/nonexistent/path/xyz")


# ─── 8. CLI integration (subprocess) ────────────────────────


class TestCliIntegration(unittest.TestCase):
    """End-to-end CLI tests via subprocess."""

    @classmethod
    def setUpClass(cls):
        cls.codelens_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.cli = os.path.join(cls.codelens_repo, "scripts", "codelens.py")

    def _run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env.pop("CODELENS_AI_MODE", None)
        proc = subprocess.run(
            [sys.executable, self.cli] + list(args),
            capture_output=True, text=True, env=env, timeout=60,
            cwd=self.codelens_repo,
        )
        return proc

    def test_no_gitleaks_flag_in_help(self):
        proc = self._run_cli("secrets", "--help")
        self.assertIn("--no-gitleaks", proc.stdout)

    def test_secrets_runs_with_regex_backend_when_gitleaks_absent(self):
        """When gitleaks is not installed, backend should be 'regex'."""
        proc = self._run_cli("secrets", "tests/fixtures")
        import json as _json
        out = proc.stdout
        json_start = out.find("{")
        self.assertGreater(json_start, -1, "No JSON in output")
        data = _json.loads(out[json_start:])
        self.assertEqual(data["backend"], "regex")
        # gitleaks_hint should be present (telling user how to install)
        self.assertTrue(data.get("gitleaks_hint"))
        self.assertIn("gitleaks", data["gitleaks_hint"])

    def test_no_gitleaks_flag_suppresses_hint(self):
        """--no-gitleaks should suppress the gitleaks_hint."""
        proc = self._run_cli("secrets", "tests/fixtures", "--no-gitleaks")
        import json as _json
        out = proc.stdout
        json_start = out.find("{")
        data = _json.loads(out[json_start:])
        self.assertEqual(data["backend"], "regex")
        self.assertFalse(data.get("gitleaks_hint"))

    def test_stats_backend_field_set(self):
        """stats.backend should be set so compact/ai formatters pick it up."""
        proc = self._run_cli("secrets", "tests/fixtures")
        import json as _json
        out = proc.stdout
        json_start = out.find("{")
        data = _json.loads(out[json_start:])
        self.assertEqual(data["stats"]["backend"], "regex")


if __name__ == "__main__":
    unittest.main()
