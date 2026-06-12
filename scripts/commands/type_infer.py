"""Type-infer command — Lightweight type inference for JS/Python."""

from typeinfer_engine import infer_types
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None, help="Specific file to analyze")
    parser.add_argument("--function", dest="function_name", default=None,
                        help="Specific function to infer types for")


def execute(args, workspace):
    return infer_types(
        workspace,
        file_path=args.file,
        function_name=args.function_name
    )


register_command("type-infer", "Lightweight type inference for JS/Python", add_args, execute)
