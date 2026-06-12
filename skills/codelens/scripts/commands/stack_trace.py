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
    # Validate: if 'name' looks like a path, it was likely meant as workspace
    name = args.name
    if name and (os.path.isabs(name) or name.startswith('./') or name.startswith('../')):
        # User probably omitted function name and passed workspace as first arg
        # Swap: use name as workspace, leave function name empty
        workspace = name
        name = ""
    return trace_error_propagation(
        name, workspace,
        error_type=args.error_type,
        max_depth=args.depth
    )


import os
register_command("stack-trace", "Error propagation simulation", add_args, execute)
