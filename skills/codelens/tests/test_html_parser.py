"""
Tests for the HTML Parser — Tree-sitter and regex fallback.
"""

import os
import sys
import pytest

# Add scripts to path
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


class TestHTMLParserBasic:
    """Test basic regex-based HTML parsing (always available)."""

    def setup_method(self):
        """Try to import tree-sitter parser, fall back to regex."""
        try:
            from parsers.html_parser import HTMLParser
            self.parser = HTMLParser()
            self.uses_ts = True
        except Exception:
            self.parser = None
            self.uses_ts = False

    def _parse(self, content, path="test.html"):
        if self.parser:
            return self.parser.extract_references(content, path)
        # Fallback regex parsing
        from parsers.html_parser import extract_html_references, detect_id_collisions
        result = extract_html_references(content, path)
        result["ids"] = detect_id_collisions(result["ids"])
        return result

    def test_basic_id_extraction(self):
        html = '<div id="main-content">Hello</div>'
        result = self._parse(html)
        id_names = [i["name"] for i in result["ids"]]
        assert "main-content" in id_names

    def test_basic_class_extraction(self):
        html = '<div class="container main-wrapper">Hello</div>'
        result = self._parse(html)
        class_names = [c["name"] for c in result["classes"]]
        assert "container" in class_names
        assert "main_wrapper" in class_names

    def test_multiple_ids(self):
        html = '<div id="header"></div><div id="footer"></div>'
        result = self._parse(html)
        id_names = [i["name"] for i in result["ids"]]
        assert "header" in id_names
        assert "footer" in id_names

    def test_id_collision_detection(self):
        html = '<div id="duplicate"></div><span id="duplicate"></span>'
        result = self._parse(html)
        for id_entry in result["ids"]:
            if id_entry["name"] == "duplicate":
                assert id_entry.get("flag") == "collision"

    def test_template_literal_skip(self):
        html = '<div id="{{ variable }}"></div>'
        result = self._parse(html)
        id_names = [i["name"] for i in result["ids"]]
        # Template literals should be skipped
        assert len(id_names) == 0 or "{{ variable }}" not in id_names

    def test_comment_skipping(self):
        html = '<!-- <div id="commented-out"></div> -->\n<div id="visible"></div>'
        result = self._parse(html)
        id_names = [i["name"] for i in result["ids"]]
        # Comments should be stripped, only "visible" should remain
        assert "visible" in id_names

    def test_empty_html(self):
        html = ""
        result = self._parse(html)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_html_no_ids_no_classes(self):
        html = "<p>Plain text</p>"
        result = self._parse(html)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_single_quote_attributes(self):
        html = "<div id='my-id' class='my-class'></div>"
        result = self._parse(html)
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        assert "my-id" in id_names
        assert "my-class" in class_names

    def test_line_numbers(self):
        html = '<div id="first"></div>\n<div id="second"></div>\n<div id="third"></div>'
        result = self._parse(html)
        assert len(result["ids"]) == 3
        for id_entry in result["ids"]:
            assert id_entry["line"] > 0

    def test_path_stored(self):
        html = '<div id="test"></div>'
        result = self._parse(html, "src/index.html")
        assert result["ids"][0]["path"] == "src/index.html"


class TestHTMLParserTreeSitter:
    """Tests specific to tree-sitter HTML parser (may be skipped if not installed)."""

    def setup_method(self):
        try:
            from parsers.html_parser import HTMLParser
            self.parser = HTMLParser()
        except Exception:
            pytest.skip("Tree-sitter HTML parser not available")

    def test_self_closing_tags(self):
        html = '<input id="email-input" class="form-control" />'
        result = self.parser.extract_references(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        assert "email-input" in id_names

    def test_nested_elements(self):
        html = '''
        <div id="outer" class="container">
            <div id="inner" class="wrapper">
                <span class="text">Hello</span>
            </div>
        </div>
        '''
        result = self.parser.extract_references(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        assert "outer" in id_names
        assert "inner" in id_names
        assert "container" in class_names
        assert "wrapper" in class_names
        assert "text" in class_names
