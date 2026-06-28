"""rule-test command — snapshot testing for rule YAML files.

Runs a rule against positive/negative code samples (``.test.yaml``) and
verifies the rule fires (or doesn't fire) where expected via inline
``# ruleid: <id>`` / ``# ok`` markers. All logic lives in
``scripts/rule_test_runner.py``; this file is the thin CLI wrapper.

Usage::

    codelens rule-test tests/rule_fixtures/py_sql_injection.yaml
    codelens rule-test tests/rule_fixtures/         # run all rules in a dir
    codelens rule-test --json tests/rule_fixtures/
    codelens rule-test --test-ignore-todo tests/rule_fixtures/

Exit codes:
    0 — all tests pass (or no tests ran)
    1 — at least one test failed or errored
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from commands import register_command
from rule_test_runner import (
    TestResult,
    determine_exit_code,
    run_tests,
    run_tests_recursive,
)


def add_args(parser):
    """Register rule-test CLI arguments."""
    parser.add_argument(
        "rule_path",
        help="Path to a rule YAML file or a directory of rule files",
    )
    parser.add_argument(
        "--test-ignore-todo",
        action="store_true",
        default=False,
        help="Skip '# todoruleid:' markers (staged rules not yet enforced)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output machine-readable JSON instead of human-readable text",
    )


def _format_human(results: List[TestResult]) -> str:
    """Render test results as human-readable text.

    One block per rule: ``<rule-id>: PASS (3/3 samples)`` or fail with
    a per-failure diff. Ends with a summary line.
    """
    lines: List[str] = []
    total_pass = sum(1 for r in results if r.is_pass)
    total_fail = sum(1 for r in results if not r.is_pass)
    total_samples = sum(r.total for r in results)
    total_passed_samples = sum(r.passed for r in results)
    total_skipped = sum(r.skipped for r in results)

    for result in results:
        rule_id = result.rule_id or Path(result.rule_path).stem
        if result.error:
            lines.append(f"\n{rule_id}: ERROR — {result.error}")
            continue

        if result.total == 0:
            lines.append(f"\n{rule_id}: SKIP (no samples)")
            continue

        # Per-rule verdict line — the most important line for CI parsers.
        verdict = "PASS" if result.is_pass else "FAIL"
        sample_summary = f"{result.passed}/{result.total} samples"
        if result.skipped:
            sample_summary += f" ({result.skipped} skipped)"
        lines.append(f"\n{rule_id}: {verdict} ({sample_summary})")

        # Per-failure detail so authors can fix the rule.
        for failure in result.failures:
            lines.append(f"  ✗ {failure.sample_name} line {failure.line}: {failure.message}")

    # Summary line.
    lines.append("\n" + "=" * 60)
    if total_fail > 0:
        lines.append(
            f"FAIL: {total_fail}/{len(results)} rule(s) failed, "
            f"{total_passed_samples}/{total_samples} samples passed "
            f"({total_skipped} skipped)"
        )
    else:
        lines.append(
            f"PASS: {total_pass}/{len(results)} rule(s), "
            f"{total_passed_samples}/{total_samples} samples passed "
            f"({total_skipped} skipped)"
        )

    return "\n".join(lines)


def _format_json(results: List[TestResult]) -> str:
    """Render test results as JSON for CI / programmatic consumers."""
    payload: Dict[str, Any] = {
        "status": "ok" if all(r.is_pass for r in results) else "fail",
        "exit_code": determine_exit_code(results),
        "total_rules": len(results),
        "total_pass": sum(1 for r in results if r.is_pass),
        "total_fail": sum(1 for r in results if not r.is_pass),
        "total_samples": sum(r.total for r in results),
        "total_passed_samples": sum(r.passed for r in results),
        "total_skipped": sum(r.skipped for r in results),
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(payload, indent=2)


def execute(args, workspace):
    """Execute the rule-test command.

    Returns a dict (so the result flows through the standard CodeLens
    output formatter) AND sets the process exit code via ``sys.exit`` so
    CI pipelines get the correct 0/1 signal.

    Args:
        args: Parsed argparse namespace with ``rule_path``, ``test_ignore_todo``,
            and ``json_output``.
        workspace: Workspace root (unused — rule-test is path-based).

    Returns:
        Dict with ``status``, ``exit_code``, ``results``, and the rendered
        ``output`` string (human or JSON).
    """
    raw_path = os.path.expanduser(args.rule_path)
    path = Path(raw_path).resolve()

    if not path.exists():
        # Surface a clear error rather than crashing — the path may be a
        # typo, and the user benefits from an actionable message.
        print(f"Error: path does not exist: {path}", file=sys.stderr)
        sys.exit(1)

    # A single file → run tests for that one rule. A directory → walk and
    # run tests for every rule with a ``.test.yaml`` companion.
    if path.is_file():
        results = [run_tests(path, ignore_todo=args.test_ignore_todo)]
    else:
        results = run_tests_recursive(path, ignore_todo=args.test_ignore_todo)

    exit_code = determine_exit_code(results)

    if args.json_output:
        output = _format_json(results)
    else:
        output = _format_human(results)

    print(output)
    sys.exit(exit_code)

    # Unreachable, but keeps the return-type contract honest for callers
    # that import ``execute`` directly (e.g., tests).
    return {
        "status": "ok" if exit_code == 0 else "fail",
        "exit_code": exit_code,
        "results": [r.to_dict() for r in results],
        "output": output,
    }


register_command(
    "rule-test",
    "Run snapshot tests for rule YAML files (inline # ruleid: / # ok markers)",
    add_args,
    execute,
)
