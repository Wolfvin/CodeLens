"""Stack-trace command — Error propagation simulation."""

from stacktrace_engine import trace_error_propagation
from commands import register_command


def add_args(parser):
    parser.add_argument("name", help="Function name that might throw")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--error-type", default=None, help="Error type (e.g., TypeError)")
    parser.add_argument("--depth", type=int, default=20, help="Max trace depth (default 20)")


def execute(args, workspace):
    return trace_error_propagation(
        args.name, workspace,
        error_type=args.error_type,
        max_depth=args.depth
    )


register_command("stack-trace", "Error propagation simulation", add_args, execute)
