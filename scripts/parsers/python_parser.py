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

from typing import Dict, List, Any, Optional, Tuple

try:
    from tree_sitter import Node
    from base_parser import BaseParser, PYTHON_SKIP_NAMES
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


# Use shared Python skip names from base_parser (single source of truth)
# Fallback for when base_parser is not available
if not HAS_TREE_SITTER:
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
                "edges": [{"from": str, "to_fn": str}],
                "skipped": [{"file": str, "reason": str, "lines": int}]  # empty list in normal operation
            }

        Issue #163: the previous MAX_SAFE_PY_LINES=200 threshold was removed
        because it silently skipped the most complex (and therefore most
        analysis-worthy) files in real codebases. The actual root-cause fix
        for the issue #116 segfault is:
          1. ``BaseParser.parse`` stores the Tree on ``self._last_tree``
             so Node references stay valid for the lifetime of the parser
             instance (already in place — see base_parser.py).
          2. ``gc.disable()`` is called for the duration of parse + walk
             to prevent cyclic GC from invalidating tree-sitter Node
             pointers mid-walk (already in place below).

        Files above ``ABSOLUTE_HARD_LIMIT_LINES`` (10,000) are still
        skipped — they are almost always generated/minified code, not
        human-written source. The skip is now explicit: the file appears
        in the ``skipped[]`` list with reason ``file_too_large`` so the
        caller knows coverage is incomplete (issue #163 DoD: "silent
        skip replaced with explicit skipped[] list").
        """
        import gc as _gc
        import logging
        _log = logging.getLogger("codelens")

        ABSOLUTE_HARD_LIMIT_LINES = 10_000
        line_count = content.count('\n') + 1
        if line_count > ABSOLUTE_HARD_LIMIT_LINES:
            _log.warning(
                "Skipping extremely large Python file %s (%d lines > %d hard limit). "
                "Use .codelensignore to exclude if this is generated code. "
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

        # Disable cyclic GC during parse + walk to prevent tree-sitter
        # node invalidation (issue #116). See base_parser.walk_tree for
        # the full rationale.
        _gc_was_enabled = _gc.isenabled()
        if _gc_was_enabled:
            _gc.disable()
        try:
            result = self._extract_references_impl(content, file_path)
        finally:
            if _gc_was_enabled:
                _gc.enable()
        # Forward-compat: always include skipped[] so callers can rely on
        # the field being present (issue #163).
        result.setdefault("skipped", [])
        return result

    def _extract_references_impl(self, content: str, file_path: str) -> Dict[str, List[Dict[str, Any]]]:
        """Implementation of :meth:`extract_references` — called with GC disabled."""
        # Issue #116/#163: use parse_tree and hold the Tree in a local
        # variable for the entire walk. tree-sitter 0.26's binding does
        # not make Node objects hold a strong reference to the Tree, so
        # the Tree must be pinned explicitly — otherwise its refcount
        # can drop to 0 mid-walk and Node pointers dangle.
        tree_obj = self.parse_tree(content.encode('utf-8'))
        root = tree_obj.root_node
        nodes = []
        edges = []

        # Track declared functions (informational — not used for walk control)
        declared_fns: Dict[str, str] = {}  # fn_name → node_id

        source = content.encode('utf-8')

        MAX_DEPTH = 200

        # Issue #116/#163: iterative DFS walk. The previous recursive form
        # caused SIGSEGV on deeply-nested Python files (depth ≥ ~100) —
        # the tree-sitter 0.26 binding invalidates Node pointers when
        # Python frames holding them are entered/exited repeatedly. The
        # iterative form holds an explicit (node, depth, class_name,
        # fn_id) stack — Node references never cross a Python function
        # call boundary, which avoids the binding's GC invalidation bug.
        # ``keep_alive`` pins every Node we visit for the duration of the
        # walk so reference counting can't free them mid-walk. Symmetric
        # with the iterative walk used in JSBackendParser.
        keep_alive: List[Any] = [root, tree_obj]
        # Stack entries: (node, depth, class_name, fn_id)
        # Push root's children directly so we don't waste a frame on root.
        root_children = root.children
        stack: List[Tuple[Any, int, Optional[str], Optional[str]]] = [
            (child, 0, None, None) for child in reversed(root_children)
        ]
        for child in root_children:
            keep_alive.append(child)

        while stack:
            node, depth, class_name, fn_id = stack.pop()
            if depth > MAX_DEPTH:
                continue

            if node.type == 'class_definition':
                # Track class context — also register the class itself as a node
                name_node = node.child_by_field_name('name')
                if name_node:
                    keep_alive.append(name_node)
                    cls_name = self.get_text(name_node, source)
                    line = self.get_line(node)

                    # Register class as a node so query/context can find it
                    class_id = f"{file_path}:{line}"
                    # Extract superclass info if present
                    superclasses_node = node.child_by_field_name('superclasses')
                    superclass_names = []
                    if superclasses_node:
                        keep_alive.append(superclasses_node)
                        for child in superclasses_node.children:
                            keep_alive.append(child)
                            if child.type == 'identifier':
                                superclass_names.append(self.get_text(child, source))
                            elif child.type == 'attribute':
                                attr = child.child_by_field_name('attribute')
                                if attr:
                                    keep_alive.append(attr)
                                    superclass_names.append(self.get_text(attr, source))

                    class_node_data = {
                        "id": class_id,
                        "fn": cls_name,
                        "file": file_path,
                        "line": line,
                        "async": False,
                        "type": "class",
                    }
                    if superclass_names:
                        class_node_data["superclasses"] = superclass_names

                    nodes.append(class_node_data)
                    declared_fns[cls_name] = class_id

                    # Walk the body with class context — push children
                    # with the new class_name.
                    body = node.child_by_field_name('body')
                    if body:
                        keep_alive.append(body)
                        for child in reversed(body.children):
                            keep_alive.append(child)
                            stack.append((child, depth + 1, cls_name, fn_id))
                continue

            elif node.type == 'function_definition':
                name_node = node.child_by_field_name('name')
                if name_node:
                    keep_alive.append(name_node)
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

                    # Walk the body with function context — push children
                    # with the new fn_id.
                    body = node.child_by_field_name('body')
                    if body:
                        keep_alive.append(body)
                        for child in reversed(body.children):
                            keep_alive.append(child)
                            stack.append((child, depth + 1, class_name, node_id))
                continue

            elif node.type == 'decorator':
                # Skip decorators - they reference functions but aren't calls
                continue

            elif node.type == 'call' and fn_id:
                # Function call: name(args) or obj.method(args)
                func_node = node.child_by_field_name('function')
                if func_node:
                    keep_alive.append(func_node)
                    call_name = self.get_text(func_node, source)

                    # Handle attribute access: obj.method
                    if func_node.type == 'attribute':
                        attr_node = func_node.child_by_field_name('attribute')
                        obj_node = func_node.child_by_field_name('object')
                        if attr_node and obj_node:
                            keep_alive.append(attr_node)
                            keep_alive.append(obj_node)
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

            # Recurse into children with same context
            if depth + 1 <= MAX_DEPTH:
                children = node.children
                for child in reversed(children):
                    keep_alive.append(child)
                    stack.append((child, depth + 1, class_name, fn_id))

        return {"nodes": nodes, "edges": edges}
