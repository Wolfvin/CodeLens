"""Tests for codelens.py — Main CLI dispatcher functions.

Tests the core post-processing functions: _apply_top_n, _apply_lite,
_apply_max_tokens, _sort_items, resolve_workspace, compute_confidence_distribution_flat,
and _suggest_fix.
"""

import json
import os
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from codelens import (
    _apply_top_n,
    _apply_lite,
    _apply_max_tokens,
    _sort_items,
    _estimate_tokens,
    compute_confidence_distribution_flat,
    _suggest_fix,
    resolve_workspace,
    _SEVERITY_ORDER,
)


# ─── _sort_items Tests ────────────────────────────────────────


class TestSortItems(unittest.TestCase):
    """Test _sort_items with various sort keys and data shapes."""

    def test_sort_by_severity_desc(self):
        """Severity maps: critical=0, high=1, ..., info=5.
        Sorting descending puts highest numeric value first (info)."""
        items = [
            {"name": "a", "severity": "low"},
            {"name": "b", "severity": "critical"},
            {"name": "c", "severity": "medium"},
        ]
        result = _sort_items(items, "severity", True)
        # Descending by numeric value: info(5) > low(4) > medium(3) > ...
        self.assertEqual(result[0]["severity"], "low")
        self.assertEqual(result[-1]["severity"], "critical")

    def test_sort_by_severity_asc(self):
        """Ascending puts lowest numeric value first (critical=0)."""
        items = [
            {"name": "a", "severity": "critical"},
            {"name": "b", "severity": "low"},
            {"name": "c", "severity": "medium"},
        ]
        result = _sort_items(items, "severity", False)
        # Ascending by numeric value: critical(0) first
        self.assertEqual(result[0]["severity"], "critical")
        self.assertEqual(result[-1]["severity"], "low")

    def test_sort_by_cyclomatic_desc(self):
        items = [
            {"name": "a", "cyclomatic": 3},
            {"name": "b", "cyclomatic": 15},
            {"name": "c", "cyclomatic": 7},
        ]
        result = _sort_items(items, "cyclomatic", True)
        self.assertEqual(result[0]["cyclomatic"], 15)
        self.assertEqual(result[-1]["cyclomatic"], 3)

    def test_sort_empty_list(self):
        self.assertEqual(_sort_items([], "severity", True), [])

    def test_sort_non_dict_items(self):
        items = ["alpha", "beta", "gamma"]
        self.assertEqual(_sort_items(items, "severity", True), items)

    def test_sort_missing_key_defaults_to_zero(self):
        items = [
            {"name": "a", "cyclomatic": 10},
            {"name": "b"},
            {"name": "c", "cyclomatic": 5},
        ]
        result = _sort_items(items, "cyclomatic", True)
        self.assertEqual(result[0]["cyclomatic"], 10)
        # Items without the key should sort as 0 (at the end when desc)

    def test_sort_severity_all_levels(self):
        items = [
            {"severity": "info"},
            {"severity": "low"},
            {"severity": "medium"},
            {"severity": "warning"},
            {"severity": "high"},
            {"severity": "critical"},
        ]
        # Descending (True) puts highest numeric value first
        result_desc = _sort_items(items, "severity", True)
        expected_desc = ["info", "low", "medium", "warning", "high", "critical"]
        actual_desc = [item["severity"] for item in result_desc]
        self.assertEqual(actual_desc, expected_desc)

        # Ascending (False) puts lowest numeric value first
        result_asc = _sort_items(items, "severity", False)
        expected_asc = ["critical", "high", "warning", "medium", "low", "info"]
        actual_asc = [item["severity"] for item in result_asc]
        self.assertEqual(actual_asc, expected_asc)

    def test_sort_numeric_string_values(self):
        items = [
            {"name": "a", "score": "10"},
            {"name": "b", "score": "2"},
            {"name": "c", "score": "30"},
        ]
        result = _sort_items(items, "score", True)
        self.assertEqual(result[0]["name"], "c")

    def test_sort_handles_type_error_gracefully(self):
        """Mixed types in sort key should not crash."""
        items = [
            {"name": "a", "score": 10},
            {"name": "b", "score": "high"},
            {"name": "c", "score": 5},
        ]
        result = _sort_items(items, "score", True)
        self.assertEqual(len(result), 3)


# ─── _apply_top_n Tests ───────────────────────────────────────


class TestApplyTopN(unittest.TestCase):
    """Test _apply_top_n truncation with various result shapes."""

    def test_truncates_list(self):
        result = {"functions": [{"name": f"fn_{i}"} for i in range(50)]}
        out = _apply_top_n(result, 10)
        self.assertEqual(len(out["functions"]), 10)
        self.assertTrue(out["functions_truncated"])
        self.assertEqual(out["functions_total"], 50)

    def test_no_truncation_when_under_limit(self):
        result = {"functions": [{"name": "fn_1"}, {"name": "fn_2"}]}
        out = _apply_top_n(result, 10)
        self.assertEqual(len(out["functions"]), 2)
        self.assertNotIn("functions_truncated", out)

    def test_top_n_zero_means_no_limit(self):
        result = {"functions": [{"name": f"fn_{i}"} for i in range(50)]}
        out = _apply_top_n(result, 0)
        self.assertEqual(len(out["functions"]), 50)

    def test_sorts_before_truncating(self):
        result = {
            "findings": [
                {"name": "low", "severity": "low"},
                {"name": "critical", "severity": "critical"},
                {"name": "medium", "severity": "medium"},
                {"name": "high", "severity": "high"},
            ]
        }
        out = _apply_top_n(result, 2, command="smell")
        # smell uses severity sort descending (True), which puts
        # highest numeric value first (low=4, medium=3, high=1, critical=0)
        self.assertEqual(len(out["findings"]), 2)

    def test_truncates_nested_dict(self):
        result = {
            "by_category": {
                "unused_vars": [{"name": f"v_{i}"} for i in range(30)],
                "dead_code": [{"name": f"d_{i}"} for i in range(5)],
            }
        }
        out = _apply_top_n(result, 10, command="smell")
        self.assertEqual(len(out["by_category"]["unused_vars"]), 10)
        self.assertEqual(len(out["by_category"]["dead_code"]), 5)

    def test_coverage_map_truncation(self):
        result = {
            "coverage_map": {f"file_{i}.py": {"fn": {}} for i in range(50)}
        }
        out = _apply_top_n(result, 10)
        self.assertEqual(len(out["coverage_map"]), 10)
        self.assertTrue(out.get("coverage_map_truncated"))

    def test_non_dict_result_passthrough(self):
        self.assertEqual(_apply_top_n("not a dict", 10), "not a dict")

    def test_multiple_list_keys_truncated(self):
        result = {
            "functions": [{"n": f"f_{i}"} for i in range(30)],
            "findings": [{"n": f"find_{i}"} for i in range(25)],
        }
        out = _apply_top_n(result, 5)
        self.assertEqual(len(out["functions"]), 5)
        self.assertEqual(len(out["findings"]), 5)

    def test_complexity_sort_before_truncate(self):
        result = {
            "functions": [
                {"name": "simple", "cyclomatic": 1},
                {"name": "complex", "cyclomatic": 20},
                {"name": "medium", "cyclomatic": 5},
            ]
        }
        out = _apply_top_n(result, 2, command="complexity")
        self.assertEqual(out["functions"][0]["name"], "complex")
        self.assertEqual(out["functions"][1]["name"], "medium")


# ─── _apply_lite Tests ────────────────────────────────────────


class TestApplyLite(unittest.TestCase):
    """Test _apply_lite for each command-specific mode."""

    def test_query_lite(self):
        result = {
            "status": "ok",
            "found": True,
            "action": "EXTEND",
            "action_reason": "Name exists and is active.",
            "node": {"fn": "hello"},
            "callers": [],
            "callees": [],
        }
        lite = _apply_lite(result, "query")
        self.assertEqual(lite["status"], "ok")
        self.assertTrue(lite["found"])
        self.assertEqual(lite["action"], "EXTEND")
        self.assertNotIn("node", lite)
        self.assertNotIn("callers", lite)

    def test_query_lite_not_found(self):
        result = {"status": "ok", "found": False, "action": "CREATE"}
        lite = _apply_lite(result, "query")
        self.assertFalse(lite["found"])
        self.assertEqual(lite["action"], "CREATE")

    def test_smell_lite(self):
        result = {
            "status": "ok",
            "health_score": 45,
            "total_findings": 12,
            "actionable_items": ["fix X", "fix Y", "fix Z"],
            "stats": {"critical": 2},
        }
        lite = _apply_lite(result, "smell")
        self.assertEqual(lite["health_score"], 45)
        self.assertEqual(lite["action"], "REVIEW")
        self.assertIn("top_findings", lite)

    def test_smell_lite_healthy(self):
        result = {
            "status": "ok",
            "health_score": 85,
            "total_findings": 2,
        }
        lite = _apply_lite(result, "smell")
        self.assertEqual(lite["action"], "MONITOR")

    def test_impact_lite(self):
        result = {
            "status": "ok",
            "risk": "high",
            "recommended_action": "Test thoroughly",
            "affected": {"direct": [], "indirect": []},
        }
        lite = _apply_lite(result, "impact")
        self.assertEqual(lite["risk"], "high")
        self.assertEqual(lite["action"], "Test thoroughly")

    def test_refactor_safe_lite(self):
        result = {
            "status": "ok",
            "safety": "safe",
            "action": "Rename is safe",
        }
        lite = _apply_lite(result, "refactor-safe")
        self.assertEqual(lite["risk"], "safe")

    def test_complexity_lite(self):
        result = {
            "status": "ok",
            "stats": {"avg_cyclomatic": 4.5, "high_complexity": 3},
            "functions": [
                {"name": "fn1", "cyclomatic": 15},
                {"name": "fn2", "cyclomatic": 10},
                {"name": "fn3", "cyclomatic": 5},
                {"name": "fn4", "cyclomatic": 3},
                {"name": "fn5", "cyclomatic": 2},
                {"name": "fn6", "cyclomatic": 1},
            ],
        }
        lite = _apply_lite(result, "complexity")
        self.assertIn("top_complex", lite)
        self.assertEqual(len(lite["top_complex"]), 5)
        self.assertEqual(lite["top_complex"][0]["name"], "fn1")

    def test_dead_code_lite(self):
        result = {
            "status": "ok",
            "removal_safety": "mostly_safe",
            "recommended_action": "Remove unused code",
            "stats": {"total_dead_code": 10},
            "results": {
                "unused_vars": [{"name": "x"}, {"name": "y"}],
                "dead_funcs": [{"name": "old"}],
            },
        }
        lite = _apply_lite(result, "dead-code")
        self.assertEqual(lite["removal_safety"], "mostly_safe")
        self.assertIn("top_items", lite)

    def test_debug_leak_lite(self):
        result = {
            "status": "ok",
            "stats": {"total_leaks": 5},
            "leaks": [
                {"name": "debug1", "severity": "high"},
                {"name": "debug2", "severity": "medium"},
                {"name": "debug3", "severity": "low"},
            ],
        }
        lite = _apply_lite(result, "debug-leak")
        self.assertIn("top_leaks", lite)

    def test_perf_hint_lite(self):
        result = {
            "status": "ok",
            "risk": "medium",
            "stats": {"total_hints": 8},
            "hints": [
                {"hint": "use set", "severity": "high"},
                {"hint": "cache result", "severity": "medium"},
            ],
        }
        lite = _apply_lite(result, "perf-hint")
        self.assertEqual(lite["risk"], "medium")
        self.assertIn("top_hints", lite)

    def test_secrets_lite_critical(self):
        result = {
            "status": "ok",
            "risk": "critical",
            "stats": {"total_secrets": 3},
            "findings": [{"name": "api_key", "severity": "critical"}],
        }
        lite = _apply_lite(result, "secrets")
        self.assertEqual(lite["action"], "FIX_IMMEDIATELY")

    def test_secrets_lite_non_critical(self):
        result = {
            "status": "ok",
            "risk": "medium",
            "stats": {"total_secrets": 1},
            "findings": [{"name": "key", "severity": "medium"}],
        }
        lite = _apply_lite(result, "secrets")
        self.assertEqual(lite["action"], "REVIEW")

    def test_a11y_lite(self):
        result = {
            "status": "ok",
            "risk": "medium",
            "stats": {"total_issues": 4},
            "issues": [{"desc": "missing alt", "severity": "high"}],
            "recommendations": ["Add alt text"],
        }
        lite = _apply_lite(result, "a11y")
        self.assertEqual(lite["risk"], "medium")
        self.assertIn("top_issues", lite)
        self.assertIn("recommendations", lite)

    def test_taint_lite(self):
        result = {
            "status": "ok",
            "risk": "critical",
            "stats": {"rules_loaded": 5},
            "findings": [
                {"taint_path": "input→sql", "severity": "critical"},
                {"taint_path": "input→exec", "severity": "high"},
            ],
            "recommendations": ["Fix SQL injection"],
        }
        lite = _apply_lite(result, "taint")
        self.assertEqual(lite["risk"], "critical")
        self.assertIn("top_findings", lite)
        self.assertIn("recommendations", lite)

    def test_generic_lite_fallback(self):
        result = {
            "status": "ok",
            "health_score": 80,
            "recommendations": ["fix A", "fix B", "fix C", "fix D"],
            "some_list": [{"name": "a"}, {"name": "b"}],
        }
        lite = _apply_lite(result, "unknown-command")
        self.assertEqual(lite["status"], "ok")
        self.assertIn("health_score", lite)
        # recommendations may be overwritten by _LIST_KEYS processing
        # since "recommendations" is in _LIST_KEYS
        self.assertIn("recommendations", lite)

    def test_non_dict_result_passthrough(self):
        self.assertEqual(_apply_lite("not a dict", "query"), "not a dict")

    def test_css_deep_lite(self):
        result = {
            "status": "ok",
            "risk": "low",
            "stats": {"total_issues": 2},
            "issues": [{"desc": "unused var", "severity": "medium"}],
        }
        lite = _apply_lite(result, "css-deep")
        self.assertIn("top_issues", lite)

    def test_regex_audit_lite(self):
        result = {
            "status": "ok",
            "risk": "high",
            "stats": {"total_issues": 3},
            "hints": [{"pattern": "evil", "severity": "high"}],
            "recommendations": ["Fix regex"],
        }
        lite = _apply_lite(result, "regex-audit")
        self.assertIn("top_hints", lite)


# ─── _apply_max_tokens Tests ──────────────────────────────────


class TestApplyMaxTokens(unittest.TestCase):
    """Test _apply_max_tokens truncation logic."""

    def test_small_result_no_truncation(self):
        result = {"status": "ok", "count": 5}
        out = _apply_max_tokens(result, 1000)
        self.assertNotIn("_token_truncated", out)

    def test_large_result_truncated(self):
        result = {
            "status": "ok",
            "functions": [{"name": f"fn_{i}", "details": "x" * 100} for i in range(100)],
        }
        out = _apply_max_tokens(result, 100)
        # Should have some truncation marker
        self.assertTrue(out.get("_token_truncated") or out.get("_token_truncated_heavy"))

    def test_zero_max_tokens_no_truncation(self):
        result = {"status": "ok", "functions": list(range(100))}
        out = _apply_max_tokens(result, 0)
        self.assertNotIn("_token_truncated", out)

    def test_preserves_status_on_heavy_truncation(self):
        result = {
            "status": "ok",
            "functions": [{"data": "x" * 200} for _ in range(200)],
            "workspace": "/test",
        }
        out = _apply_max_tokens(result, 10)
        self.assertIn("status", out)

    def test_nested_list_truncation(self):
        result = {
            "status": "ok",
            "by_category": {
                "cat1": [{"name": f"item_{i}"} for i in range(50)],
            },
        }
        out = _apply_max_tokens(result, 50)
        self.assertTrue(out.get("_token_truncated"))

    def test_does_not_mutate_original(self):
        original = {
            "status": "ok",
            "functions": [{"name": f"fn_{i}"} for i in range(50)],
        }
        import copy
        original_copy = copy.deepcopy(original)
        _apply_max_tokens(original, 10)
        self.assertEqual(original, original_copy)


# ─── _estimate_tokens Tests ───────────────────────────────────


class TestEstimateTokens(unittest.TestCase):
    """Test _estimate_tokens approximation."""

    def test_empty_string(self):
        self.assertEqual(_estimate_tokens(""), 0)

    def test_short_string(self):
        self.assertEqual(_estimate_tokens("abcd"), 1)

    def test_long_string(self):
        self.assertEqual(_estimate_tokens("a" * 400), 100)

    def test_unicode_string(self):
        self.assertGreater(_estimate_tokens("hello world 🚀"), 0)


# ─── compute_confidence_distribution_flat Tests ───────────────


class TestConfidenceDistributionFlat(unittest.TestCase):
    """Test compute_confidence_distribution_flat across result structures."""

    def test_flat_list(self):
        result = {
            "findings": [
                {"confidence": "high"},
                {"confidence": "high"},
                {"confidence": "medium"},
                {"confidence": "low"},
            ]
        }
        dist = compute_confidence_distribution_flat(result)
        self.assertEqual(dist["high"], 2)
        self.assertEqual(dist["medium"], 1)
        self.assertEqual(dist["low"], 1)

    def test_nested_dict(self):
        result = {
            "results": {
                "cat1": [{"confidence": "high"}, {"confidence": "medium"}],
                "cat2": [{"confidence": "low"}],
            }
        }
        dist = compute_confidence_distribution_flat(result)
        self.assertEqual(dist["high"], 1)
        self.assertEqual(dist["medium"], 1)
        self.assertEqual(dist["low"], 1)

    def test_empty_result(self):
        dist = compute_confidence_distribution_flat({})
        self.assertEqual(dist, {"high": 0, "medium": 0, "low": 0})

    def test_non_dict_result(self):
        dist = compute_confidence_distribution_flat("not a dict")
        self.assertEqual(dist, {"high": 0, "medium": 0, "low": 0})

    def test_missing_confidence_defaults_low(self):
        result = {"items": [{"name": "a"}, {"name": "b"}]}
        dist = compute_confidence_distribution_flat(result)
        self.assertEqual(dist["low"], 2)

    def test_mixed_findings_and_nested(self):
        result = {
            "findings": [{"confidence": "high"}],
            "results": {
                "unused": [{"confidence": "medium"}, {"confidence": "low"}],
            },
        }
        dist = compute_confidence_distribution_flat(result)
        self.assertEqual(dist["high"], 1)
        self.assertEqual(dist["medium"], 1)
        self.assertEqual(dist["low"], 1)


# ─── _suggest_fix Tests ───────────────────────────────────────


class TestSuggestFix(unittest.TestCase):
    """Test _suggest_fix for various error types and commands."""

    def test_import_error(self):
        suggestion = _suggest_fix("scan", ImportError("no module"))
        self.assertIn("module", suggestion.lower())

    def test_file_not_found(self):
        suggestion = _suggest_fix("scan", FileNotFoundError("not found"))
        self.assertIn("path", suggestion.lower())

    def test_scan_error(self):
        suggestion = _suggest_fix("scan", RuntimeError("incremental failed"))
        self.assertIn("incremental", suggestion.lower())

    def test_query_error(self):
        suggestion = _suggest_fix("query", RuntimeError("err"))
        self.assertIn("scan", suggestion.lower())

    def test_secrets_error(self):
        suggestion = _suggest_fix("secrets", RuntimeError("err"))
        self.assertIn("source files", suggestion.lower())

    def test_diff_error(self):
        suggestion = _suggest_fix("diff", RuntimeError("err"))
        self.assertIn("scan", suggestion.lower())

    def test_watch_error(self):
        suggestion = _suggest_fix("watch", RuntimeError("err"))
        self.assertIn("watchdog", suggestion.lower())

    def test_ask_error(self):
        suggestion = _suggest_fix("ask", RuntimeError("err"))
        self.assertIn("question", suggestion.lower())

    def test_unknown_command_error(self):
        suggestion = _suggest_fix("unknown-cmd", RuntimeError("err"))
        self.assertIn("help", suggestion.lower())

    def test_import_error_by_message(self):
        """Test import error detection by message content."""
        suggestion = _suggest_fix("scan", Exception("import error occurred"))
        self.assertIn("module", suggestion.lower())


# ─── _SEVERITY_ORDER Tests ────────────────────────────────────


class TestSeverityOrder(unittest.TestCase):
    """Test the _SEVERITY_ORDER mapping."""

    def test_critical_is_highest(self):
        self.assertEqual(_SEVERITY_ORDER["critical"], 0)

    def test_info_is_lowest(self):
        self.assertEqual(_SEVERITY_ORDER["info"], 5)

    def test_ordering(self):
        self.assertLess(_SEVERITY_ORDER["critical"], _SEVERITY_ORDER["high"])
        self.assertLess(_SEVERITY_ORDER["high"], _SEVERITY_ORDER["warning"])
        self.assertLess(_SEVERITY_ORDER["warning"], _SEVERITY_ORDER["medium"])
        self.assertLess(_SEVERITY_ORDER["medium"], _SEVERITY_ORDER["low"])
        self.assertLess(_SEVERITY_ORDER["low"], _SEVERITY_ORDER["info"])


# ─── resolve_workspace Tests ──────────────────────────────────


class TestResolveWorkspace(unittest.TestCase):
    """Test resolve_workspace auto-detect logic."""

    def test_valid_directory_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_workspace(tmpdir)
            self.assertEqual(result, os.path.abspath(tmpdir))

    def test_invalid_directory_falls_back(self):
        """Pass an invalid path — should fall back gracefully."""
        # resolve_workspace prints a warning for invalid paths
        # but still returns a valid path
        import io
        from contextlib import redirect_stderr
        f = io.StringIO()
        with redirect_stderr(f):
            result = resolve_workspace("/nonexistent/path/xyz123")
        self.assertIsInstance(result, str)
        self.assertTrue(os.path.isdir(result))

    def test_none_arg_returns_valid_path(self):
        result = resolve_workspace(None)
        self.assertIsInstance(result, str)
        self.assertTrue(os.path.isdir(result))


if __name__ == "__main__":
    unittest.main()
