"""Side-effect command — Analyze function side effects (pure vs impure)."""

from sideeffect_engine import analyze_side_effects
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--name", default=None, help="Specific function to analyze (optional)")
    parser.add_argument("--file", default=None, help="Filter by file path")
    parser.add_argument("--max-files", type=int, default=3000,
                        help="Max files to scan (default: 3000)")


def execute(args, workspace):
    return analyze_side_effects(
        workspace,
        function_name=args.name,
        file_filter=args.file,
        max_files=args.max_files
    )


register_command("side-effect", "Analyze function side effects (pure vs impure)", add_args, execute,

hidden=True,

deprecated_alias_for='audit',

)
