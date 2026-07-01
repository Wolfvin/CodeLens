"""
CodeLens — rule-engine entry point.

Provides a single :func:`run_rules_against_file` function that the
``scan`` and ``check`` commands can call when the user passes
``--rule-file <path.yaml>``.

The integration is purely additive — when no ``--rule-file`` is supplied,
nothing in this module is called and CodeLens behaves exactly as before.

File header — CodeLens rule engine (Phase 1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from rule_matcher import Match, match_source
from rule_pattern_parser import Rule, RuleParseError, parse_rule_file


@dataclass
class RuleFileResult:
    """Aggregate result of running one or more rule files against one file."""

    file_path: str
    matches: list[Match]
    rules_loaded: int
    error: str | None = None


def load_rules(rule_files: Iterable[str]) -> tuple[list[Rule], list[str]]:
    """
    Load rules from one or more YAML files.

    Returns ``(rules, errors)`` where ``errors`` is a list of human-readable
    error strings (one per file that failed to parse). Files that fail
    do not abort the whole batch — partial results are still returned.
    """
    rules: list[Rule] = []
    errors: list[str] = []
    for path in rule_files:
        try:
            rules.extend(parse_rule_file(path))
        except RuleParseError as exc:
            errors.append(f"{path}: {exc}")
    return rules, errors


def run_rules_against_file(
    file_path: str,
    rule_files: Iterable[str],
) -> RuleFileResult:
    """
    Load rules from ``rule_files`` and run them against ``file_path``.

    Returns a :class:`RuleFileResult`. Never raises for parse errors or
    file-not-found — those are surfaced via ``result.error``.
    """
    rule_files = list(rule_files)
    rules, errors = load_rules(rule_files)
    if errors:
        return RuleFileResult(
            file_path=file_path,
            matches=[],
            rules_loaded=len(rules),
            error="; ".join(errors),
        )

    if not rules:
        return RuleFileResult(
            file_path=file_path,
            matches=[],
            rules_loaded=0,
            error=None,
        )

    try:
        with open(file_path, "rb") as fh:
            source_bytes = fh.read()
    except OSError as exc:
        return RuleFileResult(
            file_path=file_path,
            matches=[],
            rules_loaded=len(rules),
            error=f"cannot read {file_path}: {exc}",
        )

    # Use file extension to decide language. Phase 1: only Python.
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in {".py", ".pyw", ".pyi"}:
        return RuleFileResult(
            file_path=file_path,
            matches=[],
            rules_loaded=len(rules),
            error=None,
        )

    matches = match_source(rules, source_bytes)
    return RuleFileResult(
        file_path=file_path,
        matches=matches,
        rules_loaded=len(rules),
        error=None,
    )


def format_match_for_cli(m: Match, file_path: str) -> str:
    """One-line human-readable summary, suitable for stderr / CLI output."""
    row = m.range.start_point[0] + 1
    col = m.range.start_point[1] + 1
    mv = ""
    if m.metavariables:
        mv = " " + ", ".join(f"{k}={v!r}" for k, v in m.metavariables.items())
    return f"{file_path}:{row}:{col}: [{m.severity}] {m.rule_id}: {m.message}{mv}"
