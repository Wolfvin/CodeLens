"""Tests for the markdown registry-diff renderer (issue #299).

_diff_backend() emits backend node entries keyed `name`, while _md_diff()
read `fn` and silently rendered every function name as an empty string.
These tests pin the producer/consumer contract on both sides.
"""

import os
import sys
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from diff_engine import _diff_backend  # noqa: E402
from formatters.markdown import to_markdown  # noqa: E402


def _render(backend, frontend=None):
    return to_markdown(
        {"status": "ok", "frontend": frontend or {}, "backend": backend}, "diff"
    )


class TestBackendNodeNamesRendered(unittest.TestCase):
    """Backend function names must reach the markdown output."""

    def test_added_node_name_is_rendered(self):
        out = _render({
            "added_count": 1, "removed_count": 0, "changed_count": 0,
            "added_nodes": [{"name": "freshFn", "file": "a.py", "status": "active"}],
            "removed_nodes": [], "changed_nodes": [],
        })
        self.assertIn("freshFn", out)
        self.assertIn("a.py", out)
        self.assertNotIn("- + ``", out)

    def test_removed_node_name_is_rendered(self):
        out = _render({
            "added_count": 0, "removed_count": 1, "changed_count": 0,
            "added_nodes": [], "changed_nodes": [],
            "removed_nodes": [{"name": "goneFn", "file": "a.py"}],
        })
        self.assertIn("goneFn", out)
        self.assertNotIn("- - ``", out)

    def test_changed_node_name_is_rendered(self):
        out = _render({
            "added_count": 0, "removed_count": 0, "changed_count": 1,
            "added_nodes": [], "removed_nodes": [],
            "changed_nodes": [
                {"name": "movedFn", "file": "a.py",
                 "ref_count": {"from": 2, "to": 1}}
            ],
        })
        self.assertIn("movedFn", out)
        self.assertNotIn("- ~ ``", out)


class TestContractWithProducer(unittest.TestCase):
    """Render real _diff_backend() output, not a hand-written stand-in."""

    def test_real_diff_backend_output_renders_names(self):
        old = {
            "nodes": [{"id": "a.py:1", "fn": "goneFn", "file": "a.py",
                       "ref_count": 1, "status": "active"}],
            "edges": [],
        }
        new = {
            "nodes": [{"id": "a.py:9", "fn": "freshFn", "file": "a.py",
                       "ref_count": 1, "status": "active"}],
            "edges": [],
        }

        out = _render(_diff_backend(old, new))

        self.assertIn("freshFn", out)
        self.assertIn("goneFn", out)


class TestFrontendNotRegressed(unittest.TestCase):
    """The frontend block already read `name` correctly — keep it that way."""

    def test_frontend_class_names_still_rendered(self):
        out = _render(
            {},
            frontend={
                "added_count": 1, "removed_count": 0, "changed_count": 0,
                "added_classes": [{"name": "btn-primary", "status": "active"}],
                "removed_classes": [], "changed_classes": [],
                "added_ids": [], "removed_ids": [], "changed_ids": [],
            },
        )
        self.assertIn("btn-primary", out)


if __name__ == "__main__":
    unittest.main()
