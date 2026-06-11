"""
CSS Parser for CodeLens — Tree-sitter powered
Extracts selectors referencing class (.xxx) or id (#xxx).

Handles:
- Standard CSS selectors
- Compound selectors: .modal .btn-primary → references BOTH
- Pseudo-classes stripped for matching: .btn-primary:hover → class "btn-primary"
- duplicate_define detection (same selector 2+ times)
- Comments ignored automatically by tree-sitter
- @keyframes blocks ignored
- SCSS/Less: basic support via fallback regex for preprocessor syntax
"""

import re
from typing import Dict, List, Any
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


class CSSParser(BaseParser):
    """Parse CSS to extract class and id selector references."""

    # Node types that contain selectors we care about
    SELECTOR_TYPES = {
        'class_selector',       # .btn-primary
        'id_selector',          # #sidebar-nav
        'selector',             # compound selector
        'descendant_selector',  # .modal .btn
        'child_selector',       # .modal > .btn
        'sibling_selector',     # .btn + .btn
        'adjacent_sibling_selector',
        'pseudo_class_selector', # .btn:hover
        'pseudo_element_selector',
        'attribute_selector',
        'universal_selector',
        'nesting_selector',     # & .child (SCSS/Less)
    }

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('css')
        if not lang:
            raise RuntimeError("tree-sitter-css not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract class and id references from CSS content.

        Returns:
            {"classes": [...], "ids": [...]}
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        classes = []
        ids = []

        # Track selectors per name for duplicate_define
        selector_defs: Dict[str, List[int]] = {}  # "class:name" or "id:name" → [line_numbers]

        def visit(node: Node, _, depth):
            # Skip @keyframes
            if node.type == 'keyframes_statement':
                return False  # Don't descend into keyframes

            if node.type == 'class_selector':
                self._extract_class_selector(node, source, file_path, classes, selector_defs)
            elif node.type == 'id_selector':
                self._extract_id_selector(node, source, file_path, ids, selector_defs)
            elif node.type == 'pseudo_class_selector':
                self._extract_pseudo_class(node, source, file_path, classes, ids, selector_defs)

        self.walk_tree(tree, source, visit)

        # Flag duplicate_define
        self._flag_duplicates(classes, selector_defs, "class")
        self._flag_duplicates(ids, selector_defs, "id")

        # Also handle SCSS/Less that tree-sitter-css might not parse well
        # Fallback regex for preprocessor syntax
        # Note: '::' is NOT included as it matches standard CSS pseudo-elements
        if content.strip().startswith(('<style', '@use', '@import', '//', '/*')) or \
           any(x in content for x in ['$', '@mixin', '@include', '@extend']):
            self._scss_fallback(content, file_path, classes, ids, selector_defs)
            self._flag_duplicates(classes, selector_defs, "class")
            self._flag_duplicates(ids, selector_defs, "id")

        return {"classes": classes, "ids": ids}

    def _extract_class_selector(self, node: Node, source: bytes,
                                 file_path: str, classes: List, selector_defs: Dict):
        """Extract class name from a class_selector node (.xxx)."""
        # class_selector has children: "." + class_name
        for child in node.children:
            if child.type == 'class_name' or child.type == 'identifier':
                name = self.get_text(child, source)
                line = self.get_line(node)
                classes.append({
                    "name": name,
                    "line": line,
                    "flag": None,
                    "path": file_path
                })
                key = f"class:{name}"
                if key not in selector_defs:
                    selector_defs[key] = []
                selector_defs[key].append(line)
                break

    def _extract_id_selector(self, node: Node, source: bytes,
                              file_path: str, ids: List, selector_defs: Dict):
        """Extract id name from an id_selector node (#xxx)."""
        for child in node.children:
            if child.type == 'id_name' or child.type == 'identifier':
                name = self.get_text(child, source)
                line = self.get_line(node)
                ids.append({
                    "name": name,
                    "line": line,
                    "flag": None,
                    "path": file_path
                })
                key = f"id:{name}"
                if key not in selector_defs:
                    selector_defs[key] = []
                selector_defs[key].append(line)
                break

    def _extract_pseudo_class(self, node: Node, source: bytes,
                               file_path: str, classes: List, ids: List, selector_defs: Dict):
        """Extract class/id from pseudo-class selectors like .btn:hover."""
        # pseudo_class_selector: class_selector + ":" + "hover"
        for child in node.children:
            if child.type == 'class_selector':
                self._extract_class_selector(child, source, file_path, classes, selector_defs)
            elif child.type == 'id_selector':
                self._extract_id_selector(child, source, file_path, ids, selector_defs)

    def _flag_duplicates(self, entries: List[Dict], selector_defs: Dict, entry_type: str):
        """Flag entries with duplicate_define."""
        for entry in entries:
            key = f"{entry_type}:{entry['name']}"
            lines = selector_defs.get(key, [])
            if len(lines) > 1 and entry['line'] != lines[0]:
                entry['flag'] = 'duplicate_define'

    def _scss_fallback(self, content: str, file_path: str,
                        classes: List, ids: List, selector_defs: Dict):
        """Fallback regex for SCSS/Less syntax that tree-sitter-css can't parse."""
        existing_class_names = {c["name"] for c in classes}
        existing_id_names = {i["name"] for i in ids}

        for line_num, line in enumerate(content.split('\n'), 1):
            # SCSS interpolation #{...} — skip lines with interpolation
            if '#{' in line:
                continue

            # Extract class selectors
            for match in re.finditer(r'\.([a-zA-Z_][\w-]*)', line):
                name = match.group(1)
                if name not in existing_class_names:
                    classes.append({
                        "name": name,
                        "line": line_num,
                        "flag": None,
                        "path": file_path
                    })
                    key = f"class:{name}"
                    if key not in selector_defs:
                        selector_defs[key] = []
                    selector_defs[key].append(line_num)
                    existing_class_names.add(name)

            # Extract id selectors
            for match in re.finditer(r'#([a-zA-Z_][\w-]*)', line):
                name = match.group(1)
                if name not in existing_id_names:
                    ids.append({
                        "name": name,
                        "line": line_num,
                        "flag": None,
                        "path": file_path
                    })
                    key = f"id:{name}"
                    if key not in selector_defs:
                        selector_defs[key] = []
                    selector_defs[key].append(line_num)
                    existing_id_names.add(name)
