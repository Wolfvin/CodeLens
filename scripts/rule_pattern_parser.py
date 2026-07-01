"""
CodeLens — Semgrep-compatible YAML rule parser (Phase 1).

Parses rule files that follow a Semgrep-compatible subset:

    rules:
      - id: py.assert-eq-true
        languages: [python]
        severity: INFO
        message: "Use assertEqual instead of assert == True"
        patterns:
          - pattern: assert $X == True
          - pattern-not: assert $X is True

Phase 1 supports four pattern operators:

    pattern: <expr>          AST shape match (exact + metavar)
    pattern-regex: <regex>   regex match on node source text
    pattern-not: <expr>      exclude matches whose AST matches <expr>
    pattern-either: [...]    OR across a list of {pattern: ...} dicts

Metavariable syntax:

    $X           capture any single AST node
    $...ARGS     match zero-or-more siblings (rest pattern, only inside
                 sequences such as argument lists, tuple elements, etc.)

Only the `python` language is supported in Phase 1.

This module is parsing-only. It does not perform matching — see
``rule_matcher.py`` for the AST matcher.

File header — CodeLens rule engine (Phase 1).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

import yaml


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pattern:
    """A single pattern operator parsed from a rule."""

    kind: str  # "pattern" | "pattern-regex" | "pattern-not" | "pattern-either"
    # For "pattern" / "pattern-not": raw source string (e.g. "assert $X == True")
    # For "pattern-regex": compiled regex object
    # For "pattern-either": list of child Pattern objects
    value: Any


@dataclass(frozen=True)
class Rule:
    """A parsed rule."""

    id: str
    languages: tuple[str, ...]
    severity: str
    message: str
    patterns: tuple[Pattern, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional: source file the rule was loaded from (for error messages)
    source_file: str | None = None


class RuleParseError(ValueError):
    """Raised when a rule file is malformed."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_LANGUAGES = frozenset({"python"})
SUPPORTED_PATTERN_KEYS = frozenset(
    {"pattern", "pattern-regex", "pattern-not", "pattern-either"}
)
VALID_SEVERITIES = frozenset(
    {"ERROR", "WARNING", "INFO", "HINT", "CRITICAL", "HIGH", "MEDIUM", "LOW"}
)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise RuleParseError(f"rule file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise RuleParseError(f"YAML parse error in {path}: {exc}") from exc
    if data is None:
        raise RuleParseError(f"rule file is empty: {path}")
    if not isinstance(data, dict):
        raise RuleParseError(
            f"rule file top-level must be a mapping, got {type(data).__name__}: {path}"
        )
    return data


# ---------------------------------------------------------------------------
# Pattern parsing
# ---------------------------------------------------------------------------


def _parse_single_pattern(op: str, raw: Any, source: str | None) -> Pattern:
    if op == "pattern-regex":
        if not isinstance(raw, str):
            raise RuleParseError(
                f"pattern-regex must be a string, got {type(raw).__name__}"
            )
        try:
            compiled = re.compile(raw, re.MULTILINE)
        except re.error as exc:
            raise RuleParseError(f"invalid regex in pattern-regex: {exc}") from exc
        return Pattern(kind="pattern-regex", value=compiled)

    if op == "pattern-either":
        if not isinstance(raw, list) or not raw:
            raise RuleParseError(
                "pattern-either must be a non-empty list of pattern dicts"
            )
        children: list[Pattern] = []
        for item in raw:
            if not isinstance(item, dict) or len(item) != 1:
                raise RuleParseError(
                    "pattern-either items must each contain exactly one pattern operator"
                )
            sub_op, sub_val = next(iter(item.items()))
            if sub_op not in {"pattern", "pattern-regex"}:
                raise RuleParseError(
                    f"pattern-either only supports pattern/pattern-regex, got '{sub_op}'"
                )
            children.append(_parse_single_pattern(sub_op, sub_val, source))
        return Pattern(kind="pattern-either", value=tuple(children))

    # pattern / pattern-not
    if not isinstance(raw, str) or not raw.strip():
        raise RuleParseError(f"{op} must be a non-empty string, got {raw!r}")
    return Pattern(kind=op, value=raw)


def _parse_patterns_block(raw: Any, source: str | None) -> tuple[Pattern, ...]:
    """
    The `patterns:` block can be a list of dicts (Semgrep canonical form):

        patterns:
          - pattern: ...
          - pattern-not: ...
          - pattern-either:
              - pattern: ...
              - pattern: ...

    For Phase 1 we also accept a single-dict shorthand:

        pattern: assert $X == True
    """
    if raw is None:
        return tuple()

    if isinstance(raw, dict):
        # single-dict shorthand
        return (_parse_patterns_block([raw], source))

    if not isinstance(raw, list):
        raise RuleParseError(
            f"patterns must be a list of dicts, got {type(raw).__name__}"
        )

    out: list[Pattern] = []
    for entry in raw:
        if not isinstance(entry, dict) or not entry:
            raise RuleParseError(
                "each entry in `patterns:` must be a non-empty mapping"
            )
        if len(entry) != 1:
            raise RuleParseError(
                "each entry in `patterns:` must contain exactly one pattern operator, "
                f"got keys {list(entry.keys())}"
            )
        op, val = next(iter(entry.items()))
        if op not in SUPPORTED_PATTERN_KEYS:
            raise RuleParseError(
                f"unsupported pattern operator '{op}'. "
                f"Supported: {sorted(SUPPORTED_PATTERN_KEYS)}"
            )
        out.append(_parse_single_pattern(op, val, source))
    return tuple(out)


# ---------------------------------------------------------------------------
# Rule parsing
# ---------------------------------------------------------------------------


def _normalize_severity(raw: Any) -> str:
    if raw is None:
        return "INFO"
    if not isinstance(raw, str):
        raise RuleParseError(f"severity must be a string, got {type(raw).__name__}")
    sev = raw.strip().upper()
    if sev not in VALID_SEVERITIES:
        raise RuleParseError(
            f"invalid severity '{raw}'. Valid: {sorted(VALID_SEVERITIES)}"
        )
    return sev


def _normalize_languages(raw: Any) -> tuple[str, ...]:
    if raw is None:
        raise RuleParseError("missing required field: languages")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise RuleParseError("languages must be a non-empty list")
    out: list[str] = []
    for lang in raw:
        if not isinstance(lang, str):
            raise RuleParseError(
                f"language entry must be a string, got {type(lang).__name__}"
            )
        norm = lang.strip().lower()
        if norm not in SUPPORTED_LANGUAGES:
            raise RuleParseError(
                f"unsupported language '{lang}'. Phase 1 only supports: "
                f"{sorted(SUPPORTED_LANGUAGES)}"
            )
        out.append(norm)
    return tuple(out)


def _parse_rule_dict(raw: dict[str, Any], source: str | None) -> Rule:
    if not isinstance(raw, dict):
        raise RuleParseError(f"rule entry must be a mapping, got {type(raw).__name__}")

    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise RuleParseError("rule is missing required string field: id")

    message = raw.get("message", "")
    if not isinstance(message, str):
        raise RuleParseError(f"message must be a string, got {type(message).__name__}")

    severity = _normalize_severity(raw.get("severity"))
    languages = _normalize_languages(raw.get("languages"))

    # Phase 1: only python supported — fast-fail if any non-python lang appears
    if "python" not in languages:
        raise RuleParseError(
            f"rule '{rule_id}' does not include python in languages; "
            "Phase 1 only supports python"
        )

    patterns = _parse_patterns_block(raw.get("patterns"), source)

    # If `patterns` absent but a single shorthand operator exists at top-level,
    # promote it into a single-element patterns list.
    if not patterns:
        shorthand = [
            k for k in SUPPORTED_PATTERN_KEYS if k in raw and k != "pattern-either"
        ]
        if not shorthand:
            raise RuleParseError(
                f"rule '{rule_id}' has no patterns and no shorthand pattern operator"
            )
        if len(shorthand) > 1:
            raise RuleParseError(
                f"rule '{rule_id}' has multiple shorthand operators: {shorthand}"
            )
        op = shorthand[0]
        patterns = (_parse_single_pattern(op, raw[op], source),)

    metadata = {
        k: v
        for k, v in raw.items()
        if k not in {"id", "languages", "severity", "message", "patterns"}
        | SUPPORTED_PATTERN_KEYS
    }

    return Rule(
        id=rule_id,
        languages=languages,
        severity=severity,
        message=message,
        patterns=patterns,
        metadata=metadata,
        source_file=source,
    )


def parse_rule_file(path: str) -> list[Rule]:
    """
    Parse a Semgrep-compatible YAML rule file.

    Returns a list of :class:`Rule` objects. Raises :class:`RuleParseError`
    on any structural problem so callers can surface a clean error message.
    """
    data = _load_yaml(path)
    rules_raw = data.get("rules")
    if rules_raw is None:
        raise RuleParseError(f"rule file {path} is missing top-level 'rules:' key")
    if not isinstance(rules_raw, list) or not rules_raw:
        raise RuleParseError(
            f"'rules:' in {path} must be a non-empty list, got {type(rules_raw).__name__}"
        )
    out: list[Rule] = []
    for idx, entry in enumerate(rules_raw):
        try:
            out.append(_parse_rule_dict(entry, source=path))
        except RuleParseError as exc:
            raise RuleParseError(f"{path} (rule #{idx + 1}): {exc}") from exc
    return out


def parse_rule_files(paths: Iterable[str]) -> list[Rule]:
    """Parse multiple rule files and return the combined list of rules."""
    out: list[Rule] = []
    for p in paths:
        out.extend(parse_rule_file(p))
    return out


# ---------------------------------------------------------------------------
# CLI smoke entry — `python -m scripts.rule_pattern_parser <file>` prints summary
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m scripts.rule_pattern_parser <rule.yaml>", file=None)
        return 2
    try:
        rules = parse_rule_file(argv[1])
    except RuleParseError as exc:
        import sys

        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"parsed {len(rules)} rule(s) from {argv[1]}:")
    for r in rules:
        print(
            f"  - id={r.id} sev={r.severity} langs={list(r.languages)} "
            f"patterns={len(r.patterns)}"
        )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(_main(sys.argv))
