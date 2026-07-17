"""
Tests for umbrella envelope rendering in markdown + ai formats (issue #306).

The #195 command consolidation wraps sub-check output in an envelope
``{s, st, r:[...]}``. The markdown and ai formatters never learned that shape,
so every umbrella sub-check rendered empty ("Symbol not found") or with an
empty ``items`` list. These tests pin the unwrap.
"""

import os
import sys
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from formatters.markdown import to_markdown  # noqa: E402
from formatters import _normalize_to_ai  # noqa: E402


def _envelope(sub):
    """Wrap a sub-result the way an umbrella command does."""
    return {"s": "ok", "st": {"checks_requested": 1, "checks_run": 1, "checks_failed": 0}, "r": [sub]}


_TAGS_SUB = {
    "status": "ok",
    "_check": "tags",
    "summary": {
        "files_scanned": 10, "with_full_header": 4, "with_partial_header": 1,
        "without_header": 5, "header_coverage_pct": 50.0, "distinct_flows": 2,
        "total_flow_declarations": 2,
    },
    "flows": [
        {"name": "PAYMENT", "count": 2, "locations": ["a.py:1", "b.py:9"]},
        {"name": "AUTH", "count": 1, "locations": ["c.py:3"]},
    ],
    "partial_headers": [{"file": "d.py", "present": ["WHO"], "missing": ["WHAT", "PART", "ENTRY"]}],
    "partial_headers_truncated": False,
    "untagged_files": ["e.py", "f.py"],
    "untagged_files_truncated": False,
}


class TestMarkdownEnvelope(unittest.TestCase):
    def test_tags_envelope_renders_content_not_symbol_not_found(self):
        out = to_markdown(_envelope(_TAGS_SUB), "context")

        self.assertNotIn("Symbol not found", out)
        self.assertIn("Doc-Tag Audit", out)
        self.assertIn("PAYMENT", out)
        self.assertIn("a.py:1", out)

    def test_tags_envelope_lists_partial_and_untagged(self):
        out = to_markdown(_envelope(_TAGS_SUB), "context")

        self.assertIn("d.py", out)          # partial header
        self.assertIn("WHAT", out)          # its missing tag
        self.assertIn("e.py", out)          # untagged file

    def test_envelope_dispatches_sub_to_its_own_handler(self):
        """A dead-code sub-result must reach the dead-code renderer, not generic."""
        sub = {"status": "ok", "_check": "dead-code", "dead_functions": [], "summary": {}}
        out = to_markdown(_envelope(sub), "audit")

        self.assertIn("Dead Code Analysis", out)

    def test_empty_envelope_is_not_a_crash(self):
        out = to_markdown({"s": "ok", "st": {}, "r": []}, "context")

        self.assertIn("No results", out)

    def test_non_umbrella_output_not_regressed(self):
        """A flat (non-envelope) result must still use its own handler."""
        out = to_markdown({"status": "ok", "dead_functions": [], "summary": {}}, "dead-code")

        self.assertIn("Dead Code Analysis", out)


class TestAiEnvelope(unittest.TestCase):
    def test_tags_envelope_populates_items(self):
        out = _normalize_to_ai(_envelope(_TAGS_SUB), "context")

        self.assertEqual(len(out["items"]), 2)             # the two flows
        self.assertEqual({i["name"] for i in out["items"]}, {"PAYMENT", "AUTH"})

    def test_tags_envelope_populates_stats(self):
        out = _normalize_to_ai(_envelope(_TAGS_SUB), "context")

        self.assertIn("tags", out["stats"])
        self.assertEqual(out["stats"]["tags"]["distinct_flows"], 2)

    def test_envelope_records_check_metadata(self):
        out = _normalize_to_ai(_envelope(_TAGS_SUB), "context")

        self.assertIn("checks", out["metadata"])

    def test_named_flow_members_become_items(self):
        """A single flow's members must surface as ai items (issue #309)."""
        flow_sub = {
            "status": "ok", "_check": "flow", "flow": "PAYMENT", "found": True,
            "count": 2,
            "members": [
                {"symbol": "charge", "file": "gw.js", "line": 2},
                {"symbol": "validate", "file": "cart.py", "line": 1},
            ],
        }
        out = _normalize_to_ai(_envelope(flow_sub), "context")

        self.assertEqual(len(out["items"]), 2)
        self.assertEqual({i["symbol"] for i in out["items"]}, {"charge", "validate"})


if __name__ == "__main__":
    unittest.main()
