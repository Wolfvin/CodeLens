"""A11y command — Detect accessibility issues."""

from a11y_engine import audit_accessibility
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--category", choices=["missing_alt", "missing_label", "aria_issues",
                      "keyboard_nav", "semantic_html", "color_contrast", "heading_order",
                      "link_text", "focus_management"], default=None,
                      help="Filter by a11y category")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                      help="Filter by severity")


def execute(args, workspace):
    return audit_accessibility(workspace, category=args.category, severity=args.severity)


register_command("a11y", "Detect accessibility issues", add_args, execute)
