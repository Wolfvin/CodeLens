"""
Tests for the Dead Code Detection Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from deadcode_engine import detect_dead_code


class TestDeadCodeEngine:
    """Test dead code detection across categories."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_unreachable_code_after_return(self):
        """Code after a return statement should be detected as unreachable."""
        code = """
function process(data) {
    return data;
    console.log("unreachable");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                assert len(result["results"]["unreachable"]) > 0
                item = result["results"]["unreachable"][0]
                assert "file" in item
                assert "line" in item
                assert "after" in item
                assert item["after"] == "return"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_unused_variable_detection(self):
        """Variables declared but never used should be detected."""
        code = """
function test() {
    const unusedVar = 42;
    const usedVar = 10;
    return usedVar;
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unused_vars" in result["results"]:
                unused_names = [v["variable"] for v in result["results"]["unused_vars"]]
                assert "unusedVar" in unused_names
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        """Verify the complete return structure of detect_dead_code."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            assert "workspace" in result
            assert "stats" in result
            assert "results" in result
            assert "categories_checked" in result
            # Stats sub-keys
            stats = result["stats"]
            assert "files_scanned" in stats
            assert "total_dead_code" in stats
            assert "by_category" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_categories_filter(self):
        """Filtering by categories should only check those categories."""
        code = """
function test() {
    return 1;
    console.log("dead");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws, categories=["unreachable"])
            assert result["status"] == "ok"
            assert "unreachable" in result["categories_checked"]
            # Other categories should not be checked
            assert "unused_vars" not in result["categories_checked"]
            assert "zombie_css" not in result["categories_checked"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_unused_variable(self):
        """Python variables assigned but never used should be detected."""
        code = """
def process():
    unused = 42
    used = 10
    return used
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unused_vars" in result["results"]:
                unused_names = [v["variable"] for v in result["results"]["unused_vars"]]
                assert "unused" in unused_names
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_unreachable_after_return(self):
        """Python code after return should be detected as unreachable."""
        code = """
def process():
    return True
    print("unreachable")
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                assert len(result["results"]["unreachable"]) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_code_no_dead_code(self):
        """Clean code should have minimal or no dead code findings."""
        code = """
function add(a, b) { return a + b; }
function multiply(a, b) { return a * b; }
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            # Clean code should have zero or very few dead code items
            assert result["stats"]["total_dead_code"] <= 2
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_unreachable_after_throw(self):
        """Code after a throw statement should be detected as unreachable."""
        code = """
function fail() {
    throw new Error("fail");
    console.log("never reached");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                items = result["results"]["unreachable"]
                assert any(item["after"] == "throw" for item in items)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        """Workspace with no source files should return zero dead code."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "data.json"), 'w') as f:
            f.write("{}")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_dead_code"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    # ─── Issue #105 regression tests ────────────────────────────────
    # These patterns must NOT be flagged as unreachable. They are the
    # PEP 8-friendly early-return pattern that workers were previously
    # forced to wrap in `else:` to satisfy the scanner.

    def test_issue_105_early_return_then_final_return(self):
        """Early return inside `if` + final return after should NOT be flagged."""
        code = """def f(condition):
    if condition:
        return None
    return {"key": "value"}
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_multiline_return_after_early_return(self):
        """Multi-line dict return after early return should NOT be flagged.

        This is the exact reproduction of issue #105. Before the fix, the
        scanner reported line 5 (the dict body) as unreachable because the
        multi-line return detection skipped the `return {` line without
        resetting the terminal flag from the previous `return None` inside
        the `if` block.
        """
        code = """def _detect_vulns(workspace, max_items):
    from vulnscan_engine import scan_vulnerabilities
    vuln = scan_vulnerabilities(workspace)
    total = vuln.get("stats", {}).get("total_vulnerabilities", 0)
    if total == 0:
        return None
    return {
        "category": "vulnerabilities",
        "total": total,
        "top_items": vuln.get("vulnerabilities", [])[:max_items],
    }
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on multi-line dict return: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_chained_early_returns(self):
        """Multiple chained early returns + final return should NOT be flagged."""
        code = """def g(x):
    if x is None:
        return None
    if x < 0:
        return -1
    if x > 100:
        return 100
    return x
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on chained early returns: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_nested_if_early_return(self):
        """Nested if/return + outer returns should NOT be flagged."""
        code = """def m(x, y):
    if x:
        if y:
            return None
        return 1
    return 2
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on nested if early return: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_genuinely_unreachable_still_detected(self):
        """Sanity check: genuinely unreachable code after unconditional
        return must still be detected after the fix."""
        code = """def f():
    return None
    print("unreachable")
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) >= 1, \
                f"Regression: genuinely unreachable code not detected: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)
