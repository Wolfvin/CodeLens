"""Diff command — Compare registry snapshots."""

from diff_engine import diff_current_vs_last, diff_snapshots, save_snapshot, list_snapshots
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--snapshot1", default=None, help="First snapshot ID (default: second-to-last)")
    parser.add_argument("--snapshot2", default=None, help="Second snapshot ID (default: last)")
    parser.add_argument("--list-snapshots", action="store_true", help="List available snapshots")


def execute(args, workspace):
    if args.list_snapshots:
        snaps = list_snapshots(workspace)
        return {"status": "ok", "snapshots": snaps}
    elif args.snapshot1 or args.snapshot2:
        return diff_snapshots(workspace, args.snapshot1, args.snapshot2)
    else:
        return diff_current_vs_last(workspace)


register_command("diff", "Compare registry snapshots", add_args, execute)
