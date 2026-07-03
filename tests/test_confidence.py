"""Tests for confidence scoring + schema versioning (issue #5).

Covers two agent-UX features from issue #5:

1. **Confidence scores** — every finding gets a ``confidence`` field in
   [0.0, 1.0] so agents can rank actionable vs. needs-review findings.
   - :func:`score_finding` — base scores per category + modifier adjustments
   - :func:`enrich_finding` — single-finding enrichment (idempotent)
   - :func:`enrich_findings` — payload-level enrichment (dead-code + secrets shapes)
   - :func:`confidence_distribution` — bucket findings by confidence range

2. **Schema versioning** — every JSON output gets a ``schema_version`` field
   so consumers can detect breaking changes.
   - :data:`SCHEMA_VERSION` — current version string
   - :func:`stamp_schema_version` — idempotent stamping
   - Integration: ``formatters._normalize_to_ai`` stamps every normalized output
   - Integration: ``formatters.format_output`` stamps raw JSON output

Integration tests verify that ``deadcode_engine.detect_dead_code`` and
``secrets_engine.detect_secrets`` both return findings with ``confidence``
fields, and that ``formatters.format_output`` adds ``schema_version`` to
both AI-normalized and raw JSON outputs.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import shutil

import pytest

# Make scripts/ importable.
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from confidence import (  # noqa: E402
    SCHEMA_VERSION,
    score_finding,
    enrich_finding,
    enrich_findings,
    stamp_schema_version,
    confidence_distribution,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace():
    """Yield a temporary workspace directory."""
    d = tempfile.mkdtemp(prefix="codelens_conf_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ─── Schema version ────────────────────────────────────────────────────────


class TestSchemaVersion:
    """``schema_version`` must be present on every JSON output (issue #5)."""

    def test_schema_version_is_string(self):
        assert isinstance(SCHEMA_VERSION, str)
        assert "." in SCHEMA_VERSION  # e.g. "8.2"

    def test_stamp_adds_schema_version(self):
        payload = {"status": "ok", "items": []}
        result = stamp_schema_version(payload)
        assert result["schema_version"] == SCHEMA_VERSION

    def test_stamp_is_idempotent(self):
        payload = {"status": "ok", "schema_version": "9.9"}
        result = stamp_schema_version(payload)
        # Existing version preserved — not overwritten.
        assert result["schema_version"] == "9.9"

    def test_stamp_handles_non_dict(self):
        # Should not crash on non-dict input.
        assert stamp_schema_version(None) is None
        assert stamp_schema_version([]) == []

    def test_stamp_returns_same_object(self):
        """stamp_schema_version mutates in place AND returns the payload."""
        payload = {"status": "ok"}
        result = stamp_schema_version(payload)
        assert result is payload
        assert "schema_version" in payload


# ─── score_finding ─────────────────────────────────────────────────────────


class TestScoreFinding:
    """``score_finding`` returns a confidence in [0.0, 1.0] per category."""

    def test_dead_code_unreachable_high_confidence(self):
        c = score_finding("dead_code", "unreachable", {"after": "return"})
        assert 0.85 <= c <= 1.0
        # After return is more certain than after throw
        c_throw = score_finding("dead_code", "unreachable", {"after": "throw"})
        assert c > c_throw

    def test_dead_code_unused_exports_low_confidence(self):
        c = score_finding("dead_code", "unused_exports", {})
        assert 0.0 <= c <= 0.6  # public API — often false positive

    def test_dead_code_library_api_reduces_confidence(self):
        base = score_finding("dead_code", "unused_exports", {})
        with_lib = score_finding(
            "dead_code", "unused_exports", {"source": "library_api"}
        )
        assert with_lib < base

    def test_dead_code_test_file_reduces_confidence(self):
        base = score_finding("dead_code", "unused_vars", {})
        with_test = score_finding(
            "dead_code", "unused_vars", {"in_test_file": True}
        )
        assert with_test < base

    def test_dead_code_config_file_reduces_confidence(self):
        base = score_finding("dead_code", "unused_vars", {})
        with_config = score_finding(
            "dead_code", "unused_vars", {"source": "config"}
        )
        assert with_config < base

    def test_dead_code_unknown_category_defaults_neutral(self):
        c = score_finding("dead_code", "bogus_category", {})
        assert c == 0.50

    def test_secrets_pattern_match_high_confidence(self):
        c = score_finding("secrets", "pattern_match", {})
        assert 0.80 <= c <= 1.0

    def test_secrets_entropy_medium_confidence(self):
        c = score_finding("secrets", "entropy", {})
        # Entropy could be a hash, UUID, etc. — not as certain as pattern match.
        assert 0.40 <= c <= 0.80

    def test_secrets_test_file_heavily_discounted(self):
        base = score_finding("secrets", "pattern_match", {})
        with_test = score_finding(
            "secrets", "pattern_match", {"in_test_file": True}
        )
        # Test-file secrets are almost always fixtures — big discount.
        assert with_test < base
        assert base - with_test >= 0.25

    def test_secrets_unknown_category_defaults_neutral(self):
        assert score_finding("secrets", "bogus", {}) == 0.50

    def test_unknown_engine_defaults_neutral(self):
        assert score_finding("bogus_engine", "whatever", {}) == 0.50

    def test_score_always_in_valid_range(self):
        """Even with extreme modifier stacking, score stays in [0, 1]."""
        # Stack all negative modifiers
        finding = {
            "in_test_file": True,
            "source": "library_api",
            "downgraded": True,
            "after": "throw",
        }
        c = score_finding("dead_code", "unused_exports", finding)
        assert 0.0 <= c <= 1.0

    def test_score_rounded_to_2_decimals(self):
        c = score_finding("dead_code", "unreachable", {"after": "return"})
        # Should be a clean 2-decimal number
        assert round(c, 2) == c

    def test_modifier_predicate_crash_is_swallowed(self):
        """A crashing modifier predicate must not propagate (fail-safe)."""
        # Pass a finding that would make attribute access fail — the modifier
        # predicates use .get() so they're safe, but this test documents the
        # contract: scoring never raises.
        c = score_finding("dead_code", "unreachable", None)
        # None finding — predicates use .get() which returns None, treated falsy.
        # Should not raise; should return a valid score.
        assert 0.0 <= c <= 1.0


# ─── enrich_finding ────────────────────────────────────────────────────────


class TestEnrichFinding:
    """``enrich_finding`` adds confidence to a single finding dict."""

    def test_adds_confidence_field(self):
        finding = {"type": "pattern_match", "file": "a.py", "line": 1}
        result = enrich_finding("secrets", finding)
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_idempotent(self):
        finding = {"type": "pattern_match", "confidence": 0.42}
        result = enrich_finding("secrets", finding)
        assert result["confidence"] == 0.42  # preserved, not overwritten

    def test_secrets_uses_type_for_category(self):
        """For secrets, `type` (detection method) is the scoring key, not `category`."""
        finding = {
            "type": "pattern_match",  # detection method
            "category": "aws_key",    # specific secret kind — too granular for scoring
        }
        result = enrich_finding("secrets", finding)
        # pattern_match base is 0.90 — if we'd used "aws_key" we'd get 0.50 (unknown).
        assert result["confidence"] >= 0.80

    def test_dead_code_uses_category_then_type(self):
        finding = {"type": "unreachable", "after": "return"}
        result = enrich_finding("dead_code", finding)
        # `type` is "unreachable" which is a known category.
        assert result["confidence"] >= 0.85

    def test_handles_non_dict(self):
        assert enrich_finding("secrets", None) is None
        assert enrich_finding("secrets", "not a dict") == "not a dict"

    def test_unknown_engine_still_stamps_confidence(self):
        finding = {"type": "whatever"}
        result = enrich_finding("bogus", finding)
        assert result["confidence"] == 0.50


# ─── enrich_findings (payload-level) ───────────────────────────────────────


class TestEnrichFindings:
    """``enrich_findings`` enriches all findings in a result payload."""

    def test_dead_code_payload_shape(self):
        """Dead-code style: results = {category: [finding, ...], ...}."""
        payload = {
            "status": "ok",
            "results": {
                "unreachable": [
                    {"file": "a.py", "line": 10, "after": "return"},
                    {"file": "b.py", "line": 20, "after": "throw"},
                ],
                "unused_vars": [
                    {"file": "c.py", "variable": "x", "in_test_file": True},
                ],
            },
        }
        result = enrich_findings("dead_code", payload)
        for item in result["results"]["unreachable"]:
            assert "confidence" in item
            assert 0.0 <= item["confidence"] <= 1.0
        # After return should score higher than after throw
        scores = [i["confidence"] for i in result["results"]["unreachable"]]
        assert scores[0] > scores[1]
        # Test-file unused var should be discounted
        test_var = result["results"]["unused_vars"][0]
        assert test_var["confidence"] < 0.70

    def test_secrets_payload_shape(self):
        """Secrets style: findings = [finding, ...] (flat list)."""
        payload = {
            "status": "ok",
            "findings": [
                {"type": "pattern_match", "file": "a.py", "category": "aws_key"},
                {"type": "entropy", "file": "b.py", "category": "high_entropy"},
                {"type": "pattern_match", "file": "c.py", "in_test_file": True},
            ],
        }
        result = enrich_findings("secrets", payload)
        for item in result["findings"]:
            assert "confidence" in item
        # pattern_match should score higher than entropy
        assert result["findings"][0]["confidence"] > result["findings"][1]["confidence"]
        # Test-file pattern match should be heavily discounted
        assert result["findings"][2]["confidence"] < result["findings"][0]["confidence"]

    def test_idempotent(self):
        payload = {
            "status": "ok",
            "results": {
                "unreachable": [{"file": "a.py", "confidence": 0.99}],
            },
            "findings": [{"type": "pattern_match", "confidence": 0.88}],
        }
        result = enrich_findings("dead_code", payload)
        # dead_code enriches results; secrets-style findings key is also present
        # but for dead_code engine it should not touch findings list (it's empty
        # of confidence-stamped items already).
        assert result["results"]["unreachable"][0]["confidence"] == 0.99

    def test_handles_non_dict_payload(self):
        assert enrich_findings("secrets", None) is None
        assert enrich_findings("secrets", []) == []

    def test_handles_empty_payload(self):
        result = enrich_findings("secrets", {"status": "ok"})
        assert result == {"status": "ok"}

    def test_preserves_other_fields(self):
        payload = {
            "status": "ok",
            "stats": {"total": 1},
            "findings": [{"type": "pattern_match"}],
            "risk": "high",
        }
        result = enrich_findings("secrets", payload)
        assert result["stats"] == {"total": 1}
        assert result["risk"] == "high"
        assert "confidence" in result["findings"][0]


# ─── confidence_distribution ───────────────────────────────────────────────


class TestConfidenceDistribution:
    """``confidence_distribution`` buckets findings by confidence range."""

    def test_basic_bucketing(self):
        findings = [
            {"confidence": 0.95},  # high
            {"confidence": 0.90},  # high
            {"confidence": 0.70},  # medium
            {"confidence": 0.50},  # medium
            {"confidence": 0.30},  # low
            {"confidence": 0.10},  # low
        ]
        buckets = confidence_distribution(findings)
        assert buckets["high"] == 2
        assert buckets["medium"] == 2
        assert buckets["low"] == 2
        assert buckets["unscored"] == 0

    def test_unscored_findings_counted(self):
        findings = [
            {"confidence": 0.95},
            {"no_confidence_here": True},
            {"also_unscored": True},
        ]
        buckets = confidence_distribution(findings)
        assert buckets["high"] == 1
        assert buckets["unscored"] == 2

    def test_boundary_high(self):
        # 0.85 is the high/medium boundary — inclusive on high side.
        assert confidence_distribution([{"confidence": 0.85}])["high"] == 1
        assert confidence_distribution([{"confidence": 0.84}])["medium"] == 1

    def test_boundary_medium_low(self):
        # 0.5 is the medium/low boundary — inclusive on medium side.
        assert confidence_distribution([{"confidence": 0.50}])["medium"] == 1
        assert confidence_distribution([{"confidence": 0.49}])["low"] == 1

    def test_empty_list(self):
        buckets = confidence_distribution([])
        assert buckets == {"high": 0, "medium": 0, "low": 0, "unscored": 0}

    def test_non_dict_items_skipped(self):
        findings = [{"confidence": 0.95}, "not a dict", 42, None]
        buckets = confidence_distribution(findings)
        assert buckets["high"] == 1
        assert buckets["unscored"] == 0  # non-dicts skipped, not counted as unscored


# ─── Integration: deadcode_engine ──────────────────────────────────────────


class TestDeadCodeEngineIntegration:
    """``detect_dead_code`` must return findings with ``confidence`` fields."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), "w") as f:
            f.write(code)
        return ws

    def test_unreachable_findings_have_confidence(self):
        code = """
function process(data) {
    return data;
    console.log("unreachable");
}
"""
        ws = self._create_workspace(code)
        try:
            from deadcode_engine import detect_dead_code
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                for item in result["results"]["unreachable"]:
                    assert "confidence" in item
                    assert 0.0 <= item["confidence"] <= 1.0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_confidence_reflects_after_return_vs_throw(self):
        code = """
function a() {
    return 1;
    console.log("unreachable after return");
}
function b() {
    throw new Error("x");
    console.log("unreachable after throw");
}
"""
        ws = self._create_workspace(code)
        try:
            from deadcode_engine import detect_dead_code
            result = detect_dead_code(ws)
            items = result["results"].get("unreachable", [])
            after_return = [i for i in items if i.get("after") == "return"]
            after_throw = [i for i in items if i.get("after") == "throw"]
            if after_return and after_throw:
                # After return should score higher (more certain)
                assert after_return[0]["confidence"] >= after_throw[0]["confidence"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_confidence_does_not_break_engine(self):
        """Even if confidence module has issues, engine must still return."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            from deadcode_engine import detect_dead_code
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            # Must have results key (even if empty)
            assert "results" in result
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── Integration: secrets_engine ───────────────────────────────────────────


class TestSecretsEngineIntegration:
    """``detect_secrets`` must return findings with ``confidence`` fields."""

    def _create_workspace(self, code, filename="config.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), "w") as f:
            f.write(code)
        return ws

    def test_pattern_match_finding_has_confidence(self):
        ws = self._create_workspace(
            'const API_KEY = "sk-1234567890abcdef1234567890abcdef";'
        )
        try:
            from secrets_engine import detect_secrets
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            for finding in result["findings"]:
                assert "confidence" in finding
                assert 0.0 <= finding["confidence"] <= 1.0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_pattern_match_scores_high(self):
        ws = self._create_workspace(
            'const API_KEY = "sk-1234567890abcdef1234567890abcdef";'
        )
        try:
            from secrets_engine import detect_secrets
            result = detect_secrets(ws)
            for finding in result["findings"]:
                if finding.get("type") == "pattern_match":
                    # Pattern matches are high confidence
                    assert finding["confidence"] >= 0.80
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_confidence_does_not_break_engine(self):
        """Even if confidence module has issues, engine must still return."""
        ws = self._create_workspace('function hello() { return "hi"; }')
        try:
            from secrets_engine import detect_secrets
            result = detect_secrets(ws)
            assert result["status"] == "ok"
            assert "findings" in result
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── Integration: formatters ───────────────────────────────────────────────


class TestFormatterIntegration:
    """``format_output`` must stamp ``schema_version`` on every output."""

    def test_ai_format_has_schema_version(self):
        from formatters import format_output
        data = {"status": "ok", "stats": {}, "findings": []}
        out = format_output(data, format_type="ai", command="test")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_json_format_has_schema_version(self):
        from formatters import format_output
        data = {"status": "ok", "stats": {}, "findings": []}
        out = format_output(data, format_type="json", command="test")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_json_format_does_not_mutate_input(self):
        """Raw JSON formatter stamps a copy, not the caller's dict."""
        from formatters import format_output
        data = {"status": "ok", "findings": []}
        format_output(data, format_type="json", command="test")
        # Original dict must NOT have schema_version (stamping is on a copy).
        assert "schema_version" not in data

    def test_ai_normalize_error_path_has_schema_version(self):
        from formatters import _normalize_to_ai
        result = _normalize_to_ai(
            {"status": "error", "error": "boom"}, command="test"
        )
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["status"] == "error"

    def test_ai_normalize_non_dict_has_schema_version(self):
        from formatters import _normalize_to_ai
        result = _normalize_to_ai("just a string", command="test")
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["status"] == "ok"

    def test_ai_normalize_ok_path_has_schema_version(self):
        from formatters import _normalize_to_ai
        result = _normalize_to_ai(
            {"status": "ok", "stats": {"x": 1}, "findings": []},
            command="test",
        )
        assert result["schema_version"] == SCHEMA_VERSION

    def test_markdown_format_does_not_crash(self):
        """Markdown format doesn't go through _normalize_to_ai; just verify
        it doesn't crash. schema_version is a JSON-output concern."""
        from formatters import format_output
        data = {"status": "ok", "stats": {"total_findings": 0}}
        out = format_output(data, format_type="markdown", command="test")
        assert isinstance(out, str)
        assert len(out) > 0


# ─── Integration: end-to-end CLI-style ─────────────────────────────────────


class TestEndToEndSchemaVersion:
    """Verify schema_version propagates through the full formatter pipeline."""

    def test_dead_code_ai_output_has_schema_version(self, workspace):
        from formatters import format_output
        from deadcode_engine import detect_dead_code

        # Empty workspace — engine should still return a valid payload.
        result = detect_dead_code(workspace)
        out = format_output(result, format_type="ai", command="dead-code")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["status"] == "ok"
        assert parsed["command"] == "dead-code"

    def test_secrets_ai_output_has_schema_version(self, workspace):
        from formatters import format_output
        from secrets_engine import detect_secrets

        result = detect_secrets(workspace)
        out = format_output(result, format_type="ai", command="secrets")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["status"] == "ok"

    def test_dead_code_json_output_has_schema_version(self, workspace):
        from formatters import format_output
        from deadcode_engine import detect_dead_code

        result = detect_dead_code(workspace)
        out = format_output(result, format_type="json", command="dead-code")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION

    def test_secrets_json_output_has_schema_version(self, workspace):
        from formatters import format_output
        from secrets_engine import detect_secrets

        result = detect_secrets(workspace)
        out = format_output(result, format_type="json", command="secrets")
        parsed = json.loads(out)
        assert parsed["schema_version"] == SCHEMA_VERSION
