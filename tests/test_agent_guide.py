"""
Tests for the agent usage guide (`codelens --guide`, issue #319).

The guide must never hand an agent a wrong invocation, so the key guard checks
every task command against the live registry and `_CHECKS`: a renamed or removed
sub-check breaks the test rather than silently misleading an agent.
"""

import importlib
import os
import re
import sys

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from agent_guide import build_guide, _TASKS  # noqa: E402
from commands import get_visible_commands  # noqa: E402


def _parse(run):
    """(umbrella, check) from a task's `run` string; check is None if absent."""
    parts = run.split()
    umbrella = parts[1] if len(parts) > 1 and parts[0] == "codelens" else None
    check = None
    if "--check" in parts:
        i = parts.index("--check")
        if i + 1 < len(parts):
            check = parts[i + 1]
    return umbrella, check


# ─── structure ───────────────────────────────────────────

def test_json_form_is_machine_readable():
    g = build_guide("json")
    assert isinstance(g, dict)
    assert g["tasks"] and g["conventions"] and g["commands"]


def test_text_form_has_tasks_and_conventions():
    text = build_guide("text")
    assert "Tasks" in text
    assert "Conventions" in text
    assert "codelens context" in text


# ─── the guard: guide never lies about invocations ───────

def test_every_task_umbrella_is_a_real_command():
    visible = set(get_visible_commands().keys())
    for t in _TASKS:
        umbrella, _ = _parse(t["run"])
        assert umbrella in visible, f"task '{t['task']}' names unknown command {umbrella}"


def test_every_task_check_exists_in_that_umbrella():
    for t in _TASKS:
        umbrella, check = _parse(t["run"])
        if check is None:
            continue
        mod = importlib.import_module(f"commands.{umbrella.replace('-', '_')}")
        checks = getattr(mod, "_CHECKS", {})
        assert check in checks, (
            f"task '{t['task']}' uses --check {check}, absent from {umbrella}._CHECKS"
        )


# ─── the dogfood traps are documented ────────────────────

def test_search_positional_trap_is_called_out():
    text = build_guide("text").lower()
    assert "search" in text and "positional" in text


def test_trace_domain_hint_is_present():
    text = build_guide("text")
    assert "--domain backend" in text


# ─── checks are live, not hardcoded ──────────────────────

def test_subchecks_are_derived_live():
    g = build_guide("json")
    # `source` and `flow` were added late; they must appear without editing here.
    assert "source" in g["commands"]["context"]["checks"]
    assert "flow" in g["commands"]["context"]["checks"]
    assert "flow-diff" in g["commands"]["impact"]["checks"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
