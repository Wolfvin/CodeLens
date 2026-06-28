"""Tests for the rule test runner (``scripts/rule_test_runner.py``).

Verifies the snapshot-test framework: loading rule + test fixtures,
running samples through the semantic engine, comparing findings to
inline ``# ruleid:`` / ``# ok`` markers, and reporting pass/fail.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts/ to path so we can import rule_test_runner
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from rule_test_runner import (
    TestFailure,
    TestResult,
    determine_exit_code,
    run_tests,
    run_tests_recursive,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "rule_fixtures"


# ─── Single rule tests ─────────────────────────────────────────────────


def test_run_tests_python_sql_injection():
    """The py/sql-injection fixture should pass all samples."""
    rule_path = FIXTURES_DIR / "py_sql_injection.yaml"
    result = run_tests(rule_path)

    assert result.error is None, f"Unexpected error: {result.error}"
    assert result.rule_id == "py/sql-injection"
    assert result.total == 4  # 4 samples in the test file
    # All samples should pass (2 positive + 2 negative)
    assert result.passed == 4
    assert result.failed == 0
    assert result.is_pass


def test_run_tests_javascript_xss_dom():
    """The js/xss-dom fixture should pass all samples."""
    rule_path = FIXTURES_DIR / "js_xss_dom.yaml"
    result = run_tests(rule_path)

    assert result.error is None, f"Unexpected error: {result.error}"
    assert result.rule_id == "js/xss-dom"
    assert result.total == 4
    assert result.passed == 4
    assert result.failed == 0
    assert result.is_pass


def test_run_tests_missing_test_file_errors():
    """A rule with no .test.yaml companion should report an error."""
    # Write a rule with no test companion
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    tmp.write("""
rules:
  - id: py/no-test
    message: "No test file"
    severity: high
    language: python
    sources: [input]
    sinks: [eval]
""")
    tmp.close()
    try:
        result = run_tests(Path(tmp.name))
        assert result.error is not None
        assert "No test file found" in result.error
    finally:
        os.unlink(tmp.name)


def test_run_tests_malformed_test_yaml_errors():
    """A malformed .test.yaml should produce an error, not crash."""
    # Use a temp directory so the rule and test file have matching stems.
    tmpdir = tempfile.mkdtemp()
    rule_path = Path(tmpdir) / "myrule.yaml"
    test_path = Path(tmpdir) / "myrule.test.yaml"

    rule_path.write_text(
        """
rules:
  - id: py/malformed-test
    message: "Malformed test"
    severity: high
    language: python
    sources: [input]
    sinks: [eval]
""",
        encoding="utf-8",
    )
    test_path.write_text("this: is: not: valid: yaml: [unclosed", encoding="utf-8")

    result = run_tests(rule_path)
    assert result.error is not None
    assert "parse" in result.error.lower() or "yaml" in result.error.lower()


def test_run_tests_empty_samples_errors():
    """A test file with no samples list should error."""
    tmpdir = tempfile.mkdtemp()
    rule_path = Path(tmpdir) / "myrule.yaml"
    test_path = Path(tmpdir) / "myrule.test.yaml"

    rule_path.write_text(
        """
rules:
  - id: py/empty-samples
    message: "Empty samples"
    severity: high
    language: python
    sources: [input]
    sinks: [eval]
""",
        encoding="utf-8",
    )
    test_path.write_text("rule: py/empty-samples\nsamples: []\n", encoding="utf-8")

    result = run_tests(rule_path)
    assert result.error is not None
    assert "samples" in result.error.lower()


# ─── Marker parsing ────────────────────────────────────────────────────


def test_inline_ruleid_marker_detected():
    """An inline ``# ruleid:`` marker should produce a finding expectation."""
    from rule_test_runner import _parse_markers

    code = "eval(user_input)  # ruleid: py/eval-usage\n"
    exps = _parse_markers(code)
    assert len(exps) == 1
    assert exps[0].kind == "finding"
    assert exps[0].rule_id == "py/eval-usage"
    assert exps[0].line == 1


def test_inline_ok_marker_detected():
    """An inline ``# ok`` marker should produce a no-finding expectation."""
    from rule_test_runner import _parse_markers

    code = "safe_call()  # ok\n"
    exps = _parse_markers(code)
    assert len(exps) == 1
    assert exps[0].kind == "no-finding"
    assert exps[0].line == 1


def test_standalone_ruleid_marker_attributes_to_next_line():
    """A standalone ``# ruleid:`` attributes to the next code line."""
    from rule_test_runner import _parse_markers

    code = "# ruleid: py/eval-usage\neval(user_input)\n"
    exps = _parse_markers(code)
    assert len(exps) == 1
    assert exps[0].kind == "finding"
    assert exps[0].line == 2  # the code line, not the marker line


def test_todoruleid_marker_skipped_with_ignore_todo():
    """``# todoruleid:`` should be skipped when ignore_todo=True."""
    from rule_test_runner import _parse_markers

    code = "eval(user_input)  # todoruleid: py/eval-usage\n"
    # Without ignore_todo → expectation is kept
    exps = _parse_markers(code, ignore_todo=False)
    assert len(exps) == 1
    assert exps[0].is_todo is True

    # With ignore_todo → expectation is dropped
    exps = _parse_markers(code, ignore_todo=True)
    assert len(exps) == 0


def test_multiple_markers_in_one_sample():
    """Multiple markers in one sample should all be parsed."""
    from rule_test_runner import _parse_markers

    code = """
user = input()
eval(user)  # ruleid: py/eval
safe_call()  # ok
"""
    exps = _parse_markers(code)
    assert len(exps) == 2
    kinds = [e.kind for e in exps]
    assert "finding" in kinds
    assert "no-finding" in kinds


# ─── Directory tests ───────────────────────────────────────────────────


def test_run_tests_recursive_directory():
    """Running tests on the fixtures directory should test all 10 rules."""
    results = run_tests_recursive(FIXTURES_DIR)

    # We created 10 valid rule fixtures (5 Python + 5 JS)
    # The malformed/invalid fixtures (prefixed with _) don't have .test.yaml
    # companions, so they're skipped by run_tests_recursive.
    rule_ids = [r.rule_id for r in results]
    assert "py/sql-injection" in rule_ids
    assert "py/command-injection" in rule_ids
    assert "py/path-traversal" in rule_ids
    assert "py/ssrf" in rule_ids
    assert "py/xss-template" in rule_ids
    assert "js/xss-dom" in rule_ids
    assert "js/sql-injection" in rule_ids
    assert "js/command-injection" in rule_ids
    assert "js/path-traversal" in rule_ids
    assert "js/prototype-pollution" in rule_ids

    # All should pass
    for r in results:
        assert r.is_pass, f"Rule {r.rule_id} failed: {[f.to_dict() for f in r.failures]}"


def test_run_tests_recursive_single_file():
    """Passing a single file path should run tests for just that file."""
    rule_path = FIXTURES_DIR / "py_sql_injection.yaml"
    results = run_tests_recursive(rule_path)

    assert len(results) == 1
    assert results[0].rule_id == "py/sql-injection"
    assert results[0].is_pass


# ─── Exit code logic ──────────────────────────────────────────────────


def test_determine_exit_code_all_pass():
    """All passing results → exit 0."""
    results = [TestResult(rule_path="a.yaml", rule_id="a", total=2, passed=2)]
    assert determine_exit_code(results) == 0


def test_determine_exit_code_any_fail():
    """Any failing result → exit 1."""
    results = [
        TestResult(rule_path="a.yaml", rule_id="a", total=2, passed=2),
        TestResult(rule_path="b.yaml", rule_id="b", total=2, passed=1, failed=1),
    ]
    assert determine_exit_code(results) == 1


def test_determine_exit_code_error_counts_as_fail():
    """An errored result should count as failure → exit 1."""
    results = [TestResult(rule_path="a.yaml", rule_id="a", error="something went wrong")]
    assert determine_exit_code(results) == 1


# ─── Dataclass serialization ──────────────────────────────────────────


def test_test_failure_to_dict():
    """TestFailure should serialize to a clean dict."""
    failure = TestFailure(
        sample_name="positive_basic",
        line=42,
        expected="finding",
        actual="no-finding",
        rule_id="py/sql-injection",
        message="Expected finding on line 42",
    )
    d = failure.to_dict()
    assert d["sample_name"] == "positive_basic"
    assert d["line"] == 42
    assert d["expected"] == "finding"
    assert d["actual"] == "no-finding"
    assert d["rule_id"] == "py/sql-injection"
    assert d["message"] == "Expected finding on line 42"


def test_test_result_to_dict():
    """TestResult should serialize to a clean dict."""
    result = TestResult(
        rule_path="test.yaml",
        rule_id="py/test",
        test_path="test.test.yaml",
        total=3,
        passed=2,
        failed=1,
    )
    failure = TestFailure(
        sample_name="bad",
        line=10,
        expected="finding",
        actual="no-finding",
        rule_id="py/test",
        message="oops",
    )
    result.failures.append(failure)

    d = result.to_dict()
    assert d["rule_path"] == "test.yaml"
    assert d["rule_id"] == "py/test"
    assert d["total"] == 3
    assert d["passed"] == 2
    assert d["failed"] == 1
    assert d["is_pass"] is False
    assert len(d["failures"]) == 1
    assert d["failures"][0]["sample_name"] == "bad"


# ─── All 10 fixtures pass ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule_file",
    [
        "py_sql_injection.yaml",
        "py_command_injection.yaml",
        "py_path_traversal.yaml",
        "py_ssrf.yaml",
        "py_xss_template.yaml",
        "js_xss_dom.yaml",
        "js_sql_injection.yaml",
        "js_command_injection.yaml",
        "js_path_traversal.yaml",
        "js_prototype_pollution.yaml",
    ],
)
def test_all_fixtures_pass(rule_file):
    """Every migrated fixture should pass its snapshot tests."""
    rule_path = FIXTURES_DIR / rule_file
    result = run_tests(rule_path)

    assert result.error is None, f"{rule_file}: error={result.error}"
    assert result.is_pass, (
        f"{rule_file}: {result.passed}/{result.total} passed, "
        f"{result.failed} failed. Failures: {[f.to_dict() for f in result.failures]}"
    )
