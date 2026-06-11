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
- Tauri IPC commands: #[tauri::command] → tracked with is_tauri_command + ipc_name
- Method call context: obj.method() → tracked with call_object for self-edge prevention
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

        # Track current impl context
        current_impl_for = None
        current_trait_name = None

        # Pre-scan for #[tauri::command] attribute lines
        tauri_command_lines = self._find_tauri_command_lines(source)

        # Find all function items and impl items
        fn_declarations = []

        def visit(node: Node, _, depth):
            nonlocal current_impl_for, current_trait_name

            if node.type == 'impl_item':
                current_impl_for, current_trait_name = self._parse_impl(node, source)

            elif node.type == 'function_item':
                # Only apply impl_for if this function is a descendant of an impl_item.
                # Walk up the tree to check if any ancestor is an impl_item.
                impl_for_this_fn = current_impl_for
                trait_for_this_fn = current_trait_name
                parent = node.parent
                found_impl = False
                while parent is not None:
                    if parent.type == 'impl_item':
                        found_impl = True
                        break
                    # If we hit a module or source_file before an impl, this function
                    # is at module level, not inside an impl.
                    if parent.type in ('source_file', 'mod_item', 'declaration_statement'):
                        break
                    parent = parent.parent

                if not found_impl:
                    impl_for_this_fn = None
                    trait_for_this_fn = None

                # Check if this function is a Tauri command
                fn_line = self.get_line(node)
                is_tauri_cmd = fn_line in tauri_command_lines

                decl = self._parse_function_item(node, source, file_path,
                                                  impl_for_this_fn, trait_for_this_fn,
                                                  is_tauri_cmd=is_tauri_cmd)
                if decl:
                    fn_declarations.append(decl)
                    nodes.append(decl["node"])

                # Reset impl for after processing the function inside it
                # (impl contains functions, so we keep context while inside)

        self.walk_tree(tree, source, visit)

        # Reset impl tracking for second pass
        current_impl_for = None
        current_trait_name = None

        # Second pass: find all function calls within each function's scope
        for decl in fn_declarations:
            if decl.get("body_node"):
                fn_calls = self._find_calls_in_body(decl["body_node"], source)
                for call_info in fn_calls:
                    edge = {
                        "from": decl["node"]["id"],
                        "to_fn": call_info["fn_name"],
                        "via_self": call_info.get("via_self", False),
                    }
                    # Track call object context to prevent false self-edges.
                    # When a function foo() calls obj.foo(), the edge resolver
                    # might match it back to itself. Including call_object
                    # lets the resolver know this is a method call on a different
                    # object, not a recursive call.
                    if call_info.get("call_object"):
                        edge["call_object"] = call_info["call_object"]
                    edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    def _find_tauri_command_lines(self, source: bytes) -> set:
        """Pre-scan to find line numbers of functions annotated with #[tauri::command].

        Returns a set of 1-indexed line numbers where tauri::command functions start.
        """
        lines = source.split(b'\n')
        tauri_lines = set()
        for i, line in enumerate(lines):
            if b'#[tauri::command' in line:
                # Scan forward to find the fn declaration (within next 5 lines)
                for offset in range(0, 6):
                    target = i + offset
                    if target >= len(lines):
                        break
                    if b'fn ' in lines[target]:
                        tauri_lines.add(target + 1)  # 1-indexed
                        break
        return tauri_lines

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
                              impl_for: Optional[str], trait_name: Optional[str],
                              is_tauri_cmd: bool = False) -> Optional[Dict]:
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

        # Track Tauri IPC commands — these are exposed to the frontend via invoke()
        if is_tauri_cmd:
            node_data["is_tauri_command"] = True
            # Tauri default: snake_case Rust names → camelCase in JS/TS
            ipc_name = _snake_to_camel(fn_name)
            node_data["ipc_name"] = ipc_name

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
        """Parse a call_expression to extract the called function name.

        Also tracks call_object for method calls (e.g., window.open_devtools()
        records call_object="window") to help the edge resolver prevent
        false self-edges when a function name matches a method call on a
        different object.
        """
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
            # Tree-sitter Rust grammar uses 'value' for the object and 'field'
            # for the method name (NOT 'object' as in other grammars).
            obj_node = func_node.child_by_field_name('value')
            if not obj_node:
                obj_node = func_node.child_by_field_name('object')  # fallback
            field_node = func_node.child_by_field_name('field')

            if field_node:
                method_name = self.get_text(field_node, source)
                if method_name in SKIP_NAMES:
                    return None

                via_self = False
                call_object = None
                obj_text = ""
                if obj_node:
                    obj_text = self.get_text(obj_node, source)
                    if obj_text == 'self':
                        via_self = True
                    else:
                        # Track the object name for self-edge prevention.
                        # e.g., window.open_devtools() → call_object="window"
                        # This helps the resolver know that open_devtools() called
                        # on "window" is NOT the same as the free fn open_devtools().
                        call_object = obj_text

                result = {"fn_name": method_name, "via_self": via_self}
                if call_object:
                    result["call_object"] = call_object
                return result

        # Scoped identifier: Module::function()
        if func_node.type == 'scoped_identifier':
            # Get the last part (function name)
            text = self.get_text(func_node, source)
            parts = text.split('::')
            if parts:
                name = parts[-1]
                if name in SKIP_NAMES:
                    return None
                # Track the module path for scoped calls
                result = {"fn_name": name}
                if len(parts) > 1:
                    result["call_object"] = '::'.join(parts[:-1])
                return result

        return None


# ─── Case Conversion Helper ────────────────────────────────────

def _snake_to_camel(name: str) -> str:
    """Convert snake_case Rust function name to camelCase for Tauri IPC naming.

    Tauri by default converts Rust snake_case command names to camelCase
    in the JavaScript/TypeScript frontend. For example:
    - get_profiles → getProfiles
    - patch_verge_config → patchVergeConfig
    - start_core → startCore
    """
    if '_' not in name:
        return name
    parts = name.split('_')
    return parts[0] + ''.join(p.capitalize() for p in parts[1:] if p)
