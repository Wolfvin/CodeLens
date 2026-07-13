# @WHO:   scripts/commands/css_deep.py
# @WHAT:  Deep CSS analysis command — thin wrapper over cssdeep_engine (issue #251)
# @PART:  commands
# @ENTRY: execute()
"""css-deep command — deep CSS analysis (issue #251 restoration).

Wraps ``cssdeep_engine.analyze_css_deep()`` — detects unused CSS variables,
orphan keyframes, specificity wars, duplicate properties, unused media
queries, and z-index abuse.

The engine was never deleted, but its CLI entry point (the old standalone
``css-deep`` command) was dropped in the #195 umbrella consolidation,
leaving the working engine orphaned (same situation as ``export-snapshot``,
issue #218). This restores access as ``audit --check css`` — a sub-check
under the audit umbrella, NOT a new top-level command, so the 12-umbrella
consolidation is preserved (command count stays 12).
"""

from cssdeep_engine import analyze_css_deep
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["high", "medium", "low"], default=None,
                        help="Filter by severity level")
    parser.add_argument("--category", default=None,
                        help="Filter to one category: unused_vars, orphan_keyframes, "
                             "specificity_wars, duplicate_props, unused_media, z_index_abuse")


def execute(args, workspace):
    return analyze_css_deep(
        workspace,
        severity=getattr(args, "severity", None),
        category=getattr(args, "category", None),
    )

# Issue #251: registered as the `css` sub-check of the `audit` umbrella
# (see commands/audit.py), NOT as a standalone command — keeps command
# count at 12. This module is imported by audit.py, not self-registering.
