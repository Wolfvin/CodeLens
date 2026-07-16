# @WHO:   tests/test_a11y_command.py
# @WHAT:  Tests for restored a11y as audit --check a11y (issue #256)
# @PART:  tests
"""Tests for the a11y sub-check of the audit umbrella (issue #256).

a11y_engine was orphaned in the #195 consolidation (its command entry
point was deleted, the engine kept) — the same situation as css-deep
(#251) and export-snapshot (#218). This restores access as
`audit --check a11y` — a sub-check, NOT a new top-level command.
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

from commands import a11y  # noqa: E402
from commands import audit  # noqa: E402


class TestA11yCommand:
    def test_execute_delegates_to_engine(self):
        args = argparse.Namespace(workspace=".", severity=None, category=None)
        with mock.patch(
            "commands.a11y.audit_accessibility",
            return_value={"status": "ok", "stats": {"total_issues": 3}},
        ) as mock_engine:
            result = a11y.execute(args, ".")
        mock_engine.assert_called_once_with(".", category=None, severity=None)
        assert result["status"] == "ok"

    def test_severity_and_category_passthrough(self):
        args = argparse.Namespace(workspace=".", severity="high", category="missing_alt")
        with mock.patch(
            "commands.a11y.audit_accessibility",
            return_value={"status": "ok"},
        ) as mock_engine:
            a11y.execute(args, ".")
        mock_engine.assert_called_once_with(".", category="missing_alt", severity="high")


class TestAuditDispatchesA11y:
    def test_a11y_is_registered_check(self):
        assert "a11y" in audit.ALL_CHECKS

    def test_audit_check_a11y_routes_to_engine(self):
        base = argparse.Namespace(
            workspace=".", check="a11y", severity=None, category=None,
        )
        with mock.patch(
            "commands.a11y.audit_accessibility",
            return_value={"status": "ok", "stats": {"total_issues": 9}},
        ):
            result = audit.execute(base, ".")
        assert result["s"] == "ok"
        assert result["st"]["checks_run"] == 1
        assert result["r"][0]["_check"] == "a11y"
        assert result["r"][0]["stats"]["total_issues"] == 9

    def test_audit_check_a11y_category_reaches_engine(self):
        base = argparse.Namespace(
            workspace=".", check="a11y", severity=None, category="missing_label",
        )
        with mock.patch(
            "commands.a11y.audit_accessibility",
            return_value={"status": "ok"},
        ) as mock_engine:
            audit.execute(base, ".")
        _, kwargs = mock_engine.call_args
        assert kwargs.get("category") == "missing_label"

    def test_css_and_a11y_both_registered_independently(self):
        """Regression guard: a11y was added alongside the existing css
        sub-check (#251) — both must coexist, neither shadowing the other."""
        assert "css" in audit.ALL_CHECKS
        assert "a11y" in audit.ALL_CHECKS
        assert audit._CHECKS["a11y"]["module"] == "commands.a11y"
        assert audit._CHECKS["css"]["module"] == "commands.css_deep"
