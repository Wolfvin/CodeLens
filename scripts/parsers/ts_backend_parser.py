"""
TypeScript Backend Parser for CodeLens — Tree-sitter powered
Extracts function declarations and function calls from TS non-frontend code.

Handles:
- function declarations: function name() {}
- export function declarations: export function name() {}
- Arrow functions: const name = () => {}
- Function expressions: const name = function() {}
- Async variants of all above
- Interface method signatures: interface Foo { bar(): void }
- Type alias declarations
- Enum declarations
- Abstract method signatures
- Method calls: obj.method() -> tracked as "method"
- Member expression calls: HttpClient.new()
- Anonymous/inline callbacks -> IGNORED
- Built-in keywords filtered out
"""

from typing import Dict, List, Any, Optional, Tuple
import re
from tree_sitter import Node

from base_parser import BaseParser, JS_TS_SKIP_NAMES_BASE, JS_TS_BACKEND_SKIP_NAMES_EXTRA
from grammar_loader import get_grammar_loader


# TS/JS keywords and builtins to skip when detecting function calls
SKIP_NAMES = JS_TS_SKIP_NAMES_BASE | JS_TS_BACKEND_SKIP_NAMES_EXTRA


class TSBackendParser(BaseParser):
    """Parse backend TS to extract function declarations and call graph."""

    FN_DECL_TYPES = {
        'function_declaration',
        'generator_function_declaration',
        'variable_declarator',  # for arrow functions and function expressions
    }

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('tsx')
        if not lang:
            raise RuntimeError("tree-sitter-typescript not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract function nodes and edges from backend TS.

        Returns:
            {"nodes": [...], "edges": [...]}

        Issue #210: Previously only calls inside named function bodies were
        collected. Two common patterns were silently dropped:

        1. Module-scope calls — e.g. ``router.post(path, requirePermission('admin'), handler)``
           at the top level of a route file. The ``requirePermission('admin')``
           call_expression is not inside any function declaration, so it was
           never turned into an edge. This caused middleware-factory functions
           like ``requirePermission`` to get ``ref_count == 0`` even when used
           in dozens of route files.

        2. Arrow functions in object literals — e.g.
           ``const service = { list: (ctx) => { hasPermission(ctx.user, 'read'); ... } }``.
           The ``variable_declarator`` value is an ``object`` node (not an
           ``arrow_function``), so ``_parse_variable_declarator`` returned
           None and the arrow function's body calls were lost. This caused
           service-map-style modules to be invisible to the call graph.

        Both patterns are now handled: module-scope calls are attributed to
        a synthetic ``<module>`` node per file, and object-literal arrow
        functions are registered as ``<varName>.<propertyName>`` nodes.
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        nodes = []
        edges = []

        # First pass: find all function declarations (named functions,
        # classes, and variable-bound arrow/function expressions).
        fn_declarations = self._find_function_declarations(tree, source, file_path)

        # Issue #210: Also find arrow functions assigned to object-literal
        # properties (e.g. ``const svc = { list: (ctx) => {...} }``) and
        # register them as <varName>.<key> nodes. These were previously
        # invisible to the call graph.
        fn_declarations.extend(
            self._find_object_literal_methods(tree, source, file_path)
        )

        # Build a map of line -> function for scope resolution
        fn_scope_map = self._build_scope_map(fn_declarations)

        # Track body byte ranges of every registered function so the
        # module-scope pass can skip calls that are already attributed.
        fn_body_ranges: List[Tuple[int, int]] = []
        for decl in fn_declarations:
            body = decl.get("body_node")
            if body is not None:
                fn_body_ranges.append((body.start_byte, body.end_byte))
            # Also mark the enclosing decl range so calls in the
            # parameter list / heritage clause are not double-counted.
            # We use the body range only — calls in defaults/params are
            # rare and attributing them to the function is acceptable.

        # Second pass: find all function calls within each function's body
        for decl in fn_declarations:
            nodes.append(decl["node"])
            # Find calls within this function's body
            fn_calls = self._find_calls_in_scope(decl["body_node"], source, file_path)
            for call_info in fn_calls:
                edge = {
                    "from": decl["node"]["id"],
                    "to_fn": call_info["fn_name"],
                    "via_self": call_info.get("via_self", False)
                }
                if call_info.get("is_ipc_call"):
                    edge["is_ipc_call"] = True
                edges.append(edge)

        # Issue #210: Third pass — collect module-scope calls (calls that
        # occur outside any registered function body). These are attributed
        # to a synthetic <module> node so that the call graph records them
        # as edges, even though there is no enclosing function declaration.
        module_calls = self._find_module_scope_calls(tree, source, fn_body_ranges)
        if module_calls:
            module_node_id = f"{file_path}:0"
            module_node = {
                "id": module_node_id,
                "fn": "<module>",
                "file": file_path,
                "line": 0,
                "async": False,
                "exported": True,      # module scope is never dead code
                "node_type": "module",  # marker for downstream filters
            }
            nodes.append(module_node)
            for call_info in module_calls:
                edge = {
                    "from": module_node_id,
                    "to_fn": call_info["fn_name"],
                    "via_self": call_info.get("via_self", False)
                }
                if call_info.get("is_ipc_call"):
                    edge["is_ipc_call"] = True
                edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    def _find_function_declarations(self, root: Node, source: bytes,
                                     file_path: str) -> List[Dict]:
        """Find all function declarations in the AST."""
        declarations = []

        def visit(node: Node, _, depth):
            # Handle export_statement by recursing into children and marking exported
            if node.type == 'export_statement':
                for child in node.children:
                    if child.type in ('function_declaration', 'generator_function_declaration'):
                        decl = self._parse_function_decl(child, source, file_path)
                        if decl:
                            decl["node"]["exported"] = True
                            declarations.append(decl)
                    elif child.type == 'class_declaration':
                        decl = self._parse_class_decl(child, source, file_path)
                        if decl:
                            decl["node"]["exported"] = True
                            declarations.append(decl)
                    elif child.type == 'lexical_declaration':
                        # export const foo = () => {}
                        for subchild in child.children:
                            if subchild.type == 'variable_declarator':
                                decl = self._parse_variable_declarator(subchild, source, file_path)
                                if decl:
                                    decl["node"]["exported"] = True
                                    declarations.append(decl)
                    elif child.type == 'default_export_clause':
                        # export default class Name / export default function name
                        for subchild in child.children:
                            if subchild.type == 'class_declaration':
                                decl = self._parse_class_decl(subchild, source, file_path)
                                if decl:
                                    decl["node"]["exported"] = True
                                    declarations.append(decl)
                            elif subchild.type in ('function_declaration', 'generator_function_declaration'):
                                decl = self._parse_function_decl(subchild, source, file_path)
                                if decl:
                                    decl["node"]["exported"] = True
                                    declarations.append(decl)
                return False  # Don't double-count by continuing walk

            if node.type in ('function_declaration', 'generator_function_declaration'):
                decl = self._parse_function_decl(node, source, file_path)
                if decl:
                    declarations.append(decl)
            elif node.type == 'variable_declarator':
                # Only process if parent is NOT an export_statement (to avoid double-counting)
                if node.parent and node.parent.type != 'lexical_declaration':
                    decl = self._parse_variable_declarator(node, source, file_path)
                    if decl:
                        declarations.append(decl)
                elif node.parent and node.parent.type == 'lexical_declaration':
                    if node.parent.parent and node.parent.parent.type != 'export_statement':
                        decl = self._parse_variable_declarator(node, source, file_path)
                        if decl:
                            declarations.append(decl)
            # Note: object-literal pair arrow functions are collected in a
            # separate pass (_find_object_literal_methods) so they work
            # uniformly for both exported and non-exported variables.
            # Walking them here would require descending into export_statement
            # children, which the export branch above explicitly avoids to
            # prevent double-counting of function/class declarations.

        self.walk_tree(root, source, visit)
        return declarations

    def _find_object_literal_methods(self, root: Node, source: bytes,
                                      file_path: str) -> List[Dict]:
        """Find all ``pair`` nodes whose value is an arrow_function or
        function_expression, and register them as function declarations.

        Issue #210: Arrow functions assigned to object-literal properties
        (e.g. ``const service = { list: (ctx) => { ... } }``) were
        invisible to the call graph because:

        1. The enclosing ``variable_declarator`` value is an ``object`` node
           (not an ``arrow_function``), so ``_parse_variable_declarator``
           returned None.
        2. The main walk in ``_find_function_declarations`` does not descend
           into ``export_statement`` children (to avoid double-counting), so
           pairs inside exported object literals were never visited.

        This separate pass walks the entire AST and registers every pair
        with an arrow/function value as a node named
        ``<enclosingVarName>.<key>`` (or just ``<key>`` if the pair is not
        inside a variable_declarator, e.g. an object literal passed as a
        function argument).
        """
        declarations: List[Dict] = []

        def visit(node: Node, _, depth):
            if node.type == 'pair':
                decl = self._parse_object_literal_pair(node, source, file_path)
                if decl:
                    declarations.append(decl)
            return True

        self.walk_tree(root, source, visit)
        return declarations

    def _parse_function_decl(self, node: Node, source: bytes,
                              file_path: str) -> Optional[Dict]:
        """Parse a function_declaration node."""
        fn_name = None
        is_async = False

        for child in node.children:
            if child.type == 'identifier':
                fn_name = self.get_text(child, source)
            elif child.type == 'async':
                is_async = True

        if not fn_name:
            return None

        line = self.get_line(node)
        node_id = f"{file_path}:{line}"

        # Find the body node
        body_node = None
        for child in node.children:
            if child.type == 'statement_block':
                body_node = child
                break

        return {
            "node": {
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line,
                "async": is_async
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

    def _parse_variable_declarator(self, node: Node, source: bytes,
                                    file_path: str) -> Optional[Dict]:
        """Parse a variable_declarator that contains an arrow function, function expression, or Pinia store."""
        name_node = None
        value_node = None
        is_async = False
        is_pinia_store = False

        for child in node.children:
            if child.type == 'identifier':
                name_node = child
            elif child.type in ('arrow_function', 'function_expression'):
                value_node = child
                # Check async
                for vc in child.children:
                    if vc.type == 'async':
                        is_async = True
            elif child.type == 'call_expression':
                # Check if this is a defineStore() call (Pinia store)
                func_node = child.child_by_field_name('function')
                if func_node and self.get_text(func_node, source) == 'defineStore':
                    is_pinia_store = True
                    value_node = child

        if not name_node:
            return None

        fn_name = self.get_text(name_node, source)
        line = self.get_line(node)
        node_id = f"{file_path}:{line}"

        if is_pinia_store:
            # Pinia store: const useXxxStore = defineStore('name', () => {...})
            # The body is the arrow function argument of defineStore
            body_node = None
            if value_node:
                # Find the arrow_function argument within the call_expression
                for arg in value_node.children:
                    if arg.type == 'arrow_function':
                        for ac in arg.children:
                            if ac.type in ('statement_block', 'expression'):
                                body_node = ac
                                break
                        break
                    elif arg.type == 'function_expression':
                        for ac in arg.children:
                            if ac.type == 'statement_block':
                                body_node = ac
                                break
                        break

            return {
                "node": {
                    "id": node_id,
                    "fn": fn_name,
                    "file": file_path,
                    "line": line,
                    "async": is_async,
                    "type": "pinia_store"
                },
                "body_node": body_node,
                "scope_start": node.start_point.row,
                "scope_end": node.end_point.row
            }

        if not value_node:
            return None

        # Find the body
        body_node = None
        for child in value_node.children:
            if child.type in ('statement_block', 'expression'):
                body_node = child
                break

        return {
            "node": {
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line,
                "async": is_async
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

    def _parse_class_decl(self, node: Node, source: bytes,
                           file_path: str) -> Optional[Dict]:
        """Parse a class_declaration node.

        Extracts the class name and its body as a scope.
        Handles both named classes and export default class declarations.
        """
        class_name = None
        body_node = None
        heritage = None

        for child in node.children:
            if child.type == 'identifier' or child.type == 'type_identifier':
                class_name = self.get_text(child, source)
            elif child.type == 'class_heritage':
                heritage = self.get_text(child, source)
            elif child.type == 'class_body':
                body_node = child

        if not class_name:
            return None

        line = self.get_line(node)
        node_id = f"{file_path}:{line}"

        # Any PascalCase class is marked as component to prevent false dead-code marking
        is_component = class_name[0].isupper()

        result = {
            "node": {
                "id": node_id,
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

    def _build_scope_map(self, declarations: List[Dict]) -> Dict:
        """Build a map of function scopes for call resolution."""
        # Sort by start position
        sorted_decls = sorted(declarations, key=lambda d: d["scope_start"])
        return {i: d for i, d in enumerate(sorted_decls)}

    def _parse_object_literal_pair(self, node: Node, source: bytes,
                                    file_path: str) -> Optional[Dict]:
        """Parse a ``pair`` node whose value is an arrow_function or
        function_expression, e.g. ``list: (ctx) => { ... }``.

        Issue #210: Arrow functions assigned to object-literal properties
        were previously invisible to the call graph because their enclosing
        ``variable_declarator`` value is an ``object`` node (not an
        ``arrow_function``), so ``_parse_variable_declarator`` returned None.

        We register each such arrow function as a node named
        ``<enclosingVarName>.<key>`` so calls inside its body are properly
        attributed. The enclosing var name is found by walking up to the
        nearest ``variable_declarator`` ancestor and reading its identifier.
        """
        key_node = None
        value_node = None
        for child in node.children:
            if child.type in ('property_identifier', 'identifier'):
                key_node = child
            elif child.type in ('arrow_function', 'function_expression'):
                value_node = child

        if key_node is None or value_node is None:
            return None

        # Find the enclosing variable_declarator to use as the name prefix.
        # If there is none (e.g., the pair is inside a function-argument
        # object literal), fall back to just the key name.
        prefix = ""
        parent = node.parent
        while parent is not None:
            if parent.type == 'variable_declarator':
                for pc in parent.children:
                    if pc.type == 'identifier':
                        prefix = self.get_text(pc, source)
                        break
                break
            # Stop at function boundaries — we don't want to attribute a
            # pair inside a function body to an outer-scope variable.
            if parent.type in ('function_declaration', 'generator_function_declaration',
                               'arrow_function', 'function_expression',
                               'method_definition'):
                break
            parent = parent.parent

        key_name = self.get_text(key_node, source)
        if prefix:
            fn_name = f"{prefix}.{key_name}"
        else:
            fn_name = key_name

        # Check async
        is_async = False
        for vc in value_node.children:
            if vc.type == 'async':
                is_async = True
                break

        line = self.get_line(node)
        node_id = f"{file_path}:{line}"

        # Find the body
        body_node = None
        for child in value_node.children:
            if child.type in ('statement_block', 'expression'):
                body_node = child
                break

        return {
            "node": {
                "id": node_id,
                "fn": fn_name,
                "file": file_path,
                "line": line,
                "async": is_async,
                "node_type": "object_method",
            },
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row,
        }

    def _find_module_scope_calls(self, root: Node, source: bytes,
                                  fn_body_ranges: List[Tuple[int, int]]
                                  ) -> List[Dict]:
        """Find all call_expression / new_expression nodes that are NOT
        inside any registered function body.

        Issue #210: Calls at module scope (e.g.
        ``router.post(path, requirePermission('admin'), handler)`` at the
        top level of a route file) were silently dropped because no
        enclosing function declaration existed to collect them.

        We walk the entire AST and check each call's byte range against
        the registered function body ranges. Calls outside all ranges
        are returned for attribution to the synthetic ``<module>`` node.
        """
        if not fn_body_ranges:
            # Fast path: no registered functions, every call is module-scope.
            # Sort nothing — just walk.
            pass

        calls: List[Dict] = []

        def _is_inside_fn_body(node: Node) -> bool:
            start = node.start_byte
            end = node.end_byte
            for body_start, body_end in fn_body_ranges:
                if start >= body_start and end <= body_end:
                    return True
            return False

        def visit(node: Node, _, depth):
            if node.type == 'call_expression':
                if not _is_inside_fn_body(node):
                    call_info = self._parse_call(node, source)
                    if call_info:
                        calls.append(call_info)
            elif node.type == 'new_expression':
                if not _is_inside_fn_body(node):
                    call_info = self._parse_new_expression(node, source)
                    if call_info:
                        calls.append(call_info)
            return True

        self.walk_tree(root, source, visit)
        return calls

    def _find_calls_in_scope(self, body_node: Optional[Node], source: bytes,
                              file_path: str) -> List[Dict]:
        """Find all function calls within a function body."""
        if not body_node:
            return []

        calls = []

        def visit(node: Node, _, depth):
            if node.type == 'call_expression':
                call_info = self._parse_call(node, source)
                if call_info:
                    calls.append(call_info)
            elif node.type == 'new_expression':
                call_info = self._parse_new_expression(node, source)
                if call_info:
                    calls.append(call_info)

        self.walk_tree(body_node, source, visit)
        return calls

    def _parse_call(self, node: Node, source: bytes) -> Optional[Dict]:
        """Parse a call_expression node to extract the called function name.

        For Tauri invoke() calls, extracts the command name from the first
        string argument and marks it as is_ipc_call for the edge resolver.
        """
        func_node = node.child_by_field_name('function')
        if not func_node:
            return None

        func_text = self.get_text(func_node, source)

        # Direct function call: functionName(args)
        if func_node.type == 'identifier':
            name = func_text
            if name in SKIP_NAMES:
                return None

            # ─── Tauri invoke() detection ────────────────────────────
            # Extract the command name from the first string argument.
            if name == 'invoke':
                ipc_cmd = self._extract_invoke_command(node, source)
                if ipc_cmd:
                    return {"fn_name": ipc_cmd, "is_ipc_call": True}

            return {"fn_name": name}

        # Member expression: obj.method(args)
        if func_node.type == 'member_expression':
            obj_node = func_node.child_by_field_name('object')
            prop_node = func_node.child_by_field_name('property')

            if prop_node:
                method_name = self.get_text(prop_node, source)
                if method_name in SKIP_NAMES:
                    return None

                # Check if it's a DOM/classList call we should skip
                if method_name in ('classList', 'addEventListener', 'removeEventListener',
                                   'setAttribute', 'getAttribute', 'removeAttribute',
                                   'appendChild', 'removeChild', 'insertBefore'):
                    return None

                # ─── Tauri invoke via module import ────────────────────
                if method_name == 'invoke':
                    ipc_cmd = self._extract_invoke_command(node, source)
                    if ipc_cmd:
                        return {"fn_name": ipc_cmd, "is_ipc_call": True}

                # Check if it's self.method()
                if obj_node and self.get_text(obj_node, source) == 'self':
                    return {"fn_name": method_name, "via_self": True}

                # Return as "obj.method" for better resolution
                obj_text = self.get_text(obj_node, source) if obj_node else ""
                # But for edge resolution, use just the method name
                return {"fn_name": method_name, "via_self": False}

        return None

    def _parse_new_expression(self, node: Node, source: bytes) -> Optional[Dict]:
        """Parse a new_expression node to extract the instantiated class name.

        Handles patterns like:
        - new ClassName(args)
        - new ClassName()

        This is critical for tracking class instantiation edges, which previously
        were missed — causing exported classes like AxiosError to appear "dead"
        even though they are widely instantiated via `new AxiosError()`.
        """
        constructor_node = node.child_by_field_name('constructor')
        if not constructor_node:
            return None

        # Direct class instantiation: new ClassName()
        if constructor_node.type == 'identifier':
            name = self.get_text(constructor_node, source)
            if name in SKIP_NAMES:
                return None
            return {"fn_name": name, "is_instantiation": True}

        # Member expression: new Namespace.ClassName()
        if constructor_node.type == 'member_expression':
            prop_node = constructor_node.child_by_field_name('property')
            if prop_node:
                class_name = self.get_text(prop_node, source)
                if class_name in SKIP_NAMES:
                    return None
                return {"fn_name": class_name, "is_instantiation": True}

        return None

    def _extract_invoke_command(self, node: Node, source: bytes) -> Optional[str]:
        """Extract the Tauri command name from an invoke() call's first argument.

        Handles patterns like:
        - invoke('commandName')
        - invoke<Type>('commandName')

        Returns the command name string, or None if not found.
        """
        args_node = node.child_by_field_name('arguments')
        if not args_node:
            return None

        for child in args_node.children:
            if child.type == 'string':
                text = self.get_text(child, source)
                if (text.startswith("'") and text.endswith("'")) or \
                   (text.startswith('"') and text.endswith('"')):
                    value = text[1:-1]
                    if value and re.match(r'^[a-zA-Z_][\\w]*$', value):
                        return value
        return None
