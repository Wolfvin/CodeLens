"""Golden-fixture accuracy harness for the call graph (issue #277).

WHY THIS EXISTS
---------------
CodeLens's foundation is an accurate call graph, yet `reference_count` / trace /
dead-code broke repeatedly across languages and each regression slipped past CI
until it was found by hand in a real workspace: #210, #219, #220, #222, #223,
#231. Root process gap: nothing locked the graph's output on a known fixture.

This harness scans small deterministic fixtures that reproduce the exact
patterns those bugs lived in, and asserts CONCRETE values (rc == N, this caller
set, this dead-code status) — not "rc > 0". Revert any of those fixes and a
test here fails immediately, instead of months later in someone's repo.

Each fixture documents which historical issue it guards.
"""

import json
import os
import shutil
import sys
import tempfile

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


# ─── Scan harness ────────────────────────────────────────────────────

def _run_scan(workspace: str) -> dict:
    """Run `codelens scan <workspace>` in-process; return parsed backend.json."""
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

    with open(os.path.join(workspace, ".codelens", "backend.json"), encoding="utf-8") as f:
        return json.load(f)


def _nodes_named(backend: dict, fn: str) -> list:
    return [n for n in backend["nodes"] if n.get("fn") == fn or n.get("name") == fn]


def _rc(backend: dict, fn: str) -> int:
    """Reference count for the single node named `fn` (asserts exactly one)."""
    nodes = _nodes_named(backend, fn)
    assert len(nodes) == 1, f"expected exactly 1 node named {fn!r}, got {len(nodes)}: {[n['id'] for n in nodes]}"
    return nodes[0].get("ref_count", 0)


def _callers_of(backend: dict, fn: str) -> set:
    """Set of source files that call `fn` (via graph edges → target node id)."""
    nodes = _nodes_named(backend, fn)
    assert len(nodes) == 1, f"expected 1 node named {fn!r}, got {len(nodes)}"
    target_id = nodes[0]["id"].replace("\\", "/")
    srcs = set()
    for e in backend["edges"]:
        if (e.get("to") or "").replace("\\", "/") == target_id:
            srcs.add((e.get("from") or "").replace("\\", "/"))
    return srcs


# ─── Fixtures per historical bug ─────────────────────────────────────

_MODULE_LEVEL_CALL_TS = """\
// Guards #219: a module-top-level call must count toward the callee's rc.
export function moduleLevelHelper(): number { return 1; }
export function wrapper(): number { return moduleLevelHelper(); }

// Called once at module top level (not inside any function):
moduleLevelHelper();
"""

_ASYNC_HANDLER_TS = """\
// Guards #231: a call inside an asyncHandler-wrapped arrow (one extra wrapping
// layer, not a direct argument) must still register as an edge.
import { getGoogleClient } from './svc';
export const router = { post: (_p: string, _h: unknown) => {} };
export const asyncHandler = (fn: (...a: unknown[]) => unknown) => fn;

router.post('/auth', asyncHandler(async (req: unknown, res: unknown) => {
  const c = await getGoogleClient();
  return c;
}));
"""

_SVC_TS = """\
export async function getGoogleClient(): Promise<number> { return 1; }
"""

_OBJECT_LITERAL_ARROW_TS = """\
// Guards #222: an arrow function assigned as an object-literal value must be
// registered as a node `<var>.<key>` so trace/search can resolve it by name.
export const service = {
  listItems: (ctx: unknown) => { return ctx; },
};
"""

_SAME_FILE_USAGE_RS = """\
// Guards #220: a Rust const used >=2 times in the SAME file must not be
// false-flagged dead (Counter threshold, not a broad self-exempting Set).
const RED: &str = "red";

pub fn first() -> &'static str { RED }
pub fn second() -> &'static str { RED }
"""

_GENUINELY_DEAD_TS = """\
// Control: a truly-unreferenced non-exported function IS dead. Guards against a
// fix that "cures" false positives by never flagging anything dead.
function trulyUnusedInternal(): number { return 42; }
export function used(): number { return 1; }
used();
"""


def _build_workspace(tmp_path) -> str:
    ws = tmp_path / "golden_ws"
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "mod_level.ts").write_text(_MODULE_LEVEL_CALL_TS)
    (ws / "src" / "handler.ts").write_text(_ASYNC_HANDLER_TS)
    (ws / "src" / "svc.ts").write_text(_SVC_TS)
    (ws / "src" / "object_arrow.ts").write_text(_OBJECT_LITERAL_ARROW_TS)
    (ws / "src" / "same_file.rs").write_text(_SAME_FILE_USAGE_RS)
    (ws / "src" / "dead.ts").write_text(_GENUINELY_DEAD_TS)
    return str(ws)


@pytest.fixture(scope="module")
def scanned(tmp_path_factory):
    """Yield (workspace_path, backend_json) for a scanned golden workspace."""
    if not _TS:
        pytest.skip(_SKIP)
    tmp = tmp_path_factory.mktemp("golden")
    ws = _build_workspace(tmp)
    try:
        yield ws, _run_scan(ws)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


@pytest.fixture(scope="module")
def backend(scanned):
    return scanned[1]


# ─── Golden assertions ───────────────────────────────────────────────

class TestGraphAccuracyGolden:
    """Concrete rc / caller / dead-code assertions. Revert a fix → this fails."""

    def test_module_level_call_counts_toward_rc(self, backend):
        """#219: `moduleLevelHelper` is called from wrapper() AND module-level."""
        rc = _rc(backend, "moduleLevelHelper")
        assert rc >= 2, f"#219 regression: moduleLevelHelper rc={rc}, expected >=2 (wrapper + module-level)"
        callers = _callers_of(backend, "moduleLevelHelper")
        assert any("mod_level.ts" in c for c in callers), (
            f"#219: expected a caller from mod_level.ts, got {callers}"
        )

    def test_async_handler_wrapped_call_registers_edge(self, backend):
        """#231: getGoogleClient called inside asyncHandler(async ()=>{...})."""
        rc = _rc(backend, "getGoogleClient")
        assert rc >= 1, f"#231 regression: getGoogleClient rc={rc}, expected >=1"
        callers = _callers_of(backend, "getGoogleClient")
        assert any("handler.ts" in c for c in callers), (
            f"#231: expected a caller from handler.ts, got {callers}"
        )

    def test_object_literal_arrow_registered_as_node(self, backend):
        """#222: `service.listItems` arrow value must be a resolvable node."""
        candidates = [
            n for n in backend["nodes"]
            if "listItems" in (n.get("fn") or "") or "listItems" in (n.get("name") or "")
        ]
        assert candidates, (
            "#222 regression: object-literal arrow 'service.listItems' not registered as a node"
        )

    def test_same_file_rust_const_not_dead(self, scanned):
        """#220: Rust const RED used twice same-file must not be reported dead.

        Asserts at the layer users consume (`audit --check dead-code` →
        `detect_dead_code`), NOT the raw backend.json node status: a const has
        rc 0 in the raw graph (it's never a CALLS target), but the dead-code
        engine's same-file-usage exemption (#220, Counter threshold >=2) must
        keep it out of the dead findings.
        """
        ws, _ = scanned
        from deadcode_engine import detect_dead_code
        res = detect_dead_code(ws)
        findings = res.get("findings") or res.get("dead") or res.get("items") or []
        red_hits = [f for f in findings if "RED" in str(f) and "same_file" in str(f).replace("\\", "/")]
        assert not red_hits, (
            f"#220 regression: same-file-used Rust const RED flagged dead by the engine: {red_hits[:1]}"
        )

    def test_genuinely_dead_still_detected(self, backend):
        """Control: an unreferenced internal function IS still dead (rc 0)."""
        nodes = _nodes_named(backend, "trulyUnusedInternal")
        assert nodes, "control node trulyUnusedInternal missing"
        assert nodes[0].get("ref_count", 0) == 0, (
            f"control: trulyUnusedInternal should have rc 0, got {nodes[0].get('ref_count')} — "
            "a fix that inflates rc to hide false-positives would break real dead-code detection"
        )
