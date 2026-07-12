"""
Regression tests for issue #210 — reference_count severely undercounts
cross-file calls.

Two patterns that were silently dropped before the fix:

1. **Middleware-factory-argument pattern** — a function call passed as
   an argument to a top-level route registration, e.g.
   ``router.post(path, requirePermission('admin'), handler)``.
   The ``requirePermission('admin')`` call_expression is not inside any
   function declaration, so it was never turned into a call-graph edge.

2. **Multi-site same-file calls inside object-literal arrow functions**
   — arrow functions assigned to object-literal properties, e.g.
   ``const service = { list: (ctx) => { hasPermission(ctx.user, 'read'); } }``.
   The ``variable_declarator`` value is an ``object`` node (not an
   ``arrow_function``), so ``_parse_variable_declarator`` returned None
   and the arrow function's body calls were lost.

Both patterns are now handled. These tests verify the fix by feeding
minimal repro fixtures through the TS/JS backend parsers and the
edge_resolver, then asserting the resulting ``ref_count`` matches the
ground-truth call-site count.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# ─── Parser availability guards ────────────────────────────────────
_ts_be_parser = None
_ts_be_parser_available = False
try:
    from parsers.ts_backend_parser import TSBackendParser
    _ts_be_parser = TSBackendParser()
    _ts_be_parser_available = True
except Exception:
    pass

_js_be_parser = None
_js_be_parser_available = False
try:
    from parsers.js_backend_parser import JSBackendParser
    _js_be_parser = JSBackendParser()
    _js_be_parser_available = True
except Exception:
    pass

from edge_resolver import resolve_edges


# ─── Fixtures reproducing the two reported patterns ───────────────

# Case 1 — middleware-factory argument at module scope.
# requirePermission is defined in one file, called 3× at module scope
# across three route files.
TS_PERMISSION_GATE = """\
export function requirePermission(permission: string) {
  return (req: any, res: any, next: any) => {
    if (!req.user) { res.sendStatus(403); return; }
    next();
  };
}
"""

TS_ROUTE_TEMPLATE = """\
import {{ Router }} from 'express';
import {{ requirePermission }} from '../middleware/permission-gate';

const router = Router();

router.post('{path}', requirePermission('admin'), (req, res) => {{
  res.json({{ ok: true }});
}});

export default router;
"""

# Case 2 — object-literal arrow function pattern.
# hasPermission is defined in one file, called from arrow functions
# assigned to object-literal properties in two service files (3 sites each)
# plus 1 site in a regular function.
TS_PERMISSIONS = """\
export function hasPermission(user: any, perm: string): boolean {
  return user?.permissions?.includes(perm) ?? false;
}
"""

TS_ASSIGNMENTS_SERVICE = """\
import { hasPermission } from '../lib/permissions';

export const assignmentService = {
  list: (ctx: any) => {
    if (!hasPermission(ctx.user, 'read')) return null;
    return [];
  },
  create: (ctx: any) => {
    if (!hasPermission(ctx.user, 'write')) throw new Error('no');
    return {};
  },
  remove: (ctx: any) => {
    if (!hasPermission(ctx.user, 'delete')) throw new Error('no');
    return true;
  },
};
"""

TS_TASK_TEMPLATES_SERVICE = """\
import { hasPermission } from '../lib/permissions';

export const taskTemplateService = {
  list: (ctx: any) => {
    if (!hasPermission(ctx.user, 'read')) return null;
    return [];
  },
  create: (ctx: any) => {
    if (!hasPermission(ctx.user, 'write')) throw new Error('no');
    return {};
  },
  remove: (ctx: any) => {
    if (!hasPermission(ctx.user, 'delete')) throw new Error('no');
    return true;
  },
};
"""

TS_PERMISSION_GATE_USE = """\
import { hasPermission } from './permissions';

export function checkGate(ctx: any) {
  return hasPermission(ctx.user, 'admin');
}
"""


# JS equivalents (for the JS parser)
JS_PERMISSION_GATE = """\
export function requirePermission(permission) {
  return (req, res, next) => {
    if (!req.user) { res.sendStatus(403); return; }
    next();
  };
}
"""

JS_ROUTE_TEMPLATE = """\
const {{ Router }} = require('express');
const {{ requirePermission }} = require('../middleware/permission-gate');

const router = Router();

router.post('{path}', requirePermission('admin'), (req, res) => {{
  res.json({{ ok: true }});
}});

module.exports = router;
"""

JS_PERMISSIONS = """\
export function hasPermission(user, perm) {
  return user && user.permissions && user.permissions.includes(perm);
}
"""

JS_ASSIGNMENTS_SERVICE = """\
import { hasPermission } from './permissions';

export const assignmentService = {
  list: (ctx) => {
    if (!hasPermission(ctx.user, 'read')) return null;
    return [];
  },
  create: (ctx) => {
    if (!hasPermission(ctx.user, 'write')) throw new Error('no');
    return {};
  },
  remove: (ctx) => {
    if (!hasPermission(ctx.user, 'delete')) throw new Error('no');
    return true;
  },
};
"""


def _ref_count_for(nodes: list, edges: list, target_fn: str) -> int:
    """Resolve edges and return the ref_count for the first node whose
    fn matches target_fn."""
    resolved_nodes, resolved_edges = resolve_edges(nodes, edges)
    for n in resolved_nodes:
        if n["fn"] == target_fn:
            return n.get("ref_count", 0)
    return -1  # not found


# ─── TS parser tests ──────────────────────────────────────────────

class TestIssue210TS:
    """Regression tests for issue #210 — TS backend parser."""

    @pytest.mark.skipif(not _ts_be_parser_available,
                        reason="Tree-sitter TypeScript grammar not installed")
    def test_module_scope_middleware_factory_call_is_collected(self):
        """Case 1: requirePermission('admin') passed as argument to
        router.post() at module scope must produce a call-graph edge.

        Before fix: 0 edges (call was silently dropped).
        After fix: 3 edges (one per route file).
        """
        files = [
            ("src/middleware/permission-gate.ts", TS_PERMISSION_GATE),
            ("src/routes/foo.ts", TS_ROUTE_TEMPLATE.format(path="/foo")),
            ("src/routes/bar.ts", TS_ROUTE_TEMPLATE.format(path="/bar")),
            ("src/routes/baz.ts", TS_ROUTE_TEMPLATE.format(path="/baz")),
        ]
        all_nodes = []
        all_edges = []
        for fpath, content in files:
            result = _ts_be_parser.extract_references(content, fpath)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))

        rc = _ref_count_for(all_nodes, all_edges, "requirePermission")
        assert rc == 3, (
            f"requirePermission should have ref_count=3 (3 route files call "
            f"it at module scope), got rc={rc}. Edges to requirePermission: "
            f"{[e for e in all_edges if e.get('to_fn') == 'requirePermission']}"
        )

    @pytest.mark.skipif(not _ts_be_parser_available,
                        reason="Tree-sitter TypeScript grammar not installed")
    def test_object_literal_arrow_function_calls_are_collected(self):
        """Case 2: hasPermission() called from arrow functions assigned
        to object-literal properties must produce call-graph edges.

        Before fix: 1 edge (only the call inside checkGate was detected).
        After fix: 7 edges (3 from assignmentService.{list,create,remove}
                          + 3 from taskTemplateService.{list,create,remove}
                          + 1 from checkGate).
        """
        files = [
            ("src/lib/permissions.ts", TS_PERMISSIONS),
            ("src/services/assignments.ts", TS_ASSIGNMENTS_SERVICE),
            ("src/services/task-templates.ts", TS_TASK_TEMPLATES_SERVICE),
            ("src/middleware/permission-gate-use.ts", TS_PERMISSION_GATE_USE),
        ]
        all_nodes = []
        all_edges = []
        for fpath, content in files:
            result = _ts_be_parser.extract_references(content, fpath)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))

        rc = _ref_count_for(all_nodes, all_edges, "hasPermission")
        assert rc == 7, (
            f"hasPermission should have ref_count=7 (3+3+1 call sites), "
            f"got rc={rc}. Edges to hasPermission: "
            f"{[e for e in all_edges if e.get('to_fn') == 'hasPermission']}"
        )

    @pytest.mark.skipif(not _ts_be_parser_available,
                        reason="Tree-sitter TypeScript grammar not installed")
    def test_object_literal_arrow_functions_registered_as_named_nodes(self):
        """Arrow functions in object literals should be registered as
        nodes named ``<varName>.<propertyName>`` so callers can trace
        into them via the call graph.
        """
        result = _ts_be_parser.extract_references(
            TS_ASSIGNMENTS_SERVICE, "src/services/assignments.ts",
        )
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "assignmentService.list" in fn_names
        assert "assignmentService.create" in fn_names
        assert "assignmentService.remove" in fn_names

    @pytest.mark.skipif(not _ts_be_parser_available,
                        reason="Tree-sitter TypeScript grammar not installed")
    def test_module_node_only_created_when_module_scope_calls_exist(self):
        """The synthetic ``<module>`` node should only be added when the
        file actually has module-scope calls — files with only function
        declarations should not get a <module> node.
        """
        # File with only a function declaration — no module-scope calls
        ts = "export function foo() { return bar(); }"
        result = _ts_be_parser.extract_references(ts, "test.ts")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "<module>" not in fn_names, (
            "File with no module-scope calls should not get a <module> node"
        )

        # File with module-scope call
        ts2 = "const router = Router();"
        result2 = _ts_be_parser.extract_references(ts2, "test.ts")
        fn_names2 = [n["fn"] for n in result2["nodes"]]
        assert "<module>" in fn_names2, (
            "File with module-scope calls should get a <module> node"
        )


# ─── JS parser tests ──────────────────────────────────────────────

class TestIssue210JS:
    """Regression tests for issue #210 — JS backend parser."""

    @pytest.mark.skipif(not _js_be_parser_available,
                        reason="Tree-sitter JavaScript grammar not installed")
    def test_module_scope_middleware_factory_call_is_collected(self):
        """Case 1 (JS): same as TS test but using JS parser."""
        files = [
            ("src/middleware/permission-gate.js", JS_PERMISSION_GATE),
            ("src/routes/foo.js", JS_ROUTE_TEMPLATE.format(path="/foo")),
            ("src/routes/bar.js", JS_ROUTE_TEMPLATE.format(path="/bar")),
            ("src/routes/baz.js", JS_ROUTE_TEMPLATE.format(path="/baz")),
        ]
        all_nodes = []
        all_edges = []
        for fpath, content in files:
            result = _js_be_parser.extract_references(content, fpath)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))

        rc = _ref_count_for(all_nodes, all_edges, "requirePermission")
        assert rc == 3, (
            f"requirePermission should have ref_count=3, got rc={rc}"
        )

    @pytest.mark.skipif(not _js_be_parser_available,
                        reason="Tree-sitter JavaScript grammar not installed")
    def test_object_literal_arrow_function_calls_are_collected(self):
        """Case 2 (JS): hasPermission() called from object-literal arrow
        functions must produce edges.
        """
        files = [
            ("src/lib/permissions.js", JS_PERMISSIONS),
            ("src/services/assignments.js", JS_ASSIGNMENTS_SERVICE),
        ]
        all_nodes = []
        all_edges = []
        for fpath, content in files:
            result = _js_be_parser.extract_references(content, fpath)
            all_nodes.extend(result.get("nodes", []))
            all_edges.extend(result.get("edges", []))

        rc = _ref_count_for(all_nodes, all_edges, "hasPermission")
        assert rc == 3, (
            f"hasPermission should have ref_count=3 (3 object-literal "
            f"arrow function call sites), got rc={rc}"
        )

    @pytest.mark.skipif(not _js_be_parser_available,
                        reason="Tree-sitter JavaScript grammar not installed")
    def test_object_literal_arrow_functions_registered_as_named_nodes(self):
        """Arrow functions in object literals should be registered as
        nodes named ``<varName>.<propertyName>``.
        """
        result = _js_be_parser.extract_references(
            JS_ASSIGNMENTS_SERVICE, "src/services/assignments.js",
        )
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "assignmentService.list" in fn_names
        assert "assignmentService.create" in fn_names
        assert "assignmentService.remove" in fn_names


# ─── Cross-cutting regression check ───────────────────────────────

class TestIssue210NoRegression:
    """Verify the fix does not regress existing parser behavior."""

    @pytest.mark.skipif(not _ts_be_parser_available,
                        reason="Tree-sitter TypeScript grammar not installed")
    def test_ts_regular_function_calls_still_collected(self):
        """Calls inside regular function declarations must still be
        attributed to the function (not to <module>)."""
        ts = """\
export function getAssignments(ctx: any) {
  if (!hasPermission(ctx.user, 'read')) return null;
  const a = hasPermission(ctx.user, 'write');
  return { a };
}
"""
        result = _ts_be_parser.extract_references(ts, "test.ts")
        nodes = result["nodes"]
        # getAssignments should be a registered node
        fn_names = [n["fn"] for n in nodes]
        assert "getAssignments" in fn_names
        # The 2 hasPermission calls should be attributed to getAssignments.
        # Look up the node ID for getAssignments, then check edges.
        ga_id = next(n["id"] for n in nodes if n["fn"] == "getAssignments")
        hp_edges = [e for e in result["edges"] if e.get("to_fn") == "hasPermission"]
        assert len(hp_edges) == 2, f"expected 2 hasPermission edges, got {len(hp_edges)}"
        for e in hp_edges:
            assert e["from"] == ga_id, (
                f"hasPermission call should be attributed to getAssignments "
                f"(id={ga_id!r}), got from={e['from']!r}"
            )
        # No <module> node should be created (no module-scope calls)
        assert "<module>" not in fn_names

    @pytest.mark.skipif(not _js_be_parser_available,
                        reason="Tree-sitter JavaScript grammar not installed")
    def test_js_regular_function_calls_still_collected(self):
        """Same as TS test, but for JS parser."""
        js = """\
function processOrder(order) {
  return validateOrder(order);
}
function validateOrder(order) {
  return order && order.id;
}
"""
        result = _js_be_parser.extract_references(js, "test.js")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "processOrder" in fn_names
        assert "validateOrder" in fn_names
        # processOrder calls validateOrder — should be 1 edge
        vo_edges = [e for e in result["edges"] if e.get("to_fn") == "validateOrder"]
        assert len(vo_edges) == 1
        # No <module> node
        assert "<module>" not in fn_names
