"""Tests for hybrid_engine.py — Hybrid analysis with confidence scoring.

Tests compute_confidence, compute_confidence_distribution, add_confidence_to_result,
HybridEngine without LSP (graceful fallback), and dead-code verification logic.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from hybrid_engine import (
    compute_confidence,
    compute_confidence_distribution,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_LOW,
    HybridEngine,
    add_confidence_to_result,
    create_hybrid_engine,
)


# ─── compute_confidence Tests ─────────────────────────────────


class TestComputeConfidence(unittest.TestCase):
    """Test compute_confidence with all parameter combinations."""

    def test_lsp_verified_high(self):
        self.assertEqual(compute_confidence(True, lsp_verified=True), CONFIDENCE_HIGH)

    def test_lsp_verified_false_ast_matched(self):
        self.assertEqual(compute_confidence(True, lsp_verified=False, ast_matched=True), CONFIDENCE_MEDIUM)

    def test_lsp_verified_false_ast_not_matched(self):
        self.assertEqual(compute_confidence(True, lsp_verified=False, ast_matched=False), CONFIDENCE_LOW)

    def test_lsp_none_ast_matched(self):
        self.assertEqual(compute_confidence(True, lsp_verified=None, ast_matched=True), CONFIDENCE_MEDIUM)

    def test_lsp_none_ast_not_matched(self):
        self.assertEqual(compute_confidence(True, lsp_verified=None, ast_matched=False), CONFIDENCE_LOW)

    def test_lsp_contradicts_overrides(self):
        """LSP contradiction should always result in low confidence."""
        self.assertEqual(
            compute_confidence(True, lsp_verified=True, lsp_contradicts=True),
            CONFIDENCE_LOW
        )

    def test_lsp_contradicts_without_verify(self):
        self.assertEqual(
            compute_confidence(True, lsp_verified=None, lsp_contradicts=True),
            CONFIDENCE_LOW
        )

    def test_no_lsp_ast_matched(self):
        self.assertEqual(
            compute_confidence(False, lsp_verified=None, ast_matched=True),
            CONFIDENCE_MEDIUM
        )

    def test_no_lsp_no_ast(self):
        self.assertEqual(
            compute_confidence(False, lsp_verified=None, ast_matched=False),
            CONFIDENCE_LOW
        )


# ─── compute_confidence_distribution Tests ────────────────────


class TestComputeConfidenceDistribution(unittest.TestCase):
    """Test confidence distribution computation."""

    def test_empty_findings(self):
        dist = compute_confidence_distribution([])
        self.assertEqual(dist, {"high": 0, "medium": 0, "low": 0})

    def test_all_high(self):
        dist = compute_confidence_distribution([{"confidence": "high"}, {"confidence": "high"}])
        self.assertEqual(dist["high"], 2)
        self.assertEqual(dist["medium"], 0)
        self.assertEqual(dist["low"], 0)

    def test_mixed_confidence(self):
        findings = [
            {"confidence": "high"},
            {"confidence": "medium"},
            {"confidence": "low"},
            {"confidence": "high"},
        ]
        dist = compute_confidence_distribution(findings)
        self.assertEqual(dist["high"], 2)
        self.assertEqual(dist["medium"], 1)
        self.assertEqual(dist["low"], 1)

    def test_missing_confidence_defaults_low(self):
        dist = compute_confidence_distribution([{"name": "a"}, {"name": "b"}])
        self.assertEqual(dist["low"], 2)

    def test_unknown_confidence_not_counted(self):
        dist = compute_confidence_distribution([{"confidence": "unknown"}])
        self.assertEqual(dist["high"], 0)
        self.assertEqual(dist["medium"], 0)
        self.assertEqual(dist["low"], 0)


# ─── HybridEngine — No LSP (Graceful Fallback) ────────────────


class TestHybridEngineNoLSP(unittest.TestCase):
    """Test HybridEngine when LSP is not available (graceful fallback)."""

    def test_engine_without_deep(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            self.assertFalse(engine.lsp_active)

    def test_verify_dead_code_no_lsp(self):
        """Without LSP, verify_dead_code should add medium confidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            findings = [{"name": "dead_fn", "file": "test.py", "line": 10}]
            result = engine.verify_dead_code(findings)
            self.assertEqual(result[0]["confidence"], CONFIDENCE_MEDIUM)

    def test_verify_dead_code_preserves_existing_confidence(self):
        """If finding already has confidence, it shouldn't be overwritten when no LSP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            findings = [{"name": "dead_fn", "confidence": "high"}]
            result = engine.verify_dead_code(findings)
            self.assertEqual(result[0]["confidence"], "high")

    def test_verify_dead_code_empty_findings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            result = engine.verify_dead_code([])
            self.assertEqual(result, [])

    def test_enhance_query_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            result = {"node": {"file": "test.py", "line": 10}}
            result = engine.enhance_query(result, "test_fn")
            self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)

    def test_enhance_impact_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            result = {"affected": {"direct": [], "indirect": []}}
            result = engine.enhance_impact(result, "test_fn")
            self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)

    def test_enhance_smell_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            findings = [{"name": "smell1", "file": "test.py", "line": 10}]
            result = engine.enhance_smell(findings)
            self.assertEqual(result[0]["confidence"], CONFIDENCE_MEDIUM)

    def test_enhance_smell_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            result = engine.enhance_smell([])
            self.assertEqual(result, [])

    def test_enhance_complexity_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            findings = [{"name": "fn1", "file": "test.py", "line": 5}]
            result = engine.enhance_complexity(findings)
            self.assertEqual(result[0]["confidence"], CONFIDENCE_MEDIUM)

    def test_get_lsp_client_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            self.assertIsNone(engine.get_lsp_client())

    def test_open_file_no_lsp(self):
        """Should not crash when trying to open file without LSP."""
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            engine.open_file_for_lsp("test.py")  # Should be no-op

    def test_close_all_no_lsp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            engine.close_all_lsp_files()  # Should be no-op

    def test_cleanup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            engine.cleanup()  # Should not crash


# ─── add_confidence_to_result Tests ───────────────────────────


class TestAddConfidenceToResult(unittest.TestCase):
    """Test add_confidence_to_result adds confidence to various result structures."""

    def test_adds_confidence_to_findings_list(self):
        result = {"status": "ok", "findings": [{"name": "a"}, {"name": "b"}]}
        result = add_confidence_to_result(result)
        self.assertEqual(result["findings"][0]["confidence"], CONFIDENCE_MEDIUM)
        self.assertIn("confidence_distribution", result["stats"])

    def test_adds_confidence_to_nested_dict(self):
        result = {
            "results": {
                "unused": [{"name": "a"}, {"name": "b"}],
                "dead": [{"name": "c"}],
            }
        }
        result = add_confidence_to_result(result)
        for items in result["results"].values():
            for item in items:
                self.assertEqual(item["confidence"], CONFIDENCE_MEDIUM)

    def test_with_specific_key(self):
        result = {"status": "ok", "leaks": [{"name": "a"}]}
        result = add_confidence_to_result(result, findings_key="leaks")
        self.assertEqual(result["leaks"][0]["confidence"], CONFIDENCE_MEDIUM)

    def test_non_dict_passthrough(self):
        result = add_confidence_to_result("not a dict")
        self.assertEqual(result, "not a dict")

    def test_preserves_existing_confidence(self):
        result = {"findings": [{"name": "a", "confidence": "high"}]}
        result = add_confidence_to_result(result)
        self.assertEqual(result["findings"][0]["confidence"], "high")

    def test_empty_result(self):
        result = add_confidence_to_result({"status": "ok"})
        self.assertNotIn("stats", result)


# ─── create_hybrid_engine Tests ───────────────────────────────


class TestCreateHybridEngine(unittest.TestCase):
    """Test the factory function."""

    def test_create_no_deep(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = create_hybrid_engine(tmpdir, deep=False)
            self.assertIsInstance(engine, HybridEngine)
            self.assertFalse(engine.lsp_active)


# ─── _find_symbol_char Tests ──────────────────────────────────


class TestFindSymbolChar(unittest.TestCase):
    """Test _find_symbol_char helper."""

    def test_finds_symbol_in_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, 'w') as f:
                f.write('def my_function():\n    pass\n')
            engine = HybridEngine(tmpdir, deep=False)
            char = engine._find_symbol_char(filepath, 1, "my_function")
            self.assertIsNotNone(char)
            self.assertGreaterEqual(char, 0)

    def test_symbol_not_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, 'w') as f:
                f.write('x = 1\n')
            engine = HybridEngine(tmpdir, deep=False)
            char = engine._find_symbol_char(filepath, 1, "nonexistent")
            self.assertIsNone(char)

    def test_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = HybridEngine(tmpdir, deep=False)
            char = engine._find_symbol_char("/nonexistent/file.py", 1, "fn")
            self.assertIsNone(char)

    def test_line_out_of_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, 'w') as f:
                f.write('x = 1\n')
            engine = HybridEngine(tmpdir, deep=False)
            char = engine._find_symbol_char(filepath, 100, "x")
            self.assertIsNone(char)

    def test_line_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test.py")
            with open(filepath, 'w') as f:
                f.write('x = 1\n')
            engine = HybridEngine(tmpdir, deep=False)
            char = engine._find_symbol_char(filepath, 0, "x")
            self.assertIsNone(char)


if __name__ == "__main__":
    unittest.main()
