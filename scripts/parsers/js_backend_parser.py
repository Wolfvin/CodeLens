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
            {
                "nodes": [...],
                "edges": [...],
                "skipped": [{"file": str, "reason": str, "lines": int}]  # empty in normal operation
            }

        Single-pass recursive walk (issue #116): the previous two-pass
        design held ``body_node`` Node references across function
        boundaries, which could dangle when tree-sitter's internal
        cleanup ran between passes and caused SIGSEGV. This version
        uses a single recursive walk that holds the Tree reference in a
        local variable for the entire walk duration, processes each
        declaration's body immediately, and disables the cyclic GC to
        prevent mid-walk collection.

        Issue #163: the previous MAX_SAFE_JS_LINES=100 threshold was
        removed because it silently skipped the most complex (and
        therefore most analysis-worthy) files in real codebases — e.g.
        ``scripts/regret.js`` at 2,731 lines was invisible to
        ``complexity``. The actual root-cause fix for the issue #116
        segfault is the single-pass walk + ``gc.disable()`` + holding
        the Tree reference via ``self.parse_tree()`` (all in place).

        Files above ``ABSOLUTE_HARD_LIMIT_LINES`` (10,000) are still
        skipped — they are almost always minified/generated code. The
        skip is now explicit: the file appears in the ``skipped[]`` list
        with reason ``file_too_large`` so the caller knows coverage is
        incomplete (issue #163 DoD: "silent skip replaced with explicit
        skipped[] list").
        """
        import gc as _gc
        import logging
        _log = logging.getLogger("codelens")

        ABSOLUTE_HARD_LIMIT_LINES = 10_000
        line_count = content.count('\n') + 1
        if line_count > ABSOLUTE_HARD_LIMIT_LINES:
            _log.warning(
                "Skipping extremely large JS file %s (%d lines > %d hard limit). "
                "Use .codelensignore to exclude if this is minified code. "
                "File recorded in skipped[] list (issue #163).",
                file_path, line_count, ABSOLUTE_HARD_LIMIT_LINES,
            )
            return {
                "nodes": [],
                "edges": [],
                "skipped": [{
                    "file": file_path,
                    "reason": "file_too_large",
                    "lines": line_count,
                }],
            }

        _gc_was_enabled = _gc.isenabled()
        if _gc_was_enabled:
            _gc.disable()
        try:
            source = content.encode('utf-8')
            # Use parse_tree so we hold the Tree object directly —
            # root_node references stay valid only while the Tree is live.
            tree_obj = self.parse_tree(source)
            root = tree_obj.root_node

            nodes: List[Dict] = []
            edges: List[Dict] = []

            MAX_DEPTH = 200

            # Issue #116/#163: iterative DFS walk. The previous recursive
            # form held Node references in Python frames across function
            # boundaries; combined with tree-sitter 0.26's binding this
            # caused SIGSEGV on large JS files with deeply-nested callback
            # chains. The iterative form holds an explicit (node, depth)
            # stack — Node references never cross a Python function call
            # boundary, which avoids the binding's GC invalidation bug.
            # ``keep_alive`` pins every Node we visit for the duration of
            # the walk so reference counting can't free them mid-walk.
            keep_alive: List[Node] = [root]
            stack: List[Tuple[Node, int]] = [(root, 0)]
            while stack:
                node, depth = stack.pop()
                if depth > MAX_DEPTH:
                    continue

                # Detect export_statement wrapper and mark exported
                if node.type == 'export_statement':
                    for child in node.children:
                        keep_alive.append(child)
                        if child.type in ('function_declaration', 'generator_function_declaration'):
                            self._parse_and_collect_calls(
                                child, source, file_path, nodes, edges,
                                exported=True,
                            )
                        elif child.type == 'class_declaration':
                            self._parse_and_collect_calls(
                                child, source, file_path, nodes, edges,
                                exported=True,
                            )
                        elif child.type == 'lexical_declaration':
                            for subchild in child.children:
                                keep_alive.append(subchild)
                                if subchild.type == 'variable_declarator':
                                    self._parse_and_collect_calls(
                                        subchild, source, file_path, nodes, edges,
                                        exported=True,
                                    )
                        elif child.type == 'default_export_clause':
                            for subchild in node.children:
                                keep_alive.append(subchild)
                                if subchild.type == 'class_declaration':
                                    self._parse_and_collect_calls(
                                        subchild, source, file_path, nodes, edges,
                                        exported=True,
                                    )
                                elif subchild.type in ('function_declaration', 'generator_function_declaration'):
                                    self._parse_and_collect_calls(
                                        subchild, source, file_path, nodes, edges,
                                        exported=True,
                                    )
                    continue  # Don't double-count by recursing inside export_statement

                if node.type == 'function_declaration' or node.type == 'generator_function_declaration':
                    self._parse_and_collect_calls(
                        node, source, file_path, nodes, edges,
                    )

                elif node.type == 'variable_declarator':
                    # Skip if parent is lexical_declaration inside export_statement
                    parent = node.parent
                    if parent and parent.type == 'lexical_declaration':
                        grandparent = parent.parent
                        if grandparent and grandparent.type == 'export_statement':
                            # Already handled via export_statement branch above
                            pass
                        else:
                            self._parse_and_collect_calls(
                                node, source, file_path, nodes, edges,
                            )
                    else:
                        self._parse_and_collect_calls(
                            node, source, file_path, nodes, edges,
                        )

                elif node.type == 'class_declaration':
                    self._parse_and_collect_calls(
                        node, source, file_path, nodes, edges,
                    )

                # Push children in reverse so they pop in source order
                if depth + 1 <= MAX_DEPTH:
                    children = node.children
                    for child in reversed(children):
                        keep_alive.append(child)
                        stack.append((child, depth + 1))

            return {"nodes": nodes, "edges": edges, "skipped": []}
        finally:
            if _gc_was_enabled:
                _gc.enable()

    def _parse_and_collect_calls(
        self,
        decl_node: Node,
        source: bytes,
        file_path: str,
        nodes: List[Dict],
        edges: List[Dict],
        exported: bool = False,
    ) -> Optional[Dict]:
        """Parse a declaration node and immediately collect call edges
        from its body.

        Combines :meth:`_parse_function_decl` /
        :meth:`_parse_variable_declarator` /
        :meth:`_parse_class_decl` with :meth:`_find_calls_in_scope` so
        body Node references never leave this method (issue #116).
        """
        if decl_node.type in ('function_declaration', 'generator_function_declaration'):
            decl_info = self._parse_function_decl(decl_node, source, file_path)
        elif decl_node.type == 'variable_declarator':
            decl_info = self._parse_variable_declarator(decl_node, source, file_path)
        elif decl_node.type == 'class_declaration':
            decl_info = self._parse_class_decl(decl_node, source, file_path)
        else:
            return None

        if not decl_info:
            return None

        if exported:
            decl_info["node"]["exported"] = True

        nodes.append(decl_info["node"])

        # Immediately collect calls from the body — body_node is still
        # valid here because we're inside the same recursive walk frame
        # and the Tree is held in the outer extract_references scope.
        body_node = decl_info.get("body_node")
        if body_node is not None:
            fn_calls = self._find_calls_in_scope(body_node, source, file_path)
            for call_info in fn_calls:
                edge = {
                    "from": decl_info["node"]["id"],
                    "to_fn": call_info["fn_name"],
                    "via_self": call_info.get("via_self", False)
                }
                if call_info.get("is_ipc_call"):
                    edge["is_ipc_call"] = True
                edges.append(edge)

        # Don't return body_node — let it be GC'd
        decl_info.pop("body_node", None)
        return decl_info

    def _find_function_declarations(self, root: Node, source: bytes,
                                     file_path: str) -> List[Dict]:
        """Find all function declarations in the AST."""
        declarations = []

        def visit(node: Node, _, depth):
            decl_info = None

            # Detect export_statement wrapper and mark exported
            if node.type == 'export_statement':
                for child in node.children:
                    if child.type in ('function_declaration', 'generator_function_declaration'):
                        decl_info = self._parse_function_decl(child, source, file_path)
                        if decl_info:
                            decl_info["node"]["exported"] = True
                    elif child.type == 'class_declaration':
                        decl_info = self._parse_class_decl(child, source, file_path)
                        if decl_info:
                            decl_info["node"]["exported"] = True
                    elif child.type == 'lexical_declaration':
                        # export const foo = () => {}
                        for subchild in child.children:
                            if subchild.type == 'variable_declarator':
                                decl_info = self._parse_variable_declarator(subchild, source, file_path)
                                if decl_info:
                                    decl_info["node"]["exported"] = True
                    elif child.type == 'default_export_clause':
                        # export default class Name / export default function name
                        for subchild in child.children:
                            if subchild.type == 'class_declaration':
                                decl_info = self._parse_class_decl(subchild, source, file_path)
                                if decl_info:
                                    decl_info["node"]["exported"] = True
                            elif subchild.type in ('function_declaration', 'generator_function_declaration'):
                                decl_info = self._parse_function_decl(subchild, source, file_path)
                                if decl_info:
                                    decl_info["node"]["exported"] = True
                if decl_info:
                    declarations.append(decl_info)
                return False  # Don't double-count by continuing walk inside export_statement

            if node.type == 'function_declaration' or node.type == 'generator_function_declaration':
                decl_info = self._parse_function_decl(node, source, file_path)

            elif node.type == 'variable_declarator':
                # Only process if parent is NOT an export_statement (to avoid double-counting)
                if node.parent and node.parent.type == 'lexical_declaration':
                    if node.parent.parent and node.parent.parent.type == 'export_statement':
                        return True  # Already handled above
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

        # Determine if it's a meaningful class (PascalCase) or React component.
        # Any PascalCase class is marked as component to prevent false dead-code
        # marking for domain classes like AxiosError, EventEmitter, CustomError.
        # React-specific: extends Component or React.
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

    def _find_calls_in_scope(self, body_node: Optional[Node], source: bytes,
                              file_path: str) -> List[Dict]:
        """Find all function calls within a function body.

        Issue #116/#163: iterative DFS walk. The previous recursive form
        caused SIGSEGV on large JS files with deeply-nested callback
        chains — the tree-sitter 0.26 binding invalidates Node pointers
        when Python frames holding them are entered/exited repeatedly.
        The iterative form holds an explicit (node, depth) stack and a
        ``keep_alive`` list that pins every visited Node for the
        duration of the walk so reference counting can't free them
        mid-walk. Symmetric with the iterative walk used in
        :meth:`extract_references`.
        """
        if not body_node:
            return []

        calls: List[Dict] = []
        MAX_DEPTH = 200

        keep_alive: List[Node] = [body_node]
        stack: List[Tuple[Node, int]] = [(body_node, 0)]
        while stack:
            node, depth = stack.pop()
            if depth > MAX_DEPTH:
                continue
            if node.type == 'call_expression':
                call_info = self._parse_call(node, source)
                if call_info:
                    calls.append(call_info)
            elif node.type == 'new_expression':
                call_info = self._parse_new_expression(node, source)
                if call_info:
                    calls.append(call_info)
            if depth + 1 <= MAX_DEPTH:
                children = node.children
                for child in reversed(children):
                    keep_alive.append(child)
                    stack.append((child, depth + 1))

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

        constructor_text = self.get_text(constructor_node, source)

        # Direct class instantiation: new ClassName()
        if constructor_node.type == 'identifier':
            name = constructor_text
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
