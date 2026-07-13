# @WHO:   scripts/commands/a11y.py
# @WHAT:  Accessibility (WCAG 2.1) audit command — thin wrapper over a11y_engine (issue #256)
# @PART:  commands
# @ENTRY: execute()
"""a11y command — accessibility audit (issue #256 restoration).

Wraps ``a11y_engine.audit_accessibility()`` — detects missing alt text,
missing form labels, ARIA issues, keyboard-nav gaps, non-semantic HTML,
color-contrast, heading-order, link-text, and focus-management problems
(WCAG 2.1).

The engine was never deleted, but its CLI entry point (the old standalone
``a11y`` command) was dropped in the #195 umbrella consolidation, leaving
the working engine orphaned — the exact same situation as ``css-deep``
(issue #251) and ``export-snapshot`` (issue #218). This restores access as
``audit --check a11y`` — a sub-check under the audit umbrella, NOT a new
top-level command, so the 12-umbrella consolidation is preserved (command
count stays 12).
"""

from a11y_engine import audit_accessibility
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["high", "medium", "low"], default=None,
                        help="Filter by severity level")
    parser.add_argument("--category", default=None,
                        help="Filter to one category: missing_alt, missing_label, "
                             "aria_issues, keyboard_nav, semantic_html, color_contrast, "
                             "heading_order, link_text, focus_management")


def execute(args, workspace):
    return audit_accessibility(
        workspace,
        category=getattr(args, "category", None),
        severity=getattr(args, "severity", None),
    )

# Issue #256: registered as the `a11y` sub-check of the `audit` umbrella
# (see commands/audit.py), NOT a standalone command — command count stays
# 12. Imported by audit.py, not self-registering.
