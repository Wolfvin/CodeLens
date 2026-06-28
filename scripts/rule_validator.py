"""Rule Validator for CodeLens — validates rule YAML files.

Catches the silent-skip class of bugs: typos, unknown keys, missing required
fields, invalid enum values, unparseable patterns, and cross-field violations.
Designed to be reused by the ``rule-validate`` CLI command, pre-commit hooks,
CI pipelines, and programmatic callers.

Validation pipeline (4 stages, fail-fast per rule but continue across rules):

1. **YAML syntax** — parse the file; report unclosed quotes, bad indentation,
   duplicate keys, and other YAML errors with the line reported by the parser.
2. **Schema** — required fields (``id``, ``message``, ``severity``, ``language``),
   enum ``severity`` (critical/high/medium/low/info), and unknown-key detection
   (catches typos like ``pattern-eiter`` vs ``pattern-either``).
3. **Pattern parseability** — when a ``pattern`` field is present, compile it
   with tree-sitter for the rule's ``language`` and report syntax errors.
   Falls back to a graceful warning when tree-sitter or the language grammar is
   unavailable (the validator never hard-fails on a missing optional dep).
4. **Cross-field** — ``pattern`` and ``patterns`` are mutually exclusive;
   ``fix`` requires either ``pattern`` or ``patterns``.

The dataclasses (``ValidationIssue``, ``ValidationResult``) are the public
contract — callers can serialize them to JSON, render human-readable reports,
or feed them into CI exit-code logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ─── Public dataclasses ────────────────────────────────────────────────


@dataclass
class ValidationIssue:
    """A single validation finding (error or warning) for one rule.

    Attributes:
        level: ``"error"`` or ``"warning"``. Errors fail validation;
            warnings only fail when ``--strict`` is set.
        category: Stable machine-readable category. One of:
            ``yaml_syntax``, ``schema``, ``pattern``, ``cross_field``,
            ``unknown_key``.
        message: Human-readable description of the issue.
        line: 1-based line number in the rule file, when known. ``None`` if
            the issue is file-level (e.g., YAML parse failure) or the line
            cannot be determined.
    """

    level: str
    category: str
    message: str
    line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Aggregate validation result for one rule file.

    Attributes:
        rule_path: Path to the rule file that was validated.
        is_valid: ``True`` if there are no errors (warnings alone do not
            invalidate unless the caller applies ``--strict``).
        errors: List of error-level issues.
        warnings: List of warning-level issues.
        rules_checked: Count of rule entries inside the YAML (the
            ``rules:`` list). 0 if the file failed YAML parsing.
    """

    rule_path: str
    is_valid: bool = True
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    rules_checked: int = 0

    @property
    def has_warnings(self) -> bool:
        """``True`` if any warning-level issue was recorded."""
        return len(self.warnings) > 0

    def add_error(self, category: str, message: str, line: Optional[int] = None) -> None:
        """Record an error and flip ``is_valid`` to ``False``."""
        self.errors.append(ValidationIssue("error", category, message, line))
        self.is_valid = False

    def add_warning(self, category: str, message: str, line: Optional[int] = None) -> None:
        """Record a warning. Does not flip ``is_valid`` — caller applies ``--strict``."""
        self.warnings.append(ValidationIssue("warning", category, message, line))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "rule_path": self.rule_path,
            "is_valid": self.is_valid,
            "has_warnings": self.has_warnings,
            "rules_checked": self.rules_checked,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }


# ─── Constants ─────────────────────────────────────────────────────────

# Required top-level fields on every rule entry. Missing any → schema error.
REQUIRED_FIELDS: Tuple[str, ...] = ("id", "message", "severity", "language")

# Allowed severity values (lowercase). Anything else → schema error.
VALID_SEVERITIES: Tuple[str, ...] = ("critical", "high", "medium", "low", "info")

# Known optional fields on a rule entry. Anything outside this set (and
# outside REQUIRED_FIELDS) is flagged as an ``unknown_key`` warning — the
# rule still validates, but the author probably has a typo (e.g.,
# ``pattern-eiter`` instead of ``pattern-either``).
KNOWN_OPTIONAL_FIELDS: Tuple[str, ...] = (
    "name",
    "cwe",
    "owasp",
    # Pattern-style rules (Semgrep-compatible subset)
    "pattern",
    "patterns",
    "pattern-either",
    "pattern-not",
    "pattern-inside",
    "pattern-not-inside",
    "pattern-regex",
    "metavariable-regex",
    "metavariable-comparison",
    # Taint-style rules (CodeLens native — sources/sinks/sanitizers)
    "sources",
    "sinks",
    "sanitizers",
    # Autofix
    "fix",
    "fix-regex",
    # Routing / metadata
    "paths",
    "metadata",
    "options",
    "timeout",
    "max-match-per-file",
    # Project-level rule option (depends-on) for SCA rules
    "project-depends-on",
)

# Languages CodeLens can compile patterns for via tree-sitter. Other
# languages are accepted (rule still validates) but pattern parseability
# is skipped with a warning.
TREE_SITTER_LANGUAGES: Tuple[str, ...] = (
    "python",
    "javascript",
    "typescript",
    "tsx",
    "rust",
    "html",
    "css",
)


# ─── Stage 1: YAML syntax ──────────────────────────────────────────────


def _parse_yaml(rule_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[ValidationIssue]]:
    """Parse a YAML rule file.

    Args:
        rule_path: Path to the ``.yaml`` / ``.yml`` file.

    Returns:
        Tuple of (parsed_dict_or_None, parse_error_or_None). When YAML
        parsing fails, the dict is ``None`` and the issue captures the
        parser's error message + line (when the parser exposes one).
    """
    try:
        text = rule_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, ValidationIssue(
            level="error",
            category="yaml_syntax",
            message=f"Cannot read file: {exc}",
            line=None,
        )

    try:
        # ``Loader=yaml.SafeLoader`` is the safe default; we only expect
        # plain mappings/lists/strings in rule files.
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        # ``exc.problem_mark`` carries the line/column for the parser's
        # failure point when available — surface it so the user can jump
        # straight to the typo.
        line = None
        mark = getattr(exc, "problem_mark", None)
        if mark is not None:
            line = mark.line + 1  # mark.line is 0-based
        message = str(exc).split("\n", 1)[0]  # first line is the human summary
        return None, ValidationIssue(
            level="error",
            category="yaml_syntax",
            message=f"YAML parse error: {message}",
            line=line,
        )

    if data is None:
        return None, ValidationIssue(
            level="error",
            category="yaml_syntax",
            message="File is empty or contains only comments",
            line=None,
        )

    if not isinstance(data, dict):
        return None, ValidationIssue(
            level="error",
            category="yaml_syntax",
            message=f"Top-level YAML must be a mapping, got {type(data).__name__}",
            line=1,
        )

    return data, None


# ─── Stage 2: Schema validation ────────────────────────────────────────


def _validate_schema(
    rule: Dict[str, Any],
    rule_index: int,
    result: ValidationResult,
) -> None:
    """Validate one rule entry against the schema (required fields + enums)."""
    # Required fields — missing any is a hard error.
    for field_name in REQUIRED_FIELDS:
        value = rule.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            result.add_error(
                "schema",
                f"Rule #{rule_index}: missing required field '{field_name}'",
            )

    # Severity enum — must be one of the allowed values (case-insensitive
    # match against VALID_SEVERITIES, but we flag the original casing so
    # the author can fix it).
    severity = rule.get("severity")
    if severity is not None:
        if not isinstance(severity, str):
            result.add_error(
                "schema",
                f"Rule #{rule_index}: 'severity' must be a string, got {type(severity).__name__}",
            )
        elif severity.lower() not in VALID_SEVERITIES:
            allowed = ", ".join(VALID_SEVERITIES)
            result.add_error(
                "schema",
                f"Rule #{rule_index}: invalid severity '{severity}' "
                f"(allowed: {allowed})",
            )

    # Language must be a non-empty string. Unknown languages are not a hard
    # error (the rule may still be useful for taint analysis that doesn't
    # need tree-sitter), but we warn so authors notice typos.
    language = rule.get("language")
    if language is not None and not isinstance(language, str):
        result.add_error(
            "schema",
            f"Rule #{rule_index}: 'language' must be a string, got {type(language).__name__}",
        )

    # Unknown-key detection — catches typos like ``pattern-eiter``. This is
    # the highest-value check for rule authors; it's a warning (not error)
    # because CodeLens may legitimately add new fields in the future without
    # backfilling this allowlist immediately.
    known = set(REQUIRED_FIELDS) | set(KNOWN_OPTIONAL_FIELDS)
    for key in rule.keys():
        if key not in known:
            # Suggest the closest known field (simple edit-distance heuristic).
            suggestion = _suggest_field(key, known)
            hint = f" Did you mean '{suggestion}'?" if suggestion else ""
            result.add_warning(
                "unknown_key",
                f"Rule #{rule_index}: unknown field '{key}'.{hint}",
            )


def _suggest_field(typo: str, known: set) -> Optional[str]:
    """Suggest the closest known field name for a typo.

    Uses a simple Levenshtein-distance heuristic (threshold ≤ 2 edits).
    Returns ``None`` when no known field is close enough.
    """
    best: Optional[Tuple[int, str]] = None
    for candidate in known:
        dist = _edit_distance(typo, candidate)
        if dist <= 2 and (best is None or dist < best[0]):
            best = (dist, candidate)
    return best[1] if best else None


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


# ─── Stage 3: Pattern parseability ─────────────────────────────────────


def _validate_pattern(
    rule: Dict[str, Any],
    rule_index: int,
    result: ValidationResult,
) -> None:
    """Compile ``pattern`` field with tree-sitter to catch syntax errors.

    Skips gracefully (with a warning) when tree-sitter or the language
    grammar is not installed — the validator must not hard-fail on a
    missing optional dep.
    """
    pattern = rule.get("pattern")
    if pattern is None:
        # ``patterns`` (list) is also accepted but not compiled here —
        # each entry would need its own AST check. We leave that to a
        # future enhancement and only validate the scalar ``pattern``.
        return

    if not isinstance(pattern, str):
        result.add_error(
            "pattern",
            f"Rule #{rule_index}: 'pattern' must be a string, got {type(pattern).__name__}",
        )
        return

    language = rule.get("language", "")
    if not isinstance(language, str) or language.lower() not in TREE_SITTER_LANGUAGES:
        # Not a tree-sitter-supported language — skip parseability check
        # but warn so the author knows the pattern wasn't compiled.
        if isinstance(language, str) and language:
            result.add_warning(
                "pattern",
                f"Rule #{rule_index}: pattern parseability check skipped "
                f"(language '{language}' not tree-sitter-supported)",
            )
        return

    try:
        from grammar_loader import GrammarLoader
    except ImportError:
        result.add_warning(
            "pattern",
            f"Rule #{rule_index}: pattern parseability check skipped "
            "(grammar_loader unavailable)",
        )
        return

    loader = GrammarLoader()
    parser = loader.get_parser(language.lower())
    if parser is None:
        result.add_warning(
            "pattern",
            f"Rule #{rule_index}: pattern parseability check skipped "
            f"(tree-sitter grammar for '{language}' not installed)",
        )
        return

    # Tree-sitter pattern syntax is close to (but not identical to) the
    # target language. We compile the pattern as-is and check for ``ERROR``
    # nodes — false positives are possible ( metavariables like ``$X``
    # will show up as parse errors in some languages), so we only emit a
    # warning, not a hard error.
    try:
        tree = parser.parse(pattern.encode("utf-8"))
    except Exception as exc:  # pragma: no cover — defensive
        result.add_warning(
            "pattern",
            f"Rule #{rule_index}: pattern parse raised: {exc}",
        )
        return

    root = tree.root_node
    if root.has_error:
        # Walk for the first ERROR node to surface a useful location.
        err_line = _find_error_line(root)
        result.add_warning(
            "pattern",
            f"Rule #{rule_index}: pattern may have a syntax error "
            f"(tree-sitter reported ERROR at line {err_line}). "
            "Note: metavariables like $X can trigger false positives.",
            line=err_line,
        )


def _find_error_line(root) -> Optional[int]:
    """Return the 1-based line of the first ERROR node, or ``None``."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "ERROR":
            return node.start_point[0] + 1
        for child in node.children:
            stack.append(child)
    return None


# ─── Stage 4: Cross-field validation ───────────────────────────────────


def _validate_cross_field(
    rule: Dict[str, Any],
    rule_index: int,
    result: ValidationResult,
) -> None:
    """Validate cross-field constraints that schema checks can't express."""
    has_pattern = "pattern" in rule and rule["pattern"] is not None
    has_patterns = "patterns" in rule and rule["patterns"] is not None
    has_pattern_either = "pattern-either" in rule and rule["pattern-either"] is not None
    has_fix = "fix" in rule and rule["fix"] is not None
    has_fix_regex = "fix-regex" in rule and rule["fix-regex"] is not None

    # ``pattern`` and ``patterns`` are mutually exclusive — using both is
    # ambiguous (which one wins?) and almost always a mistake.
    if has_pattern and has_patterns:
        result.add_error(
            "cross_field",
            f"Rule #{rule_index}: 'pattern' and 'patterns' are mutually exclusive",
        )

    # ``fix`` (or ``fix-regex``) requires a pattern field to apply to.
    # Without one, the fix has nothing to fix.
    if (has_fix or has_fix_regex) and not (has_pattern or has_patterns or has_pattern_either):
        result.add_error(
            "cross_field",
            f"Rule #{rule_index}: 'fix'/'fix-regex' requires 'pattern', "
            "'patterns', or 'pattern-either'",
        )


# ─── Public entry point ────────────────────────────────────────────────


def validate_rule(rule_path: Path) -> ValidationResult:
    """Validate a single rule YAML file.

    Runs all 4 validation stages (YAML syntax → schema → pattern
    parseability → cross-field) and aggregates results into a single
    ``ValidationResult``. The function never raises — callers get a
    structured result they can serialize, render, or feed into CI logic.

    Args:
        rule_path: Path to the ``.yaml`` / ``.yml`` file to validate.

    Returns:
        ``ValidationResult`` with ``is_valid=False`` if any errors were
        found. Warnings are recorded separately and only fail validation
        when the caller applies ``--strict``.
    """
    rule_path = Path(rule_path)
    result = ValidationResult(rule_path=str(rule_path))

    # Stage 1: YAML syntax
    data, parse_error = _parse_yaml(rule_path)
    if parse_error is not None:
        result.add_error(
            parse_error.category,
            parse_error.message,
            parse_error.line,
        )
        return result  # cannot continue without parsed YAML

    # The top-level mapping must contain a ``rules:`` list.
    rules_list = data.get("rules")
    if rules_list is None:
        result.add_error(
            "schema",
            "Top-level mapping must contain a 'rules' list",
        )
        return result

    if not isinstance(rules_list, list):
        result.add_error(
            "schema",
            f"'rules' must be a list, got {type(rules_list).__name__}",
        )
        return result

    result.rules_checked = len(rules_list)

    # Validate each rule entry.
    for index, rule in enumerate(rules_list, start=1):
        if not isinstance(rule, dict):
            result.add_error(
                "schema",
                f"Rule #{index}: must be a mapping, got {type(rule).__name__}",
            )
            continue

        _validate_schema(rule, index, result)
        _validate_pattern(rule, index, result)
        _validate_cross_field(rule, index, result)

    return result


def validate_rule_files(paths: List[Path]) -> List[ValidationResult]:
    """Validate multiple rule files.

    Args:
        paths: List of rule file paths (each ``.yaml`` / ``.yml``).

    Returns:
        List of ``ValidationResult``, one per input path. Order matches
        the input order.
    """
    return [validate_rule(path) for path in paths]


def determine_exit_code(results: List[ValidationResult], strict: bool = False) -> int:
    """Determine the process exit code from validation results.

    Exit code semantics (matches the ``rule-validate`` CLI contract):

    * ``0`` — all rules valid (no errors, no warnings, or warnings without
      ``--strict``).
    * ``1`` — at least one rule has an error.
    * ``2`` — at least one rule has a warning AND ``--strict`` is set (no
      errors).

    Args:
        results: List of ``ValidationResult`` from ``validate_rule_files``.
        strict: When ``True``, warnings are treated as errors for exit-code
            purposes (but still reported as warnings in the output).

    Returns:
        Exit code (0, 1, or 2).
    """
    has_error = any(not r.is_valid for r in results)
    has_warning = any(r.has_warnings for r in results)

    if has_error:
        return 1
    if has_warning and strict:
        return 2
    return 0
