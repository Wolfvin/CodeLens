"""Dataflow command — Trace data flow source→sink (security)."""

from dataflow_engine import trace_dataflow
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--source", default=None,
                        help="Source filter (user_input, env_var, file_input, api_response)")
    parser.add_argument("--sink", default=None,
                        help="Sink filter (db_query, html_output, command_exec, file_write, http_header)")
    parser.add_argument("--depth", type=int, default=15, help="Max data flow chain depth (default 15)")
    parser.add_argument("--max-files", type=int, default=3000,
                        help="Max files to scan (default 3000, use 0 for all)")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Time budget in seconds (default 120)")


def execute(args, workspace):
    return trace_dataflow(
        workspace,
        source=args.source,
        sink=args.sink,
        max_depth=args.depth,
        max_files=args.max_files,
        timeout_sec=float(args.timeout)
    )


register_command("dataflow", "Trace data flow source→sink (security)", add_args, execute)
