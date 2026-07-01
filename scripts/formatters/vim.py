"""Vim quickfix formatter for CodeLens (issue #52, Phase 2).

Emits findings in Vim's ``quickfix`` format::

    file:line:col: message

Slightly different from Emacs format — no ``severity:`` prefix
(quickfix doesn't have a native severity concept; severity goes
into the message text instead). Clicking a line in the quickfix
window jumps to the source location.

Format spec: ``:help errorformat`` in Vim, or
https://vimdoc.sourceforge.net/htmldoc/quickfix.html#errorformat

The format is line-oriented, one finding per line. Severity is
prefixed to the message so users see it in the quickfix window:
``file:line:col: [critical] message``.
"""

from __future__ import annotations

import os
from typing import Any, List

from formatters.base import Finding, extract_findings


def _format_line(finding: Finding, workspace: str = "") -> str:
    """Format a single finding as ``file:line:col: [severity] message``."""
    if not finding.file:
        path = "<unknown>"
    else:
        path = finding.file
        if workspace and path.startswith(workspace):
            path = os.path.relpath(path, workspace)
        path = path.replace("\\", "/")

    if finding.line:
        loc = f"{path}:{finding.line}"
        if finding.column:
            loc += f":{finding.column}"
    else:
        loc = path

    # Severity goes into the message — quickfix has no native severity
    # field. Brackets make it visually distinct without being noisy.
    severity_tag = ""
    if finding.severity:
        severity_tag = f"[{finding.severity}] "

    message = finding.message or finding.rule_id or "CodeLens finding"
    return f"{loc}: {severity_tag}{message}"


def format_vim(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output for Vim ``quickfix``.

    Args:
        data: CodeLens command output dict.
        command: Command name (unused — kept for API consistency).
        workspace: Workspace root (for path shortening).

    Returns:
        One line per finding, no header/footer. Empty string if no
        findings — Vim handles empty quickfix gracefully (``:copen``
        shows an empty list).
    """
    findings = extract_findings(data, command)

    active = [f for f in findings if not f.suppressed]

    if not active:
        # Return empty — Vim users typically pipe output directly to
        # ``:cgetexpr`` or ``:caddexpr``, which prefer no output over
        # a comment line (which would appear as a parse-failed entry).
        return ""

    lines: List[str] = [_format_line(f, workspace) for f in active]
    return "\n".join(lines)
