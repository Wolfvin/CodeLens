"""Env-check command — Audit environment variables."""

from envcheck_engine import check_env_vars
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--var", dest="var_name", default=None,
                        help="Filter by variable name")


def execute(args, workspace):
    return check_env_vars(workspace, var_name=args.var_name)


register_command("env-check", "Audit environment variables", add_args, execute)
