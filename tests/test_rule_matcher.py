"""
Unit tests for the rule_matcher module.

Run with:

    cd <codelens-repo>
    python -m pytest tests/unit/test_rule_matcher.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from rule_matcher import (  # noqa: E402
    Match,
    evaluate_rule,
    match_source,
    parse_python,
)
from rule_pattern_parser import Pattern, Rule, parse_rule_file  # noqa: E402

FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures", "rules")


def _rule_from_id(fixture: str, rule_id: str) -> Rule:
    for r in parse_rule_file(os.path.join(FIXTURES_DIR, fixture)):
        if r.id == rule_id:
            return r
    raise AssertionError(f"rule {rule_id} not found in {fixture}")


def _ids(matches: list[Match]) -> set[str]:
    return {m.rule_id for m in matches}


# ---------------------------------------------------------------------------
# Basic pattern matching
# ---------------------------------------------------------------------------


def test_eval_matches_simple_call() -> None:
    r = _rule_from_id("example.yaml", "py.eval-builtin")
    src = "x = eval('1+1')\n"
    matches = match_source([r], src)
    assert len(matches) == 1
    m = matches[0]
    assert m.rule_id == "py.eval-builtin"
    assert m.metavariables.get("$X") == "'1+1'"


def test_eval_does_not_match_other_calls() -> None:
    r = _rule_from_id("example.yaml", "py.eval-builtin")
    src = "x = int('1')\ny = float('2.0')\n"
    matches = match_source([r], src)
    assert matches == []


def test_exec_matches() -> None:
    r = _rule_from_id("example.yaml", "py.exec-builtin")
    src = "exec('import os')\n"
    matches = match_source([r], src)
    assert len(matches) == 1


def test_assert_eq_true_matches() -> None:
    r = _rule_from_id("example.yaml", "py.assert-eq-true")
    src = "assert x == True\n"
    matches = match_source([r], src)
    assert len(matches) == 1
    assert matches[0].metavariables.get("$X") == "x"


def test_assert_eq_true_does_not_match_is_true() -> None:
    """pattern-not should exclude `assert x is True`."""
    r = _rule_from_id("example.yaml", "py.assert-eq-true")
    src = "assert x is True\n"
    matches = match_source([r], src)
    assert matches == []


def test_assert_eq_true_does_not_match_other_compare() -> None:
    r = _rule_from_id("example.yaml", "py.assert-eq-true")
    src = "assert x == 5\n"
    matches = match_source([r], src)
    assert matches == []


# ---------------------------------------------------------------------------
# pattern-either
# ---------------------------------------------------------------------------


def test_pattern_either_matches_all_branches() -> None:
    r = _rule_from_id("example.yaml", "py.os-system-injection")
    cases = [
        "os.system('rm -rf /')\n",
        "subprocess.call('rm -rf /', shell=True)\n",
        "subprocess.run('rm -rf /', shell=True)\n",
        "subprocess.Popen('rm -rf /', shell=True)\n",
    ]
    for src in cases:
        matches = match_source([r], src)
        assert len(matches) == 1, f"expected match in: {src!r}; got {matches}"


def test_pattern_either_does_not_match_safe_call() -> None:
    r = _rule_from_id("example.yaml", "py.os-system-injection")
    src = "subprocess.run(['ls', '-l'], shell=False)\n"
    matches = match_source([r], src)
    assert matches == []


# ---------------------------------------------------------------------------
# pattern-regex
# ---------------------------------------------------------------------------


def test_pattern_regex_matches() -> None:
    r = _rule_from_id("regex-only.yaml", "py.print-debug")
    matches = match_source([r], 'print("debug: here")\n')
    assert len(matches) == 1


def test_pattern_regex_does_not_match_normal_print() -> None:
    r = _rule_from_id("regex-only.yaml", "py.print-debug")
    matches = match_source([r], 'print("hello world")\n')
    assert matches == []


# ---------------------------------------------------------------------------
# Ellipsis metavar $...ARGS
# ---------------------------------------------------------------------------


def test_ellipsis_function_call_zero_args() -> None:
    r = _rule_from_id("ellipsis.yaml", "py.ellipsis-function-call")
    matches = match_source([r], "f()\n")
    assert len(matches) >= 1


def test_ellipsis_function_call_many_args() -> None:
    r = _rule_from_id("ellipsis.yaml", "py.ellipsis-function-call")
    src = "f(1, 2, 3, x=4, y=5)\n"
    matches = match_source([r], src)
    assert len(matches) >= 1
    # The ellipsis metavar should capture the argument list
    found = False
    for m in matches:
        if "$...ARGS" in m.metavariables:
            found = True
            # Sanity: captured text should at least mention `1` and `y=5`
            assert "1" in m.metavariables["$...ARGS"]
            assert "y=5" in m.metavariables["$...ARGS"]
    assert found


def test_ellipsis_tuple_matches_two_elements() -> None:
    r = _rule_from_id("ellipsis.yaml", "py.ellipsis-tuple")
    src = "t = (1, 2, 3, 4)\n"
    matches = match_source([r], src)
    assert len(matches) >= 1


def test_ellipsis_tuple_matches_single_element() -> None:
    """$...REST should accept zero-or-more, so a 1-tuple (with trailing comma)
    is also a match."""
    r = _rule_from_id("ellipsis.yaml", "py.ellipsis-tuple")
    src = "t = (1,)\n"
    matches = match_source([r], src)
    # tree-sitter parses `(1,)` as a tuple with one element
    assert len(matches) >= 1


# ---------------------------------------------------------------------------
# Multi-rule / multi-match
# ---------------------------------------------------------------------------


def test_multiple_rules_match_same_source() -> None:
    rules = parse_rule_file(os.path.join(FIXTURES_DIR, "example.yaml"))
    src = (
        "import os\n"
        "import subprocess\n"
        "x = eval(input())\n"
        "os.system('rm -rf /')\n"
        "assert flag == True\n"
    )
    matches = match_source(rules, src)
    matched_ids = _ids(matches)
    assert "py.eval-builtin" in matched_ids
    assert "py.os-system-injection" in matched_ids
    assert "py.assert-eq-true" in matched_ids


def test_match_range_is_correct() -> None:
    r = _rule_from_id("example.yaml", "py.eval-builtin")
    src = "x = eval('1+1')\n"
    matches = match_source([r], src)
    assert len(matches) == 1
    m = matches[0]
    # The matched range should be the eval(...) call itself, not the whole line
    matched_text = src.encode("utf-8")[m.range.start_byte:m.range.end_byte].decode()
    assert "eval(" in matched_text


def test_match_range_start_point_row_col() -> None:
    r = _rule_from_id("example.yaml", "py.eval-builtin")
    src = "x = 1\neval('evil')\n"
    matches = match_source([r], src)
    assert len(matches) == 1
    m = matches[0]
    # Row is 0-indexed internally; should be on line 2 → row 1
    assert m.range.start_point[0] == 1


# ---------------------------------------------------------------------------
# Misc fixture
# ---------------------------------------------------------------------------


def test_return_none_matches() -> None:
    r = _rule_from_id("misc.yaml", "py.return-none")
    matches = match_source([r], "def f():\n    return None\n")
    assert len(matches) == 1


def test_raise_generic_exception_matches() -> None:
    r = _rule_from_id("misc.yaml", "py.raise-generic-exception")
    matches = match_source([r], 'raise Exception("boom")\n')
    assert len(matches) == 1
    assert matches[0].metavariables.get("$MSG") == '"boom"'


def test_raise_specific_exception_does_not_match() -> None:
    r = _rule_from_id("misc.yaml", "py.raise-generic-exception")
    matches = match_source([r], 'raise ValueError("boom")\n')
    assert matches == []


# ---------------------------------------------------------------------------
# Smoke: evaluate_rule with raw tree
# ---------------------------------------------------------------------------


def test_evaluate_rule_with_raw_tree() -> None:
    r = _rule_from_id("example.yaml", "py.eval-builtin")
    tree = parse_python(b"eval('1+1')\n")
    matches = evaluate_rule(r, tree, b"eval('1+1')\n")
    assert len(matches) == 1
