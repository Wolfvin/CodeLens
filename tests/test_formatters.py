"""Tests for formatters/__init__.py — AI format normalizer.

Tests _normalize_to_ai with various command output shapes, and format_output.
"""

import json
import os
import sys
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from formatters import _normalize_to_ai, format_output


# ─── _normalize_to_ai — Basic Types ───────────────────────────


class TestNormalizeBasicTypes(unittest.TestCase):
    """Test _normalize_to_ai with non-dict and basic inputs."""

    def test_non_dict_input(self):
        result = _normalize_to_ai("hello")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["items"], ["hello"])

    def test_non_dict_number(self):
        result = _normalize_to_ai(42)
        self.assertEqual(result["items"], [42])

    def test_empty_dict(self):
        result = _normalize_to_ai({})
        self.assertEqual(result["status"], "ok")

    def test_error_status(self):
        result = _normalize_to_ai({"status": "error", "error": "oops", "error_type": "RuntimeError"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "oops")
        self.assertEqual(result["error_type"], "RuntimeError")

    def test_error_with_suggestion(self):
        result = _normalize_to_ai({
            "status": "error",
            "error": "not found",
            "suggestion": "Check path",
        })
        self.assertEqual(result["suggestion"], "Check path")

    def test_error_inherits_command(self):
        result = _normalize_to_ai({"status": "error"}, command="scan")
        self.assertEqual(result["command"], "scan")


# ─── _normalize_to_ai — Stats Extraction ──────────────────────


class TestNormalizeStats(unittest.TestCase):
    """Test stats extraction from various command output shapes."""

    def test_explicit_stats(self):
        result = _normalize_to_ai({"stats": {"total": 42}})
        self.assertEqual(result["stats"]["total"], 42)

    def test_health_score_extraction(self):
        result = _normalize_to_ai({
            "health_score": 75,
            "total_findings": 10,
        })
        self.assertEqual(result["stats"]["health_score"], 75)
        self.assertEqual(result["stats"]["total_findings"], 10)

    def test_by_severity_from_health_score(self):
        result = _normalize_to_ai({
            "health_score": 50,
            "by_severity": {"critical": 2, "high": 3},
        })
        self.assertEqual(result["stats"]["by_severity"]["critical"], 2)

    def test_by_category_counts(self):
        result = _normalize_to_ai({
            "health_score": 60,
            "by_category": {
                "unused_vars": [{"name": "x"}, {"name": "y"}],
                "dead_code": [{"name": "z"}],
            },
        })
        self.assertEqual(result["stats"]["unused_vars_count"], 2)
        self.assertEqual(result["stats"]["dead_code_count"], 1)

    def test_total_cycles_extraction(self):
        result = _normalize_to_ai({"total_cycles": 5})
        self.assertEqual(result["stats"]["total_cycles"], 5)

    def test_total_issues_extraction(self):
        result = _normalize_to_ai({"total_issues": 8})
        self.assertEqual(result["stats"]["total_issues"], 8)

    def test_identity_with_registry_stats(self):
        result = _normalize_to_ai({
            "identity": "my-project",
            "registry_stats": {"files": 42, "nodes": 100},
        })
        self.assertEqual(result["stats"]["files"], 42)
        self.assertEqual(result["stats"]["nodes"], 100)


# ─── _normalize_to_ai — Items Extraction ──────────────────────


class TestNormalizeItems(unittest.TestCase):
    """Test items extraction from flat lists and category-keyed dicts."""

    def test_functions_key(self):
        result = _normalize_to_ai({"functions": [{"name": "fn1"}, {"name": "fn2"}]})
        self.assertEqual(len(result["items"]), 2)

    def test_findings_key(self):
        result = _normalize_to_ai({"findings": [{"severity": "high"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_leaks_key(self):
        result = _normalize_to_ai({"leaks": [{"type": "debug"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_hints_key(self):
        result = _normalize_to_ai({"hints": [{"hint": "cache"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_issues_key(self):
        result = _normalize_to_ai({"issues": [{"desc": "bad"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_matches_key(self):
        result = _normalize_to_ai({"matches": [{"line": 10}]})
        self.assertEqual(len(result["items"]), 1)

    def test_violations_key(self):
        result = _normalize_to_ai({"violations": [{"rule": "R1"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_entrypoints_key(self):
        result = _normalize_to_ai({"entrypoints": [{"name": "main"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_routes_key(self):
        result = _normalize_to_ai({"routes": [{"path": "/api"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_results_key(self):
        result = _normalize_to_ai({"results": [{"name": "dead_fn"}]})
        self.assertEqual(len(result["items"]), 1)

    def test_category_keyed_dict(self):
        result = _normalize_to_ai({
            "by_category": {
                "unused_vars": [{"name": "x"}, {"name": "y"}],
                "dead_code": [{"name": "z"}],
            }
        })
        self.assertEqual(len(result["items"]), 3)

    def test_category_adds_category_tag(self):
        result = _normalize_to_ai({
            "by_category": {
                "unused_vars": [{"name": "x"}],
            }
        })
        self.assertEqual(result["items"][0]["_category"], "unused_vars")

    def test_category_no_overwrite_existing(self):
        result = _normalize_to_ai({
            "by_category": {
                "cat": [{"name": "x", "category": "existing"}],
            }
        })
        self.assertEqual(result["items"][0]["category"], "existing")
        self.assertNotIn("_category", result["items"][0])

    def test_empty_list_not_extracted(self):
        result = _normalize_to_ai({"findings": []})
        self.assertEqual(result["items"], [])

    def test_coverage_map_extraction(self):
        result = _normalize_to_ai({
            "coverage_map": {
                "test.py": {
                    "my_func": {"covered": True, "line": 10},
                }
            }
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["file"], "test.py")
        self.assertEqual(result["items"][0]["function"], "my_func")

    def test_priority_order_functions_over_findings(self):
        """functions should be preferred over findings."""
        result = _normalize_to_ai({
            "functions": [{"name": "fn1"}],
            "findings": [{"name": "find1"}],
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["name"], "fn1")


# ─── _normalize_to_ai — Truncation Detection ──────────────────


class TestNormalizeTruncation(unittest.TestCase):
    """Test truncation flag detection."""

    def test_explicit_truncated(self):
        result = _normalize_to_ai({"truncated": True, "functions": []})
        self.assertTrue(result["truncated"])

    def test_files_truncated(self):
        result = _normalize_to_ai({"files_truncated": True})
        self.assertTrue(result["truncated"])

    def test_token_truncated(self):
        result = _normalize_to_ai({"_token_truncated": True})
        self.assertTrue(result["truncated"])

    def test_key_specific_truncated(self):
        result = _normalize_to_ai({"functions_truncated": True})
        self.assertTrue(result["truncated"])

    def test_no_truncation(self):
        result = _normalize_to_ai({"functions": []})
        self.assertFalse(result["truncated"])


# ─── _normalize_to_ai — Recommendations ───────────────────────


class TestNormalizeRecommendations(unittest.TestCase):
    """Test recommendations extraction and merging."""

    def test_explicit_recommendations(self):
        result = _normalize_to_ai({"recommendations": ["fix A", "fix B"]})
        self.assertEqual(len(result["recommendations"]), 2)

    def test_recommended_action_merged(self):
        result = _normalize_to_ai({
            "recommendations": [],
            "removal_safety": True,
            "recommended_action": "Remove safely",
        })
        self.assertIn("Remove safely", result["recommendations"])

    def test_actionable_items_merged(self):
        result = _normalize_to_ai({
            "recommendations": [],
            "actionable_items": ["item1", "item2"],
        })
        self.assertIn("item1", result["recommendations"])

    def test_action_plan_merged(self):
        result = _normalize_to_ai({
            "recommendations": [],
            "action_plan": ["step1", "step2"],
        })
        self.assertIn("step1", result["recommendations"])

    def test_recommendations_capped_at_10(self):
        result = _normalize_to_ai({
            "recommendations": [f"rec_{i}" for i in range(20)],
        })
        self.assertEqual(len(result["recommendations"]), 10)

    def test_no_recommendations(self):
        result = _normalize_to_ai({"status": "ok"})
        self.assertEqual(result["recommendations"], [])


# ─── _normalize_to_ai — Metadata ──────────────────────────────


class TestNormalizeMetadata(unittest.TestCase):
    """Test metadata extraction."""

    def test_workspace_metadata(self):
        result = _normalize_to_ai({"workspace": "/test"})
        self.assertEqual(result["metadata"]["workspace"], "/test")

    def test_symbol_metadata(self):
        result = _normalize_to_ai({"symbol": "my_func"})
        self.assertEqual(result["metadata"]["symbol"], "my_func")

    def test_query_metadata(self):
        result = _normalize_to_ai({"query": "search_term"})
        self.assertEqual(result["metadata"]["query"], "search_term")

    def test_confidence_metadata(self):
        result = _normalize_to_ai({"confidence": "high"})
        self.assertEqual(result["metadata"]["confidence"], "high")

    def test_frameworks_detected_metadata(self):
        result = _normalize_to_ai({"frameworks_detected": ["flask", "react"]})
        self.assertEqual(result["metadata"]["frameworks_detected"], ["flask", "react"])

    def test_dashboard_path_metadata(self):
        result = _normalize_to_ai({"dashboard_path": "/tmp/dashboard.html"})
        self.assertEqual(result["metadata"]["dashboard_path"], "/tmp/dashboard.html")

    def test_history_snapshot_metadata(self):
        result = _normalize_to_ai({
            "history_snapshot_saved": True,
            "history_snapshot_file": "snap.json",
        })
        self.assertTrue(result["metadata"]["history_available"])
        self.assertEqual(result["metadata"]["history_snapshot_file"], "snap.json")

    def test_node_metadata(self):
        result = _normalize_to_ai({"node": {"fn": "hello", "file": "a.py"}})
        self.assertEqual(result["metadata"]["node"]["fn"], "hello")

    def test_pagination_metadata(self):
        result = _normalize_to_ai({"pagination": {"page": 1, "total": 10}})
        self.assertEqual(result["metadata"]["pagination"]["total"], 10)

    def test_auto_setup_info(self):
        result = _normalize_to_ai({"_auto_setup": {"auto_setup": True}})
        self.assertEqual(result["auto_setup"]["auto_setup"], True)


# ─── format_output Tests ──────────────────────────────────────


class TestFormatOutput(unittest.TestCase):
    """Test format_output for different format types."""

    def test_json_format(self):
        data = {"status": "ok", "count": 5}
        output = format_output(data, "json")
        parsed = json.loads(output)
        self.assertEqual(parsed["count"], 5)

    def test_ai_format(self):
        data = {"status": "ok", "findings": [{"severity": "high"}]}
        output = format_output(data, "ai", command="smell")
        parsed = json.loads(output)
        self.assertEqual(parsed["status"], "ok")
        self.assertIn("items", parsed)
        self.assertIn("stats", parsed)
        self.assertIn("metadata", parsed)

    def test_markdown_format(self):
        data = {"status": "ok"}
        output = format_output(data, "markdown", command="scan")
        self.assertIsInstance(output, str)
        self.assertTrue(len(output) > 0)

    def test_ai_format_error(self):
        data = {"status": "error", "error": "oops"}
        output = format_output(data, "ai", command="scan")
        parsed = json.loads(output)
        self.assertEqual(parsed["status"], "error")


if __name__ == "__main__":
    unittest.main()
