# @WHO:   scripts/formatters/junit_xml.py
# @WHAT:  JUnit XML formatter — CI test-report integration for Jenkins/GitLab/CircleCI (issue #52 Phase 2)
# @PART:  formatters
# @ENTRY: format_junit_xml()
"""JUnit XML formatter for CodeLens (issue #52, Phase 2).

Generates JUnit XML — the universal test-result format understood by
Jenkins, GitLab CI, CircleCI, Buildkite, and most CI systems.

Why JUnit XML for a static analyzer?
------------------------------------
CI systems already have rich UI for JUnit: failure lists, trend
charts, "did this PR introduce new failures?" gates. By emitting
CodeLens findings as JUnit ``<failure>`` elements, teams get all
that UI for free without writing custom integrations.

Mapping
-------
Each CodeLens command run = one JUnit ``<testsuite>``.
Each finding = one ``<testcase>`` with a ``<failure>`` child.

* ``<testsuite name="codelens-<command>">`` — one per command.
* ``<testcase name="<rule_id>">`` — one per finding. The testcase
  name is the rule_id (e.g. ``codelens/secrets/api-key``), so CI
  systems can group/dedupe by rule.
* ``<failure message="..." type="...">`` — carries the finding
  message + severity as ``type``. The body is a multi-line stack
  with file:line + snippet.
* Critical/high findings map to ``<failure>`` (test failed).
* Medium/low/info findings map to ``<skipped>`` (test "skipped" —
  CI treats this as non-blocking but still visible).
* Suppressed findings are omitted entirely (the user already
  reviewed and dismissed them).

Severity → JUnit mapping is conservative: only critical and high
block the build (become ``<failure>``). Medium and below are
``<skipped>`` with a reason — visible in CI UI but non-blocking.
This matches how most teams configure their CI quality gates.

Spec: https://llg.cubic.org/docs/junit/ (widely-implemented de-facto
standard, originally from Ant's JUnit reporter).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List
from xml.sax.saxutils import escape, quoteattr

from formatters.base import Finding, Severity, extract_findings


# JUnit spec is XML — characters must be escaped. ``xml.sax.saxutils``
# handles ``&``, ``<``, ``>``, ``"``/``'`` for attribute values.

# Severity → JUnit outcome
_BLOCKING_SEVERITIES = {Severity.CRITICAL, Severity.HIGH, Severity.ERROR}


def _format_location(finding: Finding, workspace: str = "") -> str:
    """Format file:line for the failure body."""
    if not finding.file:
        return "<no location>"
    path = finding.file
    if workspace and path.startswith(workspace):
        path = os.path.relpath(path, workspace)
    path = path.replace("\\", "/")
    if finding.line:
        path += f":{finding.line}"
        if finding.column:
            path += f":{finding.column}"
    return path


def _format_failure_body(finding: Finding, workspace: str = "") -> str:
    """Multi-line body for a JUnit <failure> element."""
    lines: List[str] = []
    lines.append(f"Location: {_format_location(finding, workspace)}")
    if finding.category:
        lines.append(f"Category: {finding.category}")
    if finding.confidence:
        lines.append(f"Confidence: {finding.confidence}")
    if finding.cwe:
        lines.append(f"CWE: {finding.cwe}")
    if finding.taint_path:
        lines.append(f"Taint path: {finding.taint_path}")
    if finding.snippet:
        lines.append("Snippet:")
        # Indent snippet lines so the XML body is readable.
        for snip_line in finding.snippet.splitlines():
            lines.append(f"  {snip_line}")
    return "\n".join(lines)


def format_junit_xml(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output as JUnit XML.

    Args:
        data: CodeLens command output dict.
        command: Command name (becomes the ``<testsuite>`` name suffix).
        workspace: Workspace root (for path shortening in failure bodies).

    Returns:
        Valid JUnit XML string. The output is a single ``<testsuites>``
        root with one ``<testsuite>`` child. Tests systems that only
        expect a single ``<testsuite>`` (older Jenkins plugins) can
        grab ``root[0]``.
    """
    findings = extract_findings(data, command)

    # Filter out suppressed findings — they were reviewed and dismissed.
    active = [f for f in findings if not f.suppressed]
    failures = [f for f in active if f.severity in _BLOCKING_SEVERITIES]
    skips = [f for f in active if f.severity not in _BLOCKING_SEVERITIES]

    suite_name = f"codelens-{command or 'unknown'}"
    # JUnit attributes are integers — counts must be ints.
    tests_count = len(active)
    failures_count = len(failures)
    skipped_count = len(skips)

    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<testsuites name="codelens" tests="{tests_count}" '
        f'failures="{failures_count}" disabled="{skipped_count}">'
    )
    lines.append(
        f'  <testsuite name="{escape(suite_name)}" '
        f'tests="{tests_count}" '
        f'failures="{failures_count}" '
        f'disabled="{skipped_count}" '
        f'errors="0" '
        f'time="0">'
    )

    # ─── Failures (critical/high) ───
    for f in failures:
        # testcase name = rule_id (stable across runs, CI can group by it)
        tc_name = f.rule_id or f.category or "codelens-finding"
        lines.append(
            f'    <testcase name={quoteattr(tc_name)} '
            f'classname={quoteattr(f.file or "codelens")}>'
        )
        # failure type = severity (uppercase, ASCII-safe)
        failure_type = (f.severity or "failure").upper()
        failure_msg = f.message or f.rule_id or "CodeLens finding"
        body = _format_failure_body(f, workspace)
        lines.append(
            f'      <failure message={quoteattr(failure_msg)} '
            f'type="{escape(failure_type)}">{escape(body)}</failure>'
        )
        lines.append('    </testcase>')

    # ─── Skipped (medium/low/info) ───
    for f in skips:
        tc_name = f.rule_id or f.category or "codelens-finding"
        lines.append(
            f'    <testcase name={quoteattr(tc_name)} '
            f'classname={quoteattr(f.file or "codelens")}>'
        )
        # <skipped> with a reason — non-blocking but visible.
        skip_reason = f"{f.severity}: {f.message}"
        lines.append(f'      <skipped message={quoteattr(skip_reason)}/>')
        lines.append('    </testcase>')

    lines.append('  </testsuite>')
    lines.append('</testsuites>')
    return "\n".join(lines)
