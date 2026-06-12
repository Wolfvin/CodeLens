"""Secrets command — Detect hardcoded secrets and API keys."""

from secrets_engine import detect_secrets
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000)")


def execute(args, workspace):
    return detect_secrets(workspace, severity=args.severity, max_files=args.max_files)


register_command("secrets", "Detect hardcoded secrets and API keys", add_args, execute)
