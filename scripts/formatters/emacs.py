"""Emacs compilation-mode formatter for CodeLens (issue #52, Phase 2).

Emits findings in the canonical Emacs ``compile-mode`` format::

    file:line:col: severity: message

Clicking a line in ``*compilation*`` buffer jumps to the source
location. Works in Emacs (``M-x compile``), and is also recognized
by ``grep-mode``, ``flymake``, and many third-party Emacs tools.

Format spec: https://www.gnu.org/software/emacs/manual/html_node/emacs/Compilation-Mode.html

Severity → Emacs level mapping:
  critical / high → ``error``   (red, blocks next-error navigation)
  medium          → ``warning`` (yellow)
  low / info      → ``note``    (default face, non-blocking)

The format is line-oriented, one finding per line. No header, no
footer — Emacs parses each line independently, so any extra prose
would be ignored or flagged as "no match".
"""

from __future__ import annotations

import os
from typing import Any, List

from formatters.base import Finding, Severity, extract_findings


# Severity → Emacs level string. Lowercase to match Emacs convention.
_EMACS_LEVEL = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.ERROR: "error",
    Severity.MEDIUM: "warning",
    Severity.WARNING: "warning",
    Severity.LOW: "note",
    Severity.INFO: "note",
}


def _format_line(finding: Finding, workspace: str = "") -> str:
    """Format a single finding as ``file:line:col: level: message``."""
    if not finding.file:
        # Without a file, Emacs can't jump — but we still want to
        # surface the finding. Use a placeholder path.
        path = "<unknown>"
    else:
        path = finding.file
        if workspace and path.startswith(workspace):
            path = os.path.relpath(path, workspace)
        path = path.replace("\\", "/")

    # Build the location prefix: file:line:col
    # Omit col if 0 (engines often don't compute it).
    if finding.line:
        loc = f"{path}:{finding.line}"
        if finding.column:
            loc += f":{finding.column}"
    else:
        loc = path

    level = _EMACS_LEVEL.get(finding.severity, "note")
    message = finding.message or finding.rule_id or "CodeLens finding"

    return f"{loc}: {level}: {message}"


def format_emacs(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output for Emacs ``compile-mode``.

    Args:
        data: CodeLens command output dict.
        command: Command name (unused — kept for API consistency).
        workspace: Workspace root (for path shortening).

    Returns:
        One line per finding, no header/footer. Empty string if no
        findings (Emacs handles empty compile output gracefully).
    """
    findings = extract_findings(data, command)

    # Skip suppressed findings — Emacs users don't want to see
    # dismissed warnings cluttering their *compilation* buffer.
    active = [f for f in findings if not f.suppressed]

    if not active:
        # Return a single informative line — Emacs users expect SOME
        # output from a compile run, not total silence.
        return f"# CodeLens: no findings for command '{command or 'unknown'}'"

    lines: List[str] = [_format_line(f, workspace) for f in active]
    return "\n".join(lines)
