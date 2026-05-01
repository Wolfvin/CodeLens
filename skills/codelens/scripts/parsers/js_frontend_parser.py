"""
JS Frontend Parser for CodeLens — Tree-sitter powered
Extracts all references to class or id via DOM selectors.

Handles:
- document.getElementById("xxx")
- document.querySelector("#xxx" / ".xxx")
- document.querySelectorAll("#xxx" / ".xxx")
- document.getElementsByClassName("xxx")
- document.getElementsByTagName("xxx") → tag, not class/id
- $(".xxx") / $("#xxx") — jQuery
- React.refs / ReactDOM.findDOMNode → skipped (too dynamic)
- classList.add/toggle/remove → IGNORED per spec (dynamic, not direct reference)
- Only string literal values counted — variable refs skipped
"""

import re
from typing import Dict, List, Any, Optional
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


class JSFrontendParser(BaseParser):
    """Parse frontend JS to extract DOM selector references to classes and ids."""

    # DOM selector methods we track
    TRACKED_METHODS = {
        'getElementById',
        'querySelector',
        'querySelectorAll',
        'getElementsByClassName',
    }

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('javascript')
        if not lang:
            raise RuntimeError("tree-sitter-javascript not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract class and id references from frontend JS.

        Returns:
            {"classes": [...], "ids": [...]}
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        classes = []
        ids = []

        def visit(node: Node, _, depth):
            if node.type == 'call_expression':
                self._process_call(node, source, file_path, classes, ids)

        self.walk_tree(tree, source, visit)

        return {"classes": classes, "ids": ids}

    def _process_call(self, node: Node, source: bytes,
                       file_path: str, classes: List, ids: List):
        """Process a call expression to find DOM selector calls."""
        # Get the function being called
        func_node = node.child_by_field_name('function')
        if not func_node:
            return

        func_text = self.get_text(func_node, source)

        # Check for document.xxx methods
        for method in self.TRACKED_METHODS:
            if func_text.endswith(f'.{method}'):
                self._extract_selector_args(node, source, file_path, method, classes, ids)
                return

        # Check for jQuery: $(".xxx") or $("#xxx")
        if func_text == '$' or func_text == 'jQuery':
            self._extract_jquery_args(node, source, file_path, classes, ids)
            return

    def _extract_selector_args(self, node: Node, source: bytes,
                                file_path: str, method: str,
                                classes: List, ids: List):
        """Extract selector strings from method arguments."""
        args_node = node.child_by_field_name('arguments')
        if not args_node:
            return

        for arg in args_node.children:
            if arg.type == 'string':
                value = self._get_string_value(arg, source)
                if value is None:
                    continue

                line = self.get_line(node)

                if method == 'getElementById':
                    ids.append({
                        "name": value,
                        "line": line,
                        "flag": None,
                        "path": file_path
                    })
                elif method in ('querySelector', 'querySelectorAll'):
                    self._parse_css_selector(value, line, file_path, classes, ids)
                elif method == 'getElementsByClassName':
                    classes.append({
                        "name": value,
                        "line": line,
                        "flag": None,
                        "path": file_path
                    })

    def _extract_jquery_args(self, node: Node, source: bytes,
                              file_path: str, classes: List, ids: List):
        """Extract selector strings from jQuery calls."""
        args_node = node.child_by_field_name('arguments')
        if not args_node:
            return

        for arg in args_node.children:
            if arg.type == 'string':
                value = self._get_string_value(arg, source)
                if value is None:
                    continue

                line = self.get_line(node)
                self._parse_css_selector(value, line, file_path, classes, ids)

    def _parse_css_selector(self, selector: str, line: int, file_path: str,
                             classes: List, ids: List):
        """Parse a CSS selector string to extract class/id references."""
        # Extract class names: .xxx
        for match in re.finditer(r'\.([a-zA-Z_][\w-]*)', selector):
            classes.append({
                "name": match.group(1),
                "line": line,
                "flag": None,
                "path": file_path
            })

        # Extract id names: #xxx
        for match in re.finditer(r'#([a-zA-Z_][\w-]*)', selector):
            ids.append({
                "name": match.group(1),
                "line": line,
                "flag": None,
                "path": file_path
            })

    def _get_string_value(self, node: Node, source: bytes) -> Optional[str]:
        """
        Extract the string value from a string node.
        Returns None for template literals or non-literal strings.
        """
        text = self.get_text(node, source)
        # Remove quotes
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        # Template literal — skip (dynamic)
        if text.startswith('`'):
            return None
        return None
