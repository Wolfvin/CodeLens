"""
Base Parser for CodeLens — Tree-sitter powered
Provides shared utilities for all AST-based parsers.
"""

from typing import Dict, List, Any, Optional, Tuple
from tree_sitter import Language, Parser, Node


class BaseParser:
    """Base class for all tree-sitter based parsers."""

    def __init__(self, language: Language):
        self.language = language
        self.parser = Parser(language)

    def parse(self, content: bytes) -> Node:
        """Parse source content and return root node."""
        return self.parser.parse(content).root_node

    @staticmethod
    def get_text(node: Node, source: bytes) -> str:
        """Get the text content of a node."""
        return source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')

    @staticmethod
    def get_line(node: Node) -> int:
        """Get 1-based line number of a node."""
        return node.start_point.row + 1

    def walk_tree(self, node: Node, source: bytes, callback, depth=0, max_depth=50):
        """
        Walk the entire AST tree, calling callback for each node.
        Callback signature: callback(node, source, depth) -> bool (True to continue, False to skip children)
        """
        if depth > max_depth:
            return
        should_continue = callback(node, source, depth)
        if should_continue is not False:
            for child in node.children:
                self.walk_tree(child, source, callback, depth + 1, max_depth)

    def find_nodes_by_type(self, root: Node, node_type: str) -> List[Node]:
        """Find all nodes of a specific type in the tree."""
        results = []
        def visitor(node, source, depth):
            if node.type == node_type:
                results.append(node)
        self.walk_tree(root, b'', visitor)
        return results

    def find_nodes_by_types(self, root: Node, node_types: set) -> List[Node]:
        """Find all nodes matching any of the given types."""
        results = []
        def visitor(node, source, depth):
            if node.type in node_types:
                results.append(node)
        self.walk_tree(root, b'', visitor)
        return results

    def find_parent_of_type(self, node: Node, parent_type: str) -> Optional[Node]:
        """Walk up the tree to find a parent of a specific type."""
        current = node.parent
        while current:
            if current.type == parent_type:
                return current
            current = current.parent
        return None

    def is_inside_comment(self, node: Node) -> bool:
        """Check if a node is inside a comment."""
        current = node.parent
        while current:
            if current.type in ('comment', 'block_comment', 'html_comment', 'line_comment'):
                return True
            current = current.parent
        return False

    def is_inside_keyframes(self, node: Node) -> bool:
        """Check if a node is inside a @keyframes block (CSS-specific)."""
        current = node.parent
        while current:
            if current.type in ('keyframes_statement', 'at_rule'):
                return True
            current = current.parent
        return False

    def get_function_context(self, node: Node, source: bytes,
                              fn_decl_types: set) -> Optional[Tuple[str, int]]:
        """
        Find the nearest enclosing function declaration.
        Returns (function_name, line) or None.
        """
        current = node.parent
        while current:
            if current.type in fn_decl_types:
                # Find the function name
                for child in current.children:
                    if child.type in ('identifier', 'property_identifier', 'name'):
                        fn_name = self.get_text(child, source)
                        return (fn_name, self.get_line(current))
                # For variable declarators like: const fn = () => {}
                if current.type == 'variable_declarator':
                    for child in current.children:
                        if child.type == 'identifier':
                            fn_name = self.get_text(child, source)
                            return (fn_name, self.get_line(current))
            current = current.parent
        return None
