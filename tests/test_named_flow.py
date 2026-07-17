"""
Tests for the named-flow view (`context --check flow`, issue #309).

Covers, against a synthetic fixture tree:
- enclosing-symbol resolution: docstring idiom, comment-above-def idiom,
  file-header fallback, and look-ahead not binding across real code.
- cross-language collection of one flow.
- the `flow` command: --name filter (found + not-found), bare inventory.
"""

from __future__ import annotations

import argparse
import os
import sys

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from tag_audit_engine import audit_tags  # noqa: E402
from commands import flow as flow_cmd  # noqa: E402


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


@pytest.fixture
def tree(tmp_path):
    root = str(tmp_path)
    # Docstring idiom: tag inside the function body -> enclosing def above.
    _write(root, "routes.py",
           'def checkout_route(req):\n'
           '    """Entry.\n'
           '    @FLOW: PAYMENT\n'
           '    """\n'
           '    return validate(req)\n')
    # Comment-above-def idiom (JS): tag one line above the declaration.
    _write(root, "gateway.js",
           '// @FLOW: PAYMENT\n'
           'export function charge(amount) {\n'
           '  return stripe(amount);\n'
           '}\n')
    # File-header idiom: tag at the very top, no def near -> file fallback.
    _write(root, "types.d.ts",
           '// @WHO:   types.d.ts\n'
           '// @FLOW:  PURE (declarations only)\n'
           '\n'
           'export type Money = number;\n')
    return root


def _flows(root):
    return {f["name"]: f for f in audit_tags(root)["flows"]}


# ─── enclosing-symbol resolution ─────────────────────────

def test_docstring_tag_binds_to_enclosing_function(tree):
    members = {(m["file"], m["symbol"]) for m in _flows(tree)["PAYMENT"]["members"]}
    assert ("routes.py", "checkout_route") in members


def test_comment_above_def_binds_to_def_below(tree):
    members = {(m["file"], m["symbol"]) for m in _flows(tree)["PAYMENT"]["members"]}
    assert ("gateway.js", "charge") in members


def test_file_header_tag_falls_back_to_file(tree):
    pure = _flows(tree)["PURE"]["members"]
    assert len(pure) == 1
    assert pure[0]["symbol"] == ""          # no enclosing symbol -> file-level
    assert pure[0]["file"] == "types.d.ts"


def test_lookahead_does_not_cross_real_code(tmp_path):
    """A docstring tag must not bind to a nested def a few lines down."""
    root = str(tmp_path)
    _write(root, "a.py",
           'def outer():\n'
           '    """\n'
           '    @FLOW: OUTER\n'
           '    """\n'
           '    x = 1\n'
           '    def inner():\n'
           '        pass\n')
    members = _flows(root)["OUTER"]["members"]
    assert members[0]["symbol"] == "outer"   # not "inner"


def test_flow_collected_across_languages(tree):
    payment = _flows(tree)["PAYMENT"]
    assert payment["count"] == 2
    files = {m["file"] for m in payment["members"]}
    assert files == {"routes.py", "gateway.js"}


# ─── the flow command ────────────────────────────────────

def _run(root, name=None):
    args = argparse.Namespace(name=name)
    return flow_cmd.execute(args, root)


def test_named_flow_returns_only_that_flow(tree):
    out = _run(tree, "PAYMENT")
    assert out["found"] is True
    assert out["flow"] == "PAYMENT"
    assert out["count"] == 2
    assert {m["symbol"] for m in out["members"]} == {"checkout_route", "charge"}


def test_unknown_flow_is_not_found_with_available_list(tree):
    out = _run(tree, "NOPE")
    assert out["found"] is False
    assert out["count"] == 0
    assert "PAYMENT" in out["available_flows"]


def test_bare_flow_lists_every_flow(tree):
    out = _run(tree)
    names = {f["name"] for f in out["flows"]}
    assert {"PAYMENT", "PURE"} <= names
    assert out["summary"]["distinct_flows"] == len(out["flows"])


if __name__ == "__main__":
    import pytest as _p
    _p.main([__file__, "-v"])
