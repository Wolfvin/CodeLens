"""
Tests for the Circular Dependency Detection Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from circular_engine import detect_circular


class TestCircularEngine:
    """Test circular dependency detection."""

    def _create_workspace(self, files=None):
        """Create a workspace with multiple files."""
        ws = tempfile.mkdtemp()
        if files:
            for filename, content in files.items():
                filepath = os.path.join(ws, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                with open(filepath, 'w') as f:
                    f.write(content)
        return ws

    def test_circular_import_detection(self):
        """Two files importing each other should be detected as a circular import."""
        files = {
            "a.js": "const b = require('./b');\nfunction aFn() { return b.bFn(); }\nmodule.exports = { aFn };",
            "b.js": "const a = require('./a');\nfunction bFn() { return a.aFn(); }\nmodule.exports = { bFn };",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws)
            assert result["status"] == "ok"
            assert result["total_cycles"] >= 1
            assert len(result["cycles"]["import_chains"]) >= 1
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_no_cycles_in_clean_code(self):
        """Files without circular imports should report zero cycles."""
        files = {
            "main.js": "const utils = require('./utils');\nconsole.log(utils.help());",
            "utils.js": "function help() { return 'help'; }\nmodule.exports = { help };",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws)
            assert result["status"] == "ok"
            assert len(result["cycles"]["import_chains"]) == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        """Verify the complete return structure of detect_circular."""
        ws = self._create_workspace({"app.js": "function test() { return 1; }"})
        try:
            result = detect_circular(ws)
            assert result["status"] == "ok"
            assert "workspace" in result
            assert "domain" in result
            assert "total_cycles" in result
            assert "cycles" in result
            assert "summary" in result
            # Cycles sub-keys
            assert "function_calls" in result["cycles"]
            assert "import_chains" in result["cycles"]
            assert "css_imports" in result["cycles"]
            # Summary sub-keys
            assert "function_call_cycles" in result["summary"]
            assert "import_chain_cycles" in result["summary"]
            assert "css_import_cycles" in result["summary"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_domain_filter_imports(self):
        """Domain filter 'imports' should only check import chains."""
        files = {
            "a.js": "const b = require('./b');\nmodule.exports = { aFn: () => 1 };",
            "b.js": "const a = require('./a');\nmodule.exports = { bFn: () => 2 };",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws, domain="imports")
            assert result["status"] == "ok"
            assert result["domain"] == "imports"
            # function_calls should be empty (not checked)
            assert len(result["cycles"]["function_calls"]) == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_domain_filter_backend(self):
        """Domain filter 'backend' should only check function calls."""
        files = {
            "app.js": "function test() { return 1; }",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws, domain="backend")
            assert result["status"] == "ok"
            assert result["domain"] == "backend"
            # import_chains should be empty (not checked)
            assert len(result["cycles"]["import_chains"]) == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_css_import_cycle(self):
        """Circular CSS @import chains should be detected."""
        files = {
            "a.css": "@import url('./b.css');\n.a { color: red; }",
            "b.css": "@import url('./a.css');\n.b { color: blue; }",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws, domain="css")
            assert result["status"] == "ok"
            # Should detect the CSS import cycle
            assert len(result["cycles"]["css_imports"]) >= 1
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_summary_matches_cycles(self):
        """Summary counts should match actual cycle counts."""
        files = {
            "app.js": "function test() { return 1; }",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws)
            assert result["summary"]["function_call_cycles"] == len(result["cycles"]["function_calls"])
            assert result["summary"]["import_chain_cycles"] == len(result["cycles"]["import_chains"])
            assert result["summary"]["css_import_cycles"] == len(result["cycles"]["css_imports"])
            assert result["total_cycles"] == (
                result["summary"]["function_call_cycles"] +
                result["summary"]["import_chain_cycles"] +
                result["summary"]["css_import_cycles"]
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_three_way_circular_import(self):
        """Three-way circular import (a→b→c→a) should be detected."""
        files = {
            "a.js": "const b = require('./b');\nmodule.exports = { aFn: () => b.bFn() };",
            "b.js": "const c = require('./c');\nmodule.exports = { bFn: () => c.cFn() };",
            "c.js": "const a = require('./a');\nmodule.exports = { cFn: () => a.aFn() };",
        }
        ws = self._create_workspace(files)
        try:
            result = detect_circular(ws)
            assert result["status"] == "ok"
            assert len(result["cycles"]["import_chains"]) >= 1
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        """Empty workspace should report zero cycles."""
        ws = tempfile.mkdtemp()
        try:
            result = detect_circular(ws)
            assert result["status"] == "ok"
            assert result["total_cycles"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)
