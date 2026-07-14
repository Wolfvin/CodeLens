"""Regression guard for issue #228 — Rust modules / impl-blocks / trait-default
methods must NOT be false-flagged as dead code, while a genuinely-dead
standalone fn IS still flagged.

WHY THIS EXISTS
---------------
`audit --check dead-code` (→ `detect_dead_code` → `_detect_dead_from_registry`)
reads the backend registry and flags nodes with ref_count==0 / status=="dead".
Three Rust structural/implicit patterns produce ref_count==0 in the raw graph
even though they are never dead:

  1. Module declarations (`mod foo { ... }`) — a namespace referenced by path,
     never "called", so it emits no CALLS edge.
  2. Impl blocks (synthetic `impl X` node, id `file.rs:LINE:impl:X`) — only the
     methods inside are individually analyzed; the block itself is a container.
  3. Trait-default methods (`default`, `clone`, `fmt`, `drop`, `eq`, `hash`, …)
     — invoked implicitly via derive macros / `..Default::default()` / generic
     trait dispatch, which the CALLS extractor can't see.

The control (`orphan_helper`) is a truly-unreferenced standalone fn: it MUST
still be reported dead, proving the fix narrows false positives without
disabling genuine detection.
"""

import os
import shutil
import sys

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


def _tree_sitter_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        return True
    except ImportError:
        return False


_TS = _tree_sitter_available()
_SKIP = "tree-sitter not installed"


# ─── Scan harness (mirrors tests/test_graph_accuracy_golden.py) ──────────

def _run_scan(workspace: str) -> None:
    """Run `codelens scan <workspace>` in-process to populate backend.json."""
    import io
    import contextlib
    from codelens import main as codelens_main

    old_argv = sys.argv
    old_cwd = os.getcwd()
    try:
        sys.argv = ["codelens", "scan", workspace]
        os.chdir(workspace)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                codelens_main()
            except SystemExit:
                pass
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


# ─── Fixture: one Rust file exercising all four patterns ─────────────────

_ISSUE228_RS = """\
// Guards #228: modules, impl-blocks and trait-default methods must NOT be
// flagged dead; a genuinely-unreferenced standalone fn MUST be.

pub struct Widget {
    label: String,
}

// (b) an impl block with a method that IS used (see `build` below).
impl Widget {
    pub fn describe(&self) -> &str {
        &self.label
    }
}

// (c) a trait-default method implemented via a trait impl. `default` is called
// implicitly through `Widget::default()` / `..Default::default()` mechanisms
// that the CALLS extractor cannot observe.
impl Default for Widget {
    fn default() -> Self {
        Widget { label: String::from("widget") }
    }
}

pub fn build() -> String {
    let w = Widget::default();
    w.describe().to_string()
}

// (d) GENUINELY dead: never referenced anywhere, not pub, not a trait method.
fn orphan_helper() -> i32 {
    99
}

// (a) a module declaration — a namespace referenced by path, never "called".
mod helpers {
    pub fn noop() {}
}
"""


def _norm(s: str) -> str:
    return str(s).replace("\\", "/")


@pytest.fixture(scope="module")
def findings(tmp_path_factory):
    """Scan a workspace with the issue #228 Rust fixture; return dead-code findings."""
    if not _TS:
        pytest.skip(_SKIP)
    ws = str(tmp_path_factory.mktemp("issue228") / "ws")
    os.makedirs(os.path.join(ws, "src"))
    with open(os.path.join(ws, "src", "widget.rs"), "w", encoding="utf-8") as f:
        f.write(_ISSUE228_RS)
    try:
        _run_scan(ws)
        from deadcode_engine import detect_dead_code
        res = detect_dead_code(ws)
        # registry_dead is where _detect_dead_from_registry results land.
        reg = res.get("results", {}).get("registry_dead", [])
        yield reg
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def _names(findings):
    return {_norm(f.get("name", "")) for f in findings}


class TestIssue228RustImplDead:
    """modules / impl-blocks / trait-defaults NOT dead; orphan fn IS dead."""

    def test_module_not_flagged(self, findings):
        blob = _norm(findings)
        assert not any(
            (f.get("type") == "module") or "helpers" in _norm(f.get("name", ""))
            for f in findings
        ), f"#228: module declaration false-flagged as dead: {findings}"

    def test_impl_block_not_flagged(self, findings):
        assert not any(
            (f.get("type") == "impl")
            or _norm(f.get("name", "")).startswith("impl_")
            or ":impl:" in _norm(f.get("name", ""))
            for f in findings
        ), f"#228: impl block false-flagged as dead: {findings}"

    def test_trait_default_method_not_flagged(self, findings):
        names = _names(findings)
        offenders = {n for n in names if n.split("::")[-1] == "default"}
        assert not offenders, (
            f"#228: trait-default method `default` false-flagged as dead: {offenders}"
        )

    def test_genuinely_dead_fn_is_flagged(self, findings):
        names = _names(findings)
        assert any(n.split("::")[-1] == "orphan_helper" for n in names), (
            "#228 control: genuinely-dead `orphan_helper` must still be flagged, "
            f"got dead names: {names}"
        )
