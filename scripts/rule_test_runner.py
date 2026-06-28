"""Rule Test Runner for CodeLens — snapshot testing for rule YAML files.

Runs a rule against positive/negative code samples and verifies the rule
fires (or doesn't fire) where expected. The test format uses inline
``# ruleid: <rule-id>`` markers (expect a finding on this line) and
``# ok`` markers (expect no finding on this line) embedded in sample
source code, so authors can keep test fixtures next to the rule itself.

Test file convention (inline format)::

    # tests/rule_fixtures/py_sql_injection.test.yaml
    rule: py/sql-injection
    samples:
      - name: positive_basic
        language: python
        code: |
          user = request.args.get('name')
          cursor.execute("SELECT * FROM users WHERE name = '" + user + "'")  # ruleid: py/sql-injection
      - name: negative_sanitized
        language: python
        code: |
          user = request.args.get('name')
          safe = parameterized_query(user)
          cursor.execute("SELECT ... WHERE name = %s", (safe,))  # ok

The runner is decoupled from the CLI (``scripts/commands/rule_test.py``)
so it can be reused by CI pipelines and programmatic callers.

Note: this runner exercises the existing taint/semantic engine
(``scripts/semantic_engine.py``) for taint-style rules (sources/sinks/
sanitizers). Pattern-style rules (``pattern:`` field) are not yet
supported by the engine — samples for those rules are reported as
``skipped`` rather than failed, so authors can still scaffold tests
ahead of the pattern engine landing.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# ─── Public dataclasses ────────────────────────────────────────────────


@dataclass
class TestFailure:
    """A single failed test expectation.

    Attributes:
        sample_name: Name of the sample (from the ``name:`` field).
        line: 1-based line number where the expectation was set.
        expected: ``"finding"`` (ruleid marker) or ``"no-finding"`` (ok marker).
        actual: ``"finding"`` or ``"no-finding"`` -- what actually happened.
        rule_id: The rule ID the expectation was about.
        message: Human-readable explanation of the mismatch.

    Note: ``__test__ = False`` prevents pytest from collecting this
    dataclass as a test class (its name starts with ``Test``).
    """

    __test__ = False  # type: ignore[assignment]

    sample_name: str
    line: int
    expected: str
    actual: str
    rule_id: str
    message: str

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return asdict(self)


@dataclass
class TestResult:
    """Aggregate test result for one rule file.

    Attributes:
        rule_path: Path to the rule YAML file.
        rule_id: Rule ID extracted from the rule file.
        test_path: Path to the ``.test.yaml`` file (``None`` if not found).
        total: Total number of samples run.
        passed: Number of samples that passed all expectations.
        failed: Number of samples with at least one failed expectation.
        skipped: Number of samples skipped (e.g., pattern-style rule).
        failures: List of ``TestFailure`` for failed expectations.
        error: When the test file itself cannot be parsed/loaded.

    Note: ``__test__ = False`` prevents pytest from collecting this
    dataclass as a test class (its name starts with ``Test``).
    """

    __test__ = False  # type: ignore[assignment]

    rule_path: str
    rule_id: str = ""
    test_path: Optional[str] = None
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failures: List[TestFailure] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def is_pass(self) -> bool:
        """``True`` if no failures and no error."""
        return self.failed == 0 and self.error is None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {
            "rule_path": self.rule_path,
            "rule_id": self.rule_id,
            "test_path": self.test_path,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "is_pass": self.is_pass,
            "failures": [f.to_dict() for f in self.failures],
            "error": self.error,
        }


# ─── Marker parsing ────────────────────────────────────────────────────

# ``# ruleid: <rule-id>`` — expect a finding on this line. The marker
# can appear at end of code line OR on its own line above the code line
# (the runner handles both by attributing the expectation to the next
# non-comment, non-blank code line when the marker is standalone).
_RULEID_RE = re.compile(r"#\s*ruleid:\s*([\w/.\-]+)")

# ``# ok`` — expect NO finding on this line. Same attribution rule.
_OK_RE = re.compile(r"#\s*ok\b")

# ``# todoruleid: <rule-id>`` — same as ruleid but skipped when
# ``--test-ignore-todo`` is set. Useful for staging upcoming rules.
_TODORULEID_RE = re.compile(r"#\s*todoruleid:\s*([\w/.\-]+)")


@dataclass
class _Expectation:
    """Internal: one parsed expectation from a sample's markers."""

    line: int  # 1-based line the expectation applies to
    kind: str  # "finding" or "no-finding"
    rule_id: str  # the rule id the expectation is about
    is_todo: bool = False  # True for todoruleid (skipped with --test-ignore-todo)


def _parse_markers(code: str, ignore_todo: bool = False) -> List[_Expectation]:
    """Parse ``# ruleid:`` / ``# ok`` / ``# todoruleid:`` markers from code.

    Markers may appear:
    * Inline at end of a code line → expectation applies to that line.
    * Standalone on their own line → expectation applies to the next
      non-comment, non-blank line below.

    Args:
        code: The sample source code (multi-line string).
        ignore_todo: When ``True``, ``# todoruleid:`` markers are dropped.

    Returns:
        List of ``_Expectation``, one per marker found.
    """
    expectations: List[_Expectation] = []
    lines = code.split("\n")
    pending_finding: Optional[Tuple[str, bool]] = None  # (rule_id, is_todo)

    for idx, line in enumerate(lines, start=1):
        # Check for ``# ok`` first — it's the no-finding marker.
        if _OK_RE.search(line):
            # Inline ``# ok`` — applies to this line.
            expectations.append(_Expectation(line=idx, kind="no-finding", rule_id=""))
            pending_finding = None
            continue

        # Check for ``# ruleid: <id>`` (inline or standalone).
        m = _RULEID_RE.search(line)
        if m:
            rule_id = m.group(1)
            # If the line has code before the marker, it's inline.
            code_before = line[: m.start()].rstrip()
            if code_before:
                expectations.append(_Expectation(line=idx, kind="finding", rule_id=rule_id))
            else:
                # Standalone marker — attribute to next code line.
                pending_finding = (rule_id, False)
            continue

        # Check for ``# todoruleid: <id>``.
        m = _TODORULEID_RE.search(line)
        if m:
            if ignore_todo:
                continue
            rule_id = m.group(1)
            code_before = line[: m.start()].rstrip()
            if code_before:
                expectations.append(
                    _Expectation(line=idx, kind="finding", rule_id=rule_id, is_todo=True)
                )
            else:
                pending_finding = (rule_id, True)
            continue

        # Plain code line — if there's a pending standalone marker,
        # attribute it here.
        if pending_finding is not None:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                rule_id, is_todo = pending_finding
                expectations.append(
                    _Expectation(line=idx, kind="finding", rule_id=rule_id, is_todo=is_todo)
                )
                pending_finding = None

    return expectations


# ─── Rule loading ──────────────────────────────────────────────────────


def _load_rule(rule_path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load a single rule from a YAML file.

    Returns ``(rule_dict, error_message)``. If the file contains multiple
    rules under ``rules:``, the first one is returned (test files are
    expected to be one-rule-per-file).
    """
    try:
        data = yaml.safe_load(rule_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, f"YAML parse error: {exc}"
    except OSError as exc:
        return None, f"Cannot read file: {exc}"

    if not isinstance(data, dict):
        return None, f"Top-level YAML must be a mapping, got {type(data).__name__}"

    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        return None, "No 'rules' list found (or list is empty)"

    first = rules[0]
    if not isinstance(first, dict):
        return None, f"First rule entry must be a mapping, got {type(first).__name__}"

    return first, None


def _find_test_file(rule_path: Path) -> Optional[Path]:
    """Find the ``.test.yaml`` companion for a rule file.

    Convention: ``foo.yaml`` → ``foo.test.yaml`` (same directory).
    Also accepts ``foo.yml`` → ``foo.test.yaml``.
    """
    stem = rule_path.stem  # ``foo`` from ``foo.yaml``
    candidate = rule_path.with_name(f"{stem}.test.yaml")
    if candidate.exists():
        return candidate
    # Also accept ``.test.yml``.
    candidate = rule_path.with_name(f"{stem}.test.yml")
    if candidate.exists():
        return candidate
    return None


# ─── Sample execution ──────────────────────────────────────────────────


def _run_sample(
    rule: Dict[str, Any],
    sample: Dict[str, Any],
    ignore_todo: bool = False,
) -> Tuple[List[TestFailure], int, bool]:
    """Run one sample against the rule.

    Returns ``(failures, expectations_count, skipped)``.

    * ``failures`` — list of ``TestFailure`` for mismatched expectations.
    * ``expectations_count`` — total expectations checked.
    * ``skipped`` — ``True`` when the sample was skipped (pattern-style
      rule, or unsupported language).
    """
    code = sample.get("code", "")
    language = sample.get("language", rule.get("language", ""))
    sample_name = sample.get("name", "unnamed")

    # Pattern-style rules (``pattern:`` field) are not yet supported by
    # the taint engine. Skip them with a clear message rather than
    # failing — authors can scaffold tests ahead of the pattern engine.
    if "pattern" in rule or "patterns" in rule:
        return [], 0, True

    # The taint engine only knows how to analyze python / javascript /
    # typescript. Other languages → skip.
    if language not in ("python", "javascript", "typescript"):
        return [], 0, True

    expectations = _parse_markers(code, ignore_todo=ignore_todo)
    if not expectations:
        # No markers → nothing to verify. Treat as a pass with 0 checks
        # (the sample ran but had no expectations).
        return [], 0, False

    # Write the sample to a temp file so the engine can analyze it.
    # Using a real file (rather than in-memory) keeps the engine's
    # file-path-based reporting intact.
    suffix = ".py" if language == "python" else ".js" if language == "javascript" else ".ts"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        findings = _analyze_with_rule(rule, tmp_path, language)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    # Build a set of (rule_id, line) for findings on the lines we care
    # about. The engine reports line numbers as 1-based.
    finding_lines: Dict[int, List[str]] = {}
    for f in findings:
        f_line = f.get("line")
        f_rule = f.get("rule_id", "")
        if f_line is not None:
            finding_lines.setdefault(f_line, []).append(f_rule)

    failures: List[TestFailure] = []
    for exp in expectations:
        rules_at_line = finding_lines.get(exp.line, [])
        has_finding = bool(rules_at_line)

        if exp.kind == "finding":
            if not has_finding:
                failures.append(
                    TestFailure(
                        sample_name=sample_name,
                        line=exp.line,
                        expected="finding",
                        actual="no-finding",
                        rule_id=exp.rule_id,
                        message=(
                            f"Expected finding for rule '{exp.rule_id}' on line "
                            f"{exp.line}, but no finding was reported"
                        ),
                    )
                )
            elif exp.rule_id and exp.rule_id not in rules_at_line:
                failures.append(
                    TestFailure(
                        sample_name=sample_name,
                        line=exp.line,
                        expected="finding",
                        actual=f"finding (wrong rule: {rules_at_line})",
                        rule_id=exp.rule_id,
                        message=(
                            f"Expected finding for rule '{exp.rule_id}' on line "
                            f"{exp.line}, but got findings for {rules_at_line}"
                        ),
                    )
                )
        elif exp.kind == "no-finding":
            if has_finding:
                failures.append(
                    TestFailure(
                        sample_name=sample_name,
                        line=exp.line,
                        expected="no-finding",
                        actual=f"finding ({rules_at_line})",
                        rule_id=",".join(rules_at_line),
                        message=(
                            f"Expected NO finding on line {exp.line}, but got "
                            f"findings for {rules_at_line}"
                        ),
                    )
                )

    return failures, len(expectations), False


def _analyze_with_rule(
    rule: Dict[str, Any],
    file_path: str,
    language: str,
) -> List[Dict[str, Any]]:
    """Run the semantic engine with a single rule on a single file.

    Wraps ``semantic_engine.TaintAnalyzer`` so we can test one rule in
    isolation (the engine normally loads all rules from ``scripts/rules/``).
    """
    try:
        from semantic_engine import TaintAnalyzer
    except ImportError:
        return []

    analyzer = TaintAnalyzer(rules=[rule], language=language)
    return analyzer.analyze_file(file_path)


# ─── Public entry point ────────────────────────────────────────────────


def run_tests(rule_path: Path, ignore_todo: bool = False) -> TestResult:
    """Run tests for a single rule file.

    Looks for ``<rule>.test.yaml`` next to the rule file, parses its
    ``samples:``, runs each sample through the engine, and compares
    findings to the inline ``# ruleid:`` / ``# ok`` markers.

    Args:
        rule_path: Path to the rule YAML file.
        ignore_todo: When ``True``, ``# todoruleid:`` markers are skipped.

    Returns:
        ``TestResult`` with pass/fail counts and per-expectation failures.
    """
    rule_path = Path(rule_path)
    result = TestResult(rule_path=str(rule_path))

    # Load the rule (we need its ``id`` and ``language`` for the test).
    rule, err = _load_rule(rule_path)
    if err is not None:
        result.error = err
        return result

    result.rule_id = rule.get("id", "")

    # Find the companion ``.test.yaml`` file.
    test_path = _find_test_file(rule_path)
    if test_path is None:
        result.error = (
            f"No test file found. Expected '{rule_path.stem}.test.yaml' "
            f"next to '{rule_path.name}'"
        )
        return result

    result.test_path = str(test_path)

    # Parse the test file.
    try:
        test_data = yaml.safe_load(test_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        result.error = f"Test file YAML parse error: {exc}"
        return result

    if not isinstance(test_data, dict):
        result.error = f"Test file top-level must be a mapping, got {type(test_data).__name__}"
        return result

    samples = test_data.get("samples")
    if not isinstance(samples, list) or not samples:
        result.error = "Test file must contain a 'samples' list (non-empty)"
        return result

    result.total = len(samples)

    for sample in samples:
        if not isinstance(sample, dict):
            result.failed += 1
            result.failures.append(
                TestFailure(
                    sample_name="unnamed",
                    line=0,
                    expected="sample",
                    actual="invalid",
                    rule_id=result.rule_id,
                    message=f"Sample must be a mapping, got {type(sample).__name__}",
                )
            )
            continue

        failures, exp_count, skipped = _run_sample(rule, sample, ignore_todo=ignore_todo)
        if skipped:
            result.skipped += 1
            continue

        if failures:
            result.failed += 1
            result.failures.extend(failures)
        else:
            result.passed += 1

    return result


def run_tests_recursive(
    path: Path,
    ignore_todo: bool = False,
) -> List[TestResult]:
    """Run tests for every rule file under a directory (or a single file).

    Walks the path looking for ``.yaml`` / ``.yml`` rule files. For each
    one that has a companion ``.test.yaml``, runs the tests. Rule files
    without a test companion are skipped silently (reported in the
    returned list with ``error`` set, so callers can surface them).

    Args:
        path: Directory or single rule file path.
        ignore_todo: When ``True``, ``# todoruleid:`` markers are skipped.

    Returns:
        List of ``TestResult``, one per rule file that has a test companion.
    """
    path = Path(path)
    rule_files: List[Path] = []

    if path.is_file():
        if path.suffix in (".yaml", ".yml") and not path.name.endswith(".test.yaml"):
            rule_files.append(path)
    elif path.is_dir():
        # Walk and collect rule files (skip ``.test.yaml`` files — those
        # are test fixtures, not rules themselves).
        for entry in sorted(path.rglob("*.y*ml")):
            if entry.name.endswith(".test.yaml") or entry.name.endswith(".test.yml"):
                continue
            if entry.name.startswith("."):
                continue
            rule_files.append(entry)

    results: List[TestResult] = []
    for rule_file in rule_files:
        # Only include rules that have a test companion — keeps the
        # output focused on what was actually tested.
        if _find_test_file(rule_file) is not None:
            results.append(run_tests(rule_file, ignore_todo=ignore_todo))

    return results


def determine_exit_code(results: List[TestResult]) -> int:
    """Determine the process exit code from test results.

    * ``0`` — all tests pass (or no tests ran).
    * ``1`` — at least one test failed or errored.
    """
    for r in results:
        if not r.is_pass:
            return 1
    return 0
