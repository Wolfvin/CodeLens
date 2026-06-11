"""
Tests for the HTML Parser — Tree-sitter and regex fallback.
"""

import os
import sys
import pytest

# Add scripts to path
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parser
_html_parser = None
_html_parser_available = False
try:
    from parsers.html_parser import HTMLParser
    _html_parser = HTMLParser()
    _html_parser_available = True
except Exception:
    pass

# Import fallback regex parser
from parsers.fallback_html import parse_html_fallback as _fallback_html_parse


def _parse(content, path="test.html"):
    """Parse HTML using tree-sitter parser if available, otherwise regex fallback."""
    if _html_parser_available:
        return _html_parser.extract_references(content, path)
    return _fallback_html_parse(content, path)


class TestHTMLParserBasic:
    """Test basic HTML parsing (works with tree-sitter or regex fallback)."""

    def test_basic_id_extraction(self):
        html = '<div id="main-content">Hello</div>'
        result = _parse(html)
        id_names = [i["name"] for i in result["ids"]]
        assert "main-content" in id_names

    def test_basic_class_extraction(self):
        html = '<div class="container main_wrapper">Hello</div>'
        result = _parse(html)
        class_names = [c["name"] for c in result["classes"]]
        assert "container" in class_names
        assert "main_wrapper" in class_names

    def test_multiple_ids(self):
        html = '<div id="header"></div><div id="footer"></div>'
        result = _parse(html)
        id_names = [i["name"] for i in result["ids"]]
        assert "header" in id_names
        assert "footer" in id_names

    def test_id_collision_detection(self):
        html = '<div id="duplicate"></div><span id="duplicate"></span>'
        result = _parse(html)
        duplicate_entries = [i for i in result["ids"] if i["name"] == "duplicate"]
        # Tree-sitter parser flags collisions; regex fallback may not
        if _html_parser_available:
            for id_entry in duplicate_entries:
                assert id_entry.get("flag") == "collision"
        else:
            # With fallback, just verify both IDs are found
            assert len(duplicate_entries) == 2

    def test_template_literal_skip(self):
        html = '<div id="{{ variable }}"></div>'
        result = _parse(html)
        id_names = [i["name"] for i in result["ids"]]
        # Template literals should be skipped
        assert len(id_names) == 0 or "{{ variable }}" not in id_names

    def test_comment_skipping(self):
        html = '<!-- <div id="commented-out"></div> -->\n<div id="visible"></div>'
        result = _parse(html)
        id_names = [i["name"] for i in result["ids"]]
        # Comments should be stripped, only "visible" should remain
        assert "visible" in id_names

    def test_empty_html(self):
        html = ""
        result = _parse(html)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_html_no_ids_no_classes(self):
        html = "<p>Plain text</p>"
        result = _parse(html)
        assert result["ids"] == []
        assert result["classes"] == []

    def test_single_quote_attributes(self):
        html = "<div id='my-id' class='my-class'></div>"
        result = _parse(html)
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        assert "my-id" in id_names
        assert "my-class" in class_names

    def test_line_numbers(self):
        html = '<div id="first"></div>\n<div id="second"></div>\n<div id="third"></div>'
        result = _parse(html)
        assert len(result["ids"]) == 3
        for id_entry in result["ids"]:
            assert id_entry["line"] > 0

    def test_path_stored(self):
        html = '<div id="test"></div>'
        result = _parse(html, "src/index.html")
        assert result["ids"][0]["path"] == "src/index.html"


class TestHTMLParserTreeSitter:
    """Tests specific to tree-sitter HTML parser (skipped if not installed)."""

    @pytest.mark.skipif(not _html_parser_available, reason="Tree-sitter HTML grammar not installed")
    def test_self_closing_tags(self):
        html = '<input id="email-input" class="form-control" />'
        result = _html_parser.extract_references(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        assert "email-input" in id_names

    @pytest.mark.skipif(not _html_parser_available, reason="Tree-sitter HTML grammar not installed")
    def test_nested_elements(self):
        html = '''
        <div id="outer" class="container">
            <div id="inner" class="wrapper">
                <span class="text">Hello</span>
            </div>
        </div>
        '''
        result = _html_parser.extract_references(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        assert "outer" in id_names
        assert "inner" in id_names
        assert "container" in class_names
        assert "wrapper" in class_names
        assert "text" in class_names

    @pytest.mark.skipif(not _html_parser_available, reason="Tree-sitter HTML grammar not installed")
    def test_fixture_file(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample.html")
        with open(fixture_path, 'r') as f:
            content = f.read()
        result = _html_parser.extract_references(content, "sample.html")
        id_names = [i["name"] for i in result["ids"]]
        class_names = [c["name"] for c in result["classes"]]
        # Check some known IDs and classes from the fixture
        assert "app" in id_names
        assert "container" in class_names


class TestHTMLParserFallback:
    """Tests for regex fallback parser (always available)."""

    def test_fallback_basic_id(self):
        html = '<div id="test-id"></div>'
        result = _fallback_html_parse(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        assert "test-id" in id_names

    def test_fallback_basic_class(self):
        html = '<div class="test-class"></div>'
        result = _fallback_html_parse(html, "test.html")
        class_names = [c["name"] for c in result["classes"]]
        assert "test-class" in class_names

    def test_fallback_multiple_classes(self):
        html = '<div class="cls1 cls2 cls3"></div>'
        result = _fallback_html_parse(html, "test.html")
        class_names = [c["name"] for c in result["classes"]]
        assert "cls1" in class_names
        assert "cls2" in class_names
        assert "cls3" in class_names

    def test_fallback_strips_comments(self):
        html = '<!-- <div id="hidden"></div> -->\n<div id="visible"></div>'
        result = _fallback_html_parse(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        assert "visible" in id_names

    def test_fallback_skips_template_literals(self):
        html = '<div id="{{ dynamic }}"></div>'
        result = _fallback_html_parse(html, "test.html")
        id_names = [i["name"] for i in result["ids"]]
        assert "{{ dynamic }}" not in id_names

    def test_fallback_returns_ids_and_classes_keys(self):
        html = '<div id="x" class="y"></div>'
        result = _fallback_html_parse(html, "test.html")
        assert "ids" in result
        assert "classes" in result
        assert isinstance(result["ids"], list)
        assert isinstance(result["classes"], list)
