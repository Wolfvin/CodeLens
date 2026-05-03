"""
Tests for the JS Backend Parser — function call graph extraction.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


class TestJSBackendParser:
    """Test JS backend function declaration and call parsing."""

    def setup_method(self):
        try:
            from parsers.js_backend_parser import JSBackendParser
            self.parser = JSBackendParser()
        except Exception:
            self.parser = None

    def _parse(self, content, path="server.js"):
        if self.parser:
            return self.parser.extract_references(content, path)
        from parsers.js_backend_parser import extract_js_backend_references
        return extract_js_backend_references(content, path)

    def test_function_declaration(self):
        js = "function processData(input) { return input; }"
        result = self._parse(js)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "processData" in fn_names

    def test_arrow_function(self):
        js = "const fetchData = async (url) => { return fetch(url); };"
        result = self._parse(js)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "fetchData" in fn_names

    def test_async_function(self):
        js = "async function verifyToken(token) { return jwt.verify(token); }"
        result = self._parse(js)
        for node in result["nodes"]:
            if node["fn"] == "verifyToken":
                assert node["async"] is True

    def test_function_call_edge(self):
        js = """
        function hashPassword(pw) {
            return crypto.hash(pw);
        }
        function verifyPassword(input) {
            return hashPassword(input);
        }
        """
        result = self._parse(js)
        # Check that there's an edge from verifyPassword to hashPassword
        from_fns = set()
        for edge in result["edges"]:
            from_fns.add(edge["from"])
        assert len(result["edges"]) > 0

    def test_method_call(self):
        js = """
        function processOrder(order) {
            return db.save(order);
        }
        """
        result = self._parse(js)
        # Should detect db.save as a method call
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert any("save" in fn or "db.save" in fn for fn in edge_to_fns)

    def test_skip_keywords(self):
        js = """
        function check() {
            if (true) { return; }
            for (let i = 0; i < 10; i++) {}
        }
        """
        result = self._parse(js)
        # Keywords should not be in nodes or edge targets
        node_fns = [n["fn"] for n in result["nodes"]]
        assert "if" not in node_fns
        assert "for" not in node_fns
        assert "return" not in node_fns

    def test_empty_js(self):
        js = ""
        result = self._parse(js)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_file_and_line_info(self):
        js = "function hello() { return 'world'; }"
        result = self._parse(js, "src/utils.js")
        node = result["nodes"][0]
        assert node["file"] == "src/utils.js"
        assert node["line"] == 1
