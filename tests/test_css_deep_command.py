# @WHO:   tests/test_css_deep_command.py
# @WHAT:  Tests for restored css-deep as audit --check css (issue #251)
# @PART:  tests
"""Tests for the css sub-check of the audit umbrella (issue #251).

cssdeep_engine was orphaned in the #195 consolidation (its command entry
point was deleted, the engine kept). This restores access as
`audit --check css` — a sub-check, NOT a new top-level command. These
tests verify the wrapper delegates correctly, the audit umbrella dispatches
`css`, and passthrough filters (severity/category) reach the engine.
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

from commands import css_deep  # noqa: E402
from commands import audit  # noqa: E402


class TestCssDeepCommand:
    def test_execute_delegates_to_engine(self):
        args = argparse.Namespace(workspace=".", severity=None, category=None)
        with mock.patch(
            "commands.css_deep.analyze_css_deep",
            return_value={"status": "ok", "stats": {"total_issues": 3}},
        ) as mock_engine:
            result = css_deep.execute(args, ".")
        mock_engine.assert_called_once_with(".", severity=None, category=None)
        assert result["status"] == "ok"

    def test_severity_and_category_passthrough(self):
        args = argparse.Namespace(workspace=".", severity="high", category="z_index_abuse")
        with mock.patch(
            "commands.css_deep.analyze_css_deep",
            return_value={"status": "ok"},
        ) as mock_engine:
            css_deep.execute(args, ".")
        mock_engine.assert_called_once_with(".", severity="high", category="z_index_abuse")


class TestAuditDispatchesCss:
    def test_css_is_registered_check(self):
        assert "css" in audit.ALL_CHECKS

    def test_audit_check_css_routes_to_engine(self):
        base = argparse.Namespace(
            workspace=".", check="css", severity=None, category=None,
        )
        with mock.patch(
            "commands.css_deep.analyze_css_deep",
            return_value={"status": "ok", "stats": {"total_issues": 7}},
        ):
            result = audit.execute(base, ".")
        # umbrella envelope
        assert result["s"] == "ok"
        assert result["st"]["checks_run"] == 1
        assert result["r"][0]["_check"] == "css"
        assert result["r"][0]["stats"]["total_issues"] == 7

    def test_audit_check_css_severity_reaches_engine(self):
        base = argparse.Namespace(
            workspace=".", check="css", severity="high", category=None,
        )
        with mock.patch(
            "commands.css_deep.analyze_css_deep",
            return_value={"status": "ok"},
        ) as mock_engine:
            audit.execute(base, ".")
        # audit builds a synthetic namespace; the engine must receive the filter
        _, kwargs = mock_engine.call_args
        assert kwargs.get("severity") == "high"
