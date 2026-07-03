"""
Tests for the CI/CD exit-policy evaluator (issue #57 Phase 2).

Covers the strict-mode / severity-threshold / max-findings gate
decision logic in ``scripts/exit_policy.py``.

Design contract (issue #57 worker consensus, Semgrep CL-012):
- ``--strict``        : exit non-zero on ANY finding (>= low).
- ``--error``         : exit non-zero if any finding has severity >= high.
- ``--severity-threshold <level>`` : explicit form of the above.
- ``--max-findings N``: exit non-zero if relevant count > N.
- ``severity_threshold`` (explicit) takes priority over ``strict``,
  which takes priority over ``error``.
"""

from __future__ import annotations

import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from exit_policy import (  # noqa: E402
    SEVERITY_ORDER,
    SEVERITY_RANK,
    ExitDecision,
    evaluate_exit_policy,
    severity_rank,
)


# ─── severity_rank ────────────────────────────────────────────


class TestSeverityRank:
    def test_critical_is_zero(self):
        assert severity_rank("critical") == 0

    def test_high_is_one(self):
        assert severity_rank("high") == 1

    def test_medium_is_two(self):
        assert severity_rank("medium") == 2

    def test_low_is_three(self):
        assert severity_rank("low") == 3

    def test_info_is_four(self):
        assert severity_rank("info") == 4

    def test_unknown_is_five(self):
        assert severity_rank("unknown") == 5

    def test_case_insensitive(self):
        assert severity_rank("HIGH") == severity_rank("high")
        assert severity_rank("Critical") == severity_rank("critical")

    def test_none_returns_unknown(self):
        assert severity_rank(None) == SEVERITY_RANK["unknown"]

    def test_empty_returns_unknown(self):
        assert severity_rank("") == SEVERITY_RANK["unknown"]

    def test_unknown_string_returns_unknown(self):
        assert severity_rank("banana") == SEVERITY_RANK["unknown"]


# ─── strict mode ──────────────────────────────────────────────


class TestStrictMode:
    def test_strict_fails_on_any_finding(self):
        findings = [{"severity": "low"}]
        d = evaluate_exit_policy(findings, strict=True)
        assert d.should_fail is True
        assert d.exit_code == 1
        assert len(d.reasons) >= 1

    def test_strict_does_not_fail_on_info(self):
        """``info`` is below ``low`` in severity ordering — ``--strict``
        (threshold=low) does NOT catch informational findings per the
        issue #57 spec ("strict = exit non-zero on warning or above")."""
        findings = [{"severity": "info"}]
        d = evaluate_exit_policy(findings, strict=True)
        assert d.should_fail is False

    def test_strict_passes_with_no_findings(self):
        d = evaluate_exit_policy([], strict=True)
        assert d.should_fail is False
        assert d.exit_code == 0
        assert d.reasons == []

    def test_strict_threshold_is_low(self):
        d = evaluate_exit_policy([], strict=True)
        assert d.severity_threshold == "low"


# ─── error mode ───────────────────────────────────────────────


class TestErrorMode:
    def test_error_fails_on_high(self):
        findings = [{"severity": "high"}]
        d = evaluate_exit_policy(findings, error=True)
        assert d.should_fail is True

    def test_error_fails_on_critical(self):
        findings = [{"severity": "critical"}]
        d = evaluate_exit_policy(findings, error=True)
        assert d.should_fail is True

    def test_error_passes_on_medium(self):
        findings = [{"severity": "medium"}]
        d = evaluate_exit_policy(findings, error=True)
        assert d.should_fail is False

    def test_error_passes_on_low(self):
        findings = [{"severity": "low"}]
        d = evaluate_exit_policy(findings, error=True)
        assert d.should_fail is False

    def test_error_threshold_is_high(self):
        d = evaluate_exit_policy([], error=True)
        assert d.severity_threshold == "high"


# ─── severity_threshold ───────────────────────────────────────


class TestSeverityThreshold:
    def test_critical_threshold_only_fails_on_critical(self):
        findings = [{"severity": "high"}]
        d = evaluate_exit_policy(findings, severity_threshold="critical")
        assert d.should_fail is False

    def test_critical_threshold_fails_on_critical(self):
        findings = [{"severity": "critical"}]
        d = evaluate_exit_policy(findings, severity_threshold="critical")
        assert d.should_fail is True

    def test_medium_threshold_fails_on_high(self):
        findings = [{"severity": "high"}]
        d = evaluate_exit_policy(findings, severity_threshold="medium")
        assert d.should_fail is True

    def test_medium_threshold_fails_on_medium(self):
        findings = [{"severity": "medium"}]
        d = evaluate_exit_policy(findings, severity_threshold="medium")
        assert d.should_fail is True

    def test_medium_threshold_passes_on_low(self):
        findings = [{"severity": "low"}]
        d = evaluate_exit_policy(findings, severity_threshold="medium")
        assert d.should_fail is False

    def test_threshold_takes_priority_over_strict(self):
        # severity_threshold=critical + strict=True → only critical fails
        findings = [{"severity": "low"}]
        d = evaluate_exit_policy(
            findings, strict=True, severity_threshold="critical"
        )
        assert d.should_fail is False
        assert d.severity_threshold == "critical"

    def test_threshold_takes_priority_over_error(self):
        # severity_threshold=low + error=True → low fails (low < high)
        findings = [{"severity": "low"}]
        d = evaluate_exit_policy(
            findings, error=True, severity_threshold="low"
        )
        assert d.should_fail is True
        assert d.severity_threshold == "low"


# ─── max-findings ─────────────────────────────────────────────


class TestMaxFindings:
    def test_cap_exceeded_fails(self):
        findings = [{"severity": "low"}, {"severity": "low"}, {"severity": "low"}]
        d = evaluate_exit_policy(findings, max_findings=2)
        assert d.should_fail is True
        assert any("max-findings" in r for r in d.reasons)

    def test_cap_not_exceeded_passes(self):
        findings = [{"severity": "low"}, {"severity": "low"}]
        d = evaluate_exit_policy(findings, max_findings=5)
        assert d.should_fail is False

    def test_cap_zero_means_no_cap(self):
        findings = [{"severity": "low"}] * 1000
        d = evaluate_exit_policy(findings, max_findings=0)
        assert d.should_fail is False

    def test_cap_interacts_with_severity_threshold(self):
        """With severity_threshold=high, only high+ findings count toward
        the max-findings cap. The severity threshold gate itself still
        applies independently — a single high finding triggers BOTH the
        severity gate AND counts toward the cap."""
        findings = [
            {"severity": "low"},
            {"severity": "low"},
            {"severity": "low"},
            {"severity": "high"},
        ]
        d = evaluate_exit_policy(findings, severity_threshold="high", max_findings=2)
        # 1 relevant (high), cap=2 → cap OK, BUT severity threshold=high
        # + 1 high finding → severity gate fails.
        assert d.should_fail is True
        assert d.relevant_count == 1
        assert any("high-severity" in r for r in d.reasons)

    def test_cap_passes_when_below_and_no_severity_gate(self):
        """No severity threshold + max_findings=5 → all findings count
        toward cap, gate passes when count <= cap."""
        findings = [
            {"severity": "low"},
            {"severity": "low"},
            {"severity": "low"},
        ]
        d = evaluate_exit_policy(findings, max_findings=5)
        assert d.should_fail is False
        assert d.relevant_count == 3


# ─── by_severity / relevant_count ─────────────────────────────


class TestBySeverity:
    def test_by_severity_count(self):
        findings = [
            {"severity": "high"}, {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"}, {"severity": "low"}, {"severity": "low"},
        ]
        d = evaluate_exit_policy(findings, strict=True)
        assert d.by_severity["high"] == 2
        assert d.by_severity["medium"] == 1
        assert d.by_severity["low"] == 3

    def test_relevant_count_with_threshold(self):
        findings = [
            {"severity": "critical"},
            {"severity": "high"},
            {"severity": "medium"},
            {"severity": "low"},
        ]
        d = evaluate_exit_policy(findings, severity_threshold="high")
        # critical + high = 2 relevant
        assert d.relevant_count == 2

    def test_relevant_count_without_threshold(self):
        findings = [
            {"severity": "low"},
            {"severity": "medium"},
        ]
        d = evaluate_exit_policy(findings, max_findings=5)
        # No severity threshold → all findings count toward cap
        assert d.relevant_count == 2


# ─── no flags = no gate (passes) ───────────────────────────────


class TestNoFlags:
    def test_no_flags_no_findings_passes(self):
        d = evaluate_exit_policy([])
        assert d.should_fail is False
        assert d.severity_threshold is None

    def test_no_flags_with_findings_still_passes(self):
        # No severity threshold + no max-findings → no gate applies
        findings = [{"severity": "critical"}]
        d = evaluate_exit_policy(findings)
        assert d.should_fail is False


# ─── ExitDecision shape ───────────────────────────────────────


class TestExitDecisionShape:
    def test_default_decision_passes(self):
        d = ExitDecision()
        assert d.should_fail is False
        assert d.exit_code == 0
        assert d.reasons == []
        assert d.severity_threshold is None
        assert d.max_findings is None
