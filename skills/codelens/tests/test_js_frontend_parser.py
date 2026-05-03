"""
Tests for the JS Frontend Parser — DOM selector extraction.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


class TestJSFrontendParser:
    """Test JS frontend DOM selector parsing."""

    def setup_method(self):
        try:
            from parsers.js_frontend_parser import JSFrontendParser
            self.parser = JSFrontendParser()
        except Exception:
            self.parser = None

    def _parse(self, content, path="app.js"):
        if self.parser:
            return self.parser.extract_references(content, path)
        from parsers.js_frontend_parser import extract_js_frontend_references
        return extract_js_frontend_references(content, path)

    def test_get_element_by_id(self):
        js = 'const el = document.getElementById("modal-btn");'
        result = self._parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "modal-btn" in id_names

    def test_query_selector_id(self):
        js = 'const el = document.querySelector("#sidebar-nav");'
        result = self._parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "sidebar-nav" in id_names

    def test_query_selector_class(self):
        js = 'const el = document.querySelector(".btn-primary");'
        result = self._parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_query_selector_all(self):
        js = 'const els = document.querySelectorAll(".card");'
        result = self._parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "card" in class_names

    def test_get_elements_by_class_name(self):
        js = 'const items = document.getElementsByClassName("list-item");'
        result = self._parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "list-item" in class_names

    def test_jquery_id(self):
        js = 'const el = $("#header");'
        result = self._parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "header" in id_names

    def test_jquery_class(self):
        js = 'const el = $(".container");'
        result = self._parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "container" in class_names

    def test_comment_skipping(self):
        js = '// const el = document.getElementById("commented");\nconst el = document.getElementById("active");'
        result = self._parse(js)
        id_names = [i["name"] for i in result["ids"]]
        assert "active" in id_names
        # "commented" should not be present since line is commented
        assert "commented" not in id_names

    def test_empty_js(self):
        js = ""
        result = self._parse(js)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_multiple_selectors_same_line(self):
        js = 'const modal = document.querySelector(".modal"); const btn = document.querySelector(".btn");'
        result = self._parse(js)
        class_names = [c["name"] for c in result["classes"]]
        assert "modal" in class_names
        assert "btn" in class_names
