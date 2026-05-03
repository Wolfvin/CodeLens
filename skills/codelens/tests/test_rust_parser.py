"""
Tests for the Rust Parser — function call graph extraction.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


class TestRustParser:
    """Test Rust function declaration and call parsing."""

    def setup_method(self):
        try:
            from parsers.rust_parser import RustParser
            self.parser = RustParser()
        except Exception:
            self.parser = None

    def _parse(self, content, path="main.rs"):
        if self.parser:
            return self.parser.extract_references(content, path)
        from parsers.rust_parser import extract_rust_references
        return extract_rust_references(content, path)

    def test_fn_declaration(self):
        rust = "fn verify_token(token: &str) -> Result<Claims> { Ok(claims) }"
        result = self._parse(rust)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "verify_token" in fn_names

    def test_pub_fn(self):
        rust = "pub fn hash_password(pw: &str) -> String { String::new() }"
        result = self._parse(rust)
        fn_names = [n["fn"] for n in result["nodes"]]
        assert "hash_password" in fn_names

    def test_async_fn(self):
        rust = "async fn fetch_data(url: &str) -> Response { reqwest::get(url).await }"
        result = self._parse(rust)
        for node in result["nodes"]:
            if node["fn"] == "fetch_data":
                assert node["async"] is True

    def test_impl_block(self):
        rust = """
        impl UserService {
            fn verify_token(&self, token: &str) -> bool { true }
            fn hash_password(&self, pw: &str) -> String { String::new() }
        }
        """
        result = self._parse(rust)
        for node in result["nodes"]:
            if node["fn"] in ("verify_token", "hash_password"):
                assert node.get("impl_for") == "UserService"

    def test_self_method_call(self):
        rust = """
        impl Handler {
            fn process(&self, input: &str) -> String {
                self.validate(input)
            }
            fn validate(&self, input: &str) -> bool { true }
        }
        """
        result = self._parse(rust)
        # Should have edge from process to validate
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        assert "validate" in edge_to_fns

    def test_skip_macros(self):
        rust = """
        fn main() {
            println!("Hello");
            let v = vec![1, 2, 3];
        }
        """
        result = self._parse(rust)
        edge_to_fns = [e.get("to_fn", "") for e in result["edges"]]
        # Macros should not appear as function calls
        assert "println" not in edge_to_fns
        assert "vec" not in edge_to_fns

    def test_empty_rust(self):
        rust = ""
        result = self._parse(rust)
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_line_numbers(self):
        rust = "fn first() {}\nfn second() {}"
        result = self._parse(rust, "src/main.rs")
        for node in result["nodes"]:
            assert node["line"] > 0
            assert node["file"] == "src/main.rs"
