"""
Unit tests for the rule_pattern_parser module.

Run with:

    cd <codelens-repo>
    python -m pytest tests/unit/test_rule_pattern_parser.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# Make `scripts/` importable as top-level modules.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from rule_pattern_parser import (  # noqa: E402
    Pattern,
    Rule,
    RuleParseError,
    parse_rule_file,
)


FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures", "rules")


def _load(name: str) -> list[Rule]:
    return parse_rule_file(os.path.join(FIXTURES_DIR, name))


# --- happy paths ----------------------------------------------------------


def test_load_example_yaml() -> None:
    rules = _load("example.yaml")
    assert len(rules) == 5
    ids = [r.id for r in rules]
    assert "py.assert-eq-true" in ids
    assert "py.eval-builtin" in ids
    assert "py.os-system-injection" in ids
    assert "py.bare-except" in ids


def test_eval_builtin_rule_shape() -> None:
    rules = {r.id: r for r in _load("example.yaml")}
    r = rules["py.eval-builtin"]
    assert r.severity == "ERROR"
    assert r.languages == ("python",)
    assert r.message.startswith("Avoid eval()")
    assert len(r.patterns) == 1
    assert r.patterns[0].kind == "pattern"
    assert r.patterns[0].value == "eval($X)"


def test_pattern_either_parsed_as_nested_list() -> None:
    rules = {r.id: r for r in _load("example.yaml")}
    r = rules["py.os-system-injection"]
    assert len(r.patterns) == 1
    pe = r.patterns[0]
    assert pe.kind == "pattern-either"
    assert isinstance(pe.value, tuple)
    assert len(pe.value) == 4
    for child in pe.value:
        assert child.kind in {"pattern"}


def test_pattern_not_parsed() -> None:
    rules = {r.id: r for r in _load("example.yaml")}
    r = rules["py.assert-eq-true"]
    kinds = [p.kind for p in r.patterns]
    assert "pattern" in kinds
    assert "pattern-not" in kinds


def test_pattern_regex_compiled() -> None:
    rules = _load("regex-only.yaml")
    assert len(rules) == 1
    p = rules[0].patterns[0]
    assert p.kind == "pattern-regex"
    import re

    assert isinstance(p.value, re.Pattern)
    assert p.value.search('print("debug: hello")') is not None
    assert p.value.search('print("normal")') is None


def test_ellipsis_fixture_loads() -> None:
    rules = {r.id: r for r in _load("ellipsis.yaml")}
    assert "py.ellipsis-function-call" in rules
    assert "py.ellipsis-tuple" in rules


def test_misc_fixture_loads() -> None:
    rules = {r.id: r for r in _load("misc.yaml")}
    assert "py.return-none" in rules
    assert "py.raise-generic-exception" in rules
    assert "py.pass-statement" in rules


# --- error paths ----------------------------------------------------------


def test_missing_file_raises() -> None:
    with pytest.raises(RuleParseError, match="not found"):
        parse_rule_file("/nonexistent/rule.yaml")


def test_empty_file_raises(tmp_path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    with pytest.raises(RuleParseError, match="empty"):
        parse_rule_file(str(p))


def test_missing_rules_key_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("foo: bar\n", encoding="utf-8")
    with pytest.raises(RuleParseError, match="missing top-level"):
        parse_rule_file(str(p))


def test_unsupported_language_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [javascript]\n    pattern: foo()\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="only supports"):
        parse_rule_file(str(p))


def test_no_patterns_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [python]\n    message: m\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="no patterns"):
        parse_rule_file(str(p))


def test_bad_pattern_operator_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [python]\n    patterns:\n"
        "      - pattern-something: foo\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="unsupported pattern operator"):
        parse_rule_file(str(p))


def test_invalid_severity_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [python]\n    severity: BANANA\n"
        "    pattern: foo()\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="invalid severity"):
        parse_rule_file(str(p))


def test_invalid_regex_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [python]\n    patterns:\n"
        "      - pattern-regex: '[unbalanced'\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="invalid regex"):
        parse_rule_file(str(p))


def test_pattern_either_invalid_child_raises(tmp_path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "rules:\n  - id: x\n    languages: [python]\n    patterns:\n"
        "      - pattern-either:\n          - pattern-not: foo\n",
        encoding="utf-8",
    )
    with pytest.raises(RuleParseError, match="pattern-either only supports"):
        parse_rule_file(str(p))


# --- structural invariants ------------------------------------------------


def test_all_rules_have_python_language() -> None:
    for name in os.listdir(FIXTURES_DIR):
        if not name.endswith(".yaml"):
            continue
        for r in _load(name):
            assert "python" in r.languages


def test_all_rules_have_id_and_message() -> None:
    for name in os.listdir(FIXTURES_DIR):
        if not name.endswith(".yaml"):
            continue
        for r in _load(name):
            assert r.id
            assert isinstance(r.message, str)
            assert r.patterns
