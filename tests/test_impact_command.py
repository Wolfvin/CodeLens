"""Tests for the impact command's --action rename support (issue #241).

`impact_engine.analyze_impact(action="delete"|"modify")` already computed
most of what a "safe to change" sandbox needs — this extends it to rename,
the most common refactor an AI agent performs, by attaching a concrete
checklist of every statically-resolved call site that needs updating to
the new name, plus an explicit caveat about what's NOT covered (dynamic/
string-based references).
"""

import argparse
import os
import sys
from unittest import mock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from commands.impact import _run_legacy_impact  # noqa: E402


def _args(**overrides):
    ns = argparse.Namespace(
        name="oldName", action="modify", domain="auto", depth=None, new_name=None,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _fake_analyze_impact_result():
    return {
        "status": "ok",
        "symbol": "oldName",
        "action": "rename",
        "risk": "medium",
        "affected": {
            "direct": [
                {"name": "callerA", "file": "a.ts", "line": 10},
                {"name": "callerB", "file": "b.ts", "line": 22},
            ],
            "indirect": [],
            "files": ["a.ts", "b.ts"],
            "tests": [],
        },
        "stats": {
            "direct_dependents": 2,
            "indirect_dependents": 0,
            "affected_files": 2,
            "test_files_found": 0,
        },
    }


class TestRenameAction:
    def test_rename_without_new_name_errors(self):
        result = _run_legacy_impact(_args(action="rename"), ".")
        assert result["status"] == "error"
        assert "--new-name" in result["error"]

    def test_rename_with_new_name_produces_checklist(self):
        with mock.patch(
            "impact_engine.analyze_impact",
            return_value=_fake_analyze_impact_result(),
        ):
            result = _run_legacy_impact(
                _args(action="rename", new_name="newName"), "."
            )

        assert result["status"] == "ok"
        assert result["new_name"] == "newName"
        assert len(result["rename_checklist"]) == 2
        assert result["rename_checklist"][0] == {
            "file": "a.ts", "line": 10, "caller": "callerA",
        }
        assert "dynamic" in result["rename_caveat"]
        assert "rename_checklist" in result["recommendations"][0]

    def test_modify_action_unaffected_by_rename_logic(self):
        """--action modify (the default) must not get rename_checklist or
        the rename-specific error path — regression guard for the new
        branching added alongside rename support."""
        with mock.patch(
            "impact_engine.analyze_impact",
            return_value={
                "status": "ok", "risk": "low",
                "affected": {"direct": [], "indirect": [], "files": [], "tests": []},
                "stats": {"direct_dependents": 0, "indirect_dependents": 0,
                          "affected_files": 0, "test_files_found": 0},
            },
        ):
            result = _run_legacy_impact(_args(action="modify"), ".")

        assert "rename_checklist" not in result
        assert "new_name" not in result
