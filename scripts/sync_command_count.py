#!/usr/bin/env python3
"""
sync_command_count.py — Single-source-of-truth synchronizer for command counts.

Why this exists
---------------
Issue #38: CodeLens command count was hardcoded in 7+ places across the repo
(README, SKILL, SKILL-QUICK, pyproject.toml, skill.json, mcp_server.py,
graph_model.py, test_integration.py). The numbers drifted (41, 45, 56, 57, 60)
and none matched the actual runtime count. Updating them by hand every time a
command is added is exactly what caused the drift in the first place.

This script reads the runtime ``COMMAND_REGISTRY`` (the canonical source of
how many commands CodeLens actually has) and ``_TOOL_DEFINITIONS`` (the
canonical source of MCP static tool definitions) and rewrites every
documentation / metadata file to use the correct numbers.

Usage
-----
::

    python3 scripts/sync_command_count.py            # alias for --check
    python3 scripts/sync_command_count.py --check    # exit 1 if any file would change
    python3 scripts/sync_command_count.py --apply    # write changes to disk

When to run
-----------
- After adding or removing a command module in ``scripts/commands/``
- In CI (via ``tests/test_command_count.py``) to catch drift before merge
- Manually, before tagging a release

This script is the ONLY place that knows the full list of files that mention
command / MCP tool counts. The documentation files themselves never hardcode
the number — they always get it from ``COMMAND_REGISTRY`` via this script.

The strict regression sentinel (``EXPECTED_COMMAND_COUNT``) lives in
``tests/test_integration.py`` and is intentionally NOT touched by this script —
that sentinel is the test's job, not the docs' job.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple

# Make scripts/ importable when this file is run directly (no PYTHONPATH set).
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402  (path inserted above)

# ``_TOOL_DEFINITIONS`` is the static MCP tool registry. Importing it also
# validates that the MCP server module is intact. If the import fails (e.g.
# tree-sitter missing in a stripped-down environment), MCP count sync is
# skipped — but command count sync still runs.
try:
    from mcp_server import _TOOL_DEFINITIONS  # type: ignore  # noqa: E402
    _MCP_AVAILABLE = True
except Exception:  # pragma: no cover - defensive
    _TOOL_DEFINITIONS = {}  # type: ignore
    _MCP_AVAILABLE = False


# Commands that are NOT exposed as MCP tools (long-running, would block the
# JSON-RPC server). Must match ``MCPServer._get_dynamic_tools`` exclusion.
_MCP_EXCLUDED_COMMANDS = {"watch", "serve"}


def get_command_count() -> int:
    """Return the canonical CodeLens CLI command count.

    This is the single source of truth. Every doc, metadata file, and test
    sentinel must reconcile to this number.

    Issue #195: only counts visible (non-hidden) commands. Deprecated
    aliases are still in ``COMMAND_REGISTRY`` so they remain callable for
    backward compat, but they don't inflate the headline count.
    """
    return sum(1 for info in COMMAND_REGISTRY.values()
               if not info.get("hidden", False))


def get_mcp_counts() -> Tuple[int, int, int]:
    """Return ``(total, static, dynamic)`` MCP tool counts.

    - ``total``   = every visible command except the long-running exclusions
                    (``watch`` + ``serve``)
    - ``static``  = ``_TOOL_DEFINITIONS`` entries whose command name is
                    a visible (non-hidden) command (issue #195: static
                    tool definitions for hidden deprecated aliases are
                    excluded so they don't inflate the count)
    - ``dynamic`` = ``total - static`` (auto-discovered from COMMAND_REGISTRY)

    Issue #195: hidden deprecated aliases are excluded — they are not
    exposed as MCP tools (the umbrella commands are).
    """
    if not _MCP_AVAILABLE:
        return (0, 0, 0)
    visible_names = {name for name, info in COMMAND_REGISTRY.items()
                     if name not in _MCP_EXCLUDED_COMMANDS
                     and not info.get("hidden", False)}
    total = len(visible_names)
    # Only count static tools whose command is visible.
    static = sum(1 for name in _TOOL_DEFINITIONS if name in visible_names)
    dynamic = total - static
    return (total, static, dynamic)


# ─── Replacement rules ────────────────────────────────────────────────────
#
# Each entry is ``(relative_path, regex, template)``.
#
# - ``regex``   — compiled with ``re.MULTILINE``; must match the FULL phrase
#                 containing the digit(s) to be replaced, so that no other
#                 digits on the same line get clobbered.
# - ``template``— uses ``{cmd}`` / ``{mcp}`` / ``{static}`` / ``{dynamic}``
#                 placeholders, filled from the runtime counts above.
#
# When adding a new place that mentions command/MCP counts, ADD A RULE HERE.
# Do not introduce a second sync mechanism.

_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)


def _rel(*parts: str) -> str:
    return os.path.join(_PROJECT_ROOT, *parts)


def _build_rules() -> List[Tuple[str, str, str]]:
    """Return the list of ``(file, regex, template)`` sync rules."""
    return [
        # ─── README.md ───────────────────────────────────────────────
        # L5: "through N CLI commands, an MCP server with M tools (S static + D dynamic)"
        (_rel("README.md"),
         r"through \d+ CLI commands, an MCP server with \d+ tools \(\d+ static \+ \d+ dynamic\)",
         "through {cmd} CLI commands, an MCP server with {mcp} tools ({static} static + {dynamic} dynamic)"),
        # L9: "- **N CLI Commands** — From basic ..."
        (_rel("README.md"),
         r"\*\*\d+ CLI Commands\*\*",
         "**{cmd} CLI Commands**"),
        # L10: "- **MCP Server (M Tools)** — ... S statically-defined tools + D dynamically discovered"
        (_rel("README.md"),
         r"\*\*MCP Server \(\d+ Tools\)\*\* — Native AI agent integration via Model Context Protocol \(JSON-RPC over stdio\), \d+ statically-defined tools \+ \d+ dynamically discovered",
         "**MCP Server ({mcp} Tools)** — Native AI agent integration via Model Context Protocol (JSON-RPC over stdio), {static} statically-defined tools + {dynamic} dynamically discovered"),
        # L228: "CLI entry point (N commands registered)"
        (_rel("README.md"),
         r"CLI entry point \(\d+ commands registered\)",
         "CLI entry point ({cmd} commands registered)"),
        # L229: "MCP JSON-RPC server (M tools)"
        (_rel("README.md"),
         r"MCP JSON-RPC server \(\d+ tools\)",
         "MCP JSON-RPC server ({mcp} tools)"),
        # L286: "(auto-registered, N commands incl. graph-schema)"  — drop the
        # stale "incl. graph-schema" suffix; the count already includes it.
        (_rel("README.md"),
         r"\(auto-registered, \d+ commands incl\. graph-schema\)",
         "(auto-registered, {cmd} commands)"),

        # ─── SKILL.md ────────────────────────────────────────────────
        # L4: "N commands for AI-powered code analysis"
        (_rel("SKILL.md"),
         r"\d+ commands for AI-powered code analysis",
         "{cmd} commands for AI-powered code analysis"),
        # L7: "MCP server exposes M tools for AI agent integration."
        (_rel("SKILL.md"),
         r"MCP server exposes \d+ tools for AI agent integration",
         "MCP server exposes {mcp} tools for AI agent integration"),

        # ─── SKILL-QUICK.md ──────────────────────────────────────────
        # L116: "## All N Commands"
        (_rel("SKILL-QUICK.md"),
         r"^## All \d+ Commands",
         "## All {cmd} Commands"),
        # L148: "**Total: N commands** ..." — collapse the entire stale
        # parenthetical (the per-issue breakdown is wrong and not maintained).
        (_rel("SKILL-QUICK.md"),
         r"\*\*Total: \d+ commands\*\* \(.*?\)",
         "**Total: {cmd} commands** (auto-registered via `commands/__init__.py`; rerun `python3 scripts/sync_command_count.py --apply` after adding/removing a command)"),
        # L150: "## MCP Server (M Tools)"
        (_rel("SKILL-QUICK.md"),
         r"^## MCP Server \(\d+ Tools\)",
         "## MCP Server ({mcp} Tools)"),
        # L158: "Exposes M tools as `codelens_<command>` ..."
        (_rel("SKILL-QUICK.md"),
         r"Exposes \d+ tools as `codelens_<command>`",
         "Exposes {mcp} tools as `codelens_<command>`"),
        # L159: "- N statically-defined tools (full JSON schemas ...)"
        (_rel("SKILL-QUICK.md"),
         r"^- \d+ statically-defined tools \(full JSON schemas in `mcp_server.py`\) including .*$",
         "- {static} statically-defined tools (full JSON schemas in `mcp_server.py`)"),
        # L160: "- D dynamically-discovered tools (...)"
        (_rel("SKILL-QUICK.md"),
         r"^- \d+ dynamically-discovered tools \(.*\)$",
         "- {dynamic} dynamically-discovered tools (auto-discovered from `COMMAND_REGISTRY`; long-running `watch` and `serve` are excluded)"),

        # ─── pyproject.toml ──────────────────────────────────────────
        # L8: description = "... N commands for AI-powered code analysis ..."
        (_rel("pyproject.toml"),
         r"\d+ commands for AI-powered code analysis",
         "{cmd} commands for AI-powered code analysis"),

        # ─── skill.json ──────────────────────────────────────────────
        # L4: "description": "Live Codebase Reference Intelligence. N commands ..."
        (_rel("skill.json"),
         r"\d+ commands for AI-powered code analysis",
         "{cmd} commands for AI-powered code analysis"),

        # ─── scripts/mcp_server.py ───────────────────────────────────
        # L7: "... automatic tool discovery for all N+ CodeLens commands."
        (_rel("scripts", "mcp_server.py"),
         r"automatic tool discovery for all \d+\+ CodeLens commands",
         "automatic tool discovery for all {cmd} CodeLens commands"),

        # ─── scripts/graph_model.py ──────────────────────────────────
        # L16 (docstring): "All N existing CLI commands continue to work unchanged."
        (_rel("scripts", "graph_model.py"),
         r"All \d+ existing CLI commands continue to work unchanged",
         "All {cmd} existing CLI commands continue to work unchanged"),

        # ─── tests/test_integration.py ───────────────────────────────
        # L2 (module docstring): "Integration smoke tests for all N CodeLens commands."
        # NOTE: the strict sentinel `EXPECTED_COMMAND_COUNT = 64` lower in this
        # file is intentionally NOT touched — that is the test's regression
        # anchor, not a doc.
        (_rel("tests", "test_integration.py"),
         r"Integration smoke tests for all \d+ CodeLens commands",
         "Integration smoke tests for all {cmd} CodeLens commands"),
    ]


# ─── Engine ───────────────────────────────────────────────────────────────


def _format_values() -> Dict[str, str]:
    cmd = get_command_count()
    mcp_total, mcp_static, mcp_dynamic = get_mcp_counts()
    return {
        "cmd": str(cmd),
        "mcp": str(mcp_total),
        "static": str(mcp_static),
        "dynamic": str(mcp_dynamic),
    }


def _apply_rule(content: str, regex: str, template: str, values: Dict[str, str]) -> Tuple[str, int]:
    """Apply one rule to ``content``. Returns (new_content, num_substitutions)."""
    pattern = re.compile(regex, re.MULTILINE)
    replacement = template.format(**values)
    new_content, n = pattern.subn(replacement, content)
    return new_content, n


def sync(apply: bool = False) -> int:
    """Run all sync rules.

    Args:
        apply: If True, write changes to disk. If False, only report drift.

    Returns:
        Number of files that had (or would have) changes.
    """
    values = _format_values()
    rules = _build_rules()
    files_changed = 0
    drift_report: List[str] = []

    # Group rules by file so we read/write each file exactly once.
    by_file: Dict[str, List[Tuple[str, str]]] = {}
    for filepath, regex, template in rules:
        by_file.setdefault(filepath, []).append((regex, template))

    for filepath, file_rules in sorted(by_file.items()):
        if not os.path.exists(filepath):
            drift_report.append(f"  MISSING: {filepath} (skipped)")
            continue
        with open(filepath, "r", encoding="utf-8") as f:
            original = f.read()
        content = original
        rule_hits = 0
        for regex, template in file_rules:
            content, n = _apply_rule(content, regex, template, values)
            rule_hits += n
        if rule_hits == 0:
            # No rule matched — either the file already matches (good) or the
            # regex is stale (bad). We can't tell which, so we just report.
            drift_report.append(f"  NO_MATCH: {filepath} (no rule matched — already in sync, or regex is stale)")
            continue
        if content != original:
            files_changed += 1
            rel_path = os.path.relpath(filepath, _PROJECT_ROOT)
            drift_report.append(f"  DRIFT:    {rel_path} ({rule_hits} substitution(s))")
            if apply:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(content)

    # ─── Report ─────────────────────────────────────────────────────
    cmd = values["cmd"]
    mcp, static, dynamic = get_mcp_counts()
    print(f"Command count (runtime COMMAND_REGISTRY): {cmd}")
    if _MCP_AVAILABLE:
        print(f"MCP tools: {mcp} total = {static} static + {dynamic} dynamic "
              f"(excluded from MCP: {sorted(_MCP_EXCLUDED_COMMANDS)})")
    else:
        print("MCP tools: skipped (mcp_server import failed)")
    print()

    if files_changed == 0:
        print("All documentation files are in sync with COMMAND_REGISTRY.")
        return 0

    print(f"{files_changed} file(s) {'updated' if apply else 'out of sync'}:")
    for line in drift_report:
        print(line)
    if not apply:
        print()
        print("Run `python3 scripts/sync_command_count.py --apply` to fix.")
    return files_changed


# ─── CLI ──────────────────────────────────────────────────────────────────


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Synchronize command/MCP-tool counts in documentation & metadata "
            "with the runtime COMMAND_REGISTRY. Single source of truth for "
            "issue #38."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write the synchronized counts to disk.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Check-only mode (default). Exit 1 if any file would change.",
    )
    args = parser.parse_args(argv)
    return 1 if sync(apply=args.apply) > 0 and not args.apply else 0


if __name__ == "__main__":
    sys.exit(main())
