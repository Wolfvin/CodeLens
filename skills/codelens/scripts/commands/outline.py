"""Outline command — Get file structure outline."""

from outline_engine import get_file_outline, get_workspace_outline
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None, help="Specific file to outline")
    parser.add_argument("--detail", choices=["minimal", "normal", "full"], default="normal",
                        help="Detail level")
    parser.add_argument("--all", action="store_true", dest="all_files",
                        help="Outline all files in workspace")


def execute(args, workspace):
    if args.all_files:
        return get_workspace_outline(workspace)
    elif args.file:
        return get_file_outline(args.file, workspace, detail_level=args.detail)
    else:
        return get_workspace_outline(workspace)


register_command("outline", "Get file structure outline", add_args, execute)
