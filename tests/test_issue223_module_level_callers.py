"""Tests for issue #223 — module-level callers visible in trace/impact.

Background
----------
PR #219 (issue #210) fixed ``ref_count`` undercounting by adding a
synthetic ``source_id = "<file>:0:<module>"`` for module-top-level calls
(calls not nested in any function body). The synthetic id has NO matching
entry in ``graph_nodes`` (intentional — keeps ``list``/``search`` output
free of fake ``<module>`` function entries).

Pre-#223 this caused ``trace --direction up`` and ``impact`` to silently
drop all module-level callers: the BFS JOIN ``graph_nodes.node_id = ?``
returned no row, and the caller was skipped. ``ref_count`` (computed
from the target side) was correct, but ``trace``/``impact`` (computed
from the source side) were wrong — inconsistent and dangerous for
anyone using trace to decide "safe to delete?".

Issue #223 fix
--------------
``graph_model._bfs`` now emits a synthesized entry for synthetic
``<file>:0:<module>`` source_ids instead of dropping them.
``trace_engine._bfs_trace_graph`` preserves the ``module_level`` marker.
``impact_engine.analyze_impact`` emits a "module-level caller in <file>"
entry in ``affected["direct"]`` / ``affected["indirect"]`` when a
caller's ``from_id`` is a synthetic module-level id.

Constraint from issue #223: do NOT create a fake ``<module>`` node in
``graph_nodes`` — the fix must NOT pollute ``list``/``search`` output.
These tests verify that constraint too.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)


# ─── Test helpers ────────────────────────────────────────────────


def _make_workspace_with_module_level_caller():
    """Build a temp workspace whose backend.json contains one module-level caller.

    Workspace structure:
      workspace/
      └── .codelens/
          └── backend.json     # flat registry with the test fixture

    Fixture:
      nodes:
        - requirePermission (the call target — what we trace up from)
      edges:
        - {from: "<module>:0:<module>", to: "routes.ts:10:requirePermission", to_fn: "requirePermission"}
          (synthetic source_id — no matching node entry, mimics PR #219)
        - {from: "routes.ts:5:handler", to: "routes.ts:10:requirePermission", to_fn: "requirePermission"}
          (regular resolved caller — control case)

    Returns the workspace path. Caller is responsible for cleanup.
    """
    workspace = tempfile.mkdtemp(prefix="codelens_issue223_")
    codelens_dir = os.path.join(workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)

    # Backend registry fixture. The synthetic module-level caller has
    # ``from = "routes.ts:0:<module>"`` (no node entry). The regular
    # caller has ``from = "routes.ts:5:handler"`` with a matching node.
    registry = {
        "workspace": workspace,
        "last_updated": "2026-07-12T00:00:00+00:00",
        "nodes": [
            {
                "id": "routes.ts:10:requirePermission",
                "fn": "requirePermission",
                "type": "function",
                "file": "routes.ts",
                "line": 10,
            },
            {
                "id": "routes.ts:5:handler",
                "fn": "handler",
                "type": "function",
                "file": "routes.ts",
                "line": 5,
            },
        ],
        "edges": [
            # Module-level caller — synthetic source_id (NO matching node)
            {
                "from": "routes.ts:0:<module>",
                "to": "routes.ts:10:requirePermission",
                "to_fn": "requirePermission",
                "resolved": True,
            },
            # Regular resolved caller — has a matching node entry
            {
                "from": "routes.ts:5:handler",
                "to": "routes.ts:10:requirePermission",
                "to_fn": "requirePermission",
                "resolved": True,
            },
        ],
    }

    with open(os.path.join(codelens_dir, "backend.json"), "w", encoding="utf-8") as f:
        json.dump(registry, f)

    return workspace


def _populate_graph_tables(workspace):
    """Populate graph_nodes + graph_edges from the workspace's backend.json.

    Calls the real ``populate_graph_tables`` function — same code path as
    a fresh ``codelens scan`` would trigger. This ensures the SQLite
    schema matches what trace_engine / query_callers expect.
    """
    from graph_model import populate_graph_tables, default_db_path

    db_path = default_db_path(workspace)
    populate_graph_tables(workspace, db_path)
    return db_path


# ─── 1. Helper detection ─────────────────────────────────────────


class TestModuleLevelSourceIdDetection:
    """Verify is_module_level_source_id correctly identifies synthetic ids."""

    def test_recognizes_synthetic_id(self):
        from graph_model import is_module_level_source_id
        assert is_module_level_source_id("routes.ts:0:<module>") is True

    def test_recognizes_synthetic_id_with_path(self):
        from graph_model import is_module_level_source_id
        assert is_module_level_source_id("src/routes/accounting.ts:0:<module>") is True

    def test_rejects_real_node_id(self):
        from graph_model import is_module_level_source_id
        # Real node id — has actual line number and function name
        assert is_module_level_source_id("routes.ts:42:requirePermission") is False

    def test_rejects_real_node_id_line_0(self):
        from graph_model import is_module_level_source_id
        # Edge case: a real function at line 0 named "foo" — exotic but real.
        # Detection requires the literal <module> suffix, so this is rejected.
        assert is_module_level_source_id("routes.ts:0:foo") is False

    def test_rejects_empty(self):
        from graph_model import is_module_level_source_id
        assert is_module_level_source_id("") is False
        assert is_module_level_source_id(None) is False  # type: ignore[arg-type]


# ─── 2. graph_model.query_callers emits module-level caller ─────


class TestQueryCallersModuleLevel:
    """Verify query_callers returns module-level callers instead of dropping them."""

    def test_callers_include_module_level_entry(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            db_path = _populate_graph_tables(workspace)
            from graph_model import query_callers

            callers = query_callers(
                "routes.ts:10:requirePermission", db_path, max_depth=1
            )

            # Should have 2 callers: the regular handler + the module-level one.
            assert len(callers) == 2, (
                f"expected 2 callers (handler + module-level), got {len(callers)}: "
                f"{callers}"
            )

            module_level_callers = [c for c in callers if c.get("module_level")]
            assert len(module_level_callers) == 1, (
                f"expected 1 module-level caller, got {len(module_level_callers)}: "
                f"{callers}"
            )
            ml = module_level_callers[0]
            assert ml["node_id"] == "routes.ts:0:<module>"
            assert ml["node_type"] == "module"
            assert ml["file"] == "routes.ts"
            assert ml["resolved"] is True
            assert ml["cyclic"] is False
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_callers_include_regular_caller_unchanged(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            db_path = _populate_graph_tables(workspace)
            from graph_model import query_callers

            callers = query_callers(
                "routes.ts:10:requirePermission", db_path, max_depth=1
            )

            regular_callers = [c for c in callers if not c.get("module_level")]
            assert len(regular_callers) == 1
            assert regular_callers[0]["node_id"] == "routes.ts:5:handler"
            assert regular_callers[0]["name"] == "handler"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 3. trace_engine.trace_via_graph shows module-level caller ──


class TestTraceModuleLevelCaller:
    """Verify trace --direction up shows module-level callers (DoD #1)."""

    def test_trace_up_includes_module_level_caller(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            _populate_graph_tables(workspace)
            from trace_engine import trace_via_graph

            result = trace_via_graph(
                "requirePermission", workspace,
                direction="up", max_depth=3, domain="backend",
            )

            up_chain = result["chains"]["up"]
            # Depth 0 = start node (requirePermission itself).
            # Depth 1+ = callers. Should include both handler and <module>.
            assert len(up_chain) >= 2, (
                f"expected at least 2 chain entries (start + 2 callers), got {len(up_chain)}: "
                f"{up_chain}"
            )

            module_level_entries = [c for c in up_chain if c.get("module_level")]
            assert len(module_level_entries) >= 1, (
                f"expected at least 1 module_level entry in up chain, got 0. "
                f"Chain: {up_chain}"
            )
            ml = module_level_entries[0]
            assert ml["fn"] == "<module>"
            assert ml["file"] == "routes.ts"
            assert ml["node_id"] == "routes.ts:0:<module>"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_trace_up_module_level_caller_not_enqueued_for_bfs(self):
        """Module-level callers are terminal — no further BFS beyond them.

        Otherwise we'd risk infinite loops if a module-level edge happens
        to point back to a node we've already visited.
        """
        workspace = _make_workspace_with_module_level_caller()
        try:
            _populate_graph_tables(workspace)
            from trace_engine import trace_via_graph

            result = trace_via_graph(
                "requirePermission", workspace,
                direction="up", max_depth=5, domain="backend",
            )
            up_chain = result["chains"]["up"]

            # No chain entry should claim to be a 2-hop caller from
            # requirePermission (we only have 1-hop callers in the fixture).
            # Specifically, no entry should be a "module-level caller of a
            # module-level caller" — that's nonsensical.
            depth_2_entries = [c for c in up_chain if c.get("depth", 0) >= 2]
            assert depth_2_entries == [], (
                f"module-level caller should be terminal (no BFS beyond it), "
                f"but got depth-2+ entries: {depth_2_entries}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 4. impact_engine.analyze_impact shows module-level dependent ──


class TestImpactModuleLevelDependent:
    """Verify impact shows module-level callers as dependents (DoD #2)."""

    def test_impact_direct_includes_module_level_caller(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            from impact_engine import analyze_impact

            result = analyze_impact(
                "requirePermission", workspace,
                action="modify", domain="backend", depth=3,
            )

            direct = result["affected"]["direct"]
            module_level_direct = [
                d for d in direct if d.get("module_level")
            ]
            assert len(module_level_direct) >= 1, (
                f"expected at least 1 module_level entry in affected.direct, got 0. "
                f"direct: {direct}"
            )
            ml = module_level_direct[0]
            assert ml["name"] == "<module>"
            assert ml["file"] == "routes.ts"
            assert "module-level caller" in ml["relation"]
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_impact_dependent_count_includes_module_level(self):
        """DoD #2: dependent count must be consistent with rc.

        With 2 callers in the fixture (1 module-level + 1 regular),
        affected.direct should have 2 entries — not 1 (pre-#223 behavior).
        """
        workspace = _make_workspace_with_module_level_caller()
        try:
            from impact_engine import analyze_impact

            result = analyze_impact(
                "requirePermission", workspace,
                action="modify", domain="backend", depth=3,
            )
            direct = result["affected"]["direct"]
            # Filter out impl-siblings / callees — only count "calls X" relations
            # (i.e., direct callers, not "called by X" entries).
            direct_callers = [
                d for d in direct
                if d.get("relation", "").startswith("calls ")
                or d.get("relation", "").startswith("module-level caller")
            ]
            assert len(direct_callers) == 2, (
                f"expected 2 direct callers (handler + module-level), got "
                f"{len(direct_callers)}: {direct_callers}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 5. Constraint: list/search NOT polluted with <module> entries ──


class TestListSearchNotPolluted:
    """DoD #3: list/search --mode symbol must NOT show fake <module> entries.

    The fix must NOT create a fake ``<module>`` node in ``graph_nodes`` —
    constraint from issue #223. The synthetic source_id stays edge-only.
    """

    def test_graph_nodes_has_no_module_entry(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            db_path = _populate_graph_tables(workspace)
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute(
                    "SELECT node_id, name FROM graph_nodes "
                    "WHERE node_id LIKE '%:0:<module>' OR name = '<module>'"
                ).fetchall()
                assert rows == [], (
                    f"graph_nodes must NOT contain synthetic <module> entries "
                    f"(constraint from #223), but found: {rows}"
                )
            finally:
                conn.close()
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_find_nodes_by_name_does_not_return_module(self):
        """find_nodes_by_name is what powers list/search — must not return <module>."""
        workspace = _make_workspace_with_module_level_caller()
        try:
            db_path = _populate_graph_tables(workspace)
            from graph_model import find_nodes_by_name

            # Searching for "<module>" should return nothing — no node exists.
            results = find_nodes_by_name("<module>", db_path)
            assert results == [], (
                f"find_nodes_by_name('<module>') must return [] (no fake node), "
                f"got: {results}"
            )

            # Searching for "requirePermission" should return only the real node.
            results = find_nodes_by_name("requirePermission", db_path)
            assert len(results) == 1
            assert results[0]["name"] == "requirePermission"
            assert results[0]["node_id"] == "routes.ts:10:requirePermission"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 6. Regression: regular resolved callers still work ─────────


class TestRegularCallersUnchanged:
    """Make sure the fix didn't break the pre-existing resolved-caller path."""

    def test_regular_caller_still_in_trace(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            _populate_graph_tables(workspace)
            from trace_engine import trace_via_graph

            result = trace_via_graph(
                "requirePermission", workspace,
                direction="up", max_depth=3, domain="backend",
            )
            up_chain = result["chains"]["up"]

            # The regular handler caller must still be in the chain.
            handler_entries = [
                c for c in up_chain
                if c.get("fn") == "handler" and not c.get("module_level")
            ]
            assert len(handler_entries) == 1, (
                f"regular caller 'handler' missing from chain. Chain: {up_chain}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_regular_caller_still_in_impact(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            from impact_engine import analyze_impact

            result = analyze_impact(
                "requirePermission", workspace,
                action="modify", domain="backend", depth=3,
            )
            direct = result["affected"]["direct"]

            handler_entries = [
                d for d in direct
                if d.get("name") == "handler" and not d.get("module_level")
            ]
            assert len(handler_entries) == 1, (
                f"regular caller 'handler' missing from impact.direct. "
                f"direct: {direct}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ─── 7. Pure-impact-engine test (no SQLite, flat registry only) ──


class TestImpactEngineDirectly:
    """Verify impact_engine's module-level handling without graph_model.

    impact_engine reads from the flat-registry (backend.json), not from
    SQLite. This test confirms the fix works on the flat-registry path
    independently of the graph backend.
    """

    def test_impact_emits_module_level_entry_for_synthetic_from_id(self):
        workspace = _make_workspace_with_module_level_caller()
        try:
            from impact_engine import analyze_impact, _file_from_module_level_id

            # Sanity check the helper
            assert _file_from_module_level_id("routes.ts:0:<module>") == "routes.ts"
            assert _file_from_module_level_id("not-a-module-id") == ""

            result = analyze_impact(
                "requirePermission", workspace,
                action="modify", domain="backend", depth=1,
            )
            direct = result["affected"]["direct"]

            module_entries = [d for d in direct if d.get("module_level")]
            assert len(module_entries) == 1
            assert module_entries[0]["type"] == "module"
            assert module_entries[0]["name"] == "<module>"
            assert module_entries[0]["file"] == "routes.ts"
            assert module_entries[0]["line"] == 0
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
