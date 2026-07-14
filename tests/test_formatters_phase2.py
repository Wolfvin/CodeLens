"""Tests for Phase 2 formatters (issue #52): text, junit-xml, emacs, vim, gitlab-sast.

Covers:

* :func:`formatters.text.format_text` — human-readable table
* :func:`formatters.junit_xml.format_junit_xml` — JUnit XML for CI
* :func:`formatters.emacs.format_emacs` — compile-mode format
* :func:`formatters.vim.format_vim` — quickfix format
* :func:`formatters.gitlab_sast.format_gitlab_sast` — GitLab SAST JSON
* Integration: ``format_output(data, "<format>")`` dispatches correctly

Each formatter test verifies:

1. **Output shape** — basic structure (XML validity, JSON validity, line count).
2. **Field mapping** — severity → format-specific level, file:line in the right place.
3. **Empty findings** — graceful handling (not crash, not empty string).
4. **Suppressed findings** — omitted from output (formatters' job is to surface actionable, not dismissed).
5. **Workspace path shortening** — absolute paths converted to relative.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from formatters import format_output  # noqa: E402
from formatters.base import Finding, Severity, extract_findings  # noqa: E402
from formatters.text import format_text  # noqa: E402
from formatters.junit_xml import format_junit_xml  # noqa: E402
from formatters.emacs import format_emacs  # noqa: E402
from formatters.vim import format_vim  # noqa: E402
from formatters.gitlab_sast import format_gitlab_sast  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def secrets_data():
    """Synthetic ``secrets`` command output with 3 findings of varying severity."""
    return {
        "status": "ok",
        "command": "secrets",
        "findings": [
            {
                "file": "src/auth.py", "line": 42, "column": 10,
                "severity": "critical", "category": "api_key",
                "message": "Hardcoded API key detected",
                "match": "sk_live_abc123", "cwe": "CWE-798",
            },
            {
                "file": "src/utils.py", "line": 128,
                "severity": "medium", "category": "webhook",
                "message": "Webhook URL with credentials",
                "match": "https://user:pass@hook.com",
            },
            {
                "file": "src/config.py", "line": 5,
                "severity": "low", "category": "info",
                "message": "Informational note about config",
            },
        ],
        "stats": {"total": 3, "critical": 1, "medium": 1, "low": 1},
    }


@pytest.fixture
def suppressed_data():
    """Findings with one suppressed — formatters should omit suppressed."""
    return {
        "status": "ok",
        "command": "secrets",
        "findings": [
            {
                "file": "a.py", "line": 1, "severity": "critical",
                "message": "active finding",
            },
            {
                "file": "b.py", "line": 2, "severity": "high",
                "message": "suppressed finding",
                "suppressed": True,
                "suppressed_reason": "false positive",
            },
        ],
    }


@pytest.fixture
def empty_data():
    """No findings — empty result."""
    return {
        "status": "ok",
        "command": "secrets",
        "findings": [],
    }


@pytest.fixture
def error_data():
    """Error response — formatters should handle gracefully."""
    return {
        "status": "error",
        "command": "secrets",
        "error": "scan failed",
    }


# ─── text formatter ────────────────────────────────────────────


class TestTextFormatter:
    """Human-readable table output."""

    def test_renders_header_and_rows(self, secrets_data):
        out = format_text(secrets_data, "secrets")
        assert "CodeLens" in out
        assert "3 finding(s)" in out
        assert "Hardcoded API key detected" in out
        assert "Webhook URL with credentials" in out
        # Severity symbols appear
        assert "CRIT" in out
        assert "MED" in out
        assert "LOW" in out

    def test_includes_severity_summary(self, secrets_data):
        out = format_text(secrets_data, "secrets")
        assert "Summary:" in out
        assert "1 critical" in out
        assert "1 medium" in out

    def test_empty_findings_returns_message(self, empty_data):
        out = format_text(empty_data, "secrets")
        assert "No findings" in out

    def test_error_data_returns_error_message(self, error_data):
        out = format_text(error_data, "secrets")
        assert "ERROR" in out
        assert "scan failed" in out

    def test_suppressed_findings_omitted_but_counted(self, suppressed_data):
        out = format_text(suppressed_data, "secrets")
        # Active finding shows.
        assert "active finding" in out
        # Suppressed finding does NOT show in rows.
        assert "suppressed finding" not in out
        # But suppressed count is mentioned.
        assert "1 suppressed" in out

    def test_workspace_path_shortened(self, secrets_data, tmp_path):
        """Absolute paths under workspace get shortened to relative."""
        workspace = str(tmp_path)
        data = {
            "findings": [{
                "file": os.path.join(workspace, "src/x.py"),
                "line": 1, "severity": "low", "message": "test",
            }],
        }
        out = format_text(data, "test", workspace)
        assert "src/x.py" in out
        # Full path should NOT appear (it would be too long for the column).
        assert workspace not in out


# ─── junit-xml formatter ───────────────────────────────────────


class TestJunitXmlFormatter:
    """JUnit XML for Jenkins/GitLab CI."""

    def test_produces_valid_xml(self, secrets_data):
        out = format_junit_xml(secrets_data, "secrets")
        # Must be parseable as XML.
        root = ET.fromstring(out)
        assert root.tag == "testsuites"
        assert root.get("tests") == "3"

    def test_has_testsuite_with_correct_counts(self, secrets_data):
        out = format_junit_xml(secrets_data, "secrets")
        root = ET.fromstring(out)
        suite = root.find("testsuite")
        assert suite is not None
        assert suite.get("tests") == "3"
        # 1 critical → failure; 1 medium + 1 low → skipped
        assert suite.get("failures") == "1"
        assert suite.get("disabled") == "2"

    def test_critical_finding_is_failure(self, secrets_data):
        out = format_junit_xml(secrets_data, "secrets")
        root = ET.fromstring(out)
        failures = root.findall(".//failure")
        assert len(failures) == 1
        # Failure message carries the finding message.
        assert "Hardcoded API key" in failures[0].get("message", "")

    def test_medium_finding_is_skipped(self, secrets_data):
        out = format_junit_xml(secrets_data, "secrets")
        root = ET.fromstring(out)
        skips = root.findall(".//skipped")
        assert len(skips) == 2  # medium + low

    def test_failure_body_includes_location(self, secrets_data):
        out = format_junit_xml(secrets_data, "secrets")
        # Body text should include file:line.
        assert "src/auth.py:42" in out

    def test_xml_escapes_special_characters(self):
        """XML special chars in messages must be escaped."""
        data = {
            "findings": [{
                "file": "x.py", "line": 1, "severity": "critical",
                "message": 'Use of <script>alert("xss")</script> & other bad stuff',
            }],
        }
        out = format_junit_xml(data, "secrets")
        # Should parse without error.
        root = ET.fromstring(out)
        # And the message should be preserved after parsing.
        failure = root.find(".//failure")
        assert "script" in failure.get("message", "")

    def test_empty_findings_produces_valid_empty_xml(self, empty_data):
        out = format_junit_xml(empty_data, "secrets")
        root = ET.fromstring(out)
        assert root.get("tests") == "0"
        assert root.get("failures") == "0"

    def test_suppressed_findings_omitted(self, suppressed_data):
        out = format_junit_xml(suppressed_data, "secrets")
        root = ET.fromstring(out)
        # Only the active finding, not the suppressed one.
        assert root.get("tests") == "1"
        assert "suppressed finding" not in out


# ─── emacs formatter ───────────────────────────────────────────


class TestEmacsFormatter:
    """compile-mode format: ``file:line:col: level: message``."""

    def test_one_line_per_finding(self, secrets_data):
        out = format_emacs(secrets_data, "secrets")
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 3

    def test_format_matches_emacs_convention(self, secrets_data):
        out = format_emacs(secrets_data, "secrets")
        # First line should be: src/auth.py:42:10: error: Hardcoded API key detected
        first_line = out.splitlines()[0]
        assert "src/auth.py:42:10" in first_line
        assert "error" in first_line  # critical → error
        assert "Hardcoded API key detected" in first_line

    def test_severity_to_level_mapping(self, secrets_data):
        out = format_emacs(secrets_data, "secrets")
        lines = out.splitlines()
        # critical → error, medium → warning, low → note
        assert "error" in lines[0]
        assert "warning" in lines[1]
        assert "note" in lines[2]

    def test_empty_findings_returns_informative_line(self, empty_data):
        out = format_emacs(empty_data, "secrets")
        assert "no findings" in out.lower()

    def test_suppressed_findings_omitted(self, suppressed_data):
        out = format_emacs(suppressed_data, "secrets")
        assert "active finding" in out
        assert "suppressed finding" not in out

    def test_no_column_omits_col(self):
        """When column=0, omit it from the location."""
        data = {
            "findings": [{
                "file": "x.py", "line": 10, "severity": "low",
                "message": "test",
            }],
        }
        out = format_emacs(data, "secrets")
        # Should be x.py:10: warning: test (no trailing :0)
        line = out.splitlines()[0]
        # Split by " : " — the location part should be just "x.py:10"
        assert "x.py:10:" in line
        assert "x.py:10:0" not in line


# ─── vim formatter ─────────────────────────────────────────────


class TestVimFormatter:
    """quickfix format: ``file:line:col: [severity] message``."""

    def test_one_line_per_finding(self, secrets_data):
        out = format_vim(secrets_data, "secrets")
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 3

    def test_format_matches_vim_convention(self, secrets_data):
        out = format_vim(secrets_data, "secrets")
        first_line = out.splitlines()[0]
        assert "src/auth.py:42:10" in first_line
        # Severity in brackets
        assert "critical" in first_line
        assert "Hardcoded API key detected" in first_line

    def test_empty_findings_returns_empty_string(self, empty_data):
        """Vim prefers empty output over a comment line."""
        out = format_vim(empty_data, "secrets")
        assert out == ""

    def test_suppressed_findings_omitted(self, suppressed_data):
        out = format_vim(suppressed_data, "secrets")
        assert "active finding" in out
        assert "suppressed finding" not in out

    def test_no_column_omits_col(self):
        data = {
            "findings": [{
                "file": "x.py", "line": 10, "severity": "low",
                "message": "test",
            }],
        }
        out = format_vim(data, "secrets")
        line = out.splitlines()[0]
        assert "x.py:10:" in line
        assert "x.py:10:0" not in line


# ─── gitlab-sast formatter ─────────────────────────────────────


class TestGitlabSastFormatter:
    """GitLab SAST JSON for security dashboard."""

    def test_produces_valid_json(self, secrets_data):
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        assert isinstance(data, dict)
        assert "version" in data
        assert "vulnerabilities" in data
        assert "scan" in data

    def test_vulnerabilities_count_matches(self, secrets_data):
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        assert len(data["vulnerabilities"]) == 3

    def test_severity_mapping_to_gitlab_enum(self, secrets_data):
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        sevs = [v["severity"] for v in data["vulnerabilities"]]
        # critical → Critical, medium → Medium, low → Low
        assert "Critical" in sevs
        assert "Medium" in sevs
        assert "Low" in sevs

    def test_vulnerability_has_required_fields(self, secrets_data):
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        v = data["vulnerabilities"][0]
        # GitLab Secure spec required fields.
        for field in ("id", "category", "name", "message", "cve",
                      "severity", "confidence", "scanner", "location", "identifiers"):
            assert field in v, f"missing required field: {field}"
        assert v["category"] == "sast"
        assert v["scanner"]["id"] == "codelens"

    def test_stable_id_deterministic(self, secrets_data):
        """Same finding → same ID across runs (GitLab dedupes by ID)."""
        out1 = format_gitlab_sast(secrets_data, "secrets")
        out2 = format_gitlab_sast(secrets_data, "secrets")
        id1 = json.loads(out1)["vulnerabilities"][0]["id"]
        id2 = json.loads(out2)["vulnerabilities"][0]["id"]
        assert id1 == id2

    def test_cwe_added_to_identifiers(self, secrets_data):
        """Finding with CWE → cwe identifier added."""
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        v = data["vulnerabilities"][0]  # the API key finding has CWE-798
        id_types = [i["type"] for i in v["identifiers"]]
        assert "cwe" in id_types
        cwe_id = next(i for i in v["identifiers"] if i["type"] == "cwe")
        assert cwe_id["name"] == "CWE-798"

    def test_empty_findings_produces_empty_vulnerabilities(self, empty_data):
        out = format_gitlab_sast(empty_data, "secrets")
        data = json.loads(out)
        assert data["vulnerabilities"] == []
        # Scan metadata still present.
        assert data["scan"]["status"] == "success"

    def test_suppressed_findings_omitted(self, suppressed_data):
        out = format_gitlab_sast(suppressed_data, "secrets")
        data = json.loads(out)
        assert len(data["vulnerabilities"]) == 1
        assert data["vulnerabilities"][0]["message"] == "active finding"

    def test_scan_metadata_has_codelens_scanner(self, secrets_data):
        out = format_gitlab_sast(secrets_data, "secrets")
        data = json.loads(out)
        assert data["scan"]["scanner"]["id"] == "codelens"
        assert data["scan"]["scanner"]["name"] == "CodeLens"
        assert data["scan"]["type"] == "sast"


# ─── Integration: format_output dispatches to new formatters ───


class TestFormatOutputDispatch:
    """Verify format_output() routes to the new Phase 2 formatters."""

    @pytest.mark.parametrize("fmt,expected_substring", [
        ("text", "CodeLens"),
        ("junit-xml", "<?xml"),
        ("emacs", "src/auth.py:42:10"),
        ("vim", "src/auth.py:42:10"),
        ("gitlab-sast", '"vulnerabilities"'),
    ])
    def test_format_dispatched_correctly(self, secrets_data, fmt, expected_substring):
        out = format_output(secrets_data, fmt, "secrets")
        assert expected_substring in out

    def test_unknown_format_falls_back_to_json(self, secrets_data):
        """Unknown format string → default JSON output (backward compat)."""
        out = format_output(secrets_data, "nonexistent-format", "secrets")
        # Should be valid JSON (the default).
        data = json.loads(out)
        assert isinstance(data, dict)

    def test_all_existing_formats_still_work(self, secrets_data):
        """Backward compat: existing formats (json, ai, sarif, compact) unchanged."""
        # json
        out = format_output(secrets_data, "json", "secrets")
        assert json.loads(out)  # valid JSON
        # ai
        out = format_output(secrets_data, "ai", "secrets")
        data = json.loads(out)
        assert "status" in data
        # sarif
        out = format_output(secrets_data, "sarif", "secrets")
        data = json.loads(out)
        assert "runs" in data
        # compact
        out = format_output(secrets_data, "compact", "secrets")
        assert json.loads(out)  # valid JSON


# ─── CLI smoke (subprocess) ────────────────────────────────────


class TestCLISmoke:
    """End-to-end: invoke ``codelens <cmd> --format <new>`` via subprocess."""

    def _run_cli(self, fmt):
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS_DIR
        # ``security`` is the umbrella command that absorbed the standalone
        # ``secrets`` command in the #195 consolidation. Its ``--help`` must
        # list the full ``--format`` choice set.
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "codelens.py"),
             "security", "--format", fmt, "--help"],
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_help_lists_new_formats(self):
        """``codelens security --help`` should list the 5 new format choices."""
        result = self._run_cli("text")
        # The --help output should mention all 5 new formats.
        for fmt in ("text", "junit-xml", "emacs", "vim", "gitlab-sast"):
            assert fmt in result.stdout, f"format {fmt} not in --help output"


import subprocess  # noqa: E402  — used in TestCLISmoke above
