"""Tests for the rule validator (``scripts/rule_validator.py``).

Covers all 4 validation stages:
1. YAML syntax (malformed YAML, unclosed quote)
2. Schema (missing required fields, invalid severity enum)
3. Pattern parseability (skipped gracefully when tree-sitter unavailable)
4. Cross-field (pattern + patterns mutually exclusive, fix requires pattern)

Also tests the exit-code logic (``determine_exit_code``) for the 0/1/2
contract.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts/ to path so we can import rule_validator
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from rule_validator import (
    REQUIRED_FIELDS,
    VALID_SEVERITIES,
    ValidationIssue,
    ValidationResult,
    determine_exit_code,
    validate_rule,
    validate_rule_files,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "rule_fixtures"


def _write_tmp_rule(content: str) -> Path:
    """Write a rule YAML to a temp file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


# ─── Valid rule ────────────────────────────────────────────────────────


def test_validate_valid_rule_passes():
    """A well-formed taint-style rule should validate with no errors."""
    rule_path = FIXTURES_DIR / "py_sql_injection.yaml"
    result = validate_rule(rule_path)

    assert result.is_valid, f"Expected valid, got errors: {[e.to_dict() for e in result.errors]}"
    assert result.rules_checked == 1
    assert len(result.errors) == 0
    # Warnings are OK (e.g., pattern parseability skip for taint-style rules)


def test_validate_javascript_rule_passes():
    """A JS taint-style rule should also validate cleanly."""
    rule_path = FIXTURES_DIR / "js_sql_injection.yaml"
    result = validate_rule(rule_path)

    assert result.is_valid, f"Expected valid, got errors: {[e.to_dict() for e in result.errors]}"
    assert result.rules_checked == 1


def test_validate_multiple_rules_in_one_file():
    """A file with multiple rule entries should validate all of them."""
    content = """
rules:
  - id: py/rule-1
    message: "First rule"
    severity: high
    language: python
    sources: [input]
    sinks: [eval]
  - id: py/rule-2
    message: "Second rule"
    severity: critical
    language: python
    sources: [input]
    sinks: [exec]
"""
    path = _write_tmp_rule(content)
    try:
        result = validate_rule(path)
        assert result.is_valid
        assert result.rules_checked == 2
    finally:
        path.unlink()


# ─── Stage 1: YAML syntax ─────────────────────────────────────────────


def test_validate_malformed_yaml_fails():
    """Malformed YAML (unclosed quote) should produce a yaml_syntax error."""
    rule_path = FIXTURES_DIR / "_malformed_yaml.yaml"
    result = validate_rule(rule_path)

    assert not result.is_valid
    assert len(result.errors) >= 1
    assert result.errors[0].category == "yaml_syntax"
    assert "YAML parse error" in result.errors[0].message


def test_validate_empty_file_fails():
    """An empty file should produce a yaml_syntax error."""
    path = _write_tmp_rule("")
    try:
        result = validate_rule(path)
        assert not result.is_valid
        assert result.errors[0].category == "yaml_syntax"
    finally:
        path.unlink()


def test_validate_nonexistent_file_fails():
    """A missing file should produce a yaml_syntax error, not crash."""
    path = Path("/nonexistent/rule.yaml")
    result = validate_rule(path)

    assert not result.is_valid
    assert result.errors[0].category == "yaml_syntax"
    assert "Cannot read file" in result.errors[0].message


def test_validate_top_level_not_mapping_fails():
    """Top-level YAML that is a list (not a mapping) should fail."""
    path = _write_tmp_rule("- id: foo\n  message: bar\n  severity: high\n  language: python\n")
    try:
        result = validate_rule(path)
        assert not result.is_valid
        assert result.errors[0].category == "yaml_syntax"
    finally:
        path.unlink()


# ─── Stage 2: Schema validation ───────────────────────────────────────


def test_validate_missing_required_field_fails():
    """A rule missing a required field (severity) should fail with schema error."""
    rule_path = FIXTURES_DIR / "_missing_required.yaml"
    result = validate_rule(rule_path)

    assert not result.is_valid
    schema_errors = [e for e in result.errors if e.category == "schema"]
    assert len(schema_errors) >= 1
    assert any("severity" in e.message for e in schema_errors)


def test_validate_invalid_severity_enum_fails():
    """A severity outside the allowed enum should fail with schema error."""
    rule_path = FIXTURES_DIR / "_invalid_severity.yaml"
    result = validate_rule(rule_path)

    assert not result.is_valid
    schema_errors = [e for e in result.errors if e.category == "schema"]
    assert len(schema_errors) >= 1
    assert any("invalid severity" in e.message for e in schema_errors)


def test_validate_all_required_fields_enforced():
    """Each required field, when missing, should produce a schema error."""
    # Build the content WITHOUT the field being tested, rather than using
    # string replacement (which is fragile to indentation differences).
    base_fields = {
        "id": "py/test",
        "message": '"test"',
        "severity": "high",
        "language": "python",
    }
    for field_name in REQUIRED_FIELDS:
        fields = dict(base_fields)
        del fields[field_name]
        lines = [f"  - {k}: {v}" for k, v in fields.items()]
        content = "rules:\n" + "\n".join(lines) + "\n"

        path = _write_tmp_rule(content)
        try:
            result = validate_rule(path)
            assert not result.is_valid, f"Missing {field_name} should fail"
            assert any(
                field_name in e.message and e.category == "schema" for e in result.errors
            ), f"Missing {field_name} should produce schema error mentioning {field_name}"
        finally:
            path.unlink()


def test_validate_unknown_key_warns():
    """Unknown fields should produce a warning (not error), with typo suggestion."""
    rule_path = FIXTURES_DIR / "_typo_and_unknown.yaml"
    result = validate_rule(rule_path)

    # Unknown keys are warnings, not errors — rule still validates
    assert len(result.warnings) >= 1
    unknown_warnings = [w for w in result.warnings if w.category == "unknown_key"]
    assert len(unknown_warnings) >= 1

    # The typo 'pattern-eiter' should suggest 'pattern-either'
    typo_warnings = [w for w in unknown_warnings if "pattern-eiter" in w.message]
    assert len(typo_warnings) >= 1
    assert "pattern-either" in typo_warnings[0].message


# ─── Stage 4: Cross-field validation ──────────────────────────────────


def test_validate_mutually_exclusive_pattern_and_patterns():
    """Using both 'pattern' and 'patterns' should fail with cross_field error."""
    rule_path = FIXTURES_DIR / "_mutually_exclusive.yaml"
    result = validate_rule(rule_path)

    assert not result.is_valid
    cross_field_errors = [e for e in result.errors if e.category == "cross_field"]
    assert len(cross_field_errors) >= 1
    assert any("mutually exclusive" in e.message for e in cross_field_errors)


def test_validate_fix_requires_pattern():
    """'fix' without 'pattern' or 'patterns' should fail with cross_field error."""
    rule_path = FIXTURES_DIR / "_fix_without_pattern.yaml"
    result = validate_rule(rule_path)

    assert not result.is_valid
    cross_field_errors = [e for e in result.errors if e.category == "cross_field"]
    assert len(cross_field_errors) >= 1
    assert any("fix" in e.message and "requires" in e.message for e in cross_field_errors)


def test_validate_fix_with_pattern_passes():
    """'fix' with 'pattern' should pass cross_field validation."""
    content = """
rules:
  - id: py/fix-ok
    message: "Fix with pattern"
    severity: high
    language: python
    pattern: eval($X)
    fix: "ast.literal_eval($X)"
"""
    path = _write_tmp_rule(content)
    try:
        result = validate_rule(path)
        cross_field_errors = [e for e in result.errors if e.category == "cross_field"]
        assert len(cross_field_errors) == 0
    finally:
        path.unlink()


# ─── Stage 3: Pattern parseability ────────────────────────────────────


def test_validate_pattern_parseability_graceful_skip():
    """When tree-sitter is unavailable, pattern check should warn, not error."""
    content = """
rules:
  - id: py/pattern-rule
    message: "Pattern rule"
    severity: high
    language: python
    pattern: eval($X)
"""
    path = _write_tmp_rule(content)
    try:
        result = validate_rule(path)
        # Pattern parseability is a warning (metavariables cause false positives),
        # and when tree-sitter is missing it's skipped with a warning.
        # Either way, no hard error from pattern check.
        pattern_errors = [e for e in result.errors if e.category == "pattern"]
        assert len(pattern_errors) == 0
    finally:
        path.unlink()


# ─── Exit code logic ──────────────────────────────────────────────────


def test_determine_exit_code_all_valid():
    """All valid results → exit 0."""
    results = [ValidationResult(rule_path="a.yaml", is_valid=True)]
    assert determine_exit_code(results) == 0


def test_determine_exit_code_with_errors():
    """Any error → exit 1."""
    results = [
        ValidationResult(rule_path="a.yaml", is_valid=True),
        ValidationResult(rule_path="b.yaml", is_valid=False),
    ]
    assert determine_exit_code(results) == 1


def test_determine_exit_code_warnings_without_strict():
    """Warnings without --strict → exit 0."""
    result = ValidationResult(rule_path="a.yaml", is_valid=True)
    result.add_warning("unknown_key", "test warning")
    assert determine_exit_code([result], strict=False) == 0


def test_determine_exit_code_warnings_with_strict():
    """Warnings with --strict → exit 2."""
    result = ValidationResult(rule_path="a.yaml", is_valid=True)
    result.add_warning("unknown_key", "test warning")
    assert determine_exit_code([result], strict=True) == 2


def test_determine_exit_code_errors_override_warnings_strict():
    """Errors take precedence over warnings — exit 1 even with --strict."""
    result = ValidationResult(rule_path="a.yaml", is_valid=False)
    result.add_warning("unknown_key", "test warning")
    result.add_error("schema", "test error")
    assert determine_exit_code([result], strict=True) == 1


# ─── Dataclass serialization ──────────────────────────────────────────


def test_validation_issue_to_dict():
    """ValidationIssue should serialize to a clean dict."""
    issue = ValidationIssue("error", "schema", "test message", line=42)
    d = issue.to_dict()
    assert d == {"level": "error", "category": "schema", "message": "test message", "line": 42}


def test_validation_result_to_dict():
    """ValidationResult should serialize to a clean dict."""
    result = ValidationResult(rule_path="test.yaml")
    result.add_error("schema", "error msg")
    result.add_warning("unknown_key", "warning msg")

    d = result.to_dict()
    assert d["rule_path"] == "test.yaml"
    assert d["is_valid"] is False
    assert d["has_warnings"] is True
    assert len(d["errors"]) == 1
    assert len(d["warnings"]) == 1
    assert d["errors"][0]["category"] == "schema"


def test_validate_rule_files_multiple():
    """validate_rule_files should return one result per file."""
    paths = [
        FIXTURES_DIR / "py_sql_injection.yaml",
        FIXTURES_DIR / "js_xss_dom.yaml",
    ]
    results = validate_rule_files(paths)
    assert len(results) == 2
    assert all(r.is_valid for r in results)
