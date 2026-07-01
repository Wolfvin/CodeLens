"""
Base Parser for CodeLens — Tree-sitter powered
Provides shared utilities for all AST-based parsers.
"""

from typing import Dict, List, Any, Optional, Tuple
from tree_sitter import Language, Parser, Node


# ─── Shared Skip Name Sets ─────────────────────────────────────
# Common identifiers that are NOT user-defined functions and should be
# skipped when building call-graph edges.  Each parser can extend these
# with language-specific entries.

# JavaScript/TypeScript keywords + builtins shared by all JS-family parsers
JS_TS_SKIP_NAMES_BASE = frozenset({
    'if', 'else', 'for', 'while', 'switch', 'catch', 'return', 'throw',
    'const', 'let', 'var', 'function', 'class', 'new', 'typeof', 'instanceof',
    'async', 'await', 'yield', 'import', 'export', 'from', 'default',
    'try', 'finally', 'break', 'continue', 'do', 'in', 'of',
    'true', 'false', 'null', 'undefined', 'void', 'delete',
    'console', 'require', 'module', 'exports',
    'String', 'Number', 'Boolean', 'Array', 'Object', 'Promise', 'Error',
})

# Node.js / backend-specific builtins (shared by js_backend & ts_backend)
JS_TS_BACKEND_SKIP_NAMES_EXTRA = frozenset({
    'process', 'global',
    'Map', 'Set',
    'TypeError', 'RangeError', 'SyntaxError',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURIComponent',
    'decodeURIComponent', 'encodeURI', 'decodeURI',
    'JSON', 'Date', 'RegExp', 'Math', 'Buffer', 'setTimeout', 'setInterval',
    'clearTimeout', 'clearInterval', 'setImmediate', 'clearImmediate',
    'addEventListener', 'removeEventListener',
})

# React / frontend-specific builtins (used by tsx_parser)
JS_TSX_SKIP_NAMES_EXTRA = frozenset({
    'React', 'useState', 'useEffect',
    'useRef', 'useCallback', 'useMemo', 'useContext', 'useReducer',
})

# Python builtins — common identifiers that are NOT user-defined functions
PYTHON_SKIP_NAMES = frozenset({
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
})

# Rust keywords + builtins — common identifiers that are NOT user-defined functions
RUST_SKIP_NAMES = frozenset({
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
})

# Go keywords + builtins
GO_SKIP_NAMES = frozenset({
    'if', 'else', 'for', 'switch', 'case', 'default', 'return', 'break', 'continue',
    'func', 'var', 'const', 'type', 'struct', 'interface', 'map', 'chan', 'go',
    'defer', 'range', 'select', 'fallthrough', 'goto', 'package', 'import',
    'true', 'false', 'nil', 'iota',
    'len', 'cap', 'make', 'new', 'append', 'copy', 'delete', 'close',
    'panic', 'recover', 'print', 'println',
    'error', 'string', 'int', 'int8', 'int16', 'int32', 'int64',
    'uint', 'uint8', 'uint16', 'uint32', 'uint64',
    'float32', 'float64', 'complex64', 'complex128',
    'bool', 'byte', 'rune', 'uintptr',
    'fmt', 'http', 'json', 'os', 'io', 'strings', 'strconv',
})


class BaseParser:
    """Base class for all tree-sitter based parsers."""

    def __init__(self, language: Language):
        self.language = language
        self.parser = Parser(language)
        # Keep a reference to the most recent Tree so it is not garbage-
        # collected while callers still hold Node references into it.
        # Tree-sitter nodes point into memory owned by the Tree; if Python
        # frees the Tree the node pointers dangle and accessing
        # ``node.children`` / ``node.start_point`` raises SIGSEGV (issue #116).
        self._last_tree = None

    def parse(self, content: bytes) -> Node:
        """Parse source content and return root node.

        Keeps a reference to the underlying Tree on ``self._last_tree`` so
        the returned root node (and any descendants obtained via
        ``node.children`` / ``child_by_field_name``) remains valid until
        the next call to :meth:`parse`. Callers that need to hold nodes
        across multiple parses must keep their own reference to the Tree
        (returned via :meth:`parse_tree`).
        """
        tree = self.parser.parse(content)
        self._last_tree = tree
        return tree.root_node

    def parse_tree(self, content: bytes):
        """Parse source content and return the Tree object.

        Use this when you need to keep nodes alive across multiple parses
        — hold the returned Tree for as long as you hold any Node into it.
        """
        tree = self.parser.parse(content)
        self._last_tree = tree
        return tree

    @staticmethod
    def get_text(node: Node, source: bytes) -> str:
        """Get the text content of a node."""
        return source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')

    @staticmethod
    def get_line(node: Node) -> int:
        """Get 1-based line number of a node."""
        return node.start_point.row + 1

    def walk_tree(self, node: Node, source: bytes, callback, depth=0, max_depth=50):
        """
        Walk the entire AST tree, calling callback for each node.
        Callback signature: callback(node, source, depth) -> bool (True to continue, False to skip children)

        Implemented iteratively (issue #116) — the previous recursive form
        crashed with SIGSEGV on deeply-nested JS callbacks because Python's
        garbage collector could free the parent Tree while child nodes
        were still being visited. The iterative form keeps an explicit
        stack of (node, depth) tuples and never recurses into Python.

        We also disable the cyclic garbage collector for the duration of
        the walk. tree-sitter's Python binding owns node memory via the
        Tree object; if a GC pass runs mid-walk and collects a transient
        cycle that holds the Tree, the nodes on our stack dangle and the
        next ``node.children`` access raises SIGSEGV. Disabling gc here is
        safe — the walk is bounded by ``max_depth`` and the stack holds
        only ``(Node, int)`` tuples, so no unbounded growth is possible.
        """
        if depth > max_depth:
            return
        # Iterative DFS — (node, depth) tuples. We visit in the same
        # pre-order as the recursive version: callback first, then children
        # left-to-right.
        import gc as _gc
        _gc_was_enabled = _gc.isenabled()
        if _gc_was_enabled:
            _gc.disable()
        try:
            stack = [(node, depth)]
            while stack:
                cur, cur_depth = stack.pop()
                should_continue = callback(cur, source, cur_depth)
                if should_continue is False:
                    continue
                if cur_depth + 1 <= max_depth:
                    # Push children in reverse so they pop in source order.
                    children = cur.children
                    for child in reversed(children):
                        stack.append((child, cur_depth + 1))
        finally:
            if _gc_was_enabled:
                _gc.enable()

    def find_nodes_by_type(self, root: Node, node_type: str) -> List[Node]:
        """Find all nodes of a specific type in the tree."""
        results = []
        def visitor(node, source, depth):
            if node.type == node_type:
                results.append(node)
        self.walk_tree(root, b'', visitor)
        return results

    def find_nodes_by_types(self, root: Node, node_types: set) -> List[Node]:
        """Find all nodes matching any of the given types."""
        results = []
        def visitor(node, source, depth):
            if node.type in node_types:
                results.append(node)
        self.walk_tree(root, b'', visitor)
        return results

    def find_parent_of_type(self, node: Node, parent_type: str) -> Optional[Node]:
        """Walk up the tree to find a parent of a specific type."""
        current = node.parent
        while current:
            if current.type == parent_type:
                return current
            current = current.parent
        return None

    def is_inside_comment(self, node: Node) -> bool:
        """Check if a node is inside a comment."""
        current = node.parent
        while current:
            if current.type in ('comment', 'block_comment', 'html_comment', 'line_comment'):
                return True
            current = current.parent
        return False

    def is_inside_keyframes(self, node: Node) -> bool:
        """Check if a node is inside a @keyframes block (CSS-specific)."""
        current = node.parent
        while current:
            if current.type in ('keyframes_statement', 'at_rule'):
                return True
            current = current.parent
        return False

    def get_function_context(self, node: Node, source: bytes,
                              fn_decl_types: set) -> Optional[Tuple[str, int]]:
        """
        Find the nearest enclosing function declaration.
        Returns (function_name, line) or None.
        """
        current = node.parent
        while current:
            if current.type in fn_decl_types:
                # Find the function name
                for child in current.children:
                    if child.type in ('identifier', 'property_identifier', 'name'):
                        fn_name = self.get_text(child, source)
                        return (fn_name, self.get_line(current))
                # For variable declarators like: const fn = () => {}
                if current.type == 'variable_declarator':
                    for child in current.children:
                        if child.type == 'identifier':
                            fn_name = self.get_text(child, source)
                            return (fn_name, self.get_line(current))
            current = current.parent
        return None

    @staticmethod
    def get_string_value(node: Node, source: bytes) -> Optional[str]:
        """Extract the string value from a string node, removing quotes.

        Returns None for template literals (backtick strings) or non-literal
        strings, as they may contain dynamic expressions.

        This is the shared version of _get_string_value used by multiple parsers
        (tsx, js_frontend, etc.) to avoid duplication.
        """
        text = source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
        # Remove quotes
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            return text[1:-1]
        # Template literal — skip (dynamic)
        if text.startswith('`'):
            return None
        return None
