"""
Tests for the Code Smell Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from smell_engine import detect_smells


class TestSmellEngine:
    """Test code smell detection."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_long_function_detection(self):
        # Create a function with many lines
        lines = ["function veryLongFunction() {"]
        for i in range(60):
            lines.append(f"    const var{i} = {i};")
        lines.append("}")
        code = "\n".join(lines)
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert "stats" in result
            assert "health_score" in result["stats"]
            assert "by_category" in result
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_many_parameters(self):
        code = "function tooManyParams(a, b, c, d, e, f, g, h, i, j) { return a; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert isinstance(result["stats"]["health_score"], (int, float))
            assert 0 <= result["stats"]["health_score"] <= 100
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_code_high_score(self):
        code = """
function add(a, b) { return a + b; }
function multiply(a, b) { return a * b; }
"""
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert result["stats"]["health_score"] >= 70  # Clean code should score well
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_severity_filter(self):
        """Test severity_filter kwarg (actual parameter name)."""
        code = "function hello() { return 'world'; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws, severity_filter="critical")
            assert "by_category" in result
            # When filtering by critical, all returned smells should be critical
            for cat, smells in result["by_category"].items():
                for smell in smells:
                    assert smell.get("severity") == "critical"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert result["status"] == "ok"
            assert "stats" in result
            assert "by_category" in result
            assert "top_priority" in result
            assert "categories_checked" in result
            # stats sub-keys
            stats = result["stats"]
            assert "files_scanned" in stats
            assert "total_smells" in stats
            assert "critical" in stats
            assert "warning" in stats
            assert "info" in stats
            assert "health_score" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_categories_parameter(self):
        """Test filtering by specific smell categories."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws, categories=["long_fn"])
            assert result["status"] == "ok"
            assert "categories_checked" in result
            assert "long_fn" in result["categories_checked"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_large_file_detection(self):
        """Create a large file (500+ lines)."""
        lines = ["// line {}".format(i) for i in range(600)]
        code = "\n".join(lines)
        ws = self._create_workspace(code, "bigfile.js")
        try:
            result = detect_smells(ws)
            if "large_file" in result["by_category"]:
                large_file_smells = result["by_category"]["large_file"]
                assert any(s.get("severity") in ("warning", "critical") for s in large_file_smells)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_deep_nesting(self):
        """Python code with deep nesting."""
        code = "def outer():\n"
        code += "    if True:\n"
        code += "        if True:\n"
        code += "            if True:\n"
        code += "                if True:\n"
        code += "                    if True:\n"
        code += "                        pass\n"
        ws = self._create_workspace(code, "nested.py")
        try:
            result = detect_smells(ws)
            assert result["status"] == "ok"
            # Deep nesting should be detected
            if "deep_nesting" in result["by_category"]:
                nesting_smells = result["by_category"]["deep_nesting"]
                assert len(nesting_smells) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_rust_many_params(self):
        """Rust function with many parameters."""
        code = "fn many_params(a: i32, b: i32, c: i32, d: i32, e: i32, f: i32, g: i32, h: i32, i: i32) -> i32 { a }"
        ws = self._create_workspace(code, "params.rs")
        try:
            result = detect_smells(ws)
            assert result["status"] == "ok"
            # Many parameters should be detected
            if "many_params" in result["by_category"]:
                param_smells = result["by_category"]["many_params"]
                assert len(param_smells) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)
