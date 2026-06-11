"""
HTML Parser for CodeLens — Tree-sitter powered
Extracts id and class from HTML elements.

Handles:
- Standard HTML: id="xxx", class="a b c"
- Comments ignored automatically (tree-sitter skips comment nodes)
- Template literals: id="{{ variable }}" filtered out
- Self-closing tags, void elements
"""

from typing import Dict, List, Any
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


class HTMLParser(BaseParser):
    """Parse HTML to extract id and class references."""

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('html')
        if not lang:
            raise RuntimeError("tree-sitter-html not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract id and class from HTML content.

        Returns:
            {"ids": [...], "classes": [...]}
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        ids = []
        classes = []

        # Walk all attribute nodes
        def visit(node: Node, _, depth):
            if node.type == 'attribute':
                self._process_attribute(node, source, file_path, ids, classes)

        self.walk_tree(tree, source, visit)

        # Detect ID collisions
        ids = self._detect_collisions(ids)

        return {"ids": ids, "classes": classes}

    def _process_attribute(self, node: Node, source: bytes,
                           file_path: str, ids: List, classes: List):
        """Process a single HTML attribute node."""
        children = node.children
        if len(children) < 3:
            return

        attr_name_node = children[0]
        attr_name = self.get_text(attr_name_node, source)

        # Find the attribute value
        attr_value = None
        for child in children:
            if child.type == 'quoted_attribute_value':
                # Get the inner attribute_value node
                for inner in child.children:
                    if inner.type == 'attribute_value':
                        attr_value = self.get_text(inner, source)
                        break
                break
            elif child.type == 'attribute_value':
                attr_value = self.get_text(child, source)
                break

        if not attr_value:
            return

        line = self.get_line(node)

        if attr_name == 'id':
            # Skip template literals (Jinja/Vue {{ }}, JS template ${ }, Jinja {% %})
            if '{{' in attr_value or '${' in attr_value or '{%' in attr_value:
                return
            ids.append({
                "name": attr_value.strip(),
                "line": line,
                "flag": None,
                "path": file_path
            })

        elif attr_name == 'class':
            # Skip template literals (Jinja/Vue {{ }}, JS template ${ }, Jinja {% %})
            if '{{' in attr_value or '${' in attr_value or '{%' in attr_value:
                return
            # Split by whitespace
            for cls in attr_value.split():
                cls = cls.strip()
                if cls:
                    classes.append({
                        "name": cls,
                        "line": line,
                        "flag": None,
                        "path": file_path
                    })

    def _detect_collisions(self, ids: List[Dict]) -> List[Dict]:
        """Flag IDs that appear in more than 1 HTML element."""
        from collections import Counter
        id_counts = Counter(entry["name"] for entry in ids)
        for entry in ids:
            if id_counts[entry["name"]] > 1:
                entry["flag"] = "collision"
        return ids
