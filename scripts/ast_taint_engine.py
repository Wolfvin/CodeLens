"""
AST-based Taint Analysis Engine for CodeLens — v1

Real AST-level taint analysis using tree-sitter. Builds a Control Flow Graph (CFG),
performs path-sensitive forward taint propagation, and tracks source→sink data flow
with full taint path rendering.

Key Improvements over semantic_engine.py (regex-based):
1. AST-level traversal — no regex false positives from string matching
2. Real CFG with basic blocks, branches, and joins
3. Path-sensitive — tracks different taint states on if/else branches
4. Scope-aware — understands function boundaries, closures, class methods
5. Inter-procedural — tracks taint through function calls within a file
6. Sanitizer-aware — recognizes when taint is removed by sanitizers
7. Full taint path rendering — e.g., "request.args → user_input → query → cursor.execute"

Architecture:
  Phase 1: Parse file with tree-sitter → AST
  Phase 2: Build CFG from AST (basic blocks with branches)
  Phase 3: Identify taint sources (from YAML rules + built-in patterns)
  Phase 4: Forward taint propagation through CFG
  Phase 5: Check taint arrival at sinks
  Phase 6: Generate findings with taint paths and confidence

Confidence Scoring:
  0.95+ Direct source→sink, no sanitizer, same scope
  0.80+ Source→sink through function call, no sanitizer
  0.60+ Source→sink with partial sanitizer
  0.40+ Indirect taint, may be sanitized
"""

import os
import re
import time
import yaml
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from dataclasses import dataclass, field

from utils import logger, safe_read_file, DEFAULT_IGNORE_DIRS, should_ignore_dir

# ─── Tree-sitter Integration ─────────────────────────────────

try:
    from tree_sitter import Language, Parser, Node
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    Language = None
    Parser = None
    Node = None

# Lazy grammar loading
_parser_cache: Dict[str, Any] = {}


def _get_parser(lang_name: str):
    """Get a cached tree-sitter parser for a language."""
    if not TREE_SITTER_AVAILABLE:
        return None
    if lang_name in _parser_cache:
        return _parser_cache[lang_name]

    try:
        from grammar_loader import GrammarLoader
        loader = GrammarLoader()
        p = loader.get_parser(lang_name)
        if p:
            _parser_cache[lang_name] = p
            return p
    except Exception:
        pass

    # Direct load fallback
    try:
        lang_map = {
            'python': 'tree_sitter_python',
            'javascript': 'tree_sitter_javascript',
            'typescript': 'tree_sitter_typescript',
            'tsx': 'tree_sitter_typescript',
        }
        mod_name = lang_map.get(lang_name)
        if not mod_name:
            return None
        mod = __import__(mod_name)
        lang = Language(mod.language())

        # TSX/TypeScript use different language functions
        if lang_name == 'tsx':
            lang = Language(mod.language_tsx())
        elif lang_name == 'typescript':
            lang = Language(mod.language_typescript())

        parser = Parser()
        parser.language = lang
        _parser_cache[lang_name] = parser
        return parser
    except Exception:
        return None


# ─── Data Structures ─────────────────────────────────────────

@dataclass
class TaintInfo:
    """Tracks taint origin for a variable."""
    var_name: str
    sources: Set[str] = field(default_factory=set)  # set of source names (e.g., "request.args")
    path: List[str] = field(default_factory=list)    # taint path for rendering
    sanitized_by: Set[str] = field(default_factory=set)  # set of sanitizer names
    is_sanitized: bool = False

    def copy(self) -> 'TaintInfo':
        return TaintInfo(
            var_name=self.var_name,
            sources=set(self.sources),
            path=list(self.path),
            sanitized_by=set(self.sanitized_by),
            is_sanitized=self.is_sanitized,
        )


@dataclass
class TaintState:
    """Tracks which variables are tainted at each CFG node.

    Maps variable names to their taint information, including
    which sources tainted them and whether they've been sanitized.

    Improvement 2 — Scope-hierarchical taint tracking:
    Each TaintState has a `scope` (e.g., 'module', 'function:foo') and an
    optional `_parent` pointing to the enclosing scope's TaintState.  Variable
    lookups walk the parent chain so that variables from outer scopes are
    visible in inner scopes, but taint added in an inner scope does not leak
    upward.  This prevents cross-scope contamination where variable `x` in
    function A and variable `x` in function B interfere.
    """
    tainted: Dict[str, TaintInfo] = field(default_factory=dict)
    # ── Scope hierarchy (Improvement 2) ──
    scope: str = "module"                     # e.g. "module", "function:foo"
    _parent: Optional['TaintState'] = field(default=None, repr=False)

    # ── Scope-aware helpers ────────────────────────────────────

    def _lookup(self, var_name: str) -> Optional[TaintInfo]:
        """Walk the scope chain to find taint info for *var_name*.

        Current scope is checked first; if not found the parent scope
        is consulted, and so on.  This implements genuine lexical scoping
        so that closures and nested functions can see outer taint without
        cross-scope contamination.
        """
        info = self.tainted.get(var_name)
        if info is not None:
            return info
        if self._parent is not None:
            return self._parent._lookup(var_name)
        return None

    def child_scope(self, scope_name: str) -> 'TaintState':
        """Create a child TaintState that inherits from this one.

        The child starts with an empty `tainted` dict so that writes go
        only to the child scope.  Reads fall through to the parent when
        the variable is not found locally — exactly like lexical scoping.
        """
        child = TaintState(scope=scope_name, _parent=self)
        return child

    # ── Core operations (backward-compatible) ──────────────────

    def copy(self) -> 'TaintState':
        new = TaintState(scope=self.scope, _parent=self._parent)
        for var, info in self.tainted.items():
            new.tainted[var] = info.copy()
        return new

    def merge(self, other: 'TaintState') -> 'TaintState':
        """Join two states (union of taints) for CFG join points.

        Only variables in the *same* scope level are merged.  Parent
        scopes are shared (not deep-merged) which prevents a variable
        that exists only in an outer scope from being accidentally
        polluted at the join.
        """
        result = self.copy()
        for var, info in other.tainted.items():
            if var in result.tainted:
                # Union of sources
                result.tainted[var].sources |= info.sources
                # Merge paths (keep longer one)
                if len(info.path) > len(result.tainted[var].path):
                    result.tainted[var].path = list(info.path)
                # If either is unsanitized, the merge is unsanitized
                if not info.is_sanitized:
                    result.tainted[var].is_sanitized = False
                result.tainted[var].sanitized_by &= info.sanitized_by
            else:
                result.tainted[var] = info.copy()
        return result

    def is_tainted(self, var_name: str) -> bool:
        """Check if a variable is tainted (and not fully sanitized).

        Scope-aware: walks the parent chain if the variable is not
        defined in the current scope.
        """
        info = self._lookup(var_name)
        return info is not None and not info.is_sanitized

    def get_taint_info(self, var_name: str) -> Optional[TaintInfo]:
        """Scope-aware lookup — checks current scope, then parent chain."""
        return self._lookup(var_name)

    def add_taint(self, var_name: str, source: str, path_step: str,
                  sanitized_by: Set[str] = None):
        """Mark a variable as tainted from a source.

        Writes to the *current* scope only, never to a parent scope.
        This prevents inner scopes from polluting outer scopes.
        """
        existing = self.tainted.get(var_name)
        if existing:
            existing.sources.add(source)
            if path_step not in existing.path:
                existing.path.append(path_step)
            if sanitized_by:
                existing.sanitized_by |= sanitized_by
                existing.is_sanitized = bool(existing.sanitized_by)
        else:
            self.tainted[var_name] = TaintInfo(
                var_name=var_name,
                sources={source},
                path=[source, path_step],
                sanitized_by=sanitized_by or set(),
                is_sanitized=bool(sanitized_by),
            )

    def remove_taint(self, var_name: str, sanitizer: str):
        """Mark a variable as sanitized.

        If the variable exists in the current scope, sanitize it there.
        Otherwise, look it up in the parent chain and re-add a sanitized
        copy in the current scope (shadowing the parent entry).
        """
        info = self.tainted.get(var_name)
        if info:
            info.sanitized_by.add(sanitizer)
            info.is_sanitized = True
        else:
            # Variable inherited from parent scope — shadow it locally
            parent_info = self._lookup(var_name)
            if parent_info:
                local_copy = parent_info.copy()
                local_copy.sanitized_by.add(sanitizer)
                local_copy.is_sanitized = True
                self.tainted[var_name] = local_copy

    def propagate(self, src_var: str, dst_var: str):
        """Propagate taint from src_var to dst_var (assignment).

        Source is resolved via scope chain; destination is written to
        the current scope only.
        """
        src_info = self._lookup(src_var)
        if src_info:
            new_info = src_info.copy()
            new_info.var_name = dst_var
            new_info.path = list(src_info.path) + [dst_var]
            self.tainted[dst_var] = new_info


@dataclass
class BasicBlock:
    """A basic block in the Control Flow Graph."""
    id: int
    statements: List[Any] = field(default_factory=list)  # tree-sitter nodes
    successors: List[int] = field(default_factory=list)   # block IDs
    predecessors: List[int] = field(default_factory=list)  # block IDs
    taint_in: Optional[TaintState] = None
    taint_out: Optional[TaintState] = None
    line_start: int = 0
    line_end: int = 0
    scope: str = "module"  # "module", "function:func_name", "class:ClsName.method"
    is_branch: bool = False
    branch_condition: Optional[str] = None


@dataclass
class FunctionDef:
    """Represents a function definition found during AST traversal."""
    name: str
    params: List[str]
    body_node: Any  # tree-sitter node for the function body
    line_start: int
    line_end: int
    scope: str = "module"
    is_method: bool = False
    class_name: Optional[str] = None


@dataclass
class TaintFinding:
    """A taint analysis finding."""
    rule_id: str
    rule_name: str
    severity: str
    cwe: str
    message: str
    file: str
    line: int
    source: str
    sink: str
    tainted_variable: str
    sanitized: bool
    sanitizers_found: List[str]
    confidence: float
    taint_path: str


# ─── Source/Sink/Sanitizer Patterns ───────────────────────────

# Built-in Python patterns (supplement YAML rules)
PYTHON_SOURCES = {
    "request.args", "request.form", "request.json", "request.data",
    "request.args.get", "request.form.get", "request.json.get",
    "request.GET", "request.POST",
    "flask.request.args", "flask.request.form", "flask.request.json",
    "django.request.GET", "django.request.POST",
    "input", "sys.stdin", "os.environ",
}

PYTHON_SINKS = {
    "cursor.execute", "db.execute", "connection.execute",
    "session.execute", "engine.execute",
    "os.system", "os.popen",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.check_output", "subprocess.check_call",
    "eval", "exec", "compile",
    "open", "os.path.join",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "urllib.request.urlopen",
    "render_template_string", "mark_safe",
    "pickle.loads", "pickle.load", "yaml.load", "yaml.unsafe_load",
    "marshal.loads", "shelve.open",
    "logger.info", "logger.debug", "logger.warning", "logger.error",
    "logging.info", "print",
}

PYTHON_SANITIZERS = {
    "shlex.quote", "shlex.split",
    "bleach.clean", "html.escape", "markupsafe.escape",
    "escape_string", "mysql.escape_string",
    "psycopg2.sql.SQL",
    "secure_filename", "validate_path", "validate_url",
    "ast.literal_eval", "json.loads", "yaml.safe_load",
    "os.path.realpath", "os.path.abspath",
    "parameterized_query",
}

# Built-in JavaScript/TypeScript patterns
JS_SOURCES = {
    "req.body", "req.params", "req.query", "req.headers", "req.cookies",
    "request.body", "request.params", "request.query",
    "window.location", "window.location.href", "location.search",
    "document.URL", "document.cookie", "document.referrer",
    "process.argv", "process.env",
    "event.body", "event.queryStringParameters", "event.pathParameters",
    "ctx.request.body", "ctx.request.params", "ctx.request.query",
    "this.body", "this.params", "this.query",
    "message.data",
    "props", "route.params",
}

JS_SINKS = {
    "innerHTML", "outerHTML", "document.write",
    "eval", "Function",
    "child_process.exec", "exec", "execSync", "spawn",
    "db.query", "db.execute",
    "response.write", "response.end",
    "fs.readFile", "fs.readFileSync", "fs.writeFile", "fs.createReadStream",
    "fetch", "axios.get", "axios.post",
    "http.get", "https.get",
    "vm.runInNewContext", "vm.Script",
    "dangerouslySetInnerHTML",
    "Object.assign", "lodash.merge", "lodash.set",
    "new RegExp", "RegExp",
}

JS_SANITIZERS = {
    "DOMPurify.sanitize", "DOMPurify",
    "encodeURIComponent", "decodeURIComponent",
    "escapeHtml", "escape",
    "textContent", "innerText", "createTextNode",
    "JSON.parse",
    "path.normalize", "path.resolve", "path.basename",
    "URL",
    "hasOwnProperty", "Object.create", "Object.freeze",
    "sanitize", "validate",
}


# ─── CFG Builder ─────────────────────────────────────────────

class CFGBuilder:
    """Builds a Control Flow Graph from a tree-sitter AST.

    The CFG consists of BasicBlock nodes connected by successor/predecessor
    edges. Branch nodes (if/else, for, while) create multiple successors.
    """

    def __init__(self, source_bytes: bytes, language: str):
        self.source = source_bytes
        self.language = language
        self.blocks: List[BasicBlock] = []
        self._block_counter = 0
        self._current_scope = "module"
        self._functions: Dict[str, FunctionDef] = {}

    def _new_block(self, line_start: int = 0, line_end: int = 0,
                   scope: str = "module") -> BasicBlock:
        """Create a new basic block."""
        block = BasicBlock(
            id=self._block_counter,
            line_start=line_start,
            line_end=line_end,
            scope=scope or self._current_scope,
        )
        self._block_counter += 1
        self.blocks.append(block)
        return block

    def _node_text(self, node) -> str:
        """Get the text of a tree-sitter node."""
        return node.text.decode('utf-8', errors='replace')

    def _node_line(self, node) -> int:
        """Get the 1-based line number of a tree-sitter node."""
        return node.start_point.row + 1

    def build(self, root_node) -> List[BasicBlock]:
        """Build the CFG from a tree-sitter AST root node.

        Returns a list of BasicBlock objects with successors/predecessors set.
        """
        self.blocks = []
        self._block_counter = 0
        self._functions = {}

        if self.language in ('python',):
            self._build_python(root_node)
        elif self.language in ('javascript', 'typescript', 'tsx'):
            self._build_javascript(root_node)
        else:
            # Generic fallback
            self._build_generic(root_node)

        # Set predecessor edges
        for block in self.blocks:
            for succ_id in block.successors:
                if 0 <= succ_id < len(self.blocks):
                    succ = self.blocks[succ_id]
                    if block.id not in succ.predecessors:
                        succ.predecessors.append(block.id)

        return self.blocks

    def _build_python(self, root_node):
        """Build CFG for Python AST."""
        entry = self._new_block(line_start=1, scope="module")
        self._process_python_nodes(root_node.children, entry)

    def _build_javascript(self, root_node):
        """Build CFG for JavaScript/TypeScript AST."""
        entry = self._new_block(line_start=1, scope="module")
        self._process_js_nodes(root_node.children, entry)

    def _build_generic(self, root_node):
        """Generic CFG builder — flat list of statements."""
        block = self._new_block(line_start=1)
        for child in root_node.children:
            if child.is_named:
                block.statements.append(child)
                block.line_end = self._node_line(child)
        if not block.statements:
            block.line_end = 1

    # ─── Python CFG Construction ─────────────────────────────

    def _process_python_nodes(self, nodes, current_block: BasicBlock) -> BasicBlock:
        """Process a sequence of Python AST nodes, appending to current_block.

        Returns the last block in the sequence (for chaining).
        """
        for node in nodes:
            if not node.is_named:
                continue

            node_type = node.type

            if node_type == 'function_definition':
                current_block = self._process_python_function(node, current_block)
            elif node_type == 'class_definition':
                current_block = self._process_python_class(node, current_block)
            elif node_type == 'if_statement':
                current_block = self._process_python_if(node, current_block)
            elif node_type == 'for_statement':
                current_block = self._process_python_for(node, current_block)
            elif node_type == 'while_statement':
                current_block = self._process_python_while(node, current_block)
            elif node_type == 'try_statement':
                current_block = self._process_python_try(node, current_block)
            elif node_type == 'with_statement':
                current_block = self._process_python_with(node, current_block)
            else:
                # Regular statement — add to current block
                current_block.statements.append(node)
                current_block.line_end = self._node_line(node)

        return current_block

    def _process_python_function(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python function definition into its own CFG scope."""
        func_name = self._get_python_func_name(node)
        params = self._get_python_params(node)
        body = node.child_by_field_name('body')

        # Record function definition
        func_def = FunctionDef(
            name=func_name,
            params=params,
            body_node=body,
            line_start=self._node_line(node),
            line_end=node.end_point.row + 1,
            scope=self._current_scope,
            is_method='.' in self._current_scope,
            class_name=self._current_scope.split(':')[1].split('.')[0]
                       if '.' in self._current_scope else None,
        )
        self._functions[func_name] = func_def

        # Create function entry block
        old_scope = self._current_scope
        self._current_scope = f"function:{func_name}"

        func_entry = self._new_block(
            line_start=self._node_line(node),
            scope=self._current_scope,
        )
        # Add function parameters as statements for taint analysis
        if body:
            for child in body.children:
                if child.is_named:
                    func_entry.statements.append(child)
                    func_entry.line_end = self._node_line(child)

        self._current_scope = old_scope
        return current_block

    def _get_python_func_name(self, node) -> str:
        name_node = node.child_by_field_name('name')
        return self._node_text(name_node) if name_node else '<anonymous>'

    def _get_python_params(self, node) -> List[str]:
        params_node = node.child_by_field_name('parameters')
        if not params_node:
            return []
        params = []
        for child in params_node.children:
            if child.type == 'identifier':
                params.append(self._node_text(child))
            elif child.type == 'typed_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append(self._node_text(sub))
                        break
            elif child.type == 'default_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append(self._node_text(sub))
                        break
            elif child.type == 'list_splat_pattern':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append('*' + self._node_text(sub))
            elif child.type == 'dictionary_splat_pattern':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append('**' + self._node_text(sub))
        return params

    def _process_python_class(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python class definition."""
        name_node = node.child_by_field_name('name')
        class_name = self._node_text(name_node) if name_node else '<class>'
        body = node.child_by_field_name('body')

        old_scope = self._current_scope
        self._current_scope = f"class:{class_name}"

        if body:
            for child in body.children:
                if child.is_named and child.type == 'function_definition':
                    method_name = self._get_python_func_name(child)
                    old_scope2 = self._current_scope
                    self._current_scope = f"class:{class_name}.{method_name}"

                    params = self._get_python_params(child)
                    method_body = child.child_by_field_name('body')

                    func_def = FunctionDef(
                        name=method_name,
                        params=params,
                        body_node=method_body,
                        line_start=self._node_line(child),
                        line_end=child.end_point.row + 1,
                        scope=self._current_scope,
                        is_method=True,
                        class_name=class_name,
                    )
                    self._functions[f"{class_name}.{method_name}"] = func_def
                    self._functions[method_name] = func_def

                    method_block = self._new_block(
                        line_start=self._node_line(child),
                        scope=self._current_scope,
                    )
                    if method_body:
                        for stmt in method_body.children:
                            if stmt.is_named:
                                method_block.statements.append(stmt)
                                method_block.line_end = self._node_line(stmt)

                    self._current_scope = old_scope2

        self._current_scope = old_scope
        return current_block

    def _process_python_if(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python if/elif/else statement — creates branch in CFG."""
        condition = node.child_by_field_name('condition')
        consequence = node.child_by_field_name('consequence')
        alternative = node.child_by_field_name('alternative')

        # Mark current block as branch point
        cond_text = self._node_text(condition) if condition else ''
        current_block.is_branch = True
        current_block.branch_condition = cond_text
        current_block.statements.append(node)  # Keep the if statement for reference

        # Create consequence block
        then_block = self._new_block(
            line_start=self._node_line(consequence) if consequence else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(then_block.id)

        if consequence:
            for child in consequence.children:
                if child.is_named:
                    then_block.statements.append(child)
                    then_block.line_end = self._node_line(child)

        # Create alternative block (else/elif)
        else_block = None
        if alternative:
            else_block = self._new_block(
                line_start=self._node_line(alternative),
                scope=self._current_scope,
            )
            current_block.successors.append(else_block.id)

            if alternative.type == 'elif_clause':
                # Recursively handle elif
                else_block.statements.append(alternative)
                else_block.line_end = self._node_line(alternative)
            else:
                for child in alternative.children:
                    if child.is_named:
                        else_block.statements.append(child)
                        else_block.line_end = self._node_line(child)
        else:
            # No else — flow continues directly, create an empty "fall-through" block
            fallthrough = self._new_block(
                line_start=node.end_point.row + 1,
                scope=self._current_scope,
            )
            current_block.successors.append(fallthrough.id)
            return fallthrough

        # Create join block after branches
        join_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        then_block.successors.append(join_block.id)
        if else_block:
            else_block.successors.append(join_block.id)

        return join_block

    def _process_python_for(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python for loop."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)
        current_block.line_end = self._node_line(node)

        # Loop body as a separate block
        loop_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(loop_block.id)

        if body:
            for child in body.children:
                if child.is_named:
                    loop_block.statements.append(child)
                    loop_block.line_end = self._node_line(child)

        # Loop back edge + exit
        loop_block.successors.append(loop_block.id)  # back edge
        exit_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        current_block.successors.append(exit_block.id)
        loop_block.successors.append(exit_block.id)

        return exit_block

    def _process_python_while(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python while loop."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)
        current_block.is_branch = True

        loop_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(loop_block.id)

        if body:
            for child in body.children:
                if child.is_named:
                    loop_block.statements.append(child)
                    loop_block.line_end = self._node_line(child)

        loop_block.successors.append(current_block.id)  # back edge
        exit_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        current_block.successors.append(exit_block.id)

        return exit_block

    def _process_python_try(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python try/except statement."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)

        # Try body
        try_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(try_block.id)

        if body:
            for child in body.children:
                if child.is_named:
                    try_block.statements.append(child)
                    try_block.line_end = self._node_line(child)

        # Exception handlers
        for child in node.children:
            if child.type == 'except_clause' and child.is_named:
                handler_body = child.child_by_field_name('body') if hasattr(child, 'child_by_field_name') else None
                except_block = self._new_block(
                    line_start=self._node_line(child),
                    scope=self._current_scope,
                )
                current_block.successors.append(except_block.id)
                if handler_body:
                    for stmt in handler_body.children:
                        if stmt.is_named:
                            except_block.statements.append(stmt)
                            except_block.line_end = self._node_line(stmt)

        # Join after try/except
        join_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        try_block.successors.append(join_block.id)

        return join_block

    def _process_python_with(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a Python with statement."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)
        current_block.line_end = self._node_line(node)

        if body:
            with_block = self._new_block(
                line_start=self._node_line(body),
                scope=self._current_scope,
            )
            current_block.successors.append(with_block.id)
            for child in body.children:
                if child.is_named:
                    with_block.statements.append(child)
                    with_block.line_end = self._node_line(child)
            return with_block

        return current_block

    # ─── JavaScript/TypeScript CFG Construction ──────────────

    def _process_js_nodes(self, nodes, current_block: BasicBlock) -> BasicBlock:
        """Process JavaScript AST nodes."""
        for node in nodes:
            if not node.is_named:
                continue

            node_type = node.type

            if node_type in ('function_declaration', 'function_expression',
                             'arrow_function', 'generator_function_declaration',
                             'method_definition'):
                current_block = self._process_js_function(node, current_block)
            elif node_type == 'class_declaration':
                current_block = self._process_js_class(node, current_block)
            elif node_type == 'if_statement':
                current_block = self._process_js_if(node, current_block)
            elif node_type in ('for_statement', 'for_in_statement', 'of_statement'):
                current_block = self._process_js_for(node, current_block)
            elif node_type == 'while_statement':
                current_block = self._process_js_while(node, current_block)
            elif node_type == 'try_statement':
                current_block = self._process_js_try(node, current_block)
            else:
                current_block.statements.append(node)
                current_block.line_end = self._node_line(node)

        return current_block

    def _process_js_function(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a JavaScript function definition."""
        # Get function name
        name_node = node.child_by_field_name('name')
        func_name = self._node_text(name_node) if name_node else '<anonymous>'

        # Get parameters
        params_node = node.child_by_field_name('parameters')
        params = self._get_js_params(params_node)

        # Get body
        body = node.child_by_field_name('body')

        old_scope = self._current_scope
        self._current_scope = f"function:{func_name}"

        func_def = FunctionDef(
            name=func_name,
            params=params,
            body_node=body,
            line_start=self._node_line(node),
            line_end=node.end_point.row + 1,
            scope=self._current_scope,
        )
        self._functions[func_name] = func_def

        func_block = self._new_block(
            line_start=self._node_line(node),
            scope=self._current_scope,
        )
        if body:
            for child in body.children:
                if child.is_named:
                    func_block.statements.append(child)
                    func_block.line_end = self._node_line(child)

        self._current_scope = old_scope
        return current_block

    def _get_js_params(self, params_node) -> List[str]:
        """Extract parameter names from JS/TS parameter list."""
        if not params_node:
            return []
        params = []
        for child in params_node.children:
            if not child.is_named:
                continue
            if child.type == 'identifier':
                params.append(self._node_text(child))
            elif child.type == 'object_pattern':
                # Destructuring: const { id, name } = req.params
                for prop in child.children:
                    if prop.type in ('shorthand_property_identifier_pattern',
                                     'pair_pattern', 'property_identifier'):
                        if prop.type == 'shorthand_property_identifier_pattern':
                            params.append(self._node_text(prop))
                        elif prop.type == 'pair_pattern':
                            val = prop.child_by_field_name('value')
                            if val:
                                params.append(self._node_text(val))
            elif child.type == 'array_pattern':
                for el in child.children:
                    if el.is_named and el.type == 'identifier':
                        params.append(self._node_text(el))
            elif child.type == 'rest_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append('...' + self._node_text(sub))
            elif child.type == 'assignment_pattern':
                left = child.child_by_field_name('left')
                if left and left.type == 'identifier':
                    params.append(self._node_text(left))
        return params

    def _process_js_class(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process a JavaScript class declaration."""
        name_node = node.child_by_field_name('name')
        class_name = self._node_text(name_node) if name_node else '<class>'
        body = node.child_by_field_name('body')

        if body:
            for child in body.children:
                if child.is_named and child.type == 'method_definition':
                    method_name_node = child.child_by_field_name('name')
                    method_name = self._node_text(method_name_node) if method_name_node else '<method>'
                    method_body = child.child_by_field_name('body')
                    method_params_node = child.child_by_field_name('parameters')
                    method_params = self._get_js_params(method_params_node)

                    func_def = FunctionDef(
                        name=method_name,
                        params=method_params,
                        body_node=method_body,
                        line_start=self._node_line(child),
                        line_end=child.end_point.row + 1,
                        scope=f"class:{class_name}.{method_name}",
                        is_method=True,
                        class_name=class_name,
                    )
                    self._functions[f"{class_name}.{method_name}"] = func_def
                    self._functions[method_name] = func_def

                    method_block = self._new_block(
                        line_start=self._node_line(child),
                        scope=f"class:{class_name}.{method_name}",
                    )
                    if method_body:
                        for stmt in method_body.children:
                            if stmt.is_named:
                                method_block.statements.append(stmt)
                                method_block.line_end = self._node_line(stmt)

        return current_block

    def _process_js_if(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process JavaScript if/else — creates branch in CFG."""
        condition = node.child_by_field_name('condition')
        consequence = node.child_by_field_name('consequence')
        alternative = node.child_by_field_name('alternative')

        cond_text = self._node_text(condition) if condition else ''
        current_block.is_branch = True
        current_block.branch_condition = cond_text
        current_block.statements.append(node)

        # Then block
        then_block = self._new_block(
            line_start=self._node_line(consequence) if consequence else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(then_block.id)

        if consequence:
            if consequence.type in ('statement_block',):
                for child in consequence.children:
                    if child.is_named:
                        then_block.statements.append(child)
                        then_block.line_end = self._node_line(child)
            else:
                then_block.statements.append(consequence)
                then_block.line_end = self._node_line(consequence)

        # Else block
        else_block = None
        if alternative:
            else_block = self._new_block(
                line_start=self._node_line(alternative),
                scope=self._current_scope,
            )
            current_block.successors.append(else_block.id)

            if alternative.type == 'statement_block':
                for child in alternative.children:
                    if child.is_named:
                        else_block.statements.append(child)
                        else_block.line_end = self._node_line(child)
            elif alternative.type == 'if_statement':
                else_block.statements.append(alternative)
                else_block.line_end = self._node_line(alternative)
            else:
                else_block.statements.append(alternative)
                else_block.line_end = self._node_line(alternative)
        else:
            fallthrough = self._new_block(
                line_start=node.end_point.row + 1,
                scope=self._current_scope,
            )
            current_block.successors.append(fallthrough.id)
            return fallthrough

        # Join block
        join_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        then_block.successors.append(join_block.id)
        if else_block:
            else_block.successors.append(join_block.id)

        return join_block

    def _process_js_for(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process JavaScript for/for-in/for-of loop."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)
        current_block.line_end = self._node_line(node)

        loop_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(loop_block.id)

        if body:
            if body.type == 'statement_block':
                for child in body.children:
                    if child.is_named:
                        loop_block.statements.append(child)
                        loop_block.line_end = self._node_line(child)
            else:
                loop_block.statements.append(body)
                loop_block.line_end = self._node_line(body)

        loop_block.successors.append(loop_block.id)
        exit_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        current_block.successors.append(exit_block.id)
        loop_block.successors.append(exit_block.id)

        return exit_block

    def _process_js_while(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process JavaScript while loop."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)
        current_block.is_branch = True

        loop_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(loop_block.id)

        if body:
            if body.type == 'statement_block':
                for child in body.children:
                    if child.is_named:
                        loop_block.statements.append(child)
                        loop_block.line_end = self._node_line(child)
            else:
                loop_block.statements.append(body)

        loop_block.successors.append(current_block.id)
        exit_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        current_block.successors.append(exit_block.id)

        return exit_block

    def _process_js_try(self, node, current_block: BasicBlock) -> BasicBlock:
        """Process JavaScript try/catch/finally."""
        body = node.child_by_field_name('body')
        current_block.statements.append(node)

        try_block = self._new_block(
            line_start=self._node_line(body) if body else self._node_line(node),
            scope=self._current_scope,
        )
        current_block.successors.append(try_block.id)

        if body:
            for child in body.children:
                if child.is_named:
                    try_block.statements.append(child)
                    try_block.line_end = self._node_line(child)

        # catch
        catch_node = node.child_by_field_name('handler')
        if catch_node:
            catch_body = catch_node.child_by_field_name('body')
            catch_block = self._new_block(
                line_start=self._node_line(catch_node),
                scope=self._current_scope,
            )
            current_block.successors.append(catch_block.id)
            if catch_body:
                for child in catch_body.children:
                    if child.is_named:
                        catch_block.statements.append(child)
                        catch_block.line_end = self._node_line(child)

        join_block = self._new_block(
            line_start=node.end_point.row + 1,
            scope=self._current_scope,
        )
        try_block.successors.append(join_block.id)

        return join_block


# ─── AST Source/Sink/Sanitizer Detection ──────────────────────

class ASTTaintDetector:
    """Detects taint sources, sinks, and sanitizers in tree-sitter AST nodes.

    Instead of regex line-by-line matching, this walks the actual AST structure
    to identify:
    - Variable assignments from taint sources
    - Function/method calls to dangerous sinks
    - Sanitizer applications that remove taint
    - String interpolation containing tainted variables
    - Attribute access patterns (self.x = tainted, data["key"])
    - Destructuring patterns (const { id } = req.params)
    """

    def __init__(self, language: str, rules: List[Dict]):
        self.language = language
        self.rules = rules
        self.source_patterns = set()
        self.sink_patterns = set()
        self.sanitizer_patterns = set()

        # Load patterns from YAML rules
        for rule in rules:
            for src in rule.get('sources', []):
                self.source_patterns.add(src)
            for sink in rule.get('sinks', []):
                self.sink_patterns.add(sink)
            for san in rule.get('sanitizers', []):
                self.sanitizer_patterns.add(san)

        # Add built-in patterns
        if language == 'python':
            self.source_patterns |= PYTHON_SOURCES
            self.sink_patterns |= PYTHON_SINKS
            self.sanitizer_patterns |= PYTHON_SANITIZERS
        elif language in ('javascript', 'typescript', 'tsx'):
            self.source_patterns |= JS_SOURCES
            self.sink_patterns |= JS_SINKS
            self.sanitizer_patterns |= JS_SANITIZERS

    def _node_text(self, node) -> str:
        return node.text.decode('utf-8', errors='replace')

    def _node_line(self, node) -> int:
        return node.start_point.row + 1

    # ─── Expression Name Resolution ───────────────────────────

    def _resolve_expression_name(self, node) -> str:
        """Resolve a tree-sitter expression node to a qualified name string.

        Examples:
            request.args.get  →  "request.args.get"
            req.params.id     →  "req.params.id"
            os.system         →  "os.system"
            cursor.execute    →  "cursor.execute"
        """
        if node is None:
            return ""

        node_type = node.type

        if node_type == 'identifier':
            return self._node_text(node)

        elif node_type == 'attribute':
            # Python attribute access: obj.attr
            obj = node.child_by_field_name('object')
            attr = node.child_by_field_name('attribute')
            obj_name = self._resolve_expression_name(obj) if obj else ""
            attr_name = self._node_text(attr) if attr else ""
            if obj_name and attr_name:
                return f"{obj_name}.{attr_name}"
            return attr_name or obj_name

        elif node_type in ('member_expression',):
            # JS member expression: obj.prop
            obj = node.child_by_field_name('object')
            prop = node.child_by_field_name('property')
            obj_name = self._resolve_expression_name(obj) if obj else ""
            prop_name = self._node_text(prop) if prop else ""
            if obj_name and prop_name:
                return f"{obj_name}.{prop_name}"
            return prop_name or obj_name

        elif node_type == 'call':
            func = node.child_by_field_name('function')
            return self._resolve_expression_name(func) if func else ""

        elif node_type == 'call_expression':
            func = node.child_by_field_name('function')
            return self._resolve_expression_name(func) if func else ""

        elif node_type == 'subscript':
            # Python: data["key"]
            obj = node.child_by_field_name('value')
            obj_name = self._resolve_expression_name(obj) if obj else ""
            return obj_name

        return ""

    def _resolve_call_name(self, node) -> str:
        """Resolve a call expression to its function/method name.

        Works for both Python 'call' nodes and JS 'call_expression' nodes.
        """
        if node is None:
            return ""

        # For call nodes, get the function child
        if node.type == 'call':
            func = node.child_by_field_name('function')
        elif node.type == 'call_expression':
            func = node.child_by_field_name('function')
        else:
            func = node

        return self._resolve_expression_name(func)

    # ─── Source Detection ─────────────────────────────────────

    def detect_source(self, node) -> Optional[Tuple[str, str, str]]:
        """Check if an AST node represents a taint source.

        Returns:
            (source_name, var_name, path_step) or None
            source_name: e.g., "request.args"
            var_name: the variable being assigned from the source
            path_step: step for the taint path
        """
        if self.language == 'python':
            return self._detect_python_source(node)
        elif self.language in ('javascript', 'typescript', 'tsx'):
            return self._detect_js_source(node)
        return None

    def _detect_python_source(self, node) -> Optional[Tuple[str, str, str]]:
        """Detect Python taint sources from AST nodes."""
        if node.type != 'expression_statement':
            return None

        # Look for assignment: var = <source>
        for child in node.children:
            if child.type == 'assignment':
                return self._check_python_assignment_source(child)
        return None

    def _check_python_assignment_source(self, assign_node) -> Optional[Tuple[str, str, str]]:
        """Check if a Python assignment RHS is a taint source."""
        left = assign_node.child_by_field_name('left')
        right = assign_node.child_by_field_name('right')

        if not left or not right:
            return None

        var_name = self._resolve_expression_name(left)
        rhs_name = self._resolve_expression_name(right)

        # Check if RHS matches a source pattern
        matched_source = self._match_source_pattern(rhs_name)
        if matched_source:
            return (matched_source, var_name, var_name)

        # Check if RHS is a call that includes a source (e.g., request.args.get('id'))
        if right.type == 'call':
            call_name = self._resolve_call_name(right)
            matched_source = self._match_source_pattern(call_name)
            if matched_source:
                return (matched_source, var_name, var_name)

            # Check if any argument contains a source reference
            for arg in right.children:
                if arg.type == 'argument_list':
                    for sub in arg.children:
                        if sub.is_named:
                            sub_name = self._resolve_expression_name(sub)
                            matched = self._match_source_pattern(sub_name)
                            if matched:
                                return (matched, var_name, var_name)

        # Check for f-string with tainted variable
        if right.type == 'string':
            source = self._check_fstring_taint(right)
            if source:
                return (source, var_name, var_name)

        # Check for binary operation with source (string concat)
        if right.type == 'binary_operator':
            source = self._check_binary_op_taint(right)
            if source:
                return (source, var_name, var_name)

        return None

    def _detect_js_source(self, node) -> Optional[Tuple[str, str, str]]:
        """Detect JavaScript taint sources from AST nodes."""
        # Variable declaration: const/let/var x = <source>
        if node.type in ('lexical_declaration', 'variable_declaration'):
            for child in node.children:
                if child.type == 'variable_declarator':
                    return self._check_js_declarator_source(child)

        # Assignment expression: x = <source>
        if node.type == 'expression_statement':
            for child in node.children:
                if child.type == 'assignment_expression':
                    return self._check_js_assignment_source(child)

        return None

    def _check_js_declarator_source(self, decl_node) -> Optional[Tuple[str, str, str]]:
        """Check if a JS variable declarator is a taint source."""
        name_node = decl_node.child_by_field_name('name')
        value_node = decl_node.child_by_field_name('value')

        if not name_node:
            return None

        # Handle destructuring: const { id, name } = req.params
        if name_node.type == 'object_pattern':
            if not value_node:
                return None
            value_name = self._resolve_expression_name(value_node)
            matched = self._match_source_pattern(value_name)
            if matched:
                # Return each destructured variable as a source
                # We'll handle this specially — return the pattern name
                return (matched, f"<destructure:{value_name}>", f"<destructure:{value_name}>")
            return None

        var_name = self._node_text(name_node)
        if not value_node:
            return None

        value_name = self._resolve_expression_name(value_node)

        # Check direct source match
        matched = self._match_source_pattern(value_name)
        if matched:
            return (matched, var_name, var_name)

        # Check call expression
        if value_node.type == 'call_expression':
            call_name = self._resolve_call_name(value_node)
            matched = self._match_source_pattern(call_name)
            if matched:
                return (matched, var_name, var_name)

        # Check template string with tainted var
        if value_node.type == 'template_string':
            source = self._check_js_template_taint(value_node)
            if source:
                return (source, var_name, var_name)

        # Check binary expression with source
        if value_node.type == 'binary_expression':
            source = self._check_js_binary_taint(value_node)
            if source:
                return (source, var_name, var_name)

        return None

    def _check_js_assignment_source(self, assign_node) -> Optional[Tuple[str, str, str]]:
        """Check if a JS assignment expression RHS is a taint source."""
        left = assign_node.child_by_field_name('left')
        right = assign_node.child_by_field_name('right')

        if not left or not right:
            return None

        var_name = self._resolve_expression_name(left)
        rhs_name = self._resolve_expression_name(right)

        matched = self._match_source_pattern(rhs_name)
        if matched:
            return (matched, var_name, var_name)

        if right.type == 'call_expression':
            call_name = self._resolve_call_name(right)
            matched = self._match_source_pattern(call_name)
            if matched:
                return (matched, var_name, var_name)

        return None

    def _match_source_pattern(self, name: str) -> Optional[str]:
        """Check if a name matches any source pattern.

        Supports:
        - Exact matches (built-in plain patterns)
        - Suffix/prefix matches (request.args matches flask.request.args)
        - Regex matches (YAML rule patterns like ``req\\.(?:body|params)``)
        """
        if not name:
            return None

        # Exact match
        if name in self.source_patterns:
            return name

        # Suffix match: check if any source is a suffix of the name
        for pattern in self.source_patterns:
            if name.endswith('.' + pattern) or pattern.endswith('.' + name.split('.')[-1]):
                return pattern

        # Prefix match: request.args matches request.args.get
        for pattern in self.source_patterns:
            if name.startswith(pattern + '.'):
                return pattern

        # Regex match for YAML rule patterns (contain special regex chars)
        for pattern in self.source_patterns:
            if any(c in pattern for c in ('\\', '(?:', '[', '|', '(', '^', '$')):
                try:
                    if re.search(pattern, name):
                        return pattern
                except re.error:
                    pass

        return None

    def _match_sink_pattern(self, name: str) -> Optional[str]:
        """Check if a name matches any sink pattern.

        Supports exact, suffix, and regex matching.
        """
        if not name:
            return None

        if name in self.sink_patterns:
            return name

        # Suffix match
        for pattern in self.sink_patterns:
            if name.endswith('.' + pattern):
                return pattern

        # The last segment matches
        last_seg = name.split('.')[-1]
        if last_seg in self.sink_patterns:
            return name

        # Regex match for YAML rule patterns
        for pattern in self.sink_patterns:
            if any(c in pattern for c in ('\\', '(?:', '[', '|', '(', '^', '$')):
                try:
                    if re.search(pattern, name):
                        return pattern
                except re.error:
                    pass

        return None

    def _match_sanitizer_pattern(self, name: str) -> Optional[str]:
        """Check if a name matches any sanitizer pattern.

        Supports exact, suffix, and regex matching.
        """
        if not name:
            return None

        if name in self.sanitizer_patterns:
            return name

        for pattern in self.sanitizer_patterns:
            if name.endswith('.' + pattern):
                return pattern

        last_seg = name.split('.')[-1]
        if last_seg in self.sanitizer_patterns:
            return name

        # Regex match for YAML rule patterns
        for pattern in self.sanitizer_patterns:
            if any(c in pattern for c in ('\\', '(?:', '[', '|', '(', '^', '$')):
                try:
                    if re.search(pattern, name):
                        return pattern
                except re.error:
                    pass

        return None

    # ─── F-String / Template Literal Taint ────────────────────

    def _check_fstring_taint(self, string_node) -> Optional[str]:
        """Check if a Python f-string contains tainted interpolation."""
        for child in string_node.children:
            if child.type == 'interpolation':
                for sub in child.children:
                    if sub.is_named and sub.type != '{' and sub.type != '}':
                        name = self._resolve_expression_name(sub)
                        matched = self._match_source_pattern(name)
                        if matched:
                            return matched
        return None

    def _check_js_template_taint(self, template_node) -> Optional[str]:
        """Check if a JS template literal contains tainted substitution."""
        for child in template_node.children:
            if child.type == 'template_substitution':
                for sub in child.children:
                    if sub.is_named and sub.type not in ('${', '}'):
                        name = self._resolve_expression_name(sub)
                        matched = self._match_source_pattern(name)
                        if matched:
                            return matched
        return None

    def _check_binary_op_taint(self, node) -> Optional[str]:
        """Check if a Python binary operation (string concat) involves a taint source."""
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')

        for operand in (left, right):
            if operand:
                name = self._resolve_expression_name(operand)
                matched = self._match_source_pattern(name)
                if matched:
                    return matched
                # Recurse for chained binary ops
                if operand.type == 'binary_operator':
                    found = self._check_binary_op_taint(operand)
                    if found:
                        return found
        return None

    def _check_js_binary_taint(self, node) -> Optional[str]:
        """Check if a JS binary expression involves a taint source."""
        left = node.child_by_field_name('left')
        right = node.child_by_field_name('right')

        for operand in (left, right):
            if operand:
                name = self._resolve_expression_name(operand)
                matched = self._match_source_pattern(name)
                if matched:
                    return matched
                if operand.type == 'binary_expression':
                    found = self._check_js_binary_taint(operand)
                    if found:
                        return found
        return None

    # ─── Sink Detection ───────────────────────────────────────

    def detect_sink(self, node) -> Optional[Tuple[str, int, List[str]]]:
        """Check if an AST node contains a call to a dangerous sink.

        Returns:
            (sink_name, line_number, argument_var_names) or None
        """
        if self.language == 'python':
            return self._detect_python_sink(node)
        elif self.language in ('javascript', 'typescript', 'tsx'):
            return self._detect_js_sink(node)
        return None

    def _detect_python_sink(self, node) -> Optional[Tuple[str, int, List[str]]]:
        """Detect Python sink calls from AST nodes."""
        call_nodes = self._find_call_nodes(node)

        for call_node in call_nodes:
            call_name = self._resolve_call_name(call_node)
            matched_sink = self._match_sink_pattern(call_name)
            if matched_sink:
                # Extract argument variable names
                arg_vars = self._extract_call_arg_vars(call_node)
                line = self._node_line(call_node)
                return (matched_sink, line, arg_vars)

        return None

    def _detect_js_sink(self, node) -> Optional[Tuple[str, int, List[str]]]:
        """Detect JavaScript sink calls and assignments from AST nodes."""
        # Check for call expressions (eval(), db.query(), etc.)
        call_nodes = self._find_call_nodes(node)

        for call_node in call_nodes:
            call_name = self._resolve_call_name(call_node)
            matched_sink = self._match_sink_pattern(call_name)
            if matched_sink:
                arg_vars = self._extract_js_call_arg_vars(call_node)
                line = self._node_line(call_node)
                return (matched_sink, line, arg_vars)

        # Check for property assignments (element.innerHTML = ...)
        if node.type == 'expression_statement':
            for child in node.children:
                if child.type == 'assignment_expression':
                    left = child.child_by_field_name('left')
                    right = child.child_by_field_name('right')
                    if left:
                        left_name = self._resolve_expression_name(left)
                        matched_sink = self._match_sink_pattern(left_name)
                        if matched_sink:
                            right_vars = self._extract_vars_from_node(right)
                            line = self._node_line(child)
                            return (matched_sink, line, right_vars)

        return None

    def _find_call_nodes(self, node) -> List:
        """Recursively find all call/call_expression nodes in a statement."""
        calls = []
        if node.type in ('call', 'call_expression'):
            calls.append(node)

        # Don't recurse into function definitions
        if node.type in ('function_definition', 'function_declaration',
                         'arrow_function', 'class_definition', 'class_declaration'):
            return calls

        for child in node.children:
            if child.is_named:
                calls.extend(self._find_call_nodes(child))
        return calls

    def _extract_call_arg_vars(self, call_node) -> List[str]:
        """Extract variable names from Python call arguments.

        Recursively searches for identifier references inside arguments,
        including inside f-strings, binary operators, and nested calls.
        """
        arg_vars = []
        for child in call_node.children:
            if child.type == 'argument_list':
                for arg in child.children:
                    if arg.is_named:
                        # First try direct name resolution
                        name = self._resolve_expression_name(arg)
                        if name:
                            arg_vars.append(name)
                        else:
                            # Recursively extract all variable references
                            arg_vars.extend(self._extract_vars_from_node(arg))
        return arg_vars

    def _extract_js_call_arg_vars(self, call_node) -> List[str]:
        """Extract variable names from JS call arguments.

        Recursively searches for identifier references inside arguments,
        including inside template strings and binary expressions.
        """
        arg_vars = []
        for child in call_node.children:
            if child.type == 'arguments':
                for arg in child.children:
                    if arg.is_named:
                        name = self._resolve_expression_name(arg)
                        if name:
                            arg_vars.append(name)
                        else:
                            arg_vars.extend(self._extract_vars_from_node(arg))
        return arg_vars

    def _extract_vars_from_node(self, node) -> List[str]:
        """Extract all variable references from an AST node."""
        vars_found = []
        if node is None:
            return vars_found

        if node.type in ('identifier',):
            vars_found.append(self._node_text(node))
        elif node.type in ('member_expression', 'attribute'):
            # Only get the root object
            obj = node.child_by_field_name('object')
            if obj and obj.type == 'identifier':
                vars_found.append(self._node_text(obj))

        for child in node.children:
            if child.is_named:
                vars_found.extend(self._extract_vars_from_node(child))

        return vars_found

    # ─── Sanitizer Detection ──────────────────────────────────

    def detect_sanitizer(self, node) -> Optional[Tuple[str, str]]:
        """Check if an AST node represents a sanitizer application.

        Returns:
            (sanitizer_name, target_var_name) or None
        """
        if self.language == 'python':
            return self._detect_python_sanitizer(node)
        elif self.language in ('javascript', 'typescript', 'tsx'):
            return self._detect_js_sanitizer(node)
        return None

    def _detect_python_sanitizer(self, node) -> Optional[Tuple[str, str]]:
        """Detect Python sanitizer calls."""
        if node.type != 'expression_statement':
            return None

        for child in node.children:
            if child.type == 'assignment':
                left = child.child_by_field_name('left')
                right = child.child_by_field_name('right')
                if not left or not right:
                    continue

                var_name = self._resolve_expression_name(left)

                # Direct sanitizer call: x = shlex.quote(y)
                if right.type == 'call':
                    call_name = self._resolve_call_name(right)
                    matched = self._match_sanitizer_pattern(call_name)
                    if matched:
                        return (matched, var_name)

                    # Check for parameterized queries:
                    # cursor.execute("...?", (param,)) is parameterized
                    args_node = None
                    for sub in right.children:
                        if sub.type == 'argument_list':
                            args_node = sub
                            break

                    if args_node and call_name in ('cursor.execute', 'db.execute',
                                                    'connection.execute', 'session.execute'):
                        # Check if second argument is a tuple (parameterized)
                        arg_children = [c for c in args_node.children if c.is_named]
                        if len(arg_children) >= 2:
                            # Has placeholder + params = parameterized
                            return ("parameterized_query", var_name)

        return None

    def _detect_js_sanitizer(self, node) -> Optional[Tuple[str, str]]:
        """Detect JavaScript sanitizer calls."""
        # Variable declaration with sanitizer: const safe = DOMPurify.sanitize(x)
        if node.type in ('lexical_declaration', 'variable_declaration'):
            for child in node.children:
                if child.type == 'variable_declarator':
                    name_node = child.child_by_field_name('name')
                    value_node = child.child_by_field_name('value')
                    if not name_node or not value_node:
                        continue

                    var_name = self._node_text(name_node)

                    if value_node.type == 'call_expression':
                        call_name = self._resolve_call_name(value_node)
                        matched = self._match_sanitizer_pattern(call_name)
                        if matched:
                            return (matched, var_name)

        # Assignment with sanitizer
        if node.type == 'expression_statement':
            for child in node.children:
                if child.type == 'assignment_expression':
                    left = child.child_by_field_name('left')
                    right = child.child_by_field_name('right')
                    if not left or not right:
                        continue
                    var_name = self._resolve_expression_name(left)

                    if right.type == 'call_expression':
                        call_name = self._resolve_call_name(right)
                        matched = self._match_sanitizer_pattern(call_name)
                        if matched:
                            return (matched, var_name)

        return None

    # ─── Assignment/Propagation Detection ─────────────────────

    def detect_assignment(self, node) -> Optional[Tuple[str, str]]:
        """Detect variable assignment for taint propagation.

        Returns:
            (dst_var, src_var_or_expr) or None
        """
        if self.language == 'python':
            return self._detect_python_assignment(node)
        elif self.language in ('javascript', 'typescript', 'tsx'):
            return self._detect_js_assignment(node)
        return None

    def _detect_python_assignment(self, node) -> Optional[Tuple[str, str]]:
        """Detect Python variable assignments for taint propagation."""
        if node.type == 'expression_statement':
            for child in node.children:
                if child.type == 'assignment':
                    left = child.child_by_field_name('left')
                    right = child.child_by_field_name('right')
                    if not left or not right:
                        continue

                    dst = self._resolve_expression_name(left)
                    if not dst:
                        continue

                    # Simple variable assignment: y = x
                    if right.type == 'identifier':
                        return (dst, self._node_text(right))

                    # Attribute assignment: y = x.prop
                    src_name = self._resolve_expression_name(right)
                    if src_name:
                        return (dst, src_name)

                    # Call assignment: y = func(x) — propagate through
                    if right.type == 'call':
                        # Extract the argument variables for inter-procedural tracking
                        arg_vars = self._extract_call_arg_vars(right)
                        for arg_var in arg_vars:
                            if arg_var:
                                return (dst, arg_var)

                    # f-string / string concat — propagate from interpolated vars
                    if right.type == 'string':
                        for sub in right.children:
                            if sub.type == 'interpolation':
                                for inner in sub.children:
                                    if inner.is_named and inner.type not in ('{', '}'):
                                        name = self._resolve_expression_name(inner)
                                        if name:
                                            return (dst, name)

                    if right.type == 'binary_operator':
                        left_r = right.child_by_field_name('left')
                        right_r = right.child_by_field_name('right')
                        for operand in (left_r, right_r):
                            if operand:
                                name = self._resolve_expression_name(operand)
                                if name:
                                    return (dst, name)

        return None

    def _detect_js_assignment(self, node) -> Optional[Tuple[str, str]]:
        """Detect JS variable assignments for taint propagation."""
        # Variable declaration
        if node.type in ('lexical_declaration', 'variable_declaration'):
            for child in node.children:
                if child.type == 'variable_declarator':
                    name_node = child.child_by_field_name('name')
                    value_node = child.child_by_field_name('value')
                    if not name_node or not value_node:
                        continue

                    # Skip destructuring patterns — handled in source detection
                    if name_node.type == 'object_pattern':
                        continue

                    dst = self._node_text(name_node)
                    src = self._resolve_expression_name(value_node)

                    if src:
                        return (dst, src)

                    # Template string
                    if value_node.type == 'template_string':
                        for sub in value_node.children:
                            if sub.type == 'template_substitution':
                                for inner in sub.children:
                                    if inner.is_named and inner.type not in ('${', '}'):
                                        name = self._resolve_expression_name(inner)
                                        if name:
                                            return (dst, name)

                    # Binary expression
                    if value_node.type == 'binary_expression':
                        left = value_node.child_by_field_name('left')
                        right = value_node.child_by_field_name('right')
                        for operand in (left, right):
                            if operand:
                                name = self._resolve_expression_name(operand)
                                if name:
                                    return (dst, name)

        # Assignment expression
        if node.type == 'expression_statement':
            for child in node.children:
                if child.type == 'assignment_expression':
                    left = child.child_by_field_name('left')
                    right = child.child_by_field_name('right')
                    if not left or not right:
                        continue
                    dst = self._resolve_expression_name(left)
                    src = self._resolve_expression_name(right)
                    if dst and src:
                        return (dst, src)

        return None

    # ─── Destructuring Detection ──────────────────────────────

    def detect_js_destructuring(self, node) -> Optional[List[Tuple[str, str]]]:
        """Detect JS destructuring assignments that introduce taint.

        e.g., const { id, name } = req.params → id~req.params, name~req.params

        Returns:
            List of (var_name, source_name) or None
        """
        if node.type not in ('lexical_declaration', 'variable_declaration'):
            return None

        results = []
        for child in node.children:
            if child.type != 'variable_declarator':
                continue

            name_node = child.child_by_field_name('name')
            value_node = child.child_by_field_name('value')

            if not name_node or name_node.type != 'object_pattern':
                continue
            if not value_node:
                continue

            value_name = self._resolve_expression_name(value_node)
            matched = self._match_source_pattern(value_name)
            if not matched:
                continue

            # Extract destructured variable names
            for prop in name_node.children:
                if prop.type == 'shorthand_property_identifier_pattern':
                    results.append((self._node_text(prop), matched))
                elif prop.type == 'pair_pattern':
                    val = prop.child_by_field_name('value')
                    if val and val.type == 'identifier':
                        results.append((self._node_text(val), matched))

        return results if results else None


# ─── Main Analyzer ───────────────────────────────────────────

class ASTTaintAnalyzer:
    """Main AST-based taint analysis engine.

    Usage:
        analyzer = ASTTaintAnalyzer(rules=rules, language='python')
        findings = analyzer.analyze_file('/path/to/file.py', content, 'python', rules)

        # Or for a whole workspace:
        results = analyzer.analyze_workspace('/path/to/workspace')
    """

    def __init__(self, rules: List[Dict] = None, language: str = 'python'):
        self.rules = rules or []
        self.language = language
        self._detector: Optional[ASTTaintDetector] = None
        self._cfg_builder: Optional[CFGBuilder] = None
        self._functions: Dict[str, FunctionDef] = {}
        self._findings: List[TaintFinding] = []

    def analyze_file(self, file_path: str, content: str = None,
                     language: str = None, rules: List[Dict] = None) -> List[Dict]:
        """Analyze a single file for taint vulnerabilities.

        Args:
            file_path: Path to the source file.
            content: File content (if None, reads from file_path).
            language: Language override ('python', 'javascript', 'typescript', 'tsx').
            rules: Rule override (if None, uses instance rules).

        Returns:
            List of finding dicts compatible with semantic_engine format.
        """
        lang = language or self.language
        active_rules = rules or self.rules

        # Auto-load rules from default rules directory if none provided
        if not active_rules:
            active_rules = self._load_rules()

        # Read content if not provided
        if content is None:
            content = safe_read_file(file_path)
            if content is None:
                return []

        # Filter rules by language
        lang_rules = [r for r in active_rules
                      if r.get('language', '').lower() == lang.lower()]

        # Try tree-sitter analysis
        if TREE_SITTER_AVAILABLE:
            findings = self._analyze_with_treesitter(file_path, content, lang, lang_rules)
            if findings is not None:
                return findings

        # Fallback to regex-based analysis
        logger.info(f"Tree-sitter not available for {lang}, falling back to regex analysis")
        return self._analyze_with_regex(file_path, content, lang, lang_rules)

    def _analyze_with_treesitter(self, file_path: str, content: str,
                                  language: str, rules: List[Dict]) -> Optional[List[Dict]]:
        """Perform AST-based taint analysis using tree-sitter."""
        # Map language to tree-sitter grammar name
        ts_lang = language
        if language == 'typescript':
            ts_lang = 'typescript'
        elif language == 'tsx':
            ts_lang = 'tsx'

        parser = _get_parser(ts_lang)
        if not parser:
            return None

        try:
            tree = parser.parse(content.encode('utf-8'))
        except Exception as e:
            logger.warning(f"Tree-sitter parse error for {file_path}: {e}")
            return None

        if not tree or not tree.root_node:
            return None

        root = tree.root_node

        # Phase 1: Build CFG
        self._cfg_builder = CFGBuilder(content.encode('utf-8'), language)
        blocks = self._cfg_builder.build(root)
        self._functions = dict(self._cfg_builder._functions)

        # Phase 2: Set up taint detector
        self._detector = ASTTaintDetector(language, rules)

        # Phase 3: Forward taint propagation through CFG
        findings = self._propagate_taint(blocks, file_path, language, rules)

        # Phase 4: Inter-procedural analysis
        findings += self._interprocedural_analysis(file_path, content, language, rules)

        # Convert to dict format
        return [self._finding_to_dict(f) for f in findings]

    def _propagate_taint(self, blocks: List[BasicBlock], file_path: str,
                          language: str, rules: List[Dict]) -> List[TaintFinding]:
        """Forward taint propagation through the CFG.

        Uses a worklist algorithm:
        1. Initialize taint state at entry (empty for module, params-as-taint for functions)
        2. For each block, compute taint_in by merging predecessors' taint_out
        3. Process statements in the block (detect sources, propagations, sanitizers, sinks)
        4. Compute taint_out
        5. If taint_out changed, add successors to worklist

        Key: Function blocks with no predecessors get their parameters
        marked as potentially tainted (standard practice in taint analysis).
        """
        findings = []

        if not blocks:
            return findings

        # Initialize taint states — scope-aware (Improvement 2)
        # Module-level blocks get a module-scoped TaintState; function/class
        # blocks get a child scope whose parent is the module state.
        module_state = TaintState(scope='module')
        for block in blocks:
            if block.scope == 'module':
                block.taint_in = module_state.child_scope('module')
            else:
                block.taint_in = module_state.child_scope(block.scope)
            block.taint_out = block.taint_in.copy()

        # For function blocks, initialize with parameters as taint sources
        # This is standard practice — function parameters represent external input
        for block in blocks:
            if block.scope.startswith('function:') or block.scope.startswith('class:'):
                if not block.predecessors:
                    # Find the function definition for this block
                    func_name = block.scope.split(':', 1)[1]
                    if '.' in func_name:
                        func_name = func_name.split('.')[-1]
                    func_def = self._functions.get(func_name)
                    if func_def and func_def.params:
                        # Mark all parameters as tainted from "<param>"
                        for param in func_def.params:
                            clean_param = param.lstrip('*')  # Remove *args, **kwargs markers
                            block.taint_in.add_taint(
                                clean_param, f'<param:{clean_param}>', clean_param
                            )

        # Worklist: start with ALL blocks (function blocks are disconnected from module)
        worklist = deque(range(len(blocks)))
        visited = set()
        max_iterations = len(blocks) * 4  # Allow enough iterations for convergence
        iterations = 0

        while worklist and iterations < max_iterations:
            block_id = worklist.popleft()
            iterations += 1

            if block_id >= len(blocks):
                continue

            block = blocks[block_id]

            # Compute taint_in by merging predecessors
            # But preserve initial parameter taint for function entry blocks
            initial_taint = None
            if not block.predecessors and (block.scope.startswith('function:')
                                           or block.scope.startswith('class:')):
                # Keep parameter taint
                func_name = block.scope.split(':', 1)[1]
                if '.' in func_name:
                    func_name = func_name.split('.')[-1]
                func_def = self._functions.get(func_name)
                if func_def and func_def.params:
                    initial_taint = TaintState()
                    for param in func_def.params:
                        clean_param = param.lstrip('*')
                        initial_taint.add_taint(
                            clean_param, f'<param:{clean_param}>', clean_param
                        )

            if block.predecessors:
                merged = None
                for pred_id in block.predecessors:
                    if 0 <= pred_id < len(blocks) and blocks[pred_id].taint_out:
                        if merged is None:
                            merged = blocks[pred_id].taint_out.copy()
                        else:
                            merged = merged.merge(blocks[pred_id].taint_out)
                if initial_taint and merged:
                    block.taint_in = initial_taint.merge(merged)
                elif initial_taint:
                    block.taint_in = initial_taint
                elif merged:
                    block.taint_in = merged
                else:
                    block.taint_in = TaintState()
            elif initial_taint:
                block.taint_in = initial_taint
            else:
                block.taint_in = TaintState()

            # Process statements in this block
            state = block.taint_in.copy()
            for stmt in block.statements:
                state, stmt_findings = self._process_statement(
                    stmt, state, file_path, language, rules
                )
                findings.extend(stmt_findings)

            # ── Improvement 3: Path-sensitive branch condition refinement ──
            #
            # If this block is a branch point with a stored condition, we refine
            # the taint state that flows to each successor.  For example:
            #
            #   if sanitized:   ← branch_condition = "sanitized"
            #       # then-branch: sanitized is truthy → it IS sanitized
            #   else:
            #       # else-branch: sanitized is falsy → mark as NOT sanitized
            #
            # Similarly for `if not var:` the semantics are inverted.
            #
            # The refined state is stored per-successor so that when a
            # successor block merges its predecessors, it sees the refined
            # (not the generic) state.
            if block.is_branch and block.branch_condition:
                self._apply_branch_refinement(
                    block, state, blocks, visited, worklist
                )
                # The standard taint_out is the unrefined state (for any
                # non-branch successor or as fallback).  Refined states for
                # individual successors are applied inside the helper above.
                old_out = block.taint_out
                block.taint_out = state
                if not self._states_equal(old_out, state):
                    for succ_id in block.successors:
                        if succ_id not in visited or succ_id == block_id:
                            worklist.append(succ_id)
                visited.add(block_id)
                continue

            # Check if taint_out changed
            old_out = block.taint_out
            block.taint_out = state

            # If state changed, add successors to worklist
            if not self._states_equal(old_out, state):
                for succ_id in block.successors:
                    if succ_id not in visited or succ_id == block_id:
                        worklist.append(succ_id)

            visited.add(block_id)

        return findings

    def _process_statement(self, stmt, state: TaintState, file_path: str,
                            language: str, rules: List[Dict]) -> Tuple[TaintState, List[TaintFinding]]:
        """Process a single statement for taint analysis.

        Returns updated taint state and any findings.
        """
        findings = []

        if self._detector is None:
            return state, findings

        # 1. Detect source → add taint
        source_result = self._detector.detect_source(stmt)
        if source_result:
            source_name, var_name, path_step = source_result

            # Handle destructuring
            if var_name.startswith('<destructure:'):
                destructure_result = self._detector.detect_js_destructuring(stmt)
                if destructure_result:
                    for destr_var, destr_src in destructure_result:
                        state.add_taint(destr_var, destr_src, destr_var)
            else:
                state.add_taint(var_name, source_name, path_step)

        # 2. Detect sanitizer → remove taint
        sanitizer_result = self._detector.detect_sanitizer(stmt)
        if sanitizer_result:
            san_name, target_var = sanitizer_result
            state.remove_taint(target_var, san_name)
            # Also check if sanitizer is called on a tainted variable
            # e.g., x = DOMPurify.sanitize(tainted_var) → x is sanitized
            if target_var in state.tainted:
                state.tainted[target_var].sanitized_by.add(san_name)
                state.tainted[target_var].is_sanitized = True

        # 3. Detect assignment → propagate taint
        assign_result = self._detector.detect_assignment(stmt)
        if assign_result:
            dst_var, src_var = assign_result
            # Check if source variable is tainted
            src_info = state.get_taint_info(src_var)
            if src_info:
                state.propagate(src_var, dst_var)
            # Also check if the source itself is a source pattern
            src_matched = self._detector._match_source_pattern(src_var)
            if src_matched and not state.is_tainted(dst_var):
                state.add_taint(dst_var, src_matched, dst_var)

        # 4. Detect sink → check if tainted data reaches it
        sink_result = self._detector.detect_sink(stmt)
        if sink_result:
            sink_name, line, arg_vars = sink_result

            # Check if this sink is a parameterized query (sanitizer)
            is_parameterized = self._is_parameterized_sink(stmt, sink_name)

            for arg_var in arg_vars:
                # Check if the argument variable is tainted
                taint_info = state.get_taint_info(arg_var)
                if taint_info and not taint_info.is_sanitized and not is_parameterized:
                    # Tainted data reaches sink!
                    for rule in rules:
                        rule_sources = rule.get('sources', [])
                        rule_sinks = rule.get('sinks', [])

                        # Check if this source/sink pair matches the rule
                        if self._matches_rule(taint_info.sources, sink_name,
                                              rule_sources, rule_sinks):
                            taint_path = self._render_taint_path(taint_info, sink_name)
                            confidence = self._compute_confidence(
                                taint_info, sink_name, state
                            )

                            findings.append(TaintFinding(
                                rule_id=rule.get('id', 'unknown'),
                                rule_name=rule.get('name', 'Unknown'),
                                severity=rule.get('severity', 'medium'),
                                cwe=rule.get('cwe', ''),
                                message=rule.get('message', ''),
                                file=file_path,
                                line=line,
                                source=list(taint_info.sources)[0] if taint_info.sources else 'unknown',
                                sink=sink_name,
                                tainted_variable=arg_var,
                                sanitized=False,
                                sanitizers_found=[],
                                confidence=confidence,
                                taint_path=taint_path,
                            ))

                elif (taint_info and taint_info.is_sanitized) or is_parameterized:
                    # Sanitized but still worth noting at lower confidence
                    for rule in rules:
                        rule_sources = rule.get('sources', [])
                        rule_sinks = rule.get('sinks', [])

                        if self._matches_rule(taint_info.sources if taint_info else {sink_name},
                                              sink_name, rule_sources, rule_sinks):
                            taint_path = self._render_taint_path(taint_info, sink_name) if taint_info else sink_name
                            findings.append(TaintFinding(
                                rule_id=rule.get('id', 'unknown'),
                                rule_name=rule.get('name', 'Unknown'),
                                severity="info",
                                cwe=rule.get('cwe', ''),
                                message=f"Tainted data reaches {sink_name} but appears sanitized",
                                file=file_path,
                                line=line,
                                source=list(taint_info.sources)[0] if taint_info and taint_info.sources else 'unknown',
                                sink=sink_name,
                                tainted_variable=arg_var,
                                sanitized=True,
                                sanitizers_found=list(taint_info.sanitized_by) if taint_info else ['parameterized'],
                                confidence=0.30,
                                taint_path=taint_path,
                            ))

        # 5. Check for additional taint in f-strings / template literals
        # (This catches cases where taint flows through string interpolation
        #  into a variable that isn't directly the source variable)
        self._check_implicit_taint_in_statement(stmt, state)

        return state, findings

    def _check_implicit_taint_in_statement(self, stmt, state: TaintState):
        """Check for implicit taint propagation through string interpolation.

        For example:
            query = f"SELECT * FROM users WHERE id = {user_id}"
            → 'query' is tainted if 'user_id' is tainted

        And in JS:
            const url = `/api/users/${userId}`
            → 'url' is tainted if 'userId' is tainted
        """
        if self._detector is None:
            return

        # Find assignments that involve string interpolation
        if self.language == 'python' and stmt.type == 'expression_statement':
            for child in stmt.children:
                if child.type == 'assignment':
                    left = child.child_by_field_name('left')
                    right = child.child_by_field_name('right')
                    if not left or not right:
                        continue

                    dst_var = self._detector._resolve_expression_name(left)

                    # f-string
                    if right.type == 'string':
                        for sub in right.children:
                            if sub.type == 'interpolation':
                                for inner in sub.children:
                                    if inner.is_named and inner.type not in ('{', '}'):
                                        name = self._detector._resolve_expression_name(inner)
                                        if name and state.is_tainted(name):
                                            src_info = state.get_taint_info(name)
                                            if src_info and not state.is_tainted(dst_var):
                                                new_info = src_info.copy()
                                                new_info.var_name = dst_var
                                                new_info.path = list(src_info.path) + [dst_var]
                                                state.tainted[dst_var] = new_info

                    # Binary op (string concat)
                    if right.type == 'binary_operator':
                        for side_field in ('left', 'right'):
                            operand = right.child_by_field_name(side_field)
                            if operand:
                                name = self._detector._resolve_expression_name(operand)
                                if name and state.is_tainted(name):
                                    src_info = state.get_taint_info(name)
                                    if src_info and not state.is_tainted(dst_var):
                                        new_info = src_info.copy()
                                        new_info.var_name = dst_var
                                        new_info.path = list(src_info.path) + [dst_var]
                                        state.tainted[dst_var] = new_info

        elif self.language in ('javascript', 'typescript', 'tsx'):
            if stmt.type in ('lexical_declaration', 'variable_declaration'):
                for child in stmt.children:
                    if child.type == 'variable_declarator':
                        name_node = child.child_by_field_name('name')
                        value_node = child.child_by_field_name('value')
                        if not name_node or not value_node:
                            continue
                        if name_node.type == 'object_pattern':
                            continue

                        dst_var = self._detector._node_text(name_node)

                        # Template string
                        if value_node.type == 'template_string':
                            for sub in value_node.children:
                                if sub.type == 'template_substitution':
                                    for inner in sub.children:
                                        if inner.is_named and inner.type not in ('${', '}'):
                                            name = self._detector._resolve_expression_name(inner)
                                            if name and state.is_tainted(name):
                                                src_info = state.get_taint_info(name)
                                                if src_info and not state.is_tainted(dst_var):
                                                    new_info = src_info.copy()
                                                    new_info.var_name = dst_var
                                                    new_info.path = list(src_info.path) + [dst_var]
                                                    state.tainted[dst_var] = new_info

                        # Binary expression
                        if value_node.type == 'binary_expression':
                            for side_field in ('left', 'right'):
                                operand = value_node.child_by_field_name(side_field)
                                if operand:
                                    name = self._detector._resolve_expression_name(operand)
                                    if name and state.is_tainted(name):
                                        src_info = state.get_taint_info(name)
                                        if src_info and not state.is_tainted(dst_var):
                                            new_info = src_info.copy()
                                            new_info.var_name = dst_var
                                            new_info.path = list(src_info.path) + [dst_var]
                                            state.tainted[dst_var] = new_info

    def _interprocedural_analysis(self, file_path: str, content: str,
                                   language: str, rules: List[Dict]) -> List[TaintFinding]:
        """Inter-procedural taint analysis within a file.

        Tracks taint through function calls:
        1. If a function parameter is tainted at a call site
        2. The taint propagates to the parameter inside the function
        3. If the function's return value flows to a sink, we detect it

        Improvement 1 — Return value propagation:
        After analysing a function body we inspect every `return` statement.
        If the returned expression carries tainted data, we mark the
        variable that receives the call's return value as tainted at the
        call site.  This closes the inter-procedural loop:

            def get_query(user_id):      # user_id is tainted
                return f"SELECT … {user_id}"   # return is tainted

            q = get_query(uid)           # q is NOW tainted (return propagation)

        This is done by analyzing each function body separately with
        the taint state from call sites.
        """
        findings = []

        if not self._functions or not self._detector:
            return findings

        # Build a simple call graph from the source
        source_bytes = content.encode('utf-8')
        ts_lang = language
        if language == 'tsx':
            ts_lang = 'tsx'

        parser = _get_parser(ts_lang)
        if not parser:
            return findings

        try:
            tree = parser.parse(source_bytes)
        except Exception:
            return findings

        root = tree.root_node

        # Find all function calls and their arguments + return-variable
        call_sites = self._find_call_sites(root)

        # ── Improvement 1: compute return-taint for each function ──
        # After analysing a function body we extract the taint that
        # reaches any `return` statement.  This is later propagated
        # back to the call-site LHS.
        return_taint_cache: Dict[str, TaintState] = {}

        # Build a map from line number → block taint_out so we can look up
        # which variables are tainted at each call site (from Phase 3 results)
        block_taint_at_line: Dict[int, TaintState] = {}
        if self._cfg_builder:
            for block in self._cfg_builder.blocks:
                if block.taint_out:
                    for line in range(block.line_start, block.line_end + 1):
                        block_taint_at_line[line] = block.taint_out

        # For each function, analyze with taint from call sites
        for func_name, func_def in self._functions.items():
            # Skip if no one calls this function
            relevant_calls = [cs for cs in call_sites if cs['func_name'] == func_name]
            if not relevant_calls:
                continue

            for call_site in relevant_calls:
                # Create initial taint state based on call arguments
                initial_state = TaintState(scope=f'function:{func_name}')
                param_taint_map = {}  # param_idx → taint source

                args = call_site.get('args', [])
                params = func_def.params

                for i, arg_name in enumerate(args):
                    if i < len(params):
                        param_name = params[i]
                        # ── Improvement 1 (extended): use Phase 3 taint state ──
                        # Instead of only checking source patterns, look up the
                        # actual taint state from the CFG block that contains
                        # this call site.  This correctly handles cases where
                        # the argument is a local variable that was tainted by
                        # a prior source detection in Phase 3.
                        taint_info = None
                        call_line = call_site.get('line', 0)
                        taint_state = block_taint_at_line.get(call_line)
                        if taint_state:
                            taint_info = taint_state.get_taint_info(arg_name)

                        if taint_info and not taint_info.is_sanitized:
                            # The argument is tainted according to Phase 3
                            source_name = list(taint_info.sources)[0] if taint_info.sources else arg_name
                            initial_state.add_taint(param_name, source_name, param_name)
                            param_taint_map[i] = source_name
                        else:
                            # Fallback: check if arg matches source patterns
                            matched = self._detector._match_source_pattern(arg_name)
                            if matched:
                                initial_state.add_taint(param_name, matched, param_name)
                                param_taint_map[i] = matched

                # ── Improvement 1 (extended): also analyse functions that
                # generate taint internally (e.g. read from request.args)
                # even when no tainted argument is passed.  The function may
                # still return tainted data that flows to the call-site LHS.
                analyze_anyway = not initial_state.tainted and relevant_calls

                if not initial_state.tainted and not analyze_anyway:
                    continue

                # Analyze function body with this initial taint state
                func_blocks = self._cfg_builder.blocks if self._cfg_builder else []
                func_findings, final_state = self._analyze_function_body(
                    func_def, initial_state, file_path, language, rules
                )
                findings.extend(func_findings)

                # ── Improvement 1: extract return taint ──
                # Scan the function body for return statements and check
                # whether the returned expression is tainted in final_state.
                return_taint = self._extract_return_taint(
                    func_def, final_state, language
                )
                if return_taint and return_taint.tainted:
                    # Cache so we can propagate at call sites
                    cache_key = func_name
                    if cache_key in return_taint_cache:
                        return_taint_cache[cache_key] = return_taint_cache[cache_key].merge(return_taint)
                    else:
                        return_taint_cache[cache_key] = return_taint

        # ── Improvement 1: propagate return taint to call-site LHS ──
        # For each call site where the LHS variable exists, mark it as
        # tainted if the called function's return value carries taint.
        if return_taint_cache:
            self._propagate_return_taint(
                call_sites, return_taint_cache, file_path, language, rules, findings
            )

        return findings

    def _find_call_sites(self, root_node) -> List[Dict]:
        """Find all function call sites in the AST.

        Improvement 1: also records the *lhs_var* — the variable that
        receives the return value — so that return-taint can be
        propagated back to the call site.
        """
        call_sites = []

        def visit(node):
            if node.type in ('call', 'call_expression'):
                func_name = self._detector._resolve_call_name(node) if self._detector else ""

                # Extract argument variable names
                arg_vars = []
                for child in node.children:
                    if child.type in ('argument_list', 'arguments'):
                        for arg in child.children:
                            if arg.is_named:
                                name = self._detector._resolve_expression_name(arg) if self._detector else ""
                                if name:
                                    arg_vars.append(name)

                if func_name and func_name in self._functions:
                    # ── Improvement 1: determine the LHS variable ──
                    # Walk up to find the enclosing assignment so we know
                    # which variable receives the return value.
                    lhs_var = self._find_call_lhs(node)

                    call_sites.append({
                        'func_name': func_name,
                        'args': arg_vars,
                        'line': node.start_point.row + 1,
                        'lhs_var': lhs_var,  # may be None
                        'node': node,        # keep reference for later
                    })

            for child in node.children:
                if child.is_named:
                    visit(child)

        visit(root_node)
        return call_sites

    def _find_call_lhs(self, call_node) -> Optional[str]:
        """Find the variable that receives the return value of a call.

        Improvement 1 helper.  Walks the AST upward from the call_node
        to find the enclosing assignment and returns the LHS variable name.

        Handles:
            result = func(args)        → "result"
            result = obj.func(args)    → "result"
            var x = func(args)  (JS)   → "x"
        """
        if not self._detector:
            return None

        parent = call_node.parent
        if parent is None:
            return None

        # Python: assignment → right = call_node
        if parent.type == 'assignment':
            left = parent.child_by_field_name('left')
            if left:
                name = self._detector._resolve_expression_name(left)
                if name:
                    return name

        # JS: variable_declarator → value = call_node
        if parent.type == 'variable_declarator':
            name_node = parent.child_by_field_name('name')
            if name_node and name_node.type == 'identifier':
                return self._detector._node_text(name_node)

        # Check one more level up (call might be wrapped in expression_statement)
        grandparent = parent.parent
        if grandparent is None:
            return None

        if grandparent.type == 'assignment':
            left = grandparent.child_by_field_name('left')
            if left:
                name = self._detector._resolve_expression_name(left)
                if name:
                    return name

        return None

    def _analyze_function_body(self, func_def: FunctionDef,
                                initial_state: TaintState,
                                file_path: str, language: str,
                                rules: List[Dict]) -> Tuple[List[TaintFinding], TaintState]:
        """Analyze a function body with a given initial taint state.

        Improvement 1: returns both findings *and* the final taint state
        so that callers can extract return-value taint for propagation
        back to call sites.
        """
        findings = []
        state = initial_state.copy()

        if not func_def.body_node:
            return findings, state

        # Walk through the function body's statements
        for stmt in func_def.body_node.children:
            if not stmt.is_named:
                continue

            state, stmt_findings = self._process_statement(
                stmt, state, file_path, language, rules
            )
            findings.extend(stmt_findings)

        return findings, state

    # ── Improvement 1 helpers: return-value taint extraction ────────

    def _extract_return_taint(self, func_def: FunctionDef,
                               final_state: TaintState,
                               language: str) -> Optional[TaintState]:
        """Inspect return statements in a function body for tainted data.

        Walks the function body AST looking for return nodes.  For each
        return, resolves the returned expression to a variable name and
        checks if that variable is tainted in *final_state*.

        Yields a TaintState containing the taint info of any tainted
        return-expressions, or None if no return carries taint.
        """
        if not func_def.body_node or not self._detector:
            return None

        return_state = TaintState(scope=f'return:{func_def.name}')

        def visit(node):
            """Recursively find return statements."""
            found = False
            if language == 'python' and node.type == 'return_statement':
                found = True
            elif language in ('javascript', 'typescript', 'tsx') and node.type == 'return_statement':
                found = True

            if found:
                # The return statement may have a single child expression
                for child in node.children:
                    if not child.is_named:
                        continue
                    # Resolve the returned expression to a variable name
                    ret_var = self._detector._resolve_expression_name(child)
                    if ret_var:
                        taint_info = final_state.get_taint_info(ret_var)
                        if taint_info and not taint_info.is_sanitized:
                            # This return carries taint — record it
                            return_state.add_taint(
                                f'<return:{func_def.name}>',
                                list(taint_info.sources)[0] if taint_info.sources else 'unknown',
                                f'{func_def.name}()',
                            )
                            # Also store a mapping from the return taint to
                            # the actual taint info so we can propagate it
                            return_state.tainted[f'<return:{func_def.name}>'] = taint_info.copy()
                            return_state.tainted[f'<return:{func_def.name}>'].var_name = f'<return:{func_def.name}>'

                    # Also check for f-strings / binary ops in return
                    if child.type in ('string', 'template_string', 'binary_operator',
                                      'binary_expression'):
                        # Check interpolated/operand variables
                        tainted_in_expr = self._find_tainted_subexpr(child, final_state)
                        for var_name, tinfo in tainted_in_expr.items():
                            if not tinfo.is_sanitized:
                                return_state.add_taint(
                                    f'<return:{func_def.name}>',
                                    list(tinfo.sources)[0] if tinfo.sources else 'unknown',
                                    f'{func_def.name}()',
                                )
                                return_state.tainted[f'<return:{func_def.name}>'] = tinfo.copy()
                                return_state.tainted[f'<return:{func_def.name}>'].var_name = f'<return:{func_def.name}>'
                    break  # only check first named child of return

            # Recurse into non-function children (avoid descending into
            # nested function definitions)
            if node.type not in ('function_definition', 'function_declaration',
                                  'arrow_function', 'class_definition',
                                  'class_declaration'):
                for child in node.children:
                    if child.is_named:
                        visit(child)

        for stmt in func_def.body_node.children:
            if stmt.is_named:
                visit(stmt)

        if return_state.tainted:
            return return_state
        return None

    def _find_tainted_subexpr(self, node, state: TaintState) -> Dict[str, TaintInfo]:
        """Find tainted variables referenced inside an expression.

        Helper for _extract_return_taint — checks f-string
        interpolations, binary operands, and identifier sub-expressions.
        """
        result = {}

        def visit_inner(n):
            if n.type == 'identifier':
                name = self._detector._node_text(n) if self._detector else ""
                if name:
                    info = state.get_taint_info(name)
                    if info:
                        result[name] = info
            elif n.type == 'interpolation':
                for sub in n.children:
                    if sub.is_named:
                        visit_inner(sub)
            elif n.type == 'template_substitution':
                for sub in n.children:
                    if sub.is_named:
                        visit_inner(sub)
            else:
                for child in n.children:
                    if child.is_named:
                        visit_inner(child)

        visit_inner(node)
        return result

    def _propagate_return_taint(self, call_sites: List[Dict],
                                 return_taint_cache: Dict[str, TaintState],
                                 file_path: str, language: str,
                                 rules: List[Dict],
                                 findings: List[TaintFinding]):
        """Propagate taint from function return values to call-site LHS.

        Improvement 1 — for each call site where the called function has
        tainted return values, mark the LHS variable as tainted.  Then
        scan subsequent blocks for sinks that use the LHS variable.

        We do NOT re-run the full CFG propagation (which would re-initialize
        taint states).  Instead, we do a targeted forward scan from the call
        site's block to find sinks reachable with the new taint.
        """
        if not self._cfg_builder or not self._detector:
            return

        blocks = self._cfg_builder.blocks
        if not blocks:
            return

        for cs in call_sites:
            func_name = cs.get('func_name', '')
            lhs_var = cs.get('lhs_var')
            if not lhs_var or func_name not in return_taint_cache:
                continue

            ret_taint = return_taint_cache[func_name]
            return_info = ret_taint.get_taint_info(f'<return:{func_name}>')
            if not return_info:
                continue

            # Find the block that contains this call site
            call_line = cs.get('line', 0)
            start_block = None
            for block in blocks:
                if block.line_start <= call_line <= block.line_end:
                    start_block = block
                    break

            if start_block is None:
                continue

            # Create a taint state with the LHS variable tainted
            source_name = list(return_info.sources)[0] if return_info.sources else f'<return:{func_name}>'
            taint_path = list(return_info.path) if return_info.path else [source_name, lhs_var]

            # Scan from the call site block forward through successors,
            # looking for sinks that use the LHS variable.
            self._scan_for_sinks_with_taint(
                start_block, blocks, lhs_var, source_name, taint_path,
                return_info, file_path, language, rules, findings
            )

    def _scan_for_sinks_with_taint(self, start_block: 'BasicBlock',
                                     blocks: List['BasicBlock'],
                                     taint_var: str, source_name: str,
                                     taint_path: List[str],
                                     return_info: 'TaintInfo',
                                     file_path: str, language: str,
                                     rules: List[Dict],
                                     findings: List[TaintFinding]):
        """Targeted forward scan from a block to find sinks for a newly tainted variable.

        This avoids re-running the full CFG propagation.  We walk through the
        block's statements and successor blocks looking for sinks that reference
        *taint_var*.
        """
        visited_blocks = set()
        # Start scanning from the call-line onward in start_block
        worklist = deque([start_block.id])

        # Build a TaintInfo for the new taint
        new_taint = TaintInfo(
            var_name=taint_var,
            sources=set(return_info.sources),
            path=taint_path + [taint_var] if taint_var not in taint_path else taint_path,
            sanitized_by=set(return_info.sanitized_by),
            is_sanitized=return_info.is_sanitized,
        )

        while worklist:
            block_id = worklist.popleft()
            if block_id in visited_blocks:
                continue
            visited_blocks.add(block_id)

            if block_id >= len(blocks):
                continue
            block = blocks[block_id]

            # Process statements in this block looking for sinks
            for stmt in block.statements:
                sink_result = self._detector.detect_sink(stmt)
                if sink_result:
                    sink_name, line, arg_vars = sink_result
                    if taint_var in arg_vars and not new_taint.is_sanitized:
                        # Tainted return value reaches sink!
                        is_parameterized = self._is_parameterized_sink(stmt, sink_name)
                        if is_parameterized:
                            continue

                        for rule in rules:
                            rule_sources = rule.get('sources', [])
                            rule_sinks = rule.get('sinks', [])
                            if self._matches_rule(new_taint.sources, sink_name,
                                                  rule_sources, rule_sinks):
                                rendered_path = self._render_taint_path(new_taint, sink_name)
                                confidence = self._compute_confidence(new_taint, sink_name, TaintState())
                                findings.append(TaintFinding(
                                    rule_id=rule.get('id', 'unknown'),
                                    rule_name=rule.get('name', 'Unknown'),
                                    severity=rule.get('severity', 'medium'),
                                    cwe=rule.get('cwe', ''),
                                    message=rule.get('message', ''),
                                    file=file_path,
                                    line=line,
                                    source=list(new_taint.sources)[0] if new_taint.sources else 'unknown',
                                    sink=sink_name,
                                    tainted_variable=taint_var,
                                    sanitized=False,
                                    sanitizers_found=[],
                                    confidence=confidence,
                                    taint_path=rendered_path,
                                ))

                # Also check if the tainted variable is reassigned
                assign_result = self._detector.detect_assignment(stmt)
                if assign_result:
                    dst_var, src_var = assign_result
                    if src_var == taint_var:
                        # Taint propagates to dst_var — continue scanning with dst_var too
                        new_taint = TaintInfo(
                            var_name=dst_var,
                            sources=set(new_taint.sources),
                            path=list(new_taint.path) + [dst_var],
                            sanitized_by=set(new_taint.sanitized_by),
                            is_sanitized=new_taint.is_sanitized,
                        )
                        taint_var = dst_var

                # Check for sanitizer
                sanitizer_result = self._detector.detect_sanitizer(stmt)
                if sanitizer_result:
                    san_name, target_var = sanitizer_result
                    if target_var == taint_var:
                        new_taint.sanitized_by.add(san_name)
                        new_taint.is_sanitized = True

            # Add successors to worklist
            for succ_id in block.successors:
                if succ_id not in visited_blocks:
                    worklist.append(succ_id)

    # ─── Helper Methods ───────────────────────────────────────

    def _is_parameterized_sink(self, stmt, sink_name: str) -> bool:
        """Check if a sink call is using parameterized queries.

        Detects patterns like:
            cursor.execute("SELECT ... WHERE id = ?", (user_id,))
            db.query("SELECT ... WHERE id = $1", [user_id])
        """
        # Find call nodes in this statement
        call_nodes = self._find_all_calls(stmt)

        for call_node in call_nodes:
            call_name = self._detector._resolve_call_name(call_node) if self._detector else ""

            # Check if this is an execute/query call with parameterized args
            if any(call_name.endswith(x) for x in ('execute', 'query', 'raw')):
                # Check for multiple arguments (parameterized pattern)
                args_container = None
                for child in call_node.children:
                    if child.type in ('argument_list', 'arguments'):
                        args_container = child
                        break

                if args_container:
                    arg_children = [c for c in args_container.children if c.is_named]
                    # 2+ arguments = likely parameterized (query + params)
                    if len(arg_children) >= 2:
                        # Verify first arg is a string literal (the query template)
                        first_arg = arg_children[0]
                        if first_arg.type in ('string', 'template_string'):
                            text = first_arg.text.decode('utf-8', errors='replace')
                            # Check for placeholder patterns: ?, $1, %s, :param
                            if any(p in text for p in ('?', '$1', '%s', ':1', ':param')):
                                return True
        return False

    def _find_all_calls(self, node) -> List:
        """Find all call/call_expression nodes in an AST subtree."""
        calls = []
        if node.type in ('call', 'call_expression'):
            calls.append(node)

        if node.type in ('function_definition', 'function_declaration',
                         'arrow_function', 'class_definition', 'class_declaration'):
            return calls

        for child in node.children:
            if child.is_named:
                calls.extend(self._find_all_calls(child))
        return calls

    def _matches_rule(self, taint_sources: Set[str], sink_name: str,
                      rule_sources: List[str], rule_sinks: List[str]) -> bool:
        """Check if a taint source→sink pair matches a rule's sources and sinks.

        For parameter-based taint sources (e.g., '<param:user_id>'), matches
        any rule source since parameters represent arbitrary external input.

        Supports both exact string matching and regex matching for YAML rule
        patterns (e.g., 'req\\.(?:body|params|query)').
        """
        source_match = False
        sink_match = False

        # Check source match — parameter sources match any rule source
        # since function parameters can receive data from any source
        has_param_source = any(s.startswith('<param:') for s in taint_sources)
        # ── Improvement 1: return-value sources also match any rule source ──
        # because a function's return value can carry taint from any source
        # that was present inside the function body.
        has_return_source = any(s.startswith('<return:') for s in taint_sources)
        if has_param_source or has_return_source:
            source_match = True
        else:
            for src in taint_sources:
                for rule_src in rule_sources:
                    # Exact match
                    if src == rule_src:
                        source_match = True
                        break
                    # Suffix match: req.params matches flask.request.args
                    if src.endswith('.' + rule_src) or rule_src.endswith('.' + src.split('.')[-1]):
                        source_match = True
                        break
                    # Suffix match: rule_src last segment matches src last segment
                    src_last = src.split('.')[-1]
                    rule_last = rule_src.split('.')[-1]
                    if src_last == rule_last and src_last.isidentifier():
                        source_match = True
                        break
                    # ── Improvement 1 (extended): prefix match ──
                    # request.args.get should match flask.request.args
                    # because request.args is a shared sub-pattern.
                    # Try progressive prefixes of both src and rule_src.
                    src_parts = src.split('.')
                    rule_parts = rule_src.split('.')
                    # Check if any suffix of src_parts matches any prefix of rule_parts
                    # e.g., ['request', 'args', 'get'] → ['request', 'args'] matches ['flask', 'request', 'args']
                    for start in range(len(src_parts)):
                        src_suffix = '.'.join(src_parts[start:])
                        if src_suffix == rule_src or rule_src.endswith('.' + src_suffix):
                            source_match = True
                            break
                        # Also check reverse
                        if rule_src == src_suffix or src.endswith('.' + src_suffix):
                            # Already handled above
                            pass
                    if source_match:
                        break
                    # Also check if rule_src suffix matches src prefix
                    for start in range(len(rule_parts)):
                        rule_suffix = '.'.join(rule_parts[start:])
                        if src.startswith(rule_suffix + '.') or src == rule_suffix:
                            source_match = True
                            break
                    if source_match:
                        break
                    # Regex match for YAML patterns
                    if any(c in rule_src for c in ('\\', '(?:', '[', '|', '(', '^', '$')):
                        try:
                            if re.search(rule_src, src):
                                source_match = True
                                break
                        except re.error:
                            pass
                if source_match:
                    break

        # Check sink match
        for rule_sink in rule_sinks:
            # Exact match
            if sink_name == rule_sink:
                sink_match = True
                break
            # Suffix match: cursor.execute matches .execute
            sink_last = sink_name.split('.')[-1]
            rule_last = rule_sink.split('.')[-1]
            if sink_last == rule_last and sink_last.isidentifier():
                sink_match = True
                break
            if sink_name.endswith('.' + rule_sink):
                sink_match = True
                break
            # Regex match for YAML patterns
            if any(c in rule_sink for c in ('\\', '(?:', '[', '|', '(', '^', '$')):
                try:
                    # Try matching against the resolved sink name
                    if re.search(rule_sink, sink_name):
                        sink_match = True
                        break
                    # Also try matching against sink name with '()' appended
                    # (YAML patterns often use \.query\( which expects the call syntax)
                    if re.search(rule_sink, sink_name + '('):
                        sink_match = True
                        break
                    # Strip trailing \( from the pattern and try again
                    stripped = rule_sink.rstrip('\\(').rstrip('(')
                    if stripped != rule_sink and re.search(stripped, sink_name):
                        sink_match = True
                        break
                except re.error:
                    pass

        return source_match and sink_match

    def _render_taint_path(self, taint_info: TaintInfo, sink_name: str) -> str:
        """Render a human-readable taint path.

        Example: "request.args → user_input → query → cursor.execute"
        Example: "<param:user_id> → user_id → query → cursor.execute"
        """
        if taint_info.path:
            path = taint_info.path[:]
            # Clean up parameter source names for display
            cleaned = []
            for step in path:
                if step.startswith('<param:'):
                    # Extract param name
                    clean = step[7:].rstrip('>')
                    cleaned.append(clean)
                else:
                    cleaned.append(step)
            if sink_name not in cleaned:
                cleaned.append(sink_name)
            return " → ".join(cleaned)
        else:
            sources = list(taint_info.sources)
            source = sources[0] if sources else "unknown"
            # Clean parameter source name
            if source.startswith('<param:'):
                source = source[7:].rstrip('>')
            return f"{source} → {taint_info.var_name} → {sink_name}"

    def _compute_confidence(self, taint_info: TaintInfo, sink_name: str,
                            state: TaintState) -> float:
        """Compute confidence score for a finding.

        Confidence:
          0.95+ Direct source→sink, no sanitizer, same scope
          0.80+ Source→sink through function call, no sanitizer
          0.60+ Source→sink with partial sanitizer
          0.40+ Indirect taint, may be sanitized
        """
        if taint_info.is_sanitized:
            return 0.30

        # Direct source → sink (short path)
        if len(taint_info.path) <= 3:
            return 0.95

        # Through function call
        if len(taint_info.path) <= 5:
            return 0.85

        # Longer path
        if len(taint_info.path) <= 7:
            return 0.70

        # Very indirect
        return 0.50

    # ── Improvement 3 helpers: path-sensitive branch refinement ──────

    def _apply_branch_refinement(self, block: BasicBlock, state: TaintState,
                                  blocks: List[BasicBlock], visited: set,
                                  worklist: deque):
        """Apply path-sensitive refinement when propagating through a branch.

        When the branch condition references a variable whose taint status we
        track, we create *refined* copies of the outgoing state for each
        successor:

        * **then-branch** (condition is truthy):
          – If the condition variable is marked ``is_sanitized``, it stays
            sanitized (the branch confirms the sanitiser ran).
          – If the condition is ``not var`` and *var* is tainted, we keep
            the taint (the branch tells us var is falsy but still tainted).

        * **else-branch** (condition is falsy):
          – If the condition variable is marked ``is_sanitized``, we mark
            it as *not* sanitized on this path — the sanitiser did NOT run.
          – If the condition is ``not var`` and *var* is tainted, on this
            else-branch var IS truthy, which doesn't remove taint but is a
            genuine path distinction.

        Only simple conditions are handled (variable name, ``not var``,
        comparisons).  Complex conditions fall back to the default
        (lossy) merge.
        """
        cond = block.branch_condition
        if not cond or not block.successors:
            return

        # Parse the condition to extract the variable being tested
        # and whether the condition is negated.
        cond_var, is_negated = self._parse_branch_condition(cond)
        if not cond_var:
            return  # complex condition — skip refinement

        # Look up taint info for the condition variable in the current state
        var_info = state.get_taint_info(cond_var)
        if var_info is None:
            return  # variable not tracked — nothing to refine

        # We have at most 2 successors for a branch: then (index 0),
        # else (index 1).
        succ_count = len(block.successors)

        for idx, succ_id in enumerate(block.successors):
            if succ_id < 0 or succ_id >= len(blocks):
                continue
            succ = blocks[succ_id]

            # Create a refined copy of the state for this successor
            refined = state.copy()

            if idx == 0:
                # ── then-branch (condition is True) ──
                if is_negated:
                    # `if not var:` — on the then-branch var is falsy.
                    # If var was sanitized, this branch means it wasn't
                    # actually validated (e.g. sanitize returned None/empty).
                    if var_info.is_sanitized:
                        refined.remove_taint(cond_var, '<branch:then:not>')
                        # Un-sanitize: the branch tells us the sanitizer failed
                        if cond_var in refined.tainted:
                            refined.tainted[cond_var].is_sanitized = False
                            refined.tainted[cond_var].sanitized_by.discard('<branch:then:not>')
                else:
                    # `if var:` — on the then-branch var is truthy.
                    # If var was sanitized, confirm it stays sanitized.
                    # (No change needed — it's already sanitized.)
                    pass
            elif idx == 1:
                # ── else-branch (condition is False) ──
                if is_negated:
                    # `if not var:` — on the else-branch var is truthy.
                    # (No change needed for taint — truthy doesn't remove taint.)
                    pass
                else:
                    # `if var:` — on the else-branch var is falsy.
                    # If var was sanitized, this path means the sanitizer
                    # returned a falsy value (possibly failed), so we mark
                    # it as NOT sanitized on this path.
                    if var_info.is_sanitized:
                        # Shadow the parent info with an unsanitized copy
                        if cond_var in refined.tainted:
                            refined.tainted[cond_var].is_sanitized = False
                            # Keep sanitized_by for traceability but mark as
                            # "branch-override" — the sanitizer may not have
                            # run on this execution path.
                            refined.tainted[cond_var].sanitized_by.add(
                                '<branch:else:unsanitized>'
                            )

            # Store the refined state as the successor's taint_in
            # (merged with other predecessors later in the main loop)
            if succ.taint_in is None:
                succ.taint_in = refined
            else:
                succ.taint_in = succ.taint_in.merge(refined)

            # Add successor to worklist so refinement propagates
            if succ_id not in visited:
                worklist.append(succ_id)

    def _parse_branch_condition(self, cond: str) -> Tuple[Optional[str], bool]:
        """Parse a simple branch condition string.

        Returns:
            (variable_name, is_negated) or (None, False) for complex conditions.

        Handles:
            - ``var``             → ('var', False)
            - ``not var``         → ('var', True)
            - ``var != None``     → ('var', True)   (negated comparison)
            - ``var is not None`` → ('var', True)
            - ``var == None``     → ('var', False)  (truthy check inverted)
            - ``var is None``     → ('var', False)
        """
        cond = cond.strip()

        # `not var`
        m = re.match(r'^not\s+(\w+)$', cond)
        if m:
            return m.group(1), True

        # `var is not None`
        m = re.match(r'^(\w+)\s+is\s+not\s+None$', cond)
        if m:
            return m.group(1), False  # "is not None" ≈ truthy check

        # `var != None` / `var != None`
        m = re.match(r'^(\w+)\s*!=\s*None$', cond)
        if m:
            return m.group(1), False  # != None ≈ truthy check

        # `var is None`
        m = re.match(r'^(\w+)\s+is\s+None$', cond)
        if m:
            return m.group(1), True  # is None ≈ falsy ≈ negated

        # `var == None`
        m = re.match(r'^(\w+)\s*==\s*None$', cond)
        if m:
            return m.group(1), True  # == None ≈ falsy ≈ negated

        # Simple variable name
        m = re.match(r'^(\w+)$', cond)
        if m:
            return m.group(1), False

        # Comparison with a literal: var != "", var != 0, etc.
        m = re.match(r'^(\w+)\s*!=\s*["\']?["\']?\s*$', cond)
        if m:
            return m.group(1), False

        return None, False  # complex condition — no refinement

    def _states_equal(self, a: TaintState, b: TaintState) -> bool:
        """Check if two taint states are equal (for worklist convergence)."""
        if len(a.tainted) != len(b.tainted):
            return False
        for var, info in a.tainted.items():
            other = b.tainted.get(var)
            if not other:
                return False
            if info.sources != other.sources:
                return False
            if info.is_sanitized != other.is_sanitized:
                return False
        return True

    def _finding_to_dict(self, finding: TaintFinding) -> Dict:
        """Convert a TaintFinding to a dict compatible with semantic_engine format."""
        # Map confidence float to string
        if finding.confidence >= 0.90:
            confidence_str = "high"
        elif finding.confidence >= 0.70:
            confidence_str = "medium"
        elif finding.confidence >= 0.50:
            confidence_str = "low"
        else:
            confidence_str = "info"

        return {
            "rule_id": finding.rule_id,
            "rule_name": finding.rule_name,
            "severity": finding.severity,
            "cwe": finding.cwe,
            "message": finding.message,
            "file": finding.file,
            "line": finding.line,
            "source": finding.source,
            "sink": finding.sink,
            "tainted_variable": finding.tainted_variable,
            "sanitized": finding.sanitized,
            "sanitizers_found": finding.sanitizers_found,
            "confidence": confidence_str,
            "confidence_score": round(finding.confidence, 2),
            "taint_path": finding.taint_path,
            "engine": "ast_taint",
        }

    # ─── Regex Fallback ───────────────────────────────────────

    def _analyze_with_regex(self, file_path: str, content: str,
                             language: str, rules: List[Dict]) -> List[Dict]:
        """Fallback regex-based analysis when tree-sitter is not available.

        This delegates to the existing semantic_engine.py TaintAnalyzer.
        """
        try:
            from semantic_engine import TaintAnalyzer
            analyzer = TaintAnalyzer(rules, language=language)
            return analyzer.analyze_file(file_path)
        except ImportError:
            # Ultimate fallback: simple line-by-line analysis
            return self._simple_regex_analysis(file_path, content, language, rules)

    def _simple_regex_analysis(self, file_path: str, content: str,
                                language: str, rules: List[Dict]) -> List[Dict]:
        """Simplest regex-based taint analysis fallback."""
        findings = []
        lines = content.split('\n')
        tainted_vars: Dict[str, str] = {}

        # Determine source/sink patterns based on language
        if language == 'python':
            source_set = PYTHON_SOURCES
            sink_set = PYTHON_SINKS
            sanitizer_set = PYTHON_SANITIZERS
        else:
            source_set = JS_SOURCES
            sink_set = JS_SINKS
            sanitizer_set = JS_SANITIZERS

        # Phase 1: Find tainted variables
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            if language == 'python' and stripped.startswith('#'):
                continue
            if language in ('javascript', 'typescript') and (stripped.startswith('//') or stripped.startswith('*')):
                continue

            for source in source_set:
                src_name = source.split('.')[-1]
                if source in stripped or src_name in stripped:
                    import re
                    if language == 'python':
                        m = re.match(r'(\w+)\s*=\s*', stripped)
                    else:
                        m = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*', stripped)
                    if m:
                        tainted_vars[m.group(1)] = source

        # Phase 2: Check sinks
        for line_no, line in enumerate(lines, 1):
            stripped = line.strip()
            for sink in sink_set:
                sink_name = sink.split('.')[-1]
                if sink in stripped or sink_name + '(' in stripped:
                    for var, src in tainted_vars.items():
                        if var in stripped:
                            findings.append({
                                "rule_id": "taint-detected",
                                "rule_name": "Taint Vulnerability",
                                "severity": "high",
                                "cwe": "",
                                "message": f"User input flows from {src} to {sink_name}",
                                "file": file_path,
                                "line": line_no,
                                "source": src,
                                "sink": sink_name,
                                "tainted_variable": var,
                                "sanitized": False,
                                "sanitizers_found": [],
                                "confidence": "low",
                                "taint_path": f"{src} → {var} → {sink_name}",
                                "engine": "ast_taint_regex_fallback",
                            })

        return findings

    # ─── Workspace Analysis ───────────────────────────────────

    def analyze_workspace(self, workspace: str, rules_dir: str = None,
                          language: str = None) -> Dict[str, Any]:
        """Run taint analysis across an entire workspace.

        Args:
            workspace: Path to workspace root.
            rules_dir: Directory containing YAML rule files.
            language: Filter to a specific language.

        Returns:
            Dict with status, findings, stats, and recommendations.
        """
        workspace = os.path.abspath(workspace)
        start_time = time.time()

        # Load rules
        rules = self._load_rules(rules_dir)
        if not rules:
            return {
                "status": "ok",
                "total_findings": 0,
                "findings": [],
                "stats": {"rules_loaded": 0, "engine": "ast_taint"},
                "hint": "No security rules found. Add YAML rule files to scripts/rules/.",
                "engine": "ast_taint",
            }

        # Determine languages
        languages = [language] if language else self._detect_languages(workspace)

        all_findings = []
        files_analyzed = 0
        treesitter_used = 0
        regex_fallback = 0

        for lang in languages:
            lang_rules = [r for r in rules if r.get('language', '').lower() == lang.lower()]
            if not lang_rules:
                continue

            source_files = self._find_source_files(workspace, lang)

            for fpath in source_files:
                content = safe_read_file(fpath)
                if content is None:
                    continue

                files_analyzed += 1
                analyzer = ASTTaintAnalyzer(rules=lang_rules, language=lang)
                findings = analyzer.analyze_file(fpath, content=content,
                                                  language=lang, rules=lang_rules)

                # Track which engine was used
                if findings and findings[0].get('engine') == 'ast_taint':
                    treesitter_used += 1
                else:
                    regex_fallback += 1

                all_findings.extend(findings)

                # Time budget check
                if time.time() - start_time > 120:
                    logger.warning("Taint analysis time budget expired")
                    break

        # Deduplicate
        seen = set()
        unique_findings = []
        for f in all_findings:
            key = (f.get('file', ''), f.get('line', 0), f.get('rule_id', ''),
                   f.get('tainted_variable', ''))
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        unique_findings.sort(
            key=lambda f: severity_order.get(f.get("severity", "medium"), 99)
        )

        # Compute stats
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        by_rule = {}
        for f in unique_findings:
            sev = f.get("severity", "medium")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            rule_name = f.get("rule_name", "unknown")
            by_rule[rule_name] = by_rule.get(rule_name, 0) + 1

        risk = "critical" if by_severity.get("critical", 0) > 0 else \
               "high" if by_severity.get("high", 0) > 0 else \
               "medium" if by_severity.get("medium", 0) > 0 else "low"

        elapsed = time.time() - start_time

        return {
            "status": "ok",
            "risk": risk,
            "total_findings": len(unique_findings),
            "findings": unique_findings,
            "stats": {
                "files_analyzed": files_analyzed,
                "rules_loaded": len(rules),
                "languages_analyzed": languages,
                "by_severity": by_severity,
                "by_rule": by_rule,
                "treesitter_used": treesitter_used,
                "regex_fallback": regex_fallback,
                "engine": "ast_taint",
            },
            "elapsed_seconds": round(elapsed, 2),
            "treesitter_available": TREE_SITTER_AVAILABLE,
            "recommendations": self._generate_recommendations(unique_findings),
            "engine": "ast_taint",
        }

    def _load_rules(self, rules_dir: str = None) -> List[Dict]:
        """Load all YAML rule files from the rules directory."""
        if rules_dir is None:
            rules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")

        rules = []
        if not os.path.isdir(rules_dir):
            return rules

        for fname in sorted(os.listdir(rules_dir)):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(rules_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and 'rules' in data:
                    for rule in data['rules']:
                        rule['_source_file'] = fname
                        rules.append(rule)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            # JS rules are in list format
                            rule = {
                                'id': item.get('rule', 'unknown'),
                                'name': item.get('rule', 'Unknown'),
                                'language': item.get('language', 'javascript'),
                                'severity': item.get('severity', 'medium'),
                                'cwe': item.get('cwe', ''),
                                'message': item.get('message', ''),
                                'sources': item.get('sources', []),
                                'sinks': item.get('sinks', []),
                                'sanitizers': item.get('sanitizers', []),
                                '_source_file': fname,
                            }
                            rules.append(rule)
            except Exception as e:
                logger.warning(f"Failed to load rule file {fname}: {e}")

        return rules

    def _detect_languages(self, workspace: str) -> List[str]:
        """Detect programming languages present in the workspace."""
        lang_markers = {
            "python": {'.py', 'requirements.txt', 'pyproject.toml', 'setup.py'},
            "javascript": {'.js', '.mjs', '.cjs', 'package.json'},
            "typescript": {'.ts', '.tsx', 'tsconfig.json'},
        }
        found = []
        for lang, markers in lang_markers.items():
            for root, dirs, files in os.walk(workspace):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
                for f in files:
                    for marker in markers:
                        if marker.startswith('.') and f.endswith(marker):
                            found.append(lang)
                            break
                        elif not marker.startswith('.') and f == marker:
                            found.append(lang)
                            break
                if lang in found:
                    break
        return found if found else ["python"]

    def _find_source_files(self, workspace: str, language: str) -> List[str]:
        """Find all source files of a given language in the workspace."""
        ext_map = {
            "python": {'.py', '.pyi'},
            "javascript": {'.js', '.mjs', '.cjs'},
            "typescript": {'.ts', '.tsx'},
        }
        extensions = ext_map.get(language, {'.py'})
        source_files = []

        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in DEFAULT_IGNORE_DIRS]
            if '.codelens' in root:
                dirs.clear()
                continue

            rel_root = os.path.relpath(root, workspace)
            if should_ignore_dir(rel_root):
                dirs.clear()
                continue

            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    # Skip minified files
                    if '.min.js' in f or '.min.css' in f:
                        continue
                    source_files.append(os.path.join(root, f))

        return source_files

    def _generate_recommendations(self, findings: List[Dict]) -> List[str]:
        """Generate actionable recommendations from findings."""
        if not findings:
            return ["No taint vulnerabilities detected by AST analysis."]

        recs = []
        critical = [f for f in findings if f.get("severity") == "critical"]
        if critical:
            recs.append(f"URGENT: {len(critical)} critical vulnerabilities found — fix immediately")
            for c in critical[:3]:
                recs.append(
                    f"  → {c['rule_name']}: {c.get('taint_path', 'N/A')} "
                    f"in {os.path.basename(c['file'])}:{c['line']}"
                )

        high = [f for f in findings if f.get("severity") == "high"]
        if high:
            recs.append(f"HIGH: {len(high)} high-severity issues — review and fix soon")

        unsanitized = [f for f in findings if not f.get("sanitized")]
        if unsanitized:
            recs.append(f"{len(unsanitized)} unsanitized taint paths — add input validation/sanitization")

        ast_findings = [f for f in findings if f.get("engine") == "ast_taint"]
        if ast_findings:
            recs.append(f"AST engine found {len(ast_findings)} findings with path-sensitive analysis")

        return recs[:10]


# ─── Public API ───────────────────────────────────────────────

def analyze_file(file_path: str, content: str = None,
                 language: str = 'python', rules: List[Dict] = None) -> List[Dict]:
    """Convenience function to analyze a single file."""
    analyzer = ASTTaintAnalyzer(rules=rules, language=language)
    return analyzer.analyze_file(file_path, content=content,
                                  language=language, rules=rules)


def analyze_workspace(workspace: str, rules_dir: str = None,
                      language: str = None) -> Dict[str, Any]:
    """Convenience function to analyze an entire workspace."""
    analyzer = ASTTaintAnalyzer()
    return analyzer.analyze_workspace(workspace, rules_dir=rules_dir,
                                      language=language)


def is_available() -> bool:
    """Check if the AST taint engine (with tree-sitter) is available."""
    return TREE_SITTER_AVAILABLE


def get_supported_languages() -> List[str]:
    """Get list of languages supported by the AST taint engine."""
    if not TREE_SITTER_AVAILABLE:
        return []
    supported = []
    for lang in ('python', 'javascript', 'typescript', 'tsx'):
        if _get_parser(lang):
            supported.append(lang)
    return supported
