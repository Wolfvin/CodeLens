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
