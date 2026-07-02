"""Test that large files use regex fallback and report skipped_from_tree_sitter.

Verifies issue #163 fix: silent skip is replaced with explicit fallback
+ skipped_from_tree_sitter field in the parser result.
"""
import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parsers
_js_be_parser = None
_js_be_parser_available = False
try:
    from parsers.js_backend_parser import JSBackendParser
    _js_be_parser = JSBackendParser()
    _js_be_parser_available = True
except Exception:
    pass

_py_parser = None
_py_parser_available = False
try:
    from parsers.python_parser import PythonParser
    _py_parser = PythonParser()
    _py_parser_available = True
except Exception:
    pass


def _make_js_large(n_lines=300):
    """Generate a JS file above the tree-sitter safety threshold."""
    lines = []
    for i in range(n_lines):
        lines.append(f"function f{i}() {{ return processItem({i}); }}")
    return "\n".join(lines) + "\n"


def _make_py_large(n_lines=600):
    """Generate a Python file above the tree-sitter safety threshold."""
    lines = []
    for i in range(n_lines):
        lines.append(f"def f{i}():\n    return process_item({i})\n")
    return "".join(lines)


class TestLargeFileFallback:
    """Issue #163: large files must use regex fallback, not silent skip."""

    @pytest.mark.skipif(not _js_be_parser_available, reason="JSBackendParser not available")
    def test_js_large_file_returns_nodes_not_empty(self):
        """A large JS file must return non-empty nodes (via regex fallback).

        Before fix: silent skip returned {"nodes": [], "edges": []}.
        After fix: regex fallback returns partial coverage.
        """
        content = _make_js_large(300)
        result = _js_be_parser.extract_references(content, "large.js")
        # Must NOT be empty — fallback gives partial coverage
        assert len(result["nodes"]) > 0, (
            "Large JS file returned 0 nodes — silent skip regression (issue #163)"
        )
        assert len(result["edges"]) > 0

    @pytest.mark.skipif(not _js_be_parser_available, reason="JSBackendParser not available")
    def test_js_large_file_reports_skipped_from_tree_sitter(self):
        """Large JS file result must include skipped_from_tree_sitter field."""
        content = _make_js_large(300)
        result = _js_be_parser.extract_references(content, "large.js")
        assert "skipped_from_tree_sitter" in result, (
            "skipped_from_tree_sitter field missing — silent skip regression (issue #163)"
        )
        skip_info = result["skipped_from_tree_sitter"]
        assert skip_info["file"] == "large.js"
        assert skip_info["lines"] > 250
        assert skip_info["threshold"] == 250
        assert skip_info["reason"] == "tree_sitter_binding_segfault_risk"
        assert skip_info["fallback_used"] == "regex"

    @pytest.mark.skipif(not _js_be_parser_available, reason="JSBackendParser not available")
    def test_js_small_file_does_not_report_skipped(self):
        """Small JS file (under threshold) must NOT have skipped_from_tree_sitter."""
        content = "function small() { return 1; }\n"
        result = _js_be_parser.extract_references(content, "small.js")
        assert "skipped_from_tree_sitter" not in result, (
            "Small file should be parsed by tree-sitter, not fallback"
        )
        assert len(result["nodes"]) == 1

    @pytest.mark.skipif(not _py_parser_available, reason="PythonParser not available")
    def test_py_large_file_returns_nodes_not_empty(self):
        """A large Python file must return non-empty nodes (via regex fallback)."""
        content = _make_py_large(600)
        result = _py_parser.extract_references(content, "large.py")
        assert len(result["nodes"]) > 0, (
            "Large Python file returned 0 nodes — silent skip regression (issue #163)"
        )

    @pytest.mark.skipif(not _py_parser_available, reason="PythonParser not available")
    def test_py_large_file_reports_skipped_from_tree_sitter(self):
        """Large Python file result must include skipped_from_tree_sitter field."""
        content = _make_py_large(600)
        result = _py_parser.extract_references(content, "large.py")
        assert "skipped_from_tree_sitter" in result, (
            "skipped_from_tree_sitter field missing — silent skip regression (issue #163)"
        )
        skip_info = result["skipped_from_tree_sitter"]
        assert skip_info["file"] == "large.py"
        assert skip_info["lines"] > 500
        assert skip_info["threshold"] == 500
        assert skip_info["reason"] == "tree_sitter_binding_segfault_risk"
        assert skip_info["fallback_used"] == "regex"

    @pytest.mark.skipif(not _py_parser_available, reason="PythonParser not available")
    def test_py_small_file_does_not_report_skipped(self):
        """Small Python file must NOT have skipped_from_tree_sitter."""
        content = "def small():\n    return 1\n"
        result = _py_parser.extract_references(content, "small.py")
        assert "skipped_from_tree_sitter" not in result
        assert len(result["nodes"]) == 1
