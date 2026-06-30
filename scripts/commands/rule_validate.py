"""rule-validate command — validate rule YAML files for typos and schema errors.

Catches the silent-skip class of bugs: typos (``pattern-eiter`` vs
``pattern-either``), unknown keys, missing required fields, invalid
``severity`` enum, unparseable ``pattern`` strings, and cross-field
violations (``pattern`` + ``patterns`` mutually exclusive, ``fix`` requires
``pattern``). All logic lives in ``scripts/rule_validator.py``; this file
is the thin CLI wrapper.

Exit codes:
    0 — all rules valid (no errors, no warnings without ``--strict``)
    1 — at least one rule has an error
    2 — at least one rule has a warning AND ``--strict`` is set

Usage::

    codelens rule-validate scripts/rules/python_security.yaml
    codelens rule-validate --strict scripts/rules/*.yaml
    codelens rule-validate --json scripts/rules/python_security.yaml
    codelens rule-validate scripts/rules/   # validate every rule file in a directory
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from commands import register_command
from rule_validator import (
    ValidationResult,
    determine_exit_code,
    validate_rule,
    validate_rule_files,
)

# Exit codes — kept as named constants so the command and its tests agree.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_WARNING_STRICT = 2


def add_args(parser):
    """Register rule-validate CLI arguments."""
    parser.add_argument(
        "rule_path",
        nargs="+",
        help="Path(s) to rule YAML file(s) to validate, or directory(ies) of rule files",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Treat warnings as errors for exit-code purposes (exit 2 instead of 0)",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output machine-readable JSON instead of human-readable text",
    )


def _format_human(results: List[ValidationResult], strict: bool) -> str:
    """Render validation results as human-readable text.

    One block per rule file: header line, then errors (✗) and warnings (⚠),
    each with file:line: message. Ends with a summary line.
    """
    lines: List[str] = []
    total_errors = sum(len(r.errors) for r in results)
    total_warnings = sum(len(r.warnings) for r in results)
    total_rules = sum(r.rules_checked for r in results)
    valid_files = sum(1 for r in results if r.is_valid)

    for result in results:
        # Header: file path + ✓/✗ status badge.
        status = "✓ valid" if result.is_valid else "✗ invalid"
        lines.append(f"\n{result.rule_path} — {status} ({result.rules_checked} rules)")
        lines.append("─" * 60)

        if not result.errors and not result.warnings:
            lines.append("  No issues found.")
            continue

        # Errors first (always surface the most important issues up top).
        for issue in result.errors:
            loc = f"line {issue.line}: " if issue.line else ""
            lines.append(f"  ✗ [{issue.category}] {loc}{issue.message}")

        # Then warnings.
        for issue in result.warnings:
            loc = f"line {issue.line}: " if issue.line else ""
            lines.append(f"  ⚠ [{issue.category}] {loc}{issue.message}")

    # Summary line — gives CI parsers and humans a one-line verdict.
    lines.append("\n" + "=" * 60)
    if total_errors > 0:
        lines.append(
            f"FAIL: {total_errors} error(s), {total_warnings} warning(s) "
            f"across {len(results)} file(s), {total_rules} rule(s)"
        )
    elif total_warnings > 0 and strict:
        lines.append(
            f"FAIL (--strict): {total_warnings} warning(s) treated as errors "
            f"across {len(results)} file(s), {total_rules} rule(s)"
        )
    elif total_warnings > 0:
        lines.append(
            f"PASS with warnings: {valid_files}/{len(results)} file(s) valid, "
            f"{total_warnings} warning(s) (use --strict to fail on warnings)"
        )
    else:
        lines.append(
            f"PASS: {len(results)}/{len(results)} file(s) valid, {total_rules} rule(s) checked"
        )

    return "\n".join(lines)


def _format_json(results: List[ValidationResult], strict: bool) -> str:
    """Render validation results as JSON for CI / programmatic consumers."""
    payload: Dict[str, Any] = {
        "status": "ok" if all(r.is_valid for r in results) else "error",
        "strict": strict,
        "exit_code": determine_exit_code(results, strict=strict),
        "total_files": len(results),
        "total_rules": sum(r.rules_checked for r in results),
        "total_errors": sum(len(r.errors) for r in results),
        "total_warnings": sum(len(r.warnings) for r in results),
        "results": [r.to_dict() for r in results],
    }
    return json.dumps(payload, indent=2)


def execute(args, workspace):
    """Execute the rule-validate command.

    Returns a dict (so the result flows through the standard CodeLens
    output formatter) AND sets the process exit code via ``sys.exit`` so
    CI pipelines get the correct 0/1/2 signal.

    Args:
        args: Parsed argparse namespace with ``rule_path`` (list),
            ``strict`` (bool), and ``json_output`` (bool).
        workspace: Workspace root (unused — rule-validate is path-based).

    Returns:
        Dict with ``status``, ``exit_code``, ``results``, and the rendered
        ``output`` string (human or JSON).
    """
    # Expand and deduplicate paths. ``args.rule_path`` is a list (nargs="+").
    # Each entry may be either a single rule file OR a directory of rule files
    # (issue #97): when a directory is given, enumerate the ``*.yaml``/``*.yml``
    # rule files inside it rather than trying to ``open()`` the directory
    # itself — ``read_text()`` on a directory raises ``IsADirectoryError`` on
    # Linux/macOS and ``PermissionError`` on Windows.
    paths: List[Path] = []
    seen: set = set()
    for raw in args.rule_path:
        # Expand ``~`` and resolve to absolute. We don't follow symlinks
        # here — a missing file is reported as a validation error below.
        p = Path(os.path.expanduser(raw)).resolve()

        if p.is_dir():
            # Directory → enumerate rule files inside it (recursive, matching
            # rule-test's behavior). Skip ``.test.yaml``/``.test.yml`` (test
            # fixtures with a different schema) and hidden/dotfiles.
            for entry in sorted(p.rglob("*.y*ml")):
                if entry.name.endswith((".test.yaml", ".test.yml")):
                    continue
                if entry.name.startswith("."):
                    continue
                if entry in seen:
                    continue
                seen.add(entry)
                paths.append(entry)
        else:
            if p in seen:
                continue
            seen.add(p)
            paths.append(p)

    # Validate each path. Missing files produce a single-error result
    # rather than crashing — the validator's ``_parse_yaml`` already
    # handles ``OSError`` and records it as a yaml_syntax error.
    results = validate_rule_files(paths)

    exit_code = determine_exit_code(results, strict=args.strict)

    if args.json_output:
        output = _format_json(results, args.strict)
    else:
        output = _format_human(results, args.strict)

    # Print to stdout so the report is pipeable, then exit with the
    # contract code. We use ``sys.exit`` from inside the command (rather
    # than returning a sentinel) because rule-validate is fundamentally a
    # CI gate — the exit code IS the result.
    print(output)
    sys.exit(exit_code)

    # Unreachable, but keeps the return-type contract honest for callers
    # that import ``execute`` directly (e.g., tests).
    return {
        "status": "ok" if exit_code == 0 else "error",
        "exit_code": exit_code,
        "results": [r.to_dict() for r in results],
        "output": output,
    }


register_command(
    "rule-validate",
    "Validate rule YAML files for typos, schema errors, and unparseable patterns",
    add_args,
    execute,
)
