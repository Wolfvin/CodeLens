"""
JS Backend Parser for CodeLens — Tree-sitter powered
Extracts function declarations and function calls from JS non-frontend code.

Handles:
- function declarations: function name() {}
- arrow functions: const name = () => {}
- function expressions: const name = function() {}
- async variants of all above
- Method calls: obj.method() → tracked as "method"
- Member expression calls: HttpClient.new()
- Anonymous/inline callbacks → IGNORED
- Built-in keywords filtered out
"""

from typing import Dict, List, Any, Optional, Tuple
import re
from tree_sitter import Node

from base_parser import BaseParser, JS_TS_SKIP_NAMES_BASE, JS_TS_BACKEND_SKIP_NAMES_EXTRA
from grammar_loader import get_grammar_loader


# JS keywords and builtins to skip when detecting function calls
SKIP_NAMES = JS_TS_SKIP_NAMES_BASE | JS_TS_BACKEND_SKIP_NAMES_EXTRA


class JSBackendParser(BaseParser):
    """Parse backend JS to extract function declarations and call graph."""

    FN_DECL_TYPES = {
        'function_declaration',
        'generator_function_declaration',
        'variable_declarator',  # for arrow functions and function expressions
        'class_declaration',   # for TypeScript/JS class declarations
    }

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('javascript')
        if not lang:
            raise RuntimeError("tree-sitter-javascript not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract function nodes and edges from backend JS.

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        nodes = []
        edges = []

        # First pass: find all function declarations
        fn_declarations = self._find_function_declarations(tree, source, file_path)

        # Build a map of line → function for scope resolution
        fn_scope_map = self._build_scope_map(fn_declarations)

        # Second pass: find all function calls within each scope
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

        return {"nodes": nodes, "edges": edges}

    def _find_function_declarations(self, root: Node, source: bytes,
                                     file_path: str) -> List[Dict]:
        """Find all function declarations in the AST."""
        declarations = []

        def visit(node: Node, _, depth):
            decl_info = None

            if node.type == 'function_declaration' or node.type == 'generator_function_declaration':
                decl_info = self._parse_function_decl(node, source, file_path)

            elif node.type == 'variable_declarator':
                decl_info = self._parse_variable_declarator(node, source, file_path)

            elif node.type == 'class_declaration':
                decl_info = self._parse_class_decl(node, source, file_path)

            if decl_info:
                declarations.append(decl_info)
                return True  # Continue walking to find nested functions

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
        """Parse a variable_declarator that contains an arrow function or function expression."""
        name_node = None
        value_node = None
        is_async = False

        for child in node.children:
            if child.type == 'identifier':
                name_node = child
            elif child.type in ('arrow_function', 'function_expression'):
                value_node = child
                # Check async
                for vc in child.children:
                    if vc.type == 'async':
                        is_async = True

        if not name_node or not value_node:
            return None

        fn_name = self.get_text(name_node, source)
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
        This allows classes like `BookingRepository` to appear as nodes
        in the backend registry, making them discoverable via query/context/trace.
        """
        class_name = None
        body_node = None
        heritage = None  # extends/implements info

        for child in node.children:
            if child.type == 'identifier':
                class_name = self.get_text(child, source)
            elif child.type == 'class_heritage':
                # e.g., extends BaseRepo or implements IRepository
                heritage = self.get_text(child, source)
            elif child.type == 'class_body':
                body_node = child

        if not class_name:
            return None

        line = self.get_line(node)
        node_id = f"{file_path}:{line}"

        # Determine if it's a React component (PascalCase + extends Component)
        is_component = class_name[0].isupper() and (
            heritage and ('Component' in heritage or 'React' in heritage)
        )

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
                # Handle: tauri.invoke('cmd') or api.invoke('cmd')
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
