# @WHO:   scripts/formatters/text.py
# @WHAT:  Text table formatter — human-readable ASCII table for terminal output (issue #52 Phase 2)
# @PART:  formatters
# @ENTRY: format_text()
"""Text table formatter for CodeLens (issue #52, Phase 2).

Human-readable table output for terminal consumption:

    RULE ID                          SEVERITY  LOCATION                       MESSAGE
    codelens/secrets/api-key         critical  src/auth.py:42:10              Hardcoded API key detected
    codelens/dead-code/unreachable   medium    src/utils.py:128:1             Unreachable code after return

Designed for ``--format text`` — when the user wants a quick
terminal-readable view without JSON noise. ASCII-only so it pipes
cleanly through ``grep``/``awk`` and works on Windows terminals.

The formatter consumes :class:`formatters.base.Finding` objects via
:func:`formatters.base.extract_findings` — single extraction path,
consistent with all other Phase 2 formatters.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from formatters.base import Finding, Severity, extract_findings


# Column widths — tuned for 80-column terminals. Long fields are
# truncated with ellipsis. ``MESSAGE`` gets the leftover space.
_COL_WIDTHS = {
    "rule_id": 32,
    "severity": 9,
    "location": 30,
}

# Severity → display symbol (ASCII, not Unicode, for terminal compat).
_SEVERITY_SYMBOL = {
    Severity.CRITICAL: "CRIT",
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MED ",
    Severity.LOW: "LOW ",
    Severity.INFO: "INFO",
    Severity.ERROR: "ERR ",
    Severity.WARNING: "WARN",
}


def _truncate(text: str, width: int) -> str:
    """Truncate text to width, appending ``...`` if truncated."""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _format_location(finding: Finding, workspace: str = "") -> str:
    """Format ``file:line:column`` for the LOCATION column.

    Strips the workspace prefix to keep paths short. If ``file`` is
    empty, returns ``<unknown>``.
    """
    if not finding.file:
        return "<unknown>"
    path = finding.file
    if workspace and path.startswith(workspace):
        path = os.path.relpath(path, workspace)
    # Replace backslashes for cross-platform consistency.
    path = path.replace("\\", "/")

    parts: List[str] = [path]
    if finding.line:
        parts.append(str(finding.line))
        if finding.column:
            parts.append(str(finding.column))
    return ":".join(parts)


def format_text(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output as a human-readable text table.

    Args:
        data: CodeLens command output dict.
        command: Command name (used in the header).
        workspace: Workspace root (for path shortening).

    Returns:
        Multi-line string with header + finding rows. If no findings,
        returns a "no findings" message (not an empty string — empty
        output looks like a bug).
    """
    findings = extract_findings(data, command)

    # Split active vs suppressed — formatters' job is to surface
    # actionable findings. Suppressed count is shown in the footer
    # so the user knows dismissals happened, but suppressed findings
    # don't get their own rows (they'd clutter the table).
    active = [f for f in findings if not f.suppressed]
    suppressed_count = len(findings) - len(active)

    if not active:
        if isinstance(data, dict) and data.get("status") == "error":
            return f"ERROR: {data.get('error', 'unknown error')}"
        if suppressed_count:
            return f"No active findings for command '{command or 'unknown'}' ({suppressed_count} suppressed)."
        return f"No findings for command '{command or 'unknown'}'."

    # ─── Header ───
    header = (
        f"CodeLens — {len(active)} finding(s) from command '{command or 'unknown'}'"
    )
    sep = "=" * 80

    # ─── Column headers ───
    col_header = (
        f"{'RULE ID':<{_COL_WIDTHS['rule_id']}}  "
        f"{'SEVERITY':<{_COL_WIDTHS['severity']}}  "
        f"{'LOCATION':<{_COL_WIDTHS['location']}}  "
        f"MESSAGE"
    )
    col_sep = "-" * 80

    # ─── Rows ───
    lines: List[str] = [header, sep, col_header, col_sep]
    for f in active:
        rule = _truncate(f.rule_id or "<no-rule>", _COL_WIDTHS["rule_id"])
        sev = _truncate(
            _SEVERITY_SYMBOL.get(f.severity, f.severity[:4].upper() or "UNKN"),
            _COL_WIDTHS["severity"],
        )
        loc = _truncate(_format_location(f, workspace), _COL_WIDTHS["location"])
        # Message gets the leftover width — don't truncate, let it wrap
        # naturally (terminals handle that better than us hard-wrapping).
        msg = f.message or "<no message>"
        lines.append(
            f"{rule:<{_COL_WIDTHS['rule_id']}}  "
            f"{sev:<{_COL_WIDTHS['severity']}}  "
            f"{loc:<{_COL_WIDTHS['location']}}  "
            f"{msg}"
        )

    lines.append(sep)

    # ─── Severity summary footer ───
    sev_counts: Dict[str, int] = {}
    for f in active:
        sev_counts[f.severity] = sev_counts.get(f.severity, 0) + 1
    summary_parts = [f"{count} {sev}" for sev, count in sorted(sev_counts.items())]
    lines.append(f"Summary: {', '.join(summary_parts)}")
    if suppressed_count:
        lines.append(f"({suppressed_count} suppressed)")

    return "\n".join(lines)
