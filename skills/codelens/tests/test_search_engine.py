"""
Tests for the search engine — code pattern search across workspace.
"""

import os
import sys
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from search_engine import search_workspace


class TestSearchEngine:
    """Test code search functionality."""

    def _create_workspace(self):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "app.js"), 'w') as f:
            f.write("function hello() { return 'world'; }\nfunction goodbye() { return 'bye'; }\n")
        with open(os.path.join(ws, "utils.py"), 'w') as f:
            f.write("def process_data(input):\n    return input.upper()\n")
        return ws

    def test_basic_search(self):
        ws = self._create_workspace()
        try:
            result = search_workspace("function", ws)
            assert result["count"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_with_file_type(self):
        ws = self._create_workspace()
        try:
            result = search_workspace("function", ws, file_type="js")
            assert result["count"] > 0
            for match in result["matches"]:
                assert match["path"].endswith(".js")
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_no_results(self):
        ws = self._create_workspace()
        try:
            result = search_workspace("NONEXISTENT_PATTERN_XYZ", ws)
            assert result["count"] == 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
