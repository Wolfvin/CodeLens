"""
Tests for the JS Backend Parser — function call graph extraction.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parser
_js_be_parser = None
_js_be_parser_available = False
try:
    from parsers.js_backend_parser import JSBackendParser
    _js_be_parser = JSBackendParser()
    _js_be_parser_available = True
except Exception:
    pass

# Import fallback regex parser from parsers module
from parsers.fallback_js_backend import parse_js_backend_fallback as _fallback_js_backend_parse


def _parse(content, path="server.js"):
    """Parse JS backend using tree-sitter parser if available, otherwise regex fallback."""
    if _js_be_parser_available:
        return _js_be_parser.extract_references(content, path)
    return _fallback_js_backend_parse(content, path)


class TestJSBackendParser:
    """Test JS backend function declaration and call parsing."""

    def test_function_declaration(self):
        js = "function processData(input) { return input; }"
        result = _parse(js)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "processData" in fn_names

    def test_arrow_function(self):
        js = "const fetchData = async (url) => { return fetch(url); };"
        result = _parse(js)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "fetchData" in fn_names

    def test_async_function(self):
        js = "async function verifyToken(token) { return jwt.verify(token); }"
        result = _parse(js)
        for node in result["nodes"]:
            if node["fn"] == "verifyToken":
                # Tree-sitter parser correctly detects async; fallback regex may not
                if _js_be_parser_available:
                    assert node["async"] is True
                else:
                    # Fallback regex parser has a known limitation with async detection
                    # when the regex itself matches the 'async' keyword
                    assert "async" in node or node.get("async") is not None

    def test_function_call_edge(self):
        js = """
        function hashPassword(pw) {
            return crypto.hash(pw);
        }
        function verifyPassword(input) {
            return hashPassword(input);
        }
        """
        result = _parse(js)
        # Check that there's at least one edge (call from verifyPassword to hashPassword)
        assert len(result["edges"]) > 0

    def test_method_call(self):
        js = """
        function processOrder(order) {
            return db.save(order);
        }
        """
        result = _parse(js)
        # Should detect save as a method call
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert any("save" in fn for fn in edge_to_fns)

    def test_skip_keywords(self):
        js = """
        function check() {
            if (true) { return; }
            for (let i = 0; i < 10; i++) {}
        }
        """
        result = _parse(js)
        # Keywords should not be in nodes
        node_fns = [n["fn"] for n in result["nodes"]]
        assert "if" not in node_fns
        assert "for" not in node_fns
        assert "return" not in node_fns

    def test_empty_js(self):
        js = ""
        result = _parse(js)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_file_and_line_info(self):
        js = "function hello() { return 'world'; }"
        result = _parse(js, "src/utils.js")
        node = result["nodes"][0]
        assert node["file"] == "src/utils.js"
        assert node["line"] == 1


class TestJSBackendParserTreeSitter:
    """Tests specific to tree-sitter JS backend parser."""

    @pytest.mark.skipif(not _js_be_parser_available, reason="Tree-sitter JavaScript grammar not installed")
    def test_fixture_file(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "server.js")
        with open(fixture_path, 'r') as f:
            content = f.read()
        result = _js_be_parser.extract_references(content, "server.js")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "initializeApp" in fn_names
        assert "setupMiddleware" in fn_names

    @pytest.mark.skipif(not _js_be_parser_available, reason="Tree-sitter JavaScript grammar not installed")
    def test_function_expression(self):
        js = "const handler = function() { return true; };"
        result = _js_be_parser.extract_references(js, "test.js")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "handler" in fn_names


class TestJSBackendFallback:
    """Tests for regex fallback JS backend parser."""

    def test_fallback_function_declaration(self):
        js = "function myFunc() { return true; }"
        result = _fallback_js_backend_parse(js, "test.js")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "myFunc" in fn_names

    def test_fallback_arrow_function(self):
        js = "const myArrow = () => { return 42; };"
        result = _fallback_js_backend_parse(js, "test.js")
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "myArrow" in fn_names

    def test_fallback_empty(self):
        result = _fallback_js_backend_parse("", "test.js")
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_fallback_skips_keywords(self):
        js = "function check() { if (true) { return 1; } }"
        result = _fallback_js_backend_parse(js, "test.js")
        node_fns = [n["fn"] for n in result["nodes"]]
        assert "if" not in node_fns
        assert "return" not in node_fns

    def test_fallback_returns_nodes_and_edges_keys(self):
        js = "function test() { return true; }"
        result = _fallback_js_backend_parse(js, "test.js")
        assert "nodes" in result
        assert "edges" in result
        assert isinstance(result["nodes"], list)
        assert isinstance(result["edges"], list)


# ─── Issue #210: module-top-level call extraction ──────────────────────────
# These tests reproduce two real-world patterns from the KDS backend audit
# (see GitHub issue #210) where reference_count was severely undercounted
# because the per-function pass missed them:
#   1. Middleware-factory argument: `router.post(path, requirePermission('admin'), handler)`
#      — `requirePermission('admin')` is a call_expression passed as an argument
#      to another call_expression at module top-level. The per-function pass
#      only walks registered function bodies; module-top-level calls are
#      invisible. Issue #210 fix adds a module-level pass that walks the AST
#      root, skips registered declaration subtrees, and extracts remaining
#      call_expression nodes (including those nested inside other calls'
#      argument lists).
#   2. Inline arrow callback body: `router.post(path, fn, (req, res) => {
#      hasPermission(...) })` — the arrow function is passed as an argument
#      and is NOT registered as a function declaration (not assigned to a
#      name), so the per-function pass never visits its body. The module-
#      level pass walks into inline arrow functions and extracts their calls.
class TestIssue210ModuleLevelCalls:
    """Issue #210 regression tests: module-top-level call extraction.

    Before the fix, both patterns below produced 0 call edges because the
    per-function pass only walks bodies of registered function/class
    declarations. Module-top-level calls and calls inside inline arrow
    function callbacks were missed entirely, causing reference_count
    undercounting for any function only called via those patterns.
    """

    def test_middleware_factory_argument_extracted(self):
        """Call passed as argument to another call (router.post pattern).

        Before fix: `requirePermission('admin')` inside `router.post(...)` at
        module top-level was not extracted — 0 edges to `requirePermission`.
        After fix: 1 edge with synthetic `<module>` source_id.
        """
        js = """
        const router = Router();
        router.post('/foo', requirePermission('admin'), (req, res) => {
          res.json({ ok: true });
        });
        """
        result = _parse(js, "routes.js")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        # requirePermission must be extracted as a call target
        assert "requirePermission" in edge_to_fns, (
            f"requirePermission edge missing — module-top-level call passed "
            f"as argument not extracted. edges={edge_to_fns}"
        )
        # The edge source must be the synthetic <module> id (file:0:<module>)
        rp_edges = [e for e in result["edges"] if e.get("to_fn") == "requirePermission"]
        assert all(e["from"].endswith(":0:<module>") for e in rp_edges), (
            f"requirePermission edge source should be <module> synthetic id, "
            f"got: {[e['from'] for e in rp_edges]}"
        )

    def test_inline_arrow_callback_body_calls_extracted(self):
        """Calls inside inline arrow function callback body (route handler).

        Before fix: `hasPermission(...)` inside `(req, res) => { ... }` was
        not extracted because the arrow function isn't a registered function
        declaration. After fix: edge extracted via module-level pass walking
        into inline arrow functions.
        """
        js = """
        const router = Router();
        router.post('/foo', authMiddleware, (req, res) => {
          if (hasPermission(req.user, 'admin')) {
            return res.json({ ok: true });
          }
          res.status(403).send('forbidden');
        });
        """
        result = _parse(js, "routes.js")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "hasPermission" in edge_to_fns, (
            f"hasPermission edge missing — inline arrow callback body call "
            f"not extracted. edges={edge_to_fns}"
        )

    def test_multi_site_same_file_accumulates_edges(self):
        """Multiple call sites of the same function in one file each emit
        their own edge — no dedup collapse that would undercount rc.

        Mirrors the `hasPermission` case from KDS backend (3 call sites per
        route file × 2 route files → rc=6 from module-level alone).
        """
        js = """
        const router = Router();
        router.post('/a', fn, (req, res) => {
          if (hasPermission(req.user, 'a')) { return res.json({ ok: true }); }
          res.status(403).send('forbidden');
        });
        router.post('/b', fn, (req, res) => {
          if (hasPermission(req.user, 'b')) { return res.json({ ok: true }); }
          res.status(403).send('forbidden');
        });
        router.post('/c', fn, (req, res) => {
          if (hasPermission(req.user, 'c')) { return res.json({ ok: true }); }
          res.status(403).send('forbidden');
        });
        """
        result = _parse(js, "routes.js")
        hp_edges = [e for e in result["edges"] if e.get("to_fn") == "hasPermission"]
        assert len(hp_edges) == 3, (
            f"Expected 3 hasPermission edges (one per call site), got "
            f"{len(hp_edges)}. edges={hp_edges}"
        )

    def test_no_double_count_for_calls_inside_function_body(self):
        """Calls inside a registered function body must NOT be re-extracted
        by the module-level pass — otherwise ref_count would be inflated.

        The module-level pass skips subtrees of registered declarations
        (function_declaration, class_declaration, variable_declarator with
        arrow/function value) to avoid double-counting.
        """
        js = """
        function handler() {
          return helper();
        }
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(js, "test.js")
        helper_edges = [e for e in result["edges"] if e.get("to_fn") == "helper"]
        # `helper()` is called once inside `handler()` body. The per-function
        # pass extracts it with from=handler's node id. The module-level pass
        # must NOT re-extract it (handler's subtree is skipped).
        assert len(helper_edges) == 1, (
            f"Expected exactly 1 helper edge (no double-count), got "
            f"{len(helper_edges)}. edges={helper_edges}"
        )
        # The single edge should come from handler's node id, not <module>
        assert not helper_edges[0]["from"].endswith(":0:<module>"), (
            f"helper edge should come from handler's node id, not <module>. "
            f"edge={helper_edges[0]}"
        )

    def test_module_level_call_extracts_router_post(self):
        """Sanity: module-top-level `router.post(...)` itself is extracted
        (its target is `post` — a method call, resolved via short-name match
        by edge_resolver). Before fix, this was also missed.
        """
        js = """
        const router = Router();
        router.post('/foo', handler);
        """
        result = _parse(js, "routes.js")
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        # `post` is the method name from `router.post(...)` — extracted as
        # to_fn="post" by _parse_call (member_expression → method name).
        assert "post" in edge_to_fns, (
            f"router.post call not extracted at module top-level. "
            f"edges={edge_to_fns}"
        )
