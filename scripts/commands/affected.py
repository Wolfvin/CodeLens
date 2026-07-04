"""Affected command — identify test files affected by source changes.

Issue #62 Phase 1: quick-win CI/CD tool. Given a list of changed source
files (positional args, or piped via ``--stdin`` from ``git diff --name-only``),
walks the reverse import-dependency graph and prints every test file that
transitively depends on any of the changed files.

The classic CI pattern is::

    AFFECTED=$(git diff --name-only HEAD | codelens affected --stdin --quiet)
    pytest $AFFECTED

By default only test files are returned (so ``pytest $AFFECTED`` doesn't try
to run non-test modules). Pass ``--include-source`` to also list non-test
dependents — useful for impact analysis in code review.

Resolution of changed-file paths is forgiving: absolute paths, workspace-
relative paths, and bare basenames are all accepted. Ambiguous basenames
(files with the same name in multiple directories) are skipped rather
than silently picking the wrong one.

Backed by :func:`dependents_engine.get_affected_files`.
"""

from __future__ import annotations

import sys

from commands import register_command


def add_args(parser):
    """Add `affected` command arguments."""
    parser.add_argument(
        "files",
        nargs="*",
        default=None,
        help="Changed file paths (absolute, relative, or bare basenames). "
             "If omitted, reads from stdin — pipe `git diff --name-only`.",
    )
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted).",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        default=False,
        help="Read changed file paths from stdin (one per line). "
             "Useful for piping: `git diff --name-only HEAD | codelens affected --stdin`.",
    )
    parser.add_argument(
        "-d", "--depth",
        type=int,
        default=5,
        help="BFS depth cap (default 5). -1 = unlimited (with a 5000-node safety cap).",
    )
    parser.add_argument(
        "-f", "--filter",
        default=None,
        metavar="<glob>",
        help="Only return affected files matching this glob (e.g. 'tests/*.py'). "
             "Does not affect traversal. Default: no filter.",
    )
    parser.add_argument(
        "-j", "--json",
        dest="as_json",
        action="store_true",
        default=False,
        help="Emit full result dict as JSON instead of plain file list.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        default=False,
        help="Only print affected file paths, one per line. No stats, no headers. "
             "Default when piping to another command.",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        default=False,
        help="Also return non-test dependents. By default only test files are returned.",
    )


def execute(args, workspace):
    """Run the affected-files analysis.

    Returns a dict (when ``--json`` or default) or prints paths to stdout
    (when ``--quiet``). Reads from stdin when ``--stdin`` is set.
    """
    # Gather changed files from args + stdin
    changed_files: list[str] = list(args.files or [])

    if getattr(args, "stdin", False):
        try:
            stdin_text = sys.stdin.read()
        except (KeyboardInterrupt, OSError):
            stdin_text = ""
        for line in stdin_text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                changed_files.append(line)

    # Issue #176: argparse assigns ALL positional args to ``files`` (nargs="*")
    # and leaves ``workspace`` as None. The CLI dispatcher then auto-detects
    # workspace to cwd, which is wrong when the user explicitly passed a
    # workspace path as the first positional arg.
    #
    # Heuristic: if the first item in ``files`` is an existing directory that
    # differs from the auto-detected workspace, treat it as the intended
    # workspace and remove it from the changed-files list. This is
    # non-breaking: if the first arg is a file (not a dir), the old behavior
    # is preserved.
    import os
    if changed_files and os.path.isdir(changed_files[0]):
        first_arg_abs = os.path.abspath(changed_files[0])
        ws_abs = os.path.abspath(workspace) if workspace else ""
        if first_arg_abs != ws_abs:
            workspace = first_arg_abs
            changed_files.pop(0)

    if not changed_files:
        return {
            "status": "error",
            "error": (
                "no changed files provided. Pass file paths as args, or use "
                "--stdin to read from stdin (e.g. `git diff --name-only | "
                "codelens affected --stdin`)."
            ),
            "workspace": workspace,
        }

    # Lazy import — keeps the command light if only --help is invoked
    from dependents_engine import get_affected_files

    result = get_affected_files(
        changed_files=changed_files,
        workspace=workspace,
        depth=args.depth,
        file_filter=args.filter,
        include_source=args.include_source,
    )

    # --quiet mode: print only file paths, one per line, to stdout
    if getattr(args, "quiet", False):
        for f in result.get("affected", []):
            print(f)
        # Return a minimal dict so the CLI wrapper doesn't double-print
        return {
            "status": "ok",
            "quiet": True,
            "affected_count": len(result.get("affected", [])),
            "workspace": workspace,
        }

    # Default + --json: return the full result dict (formatter handles output)
    st = result.get("stats", {})
    if st.get("affected_test_count", 0) == 0 and st.get("visited_total", 0) > 0:
        result["note"] = "No test files found in dependents. Use --include-source to list all affected source files."
    return result


register_command(
    "affected",
    "Identify test files affected by source changes (issue #62 Phase 1)",
    add_args,
    execute,
)
