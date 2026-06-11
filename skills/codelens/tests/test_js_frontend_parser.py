"""
Tests for the JS Frontend Parser — DOM selector extraction.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parser
_js_fe_parser = None
_js_fe_parser_available = False
try:
    from parsers.js_frontend_parser import JSFrontendParser
    _js_fe_parser = JSFrontendParser()
    _js_fe_parser_available = True
except Exception:
    pass

# Import fallback regex parser
from parsers.fallback_js_frontend import parse_js_frontend_fallback as _fallback_js_frontend_parse


def _parse(content, path="app.js"):
    """Parse JS frontend using tree-sitter parser if available, otherwise regex fallback."""
    if _js_fe_parser_available:
        return _js_fe_parser.extract_references(content, path)
    return _fallback_js_frontend_parse(content, path)


class TestJSFrontendParser:
    """Test JS frontend DOM selector parsing."""

    def test_get_element_by_id(self):
        js = 'const el = document.getElementById("modal-btn");'
        result = _parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "modal-btn" in id_names

    def test_query_selector_id(self):
        js = 'const el = document.querySelector("#sidebar-nav");'
        result = _parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "sidebar-nav" in id_names

    def test_query_selector_class(self):
        js = 'const el = document.querySelector(".btn-primary");'
        result = _parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_query_selector_all(self):
        js = 'const els = document.querySelectorAll(".card");'
        result = _parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "card" in class_names

    def test_get_elements_by_class_name(self):
        js = 'const items = document.getElementsByClassName("list-item");'
        result = _parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "list-item" in class_names

    @pytest.mark.skipif(not _js_fe_parser_available, reason="jQuery parsing requires tree-sitter")
    def test_jquery_id(self):
        js = 'const el = $("#header");'
        result = _parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "header" in id_names

    @pytest.mark.skipif(not _js_fe_parser_available, reason="jQuery parsing requires tree-sitter")
    def test_jquery_class(self):
        js = 'const el = $(".container");'
        result = _parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "container" in class_names

    def test_comment_skipping(self):
        js = '// const el = document.getElementById("commented");\nconst el = document.getElementById("active");'
        result = _parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "active" in id_names
        # The regex fallback strips single-line comments, tree-sitter skips them
        assert "commented" not in id_names

    def test_empty_js(self):
        js = ""
        result = _parse(js)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_multiple_selectors_same_line(self):
        js = 'const modal = document.querySelector(".modal"); const btn = document.querySelector(".btn");'
        result = _parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "modal" in class_names
        assert "btn" in class_names


class TestJSFrontendParserTreeSitter:
    """Tests specific to tree-sitter JS frontend parser."""

    @pytest.mark.skipif(not _js_fe_parser_available, reason="Tree-sitter JavaScript grammar not installed")
    def test_fixture_file(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "app.js")
        with open(fixture_path, 'r') as f:
            content = f.read()
        result = _js_fe_parser.extract_references(content, "app.js")
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        # Check known references from fixture
        assert "app" in id_names
        assert "nav-link" in class_names


class TestJSFrontendFallback:
    """Tests for regex fallback JS frontend parser."""

    def test_fallback_get_element_by_id(self):
        js = 'const el = document.getElementById("test-id");'
        result = _fallback_js_frontend_parse(js, "test.js")
        id_names = [i["name"] for i in result["ids"]]
        assert "test-id" in id_names

    def test_fallback_query_selector(self):
        js = 'const el = document.querySelector(".test-class");'
        result = _fallback_js_frontend_parse(js, "test.js")
        class_names = [c["name"] for c in result["classes"]]
        assert "test-class" in class_names

    def test_fallback_get_elements_by_class_name(self):
        js = 'const items = document.getElementsByClassName("item");'
        result = _fallback_js_frontend_parse(js, "test.js")
        class_names = [c["name"] for c in result["classes"]]
        assert "item" in class_names

    def test_fallback_query_selector_id(self):
        js = 'const el = document.querySelector("#my-id");'
        result = _fallback_js_frontend_parse(js, "test.js")
        id_names = [i["name"] for i in result["ids"]]
        assert "my-id" in id_names

    def test_fallback_returns_classes_and_ids_keys(self):
        js = 'document.querySelector(".x"); document.getElementById("y");'
        result = _fallback_js_frontend_parse(js, "test.js")
        assert "classes" in result
        assert "ids" in result
        assert isinstance(result["classes"], list)
        assert isinstance(result["ids"], list)
