"""Memory command — Serena-style markdown memory system (issue #60).

Provides cross-session memory for AI agents using CodeLens. Memory files are
plain markdown stored under ``.codelens/memories/`` in the workspace (project
scope) or ``~/.codelens/memories/global/`` (global scope, read-only via CLI).

Usage::

    codelens memory write <name> <content>   # create/update project memory
    codelens memory read <name>              # read memory (project or global)
    codelens memory list                     # list all memories
    codelens memory delete <name>            # delete (project memory only)

The storage layout, file header rules, and ``mem:NAME`` reference validation
live in :mod:`memories.memory_manager` — this module is a thin CLI wrapper.
"""

from __future__ import annotations

from typing import Any, Dict

from commands import register_command


def add_args(parser):
    """Add memory subcommand arguments to the parser."""
    sub = parser.add_subparsers(dest="memory_action", help="Memory action")

    # memory write <name> <content>
    write = sub.add_parser(
        "write",
        help="Create or update a project memory file",
        description=(
            "Create or update a project memory file at "
            ".codelens/memories/<name>.md. The file is given a canonical "
            "'# Memory: <name>' header. mem:NAME references in <content> are "
            "validated and warnings are emitted for any references that do "
            "not exist in project or global scope — the write itself always "
            "succeeds (issue #60: warn, don't block)."
        ),
    )
    write.add_argument("name", help="Memory topic name (e.g. 'auth-flow')")
    write.add_argument(
        "content",
        help="Memory content (markdown). May include 'mem:NAME' references.",
    )

    # memory read <name>
    read = sub.add_parser(
        "read",
        help="Read a memory file (project or global)",
        description=(
            "Read a memory file. Looks in the project scope first, then "
            "falls back to the global scope. Returns 'not_found' if the "
            "memory doesn't exist in either scope."
        ),
    )
    read.add_argument("name", help="Memory topic name")

    # memory list
    sub.add_parser(
        "list",
        help="List all memory files (project + global)",
        description=(
            "List all memory files in project and global scope. Project "
            "memories shadow global memories of the same name."
        ),
    )

    # memory delete <name>
    delete = sub.add_parser(
        "delete",
        help="Delete a project memory file",
        description=(
            "Delete a project memory file. Global memories are read-only "
            "via CLI and cannot be deleted here — remove them manually from "
            "~/.codelens/memories/global/ if needed."
        ),
    )
    delete.add_argument("name", help="Memory topic name")


def execute(args, workspace):
    """Dispatch the memory subcommand."""
    action = getattr(args, "memory_action", None)
    if not action:
        return {
            "status": "error",
            "error": "No memory action specified. Use: write, read, list, delete",
            "usage": "codelens memory <write|read|list|delete> [args]",
            "examples": [
                "codelens memory write auth-flow 'Uses JWT, see mem:tokens'",
                "codelens memory read auth-flow",
                "codelens memory list",
                "codelens memory delete auth-flow",
            ],
        }

    # Lazy import so a broken memory_manager never breaks command discovery.
    from memories.memory_manager import (
        write_memory,
        read_memory,
        list_memories,
        delete_memory,
    )

    if action == "write":
        return write_memory(workspace, args.name, args.content)
    if action == "read":
        return read_memory(workspace, args.name)
    if action == "list":
        return list_memories(workspace)
    if action == "delete":
        return delete_memory(workspace, args.name)

    return {
        "status": "error",
        "error": f"Unknown memory action: {action}",
        "available_actions": ["write", "read", "list", "delete"],
    }


register_command(
    "memory",
    "Serena-style markdown memory system (write/read/list/delete)",
    add_args,
    execute,
)
