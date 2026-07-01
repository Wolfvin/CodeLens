"""Tests for Phase 1 (Finding dataclass + extract_findings) of issue #52.

Covers:

* :class:`formatters.base.Finding` dataclass construction and ``to_dict()``
* :func:`formatters.base.extract_findings` — extracting findings from
  heterogeneous engine outputs
* :func:`formatters.base._normalize_severity` — engine severity → canonical
* :func:`formatters.base._normalize_finding_dict` — engine finding dict → Finding

The extraction logic is the heart of Phase 1 — every Phase 2 formatter
depends on it producing consistent :class:`Finding` objects from the
many different shapes engines emit.
"""

from __future__ import annotations

import os
import sys

import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from formatters.base import (  # noqa: E402
    Finding,
    Severity,
    extract_findings,
    findings_to_dicts,
    _normalize_severity,
    _normalize_finding_dict,
)


# ─── Finding dataclass ─────────────────────────────────────────


class TestFindingDataclass:
    """Verify Finding construction and to_dict()."""

    def test_minimal_construction(self):
        f = Finding(message="test")
        assert f.message == "test"
        assert f.severity == Severity.UNKNOWN
        assert f.file == ""
        assert f.line == 0

    def test_full_construction(self):
        f = Finding(
            message="Hardcoded API key",
            severity=Severity.CRITICAL,
            file="src/auth.py",
            line=42,
            column=10,
            rule_id="codelens/secrets/api-key",
            category="api_key",
            command="secrets",
            cwe="CWE-798",
            snippet="sk_live_abc123",
        )
        assert f.severity == Severity.CRITICAL
        assert f.line == 42
        assert f.cwe == "CWE-798"

    def test_to_dict_omits_empty_fields(self):
        """to_dict() should omit empty/zero fields to keep JSON compact."""
        f = Finding(message="test", severity="medium", file="x.py", line=10)
        d = f.to_dict()
        assert d["message"] == "test"
        assert d["severity"] == "medium"
        assert d["file"] == "x.py"
        assert d["line"] == 10
        # Empty fields omitted.
        assert "column" not in d
        assert "cwe" not in d
        assert "snippet" not in d
        assert "suppressed" not in d  # False is omitted

    def test_to_dict_keeps_severity_and_message_even_if_empty(self):
        """severity and message are required — always present in to_dict."""
        f = Finding(message="")
        d = f.to_dict()
        assert "severity" in d
        assert "message" in d

    def test_to_dict_extras_merged_into_top_level(self):
        """extras dict is merged into the output, not nested under 'extras'."""
        f = Finding(message="test", extras={"custom_field": "value", "n": 42})
        d = f.to_dict()
        assert d["custom_field"] == "value"
        assert d["n"] == 42
        assert "extras" not in d  # extras itself is not in output


# ─── Severity normalization ────────────────────────────────────


class TestNormalizeSeverity:
    """Verify engine-specific severity strings are normalized to canonical."""

    @pytest.mark.parametrize("raw,expected", [
        # Direct canonical
        ("critical", Severity.CRITICAL),
        ("CRITICAL", Severity.CRITICAL),  # case-insensitive
        ("Critical", Severity.CRITICAL),
        ("high", Severity.HIGH),
        ("medium", Severity.MEDIUM),
        ("low", Severity.LOW),
        ("info", Severity.INFO),
        # Aliases
        ("error", Severity.CRITICAL),  # error → critical (blocking)
        ("fatal", Severity.CRITICAL),
        ("blocker", Severity.CRITICAL),
        ("warning", Severity.MEDIUM),
        ("warn", Severity.MEDIUM),
        ("moderate", Severity.MEDIUM),
        ("informational", Severity.LOW),
        ("note", Severity.LOW),
        ("hint", Severity.LOW),
        ("trivial", Severity.LOW),
        # Edge cases
        ("", Severity.UNKNOWN),
        (None, Severity.UNKNOWN),
        ("unknown_severity", Severity.UNKNOWN),
        ("very_high", Severity.UNKNOWN),  # not a recognized alias
    ])
    def test_severity_normalization(self, raw, expected):
        assert _normalize_severity(raw) == expected


# ─── extract_findings ──────────────────────────────────────────


class TestExtractFindings:
    """Verify extraction from various engine output shapes."""

    def test_empty_data_returns_empty_list(self):
        assert extract_findings(None) == []
        assert extract_findings("not a dict") == []
        assert extract_findings({}) == []

    def test_error_status_returns_empty(self):
        """Error responses have no findings."""
        data = {"status": "error", "error": "boom", "findings": [{"file": "x.py"}]}
        assert extract_findings(data, "secrets") == []

    def test_plain_findings_list(self):
        data = {
            "findings": [
                {"file": "a.py", "line": 10, "severity": "critical", "message": "API key"},
                {"file": "b.py", "line": 20, "severity": "medium", "message": "webhook"},
            ],
        }
        findings = extract_findings(data, "secrets")
        assert len(findings) == 2
        assert all(isinstance(f, Finding) for f in findings)
        assert findings[0].file == "a.py"
        assert findings[0].line == 10
        assert findings[0].severity == Severity.CRITICAL
        assert findings[0].command == "secrets"

    def test_alternative_list_keys(self):
        """Engines use different keys: findings, leaks, hints, issues, etc."""
        for key in ("findings", "leaks", "hints", "issues", "violations", "matches", "chains", "results"):
            data = {key: [{"file": "x.py", "line": 1, "message": "test"}]}
            findings = extract_findings(data, "cmd")
            assert len(findings) == 1, f"failed for key={key}"

    def test_category_keyed_dict(self):
        """by_category dict of lists — dead-code, smell pattern."""
        data = {
            "by_category": {
                "unreachable": [
                    {"file": "x.py", "line": 10, "message": "unreachable code"},
                ],
                "unused_variable": [
                    {"file": "y.py", "line": 20, "message": "unused var"},
                ],
            },
        }
        findings = extract_findings(data, "dead-code")
        assert len(findings) == 2
        categories = {f.category for f in findings}
        assert categories == {"unreachable", "unused_variable"}

    def test_dedup_across_list_and_dict(self):
        """Same finding in both 'findings' and 'by_category' → only one Finding."""
        finding_dict = {"file": "x.py", "line": 10, "category": "api_key", "message": "key"}
        data = {
            "findings": [finding_dict],
            "by_category": {"api_key": [finding_dict]},
        }
        findings = extract_findings(data, "secrets")
        assert len(findings) == 1  # deduplicated

    def test_rule_id_synthesized_from_command_and_category(self):
        """When engine doesn't provide rule_id, synthesize codelens/<cmd>/<cat>."""
        data = {
            "findings": [{"file": "x.py", "line": 1, "category": "api_key", "message": "test"}],
        }
        findings = extract_findings(data, "secrets")
        assert findings[0].rule_id == "codelens/secrets/api-key"

    def test_existing_rule_id_preserved(self):
        """If engine provides rule_id, don't overwrite."""
        data = {
            "findings": [{"file": "x.py", "line": 1, "rule_id": "custom-rule-001", "message": "test"}],
        }
        findings = extract_findings(data, "secrets")
        assert findings[0].rule_id == "custom-rule-001"

    def test_field_aliases(self):
        """Engines use different field names for the same concept."""
        data = {
            "findings": [{
                "defined_in": "src/x.py",  # alias for file
                "line_number": 42,         # alias for line
                "col": 10,                 # alias for column
                "risk": "high",            # alias for severity
                "name": "test finding",    # alias for message
                "type": "crypto",          # alias for category
            }],
        }
        findings = extract_findings(data, "secrets")
        f = findings[0]
        assert f.file == "src/x.py"
        assert f.line == 42
        assert f.column == 10
        assert f.severity == Severity.HIGH
        assert f.message == "test finding"
        assert f.category == "crypto"

    def test_extras_preserved(self):
        """Non-canonical fields go into extras and survive to_dict()."""
        data = {
            "findings": [{
                "file": "x.py", "line": 1, "message": "test",
                "custom_field": "value",
                "another_extra": 42,
            }],
        }
        findings = extract_findings(data, "secrets")
        f = findings[0]
        assert f.extras.get("custom_field") == "value"
        assert f.extras.get("another_extra") == 42
        # And survives to_dict()
        d = f.to_dict()
        assert d["custom_field"] == "value"
        assert d["another_extra"] == 42

    def test_suppressed_finding_extracted_with_flag(self):
        data = {
            "findings": [{
                "file": "x.py", "line": 1, "message": "test",
                "suppressed": True,
                "suppressed_reason": "false positive",
            }],
        }
        findings = extract_findings(data, "secrets")
        assert len(findings) == 1
        assert findings[0].suppressed is True
        assert findings[0].suppressed_reason == "false positive"

    def test_taint_specific_fields(self):
        data = {
            "chains": [{
                "file": "x.py", "line": 1, "message": "SQLi",
                "source": "request.input",
                "sink": "cursor.execute",
                "taint_path": "request.input → format_sql → cursor.execute",
            }],
        }
        findings = extract_findings(data, "taint")
        f = findings[0]
        assert f.source == "request.input"
        assert f.sink == "cursor.execute"
        assert "request.input" in f.taint_path

    def test_non_dict_finding_in_list_skipped(self):
        """Defensive: non-dict items in findings list don't crash."""
        data = {"findings": [{"file": "x.py", "line": 1, "message": "real"}, "not a dict", 42, None]}
        findings = extract_findings(data, "secrets")
        assert len(findings) == 1  # only the dict one extracted


# ─── Round-trip: Finding → dict → Finding ──────────────────────


class TestRoundTrip:
    """findings_to_dicts produces dicts that match Finding.to_dict()."""

    def test_findings_to_dicts_returns_list_of_dicts(self):
        findings = [
            Finding(message="a", severity="critical", file="x.py", line=1),
            Finding(message="b", severity="medium", file="y.py", line=2),
        ]
        result = findings_to_dicts(findings)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(d, dict) for d in result)
        assert result[0]["message"] == "a"
        assert result[1]["file"] == "y.py"
