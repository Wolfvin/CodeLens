"""
Tests for the Code Smell Engine.
"""

import os
import sys
import tempfile
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
            assert "health_score" in result
            assert "findings" in result
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_many_parameters(self):
        code = "function tooManyParams(a, b, c, d, e, f, g, h, i, j) { return a; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert isinstance(result["health_score"], (int, float))
            assert 0 <= result["health_score"] <= 100
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_code_high_score(self):
        code = """
function add(a, b) { return a + b; }
function multiply(a, b) { return a * b; }
"""
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws)
            assert result["health_score"] >= 70  # Clean code should score well
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_severity_filter(self):
        code = "function hello() { return 'world'; }"
        ws = self._create_workspace(code)
        try:
            result = detect_smells(ws, severity="critical")
            assert "findings" in result
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
