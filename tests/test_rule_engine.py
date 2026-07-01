"""
Tests for the rule_engine entry-point module — simulates how the
`scan --rule-file` integration would behave.

Run with:

    cd <codelens-repo>
    python -m pytest tests/unit/test_rule_engine.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from rule_engine import (  # noqa: E402
    format_match_for_cli,
    load_rules,
    run_rules_against_file,
)

FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures", "rules")


def test_load_rules_all_fixtures() -> None:
    files = [
        os.path.join(FIXTURES_DIR, n)
        for n in os.listdir(FIXTURES_DIR)
        if n.endswith(".yaml")
    ]
    rules, errors = load_rules(files)
    assert errors == []
    assert len(rules) >= 9  # 5 + 1 + 1 + 2 + 3 = 12 actually


def test_load_rules_handles_bad_file() -> None:
    rules, errors = load_rules(["/nonexistent/rule.yaml"])
    assert rules == []
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_run_rules_against_python_file(tmp_path) -> None:
    py = tmp_path / "evil.py"
    py.write_text(
        "import os\n"
        "x = eval('1+1')\n"
        "os.system('rm -rf /')\n",
        encoding="utf-8",
    )
    result = run_rules_against_file(
        str(py), [os.path.join(FIXTURES_DIR, "example.yaml")]
    )
    assert result.error is None
    assert result.rules_loaded == 5
    ids = {m.rule_id for m in result.matches}
    assert "py.eval-builtin" in ids
    assert "py.os-system-injection" in ids


def test_run_rules_against_non_python_file_is_noop(tmp_path) -> None:
    txt = tmp_path / "notes.txt"
    txt.write_text("eval('hi')\n", encoding="utf-8")
    result = run_rules_against_file(
        str(txt), [os.path.join(FIXTURES_DIR, "example.yaml")]
    )
    assert result.error is None
    assert result.matches == []


def test_run_rules_against_missing_file_returns_error(tmp_path) -> None:
    result = run_rules_against_file(
        str(tmp_path / "missing.py"),
        [os.path.join(FIXTURES_DIR, "example.yaml")],
    )
    assert result.error is not None
    assert "cannot read" in result.error
    assert result.matches == []


def test_run_rules_with_bad_rule_file_returns_error(tmp_path) -> None:
    py = tmp_path / "x.py"
    py.write_text("x = 1\n", encoding="utf-8")
    result = run_rules_against_file(str(py), ["/nonexistent/rule.yaml"])
    assert result.error is not None
    assert "not found" in result.error
    assert result.matches == []


def test_format_match_for_cli() -> None:
    from rule_matcher import Match, Range

    m = Match(
        rule_id="py.eval-builtin",
        range=Range(10, 20, (1, 5), (1, 15)),
        severity="ERROR",
        message="Avoid eval() — code injection risk",
        metavariables={"$X": "'1+1'"},
    )
    line = format_match_for_cli(m, "evil.py")
    assert "evil.py:2:6:" in line  # row+1, col+1
    assert "[ERROR]" in line
    assert "py.eval-builtin" in line
    assert "$X=" in line


def test_run_multiple_rule_files(tmp_path) -> None:
    py = tmp_path / "all.py"
    py.write_text(
        "eval('1')\n"
        "print(\"debug: x\")\n"
        "raise Exception('boom')\n",
        encoding="utf-8",
    )
    result = run_rules_against_file(
        str(py),
        [
            os.path.join(FIXTURES_DIR, "example.yaml"),
            os.path.join(FIXTURES_DIR, "regex-only.yaml"),
            os.path.join(FIXTURES_DIR, "misc.yaml"),
        ],
    )
    assert result.error is None
    ids = {m.rule_id for m in result.matches}
    assert "py.eval-builtin" in ids
    assert "py.print-debug" in ids
    assert "py.raise-generic-exception" in ids
