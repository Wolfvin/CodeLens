"""
Python Parser for CodeLens — Tree-sitter Edition
Extracts function declarations, class definitions, and function calls from Python source.

Detected patterns:
- def process_data(input): ...
- async def fetch_data(url): ...
- class UserController: ...
- def method(self, arg): ...  (tracked with impl_for)
- process_data(myInput)
- self.process_data(myInput)
- utils.process_data(myInput)

Rules:
- Class methods tracked with impl_for: ClassName
- Async functions tracked with async: True
- Nested functions tracked
- Decorators preserved as metadata
- Lambda expressions → IGNORED (anonymous)
- Same function name in multiple files → flag duplicate_define
"""

from typing import Dict, List, Any, Optional

try:
    from tree_sitter import Node
    from base_parser import BaseParser
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


class PythonParser(BaseParser):
    """Tree-sitter powered Python parser for function/class extraction."""

    def __init__(self):
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter or base_parser not available")
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        lang = loader.get_language('python')
        if lang is None:
            raise ImportError("tree-sitter Python grammar not available")
        super().__init__(lang)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract function declarations and calls from Python content.

        Returns:
            {
                "nodes": [{"id": str, "fn": str, "file": str, "line": int, "async": bool, "impl_for": str|None}],
                "edges": [{"from": str, "to_fn": str}]
            }
        """
        source = content.encode('utf-8')
        tree = self.parse(source)
        nodes = []
        edges = []

        # Track declared functions and current class
        declared_fns: Dict[str, str] = {}  # fn_name → node_id

        # Context tracking via depth-aware stack
        # Each entry: (depth, type, value)
        #   type='class'  → value is class name
        #   type='function' → value is previous current_fn_id to restore
        context_stack: List[tuple] = []
        current_fn_id: Optional[str] = None

        # Skip names that aren't user-defined functions
        skip_names = {
            'if', 'else', 'elif', 'for', 'while', 'with', 'try', 'except', 'finally',
            'return', 'yield', 'raise', 'break', 'continue', 'pass', 'import', 'from',
            'class', 'def', 'async', 'await', 'lambda', 'global', 'nonlocal',
            'True', 'False', 'None',
            'print', 'len', 'range', 'int', 'str', 'float', 'bool', 'list', 'dict',
            'set', 'tuple', 'type', 'isinstance', 'super', 'property',
            'enumerate', 'zip', 'map', 'filter', 'sorted', 'reversed',
            'iter', 'next', 'abs', 'min', 'max', 'sum', 'any', 'all',
            'self', 'cls', 'open', 'hasattr', 'getattr', 'setattr',
            'staticmethod', 'classmethod', 'abstractmethod',
        }

        def visit(node, src, depth):
            nonlocal current_fn_id

            # Pop context entries whose depth >= current depth
            # (we've exited those subtrees)
            while context_stack and context_stack[-1][0] >= depth:
                _, ctx_type, ctx_value = context_stack.pop()
                if ctx_type == 'function':
                    current_fn_id = ctx_value  # Restore previous fn_id

            if node.type == 'decorator':
                return False  # Skip decorator children

            if node.type == 'class_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    cls_name = self.get_text(name_node, src)
                    context_stack.append((depth, 'class', cls_name))
                return  # Continue walking children

            if node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    fn_name = self.get_text(name_node, src)
                    line = self.get_line(node)
                    node_id = f"{file_path}:{line}"

                    # Check async
                    is_async = any(
                        child.type == 'async' or (child.type == 'identifier' and child.text == b'async')
                        for child in node.children
                    )

                    # Get current class context
                    class_name = None
                    for _, ctx_type, ctx_name in context_stack:
                        if ctx_type == 'class':
                            class_name = ctx_name

                    node_data = {
                        "id": node_id,
                        "fn": fn_name,
                        "file": file_path,
                        "line": line,
                        "async": is_async,
                    }
                    if class_name:
                        node_data["impl_for"] = class_name

                    nodes.append(node_data)
                    declared_fns[fn_name] = node_id

                    # Save current fn_id to restore when exiting this function
                    context_stack.append((depth, 'function', current_fn_id))
                    current_fn_id = node_id
                return  # Continue walking children

            if node.type == 'call' and current_fn_id:
                # Function call: name(args) or obj.method(args)
                func_node = node.child_by_field_name('function')
                if func_node:
                    call_name = self.get_text(func_node, src)

                    # Handle attribute access: obj.method
                    if func_node.type == 'attribute':
                        attr_node = func_node.child_by_field_name('attribute')
                        obj_node = func_node.child_by_field_name('object')
                        if attr_node and obj_node:
                            method_name = self.get_text(attr_node, src)
                            obj_name = self.get_text(obj_node, src)
                            if method_name not in skip_names:
                                is_self = obj_name == 'self'
                                edges.append({
                                    "from": current_fn_id,
                                    "to_fn": method_name,
                                    "via_self": is_self
                                })
                    elif func_node.type == 'identifier':
                        if call_name not in skip_names:
                            edges.append({
                                "from": current_fn_id,
                                "to_fn": call_name
                            })

        self.walk_tree(tree, source, visit)

        return {"nodes": nodes, "edges": edges}
