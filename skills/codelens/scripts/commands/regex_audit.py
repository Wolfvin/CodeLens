"""Regex-audit command — Audit regex for ReDoS and issues."""

from regexaudit_engine import audit_regex_patterns
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity")


def execute(args, workspace):
    return audit_regex_patterns(workspace, severity=args.severity)


register_command("regex-audit", "Audit regex for ReDoS and issues", add_args, execute)
