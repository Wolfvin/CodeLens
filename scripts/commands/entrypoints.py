"""Entrypoints command — Map execution entry points."""

from entrypoints_engine import map_entrypoints
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--type", dest="entry_type", default=None,
                        choices=["main", "http_handler", "event_handler", "cli_command",
                                 "cron_job", "worker", "module_export", "test_entry"],
                        help="Filter by entry point type")
    parser.add_argument("--exclude-tests", action="store_true", default=False,
                        help="Exclude test_entry type from scanning (reduces noise on large repos)")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000)")


def execute(args, workspace):
    return map_entrypoints(workspace, entry_type=args.entry_type,
                           exclude_tests=args.exclude_tests,
                           max_files=args.max_files)


register_command("entrypoints", "Map execution entry points", add_args, execute,

hidden=True,

)
