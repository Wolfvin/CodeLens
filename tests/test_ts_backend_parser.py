"""
Tests for the TS Backend Parser — function call graph extraction.

Issue #210 regression coverage: module-top-level call extraction for
TypeScript backend files. Mirrors the test coverage in
``test_js_backend_parser.py::TestIssue210ModuleLevelCalls`` but for the
TypeScript parser (which uses a different code path — two-pass design
vs. JS parser's single-pass design).

The KDS backend (Coretax-Auto-Downloader) reported in issue #210 is a
TypeScript Express app, so the TS parser is the primary fix target.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parser
_ts_be_parser = None
_ts_be_parser_available = False
try:
    from parsers.ts_backend_parser import TSBackendParser
    _ts_be_parser = TSBackendParser()
    _ts_be_parser_available = True
except Exception:
    pass


def _parse(content, path="server.ts"):
    """Parse TS backend using tree-sitter parser. Skips if unavailable."""
    if not _ts_be_parser_available:
        pytest.skip("Tree-sitter TypeScript grammar not installed")
    return _ts_be_parser.extract_references(content, path)


@pytest.mark.skipif(not _ts_be_parser_available, reason="Tree-sitter TypeScript grammar not installed")
class TestTSBackendParser:
    """Baseline tests for TSBackendParser function declaration extraction."""

    def test_function_declaration(self):
        ts = "function processData(input: string): string { return input; }"
        result = _parse(ts)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "processData" in fn_names

    def test_exported_function_declaration(self):
        ts = "export function verifyToken(token: string): boolean { return true; }"
        result = _parse(ts)
        for node in result["nodes"]:
            if node["fn"] == "verifyToken":
                assert node.get("exported") is True

    def test_arrow_function_with_types(self):
        ts = "const fetchData = async (url: string): Promise<void> => { return; };"
        result = _parse(ts)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "fetchData" in fn_names

    def test_function_call_edge(self):
        ts = """
        function hashPassword(pw: string): string { return crypto.hash(pw); }
        function verifyPassword(input: string): boolean { return hashPassword(input); }
        """
        result = _parse(ts)
        assert len(result["edges"]) > 0
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "hashPassword" in edge_to_fns


@pytest.mark.skipif(not _ts_be_parser_available, reason="Tree-sitter TypeScript grammar not installed")
class TestTSBackendParserIssue210ModuleLevel:
    """Issue #210 regression tests: module-top-level call extraction for TS.

    Before the fix, the per-function pass only walked bodies of registered
    function/class declarations. Module-top-level calls (e.g.
    `router.post(path, requirePermission('admin'), handler)` at file root)
    and calls inside inline arrow/function-expression callbacks (e.g. route
    handlers) were missed entirely, causing reference_count undercounting.

    The KDS backend reported in issue #210 is a TypeScript Express app, so
    these TS tests reproduce the exact patterns from the bug report.
    """

    def test_middleware_factory_argument_extracted(self):
        """Call passed as argument to another call (router.post pattern).

        This is the exact `requirePermission('admin')` pattern from
        permission-gate.ts in the KDS backend. Before fix: 0 edges to
        requirePermission. After fix: 1 edge with synthetic <module> source.
        """
        ts = """
        import { Router } from 'express';
        import { requirePermission } from './middleware/permission-gate';

        const router = Router();

        router.post('/accounting/journal', requirePermission('admin'), (req, res) => {
          res.json({ ok: true });
        });
        """
        result = _parse(ts, "src/routes/accounting.ts")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "requirePermission" in edge_to_fns, (
            f"requirePermission edge missing — module-top-level call passed "
            f"as argument not extracted. edges={edge_to_fns}"
        )
        rp_edges = [e for e in result["edges"] if e.get("to_fn") == "requirePermission"]
        assert all(e["from"].endswith(":0:<module>") for e in rp_edges), (
            f"requirePermission edge source should be <module> synthetic id, "
            f"got: {[e['from'] for e in rp_edges]}"
        )

    def test_inline_arrow_callback_body_calls_extracted(self):
        """Calls inside inline arrow function callback body (route handler).

        This is the exact `hasPermission(...)` pattern from the KDS backend
        route handlers. Before fix: 0 edges to hasPermission from route
        files. After fix: edge extracted via module-level pass.
        """
        ts = """
        import { Router } from 'express';
        import { hasPermission } from '../lib/permissions';

        const router = Router();

        router.post('/foo', authMiddleware, (req, res) => {
          if (hasPermission(req.user, 'admin')) {
            return res.json({ ok: true });
          }
          res.status(403).send('forbidden');
        });
        """
        result = _parse(ts, "src/routes/foo.ts")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "hasPermission" in edge_to_fns, (
            f"hasPermission edge missing — inline arrow callback body call "
            f"not extracted. edges={edge_to_fns}"
        )

    def test_multi_site_same_file_accumulates_edges(self):
        """Multiple call sites of the same function in one file each emit
        their own edge — no dedup collapse that would undercount rc.

        Mirrors the KDS backend case: 3 `requirePermission('admin')` call
        sites per route file × 4 route files → rc=12 from module-level alone.
        """
        ts = """
        import { Router } from 'express';
        import { requirePermission } from './middleware/permission-gate';

        const router = Router();

        router.post('/a', requirePermission('admin'), (req, res) => { res.json({ ok: true }); });
        router.post('/b', requirePermission('admin'), (req, res) => { res.json({ ok: true }); });
        router.post('/c', requirePermission('admin'), (req, res) => { res.json({ ok: true }); });
        """
        result = _parse(ts, "src/routes/foo.ts")
        rp_edges = [e for e in result["edges"] if e.get("to_fn") == "requirePermission"]
        assert len(rp_edges) == 3, (
            f"Expected 3 requirePermission edges (one per call site), got "
            f"{len(rp_edges)}. edges={rp_edges}"
        )

    def test_no_double_count_for_calls_inside_function_body(self):
        """Calls inside a registered function body must NOT be re-extracted
        by the module-level pass — otherwise ref_count would be inflated.

        The module-level pass skips subtrees of registered declarations
        (function_declaration, class_declaration, variable_declarator with
        arrow/function value) to avoid double-counting.
        """
        ts = """
        function handler(): void {
          helper();
        }
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(ts, "test.ts")
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count), got "
            f"{len(helper_edges)}. edges={helper_edges}"
        )
        assert not helper_edges[0]["from"].endswith(":0:<module>"), (
            f"helper edge should come from handler's node id, not <module>. "
            f"edge={helper_edges[0]}"
        )

    def test_module_level_call_extracts_router_post(self):
        """Sanity: module-top-level `router.post(...)` itself is extracted.
        """
        ts = """
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(ts, "routes.ts")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "post" in edge_to_fns, (
            f"router.post call not extracted at module top-level. "
            f"edges={edge_to_fns}"
        )

    def test_class_method_body_not_double_counted(self):
        """Calls inside an exported class method body are extracted by the
        per-function pass (which walks class_body). The module-level pass
        must skip the class_declaration subtree (inside export_statement)
        to avoid double-counting.

        Note: the TS parser only registers classes via the export_statement
        branch of _find_function_declarations, so we use `export class`
        here. Non-exported class registration is a separate pre-existing
        limitation outside issue #210's scope.
        """
        ts = """
        export class Service {
          process(): void {
            this.helper();
          }
        }
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(ts, "test.ts")
        # `helper` is called once inside Service.process. The per-function
        # pass walks class_body → finds helper call. The module-level pass
        # skips class_declaration subtree (inside export_statement) → no
        # double-count.
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count from class "
            f"subtree), got {len(helper_edges)}. edges={helper_edges}"
        )

    def test_exported_arrow_function_not_double_counted(self):
        """`export const foo = () => {...}` — the arrow function is registered
        as a function declaration. Module-level pass must skip the
        variable_declarator subtree to avoid double-counting its body calls.
        """
        ts = """
        export const handler = () => {
          return helper();
        };
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(ts, "test.ts")
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count from exported "
            f"arrow function), got {len(helper_edges)}. edges={helper_edges}"
        )


@pytest.mark.skipif(not _ts_be_parser_available, reason="Tree-sitter TypeScript grammar not installed")
class TestTSBackendParserIssue222ObjectLiteralMethods:
    """Issue #222 regression tests: arrow functions assigned to object-literal
    properties must be registered as function nodes.

    Before fix: ``const svc = { list: (ctx) => { ... } }`` — the
    ``variable_declarator`` value is an ``object`` node (not
    ``arrow_function``), so ``_parse_variable_declarator`` returned None
    and the arrow function was invisible as a node. Calls inside the
    arrow body were extracted by the module-level pass (issue #210) and
    attributed to ``<module>``, so ``ref_count`` was correct but
    ``trace``/``impact``/``search --mode symbol`` could not resolve the
    method by name.

    After fix: each arrow/function pair in an object literal is registered
    as a node named ``<varName>.<key>``, and calls inside its body are
    attributed to that node id.
    """

    def test_object_literal_arrow_function_registered_as_node(self):
        """``const svc = { list: (ctx) => {} }`` → node ``svc.list``."""
        ts = """\
const svc = {
  list: (ctx: any) => { return helper(); },
};
"""
        result = _parse(ts, "test.ts")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "svc.list" in fn_names, (
            f"Object-literal arrow function should be registered as "
            f"svc.list, got fn_names={fn_names}"
        )

    def test_object_literal_function_expression_registered_as_node(self):
        """``const svc = { list: function() {} }`` → node ``svc.list``."""
        ts = """\
const svc = {
  list: function(ctx: any) { return helper(); },
};
"""
        result = _parse(ts, "test.ts")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "svc.list" in fn_names, (
            f"Object-literal function expression should be registered as "
            f"svc.list, got fn_names={fn_names}"
        )

    def test_object_literal_method_calls_attributed_to_method_node(self):
        """Calls inside an object-literal arrow function body must be
        attributed to the ``<varName>.<key>`` node id, not to ``<module>``.

        Before fix: calls were attributed to ``<module>`` (via the
        module-level pass). After fix: calls are attributed to the
        method node id, and the module-level pass skips the pair subtree
        to avoid double-counting.
        """
        ts = """\
const svc = {
  list: (ctx: any) => { return helper(); },
};
"""
        result = _parse(ts, "test.ts")
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count), got "
            f"{len(helper_edges)}. edges={helper_edges}"
        )
        # The edge should come from svc.list's node id, not <module>
        edge_from = helper_edges[0]["from"]
        assert ":0:<module>" not in edge_from, (
            f"helper edge should come from svc.list's node id, not <module>. "
            f"edge={helper_edges[0]}"
        )

    def test_object_literal_multiple_methods_all_registered(self):
        """Multiple arrow functions in the same object literal must all
        be registered as separate nodes."""
        ts = """\
export const assignmentService = {
  list: (ctx: any) => { return hasPermission(ctx.user, 'read'); },
  create: (ctx: any) => { return hasPermission(ctx.user, 'write'); },
  remove: (ctx: any) => { return hasPermission(ctx.user, 'delete'); },
};
"""
        result = _parse(ts, "test.ts")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "assignmentService.list" in fn_names
        assert "assignmentService.create" in fn_names
        assert "assignmentService.remove" in fn_names

        # 3 hasPermission edges, one per method
        hp_edges = [e for e in result["edges"] if e.get("to_fn") == "hasPermission"]
        assert len(hp_edges) == 3, (
            f"Expected 3 hasPermission edges (one per method), got "
            f"{len(hp_edges)}. edges={hp_edges}"
        )
        # None should come from <module>
        for e in hp_edges:
            assert ":0:<module>" not in e["from"], (
                f"hasPermission edge should come from method node, not <module>. "
                f"edge={e}"
            )

    def test_object_literal_method_ref_count_correct(self):
        """End-to-end: hasPermission called only via object-literal arrow
        functions must have correct ref_count after edge resolution."""
        from edge_resolver import resolve_edges
        ts_permissions = """\
export function hasPermission(user: any, perm: string): boolean {
  return user?.permissions?.includes(perm) ?? false;
}
"""
        ts_service = """\
import { hasPermission } from './permissions';
export const assignmentService = {
  list: (ctx: any) => { if (!hasPermission(ctx.user, 'read')) return null; return []; },
  create: (ctx: any) => { if (!hasPermission(ctx.user, 'write')) throw new Error('no'); return {}; },
  remove: (ctx: any) => { if (!hasPermission(ctx.user, 'delete')) throw new Error('no'); return true; },
};
"""
        all_nodes = []
        all_edges = []
        for fpath, content in [
            ("src/lib/permissions.ts", ts_permissions),
            ("src/services/assignments.ts", ts_service),
        ]:
            r = _ts_be_parser.extract_references(content, fpath)
            all_nodes.extend(r.get("nodes", []))
            all_edges.extend(r.get("edges", []))

        resolved_nodes, _ = resolve_edges(all_nodes, all_edges)
        for n in resolved_nodes:
            if n["fn"] == "hasPermission":
                assert n.get("ref_count", 0) == 3, (
                    f"hasPermission ref_count should be 3 (3 call sites in "
                    f"object-literal arrow functions), got {n.get('ref_count', 0)}"
                )
                return
        pytest.fail("hasPermission node not found in resolved nodes")

    def test_object_literal_with_non_arrow_pairs_not_affected(self):
        """Object literals with non-arrow pairs (e.g. ``count: 5``) must
        not break parsing — non-arrow pairs are simply skipped."""
        ts = """\
const config = {
  count: 5,
  name: 'svc',
  handler: (ctx: any) => { return helper(ctx); },
};
"""
        result = _parse(ts, "test.ts")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "config.handler" in fn_names, (
            f"config.handler should be registered, got fn_names={fn_names}"
        )
        # Non-arrow pairs should not produce nodes
        assert "config.count" not in fn_names
        assert "config.name" not in fn_names

    def test_no_double_count_object_literal_arrow_and_module_level(self):
        """Calls inside object-literal arrow functions must NOT be
        double-counted by the module-level pass.

        Before fix #222: the module-level pass would extract calls inside
        the arrow body AND the per-function pass would also extract them
        (after registering the arrow as a node), leading to ref_count=2x.
        After fix: the module-level pass skips pair subtrees with
        arrow/function values.
        """
        ts = """\
const svc = {
  list: (ctx: any) => { return helper(); },
};
"""
        result = _parse(ts, "test.ts")
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count between "
            f"per-function pass and module-level pass), got {len(helper_edges)}. "
            f"edges={helper_edges}"
        )

    def test_object_literal_in_function_body_not_double_counted(self):
        """Object literal returned from a function: the function body
        is already walked by the per-function pass, so the object-literal
        method pass must not re-walk the same pairs.

        Note: object literals inside function bodies don't have a
        variable_declarator parent at module scope, so they are skipped
        by _find_object_literal_method_decls (no stable var name).
        """
        ts = """\
function makeService() {
  return {
    list: (ctx: any) => { return helper(); },
  };
}
"""
        result = _parse(ts, "test.ts")
        # helper() is inside the arrow function inside the object literal
        # inside makeService's body. The per-function pass for makeService
        # walks its body and extracts helper() attributed to makeService.
        # The object-literal method pass skips this pair (no
        # variable_declarator parent with object value at module scope).
        # The module-level pass skips makeService's subtree (registered decl).
        # So helper should have exactly 1 edge, from makeService.
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        assert len(helper_edges) == 1, (
            f"Expected 1 helper edge (from makeService), got {len(helper_edges)}. "
            f"edges={helper_edges}"
        )
        # Should NOT come from <module> — makeService is a registered decl
        from_text = helper_edges[0]["from"]
        assert ":0:<module>" not in from_text, (
            f"helper edge should come from makeService's node id, not <module>. "
            f"edge={helper_edges[0]}"
        )
