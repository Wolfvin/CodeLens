"""
Tests for the search engine — code pattern search across workspace.
"""

import os
import sys
import tempfile
import shutil
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
            result = search_workspace(ws, "function")
            assert result["status"] == "ok"
            assert result["stats"]["total_matches"] > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_with_file_type(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "function", file_type="js")
            assert result["status"] == "ok"
            assert result["stats"]["total_matches"] > 0
            for match in result["matches"]:
                assert match["file"].endswith(".js")
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_no_results(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "NONEXISTENT_PATTERN_XYZ")
            assert result["status"] == "ok"
            assert result["stats"]["total_matches"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_returns_matches_list(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "hello")
            assert "matches" in result
            assert isinstance(result["matches"], list)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_match_has_file_line(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "function", file_type="js")
            if result["matches"]:
                match = result["matches"][0]
                assert "file" in match
                assert "line" in match
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_stats(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "function")
            stats = result["stats"]
            assert "files_searched" in stats
            assert "files_matched" in stats
            assert "total_matches" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_invalid_regex(self):
        """Invalid regex should return an error status, not crash."""
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "[invalid")
            assert result["status"] == "error"
            assert "matches" in result
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_case_insensitive(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "HELLO", case_sensitive=False)
            assert result["status"] == "ok"
            # "hello" in app.js should be found case-insensitively
            assert result["stats"]["total_matches"] > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_match_structure(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "hello")
            if result["matches"]:
                match = result["matches"][0]
                assert "file" in match
                assert "line" in match
                assert "match" in match
                assert "start_col" in match
                assert "end_col" in match
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_search_stats_truncated_key(self):
        ws = self._create_workspace()
        try:
            result = search_workspace(ws, "function")
            stats = result["stats"]
            assert "truncated" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)
