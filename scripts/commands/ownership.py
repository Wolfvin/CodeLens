"""Ownership command — Git blame-based code ownership."""

from ownership_engine import analyze_ownership
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--file", default=None, help="Specific file to analyze")
    parser.add_argument("--function", dest="function_name", default=None,
                        help="Specific function to check ownership")


def execute(args, workspace):
    return analyze_ownership(
        workspace,
        file_path=args.file,
        function_name=args.function_name
    )


register_command("ownership", "Git blame-based code ownership", add_args, execute,

hidden=True,

deprecated_alias_for='history',

)
