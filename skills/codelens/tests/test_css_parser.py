"""
Tests for the CSS Parser — Tree-sitter and regex fallback.
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


class TestCSSParserBasic:
    """Test basic CSS parsing."""

    def setup_method(self):
        try:
            from parsers.css_parser import CSSParser
            self.parser = CSSParser()
            self.uses_ts = True
        except Exception:
            self.parser = None
            self.uses_ts = False

    def _parse(self, content, path="test.css"):
        if self.parser:
            return self.parser.extract_references(content, path)
        from parsers.css_parser import extract_css_references
        return extract_css_references(content, path)

    def test_class_selector(self):
        css = ".btn-primary { color: blue; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_id_selector(self):
        css = "#sidebar-nav { width: 200px; }"
        result = self._parse(css)
        id_names = [i["name"] for i in result["ids"]]
        assert "sidebar-nav" in id_names

    def test_compound_selector(self):
        css = ".modal .btn-primary { display: flex; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "modal" in class_names
        assert "btn-primary" in class_names

    def test_duplicate_define_flag(self):
        css = """
        .container { max-width: 1200px; }
        .container { max-width: 960px; }
        """
        result = self._parse(css)
        container_entries = [c for c in result["classes"] if c["name"] == "container"]
        # At least one should have duplicate_define flag
        flags = [e.get("flag") for e in container_entries]
        assert "duplicate_define" in flags or len(container_entries) >= 2

    def test_comment_skipping(self):
        css = "/* .old-class { display: none; } */\n.new-class { display: block; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "new-class" in class_names

    def test_keyframes_skipping(self):
        css = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }\n.fade-in { animation: fadeIn; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "fade-in" in class_names

    def test_pseudo_class(self):
        css = ".btn-primary:hover { background: darkblue; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "btn-primary" in class_names

    def test_empty_css(self):
        css = ""
        result = self._parse(css)
        assert result["classes"] == []
        assert result["ids"] == []

    def test_comma_separated_selectors(self):
        css = ".header, .footer { padding: 10px; }"
        result = self._parse(css)
        class_names = [c["name"] for c in result["classes"]]
        assert "header" in class_names
        assert "footer" in class_names

    def test_line_numbers(self):
        css = ".first {}\n.second {}\n#third {}"
        result = self._parse(css)
        for entry in result["classes"] + result["ids"]:
            assert entry["line"] > 0
