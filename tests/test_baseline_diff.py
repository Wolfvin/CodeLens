"""
Tests for the CI/CD baseline-diff engine (issue #57 Phase 1).

Covers:
- ``finding_identity()`` — stability across message/column changes,
  case-insensitive severity, path separator normalisation.
- ``diff_findings()`` — new / preexisting / resolved classification,
  per-severity delta computation, empty baseline (first run).
- ``save_baseline()`` / ``load_baseline()`` — JSON round-trip,
  metadata block, missing file returns None.
- ``filter_to_changed_files()`` — keep only findings whose file is in
  a git diff list; absolute vs relative path handling.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from baseline_diff import (  # noqa: E402
    baseline_path,
    diff_findings,
    filter_to_changed_files,
    finding_identity,
    load_baseline,
    save_baseline,
)


# ─── finding_identity ─────────────────────────────────────────


class TestFindingIdentity:
    def test_basic_stability(self):
        f = {"rule_id": "sql-inj", "file": "app.py", "line": 42, "severity": "high"}
        assert finding_identity(f) == finding_identity(f)

    def test_ignores_message_text(self):
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high", "message": "msg A"}
        f2 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high", "message": "msg B"}
        assert finding_identity(f1) == finding_identity(f2)

    def test_ignores_column(self):
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "column": 5, "severity": "high"}
        f2 = {"rule_id": "r", "file": "a.py", "line": 1, "column": 99, "severity": "high"}
        assert finding_identity(f1) == finding_identity(f2)

    def test_severity_case_insensitive(self):
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "HIGH"}
        f2 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high"}
        assert finding_identity(f1) == finding_identity(f2)

    def test_path_separator_normalisation(self):
        f1 = {"rule_id": "r", "file": "src/app.py", "line": 1, "severity": "high"}
        f2 = {"rule_id": "r", "file": "src\\app.py", "line": 1, "severity": "high"}
        assert finding_identity(f1) == finding_identity(f2)

    def test_different_rule_id_different_identity(self):
        f1 = {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"}
        f2 = {"rule_id": "r2", "file": "a.py", "line": 1, "severity": "high"}
        assert finding_identity(f1) != finding_identity(f2)

    def test_different_line_different_identity(self):
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high"}
        f2 = {"rule_id": "r", "file": "a.py", "line": 2, "severity": "high"}
        assert finding_identity(f1) != finding_identity(f2)

    def test_different_severity_different_identity(self):
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high"}
        f2 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "medium"}
        assert finding_identity(f1) != finding_identity(f2)

    def test_missing_fields_does_not_raise(self):
        f = {}
        assert isinstance(finding_identity(f), str)
        assert len(finding_identity(f)) == 16

    def test_rule_field_alias(self):
        """``rule`` is accepted as an alias for ``rule_id``."""
        f1 = {"rule_id": "r", "file": "a.py", "line": 1, "severity": "high"}
        f2 = {"rule": "r", "file": "a.py", "line": 1, "severity": "high"}
        assert finding_identity(f1) == finding_identity(f2)


# ─── diff_findings ────────────────────────────────────────────


class TestDiffFindings:
    def test_first_run_no_baseline_all_new(self):
        current = [
            {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"},
            {"rule_id": "r2", "file": "b.py", "line": 2, "severity": "low"},
        ]
        d = diff_findings(current, None)
        assert len(d["new_findings"]) == 2
        assert len(d["preexisting_findings"]) == 0
        assert len(d["resolved_findings"]) == 0
        assert d["total_findings"] == 2
        assert d["baseline_total"] == 0

    def test_classification(self):
        current = [
            {"rule_id": "r1", "file": "a.py", "line": 10, "severity": "high"},  # preexisting
            {"rule_id": "r2", "file": "b.py", "line": 20, "severity": "medium"},  # new
        ]
        baseline = [
            {"rule_id": "r1", "file": "a.py", "line": 10, "severity": "high"},  # preexisting
            {"rule_id": "r3", "file": "c.py", "line": 30, "severity": "low"},  # resolved
        ]
        d = diff_findings(current, baseline)
        assert len(d["new_findings"]) == 1
        assert d["new_findings"][0]["rule_id"] == "r2"
        assert len(d["preexisting_findings"]) == 1
        assert d["preexisting_findings"][0]["rule_id"] == "r1"
        assert len(d["resolved_findings"]) == 1
        assert d["resolved_findings"][0]["rule_id"] == "r3"
        assert d["total_findings"] == 2
        assert d["baseline_total"] == 2

    def test_delta_per_severity(self):
        current = [
            {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"},
            {"rule_id": "r2", "file": "b.py", "line": 2, "severity": "medium"},
            {"rule_id": "r4", "file": "d.py", "line": 4, "severity": "medium"},
        ]
        baseline = [
            {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"},  # preexisting
            {"rule_id": "r3", "file": "c.py", "line": 3, "severity": "low"},  # resolved
        ]
        d = diff_findings(current, baseline)
        # high: 1 current, 1 baseline → 0
        assert d["delta_per_severity"]["high"] == 0
        # medium: 2 current, 0 baseline → +2
        assert d["delta_per_severity"]["medium"] == 2
        # low: 0 current, 1 baseline → -1
        assert d["delta_per_severity"]["low"] == -1

    def test_empty_current_all_resolved(self):
        baseline = [
            {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"},
        ]
        d = diff_findings([], baseline)
        assert len(d["new_findings"]) == 0
        assert len(d["preexisting_findings"]) == 0
        assert len(d["resolved_findings"]) == 1
        assert d["total_findings"] == 0

    def test_summary_string_present(self):
        d = diff_findings([], None)
        assert isinstance(d["summary"], str)
        assert "new" in d["summary"]

    def test_new_findings_have_identity_attached(self):
        current = [{"rule_id": "r", "file": "a.py", "line": 1, "severity": "high"}]
        d = diff_findings(current, None)
        assert "_identity" in d["new_findings"][0]


# ─── save_baseline / load_baseline ────────────────────────────


class TestBaselinePersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        ws = str(tmp_path)
        findings = [
            {"rule_id": "r1", "file": "a.py", "line": 1, "severity": "high"},
            {"rule_id": "r2", "file": "b.py", "line": 2, "severity": "medium"},
        ]
        path = save_baseline(ws, "abc123", findings)
        assert os.path.exists(path)
        assert "abc123" in path
        assert ".codelens" in path

        loaded = load_baseline(ws, "abc123")
        assert loaded is not None
        assert loaded["sha"] == "abc123"
        assert loaded["version"] == 1
        assert loaded["finding_count"] == 2
        assert len(loaded["findings"]) == 2
        assert "created_at_iso" in loaded

    def test_load_missing_returns_none(self, tmp_path):
        assert load_baseline(str(tmp_path), "nonexistent") is None

    def test_load_none_sha_returns_none(self, tmp_path):
        assert load_baseline(str(tmp_path), None) is None

    def test_load_corrupt_returns_none(self, tmp_path):
        ws = str(tmp_path)
        path = baseline_path(ws, "bad")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{not valid json")
        assert load_baseline(ws, "bad") is None

    def test_baseline_path_format(self, tmp_path):
        ws = str(tmp_path)
        p = baseline_path(ws, "abc123")
        assert p.endswith("baseline_abc123.json")
        assert ".codelens" in p


# ─── filter_to_changed_files ──────────────────────────────────


class TestFilterToChangedFiles:
    def test_keeps_only_changed(self):
        findings = [
            {"rule_id": "r", "file": "changed.py", "line": 1, "severity": "high"},
            {"rule_id": "r", "file": "unchanged.py", "line": 1, "severity": "high"},
        ]
        changed = ["changed.py"]
        out = filter_to_changed_files(findings, changed)
        assert len(out) == 1
        assert out[0]["file"] == "changed.py"

    def test_empty_changed_returns_empty(self):
        findings = [{"file": "a.py", "severity": "high"}]
        assert filter_to_changed_files(findings, []) == []

    def test_absolute_path_in_finding_matches_relative_in_changed(self):
        findings = [
            {"file": "/ws/src/app.py", "severity": "high"},
        ]
        changed = ["src/app.py"]
        out = filter_to_changed_files(findings, changed, workspace="/ws")
        assert len(out) == 1

    def test_backslash_path_normalisation(self):
        findings = [{"file": "src\\app.py", "severity": "high"}]
        changed = ["src/app.py"]
        out = filter_to_changed_files(findings, changed)
        assert len(out) == 1

    def test_finding_without_file_dropped(self):
        findings = [
            {"rule_id": "r", "severity": "high"},  # no file field
        ]
        changed = ["anything.py"]
        assert filter_to_changed_files(findings, changed) == []

    def test_path_field_alias(self):
        """``path`` is accepted as an alias for ``file``."""
        findings = [{"path": "a.py", "severity": "high"}]
        changed = ["a.py"]
        out = filter_to_changed_files(findings, changed)
        assert len(out) == 1
