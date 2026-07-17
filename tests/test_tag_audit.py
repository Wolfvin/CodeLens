"""
Tests for the doc-tag audit engine (issue #305).

Covers, against a synthetic fixture tree (not just a self-scan):
- flow inventory: distinct names, locations, first-token naming
- header coverage: full / partial / none classification
- prose-mention rejection: `@FLOW:` inside backticks must not count
- determinism: sorted output
- read-only: the scan never writes to source
"""

from __future__ import annotations

import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from tag_audit_engine import audit_tags, _flow_name  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


@pytest.fixture
def tree(tmp_path):
    root = str(tmp_path)
    # Full header + a named flow (Python).
    _write(root, "full.py",
           "# @WHO:   full.py\n"
           "# @WHAT:  a thing\n"
           "# @PART:  engine\n"
           "# @ENTRY: run()\n"
           "def run():\n"
           "    '''Charge the cart.\n"
           "\n"
           "    @FLOW:    PAYMENT_FLOW\n"
           "    @CALLS: charge()\n"
           "    @MUTATES: nothing\n"
           "    '''\n")
    # Partial header — missing PART and ENTRY.
    _write(root, "partial.py",
           "# @WHO:  partial.py\n"
           "# @WHAT: half-documented\n"
           "x = 1\n")
    # No tags at all.
    _write(root, "bare.py", "y = 2\n")
    # TS file, full header + flow via // comments (language-agnostic).
    _write(root, "web/app.ts",
           "// @WHO:   app.ts\n"
           "// @WHAT:  ui\n"
           "// @PART:  frontend\n"
           "// @ENTRY: main()\n"
           "// @FLOW:  PAYMENT_FLOW\n"
           "export function main() {}\n")
    # A file that DOCUMENTS the convention in prose — must NOT register flows.
    _write(root, "docs_mention.py",
           '"""Explains the tags.\n'
           "The `@FLOW: GHOST_FLOW` marker names a chain; `@WHO` heads a file.\n"
           '"""\n')
    return root


def test_flow_inventory_lists_distinct_names(tree):
    result = audit_tags(tree)
    names = [f["name"] for f in result["flows"]]

    assert names == ["PAYMENT_FLOW"]  # sorted, distinct, prose GHOST_FLOW excluded


def test_flow_records_all_declaration_sites(tree):
    result = audit_tags(tree)
    payment = next(f for f in result["flows"] if f["name"] == "PAYMENT_FLOW")

    assert payment["count"] == 2  # full.py + web/app.ts
    assert payment["locations"] == sorted(payment["locations"])
    assert any(loc.startswith("full.py:") for loc in payment["locations"])
    assert any(loc.startswith("web/app.ts:") for loc in payment["locations"])


def test_prose_mention_is_not_counted_as_a_flow(tree):
    result = audit_tags(tree)
    names = [f["name"] for f in result["flows"]]

    assert "GHOST_FLOW" not in names


def test_prose_mention_file_counts_as_untagged(tree):
    """docs_mention.py names @WHO/@FLOW only in prose → no real header."""
    result = audit_tags(tree)

    assert "docs_mention.py" in result["untagged_files"]


def test_header_classification(tree):
    result = audit_tags(tree)
    s = result["summary"]

    assert s["with_full_header"] == 2       # full.py, web/app.ts
    assert s["with_partial_header"] == 1    # partial.py
    assert s["without_header"] == 2         # bare.py, docs_mention.py


def test_partial_header_reports_missing_tags(tree):
    result = audit_tags(tree)
    partial = next(p for p in result["partial_headers"] if p["file"] == "partial.py")

    assert partial["present"] == ["WHAT", "WHO"]
    assert partial["missing"] == ["PART", "ENTRY"]


def test_untagged_list_is_sorted(tree):
    result = audit_tags(tree)

    assert result["untagged_files"] == sorted(result["untagged_files"])


def test_output_is_deterministic(tree):
    assert audit_tags(tree) == audit_tags(tree)


def test_scan_is_read_only(tree):
    before = {
        rel: os.path.getmtime(os.path.join(tree, rel))
        for rel in ("full.py", "partial.py", "bare.py")
    }
    audit_tags(tree)
    after = {
        rel: os.path.getmtime(os.path.join(tree, rel))
        for rel in ("full.py", "partial.py", "bare.py")
    }

    assert before == after


# ─── _flow_name unit ─────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("PAYMENT_FLOW", "PAYMENT_FLOW"),
    ("PURE (declarations only)", "PURE"),
    ("  AUDIT_DISPATCH  ", "AUDIT_DISPATCH"),
    ("", ""),
])
def test_flow_name_takes_first_token(raw, expected):
    assert _flow_name(raw) == expected
