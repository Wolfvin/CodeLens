"""Tests for router-instance-scoped middleware detection in apimap_engine.

Reproduces issue #214: ``<routerVar>.use(middleware)`` (the standard Express
modular-routing pattern) was silently dropped because ``_extract_js_middleware``
hardcoded the receiver to ``app|server|fastify|hono``. As a result every
route registered via a custom ``Router()`` instance was reported as
``auth_protected: false`` even when the router explicitly mounted an auth
middleware via ``router.use(authMiddleware)``.

These tests lock in the fix:

* ``<routerVar>.use(mw)`` is detected and scoped to that router instance only
* Router-scoped middleware does NOT leak to routes on other routers or to
  top-level ``app.get/post`` routes
* Public routes (no auth middleware anywhere in their chain) stay public
* Global ``app.use(mw)`` middleware is still attached to every route
* ``requirePermission`` / ``hasPermission`` / ``checkPermission`` are
  classified as ``auth`` (so they bump ``auth_protected`` count)
* ``Router()`` and ``express.Router()`` are both recognised
"""

import os
import sys
import tempfile
import shutil

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from apimap_engine import (  # noqa: E402
    _classify_middleware,
    _detect_router_vars,
    _extract_js_middleware,
    _extract_js_routes,
    map_api_routes,
)


# ---------------------------------------------------------------------------
# _detect_router_vars
# ---------------------------------------------------------------------------

class TestDetectRouterVars:
    def test_bare_router_assignment(self):
        content = "const router = Router();"
        assert _detect_router_vars(content) == {"router": ""}

    def test_express_router_assignment(self):
        # The issue body explicitly calls out `= express.Router()` as a pattern
        # that must be recognised (the pre-fix inline regex only matched `Router()`).
        content = "const accountingRouter = express.Router();"
        assert _detect_router_vars(content) == {"accountingRouter": ""}

    def test_router_with_prefix(self):
        content = "const r = Router({ prefix: '/api/v2' });"
        assert _detect_router_vars(content) == {"r": "/api/v2"}

    def test_new_router(self):
        content = "var adminRouter = new Router();"
        assert _detect_router_vars(content) == {"adminRouter": ""}

    def test_multiple_routers(self):
        content = """
        const accountingRouter = express.Router({ prefix: '/api/accounting' });
        const publicRouter = Router();
        """
        assert _detect_router_vars(content) == {
            "accountingRouter": "/api/accounting",
            "publicRouter": "",
        }

    def test_no_router_assignment(self):
        content = "const app = express();\napp.get('/x', h);"
        assert _detect_router_vars(content) == {}


# ---------------------------------------------------------------------------
# _extract_js_middleware — router-scoped detection
# ---------------------------------------------------------------------------

class TestExtractJsMiddlewareRouterScoped:
    def test_router_use_middleware_no_path(self):
        content = "accountingRouter.use(authMiddleware);"
        mw = _extract_js_middleware(content, "f.ts", {"accountingRouter": ""})
        assert len(mw) == 1
        assert mw[0]["name"] == "authMiddleware"
        assert mw[0]["type"] == "auth"
        assert mw[0]["scope"] == "router:accountingRouter"

    def test_router_use_require_permission_with_args(self):
        # The exact pattern from issue #214 / KDS backend.
        # `requirePermission('admin')` is a call, not a bare identifier — the
        # `(\w+)` capture must grab `requirePermission` and the `('admin')`
        # part is stripped by the existing classification path.
        content = "accountingRouter.use(requirePermission('admin'));"
        mw = _extract_js_middleware(content, "f.ts", {"accountingRouter": ""})
        assert len(mw) == 1
        assert mw[0]["name"] == "requirePermission"
        assert mw[0]["type"] == "auth"
        assert mw[0]["scope"] == "router:accountingRouter"

    def test_router_use_skips_unknown_receiver(self):
        # `foo` is not a known Router() var and not a global app name —
        # we must NOT treat this as middleware (avoids false positives from
        # arbitrary `foo.use(bar)` calls).
        content = "foo.use(someHandler);"
        mw = _extract_js_middleware(content, "f.ts", {})
        assert mw == []

    def test_router_use_skips_non_router_objects(self):
        # `cache.use(...)` should not be picked up as middleware.
        content = "cache.use(new Map());"
        mw = _extract_js_middleware(content, "f.ts", {})
        assert mw == []

    def test_global_app_use_still_global_scope(self):
        content = "app.use(cors());"
        mw = _extract_js_middleware(content, "f.ts", {})
        assert len(mw) == 1
        assert mw[0]["scope"] == "global"

    def test_router_use_path_scoped(self):
        content = 'accountingRouter.use("/reports", auditLogger);'
        mw = _extract_js_middleware(content, "f.ts", {"accountingRouter": ""})
        assert len(mw) == 1
        assert mw[0]["name"] == "auditLogger"
        assert mw[0]["scope"] == "router-path:accountingRouter:/reports"

    def test_router_use_does_not_leak_to_global(self):
        # Two routers in the same file — middleware on one must not appear
        # with scope referencing the other.
        content = """
        const accountingRouter = Router();
        const publicRouter = Router();
        accountingRouter.use(authMiddleware);
        publicRouter.use(cors);
        """
        rv = _detect_router_vars(content)
        mw = _extract_js_middleware(content, "f.ts", rv)
        scopes = {m["scope"] for m in mw}
        assert "router:accountingRouter" in scopes
        assert "router:publicRouter" in scopes
        # No global scope (neither receiver is app/server/fastify/hono)
        assert "global" not in scopes


# ---------------------------------------------------------------------------
# _extract_js_routes — router_var tagging
# ---------------------------------------------------------------------------

class TestExtractJsRoutesRouterVarTagging:
    def test_route_records_router_var(self):
        content = """
        const accountingRouter = Router({ prefix: '/api/accounting' });
        accountingRouter.get('/invoices', getInvoices);
        """
        rv = _detect_router_vars(content)
        routes = _extract_js_routes(content, "f.ts", set(), rv)
        assert len(routes) == 1
        assert routes[0]["router_var"] == "accountingRouter"
        # prefix must still be applied
        assert routes[0]["path"] == "/api/accounting/invoices"

    def test_app_route_records_app_var(self):
        content = "app.get('/users', getUsers);"
        routes = _extract_js_routes(content, "f.ts", set(), {})
        assert len(routes) == 1
        assert routes[0]["router_var"] == "app"


# ---------------------------------------------------------------------------
# map_api_routes — end-to-end DoD scenarios from issue #214
# ---------------------------------------------------------------------------

_KDS_STYLE_SOURCE = """
import { Router } from 'express';
import { authMiddleware, requirePermission } from '../middleware/auth';
import { requireOutletAccess } from '../middleware/access';

const accountingRouter = Router({ prefix: '/api/accounting' });

accountingRouter.use(authMiddleware);
accountingRouter.use(requireOutletAccess);
accountingRouter.use(requirePermission('admin'));

accountingRouter.get('/invoices', getInvoices);
accountingRouter.post('/invoices', createInvoice);
accountingRouter.delete('/invoices/:id', deleteInvoice);
accountingRouter.put('/invoices/:id', updateInvoice);

// Public router — no auth
const publicRouter = Router();
publicRouter.get('/health', healthCheck);
publicRouter.get('/version', versionInfo);
"""


@pytest.fixture
def kds_workspace():
    ws = tempfile.mkdtemp()
    routes_dir = os.path.join(ws, "src", "routes")
    os.makedirs(routes_dir)
    with open(os.path.join(routes_dir, "accounting.ts"), "w") as f:
        f.write(_KDS_STYLE_SOURCE)
    yield ws
    shutil.rmtree(ws, ignore_errors=True)


class TestMapApiRoutesIssue214:
    def test_auth_protected_count_above_baseline(self, kds_workspace):
        # DoD #1: auth_protected count is significantly higher than 3 (the
        # pre-fix false-negative baseline reported in the issue body).
        result = map_api_routes(kds_workspace)
        assert result["status"] == "ok"
        # All 4 accounting routes are auth-protected via router.use(authMiddleware)
        assert result["stats"]["auth_protected"] == 4
        assert result["stats"]["total_routes"] == 6

    def test_public_routes_stay_public(self, kds_workspace):
        # DoD #2: routes not under any auth-bearing router stay auth_protected=False.
        result = map_api_routes(kds_workspace)
        public_routes = [
            r for r in result["routes"] if not r.get("auth_protected")
        ]
        assert len(public_routes) == 2
        public_paths = sorted(r["path"] for r in public_routes)
        assert public_paths == ["/health", "/version"]

    def test_router_middleware_does_not_leak_to_public_routes(self, kds_workspace):
        # Constraint: accountingRouter.use(authMiddleware) must NOT attach to
        # routes on publicRouter.
        result = map_api_routes(kds_workspace)
        for r in result["routes"]:
            mw_names = {m["name"] for m in r.get("middleware_chain", [])}
            if r["path"] in ("/health", "/version"):
                # publicRouter routes must not carry any accounting-scoped mw
                assert "authMiddleware" not in mw_names
                assert "requirePermission" not in mw_names
                assert "requireOutletAccess" not in mw_names
            else:
                # accounting routes must have all three
                assert "authMiddleware" in mw_names
                assert "requirePermission" in mw_names
                assert "requireOutletAccess" in mw_names

    def test_router_var_recorded_on_routes(self, kds_workspace):
        # Helper for downstream tooling: each JS route carries the receiver
        # variable name so consumers can group routes by router instance.
        result = map_api_routes(kds_workspace)
        for r in result["routes"]:
            assert "router_var" in r
            assert r["router_var"] in {"accountingRouter", "publicRouter"}

    def test_app_use_global_middleware_no_regression(self):
        # DoD #3: app.use()/server.use() global middleware still attached to
        # every route like before.
        ws = tempfile.mkdtemp()
        try:
            with open(os.path.join(ws, "app.ts"), "w") as f:
                f.write(
                    "const express = require('express');\n"
                    "const app = express();\n"
                    "app.use(cors());\n"
                    "app.use(jwt);\n"
                    "app.get('/users', getUsers);\n"
                    "app.post('/users', createUser);\n"
                    "app.get('/health', healthCheck);\n"
                )
            result = map_api_routes(ws)
            for r in result["routes"]:
                mw_names = {m["name"] for m in r.get("middleware_chain", [])}
                assert "cors" in mw_names
                assert "jwt" in mw_names
                # jwt is auth-classified → all routes auth_protected
                assert r.get("auth_protected") is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ---------------------------------------------------------------------------
# _classify_middleware — auth pattern expansion (issue #214 DoD #1)
# ---------------------------------------------------------------------------

class TestAuthMiddlewarePatternExpansion:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("requirePermission", "auth"),
            ("hasPermission", "auth"),
            ("checkPermission", "auth"),
            ("verifyPermission", "auth"),
            ("ensurePermission", "auth"),
            ("authMiddleware", "auth"),
            ("requireAuth", "auth"),
            # Non-auth examples must NOT be misclassified
            ("cors", "cors"),
            ("rateLimit", "rate_limit"),
            ("validate", "validation"),
            ("auditLogger", "custom"),
            ("requireOutletAccess", "custom"),  # not auth; "access" too broad
        ],
    )
    def test_classification(self, name, expected):
        assert _classify_middleware(name) == expected
