"""Search command — Search code pattern across workspace."""

import os
from search_engine import search_workspace
from registry import load_config
from commands import register_command


def add_args(parser):
    parser.add_argument("pattern", help="Regex pattern to search for")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--type", dest="file_type", default=None,
                        help="File type filter (html, css, js, ts, tsx, rust, python, vue, svelte)")
    parser.add_argument("--file", default=None, help="Filter by file path substring")
    parser.add_argument("--max-results", type=int, default=200, help="Max results (default 200)")
    parser.add_argument("--context", type=int, default=0, help="Context lines around match")
    parser.add_argument("--ignore-case", action="store_true", help="Case-insensitive search")
    parser.add_argument("--whole-word", action="store_true", help="Match whole words only")


def execute(args, workspace):
    config = load_config(os.path.abspath(workspace))
    return search_workspace(
        workspace, args.pattern,
        file_type=args.file_type,
        file_filter=args.file,
        max_results=args.max_results,
        context_lines=args.context,
        case_sensitive=not args.ignore_case,
        whole_word=args.whole_word,
        config=config
    )


register_command("search", "Search code pattern across workspace", add_args, execute)
