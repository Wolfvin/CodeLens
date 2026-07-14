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

from base_parser import BaseParser, JS_TS_SKIP_NAMES_BASE, JS_TSX_SKIP_NAMES_EXTRA
from grammar_loader import get_grammar_loader


class TSXParser(BaseParser):
    """Parse TSX/JSX files to extract class/id references and function declarations."""

    # Same skip list as JS backend + React hooks
    SKIP_NAMES = JS_TS_SKIP_NAMES_BASE | JS_TSX_SKIP_NAMES_EXTRA

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

        # Second pass: walk entire tree for JSX attrs, component usage, and calls
        def visit(node: Node, _, depth):
            if node.type == 'jsx_attribute':
                self._process_jsx_attribute(node, source, file_path, classes, ids)
            elif node.type in ('jsx_opening_element', 'jsx_self_closing_element'):
                self._process_jsx_component(node, source, file_path, fn_declarations, edges)
            elif node.type == 'jsx_expression':
                self._process_jsx_expression(node, source, file_path, fn_declarations, edges)
            elif node.type == 'call_expression':
                call_info = self._parse_call(node, source, fn_declarations)
                if call_info:
                    edges.append(call_info)
            elif node.type == 'new_expression':
                call_info = self._parse_new_expression(node, source, fn_declarations)
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
        """Find all function/component/class declarations."""
        declarations = []

        def visit(node: Node, _, depth):
            decl = None

            if node.type == 'function_declaration':
                decl = self._parse_fn_decl(node, source, file_path)
            elif node.type == 'variable_declarator':
                decl = self._parse_var_declarator(node, source, file_path)
            elif node.type == 'class_declaration':
                decl = self._parse_class_decl(node, source, file_path)
            elif node.type == 'export_statement':
                for child in node.children:
                    if child.type in ('function_declaration', 'generator_function_declaration'):
                        decl = self._parse_fn_decl(child, source, file_path)
                        if decl:
                            declarations.append(decl)
                    elif child.type == 'lexical_declaration':
                        for subchild in child.children:
                            if subchild.type == 'variable_declarator':
                                decl = self._parse_var_declarator(subchild, source, file_path)
                                if decl:
                                    declarations.append(decl)
                return False  # Already processed, don't let walk double-count

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

    def _parse_class_decl(self, node: Node, source: bytes, file_path: str) -> Optional[Dict]:
        """Parse a class_declaration node for TSX files.

        Extracts the class name and body scope, enabling class-based components
        and service/repository classes to appear in the backend registry.
        """
        class_name = None
        body_node = None
        heritage = None

        for child in node.children:
            if child.type == 'identifier':
                class_name = self.get_text(child, source)
            elif child.type == 'class_heritage':
                heritage = self.get_text(child, source)
            elif child.type == 'class_body':
                body_node = child

        if not class_name:
            return None

        line = self.get_line(node)
        is_component = class_name[0].isupper() and (
            heritage and ('Component' in heritage or 'React' in heritage)
        )

        result = {
            "node": {
                "id": f"{file_path}:{line}",
                "fn": class_name,
                "file": file_path,
                "line": line,
                "async": False,
                "component": is_component,
                "node_type": "class",
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

        if heritage:
            result["node"]["heritage"] = heritage

        return result

    def _process_jsx_component(self, node: Node, source: bytes,
                                file_path: str, fn_declarations: List[Dict],
                                edges: List):
        """Process a JSX opening/closing element to track component usage.

        In React, <Button variant="default"> is equivalent to calling Button().
        Without tracking this, all React components appear "dead" because their
        only references are through JSX syntax, not function calls.

        Handles:
        - <Button> → edge to "Button"
        - <Button /> → edge to "Button"
        - <ui.Button> → edge to "Button" (member expression)
        - <div>, <span>, <h1> → SKIP (HTML elements are lowercase)
        """
        # Get the element name node
        name_node = node.child_by_field_name('name')
        if not name_node:
            # Try first child that is an identifier or member_expression
            for child in node.children:
                if child.type in ('identifier', 'member_expression', 'nested_identifier'):
                    name_node = child
                    break

        if not name_node:
            return

        # Extract component name
        component_name = None
        if name_node.type == 'identifier':
            component_name = self.get_text(name_node, source)
        elif name_node.type == 'member_expression':
            # e.g., <ui.Button> → extract "Button"
            prop_node = name_node.child_by_field_name('property')
            if prop_node:
                component_name = self.get_text(prop_node, source)
        elif name_node.type == 'nested_identifier':
            # e.g., <Motion.Button> → extract last part
            for child in name_node.children:
                if child.type == 'identifier':
                    component_name = self.get_text(child, source)

        if not component_name:
            return

        # Skip HTML elements (lowercase) and built-in SVG elements
        if component_name[0].islower():
            return

        # Skip common non-component uppercase identifiers
        NON_COMPONENTS = {
            'Fragment', 'Suspense', 'StrictMode', 'Provider', 'Consumer',
        }
        if component_name in NON_COMPONENTS:
            return

        # Find which function this JSX is inside (the caller)
        jsx_line = self.get_line(node)
        caller_id = None
        best_scope_size = float('inf')
        for decl in fn_declarations:
            if decl["scope_start"] <= jsx_line - 1 <= decl["scope_end"]:
                scope_size = decl["scope_end"] - decl["scope_start"]
                if scope_size < best_scope_size:
                    best_scope_size = scope_size
                    caller_id = decl["node"]["id"]

        if not caller_id:
            return

        # Create edge: caller → component
        edges.append({
            "from": caller_id,
            "to_fn": component_name,
            "via_jsx": True
        })

    def _process_jsx_expression(self, node: Node, source: bytes,
                                 file_path: str, fn_declarations: List[Dict],
                                 edges: List):
        """Emit usage edges for functions referenced inside a JSX expression
        container (issue #294).

        In React, an event handler is passed by *reference* as a prop value —
        ``onClick={handleClick}`` — not by call. The per-call passes only see
        ``call_expression`` nodes, so a bare identifier reference produces zero
        edges, leaving the handler with ``ref_count=0`` and false-flagged dead.

        This handler counts two reference shapes as usage, but ONLY when the
        identifier resolves to a function declared in this file (guarded by
        ``declared``) — arbitrary identifiers, DOM props, and non-function names
        are never counted:

        1. Attribute value / child reference: ``onClick={handleClick}`` — the
           expression's direct child is the identifier.
        2. Callback argument: ``{items.map(renderItem)}`` — the identifier is
           passed as an argument to a call.

        Double-counting is avoided by:
          - skipping the ``function`` position of a ``call_expression`` (those
            are already emitted by :meth:`_parse_call`), walking only its
            ``arguments``;
          - not descending into nested ``jsx_expression`` nodes (the outer
            tree walk visits each one on its own);
          - skipping ``member_expression`` (e.g. ``items.map`` / ``this.x``).
        """
        declared = {d["node"]["fn"] for d in fn_declarations}
        if not declared:
            return

        # Resolve the enclosing function (innermost scope) as the edge source.
        expr_line = self.get_line(node)
        caller_id = None
        best_scope_size = float('inf')
        for decl in fn_declarations:
            if decl["scope_start"] <= expr_line - 1 <= decl["scope_end"]:
                scope_size = decl["scope_end"] - decl["scope_start"]
                if scope_size < best_scope_size:
                    best_scope_size = scope_size
                    caller_id = decl["node"]["id"]
        if not caller_id:
            return

        seen = set()

        def emit(name: str):
            if name in seen:
                return
            if name in self.SKIP_NAMES or name not in declared:
                return
            seen.add(name)
            edges.append({
                "from": caller_id,
                "to_fn": name,
                "via_jsx_ref": True,
            })

        def walk(n: Node):
            for child in n.children:
                t = child.type
                if t == 'jsx_expression':
                    # Handled by the outer tree walk — avoid re-processing.
                    continue
                if t == 'identifier':
                    emit(self.get_text(child, source))
                elif t == 'call_expression':
                    # Function position is already counted by _parse_call;
                    # only inspect arguments for callback references.
                    args = child.child_by_field_name('arguments')
                    if args:
                        walk(args)
                elif t == 'member_expression':
                    # e.g. items.map, this.handler — not a bare function ref.
                    continue
                else:
                    walk(child)

        walk(node)

    def _parse_call(self, node: Node, source: bytes,
                     fn_declarations: List[Dict]) -> Optional[Dict]:
        """Parse a call expression and return an edge if it's within a known function.

        For Tauri invoke() calls, extracts the command name from the first string
        argument and creates an edge with is_ipc_call=True. This enables the edge
        resolver to match invoke('getProfiles') to the Rust #[tauri::command]
        handler get_profiles.
        """
        func_node = node.child_by_field_name('function')
        if not func_node:
            return None

        func_text = self.get_text(func_node, source)

        # Find which function this call is inside
        # Use innermost (smallest scope) function that contains this line
        call_line = self.get_line(node)
        caller_id = None
        best_scope_size = float('inf')
        for decl in fn_declarations:
            if decl["scope_start"] <= call_line - 1 <= decl["scope_end"]:
                scope_size = decl["scope_end"] - decl["scope_start"]
                if scope_size < best_scope_size:
                    best_scope_size = scope_size
                    caller_id = decl["node"]["id"]

        if not caller_id:
            return None

        # Determine called function name
        if func_node.type == 'identifier':
            name = func_text
            if name in self.SKIP_NAMES:
                return None

            # ─── Tauri invoke() detection ────────────────────────────
            # When we see invoke('commandName'), extract the command name
            # from the first argument instead of using 'invoke' as to_fn.
            # This is critical for Tauri apps where the frontend calls
            # Rust backend via invoke('getProfiles') etc.
            if name == 'invoke':
                ipc_cmd = self._extract_invoke_command(node, source)
                if ipc_cmd:
                    return {"from": caller_id, "to_fn": ipc_cmd, "is_ipc_call": True}

            return {"from": caller_id, "to_fn": name}

        elif func_node.type == 'member_expression':
            prop_node = func_node.child_by_field_name('property')
            if prop_node:
                method_name = self.get_text(prop_node, source)
                if method_name in self.SKIP_NAMES:
                    return None

                # ─── Tauri invoke via module import ────────────────────
                # Handle cases like: tauri.invoke('cmd') or api.invoke('cmd')
                obj_node = func_node.child_by_field_name('object')
                if obj_node and method_name == 'invoke':
                    ipc_cmd = self._extract_invoke_command(node, source)
                    if ipc_cmd:
                        return {"from": caller_id, "to_fn": ipc_cmd, "is_ipc_call": True}

                return {"from": caller_id, "to_fn": method_name}

        return None

    def _parse_new_expression(self, node: Node, source: bytes,
                               fn_declarations: List[Dict] = None) -> Optional[Dict]:
        """Parse a new_expression node to extract the instantiated class name.

        Handles patterns like:
        - new ClassName(args)
        - new ClassName()
        """
        constructor_node = node.child_by_field_name('constructor')
        if not constructor_node:
            return None

        # Find which function this call is inside
        call_line = self.get_line(node)
        caller_id = None
        if fn_declarations:
            best_scope_size = float('inf')
            for decl in fn_declarations:
                if decl["scope_start"] <= call_line - 1 <= decl["scope_end"]:
                    scope_size = decl["scope_end"] - decl["scope_start"]
                    if scope_size < best_scope_size:
                        best_scope_size = scope_size
                        caller_id = decl["node"]["id"]

        if not caller_id:
            return None

        # Direct class instantiation: new ClassName()
        if constructor_node.type == 'identifier':
            name = self.get_text(constructor_node, source)
            if name in self.SKIP_NAMES:
                return None
            return {"from": caller_id, "to_fn": name}

        # Member expression: new Namespace.ClassName()
        if constructor_node.type == 'member_expression':
            prop_node = constructor_node.child_by_field_name('property')
            if prop_node:
                class_name = self.get_text(prop_node, source)
                if class_name in self.SKIP_NAMES:
                    return None
                return {"from": caller_id, "to_fn": class_name}

        return None

    def _extract_invoke_command(self, node: Node, source: bytes) -> Optional[str]:
        """Extract the Tauri command name from an invoke() call's first argument.

        Handles patterns like:
        - invoke('commandName')
        - invoke<Type>('commandName')
        - invoke<void>('commandName')

        The command name is always the first string literal argument.
        Returns the command name string, or None if not found.
        """
        args_node = node.child_by_field_name('arguments')
        if not args_node:
            return None

        # Find the first string argument
        for child in args_node.children:
            if child.type == 'string':
                value = self._get_string_value(child, source)
                if value and re.match(r'^[a-zA-Z_][\w]*$', value):
                    return value
            # Skip type arguments like <void> or <IProfilesConfig>
            # and template strings
        return None

    def _get_string_value(self, node: Node, source: bytes) -> Optional[str]:
        """Extract string value, removing quotes. Delegates to BaseParser.get_string_value."""
        return self.get_string_value(node, source)
