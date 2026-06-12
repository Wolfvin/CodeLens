"""
Tests for the Complexity Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from complexity_engine import compute_complexity


class TestComplexityEngine:
    """Test cyclomatic and cognitive complexity computation."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_simple_function_low_complexity(self):
        """Simple function should have low cyclomatic complexity."""
        code = "function add(a, b) { return a + b; }"
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_functions"] >= 1
            # Simple function should have CC = 1 (no decision points)
            for fn in result["functions"]:
                if fn["name"] == "add":
                    assert fn["cyclomatic"] <= 2
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_complex_function_high_complexity(self):
        """Function with many branches should have high cyclomatic complexity."""
        code = """
function process(data) {
    if (data.a) {
        if (data.b) {
            for (let i = 0; i < data.c; i++) {
                if (data.d) {
                    while (data.e) {
                        if (data.f) {
                            return 1;
                        }
                    }
                }
            }
        }
    }
    return 0;
}
"""
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws)
            assert result["status"] == "ok"
            # Should find the function
            fn_names = [f["name"] for f in result["functions"]]
            assert "process" in fn_names
            # Complex function should have CC > 5
            process_fn = next(f for f in result["functions"] if f["name"] == "process")
            assert process_fn["cyclomatic"] >= 5
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        """Verify the complete return structure of compute_complexity."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws)
            assert result["status"] == "ok"
            assert "workspace" in result
            assert "stats" in result
            assert "functions" in result
            assert "hotspots" in result
            assert "recommendations" in result
            # Stats sub-keys
            stats = result["stats"]
            assert "total_functions" in stats
            assert "files_scanned" in stats
            assert "avg_cyclomatic" in stats
            assert "avg_cognitive" in stats
            assert "high_complexity" in stats
            assert "by_complexity_level" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_function_result_fields(self):
        """Each function result should have the expected fields."""
        code = "function greet(name) { return 'Hello ' + name; }"
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws)
            if result["functions"]:
                fn = result["functions"][0]
                assert "name" in fn
                assert "file" in fn
                assert "line" in fn
                assert "cyclomatic" in fn
                assert "cognitive" in fn
                assert "loc" in fn
                assert "params" in fn
                assert "max_nesting" in fn
                assert "complexity_level" in fn
                assert "refactoring_suggestion" in fn
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_function_name_filter(self):
        """Filtering by function_name should return only that function."""
        code = """
function target() { return 1; }
function other() { return 2; }
"""
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws, function_name="target")
            assert result["status"] == "ok"
            assert result["function"] == "target"
            assert "result" in result
            assert result["result"]["name"] == "target"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_function_name_not_found(self):
        """Searching for a non-existent function should return not_found."""
        code = "function exists() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws, function_name="nonexistent")
            assert result["status"] == "not_found"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_threshold_filter(self):
        """Threshold should filter out low-complexity functions."""
        code = """
function simple() { return 1; }
function complex() {
    if (a) { if (b) { if (c) { if (d) { if (e) { return 1; } } } } }
    return 0;
}
"""
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws, threshold=5)
            assert result["status"] == "ok"
            # Only functions with CC >= threshold should be returned
            for fn in result["functions"]:
                assert fn["cyclomatic"] >= 5
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_complexity(self):
        """Python code should be analyzed for complexity."""
        code = """
def process(data):
    if data.get('a'):
        for item in data.get('b', []):
            if item > 0:
                while item < 100:
                    item *= 2
    return data
"""
        ws = self._create_workspace(code, "process.py")
        try:
            result = compute_complexity(ws)
            assert result["status"] == "ok"
            fn_names = [f["name"] for f in result["functions"]]
            assert "process" in fn_names
            process_fn = next(f for f in result["functions"] if f["name"] == "process")
            assert process_fn["cyclomatic"] >= 2
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_hotspots_are_sorted(self):
        """Hotspots should be sorted by cyclomatic complexity (highest first)."""
        code = """
function easy() { return 1; }
function medium(x) { if (x) { return 2; } return 3; }
function hard(a, b, c) { if (a) { if (b) { if (c) { return 4; } } } return 5; }
"""
        ws = self._create_workspace(code)
        try:
            result = compute_complexity(ws)
            hotspots = result["hotspots"]
            if len(hotspots) >= 2:
                for i in range(len(hotspots) - 1):
                    assert hotspots[i]["cyclomatic"] >= hotspots[i + 1]["cyclomatic"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        """Workspace with no source files should return zero functions."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "readme.txt"), 'w') as f:
            f.write("Not a source file")
        try:
            result = compute_complexity(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_functions"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)
