"""Regex-audit command — Audit regex for ReDoS and issues."""

from regexaudit_engine import audit_regex_patterns, MAX_FILES_PER_RUN
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["high", "medium", "low"], default=None,
                        help="Filter by severity")
    parser.add_argument("--max-files", type=int, default=MAX_FILES_PER_RUN,
                        help=f"Max files to scan (default: {MAX_FILES_PER_RUN})")


def execute(args, workspace):
    return audit_regex_patterns(workspace, severity=args.severity, max_files=args.max_files)

# Issue #199: deprecated "regex-audit" alias registration removed; this module is now an implementation module imported by the "security" umbrella command.
