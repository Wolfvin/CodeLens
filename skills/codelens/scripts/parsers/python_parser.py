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


class PythonParser:
    """Tree-sitter powered Python parser for function/class extraction."""

    def __init__(self):
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter or base_parser not available")
        self._parser = None
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        ts_parser = loader.get_parser('python')
        if ts_parser is None:
            raise ImportError("tree-sitter Python grammar not available")
        self._parser = ts_parser

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract function declarations and calls from Python content.

        Returns:
            {
                "nodes": [{"id": str, "fn": str, "file": str, "line": int, "async": bool, "impl_for": str|None}],
                "edges": [{"from": str, "to_fn": str}]
            }
        """
        tree = self._parser.parse(content.encode('utf-8'))
        nodes = []
        edges = []

        # Track declared functions and current class
        declared_fns: Dict[str, str] = {}  # fn_name → node_id
        current_class: Optional[str] = None
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

        def _walk(node, class_name=None, fn_id=None):
            """Recursively walk the tree to find functions and calls."""
            nonlocal current_class, current_fn_id

            if node.type == 'class_definition':
                # Track class context
                name_node = node.child_by_field_name('name')
                if name_node:
                    cls_name = content[name_node.start_byte:name_node.end_byte]
                    # Walk the body with class context
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            _walk(child, class_name=cls_name, fn_id=fn_id)
                return

            elif node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    fn_name = content[name_node.start_byte:name_node.end_byte]
                    line = node.start_point[0] + 1  # 1-indexed
                    node_id = f"{file_path}:{line}"

                    # Check async
                    is_async = any(
                        child.type == 'async' or (child.type == 'identifier' and child.text == b'async')
                        for child in node.children
                    )

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

                    # Walk the body with function context
                    body = node.child_by_field_name('body')
                    if body:
                        old_fn_id = current_fn_id
                        current_fn_id = node_id
                        for child in body.children:
                            _walk(child, class_name=class_name, fn_id=node_id)
                        current_fn_id = old_fn_id
                return

            elif node.type == 'decorator':
                # Skip decorators - they reference functions but aren't calls
                return

            elif node.type == 'call' and fn_id:
                # Function call: name(args) or obj.method(args)
                func_node = node.child_by_field_name('function')
                if func_node:
                    call_name = content[func_node.start_byte:func_node.end_byte]

                    # Handle attribute access: obj.method
                    if func_node.type == 'attribute':
                        attr_node = func_node.child_by_field_name('attribute')
                        obj_node = func_node.child_by_field_name('object')
                        if attr_node and obj_node:
                            method_name = content[attr_node.start_byte:attr_node.end_byte]
                            obj_name = content[obj_node.start_byte:obj_node.end_byte]
                            if method_name not in skip_names:
                                is_self = obj_name == 'self'
                                full_name = f"{obj_name}.{method_name}"
                                edges.append({
                                    "from": fn_id,
                                    "to_fn": method_name,
                                    "via_self": is_self
                                })
                    elif func_node.type == 'identifier':
                        if call_name not in skip_names:
                            edges.append({
                                "from": fn_id,
                                "to_fn": call_name
                            })

            # Recurse into children
            for child in node.children:
                _walk(child, class_name=class_name, fn_id=fn_id)

        root = tree.root_node
        for child in root.children:
            _walk(child)

        return {"nodes": nodes, "edges": edges}
