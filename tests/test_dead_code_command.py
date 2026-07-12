"""Tests for the dead-code command's deletion_safety cross-check (issue #238).

`audit --check dead-code` previously reported `status: dead` from the
registry with no signal about whether a finding is actually safe to delete
— an agent had to manually chain a separate `context --check trace
--direction up` call per finding to check for entry points. This wires
`impact_engine.analyze_impact(action="delete")` (which already computes
exactly this signal) directly into the dead-code command output.
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

from commands import dead_code  # noqa: E402


def _base_args(**overrides):
    ns = argparse.Namespace(
        workspace=".",
        categories=None,
        max_files=3000,
        max_results=100,
        verify_impact=True,
        verify_impact_limit=20,
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    return ns


def _fake_dead_code_result():
    return {
        "status": "ok",
        "stats": {"total_dead_code": 2},
        "results": {
            "unused_exports": [
                {"file": "AdGate.tsx", "line": 39, "name": "AdGate", "type": "default_export"},
            ],
            "registry_dead": [
                {"file": "utils.ts", "line": 10, "name": "reallyUnusedHelper", "type": "function"},
            ],
        },
    }


class TestDeletionSafetyCrossCheck:
    def test_high_risk_symbol_flagged_entry_point_likely(self):
        """A dead-code finding that analyze_impact reports as high-risk
        (real dependents exist) must not be silently labeled safe."""
        with mock.patch("commands.dead_code.detect_dead_code", return_value=_fake_dead_code_result()), \
             mock.patch("hybrid_engine.create_hybrid_engine", side_effect=ImportError), \
             mock.patch(
                "impact_engine.analyze_impact",
                side_effect=lambda name, ws, **kw: {
                    "risk": "high" if name == "AdGate" else "low",
                    "stats": {"direct_dependents": 6 if name == "AdGate" else 0},
                },
            ):
            result = dead_code.execute(_base_args(), ".")

        items_by_name = {
            item["name"]: item
            for cat in result["results"].values()
            for item in cat
        }
        assert items_by_name["AdGate"]["deletion_safety"] == "entry_point_likely"
        assert items_by_name["reallyUnusedHelper"]["deletion_safety"] == "safe"

    def test_no_verify_impact_flag_skips_cross_check(self):
        """--no-verify-impact must not call analyze_impact at all."""
        with mock.patch("commands.dead_code.detect_dead_code", return_value=_fake_dead_code_result()), \
             mock.patch("hybrid_engine.create_hybrid_engine", side_effect=ImportError), \
             mock.patch("impact_engine.analyze_impact") as mock_analyze:
            result = dead_code.execute(_base_args(verify_impact=False), ".")

        mock_analyze.assert_not_called()
        for cat in result["results"].values():
            for item in cat:
                assert "deletion_safety" not in item

    def test_verify_impact_limit_caps_calls(self):
        """Only the first N findings (across all categories combined) are
        cross-checked, to bound cost on large dead-code result sets."""
        many_findings = {
            "status": "ok",
            "stats": {"total_dead_code": 10},
            "results": {
                "unused_exports": [
                    {"file": f"f{i}.ts", "line": i, "name": f"fn{i}", "type": "function"}
                    for i in range(10)
                ],
            },
        }
        with mock.patch("commands.dead_code.detect_dead_code", return_value=many_findings), \
             mock.patch("hybrid_engine.create_hybrid_engine", side_effect=ImportError), \
             mock.patch(
                "impact_engine.analyze_impact",
                return_value={"risk": "low", "stats": {}},
            ) as mock_analyze:
            dead_code.execute(_base_args(verify_impact_limit=3), ".")

        assert mock_analyze.call_count == 3

    def test_analyze_impact_failure_does_not_crash_command(self):
        """If analyze_impact raises for a given symbol, the command must
        still return successfully with an 'unknown' safety label — not
        propagate the exception and break the whole dead-code report."""
        with mock.patch("commands.dead_code.detect_dead_code", return_value=_fake_dead_code_result()), \
             mock.patch("hybrid_engine.create_hybrid_engine", side_effect=ImportError), \
             mock.patch("impact_engine.analyze_impact", side_effect=RuntimeError("boom")):
            result = dead_code.execute(_base_args(), ".")

        assert result["status"] == "ok"
        for cat in result["results"].values():
            for item in cat:
                assert item["deletion_safety"] == "unknown"
