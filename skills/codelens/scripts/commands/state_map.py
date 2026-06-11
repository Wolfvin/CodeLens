"""State-map command — Track global state management."""

from statemap_engine import map_state
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--store", dest="store_name", default=None,
                        help="Filter by store name")


def execute(args, workspace):
    return map_state(workspace, store_name=args.store_name)


register_command("state-map", "Track global state management", add_args, execute)
