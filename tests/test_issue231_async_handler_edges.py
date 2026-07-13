"""Tests for issue #231 — calls inside asyncHandler-wrapped route handlers
missing from graph_edges.

Background
----------
Issue #231 reported that ``getGoogleClient`` showed ``rc:0`` in
``search --mode symbol`` even though it is called once inside a route
handler:

.. code-block:: typescript

   customerAuthRouter.post(
     '/auth/google',
     asyncHandler(async (req, res) => {
       const client = await getGoogleClient();
       res.json({ ok: true, client });
     })
   );

The parser (``TSBackendParser.extract_references``) was verified correct
in isolation — it emits the edge ``<file>:0:<module> → getGoogleClient``.
But after a fresh scan, the edge never reached ``backend.json`` and thus
never reached ``graph_edges``.

Root cause (different from the issue's hypothesis)
--------------------------------------------------
The issue hypothesised the bug was in ``graph_model.populate_graph_tables``
(baris ~330-375). Investigation proved the bug was UPSTREAM: the file
``src/routes/public/customer-auth.ts`` was being misclassified as a
**TSX frontend** file (not TS backend) by ``commands.scan.is_frontend_file``,
because the path contained ``/public/`` as a MIDDLE segment and
``is_frontend_file`` matched any path containing ``/public/`` — not just
paths starting with ``public/``.

TSX frontend parser does NOT extract backend call-graph edges, so every
call inside that file was silently dropped before reaching
``backend.json`` / ``graph_edges``.

Fix
---
``is_frontend_file`` and ``is_backend_file`` now match only as
workspace-root-relative path prefixes (``startswith``), NOT as
middle-segment substring matches. This is consistent with the semantic
of ``frontend_paths``/``backend_paths`` as workspace-root directories,
and is DIFFERENT from ``should_ignore`` (which intentionally matches
middle segments — ``node_modules`` can be nested in monorepos).

Regression safeguard
--------------------
Issue #219 fixed ``ref_count`` for direct-argument calls
(``router.post(path, requirePermission('admin'), handler)``). The #231
fix must not regress that — both patterns are tested below.
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


# ─── 1. Unit tests: is_frontend_file / is_backend_file ───────────────


class TestIsFrontendFileSegmentMatching:
    """Verify is_frontend_file only matches workspace-root-relative prefixes.

    Issue #231: previously matched any path containing ``/public/`` as a
    middle segment, misclassifying ``src/routes/public/customer-auth.ts``
    (a backend route file) as frontend TSX.
    """

    def _config(self, frontend_paths=None, backend_paths=None):
        return {
            "frontend_paths": frontend_paths if frontend_paths is not None
                else ["src/client/", "public/", "frontend/", "static/", "templates/"],
            "backend_paths": backend_paths if backend_paths is not None
                else ["src/server/", "src/api/", "src/"],
        }

    def test_public_at_root_matches_frontend(self):
        """``public/foo.ts`` IS a frontend file (workspace-root public/)."""
        from commands.scan import is_frontend_file
        assert is_frontend_file("public/foo.ts", self._config()) is True

    def test_src_client_matches_frontend(self):
        """``src/client/foo.ts`` IS a frontend file."""
        from commands.scan import is_frontend_file
        assert is_frontend_file("src/client/foo.ts", self._config()) is True

    def test_routes_public_does_not_match_frontend(self):
        """``src/routes/public/customer-auth.ts`` is NOT a frontend file.

        This is the core #231 regression: the path contains ``/public/``
        as a middle segment, but it is a backend route file, not a
        workspace-root ``public/`` static asset.
        """
        from commands.scan import is_frontend_file
        assert is_frontend_file(
            "src/routes/public/customer-auth.ts", self._config()
        ) is False

    def test_nested_public_does_not_match_frontend(self):
        """``packages/app/public/foo.ts`` is NOT a frontend file.

        ``frontend_paths`` identifies the workspace-root directory, not
        any directory with that name anywhere in the tree.
        """
        from commands.scan import is_frontend_file
        assert is_frontend_file(
            "packages/app/public/foo.ts", self._config()
        ) is False

    def test_unrelated_path_does_not_match_frontend(self):
        """``src/services/google.ts`` is NOT a frontend file."""
        from commands.scan import is_frontend_file
        assert is_frontend_file("src/services/google.ts", self._config()) is False

    def test_windows_backslash_normalized(self):
        """Backslash paths are normalized before matching."""
        from commands.scan import is_frontend_file
        # src\client\foo.ts → src/client/foo.ts → matches src/client/
        assert is_frontend_file("src\\client\\foo.ts", self._config()) is True
        # src\routes\public\customer-auth.ts → does NOT match (middle segment)
        assert is_frontend_file(
            "src\\routes\\public\\customer-auth.ts", self._config()
        ) is False


class TestIsBackendFileSegmentMatching:
    """Verify is_backend_file only matches workspace-root-relative prefixes."""

    def _config(self, frontend_paths=None, backend_paths=None):
        return {
            "frontend_paths": frontend_paths if frontend_paths is not None
                else ["src/client/", "public/", "frontend/", "static/", "templates/"],
            "backend_paths": backend_paths if backend_paths is not None
                else ["src/server/", "src/api/", "src/"],
        }

    def test_src_matches_backend(self):
        """``src/foo.ts`` IS a backend file (src/ is in backend_paths)."""
        from commands.scan import is_backend_file
        assert is_backend_file("src/foo.ts", self._config()) is True

    def test_src_routes_public_matches_backend(self):
        """``src/routes/public/customer-auth.ts`` IS a backend file.

        After the #231 fix, this path matches ``src/`` as a prefix and
        is correctly categorized as backend.
        """
        from commands.scan import is_backend_file
        assert is_backend_file(
            "src/routes/public/customer-auth.ts", self._config()
        ) is True

    def test_nested_src_does_not_match_backend(self):
        """``packages/app/src/foo.ts`` is NOT a backend file.

        ``backend_paths`` identifies the workspace-root directory, not
        any directory named ``src`` anywhere in the tree. Pre-#231 this
        would have matched via the middle-segment check.
        """
        from commands.scan import is_backend_file
        assert is_backend_file(
            "packages/app/src/foo.ts", self._config()
        ) is False


# ─── 2. File categorization via discover_files ───────────────────────


class TestDiscoverFilesCategorization:
    """Verify discover_files correctly categorizes .ts files in routes/public/."""

    def test_ts_in_routes_public_goes_to_js_backend(self, tmp_path):
        """``src/routes/public/customer-auth.ts`` must be categorized as
        js_backend (parsed by TSBackendParser), NOT tsx (frontend parser).

        Pre-#231 this was misclassified as tsx because the path contained
        ``/public/``.
        """
        from commands.scan import discover_files
        from registry import save_config

        # Build workspace
        ws = tmp_path / "ws"
        (ws / "src" / "routes" / "public").mkdir(parents=True)
        (ws / "src" / "services").mkdir(parents=True)
        (ws / "src" / "middleware").mkdir(parents=True)
        (ws / "src" / "utils").mkdir(parents=True)
        (ws / "src" / "client").mkdir(parents=True)

        (ws / "src" / "routes" / "public" / "customer-auth.ts").write_text(
            "export const x = 1;\n"
        )
        (ws / "src" / "services" / "google.ts").write_text(
            "export function getGoogleClient() { return null; }\n"
        )
        # A real frontend file — should still be categorized as tsx
        (ws / "src" / "client" / "App.tsx").write_text(
            "export function App() { return null; }\n"
        )

        # Default config (same as registry.load_config defaults)
        config = {
            "frontend_paths": ["src/client/", "public/", "frontend/", "static/", "templates/"],
            "backend_paths": ["src/server/", "src/api/", "src/"],
            "watch": False,
            "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
            "frameworks": [],
            "jsx_mode": False,
            "vue_mode": False,
            "svelte_mode": False,
            "tailwind_mode": False,
            "css_preprocessor": None,
        }
        save_config(str(ws), config)

        files = discover_files(str(ws), config)

        # The backend .ts files must be in js_backend
        js_backend_basenames = [os.path.basename(f) for f in files["js_backend"]]
        assert "customer-auth.ts" in js_backend_basenames, (
            f"customer-auth.ts should be in js_backend (TS backend parser), "
            f"got js_backend={js_backend_basenames}, tsx={[os.path.basename(f) for f in files['tsx']]}"
        )
        assert "google.ts" in js_backend_basenames, (
            f"google.ts should be in js_backend, got {js_backend_basenames}"
        )

        # The frontend .tsx file must still be in tsx (not regressed)
        tsx_basenames = [os.path.basename(f) for f in files["tsx"]]
        assert "App.tsx" in tsx_basenames, (
            f"App.tsx should be in tsx, got {tsx_basenames}"
        )

        # And customer-auth.ts must NOT be in tsx
        assert "customer-auth.ts" not in tsx_basenames, (
            f"customer-auth.ts must NOT be in tsx (frontend), got tsx={tsx_basenames}"
        )


# ─── 3. End-to-end: asyncHandler-wrapped call reaches graph_edges ────


# Fixture source code mimicking the KDS backend pattern from issue #231.
_ASYNC_HANDLER_ROUTE_TS = """\
// Reproduces issue #231 pattern: asyncHandler-wrapped route handler.
// The arrow function is NOT a direct argument to .post() — it is wrapped
// by asyncHandler(...) (a common Express pattern for auto-catching async errors).
import { Router } from 'express';
import { asyncHandler } from '../../utils/asyncHandler';
import { getGoogleClient } from '../../services/google';

export const customerAuthRouter = Router();

customerAuthRouter.post(
  '/auth/google',
  asyncHandler(async (req, res) => {
    const client = await getGoogleClient();
    res.json({ ok: true, client });
  })
);
"""

_GOOGLE_SERVICE_TS = """\
// Defines getGoogleClient so the resolver can find it as a target node.
export async function getGoogleClient(): Promise<unknown> {
  return null;
}
"""

_ASYNC_HANDLER_UTIL_TS = """\
// Minimal asyncHandler wrapper — common Express pattern.
export function asyncHandler<T extends (...args: any[]) => Promise<any>>(fn: T): T {
  return ((...args: any[]) => {
    const result = fn(...args);
    if (result && typeof result.then === 'function') {
      result.catch(args[2]);
    }
    return result;
  }) as T;
}
"""

# Issue #219 regression safeguard: direct-argument call pattern.
_DIRECT_ARG_ROUTE_TS = """\
// Issue #219 pattern: requirePermission is called DIRECTLY as argument
// to .post(), NOT wrapped by another function. This pattern was fixed
// by PR #219 and must not regress.
import { Router } from 'express';
import { requirePermission } from '../../middleware/auth';

export const adminRouter = Router();

adminRouter.post(
  '/admin/users',
  requirePermission('admin'),
  (req, res) => {
    res.json({ ok: true });
  }
);
"""

_AUTH_MIDDLEWARE_TS = """\
// Exports requirePermission so the parser registers it as a node.
export function requirePermission(role: string): (req: any, res: any, next: any) => void {
  return (req: any, res: any, next: any) => {
    if (req.user?.role === role) {
      next();
    } else {
      res.status(403).json({ error: 'forbidden' });
    }
  };
}
"""


def _build_issue231_workspace(tmp_path):
    """Build a workspace reproducing the issue #231 pattern.

    Structure:
      ws/
      ├── src/
      │   ├── routes/
      │   │   ├── public/
      │   │   │   └── customer-auth.ts   ← asyncHandler-wrapped (the #231 bug)
      │   │   └── admin-users.ts         ← direct-argument (#219 regression check)
      │   ├── services/
      │   │   └── google.ts              ← getGoogleClient definition
      │   ├── middleware/
      │   │   └── auth.ts                ← requirePermission definition
      │   └── utils/
      │       └── asyncHandler.ts        ← asyncHandler wrapper
      └── .codelens/                     ← created by scan

    Returns the workspace path.
    """
    ws = tmp_path / "issue231_ws"
    ws.mkdir()

    routes_public = ws / "src" / "routes" / "public"
    routes_public.mkdir(parents=True)
    (ws / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "services").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "middleware").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "utils").mkdir(parents=True, exist_ok=True)

    (routes_public / "customer-auth.ts").write_text(_ASYNC_HANDLER_ROUTE_TS)
    (ws / "src" / "routes" / "admin-users.ts").write_text(_DIRECT_ARG_ROUTE_TS)
    (ws / "src" / "services" / "google.ts").write_text(_GOOGLE_SERVICE_TS)
    (ws / "src" / "middleware" / "auth.ts").write_text(_AUTH_MIDDLEWARE_TS)
    (ws / "src" / "utils" / "asyncHandler.ts").write_text(_ASYNC_HANDLER_UTIL_TS)

    return str(ws)


def _run_scan(workspace):
    """Run ``codelens scan`` on the workspace via the in-process API.

    Returns the parsed scan-result JSON.
    """
    from codelens import main as codelens_main

    old_argv = sys.argv
    old_cwd = os.getcwd()
    try:
        sys.argv = ["codelens", "scan", workspace]
        os.chdir(workspace)
        codelens_main()
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)

    # Read the backend.json produced by scan
    backend_path = os.path.join(workspace, ".codelens", "backend.json")
    with open(backend_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _query_graph_edges(workspace, target_node_id=None, source_contains=None):
    """Query graph_edges from the workspace's SQLite DB.

    Returns a list of dicts: {source_id, target_id, edge_type, extra_json}.
    """
    db_path = os.path.join(workspace, ".codelens", "codelens.db")
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        sql = "SELECT source_id, target_id, edge_type, extra_json FROM graph_edges"
        conditions = []
        params = []
        if target_node_id is not None:
            # backend.json node ids use the OS-native separator (backslash on
            # Windows); graph_edges stores target_id with forward slashes.
            # Normalize both sides so the match is cross-platform (issue #268).
            conditions.append("REPLACE(target_id, '\\', '/') = ?")
            params.append(target_node_id.replace("\\", "/"))
        if source_contains is not None:
            conditions.append("source_id LIKE ?")
            params.append(f"%{source_contains}%")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [
            {
                "source_id": r[0],
                "target_id": r[1],
                "edge_type": r[2],
                "extra_json": r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


class TestAsyncHandlerEdgeReachesGraph:
    """End-to-end: the asyncHandler-wrapped call must reach graph_edges.

    This is the core regression test for issue #231. Before the fix,
    ``customer-auth.ts`` was misclassified as TSX (frontend), so the
    TS backend parser never ran on it — the edge
    ``customer-auth.ts:0:<module> → getGoogleClient`` was never emitted,
    never reached ``backend.json``, and never reached ``graph_edges``.
    """

    def test_getgoogleclient_edge_in_backend_json(self, tmp_path):
        """The resolved edge must be in backend.json after scan."""
        workspace = _build_issue231_workspace(tmp_path)
        try:
            backend = _run_scan(workspace)

            # Find getGoogleClient node
            ggc_nodes = [n for n in backend["nodes"] if n.get("fn") == "getGoogleClient"]
            assert len(ggc_nodes) == 1, (
                f"Expected 1 getGoogleClient node, got {len(ggc_nodes)}: {ggc_nodes}"
            )
            ggc_node_id = ggc_nodes[0]["id"]

            # Find edges targeting getGoogleClient's node_id
            ggc_edges = [
                e for e in backend["edges"]
                if e.get("to") == ggc_node_id
            ]
            assert len(ggc_edges) >= 1, (
                f"Expected >=1 edge targeting getGoogleClient "
                f"(node_id={ggc_node_id}), got {len(ggc_edges)}. "
                f"All edges: {backend['edges']}"
            )

            # Verify the edge source is the customer-auth.ts module-level caller
            ca_edges = [
                e for e in ggc_edges
                if "customer-auth" in e.get("from", "")
            ]
            assert len(ca_edges) == 1, (
                f"Expected 1 edge from customer-auth.ts to getGoogleClient, "
                f"got {len(ca_edges)}: {ca_edges}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_getgoogleclient_edge_in_graph_edges(self, tmp_path):
        """The resolved edge must be in SQLite graph_edges after scan."""
        workspace = _build_issue231_workspace(tmp_path)
        try:
            backend = _run_scan(workspace)

            ggc_nodes = [n for n in backend["nodes"] if n.get("fn") == "getGoogleClient"]
            assert len(ggc_nodes) == 1
            ggc_node_id = ggc_nodes[0]["id"]

            # Query graph_edges for CALLS edges targeting getGoogleClient
            edges = _query_graph_edges(workspace, target_node_id=ggc_node_id)
            calls_edges = [e for e in edges if e["edge_type"] == "CALLS"]
            assert len(calls_edges) >= 1, (
                f"Expected >=1 CALLS edge targeting getGoogleClient "
                f"(node_id={ggc_node_id}), got {len(calls_edges)}. "
                f"All matching edges: {edges}"
            )

            # Verify the edge source is the customer-auth.ts module-level caller
            ca_edges = [
                e for e in calls_edges
                if "customer-auth" in e["source_id"]
            ]
            assert len(ca_edges) == 1, (
                f"Expected 1 CALLS edge from customer-auth.ts to getGoogleClient, "
                f"got {len(ca_edges)}: {ca_edges}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_getgoogleclient_ref_count_at_least_one(self, tmp_path):
        """getGoogleClient's ref_count must be >= 1 after scan.

        This is the Definition of Done #1 from issue #231:
        ``search "getGoogleClient" <kds-path> --mode symbol`` shows ``rc >= 1``.
        """
        workspace = _build_issue231_workspace(tmp_path)
        try:
            backend = _run_scan(workspace)

            ggc_nodes = [n for n in backend["nodes"] if n.get("fn") == "getGoogleClient"]
            assert len(ggc_nodes) == 1
            ggc = ggc_nodes[0]
            assert ggc.get("ref_count", 0) >= 1, (
                f"Expected getGoogleClient ref_count >= 1, "
                f"got {ggc.get('ref_count')}. Full node: {ggc}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_customer_auth_file_categorized_as_backend(self, tmp_path):
        """The scan must categorize customer-auth.ts as js_backend, not tsx.

        This is the root-cause check — verifies the file categorization
        fix is exercised by the real scan pipeline.
        """
        workspace = _build_issue231_workspace(tmp_path)
        try:
            from commands.scan import discover_files
            from registry import load_config

            config = load_config(workspace)
            files = discover_files(workspace, config)

            js_backend_basenames = [os.path.basename(f) for f in files["js_backend"]]
            tsx_basenames = [os.path.basename(f) for f in files["tsx"]]

            assert "customer-auth.ts" in js_backend_basenames, (
                f"customer-auth.ts must be in js_backend. "
                f"js_backend={js_backend_basenames}, tsx={tsx_basenames}"
            )
            assert "customer-auth.ts" not in tsx_basenames, (
                f"customer-auth.ts must NOT be in tsx. tsx={tsx_basenames}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


class TestDirectArgumentPatternNoRegression:
    """Issue #219 regression safeguard: direct-argument calls still work.

    Pattern: ``router.post(path, requirePermission('admin'), handler)``
    — ``requirePermission`` is called DIRECTLY as an argument to ``.post()``,
    NOT wrapped by another function. PR #219 fixed ``ref_count`` for this
    pattern; the #231 fix must not regress it.
    """

    def test_requirepermission_edge_in_graph_edges(self, tmp_path):
        """The resolved edge for requirePermission must be in graph_edges."""
        workspace = _build_issue231_workspace(tmp_path)
        try:
            backend = _run_scan(workspace)

            rp_nodes = [
                n for n in backend["nodes"] if n.get("fn") == "requirePermission"
            ]
            assert len(rp_nodes) == 1, (
                f"Expected 1 requirePermission node, got {len(rp_nodes)}: {rp_nodes}"
            )
            rp_node_id = rp_nodes[0]["id"]

            # Query graph_edges for CALLS edges targeting requirePermission
            edges = _query_graph_edges(workspace, target_node_id=rp_node_id)
            calls_edges = [e for e in edges if e["edge_type"] == "CALLS"]
            assert len(calls_edges) >= 1, (
                f"Expected >=1 CALLS edge targeting requirePermission "
                f"(node_id={rp_node_id}), got {len(calls_edges)}. "
                f"All matching edges: {edges}"
            )

            # Verify the edge source is the admin-users.ts module-level caller
            au_edges = [
                e for e in calls_edges
                if "admin-users" in e["source_id"]
            ]
            assert len(au_edges) == 1, (
                f"Expected 1 CALLS edge from admin-users.ts to requirePermission, "
                f"got {len(au_edges)}: {au_edges}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_requirepermission_ref_count_at_least_one(self, tmp_path):
        """requirePermission's ref_count must be >= 1 (no #219 regression)."""
        workspace = _build_issue231_workspace(tmp_path)
        try:
            backend = _run_scan(workspace)

            rp_nodes = [
                n for n in backend["nodes"] if n.get("fn") == "requirePermission"
            ]
            assert len(rp_nodes) == 1
            rp = rp_nodes[0]
            assert rp.get("ref_count", 0) >= 1, (
                f"Expected requirePermission ref_count >= 1 (no #219 regression), "
                f"got {rp.get('ref_count')}. Full node: {rp}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
