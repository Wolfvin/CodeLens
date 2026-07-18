# @WHO:   scripts/agent_guide.py
# @WHAT:  Task-oriented usage guide for agents (`codelens --guide`)
# @PART:  cli
# @ENTRY: build_guide()
"""The guide a new agent reads to use CodeLens without guessing.

`codelens --help` lists commands; this answers "I want to do X — what do I
run?" with copy-paste examples, spells out the positional conventions, and
bakes in the traps found by dogfooding (search's pattern positional, trace's
--domain backend). Sub-checks are derived live from each umbrella's `_CHECKS`
so the guide can't drift from the code.
"""

import importlib
import json
from typing import Any, Dict, List


# Task → command. Intent can't be derived from the registry, so this is
# curated — but every command here is a real, tested invocation. `<ws>` is the
# workspace path (auto-detected if omitted); `FN` a function name.
_TASKS: List[Dict[str, str]] = [
    {"task": "Orient in an unfamiliar codebase",
     "run": "codelens context <ws>"},
    {"task": "Who calls this function (callers)",
     "run": "codelens context <ws> --check trace --name FN --direction up --domain backend"},
    {"task": "What does this function call (callees)",
     "run": "codelens context <ws> --check trace --name FN --direction down --domain backend"},
    {"task": "Read one function's source (skip reading the whole file)",
     "run": "codelens context <ws> --check source --name FN"},
    {"task": "Blast radius before changing a symbol",
     "run": "codelens impact <ws> --name FN"},
    {"task": "A file's structure (functions/classes)",
     "run": "codelens context <ws> --check outline --file path/to/file.py"},
    {"task": "Find a symbol by name",
     "run": "codelens search FN --mode symbol",
     "note": "PATTERN is the first positional (workspace optional second): "
             "`codelens search FN [<ws>] --mode symbol` — the reverse of every "
             "other command."},
    {"task": "Regex / full-text search",
     "run": "codelens search 'PATTERN' --mode regex"},
    {"task": "Find dead code",
     "run": "codelens audit <ws> --check dead-code"},
    {"task": "Collect a named @FLOW's scattered functions",
     "run": "codelens context <ws> --check flow --name FLOW_NAME"},
    {"task": "Did a named flow's shape change between two snapshots",
     "run": "codelens impact <ws> --check flow-diff --name FLOW_NAME"},
    {"task": "Audit @FLOW/@ENTRY doc-tags & coverage",
     "run": "codelens context <ws> --check tags"},
    {"task": "Circular dependencies",
     "run": "codelens deps <ws> --check circular"},
    {"task": "Scan / (re)build the graph for a workspace",
     "run": "codelens scan <ws>"},
    {"task": "Scan for secrets",
     "run": "codelens security <ws> --check secrets"},
]

_CONVENTIONS = [
    "Most commands take the workspace as the first positional: "
    "`codelens <command> <workspace> [--check X] [--name Y]`.",
    "EXCEPTION — `search` is `codelens search <pattern> [<workspace>] "
    "--mode symbol|regex|semantic|graph`: the PATTERN is the first positional, "
    "the workspace an optional second (not the other way round).",
    "Add `--format json` (structured) or `--format compact` (token-lean) for "
    "machine parsing; the default is human-readable.",
    "`trace` and `context --check context` resolve backend symbols best with "
    "`--domain backend` (the default `auto` can miss them).",
    "On a CLI argument error with a machine format, the error is printed to "
    "stdout as `{\"s\":\"error\",...}` — so an empty result is a real empty, "
    "not a hidden error.",
    "Run `scan` once so graph-backed checks (impact, trace, flow subgraph, "
    "source-by-name) have data; they degrade gracefully without it.",
]

# Umbrellas whose sub-checks come from a `_CHECKS` dict, plus the odd ones out.
_UMBRELLAS = ["context", "impact", "audit", "deps", "security", "api_map"]
_NON_CHECK = {
    "search": "modes: semantic (default) | symbol | regex | graph "
              "(via --mode; pattern is positional)",
    "summary": "workspace summary (no --check)",
    "scan": "build/refresh the registry (no --check)",
    "doctor": "environment audit (no --check)",
    "history": "historical trend data (no --check)",
    "graph": "raw Cypher-subset query (power-user)",
}


def _live_checks() -> Dict[str, List[str]]:
    """Sub-checks per umbrella, read straight from the code."""
    out: Dict[str, List[str]] = {}
    for name in _UMBRELLAS:
        try:
            mod = importlib.import_module(f"commands.{name}")
            checks = getattr(mod, "_CHECKS", None)
            if checks:
                out[name.replace("_", "-")] = list(checks.keys())
        except Exception:
            continue
    return out


def build_guide(fmt: str = "text") -> Any:
    """The agent usage guide. Returns a dict for machine formats, else text."""
    checks = _live_checks()
    guide = {
        "tool": "codelens",
        "how_to_read": "Find your task below and run the command; replace "
                       "<ws>/FN/FLOW_NAME with your values.",
        "conventions": _CONVENTIONS,
        "tasks": _TASKS,
        "commands": {
            **{u: {"checks": c} for u, c in checks.items()},
            **{u: {"note": n} for u, n in _NON_CHECK.items()},
        },
    }

    if fmt in ("json", "compact", "ai", "sarif", "graphml", "junit-xml", "gitlab-sast"):
        return guide

    return _render_text(guide)


def _render_text(guide: Dict) -> str:
    lines = ["# CodeLens — agent guide", "", guide["how_to_read"], "",
             "## Conventions"]
    for c in guide["conventions"]:
        lines.append(f"- {c}")
    lines += ["", "## Tasks → commands"]
    for t in guide["tasks"]:
        lines.append(f"- {t['task']}:")
        lines.append(f"    {t['run']}")
        if t.get("note"):
            lines.append(f"    note: {t['note']}")
    lines += ["", "## Commands & sub-checks"]
    for cmd, info in guide["commands"].items():
        if "checks" in info:
            lines.append(f"- {cmd}: --check " + " | ".join(info["checks"]))
        else:
            lines.append(f"- {cmd}: {info['note']}")
    return "\n".join(lines)
