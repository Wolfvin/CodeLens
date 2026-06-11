"""
Rust Parser for CodeLens — Tree-sitter powered
Extracts function declarations and function calls from Rust source code.

Handles:
- fn name() {}
- pub fn name() {}
- async fn name() {}
- impl blocks: impl TypeName { fn method() {} } → tracked with impl_for
- Method calls: self.method() → tracked with via_self
- Scoped calls: Module::function() → tracked
- Macro calls: println!(), vec!() → IGNORED
- Trait implementations: impl Trait for Type → tracked with impl_for + trait_name
- Comments ignored automatically by tree-sitter
"""

from typing import Dict, List, Any, Optional
from tree_sitter import Node

from base_parser import BaseParser
from grammar_loader import get_grammar_loader


# Rust builtins and macros to skip
SKIP_NAMES = {
    'if', 'else', 'for', 'while', 'loop', 'match', 'return', 'break', 'continue',
    'let', 'mut', 'pub', 'fn', 'struct', 'enum', 'impl', 'trait', 'use', 'mod',
    'crate', 'super', 'self', 'Self', 'where', 'type', 'const', 'static',
    'true', 'false', 'as', 'in', 'ref', 'move', 'dyn', 'async', 'await',
    'Some', 'None', 'Ok', 'Err',
    # Standard macros
    'println', 'eprintln', 'print', 'eprint', 'format', 'format_args',
    'vec', 'boxed', 'slice', 'array',
    'panic', 'assert', 'assert_eq', 'assert_ne', 'debug_assert', 'debug_assert_eq',
    'todo', 'unimplemented', 'unreachable', 'compile_error',
    'write', 'writeln', 'read_line',
    'derive', 'test', 'cfg', 'allow', 'warn', 'doc', 'feature',
    'include', 'include_str', 'include_bytes',
    'concat', 'env', 'option_env', 'file', 'line', 'column', 'module_path',
    'thread_local', 'lazy_static',
    # Common std types
    'String', 'Vec', 'Box', 'Rc', 'Arc', 'Cell', 'RefCell',
    'HashMap', 'HashSet', 'BTreeMap', 'BTreeSet',
    'Result', 'Option', 'Cow', 'Duration', 'Instant',
    'Default', 'Display', 'Debug', 'Clone', 'Copy', 'From', 'Into',
    'FromStr', 'ToString', 'Iterator', 'IntoIterator',
    'new', 'default', 'from', 'into', 'clone', 'drop',
}


class RustParser(BaseParser):
    """Parse Rust to extract function declarations and call graph."""

    def __init__(self):
        loader = get_grammar_loader()
        lang = loader.get_language('rust')
        if not lang:
            raise RuntimeError("tree-sitter-rust not installed")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict]]:
        """
        Extract function nodes and edges from Rust content.

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        source = content.encode('utf-8')
        tree = self.parse(source)

        nodes = []
        edges = []

        # Track current impl context with proper scope management
        current_impl_for = None
        current_trait_name = None
        # Stack of (impl_for, trait_name, end_byte) for scope tracking
        impl_scope_stack = []

        # Find all function items and impl items
        fn_declarations = []

        def visit(node: Node, _, depth):
            nonlocal current_impl_for, current_trait_name

            # Pop impl scopes that have ended (node starts after scope ended)
            while impl_scope_stack and node.start_byte >= impl_scope_stack[-1][2]:
                impl_scope_stack.pop()
                if impl_scope_stack:
                    current_impl_for, current_trait_name = impl_scope_stack[-1][0], impl_scope_stack[-1][1]
                else:
                    current_impl_for = None
                    current_trait_name = None

            if node.type == 'impl_item':
                impl_for, trait_name = self._parse_impl(node, source)
                # Push current scope, then set new context
                impl_scope_stack.append((impl_for, trait_name, node.end_byte))
                current_impl_for = impl_for
                current_trait_name = trait_name

            elif node.type == 'function_item':
                decl = self._parse_function_item(node, source, file_path,
                                                  current_impl_for, current_trait_name)
                if decl:
                    fn_declarations.append(decl)
                    nodes.append(decl["node"])

        self.walk_tree(tree, source, visit)

        # Second pass: find all function calls within each function's scope
        for decl in fn_declarations:
            if decl.get("body_node"):
                fn_calls = self._find_calls_in_body(decl["body_node"], source)
                for call_info in fn_calls:
                    edges.append({
                        "from": decl["node"]["id"],
                        "to_fn": call_info["fn_name"],
                        "via_self": call_info.get("via_self", False)
                    })

        return {"nodes": nodes, "edges": edges}

    def _parse_impl(self, node: Node, source: bytes) -> tuple:
        """Parse an impl_item node to extract the type and optional trait."""
        impl_for = None
        trait_name = None

        for child in node.children:
            if child.type == 'type_identifier':
                impl_for = self.get_text(child, source)
            elif child.type == 'trait_bound' or child.type == 'scoped_type_identifier':
                # impl Trait for Type
                text = self.get_text(child, source)
                if 'for' in text:
                    parts = text.split('for')
                    trait_name = parts[0].strip()
                    if not impl_for and len(parts) > 1:
                        impl_for = parts[1].strip()
                else:
                    trait_name = text

        return impl_for, trait_name

    def _parse_function_item(self, node: Node, source: bytes, file_path: str,
                              impl_for: Optional[str], trait_name: Optional[str]) -> Optional[Dict]:
        """Parse a function_item node."""
        fn_name = None
        is_pub = False
        is_async = False
        body_node = None

        for child in node.children:
            if child.type == 'identifier':
                fn_name = self.get_text(child, source)
            elif child.type == 'visibility_modifier':
                is_pub = True
            elif child.type == 'function_modifiers':
                # Check for async inside modifiers
                for mc in child.children:
                    if mc.type == 'async':
                        is_async = True
            elif child.type == 'block':
                body_node = child

        if not fn_name:
            return None

        line = self.get_line(node)
        node_data = {
            "id": f"{file_path}:{line}",
            "fn": fn_name,
            "file": file_path,
            "line": line,
            "pub": is_pub,
            "async": is_async
        }

        if impl_for:
            node_data["impl_for"] = impl_for
        if trait_name:
            node_data["trait_name"] = trait_name

        return {
            "node": node_data,
            "body_node": body_node,
            "scope_start": node.start_point.row,
            "scope_end": node.end_point.row
        }

    def _find_calls_in_body(self, body_node: Node, source: bytes) -> List[Dict]:
        """Find all function calls within a function body."""
        calls = []

        def visit(node: Node, _, depth):
            if node.type == 'call_expression':
                call_info = self._parse_call(node, source)
                if call_info:
                    calls.append(call_info)

        self.walk_tree(body_node, source, visit)
        return calls

    def _parse_call(self, node: Node, source: bytes) -> Optional[Dict]:
        """Parse a call_expression to extract the called function name."""
        func_node = node.child_by_field_name('function')
        if not func_node:
            return None

        # Direct call: function_name(args)
        if func_node.type == 'identifier':
            name = self.get_text(func_node, source)
            if name in SKIP_NAMES:
                return None
            return {"fn_name": name}

        # Field expression: self.method() or obj.method()
        if func_node.type == 'field_expression':
            obj_node = func_node.child_by_field_name('object')
            field_node = func_node.child_by_field_name('field')

            if field_node:
                method_name = self.get_text(field_node, source)
                if method_name in SKIP_NAMES:
                    return None

                via_self = False
                if obj_node and self.get_text(obj_node, source) == 'self':
                    via_self = True

                return {"fn_name": method_name, "via_self": via_self}

        # Scoped identifier: Module::function()
        if func_node.type == 'scoped_identifier':
            # Get the last part (function name)
            text = self.get_text(func_node, source)
            parts = text.split('::')
            if parts:
                name = parts[-1]
                if name in SKIP_NAMES:
                    return None
                return {"fn_name": name}

        return None
