"""Tests for router-instance-scoped middleware detection in api-map.

Regression coverage for issue #214:
`accountingRouter.use(authMiddleware)` (and any `<routerVar>.use(mw)` on a
detected `Router()` instance) must propagate the middleware to every route
registered on the SAME router variable, in the SAME file — and ONLY those
routes. Before #214 the regex was hardcoded to `app|server|fastify|hono`
receivers, so the standard Express modular-router pattern produced
`auth_protected: false` for routes that were in fact auth-protected.

Scope rules covered here:
  * `<routerVar>.use(authMw)` → routes on the same router var get the mw.
  * Routes on a DIFFERENT router var in the same file do NOT get the mw.
  * Routes on a router var in a DIFFERENT file do NOT get the mw.
  * `app.use(authMw)` (global) still attaches to every route — no regression.
  * `express.Router()` (qualified form) is detected, not just bare `Router()`.
  * `requirePermission('admin')` (call-style middleware on a router) is
    classified as auth and attached.
"""

import os
import shutil
import tempfile

import pytest

# Make the scripts/ dir importable as the engine modules are flat modules.
SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
import sys
sys.path.insert(0, SCRIPTS_DIR)

from apimap_engine import (  # noqa: E402
    map_api_routes,
    _detect_router_vars,
    _extract_js_middleware,
    _extract_js_routes,
    _classify_middleware,
)


@pytest.fixture
def workspace():
    """Yield a fresh temp workspace dir, cleaned up after the test."""
    d = tempfile.mkdtemp(prefix="codelens_apimap_test_")
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _write(workspace, name, content):
    path = os.path.join(workspace, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return path


# ─── 1. Unit-level: _detect_router_vars ────────────────────────────


class TestDetectRouterVars:
    def test_bare_router_form(self):
        """`const r = Router()` — existing form, must still work."""
        rv = _detect_router_vars("const r = Router();")
        assert rv == {"r": ""}

    def test_bare_router_form_lowercase(self):
        """`const r = router()` — lowercase variant."""
        rv = _detect_router_vars("const r = router();")
        assert rv == {"r": ""}

    def test_new_router_form(self):
        """`const r = new Router()` — with `new`."""
        rv = _detect_router_vars("const r = new Router();")
        assert rv == {"r": ""}

    def test_qualified_router_form(self):
        """`const r = express.Router()` — issue #214 form, was previously missed."""
        rv = _detect_router_vars("const r = express.Router();")
        assert rv == {"r": ""}, f"express.Router() not detected; got {rv!r}"

    def test_qualified_new_router_form(self):
        """`const r = new express.Router()` — qualified + new."""
        rv = _detect_router_vars("const r = new express.Router();")
        assert rv == {"r": ""}

    def test_prefix_extracted(self):
        """Prefix option is still extracted from any form."""
        rv = _detect_router_vars("const r = Router({ prefix: '/api' });")
        assert rv == {"r": "/api"}
        rv = _detect_router_vars("const r = express.Router({ prefix: '/api' });")
        assert rv == {"r": "/api"}

    def test_multiple_routers(self):
        """Multiple router assignments in one file all get detected."""
        content = """
            const express = require("express");
            const accountingRouter = express.Router();
            const publicRouter = Router();
            const adminRouter = new Router();
        """
        rv = _detect_router_vars(content)
        assert set(rv.keys()) == {"accountingRouter", "publicRouter", "adminRouter"}


# ─── 2. Unit-level: _extract_js_middleware ─────────────────────────


class TestExtractJsMiddlewareRouterScope:
    def test_router_var_use_emits_router_scope(self):
        """`<routerVar>.use(mw)` emits scope=router:<var>."""
        content = """
            const accountingRouter = express.Router();
            accountingRouter.use(authMiddleware);
        """
        mw_list = _extract_js_middleware(content, "accounting.ts")
        scopes = [m["scope"] for m in mw_list]
        assert "router:accountingRouter" in scopes, (
            f"router:accountingRouter not in {scopes!r}"
        )
        # And it's NOT also emitted as global
        assert "global" not in scopes

    def test_app_use_still_emits_global(self):
        """Existing `app.use(mw)` keeps emitting scope=global (no regression)."""
        content = """
            const app = express();
            app.use(authMiddleware);
        """
        mw_list = _extract_js_middleware(content, "server.js")
        scopes = [(m["name"], m["scope"]) for m in mw_list]
        assert ("authMiddleware", "global") in scopes

    def test_router_var_use_call_style_middleware(self):
        """`router.use(requirePermission('admin'))` — bare-name capture works."""
        content = """
            const adminRouter = express.Router();
            adminRouter.use(requirePermission('admin'));
        """
        mw_list = _extract_js_middleware(content, "admin.ts")
        scopes = [(m["name"], m["scope"], m["type"]) for m in mw_list]
        assert ("requirePermission", "router:adminRouter", "auth") in scopes, (
            f"requirePermission not classified as auth router-scope; got {scopes!r}"
        )

    def test_router_var_not_detected_when_no_router_assignment(self):
        """If the receiver is not a detected Router() var, no router-scope mw emitted."""
        # `someRandom.use(mw)` — `someRandom` is not a Router() assignment.
        content = """
            const someRandom = somethingElse();
            someRandom.use(authMiddleware);
        """
        mw_list = _extract_js_middleware(content, "x.js")
        scopes = [m["scope"] for m in mw_list]
        # No router-scope emission, and no global either (someRandom != app/server/etc)
        assert all(not s.startswith("router:") for s in scopes), (
            f"unexpected router-scope emission: {scopes!r}"
        )
        assert "global" not in scopes


# ─── 3. Unit-level: _classify_middleware ───────────────────────────


class TestClassifyMiddlewareIssue214:
    def test_requirepermission_is_auth(self):
        """`requirePermission` (camelCase) is classified as auth (issue #214)."""
        assert _classify_middleware("requirePermission") == "auth"
        assert _classify_middleware("requirePermissionMiddleware") == "auth"

    def test_authmiddleware_is_auth(self):
        """`authMiddleware` continues to be classified as auth."""
        assert _classify_middleware("authMiddleware") == "auth"

    def test_requireoutletaccess_is_custom(self):
        """`requireOutletAccess` is outlet-scope, not generic auth — stays custom.

        The issue body mentions this middleware as part of the KDS pattern,
        but it's a tenant-scope check, not a generic auth gate. We do NOT add
        it to the global AUTH_MIDDLEWARE_PATTERNS — over-broadening that set
        would cause false positives in other codebases. KDS-specific names
        belong in user-supplied config, not in the engine.
        """
        assert _classify_middleware("requireOutletAccess") == "custom"


# ─── 4. Unit-level: _extract_js_routes adds router_var ─────────────


class TestExtractJsRoutesRouterVarField:
    def test_route_on_router_var_records_router_var(self):
        """Routes registered on a Router() var record the var name in router_var."""
        content = """
            const express = require("express");
            const accountingRouter = express.Router();
            accountingRouter.get("/invoices", listInvoices);
        """
        frameworks = set()
        routes = _extract_js_routes(content, "accounting.ts", frameworks)
        assert len(routes) == 1
        assert routes[0]["router_var"] == "accountingRouter"

    def test_route_on_app_has_no_router_var(self):
        """Routes registered on `app`/`server`/`fastify`/`hono` have router_var=None."""
        content = """
            const express = require("express");
            const app = express();
            app.get("/health", healthCheck);
        """
        frameworks = set()
        routes = _extract_js_routes(content, "server.js", frameworks)
        assert len(routes) == 1
        assert routes[0]["router_var"] is None


# ─── 5. End-to-end: map_api_routes ─────────────────────────────────


class TestMapApiRoutesRouterMiddleware:
    def test_kds_pattern_auth_protected_count_increases(self, workspace):
        """Reproduces the KDS pattern from issue #214.

        Before fix: auth_protected=0 (false negative — accountingRouter.use
        was missed because regex was hardcoded to app/server/fastify/hono).
        After fix: auth_protected=3 (all routes on accountingRouter).
        """
        _write(workspace, "server.js", """
            const express = require("express");
            const { Router } = require("express");
            const authMiddleware = require("./authMiddleware");
            const requireOutletAccess = require("./requireOutletAccess");

            const accountingRouter = Router();
            accountingRouter.use(authMiddleware);
            accountingRouter.use(requireOutletAccess);

            accountingRouter.get("/invoices", listInvoices);
            accountingRouter.post("/invoices", createInvoice);
            accountingRouter.get("/invoices/:id", getInvoice);

            const publicRouter = Router();
            publicRouter.get("/health", healthCheck);

            const app = express();
            app.use("/api/accounting", accountingRouter);
            app.use("/api/public", publicRouter);
            app.listen(3000);
        """)
        result = map_api_routes(workspace)
        assert result["status"] == "ok"
        # 4 routes total, 3 auth_protected (accountingRouter), 1 public (/health)
        assert result["stats"]["total_routes"] == 4
        assert result["stats"]["auth_protected"] == 3, (
            f"expected 3 auth_protected, got {result['stats']['auth_protected']}"
        )
        assert result["stats"]["public"] == 1

        # Verify per-route
        by_path = {(r["method"], r["path"]): r for r in result["routes"]}
        assert by_path[("GET", "/invoices")]["auth_protected"] is True
        assert by_path[("POST", "/invoices")]["auth_protected"] is True
        assert by_path[("GET", "/invoices/:id")]["auth_protected"] is True
        assert by_path[("GET", "/health")]["auth_protected"] is False, (
            "/health on publicRouter should NOT be auth-protected (over-detection)"
        )

    def test_no_cross_leak_between_router_vars_same_file(self, workspace):
        """Multiple router vars in the same file — middleware only applies to its own var."""
        _write(workspace, "server.js", """
            const { Router } = require("express");
            const authedRouter = Router();
            authedRouter.use(authMiddleware);
            authedRouter.get("/a1", h1);

            const publicRouter = Router();
            publicRouter.get("/p1", h2);
            publicRouter.get("/p2", h3);

            const adminRouter = Router();
            adminRouter.use(requirePermission);
            adminRouter.post("/admin", h4);
        """)
        result = map_api_routes(workspace)
        by_path = {(r["method"], r["path"]): r for r in result["routes"]}
        assert by_path[("GET", "/a1")]["auth_protected"] is True
        assert by_path[("GET", "/p1")]["auth_protected"] is False
        assert by_path[("GET", "/p2")]["auth_protected"] is False
        assert by_path[("POST", "/admin")]["auth_protected"] is True, (
            "requirePermission must classify as auth and reach /admin"
        )

    def test_no_cross_leak_between_files(self, workspace):
        """Middleware on accountingRouter in accounting.ts MUST NOT leak to assignments.ts.

        This is the core constraint from the issue body — `accountingRouter.use(...)`
        HANYA berlaku untuk route via accountingRouter, not for routes in other
        files (which have their own assignmentsRouter etc).
        """
        _write(workspace, "accounting.ts", """
            const { Router } = require("express");
            const accountingRouter = Router();
            accountingRouter.use(authMiddleware);
            accountingRouter.get("/invoices", listInvoices);
        """)
        _write(workspace, "assignments.ts", """
            const { Router } = require("express");
            const assignmentsRouter = Router();
            // NO authMiddleware here
            assignmentsRouter.get("/tasks", listTasks);
        """)
        result = map_api_routes(workspace)
        by_file_path = {(r["file"], r["path"]): r for r in result["routes"]}
        assert by_file_path[("accounting.ts", "/invoices")]["auth_protected"] is True
        assert by_file_path[("assignments.ts", "/tasks")]["auth_protected"] is False, (
            "Cross-file leak: assignments.ts /tasks got auth from accounting.ts"
        )

    def test_app_use_global_middleware_still_attaches_to_all_routes(self, workspace):
        """Regression guard: existing global `app.use(mw)` still applies to all routes.

        This was working before the fix and must remain working — the new
        router-scope branch must not interfere with the global branch.
        """
        _write(workspace, "server.js", """
            const express = require("express");
            const app = express();
            app.use(authMiddleware);
            app.get("/api/health", healthCheck);
            app.get("/api/users", listUsers);
        """)
        result = map_api_routes(workspace)
        for r in result["routes"]:
            assert r["auth_protected"] is True, (
                f"global app.use(authMiddleware) should protect all routes; "
                f"{r['method']} {r['path']} got auth_protected={r['auth_protected']}"
            )

    def test_express_qualified_router_form_detected(self, workspace):
        """`express.Router()` (TypeScript/ESM convention) is detected end-to-end.

        Before #214, only the bare `Router()` form was caught; the qualified
        `express.Router()` form — the most common in TS backends — was missed.
        """
        _write(workspace, "server.ts", """
            import express, { Request, Response } from "express";
            const accountingRouter = express.Router();
            accountingRouter.use(authMiddleware);
            accountingRouter.get("/invoices", (req: Request, res: Response) => {});
        """)
        result = map_api_routes(workspace)
        by_path = {(r["method"], r["path"]): r for r in result["routes"]}
        assert by_path[("GET", "/invoices")]["auth_protected"] is True, (
            "express.Router() form was not detected — auth_protected should be True"
        )

    def test_router_with_prefix(self, workspace):
        """Router({ prefix: '/api' }) — prefix still applied + middleware propagates."""
        _write(workspace, "server.js", """
            const { Router } = require("express");
            const r = Router({ prefix: "/api" });
            r.use(authMiddleware);
            r.get("/users", listUsers);
        """)
        result = map_api_routes(workspace)
        by_path = {(r["method"], r["path"]): r for r in result["routes"]}
        # Prefix should be applied
        assert ("GET", "/api/users") in by_path, (
            f"prefix /api not applied; got paths {list(by_path.keys())}"
        )
        # And middleware should propagate
        assert by_path[("GET", "/api/users")]["auth_protected"] is True

    def test_router_use_without_path_arg(self, workspace):
        """DoD #4: minimal repro of `<routerVar>.use(mwName)` + routes on the same router."""
        _write(workspace, "server.js", """
            const { Router } = require("express");
            const myRouter = Router();
            myRouter.use(authMiddleware);
            myRouter.get("/protected", handler);
        """)
        result = map_api_routes(workspace)
        by_path = {(r["method"], r["path"]): r for r in result["routes"]}
        assert by_path[("GET", "/protected")]["auth_protected"] is True

    def test_router_scope_middleware_does_not_crash_with_inline_args(self, workspace):
        """Router-scope middleware attaches cleanly even when routes have inline args.

        Note: inline middleware extraction (between path and handler) is a
        separate, pre-existing code path with its own bugs (it searches
        forward for a `(` after the path string, but there is none — see
        `_extract_inline_middleware` in apimap_engine.py). That pre-existing
        behavior is out of scope for #214. This test only verifies the new
        router-scope path coexists without crashing and the router-scope
        middleware is correctly attached.
        """
        _write(workspace, "server.js", """
            const { Router } = require("express");
            const r = Router();
            r.use(authMiddleware);
            r.get("/x", validateInput, handler);
        """)
        result = map_api_routes(workspace)
        route = next(r for r in result["routes"] if r["path"] == "/x")
        mw_names = {m["name"] for m in route["middleware_chain"]}
        assert "authMiddleware" in mw_names, (
            f"router-scope authMiddleware missing from chain; got {mw_names}"
        )
        assert route["auth_protected"] is True
