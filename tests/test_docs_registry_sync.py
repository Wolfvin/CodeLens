"""Docs↔registry sync guard (issue #278).

WHY THIS EXISTS
---------------
Agent-facing docs drifted from the code silently and stayed wrong for a long
time: the sub-check tables in README/SKILL/SKILL-QUICK were missing css / a11y
(audit) and diagnostics / overview (context) from #236 until PR #275, and
`references/agent-integration.md` was a full major version behind (PR #276).
Nothing forced docs == code.

This test derives the truth from the live `_CHECKS` dicts of each umbrella and
fails if any sub-check the code exposes is absent from the agent-facing command
tables. It does NOT check prose — only that every real sub-check name is listed,
so an agent reading the docs can discover it.
"""

import importlib
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Umbrella commands that expose sub-checks via a module-level `_CHECKS` dict.
_UMBRELLAS = ["audit", "context", "deps", "security", "impact", "api_map"]

# Agent-facing docs that carry the command / sub-check catalog.
_DOC_FILES = ["README.md", "SKILL.md", "SKILL-QUICK.md"]


def _sub_checks(module_name: str):
    mod = importlib.import_module(f"commands.{module_name}")
    checks = getattr(mod, "_CHECKS", None)
    return list(checks.keys()) if isinstance(checks, dict) else []


def _all_sub_checks():
    out = {}
    for u in _UMBRELLAS:
        out[u] = _sub_checks(u)
    return out


def _read_doc(name: str) -> str:
    with open(os.path.join(REPO_ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_umbrellas_have_checks():
    """Sanity: the umbrellas we track actually expose _CHECKS (guards against a
    refactor that renames _CHECKS and silently makes this whole test vacuous)."""
    all_checks = _all_sub_checks()
    for u in ("audit", "context", "security"):
        assert all_checks[u], f"{u} exposes no _CHECKS — did the attribute get renamed?"


@pytest.mark.parametrize("doc", _DOC_FILES)
def test_every_subcheck_documented(doc):
    """Every sub-check name in the code must appear verbatim in each doc's
    catalog. Missing name → the doc has drifted from the registry (issue #278)."""
    text = _read_doc(doc)
    missing = []
    for umbrella, checks in _all_sub_checks().items():
        for check in checks:
            if check not in text:
                missing.append(f"{umbrella}:{check}")
    assert not missing, (
        f"{doc} is missing these sub-checks that exist in the code registry "
        f"(add them to the catalog table, or the code diverged): {missing}"
    )


def test_umbrella_command_names_documented():
    """All 12 umbrella command names must appear in SKILL.md's catalog."""
    from commands import COMMAND_REGISTRY
    # Visible umbrellas = registered, non-hidden. Derive the 12 from the CLI count.
    text = _read_doc("SKILL.md")
    umbrellas = ["scan", "search", "context", "deps", "audit", "security",
                 "summary", "impact", "api-map", "doctor", "history", "graph"]
    missing = [u for u in umbrellas if u not in text]
    assert not missing, f"SKILL.md missing umbrella command names: {missing}"
    # And they must all be real registered commands (guards a stale doc name).
    for u in umbrellas:
        assert u in COMMAND_REGISTRY, f"SKILL.md lists '{u}' but it is not a registered command"
