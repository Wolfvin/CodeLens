"""Symbols command — Search registry symbols by name."""

from search_engine import search_symbols
from commands import register_command


def add_args(parser):
    parser.add_argument("name", help="Symbol name to search")
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--domain", choices=["frontend", "backend", "all"], default="all",
                        help="Domain to search")
    parser.add_argument("--fuzzy", action="store_true", help="Allow partial/fuzzy matching")


def execute(args, workspace):
    return search_symbols(workspace, args.name, domain=args.domain, fuzzy=args.fuzzy)


register_command("symbols", "Search symbols in registry by name", add_args, execute)
