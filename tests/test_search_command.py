"""Tests for search command self-correction hints (issue #239).

`search` is the only umbrella command with `pattern` before `workspace`
(opposite of every other command) — getting it backwards doesn't error,
it silently searches for the workspace path as the pattern and returns
an empty "ok" result. Separately, a Cypher-shaped pattern passed without
`--mode graph` gets misinterpreted by the default semantic mode instead
of erroring or hinting. Both are runtime self-correction, not just docs.
"""

import argparse
import os
import sys
import tempfile
from unittest import mock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from commands.search import (  # noqa: E402
    _detect_pattern_workspace_swap,
    execute,
)


class TestDetectPatternWorkspaceSwap:
    def test_pattern_is_existing_directory_flags_swap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            hint = _detect_pattern_workspace_swap(tmpdir, "some pattern")
        assert hint is not None
        assert "swapped" in hint

    def test_pattern_is_normal_string_no_hint(self):
        assert _detect_pattern_workspace_swap("getAccessMode", ".") is None

    def test_none_pattern_no_crash(self):
        assert _detect_pattern_workspace_swap(None, ".") is None


class TestSearchExecuteHints:
    def _args(self, pattern, mode="semantic"):
        return argparse.Namespace(
            pattern=pattern, mode=mode, top=None, db_path=None,
            file_type=None, file=None, max_results=200, context=0,
            ignore_case=False, whole_word=False, domain=None, fuzzy=False,
            validate=False, limit=None, offset=0,
        )

    def test_argument_swap_produces_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch("commands.search._run_semantic", return_value={"status": "ok"}):
            result = execute(self._args(pattern=tmpdir), tmpdir)
        assert result.get("_hints")
        assert any("swapped" in h for h in result["_hints"])

    def test_cypher_pattern_auto_routes_to_graph_mode(self):
        with mock.patch("commands.search._run_graph", return_value={"status": "ok"}) as mock_graph, \
             mock.patch("commands.search._run_semantic") as mock_semantic:
            args = self._args(pattern="MATCH (n) RETURN n LIMIT 5", mode="semantic")
            result = execute(args, ".")

        mock_graph.assert_called_once()
        mock_semantic.assert_not_called()
        assert result["st"]["mode"] == "graph"
        assert result.get("_hints")
        assert any("auto-routed" in h for h in result["_hints"])

    def test_cypher_pattern_with_explicit_graph_mode_no_hint(self):
        """If the caller already passed --mode graph, no hint is needed —
        the auto-route heuristic should be a no-op, not noisy."""
        with mock.patch("commands.search._run_graph", return_value={"status": "ok"}):
            args = self._args(pattern="MATCH (n) RETURN n LIMIT 5", mode="graph")
            result = execute(args, ".")
        assert not result.get("_hints")

    def test_normal_symbol_query_no_hints(self):
        with mock.patch("commands.search._run_symbol", return_value={"status": "ok", "results": []}):
            args = self._args(pattern="getAccessMode", mode="symbol")
            result = execute(args, ".")
        assert "_hints" not in result

    def test_regex_pattern_resembling_but_not_cypher_not_rerouted(self):
        """A regex pattern that merely contains the word MATCH somewhere
        (not at the start followed by a paren) must not be reinterpreted
        as Cypher — only high-confidence matches auto-route."""
        with mock.patch("commands.search._run_regex", return_value={"status": "ok", "matches": []}) as mock_regex, \
             mock.patch("commands.search._run_graph") as mock_graph:
            args = self._args(pattern="function MATCHER(x) {", mode="regex")
            result = execute(args, ".")
        mock_graph.assert_not_called()
        mock_regex.assert_called_once()
        assert "_hints" not in result
