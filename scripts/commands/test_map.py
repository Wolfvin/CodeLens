"""Test-map command — Map test coverage for functions."""

from testmap_engine import map_test_coverage
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--function", dest="function_name", default=None,
                        help="Check specific function test coverage")
    parser.add_argument("--file", default=None, help="Filter by source file path")
    parser.add_argument("--max-files", type=int, default=3000,
                        help="Max files to scan (default: 3000)")


def execute(args, workspace):
    return map_test_coverage(
        workspace,
        function_name=args.function_name,
        file_filter=args.file,
        max_files=args.max_files
    )


register_command("test-map", "Map test coverage for functions", add_args, execute,

hidden=True,

)
