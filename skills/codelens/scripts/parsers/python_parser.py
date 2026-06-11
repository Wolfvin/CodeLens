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


# Shared Python skip names — common builtins that are not user-defined functions
PYTHON_SKIP_NAMES = {
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


class PythonParser(BaseParser if HAS_TREE_SITTER else object):
    """Tree-sitter powered Python parser for function/class extraction.

    Extends BaseParser to use shared utilities like get_text() and get_line()
    for consistent AST traversal across all parsers.
    """

    def __init__(self):
        if not HAS_TREE_SITTER:
            raise ImportError("tree-sitter or base_parser not available")
        from grammar_loader import get_grammar_loader
        loader = get_grammar_loader()
        language = loader.get_language('python')
        if language is None:
            raise ImportError("tree-sitter Python grammar not available")
        super().__init__(language)

    def extract_references(self, content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Extract function declarations and calls from Python content.

        Returns:
            {
                "nodes": [{"id": str, "fn": str, "file": str, "line": int, "async": bool, "impl_for": str|None}],
                "edges": [{"from": str, "to_fn": str}]
            }
        """
        root = self.parse(content.encode('utf-8'))
        nodes = []
        edges = []

        # Track declared functions and current class
        declared_fns: Dict[str, str] = {}  # fn_name → node_id
        current_class: Optional[str] = None
        current_fn_id: Optional[str] = None

        source = content.encode('utf-8')

        def _walk(node, class_name=None, fn_id=None):
            """Recursively walk the tree to find functions and calls."""
            nonlocal current_class, current_fn_id

            if node.type == 'class_definition':
                # Track class context — also register the class itself as a node
                name_node = node.child_by_field_name('name')
                if name_node:
                    cls_name = self.get_text(name_node, source)
                    line = self.get_line(node)

                    # Register class as a node so query/context can find it
                    class_id = f"{file_path}:{line}"
                    # Extract superclass info if present
                    superclasses_node = node.child_by_field_name('superclasses')
                    superclass_names = []
                    if superclasses_node:
                        for child in superclasses_node.children:
                            if child.type == 'identifier':
                                superclass_names.append(self.get_text(child, source))
                            elif child.type == 'attribute':
                                attr = child.child_by_field_name('attribute')
                                if attr:
                                    superclass_names.append(self.get_text(attr, source))

                    class_node = {
                        "id": class_id,
                        "fn": cls_name,
                        "file": file_path,
                        "line": line,
                        "async": False,
                        "type": "class",
                    }
                    if superclass_names:
                        class_node["superclasses"] = superclass_names

                    nodes.append(class_node)
                    declared_fns[cls_name] = class_id

                    # Walk the body with class context
                    body = node.child_by_field_name('body')
                    if body:
                        for child in body.children:
                            _walk(child, class_name=cls_name, fn_id=fn_id)
                return

            elif node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    fn_name = self.get_text(name_node, source)
                    line = self.get_line(node)

                    # Check async
                    is_async = any(
                        child.type == 'async' or (child.type == 'identifier' and child.text == b'async')
                        for child in node.children
                    )

                    node_id = f"{file_path}:{line}"
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
                    call_name = self.get_text(func_node, source)

                    # Handle attribute access: obj.method
                    if func_node.type == 'attribute':
                        attr_node = func_node.child_by_field_name('attribute')
                        obj_node = func_node.child_by_field_name('object')
                        if attr_node and obj_node:
                            method_name = self.get_text(attr_node, source)
                            obj_name = self.get_text(obj_node, source)
                            if method_name not in PYTHON_SKIP_NAMES:
                                is_self = obj_name == 'self'
                                edges.append({
                                    "from": fn_id,
                                    "to_fn": method_name,
                                    "via_self": is_self
                                })
                    elif func_node.type == 'identifier':
                        if call_name not in PYTHON_SKIP_NAMES:
                            edges.append({
                                "from": fn_id,
                                "to_fn": call_name
                            })

            # Recurse into children
            for child in node.children:
                _walk(child, class_name=class_name, fn_id=fn_id)

        for child in root.children:
            _walk(child)

        return {"nodes": nodes, "edges": edges}
