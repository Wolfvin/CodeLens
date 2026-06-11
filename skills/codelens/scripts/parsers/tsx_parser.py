"""
TSX Parser for CodeLens — Tree-sitter powered
Extracts className, id, and function references from TSX/JSX files.

Handles:
- JSX className="xxx" (React style)
- JSX id="xxx"
- TypeScript function declarations
- Arrow function components
- Dynamic className: className={`modal ${isOpen ? 'active' : ''}`}
  → extracts literal class names from template literals
- Conditional className: className={"btn-primary"}
- Spread props: className={classes.wrapper} → tracks "wrapper" as dynamic ref

This parser COMBINES frontend (class/id tracking) and backend (function call graph)
since TSX files contain both component definitions and DOM references.
"""

import re
from typing import Dict, List, Any, Optional
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


class TSXParser(BaseParser):
    """Parse TSX/JSX files to extract class/id references and function declarations."""

    # Same skip list as JS backend
    SKIP_NAMES = {
        'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
        'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
        'async', 'await', 'yield', 'import', 'export', 'from', 'default',
        'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
        'true', 'false', 'null', 'undefined', 'void', 'delete',
        'console', 'require', 'module', 'exports', 'React', 'useState', 'useEffect',
        'useRef', 'useCallback', 'useMemo', 'useContext', 'useReducer',
        'String', 'Number', 'Boolean', 'Array', 'Object', 'Promise', 'Error',
    }

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('tsx')
        if not lang:
            raise RuntimeError("tree-sitter-typescript not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, Any]:
        """
        Extract all references from a TSX file.

        Returns:
            {
                "frontend": {"classes": [...], "ids": [...]},
                "backend": {"nodes": [...], "edges": [...]}
            }
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        classes = []
        ids = []
        nodes = []
        edges = []

        # First pass: find function declarations
        fn_declarations = self._find_declarations(tree, source, file_path)
        for decl in fn_declarations:
            nodes.append(decl["node"])

        # Second pass: walk entire tree for JSX attrs and calls
        def visit(node: Node, _, depth):
            if node.type == 'jsx_attribute':
                self._process_jsx_attribute(node, source, file_path, classes, ids)
            elif node.type == 'call_expression':
                call_info = self._parse_call(node, source, fn_declarations)
                if call_info:
                    edges.append(call_info)

        self.walk_tree(tree, source, visit)

        return {
            "frontend": {"classes": classes, "ids": ids},
            "backend": {"nodes": nodes, "edges": edges}
        }

    def _process_jsx_attribute(self, node: Node, source: bytes,
                                file_path: str, classes: List, ids: List):
        """Process a JSX attribute to extract className or id."""
        children = node.children
        if len(children) < 2:
            return

        # Get attribute name
        attr_name_node = children[0]
        attr_name = self.get_text(attr_name_node, source)
        line = self.get_line(node)

        if attr_name == 'className':
            self._extract_classname_value(node, source, file_path, line, classes)
        elif attr_name == 'id':
            self._extract_id_value(node, source, file_path, line, ids)

    def _extract_classname_value(self, node: Node, source: bytes,
                                  file_path: str, line: int, classes: List):
        """
        Extract class names from className attribute.
        Handles:
        - className="static classes"
        - className={`template ${dynamic}`}
        - className={"expression"}
        - className={condition ? "a" : "b"}
        """
        for child in node.children:
            if child.type == 'string':
                value = self._get_string_value(child, source)
                if value:
                    for cls in value.split():
                        cls = cls.strip()
                        if cls and not cls.startswith('{') and not cls.startswith('$'):
                            classes.append({
                                "name": cls,
                                "line": line,
                                "flag": None,
                                "path": file_path,
                                "source": "jsx_classname"
                            })

            elif child.type == 'jsx_expression':
                # className={...} — try to extract literal strings from the expression
                self._extract_classes_from_expression(child, source, file_path, line, classes)

    def _extract_classes_from_expression(self, node: Node, source: bytes,
                                          file_path: str, line: int, classes: List):
        """Extract class names from a JSX expression container."""
        for child in node.children:
            # Template literal: `modal ${isOpen ? 'active' : ''}`
            if child.type == 'template_string':
                template_text = self.get_text(child, source)
                # Extract literal parts from template
                # Match static text between ${...}
                parts = re.split(r'\$\{[^}]*\}', template_text)
                for part in parts:
                    part = part.strip('`').strip()
                    for cls in part.split():
                        cls = cls.strip()
                        if cls and re.match(r'^[a-zA-Z_][\w-]*$', cls):
                            classes.append({
                                "name": cls,
                                "line": line,
                                "flag": None,
                                "path": file_path,
                                "source": "jsx_template"
                            })

                # Also extract strings inside template expressions
                self._walk_for_strings(child, source, file_path, line, classes)

            # Ternary: condition ? "a" : "b"
            elif child.type == 'ternary_expression':
                self._walk_for_strings(child, source, file_path, line, classes)

            # Simple string: className={"btn-primary"}
            elif child.type == 'string':
                value = self._get_string_value(child, source)
                if value:
                    for cls in value.split():
                        cls = cls.strip()
                        if cls:
                            classes.append({
                                "name": cls,
                                "line": line,
                                "flag": None,
                                "path": file_path,
                                "source": "jsx_expr"
                            })

            # Logical AND: className={"active" && "visible"}
            elif child.type == 'binary_expression' or child.type == 'parenthesized_expression':
                self._walk_for_strings(child, source, file_path, line, classes)

    def _walk_for_strings(self, node: Node, source: bytes,
                           file_path: str, line: int, classes: List):
        """Walk a subtree to find all string literals containing class names."""
        def visit(n, _, depth):
            if n.type == 'string':
                value = self._get_string_value(n, source)
                if value:
                    for cls in value.split():
                        cls = cls.strip()
                        if cls and re.match(r'^[a-zA-Z_][\w-]*$', cls):
                            classes.append({
                                "name": cls,
                                "line": line,
                                "flag": None,
                                "path": file_path,
                                "source": "jsx_nested"
                            })

        self.walk_tree(node, source, visit, max_depth=10)

    def _extract_id_value(self, node: Node, source: bytes,
                           file_path: str, line: int, ids: List):
        """Extract id from JSX id attribute."""
        for child in node.children:
            if child.type == 'string':
                value = self._get_string_value(child, source)
                if value and not value.startswith('{'):
                    ids.append({
                        "name": value.strip(),
                        "line": line,
                        "flag": None,
                        "path": file_path,
                        "source": "jsx_id"
                    })

    def _find_declarations(self, root: Node, source: bytes,
                            file_path: str) -> List[Dict]:
        """Find all function/component declarations."""
        declarations = []

        def visit(node: Node, _, depth):
            decl = None

            if node.type == 'function_declaration':
                decl = self._parse_fn_decl(node, source, file_path)
            elif node.type == 'variable_declarator':
                decl = self._parse_var_declarator(node, source, file_path)
            elif node.type == 'export_statement':
                # Check children for function/variable declarations
                for child in node.children:
                    if child.type in ('function_declaration', 'lexical_declaration'):
                        pass  # Will be caught by walk

            if decl:
                declarations.append(decl)

        self.walk_tree(root, source, visit)
        return declarations

    def _parse_fn_decl(self, node: Node, source: bytes, file_path: str) -> Optional[Dict]:
        """Parse a function declaration."""
        fn_name = None
        is_async = False
        body_node = None

        for child in node.children:
            if child.type == 'identifier':
                fn_name = self.get_text(child, source)
            elif child.type == 'async':
                is_async = True
            elif child.type == 'statement_block':
                body_node = child

        if not fn_name:
            return None

        line = self.get_line(node)
        return {
            "node": {
                "id": f"{file_path}:{line}",
                "fn": fn_name,
                "file": file_path,
                "line": line,
                "async": is_async,
                "component": fn_name[0].isupper()  # React component convention
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

    def _parse_var_declarator(self, node: Node, source: bytes, file_path: str) -> Optional[Dict]:
        """Parse a variable declarator (arrow function / function expression)."""
        name_node = None
        value_node = None
        is_async = False

        for child in node.children:
            if child.type == 'identifier':
                name_node = child
            elif child.type in ('arrow_function', 'function_expression'):
                value_node = child
                for vc in child.children:
                    if vc.type == 'async':
                        is_async = True

        if not name_node or not value_node:
            return None

        fn_name = self.get_text(name_node, source)
        line = self.get_line(node)

        body_node = None
        for child in value_node.children:
            if child.type in ('statement_block', 'expression'):
                body_node = child
                break

        return {
            "node": {
                "id": f"{file_path}:{line}",
                "fn": fn_name,
                "file": file_path,
                "line": line,
                "async": is_async,
                "component": fn_name[0].isupper()
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

    def _parse_call(self, node: Node, source: bytes,
                     fn_declarations: List[Dict]) -> Optional[Dict]:
        """Parse a call expression and return an edge if it's within a known function."""
        func_node = node.child_by_field_name('function')
        if not func_node:
            return None

        func_text = self.get_text(func_node, source)

        # Find which function this call is inside
        call_line = self.get_line(node)
        caller_id = None
        best_scope_start = -1
        best_scope_end = float('inf')
        for decl in fn_declarations:
            if decl["scope_start"] <= call_line - 1 <= decl["scope_end"]:
                # Check if this is the innermost function (tightest enclosing scope)
                if caller_id is None or \
                   (decl["scope_start"] >= best_scope_start and decl["scope_end"] <= best_scope_end):
                    caller_id = decl["node"]["id"]
                    best_scope_start = decl["scope_start"]
                    best_scope_end = decl["scope_end"]

        if not caller_id:
            return None

        # Determine called function name
        if func_node.type == 'identifier':
            name = func_text
            if name in self.SKIP_NAMES:
                return None
            return {"from": caller_id, "to_fn": name}

        elif func_node.type == 'member_expression':
            prop_node = func_node.child_by_field_name('property')
            if prop_node:
                method_name = self.get_text(prop_node, source)
                if method_name in self.SKIP_NAMES:
                    return None
                return {"from": caller_id, "to_fn": method_name}

        return None

    def _get_string_value(self, node: Node, source: bytes) -> Optional[str]:
        """Extract string value, removing quotes."""
        text = self.get_text(node, source)
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        if text.startswith('`'):
            return None  # Template literal handled separately
        return None
