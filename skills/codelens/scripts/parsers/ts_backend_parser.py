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
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


# TS/JS keywords and builtins to skip when detecting function calls
SKIP_NAMES = {
    'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
    'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
    'async', 'await', 'yield', 'import', 'export', 'from', 'default',
    'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
    'true', 'false', 'null', 'undefined', 'void', 'delete',
    'console', 'require', 'module', 'exports', 'process', 'global',
    'String', 'Number', 'Boolean', 'Array', 'Object', 'Map', 'Set',
    'Promise', 'Error', 'TypeError', 'RangeError', 'SyntaxError',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
    'decodeURIComponent', 'encodeURI', 'decodeURI',
    'JSON', 'Date', 'RegExp', 'Math', 'Buffer', 'setTimeout', 'setInterval',
    'clearTimeout', 'clearInterval', 'setImmediate', 'clearImmediate',
    'addEventListener', 'removeEventListener',
}


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
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        nodes = []
        edges = []
        fn_stack = []  # Stack of (fn_name, node_id) for nested functions

        # First pass: find all function declarations
        fn_declarations = self._find_function_declarations(tree, source, file_path)

        # Build a map of line -> function for scope resolution
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
            # Handle export_statement by recursing into children
            if node.type == 'export_statement':
                for child in node.children:
                    if child.type in ('function_declaration', 'generator_function_declaration'):
                        decl = self._parse_function_decl(child, source, file_path)
                        if decl:
                            declarations.append(decl)
                    elif child.type == 'lexical_declaration':
                        # export const foo = () => {}
                        for subchild in child.children:
                            if subchild.type == 'variable_declarator':
                                decl = self._parse_variable_declarator(subchild, source, file_path)
                                if decl:
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
                    import re
                    if value and re.match(r'^[a-zA-Z_][\\w]*$', value):
                        return value
        return None
