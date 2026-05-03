"""
Tests for the CSS Parser — Tree-sitter and regex fallback.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Try to import tree-sitter based parser
_css_parser = None
_css_parser_available = False
try:
    from parsers.css_parser import CSSParser
    _css_parser = CSSParser()
    _css_parser_available = True
except Exception:
    pass

# Import fallback regex parser from codelens.py
from codelens import _fallback_css_parse


def _parse(content, path="test.css"):
    """Parse CSS using tree-sitter parser if available, otherwise regex fallback."""
    if _css_parser_available:
        return _css_parser.extract_references(content, path)
    return _fallback_css_parse(content, path)


class TestCSSParserBasic:
    """Test basic CSS parsing (works with tree-sitter or regex fallback)."""

    def test_class_selector(self):
        css = ".btn-primary { color: blue; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_id_selector(self):
        css = "#sidebar-nav { width: 200px; }"
        result = _parse(css)
        id_names = [i["name"] for i in result["ids"]]
        assert "sidebar-nav" in id_names

    def test_compound_selector(self):
        css = ".modal .btn-primary { display: flex; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "modal" in class_names
        assert "btn-primary" in class_names

    def test_duplicate_define_flag(self):
        css = """
        .container { max-width: 1200px; }
        .container { max-width: 960px; }
        """
        result = _parse(css)
        container_entries = [c for c in result["classes"] if c["name"] == "container"]
        # Tree-sitter parser sets duplicate_define flag; regex fallback may not
        if _css_parser_available:
            flags = [e.get("flag") for e in container_entries]
            assert "duplicate_define" in flags or len(container_entries) >= 2
        else:
            assert len(container_entries) >= 2

    def test_comment_skipping(self):
        css = "/* .old-class { display: none; } */\n.new-class { display: block; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "new-class" in class_names

    def test_keyframes_skipping(self):
        css = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }\n.fade-in { animation: fadeIn; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "fade-in" in class_names

    def test_pseudo_class(self):
        css = ".btn-primary:hover { background: darkblue; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_empty_css(self):
        css = ""
        result = _parse(css)
        assert result["classes"] == []
        assert result["ids"] == []

    def test_comma_separated_selectors(self):
        css = ".header, .footer { padding: 10px; }"
        result = _parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "header" in class_names
        assert "footer" in class_names

    def test_line_numbers(self):
        css = ".first {}\n.second {}\n#third {}"
        result = _parse(css)
        for entry in result["classes"] + result["ids"]:
            assert entry["line"] > 0

    def test_path_stored(self):
        css = ".test {}"
        result = _parse(css, "styles/main.css")
        assert result["classes"][0]["path"] == "styles/main.css"


class TestCSSParserTreeSitter:
    """Tests specific to tree-sitter CSS parser (skipped if not installed)."""

    @pytest.mark.skipif(not _css_parser_available, reason="Tree-sitter CSS grammar not installed")
    def test_fixture_file(self):
        fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample.css")
        with open(fixture_path, 'r') as f:
            content = f.read()
        result = _css_parser.extract_references(content, "sample.css")
        class_names = [c["name"] for c in result["classes"]]
        id_names = [i["name"] for i in result["ids"]]
        assert "container" in class_names
        assert "btn-primary" in class_names
        assert "app" in id_names


class TestCSSParserFallback:
    """Tests for regex fallback CSS parser."""

    def test_fallback_class_selector(self):
        css = ".my-class { color: red; }"
        result = _fallback_css_parse(css, "test.css")
        class_names = [c["name"] for c in result["classes"]]
        assert "my-class" in class_names

    def test_fallback_id_selector(self):
        css = "#my-id { width: 100px; }"
        result = _fallback_css_parse(css, "test.css")
        id_names = [i["name"] for i in result["ids"]]
        assert "my-id" in id_names

    def test_fallback_strips_comments(self):
        css = "/* .hidden {} */\n.visible { display: block; }"
        result = _fallback_css_parse(css, "test.css")
        class_names = [c["name"] for c in result["classes"]]
        assert "visible" in class_names

    def test_fallback_returns_classes_and_ids_keys(self):
        css = ".x {} #y {}"
        result = _fallback_css_parse(css, "test.css")
        assert "classes" in result
        assert "ids" in result
        assert isinstance(result["classes"], list)
        assert isinstance(result["ids"], list)
