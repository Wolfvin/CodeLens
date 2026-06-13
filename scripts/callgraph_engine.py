"""
Enhanced Cross-File Dataflow Engine with Real Call Graph Resolution — v1

Builds a workspace-wide call graph using tree-sitter AST parsing, resolves
cross-file calls through import analysis, constructs a data flow graph that
connects per-file taint results, and performs inter-procedural taint propagation
across file boundaries.

Key Improvements over crossfile_taint_engine.py (regex-based):
1. Tree-sitter AST parsing — no regex false positives for function/method extraction
2. Proper class method resolution — handles self.method(), ClassName.method()
3. Full import resolution — from X import Y, import X, re-exports in __init__.py
4. Data Flow Graph — connects variable taint states across files
5. Inter-procedural taint propagation — tracks taint through function params and return values
6. Callback/higher-order function support — best-effort tracking

Architecture:
  Phase 1: Parse every source file with tree-sitter → extract FunctionDefs + CallSites
  Phase 2: Resolve imports for each file → build per-file ImportMaps
  Phase 3: Resolve call sites using ImportMaps → build CallGraph with caller→callee edges
  Phase 4: Run per-file taint analysis (using ast_taint_engine or built-in)
  Phase 5: Build Data Flow Graph from call graph + per-file taint results
  Phase 6: Propagate taint across file boundaries via call graph edges
  Phase 7: Generate cross-file findings with full taint paths

Performance:
  - Lazy parsing (tree-sitter parsers cached per language)
  - Import resolution cached per file
  - Time budget: configurable (default 120s)
  - Max files: configurable (default 3000)
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

# Lazy parser cache
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


def _detect_language(file_path: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    lang_map = {
        '.py': 'python', '.pyi': 'python',
        '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript', '.tsx': 'tsx',
    }
    return lang_map.get(ext)


# ─── Data Structures ─────────────────────────────────────────

@dataclass
class FunctionDef:
    """Represents a function/method definition extracted from AST."""
    qualified_name: str        # e.g., "utils.helper" or "module.ClassName.method"
    file_path: str             # relative path from workspace root
    line: int                  # line number of definition
    params: List[str]          # parameter names
    return_type: Optional[str] = None  # return type annotation if present
    is_method: bool = False    # True if this is a class method
    class_name: Optional[str] = None   # Enclosing class name
    is_async: bool = False     # True if async def
    is_static: bool = False    # True if @staticmethod
    is_classmethod: bool = False  # True if @classmethod
    decorators: List[str] = field(default_factory=list)

    @property
    def short_name(self) -> str:
        """Last component of qualified name."""
        return self.qualified_name.rsplit('.', 1)[-1]

    @property
    def module_name(self) -> str:
        """Module path portion (file path without extension)."""
        return os.path.splitext(self.file_path)[0].replace(os.sep, '.')


@dataclass
class CallSite:
    """Represents a function/method call in the source code."""
    caller_function: str       # qualified name of the containing function (or "module")
    callee_name: str           # name as written in source (e.g., "helper" or "obj.method")
    arguments: List[str]       # argument expressions (variable names)
    line: int                  # line number of call
    file_path: str             # relative path of the file
    resolved_target: Optional[str] = None  # resolved qualified name after import resolution
    is_method_call: bool = False   # True if obj.method() style
    receiver_expr: Optional[str] = None  # e.g., "self", "db", "cursor"
    call_type: str = "direct"  # "direct", "method", "constructor", "callback", "dynamic"

    @property
    def is_cross_file(self) -> bool:
        """Check if this call resolves to a different file."""
        if not self.resolved_target:
            return False
        # The resolved target includes the module path
        return True  # Will be determined during resolution


@dataclass
class CallEdge:
    """A directed edge in the call graph: caller → callee."""
    caller: str          # qualified name of caller function
    callee: str          # qualified name of callee function
    file_path: str       # file where the call occurs
    line: int            # line number of call
    call_type: str = "direct"  # "direct", "method", "callback", "dynamic"
    arguments: List[str] = field(default_factory=list)  # argument expressions
    confidence: float = 1.0  # 1.0 for fully resolved, lower for heuristics

    def __hash__(self):
        return hash((self.caller, self.callee, self.file_path, self.line))

    def __eq__(self, other):
        if not isinstance(other, CallEdge):
            return False
        return (self.caller == other.caller and self.callee == other.callee
                and self.file_path == other.file_path and self.line == other.line)


@dataclass
class ImportInfo:
    """Information about a single import statement."""
    local_name: str       # name used in this file
    module_path: str      # module being imported from
    imported_name: str    # name being imported
    is_from_import: bool  # True for "from X import Y"
    line: int             # line number
    is_star: bool = False  # True for "from X import *"

    @property
    def qualified_name(self) -> str:
        """Fully qualified name of the imported symbol."""
        if self.is_from_import:
            return f"{self.module_path}.{self.imported_name}"
        return self.module_path


@dataclass
class ImportMap:
    """Import resolution for a single file."""
    file_path: str
    imports: Dict[str, str] = field(default_factory=dict)      # local_name → qualified_name
    from_imports: Dict[str, str] = field(default_factory=dict)  # local_name → module.function
    module_imports: Dict[str, str] = field(default_factory=dict)  # local_name → module_path
    star_imports: List[str] = field(default_factory=list)        # modules with "from X import *"
    re_exports: Dict[str, str] = field(default_factory=dict)     # re-exported names local→qualified
    all_imports: List[ImportInfo] = field(default_factory=list)  # all parsed import info

    def resolve(self, name: str) -> Optional[str]:
        """Resolve a local name to its fully qualified name.

        Priority: from_imports > imports > module_imports > star_imports
        """
        # Direct from-import: from module import func → module.func
        if name in self.from_imports:
            return self.from_imports[name]

        # Direct import: import module → module
        if name in self.imports:
            return self.imports[name]

        # Module import: import module as alias → module
        if name in self.module_imports:
            return self.module_imports[name]

        # Re-export: from .utils import helper (in __init__.py)
        if name in self.re_exports:
            return self.re_exports[name]

        return None

    def resolve_attribute(self, obj_name: str, attr_name: str) -> Optional[str]:
        """Resolve obj.attr to a fully qualified name.

        E.g., module.method() where module was imported → module.method
        """
        # Check if obj_name is an imported module
        if obj_name in self.module_imports:
            return f"{self.module_imports[obj_name]}.{attr_name}"

        if obj_name in self.imports:
            return f"{self.imports[obj_name]}.{attr_name}"

        # Check if obj_name is a from-import (e.g., from package import Module)
        if obj_name in self.from_imports:
            return f"{self.from_imports[obj_name]}.{attr_name}"

        return None


@dataclass
class CallGraph:
    """The workspace-wide call graph."""
    functions: Dict[str, FunctionDef] = field(default_factory=dict)  # qualified_name → FunctionDef
    edges: List[CallEdge] = field(default_factory=list)              # caller→callee edges
    import_map: Dict[str, ImportMap] = field(default_factory=dict)   # file_path → ImportMap
    file_functions: Dict[str, List[str]] = field(default_factory=dict)  # file_path → [qualified_names]
    unresolved_calls: List[CallSite] = field(default_factory=list)   # calls that couldn't be resolved
    class_methods: Dict[str, Dict[str, str]] = field(default_factory=dict)  # class_name → {method: qname}
    _edge_index: Dict[str, List[CallEdge]] = field(default_factory=lambda: defaultdict(list))
    _callee_index: Dict[str, List[CallEdge]] = field(default_factory=lambda: defaultdict(list))

    def add_function(self, func_def: FunctionDef):
        """Register a function definition."""
        self.functions[func_def.qualified_name] = func_def
        if func_def.file_path not in self.file_functions:
            self.file_functions[func_def.file_path] = []
        if func_def.qualified_name not in self.file_functions[func_def.file_path]:
            self.file_functions[func_def.file_path].append(func_def.qualified_name)

        # Track class methods
        if func_def.is_method and func_def.class_name:
            cls_key = f"{func_def.file_path}:{func_def.class_name}"
            if cls_key not in self.class_methods:
                self.class_methods[cls_key] = {}
            self.class_methods[cls_key][func_def.short_name] = func_def.qualified_name

    def add_edge(self, edge: CallEdge):
        """Add a call graph edge."""
        self.edges.append(edge)
        self._edge_index[edge.caller].append(edge)
        self._callee_index[edge.callee].append(edge)

    def get_callees(self, caller: str) -> List[CallEdge]:
        """Get all edges where the given function is the caller."""
        return self._edge_index.get(caller, [])

    def get_callers(self, callee: str) -> List[CallEdge]:
        """Get all edges where the given function is the callee (reverse lookup)."""
        return self._callee_index.get(callee, [])

    def resolve_function(self, name: str, context_file: str = None) -> Optional[FunctionDef]:
        """Resolve a function name to its definition.

        Priority:
        1. Exact qualified name match
        2. File-local match (same file)
        3. Cross-file match by short name
        """
        # Exact match
        if name in self.functions:
            return self.functions[name]

        # File-local match
        if context_file:
            local_funcs = self.file_functions.get(context_file, [])
            for qname in local_funcs:
                if qname.split('.')[-1] == name or qname == name:
                    return self.functions.get(qname)

        # Global short-name match
        for qname, fdef in self.functions.items():
            if fdef.short_name == name:
                return fdef

        return None

    def resolve_method(self, class_name: str, method_name: str,
                       context_file: str = None) -> Optional[FunctionDef]:
        """Resolve a class method to its definition."""
        # Try exact class match in context file
        if context_file:
            cls_key = f"{context_file}:{class_name}"
            methods = self.class_methods.get(cls_key, {})
            if method_name in methods:
                qname = methods[method_name]
                return self.functions.get(qname)

        # Search all files for the class
        for cls_key, methods in self.class_methods.items():
            if cls_key.split(':')[-1] == class_name and method_name in methods:
                qname = methods[method_name]
                return self.functions.get(qname)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get call graph statistics."""
        cross_file_edges = sum(1 for e in self.edges
                               if e.caller and e.callee
                               and any(c in e.caller for c in ':/')
                               and any(c in e.callee for c in ':/'))
        return {
            "total_functions": len(self.functions),
            "total_edges": len(self.edges),
            "cross_file_edges": cross_file_edges,
            "unresolved_calls": len(self.unresolved_calls),
            "files_indexed": len(self.file_functions),
            "classes_found": len(self.class_methods),
            "total_imports": sum(len(im.all_imports) for im in self.import_map.values()),
        }


# ─── Data Flow Graph Structures ──────────────────────────────

@dataclass
class DataFlowNode:
    """A node in the data flow graph — a variable with its taint status."""
    var_name: str           # variable name
    file_path: str          # source file
    function_name: str      # containing function (or "module")
    line: int               # line number
    is_tainted: bool = False
    taint_sources: Set[str] = field(default_factory=set)  # set of source names
    taint_path: List[str] = field(default_factory=list)    # chain of variable names
    is_sanitized: bool = False
    sanitizers: Set[str] = field(default_factory=set)
    confidence: float = 0.0

    @property
    def node_id(self) -> str:
        return f"{self.file_path}:{self.function_name}:{self.var_name}:{self.line}"


@dataclass
class DataFlowEdge:
    """An edge in the data flow graph — data flows from source to target."""
    source_id: str      # DataFlowNode.node_id of source
    target_id: str      # DataFlowNode.node_id of target
    flow_type: str      # "assignment", "parameter", "return", "class_attr", "callback"
    file_path: str      # file where the flow occurs
    line: int           # line number
    is_cross_file: bool = False
    detail: str = ""    # additional context


@dataclass
class DataFlowGraph:
    """Workspace-wide data flow graph connecting taint states across files."""
    nodes: Dict[str, DataFlowNode] = field(default_factory=dict)  # node_id → DataFlowNode
    edges: List[DataFlowEdge] = field(default_factory=list)
    _adjacency: Dict[str, List[DataFlowEdge]] = field(default_factory=lambda: defaultdict(list))
    _reverse_adjacency: Dict[str, List[DataFlowEdge]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, node: DataFlowNode):
        """Add a data flow node."""
        self.nodes[node.node_id] = node

    def add_edge(self, edge: DataFlowEdge):
        """Add a data flow edge."""
        self.edges.append(edge)
        self._adjacency[edge.source_id].append(edge)
        self._reverse_adjacency[edge.target_id].append(edge)

    def get_successors(self, node_id: str) -> List[DataFlowEdge]:
        """Get all edges flowing from a node."""
        return self._adjacency.get(node_id, [])

    def get_predecessors(self, node_id: str) -> List[DataFlowEdge]:
        """Get all edges flowing into a node."""
        return self._reverse_adjacency.get(node_id, [])

    def get_tainted_nodes(self) -> List[DataFlowNode]:
        """Get all tainted nodes."""
        return [n for n in self.nodes.values() if n.is_tainted]

    def get_cross_file_edges(self) -> List[DataFlowEdge]:
        """Get all edges that cross file boundaries."""
        return [e for e in self.edges if e.is_cross_file]

    def find_taint_paths(self, source_id: str, sink_id: str,
                         max_depth: int = 20) -> List[List[DataFlowEdge]]:
        """Find all taint propagation paths from source to sink.

        Uses BFS with path tracking to find all paths up to max_depth.
        """
        if source_id not in self.nodes or sink_id not in self.nodes:
            return []

        paths = []
        queue: deque = deque()
        queue.append((source_id, []))
        visited_in_path = set()

        while queue:
            current_id, path = queue.popleft()

            if len(path) > max_depth:
                continue

            if current_id == sink_id:
                paths.append(list(path))
                continue

            # Prevent cycles
            path_key = (current_id, len(path))
            if path_key in visited_in_path:
                continue
            visited_in_path.add(path_key)

            for edge in self.get_successors(current_id):
                # Only follow edges that propagate taint
                source_node = self.nodes.get(edge.source_id)
                if source_node and source_node.is_tainted:
                    new_path = path + [edge]
                    queue.append((edge.target_id, new_path))

        return paths


# ─── Call Graph Builder ──────────────────────────────────────

class CallGraphBuilder:
    """Builds a workspace-wide call graph from tree-sitter ASTs.

    Parses every source file, extracts function definitions and call sites,
    resolves imports, and connects callers to callees.
    """

    # Python built-ins and common library functions to skip
    PYTHON_BUILTINS = frozenset({
        'print', 'len', 'range', 'str', 'int', 'float', 'list', 'dict',
        'set', 'tuple', 'bool', 'type', 'isinstance', 'issubclass',
        'hasattr', 'getattr', 'setattr', 'delattr', 'super', 'property',
        'staticmethod', 'classmethod', 'enumerate', 'zip', 'map', 'filter',
        'sorted', 'reversed', 'iter', 'next', 'abs', 'max', 'min', 'sum',
        'any', 'all', 'open', 'id', 'hash', 'repr', 'format', 'vars',
        'dir', 'help', 'input', 'ord', 'chr', 'hex', 'oct', 'bin',
        'round', 'pow', 'divmod', 'complex', 'bytearray', 'bytes',
        'memoryview', 'frozenset', 'slice', 'object', 'Exception',
        'ValueError', 'TypeError', 'KeyError', 'IndexError', 'AttributeError',
        'RuntimeError', 'StopIteration', 'NotImplementedError',
    })

    # JavaScript built-ins to skip
    JS_BUILTINS = frozenset({
        'console', 'require', 'typeof', 'parseInt', 'parseFloat',
        'String', 'Number', 'Boolean', 'Array', 'Object', 'Math',
        'JSON', 'Promise', 'Symbol', 'Map', 'Set', 'WeakMap', 'WeakSet',
        'Date', 'RegExp', 'Error', 'TypeError', 'RangeError',
        'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
        'process', 'Buffer', 'undefined', 'NaN', 'Infinity',
    })

    # File extensions by language
    LANG_EXTENSIONS = {
        'python': {'.py', '.pyi'},
        'javascript': {'.js', '.mjs', '.cjs', '.jsx'},
        'typescript': {'.ts'},
        'tsx': {'.tsx'},
    }

    def __init__(self, max_files: int = 3000, timeout_sec: float = 120.0):
        self.max_files = max_files
        self.timeout_sec = timeout_sec
        self._start_time = 0.0
        self._files_parsed = 0

    def build(self, workspace: str, languages: List[str] = None,
              source_files: List[str] = None) -> CallGraph:
        """Build call graph from source files in the workspace.

        Args:
            workspace: Absolute path to workspace root.
            languages: List of languages to parse. None = auto-detect.
            source_files: Explicit list of files. None = discover automatically.

        Returns:
            CallGraph with all functions, edges, and import maps.
        """
        workspace = os.path.abspath(workspace)
        self._start_time = time.time()
        self._files_parsed = 0
        cg = CallGraph()

        # Discover source files
        if source_files is None:
            source_files = self._find_source_files(workspace, languages)

        if not source_files:
            logger.info("[CallGraph] No source files found")
            return cg

        logger.info(f"[CallGraph] Processing {len(source_files)} files...")

        # Phase 1: Parse imports and function definitions for each file
        for fpath in source_files:
            if self._timed_out():
                logger.warning("[CallGraph] Time budget expired during Phase 1")
                break

            content = safe_read_file(fpath)
            if content is None:
                continue

            rel_path = os.path.relpath(fpath, workspace)
            lang = _detect_language(fpath)
            if not lang:
                continue

            # Parse imports
            import_map = self._resolve_imports(fpath, content, lang, workspace)
            cg.import_map[rel_path] = import_map

            # Parse function definitions
            func_defs = self._parse_file_definitions(fpath, content, lang, workspace)
            for fdef in func_defs:
                cg.add_function(fdef)

            self._files_parsed += 1

        # Phase 2: Handle __init__.py re-exports
        self._resolve_re_exports(cg, workspace)

        logger.info(f"[CallGraph] Phase 1 complete: {len(cg.functions)} functions, "
                     f"{len(cg.import_map)} files with imports")

        # Phase 3: Parse call sites and resolve targets
        for fpath in source_files:
            if self._timed_out():
                logger.warning("[CallGraph] Time budget expired during Phase 3")
                break

            content = safe_read_file(fpath)
            if content is None:
                continue

            rel_path = os.path.relpath(fpath, workspace)
            lang = _detect_language(fpath)
            if not lang:
                continue

            import_map = cg.import_map.get(rel_path)
            call_sites = self._parse_file_calls(fpath, content, lang, workspace)

            # Resolve each call site
            for cs in call_sites:
                resolved = self._resolve_call(cs, import_map, cg, workspace)
                cs.resolved_target = resolved

                if resolved and resolved in cg.functions:
                    # Determine caller qualified name
                    caller_qname = cs.caller_function
                    # Try to find the actual FunctionDef for the caller
                    if caller_qname == "module":
                        caller_qname = f"{rel_path}:<module>"

                    edge = CallEdge(
                        caller=caller_qname,
                        callee=resolved,
                        file_path=rel_path,
                        line=cs.line,
                        call_type=cs.call_type,
                        arguments=cs.arguments,
                        confidence=1.0 if cs.call_type == "direct" else 0.7,
                    )
                    cg.add_edge(edge)
                else:
                    # Unresolved call
                    cg.unresolved_calls.append(cs)

        stats = cg.get_stats()
        logger.info(f"[CallGraph] Build complete: {stats['total_functions']} functions, "
                     f"{stats['total_edges']} edges, {stats['unresolved_calls']} unresolved")

        return cg

    def _find_source_files(self, workspace: str,
                           languages: List[str] = None) -> List[str]:
        """Discover source files in the workspace."""
        extensions = set()
        if languages:
            for lang in languages:
                extensions |= self.LANG_EXTENSIONS.get(lang, set())
        else:
            for exts in self.LANG_EXTENSIONS.values():
                extensions |= exts

        source_files = []
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs
                       if not d.startswith('.')
                       and d not in DEFAULT_IGNORE_DIRS
                       and d not in ('node_modules', '__pycache__', '.codelens',
                                     'venv', '.venv', 'env', '.git', 'dist',
                                     'build', 'target', '.tox', '.mypy_cache')]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in extensions:
                    fpath = os.path.join(root, fname)
                    try:
                        if os.path.getsize(fpath) <= 200 * 1024:  # Skip files > 200KB
                            source_files.append(fpath)
                    except OSError:
                        continue

                if self.max_files and len(source_files) >= self.max_files:
                    return source_files

        return source_files

    def _parse_file_definitions(self, file_path: str, content: str,
                                 language: str, workspace: str) -> List[FunctionDef]:
        """Parse a file and extract all function/method definitions.

        Uses tree-sitter for accurate AST-level extraction.
        Falls back to regex if tree-sitter is unavailable.
        """
        rel_path = os.path.relpath(file_path, workspace)
        parser = _get_parser(language)

        if parser and TREE_SITTER_AVAILABLE:
            return self._parse_definitions_treesitter(rel_path, content, language, parser)
        else:
            return self._parse_definitions_regex(rel_path, content, language)

    def _parse_definitions_treesitter(self, rel_path: str, content: str,
                                       language: str, parser) -> List[FunctionDef]:
        """Extract function definitions using tree-sitter AST."""
        defs = []

        try:
            tree = parser.parse(content.encode('utf-8'))
            if not tree or not tree.root_node:
                return self._parse_definitions_regex(rel_path, content, language)
        except Exception:
            return self._parse_definitions_regex(rel_path, content, language)

        # Track class scope for method resolution
        class_stack: List[str] = []
        decorator_stack: List[List[str]] = []

        def _walk(node, scope_prefix: str = ""):
            nonlocal class_stack, decorator_stack

            if language == 'python':
                # Python function definition
                if node.type == 'function_definition':
                    name_node = node.child_by_field_name('name')
                    params_node = node.child_by_field_name('parameters')
                    return_type_node = node.child_by_field_name('return_type')

                    if not name_node:
                        return

                    name = content[name_node.start_byte:name_node.end_byte]
                    params = self._extract_python_params(params_node, content)
                    ret_type = None
                    if return_type_node:
                        ret_type = content[return_type_node.start_byte:return_type_node.end_byte]

                    # Build qualified name
                    if class_stack:
                        qname = f"{rel_path}:{class_stack[-1]}.{name}"
                        is_method = True
                        class_name = class_stack[-1]
                    else:
                        qname = f"{rel_path}:{name}"
                        is_method = False
                        class_name = None

                    # Check decorators
                    is_static = False
                    is_classmethod = False
                    decorators = []
                    for child in node.children:
                        if child.type == 'decorator':
                            dec_text = content[child.start_byte:child.end_byte].strip()
                            decorators.append(dec_text)
                            if '@staticmethod' in dec_text:
                                is_static = True
                            elif '@classmethod' in dec_text:
                                is_classmethod = True

                    # Check for async
                    is_async = False
                    for child in node.children:
                        if child.type == 'async':
                            is_async = True
                            break

                    fdef = FunctionDef(
                        qualified_name=qname,
                        file_path=rel_path,
                        line=name_node.start_point[0] + 1,
                        params=params,
                        return_type=ret_type,
                        is_method=is_method,
                        class_name=class_name,
                        is_async=is_async,
                        is_static=is_static,
                        is_classmethod=is_classmethod,
                        decorators=decorators,
                    )
                    defs.append(fdef)

                    # Recurse into function body for nested functions
                    body_node = node.child_by_field_name('body')
                    if body_node:
                        _walk(body_node, f"{scope_prefix}.{name}" if scope_prefix else name)

                # Python class definition
                elif node.type == 'class_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        class_name = content[name_node.start_byte:name_node.end_byte]
                        class_stack.append(class_name)
                        # Walk children (methods)
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            for child in body_node.children:
                                _walk(child, f"{scope_prefix}.{class_name}" if scope_prefix else class_name)
                        class_stack.pop()

                else:
                    # Recurse into children
                    for child in node.children:
                        _walk(child, scope_prefix)

            elif language in ('javascript', 'typescript', 'tsx'):
                # JavaScript/TypeScript function declaration
                if node.type == 'function_declaration':
                    name_node = node.child_by_field_name('name')
                    params_node = node.child_by_field_name('parameters')

                    if not name_node:
                        return

                    name = content[name_node.start_byte:name_node.end_byte]
                    params = self._extract_js_params(params_node, content)

                    qname = f"{rel_path}:{name}"
                    is_async = any(c.type == 'async' for c in node.children)

                    fdef = FunctionDef(
                        qualified_name=qname,
                        file_path=rel_path,
                        line=name_node.start_point[0] + 1,
                        params=params,
                        is_async=is_async,
                    )
                    defs.append(fdef)

                    # Recurse for nested functions
                    body_node = node.child_by_field_name('body')
                    if body_node:
                        for child in body_node.children:
                            _walk(child, scope_prefix)

                # Arrow function with name: const name = () => {}
                elif node.type == 'variable_declarator':
                    name_node = node.child_by_field_name('name')
                    value_node = node.child_by_field_name('value')

                    if name_node and value_node:
                        # Skip require() calls — they're imports, not functions
                        is_require = False
                        if value_node.type == 'call_expression':
                            func_node = value_node.child_by_field_name('function')
                            if func_node and func_node.type == 'identifier':
                                func_name = content[func_node.start_byte:func_node.end_byte]
                                if func_name == 'require':
                                    is_require = True

                        # Skip object_pattern (destructuring import)
                        # e.g., const { queryUser } = require('./db')
                        if name_node.type == 'object_pattern':
                            is_require = True

                        if not is_require and value_node.type in (
                            'arrow_function', 'function_expression'
                        ):
                            name = content[name_node.start_byte:name_node.end_byte]
                            params = []
                            params_node = value_node.child_by_field_name('parameters')
                            params = self._extract_js_params(params_node, content)

                            qname = f"{rel_path}:{name}"
                            fdef = FunctionDef(
                                qualified_name=qname,
                                file_path=rel_path,
                                line=name_node.start_point[0] + 1,
                                params=params,
                            )
                            defs.append(fdef)

                # Method definition in class
                elif node.type == 'method_definition':
                    name_node = node.child_by_field_name('name')
                    params_node = node.child_by_field_name('parameters')

                    if name_node:
                        name = content[name_node.start_byte:name_node.end_byte]
                        params = self._extract_js_params(params_node, content)

                        if class_stack:
                            qname = f"{rel_path}:{class_stack[-1]}.{name}"
                        else:
                            qname = f"{rel_path}:{name}"

                        fdef = FunctionDef(
                            qualified_name=qname,
                            file_path=rel_path,
                            line=name_node.start_point[0] + 1,
                            params=params,
                            is_method=True,
                            class_name=class_stack[-1] if class_stack else None,
                        )
                        defs.append(fdef)

                # Class declaration
                elif node.type == 'class_declaration':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        class_name = content[name_node.start_byte:name_node.end_byte]
                        class_stack.append(class_name)
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            for child in body_node.children:
                                _walk(child, scope_prefix)
                        class_stack.pop()

                else:
                    for child in node.children:
                        _walk(child, scope_prefix)

        _walk(tree.root_node)
        return defs

    def _parse_definitions_regex(self, rel_path: str, content: str,
                                  language: str) -> List[FunctionDef]:
        """Fallback: Extract function definitions using regex."""
        defs = []
        lines = content.split('\n')

        if language == 'python':
            current_class = None
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Class definition
                m = re.match(r'^class\s+(\w+)', stripped)
                if m:
                    current_class = m.group(1)
                    continue

                # Reset class scope on dedent
                if current_class and not stripped.startswith('#'):
                    indent = len(line) - len(line.lstrip())
                    if indent == 0 and stripped and not stripped.startswith(('class ', 'def ')):
                        if not stripped.startswith(('class ', '@', '"""', "'''")):
                            current_class = None

                # Function definition
                m = re.match(r'^(\s*)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)', line)
                if m:
                    name = m.group(2)
                    params_str = m.group(3)
                    params = [p.strip().split(':')[0].split('=')[0].strip()
                              for p in params_str.split(',')
                              if p.strip() and p.strip() not in ('self', 'cls')]
                    params = [p for p in params if p and p.isidentifier()]

                    is_method = current_class is not None
                    if current_class:
                        qname = f"{rel_path}:{current_class}.{name}"
                    else:
                        qname = f"{rel_path}:{name}"

                    defs.append(FunctionDef(
                        qualified_name=qname,
                        file_path=rel_path,
                        line=i,
                        params=params,
                        is_method=is_method,
                        class_name=current_class,
                    ))

        elif language in ('javascript', 'typescript', 'tsx'):
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Function declaration
                m = re.match(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', line)
                if m:
                    name = m.group(1)
                    params = [p.strip() for p in m.group(2).split(',') if p.strip()]
                    defs.append(FunctionDef(
                        qualified_name=f"{rel_path}:{name}",
                        file_path=rel_path,
                        line=i,
                        params=params,
                    ))
                    continue

                # Arrow function
                m = re.match(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>', line)
                if m:
                    name = m.group(1)
                    params = [p.strip() for p in m.group(2).split(',') if p.strip()]
                    defs.append(FunctionDef(
                        qualified_name=f"{rel_path}:{name}",
                        file_path=rel_path,
                        line=i,
                        params=params,
                    ))

        return defs

    def _extract_python_params(self, params_node, content: str) -> List[str]:
        """Extract parameter names from a Python function parameters node."""
        if not params_node:
            return []

        params = []
        for child in params_node.children:
            if child.type == 'identifier':
                name = content[child.start_byte:child.end_byte]
                if name not in ('self', 'cls'):
                    params.append(name)
            elif child.type == 'typed_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        name = content[sub.start_byte:sub.end_byte]
                        if name not in ('self', 'cls'):
                            params.append(name)
                        break
            elif child.type == 'default_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        name = content[sub.start_byte:sub.end_byte]
                        if name not in ('self', 'cls'):
                            params.append(name)
                        break
            elif child.type == 'typed_default_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        name = content[sub.start_byte:sub.end_byte]
                        if name not in ('self', 'cls'):
                            params.append(name)
                        break
            elif child.type == 'list_splat_pattern':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append('*' + content[sub.start_byte:sub.end_byte])
            elif child.type == 'dictionary_splat_pattern':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append('**' + content[sub.start_byte:sub.end_byte])

        return params

    def _extract_js_params(self, params_node, content: str) -> List[str]:
        """Extract parameter names from a JS/TS function parameters node."""
        if not params_node:
            return []

        params = []
        for child in params_node.children:
            if child.type == 'identifier':
                params.append(content[child.start_byte:child.end_byte])
            elif child.type == 'required_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append(content[sub.start_byte:sub.end_byte])
                        break
            elif child.type == 'optional_parameter':
                for sub in child.children:
                    if sub.type == 'identifier':
                        params.append(content[sub.start_byte:sub.end_byte])
                        break
            elif child.type in ('object_pattern', 'array_pattern'):
                # Destructuring: extract variable names
                for sub in child.children:
                    if sub.type == 'shorthand_property_identifier':
                        params.append(content[sub.start_byte:sub.end_byte])
                    elif sub.type == 'identifier':
                        params.append(content[sub.start_byte:sub.end_byte])
                    elif sub.type == 'pair':
                        for p in sub.children:
                            if p.type == 'shorthand_property_identifier':
                                params.append(content[p.start_byte:p.end_byte])
                                break

        return params

    # ── Import Resolution ─────────────────────────────────────

    def _resolve_imports(self, file_path: str, content: str,
                          language: str, workspace: str) -> ImportMap:
        """Parse import statements and build an ImportMap for a file.

        Uses tree-sitter for accurate parsing when available.
        """
        rel_path = os.path.relpath(file_path, workspace)
        parser = _get_parser(language)

        if parser and TREE_SITTER_AVAILABLE:
            return self._resolve_imports_treesitter(rel_path, content, language, parser, workspace)
        else:
            return self._resolve_imports_regex(rel_path, content, language, workspace)

    def _resolve_imports_treesitter(self, rel_path: str, content: str,
                                     language: str, parser,
                                     workspace: str) -> ImportMap:
        """Parse imports using tree-sitter AST."""
        imap = ImportMap(file_path=rel_path)

        try:
            tree = parser.parse(content.encode('utf-8'))
            if not tree or not tree.root_node:
                return self._resolve_imports_regex(rel_path, content, language, workspace)
        except Exception:
            return self._resolve_imports_regex(rel_path, content, language, workspace)

        def _walk_imports(node):
            if language == 'python':
                if node.type == 'import_statement':
                    # import module [as alias]
                    # import module.sub
                    for child in node.children:
                        if child.type == 'dotted_name':
                            module_path = content[child.start_byte:child.end_byte]
                            local_name = module_path.split('.')[0]
                            imap.imports[local_name] = module_path
                            imap.module_imports[local_name] = module_path
                            imap.all_imports.append(ImportInfo(
                                local_name=local_name,
                                module_path=module_path,
                                imported_name=module_path,
                                is_from_import=False,
                                line=node.start_point[0] + 1,
                            ))
                        elif child.type == 'aliased_import':
                            name_node = child.child_by_field_name('name')
                            alias_node = child.child_by_field_name('alias')
                            if name_node and alias_node:
                                module_path = content[name_node.start_byte:name_node.end_byte]
                                alias = content[alias_node.start_byte:alias_node.end_byte]
                                imap.imports[alias] = module_path
                                imap.module_imports[alias] = module_path
                                imap.all_imports.append(ImportInfo(
                                    local_name=alias,
                                    module_path=module_path,
                                    imported_name=module_path,
                                    is_from_import=False,
                                    line=node.start_point[0] + 1,
                                ))

                elif node.type == 'import_from_statement':
                    # from module import name [as alias]
                    # from .module import name1, name2 as alias2
                    module_path = ""
                    imported_names = []
                    is_star = False

                    # Phase 1: Find module_path (first dotted_name or relative_import
                    # BEFORE the 'import' keyword) and collect imported names
                    # AFTER the 'import' keyword.
                    #
                    # Tree-sitter structure for "from utils import get_user, sanitize_input":
                    #   import_from_statement
                    #     from
                    #     dotted_name (utils)         ← module path
                    #     import
                    #     dotted_name (get_user)       ← imported name
                    #     ,
                    #     dotted_name (sanitize_input) ← imported name
                    #
                    # Or with import_list:
                    #   import_from_statement
                    #     from
                    #     dotted_name (utils)
                    #     import
                    #     import_list
                    #       identifier (get_user)
                    #       ,
                    #       identifier (sanitize_input)

                    found_import_kw = False
                    for child in node.children:
                        if child.type == 'import':
                            found_import_kw = True
                            continue

                        if not found_import_kw:
                            # Before 'import' keyword — this is the module path
                            if child.type == 'dotted_name':
                                module_path = content[child.start_byte:child.end_byte]
                            elif child.type == 'relative_import':
                                dots = content[child.start_byte:child.end_byte]
                                module_path = dots
                            elif child.type == 'identifier':
                                # from X import Y — single identifier module
                                if not module_path:
                                    module_path = content[child.start_byte:child.end_byte]
                        else:
                            # After 'import' keyword — these are imported names
                            if child.type == 'wildcard_import':
                                is_star = True
                            elif child.type == 'import_list':
                                for item in child.children:
                                    if item.type in ('identifier', 'dotted_name'):
                                        name = content[item.start_byte:item.end_byte]
                                        imported_names.append((name, name))
                                    elif item.type == 'aliased_import':
                                        name_node = item.child_by_field_name('name')
                                        alias_node = item.child_by_field_name('alias')
                                        if name_node:
                                            orig = content[name_node.start_byte:name_node.end_byte]
                                            alias = content[alias_node.start_byte:alias_node.end_byte] if alias_node else orig
                                            imported_names.append((orig, alias))
                            elif child.type in ('identifier', 'dotted_name'):
                                # Direct child after import keyword (no import_list wrapper)
                                name = content[child.start_byte:child.end_byte]
                                imported_names.append((name, name))
                            elif child.type == 'aliased_import':
                                name_node = child.child_by_field_name('name')
                                alias_node = child.child_by_field_name('alias')
                                if name_node:
                                    orig = content[name_node.start_byte:name_node.end_byte]
                                    alias = content[alias_node.start_byte:alias_node.end_byte] if alias_node else orig
                                    imported_names.append((orig, alias))
                            # Skip commas and other punctuation

                    # Resolve relative imports
                    module_path = self._resolve_relative_module(
                        module_path, rel_path, workspace
                    )

                    # Register imports
                    for orig_name, alias in imported_names:
                        qname = f"{module_path}.{orig_name}" if module_path else orig_name
                        imap.from_imports[alias] = qname
                        imap.imports[alias] = qname
                        imap.all_imports.append(ImportInfo(
                            local_name=alias,
                            module_path=module_path,
                            imported_name=orig_name,
                            is_from_import=True,
                            line=node.start_point[0] + 1,
                        ))

                    if is_star:
                        imap.star_imports.append(module_path)
                        imap.all_imports.append(ImportInfo(
                            local_name='*',
                            module_path=module_path,
                            imported_name='*',
                            is_from_import=True,
                            is_star=True,
                            line=node.start_point[0] + 1,
                        ))

            elif language in ('javascript', 'typescript', 'tsx'):
                if node.type == 'import_statement':
                    # import X from 'module'
                    # import { X, Y } from 'module'
                    # import * as X from 'module'
                    source_str = ""
                    import_names = []

                    for child in node.children:
                        if child.type == 'string':
                            source_str = content[child.start_byte:child.end_byte].strip("'\"")
                        elif child.type == 'identifier':
                            # Default import: import X from 'module'
                            name = content[child.start_byte:child.end_byte]
                            import_names.append((name, name, 'default'))
                        elif child.type == 'named_imports':
                            for sub in child.children:
                                if sub.type == 'import_specifier':
                                    name_node = sub.child_by_field_name('name')
                                    alias_node = sub.child_by_field_name('alias')
                                    if name_node:
                                        orig = content[name_node.start_byte:name_node.end_byte]
                                        alias = content[alias_node.start_byte:alias_node.end_byte] if alias_node else orig
                                        import_names.append((orig, alias, 'named'))
                        elif child.type == 'namespace_import':
                            # import * as X from 'module'
                            for sub in child.children:
                                if sub.type == 'identifier':
                                    name = content[sub.start_byte:sub.end_byte]
                                    import_names.append(('*', name, 'namespace'))

                    # Convert source to module path
                    module_path = self._js_source_to_module(source_str, rel_path, workspace)

                    for orig, alias, kind in import_names:
                        if kind == 'namespace':
                            imap.module_imports[alias] = module_path
                            imap.imports[alias] = module_path
                        elif kind == 'default':
                            qname = f"{module_path}.{orig}" if module_path else orig
                            imap.from_imports[alias] = qname
                            imap.imports[alias] = qname
                        else:
                            qname = f"{module_path}.{orig}" if module_path else orig
                            imap.from_imports[alias] = qname
                            imap.imports[alias] = qname

                        imap.all_imports.append(ImportInfo(
                            local_name=alias,
                            module_path=module_path,
                            imported_name=orig,
                            is_from_import=True,
                            line=node.start_point[0] + 1,
                        ))

                elif node.type == 'require_call':
                    # const X = require('module')
                    for child in node.children:
                        if child.type == 'string':
                            source_str = content[child.start_byte:child.end_byte].strip("'\"")
                            module_path = self._js_source_to_module(source_str, rel_path, workspace)
                            if module_path:
                                imap.module_imports[module_path.split('.')[-1]] = module_path
                                imap.imports[module_path.split('.')[-1]] = module_path

                # Handle: const { X, Y } = require('./module')
                # and: const X = require('./module')
                # These are variable_declarator nodes, not require_call nodes
                elif node.type == 'variable_declarator':
                    name_node = node.child_by_field_name('name')
                    value_node = node.child_by_field_name('value')

                    if name_node and value_node and value_node.type == 'call_expression':
                        func_node = value_node.child_by_field_name('function')
                        if func_node and func_node.type == 'identifier':
                            func_name = content[func_node.start_byte:func_node.end_byte]
                            if func_name == 'require':
                                # Get the source string
                                args_node = value_node.child_by_field_name('arguments')
                                source_str = ""
                                if args_node:
                                    for arg_child in args_node.children:
                                        if arg_child.type == 'string':
                                            source_str = content[arg_child.start_byte:arg_child.end_byte].strip("'\"")

                                module_path = self._js_source_to_module(source_str, rel_path, workspace)

                                if name_node.type == 'object_pattern':
                                    # Destructuring: const { queryUser, updateUser } = require('./db')
                                    for pat_child in name_node.children:
                                        if pat_child.type == 'shorthand_property_identifier_pattern':
                                            name = content[pat_child.start_byte:pat_child.end_byte]
                                            qname = f"{module_path}.{name}" if module_path else name
                                            imap.from_imports[name] = qname
                                            imap.imports[name] = qname
                                            imap.all_imports.append(ImportInfo(
                                                local_name=name,
                                                module_path=module_path,
                                                imported_name=name,
                                                is_from_import=True,
                                                line=node.start_point[0] + 1,
                                            ))
                                        elif pat_child.type == 'pair_pattern':
                                            # { X: Y } — alias
                                            for pair_child in pat_child.children:
                                                if pair_child.type == 'shorthand_property_identifier_pattern':
                                                    orig = content[pair_child.start_byte:pair_child.end_byte]
                                                elif pair_child.type == 'identifier':
                                                    alias = content[pair_child.start_byte:pair_child.end_byte]
                                        elif pat_child.type == 'assignment_pattern':
                                            # { X = default } — with default value
                                            for assign_child in pat_child.children:
                                                if assign_child.type == 'shorthand_property_identifier_pattern':
                                                    name = content[assign_child.start_byte:assign_child.end_byte]
                                                    qname = f"{module_path}.{name}" if module_path else name
                                                    imap.from_imports[name] = qname
                                                    imap.imports[name] = qname
                                                    imap.all_imports.append(ImportInfo(
                                                        local_name=name,
                                                        module_path=module_path,
                                                        imported_name=name,
                                                        is_from_import=True,
                                                        line=node.start_point[0] + 1,
                                                    ))
                                elif name_node.type == 'identifier':
                                    # Simple: const X = require('./module')
                                    name = content[name_node.start_byte:name_node.end_byte]
                                    imap.module_imports[name] = module_path
                                    imap.imports[name] = module_path
                                    imap.all_imports.append(ImportInfo(
                                        local_name=name,
                                        module_path=module_path,
                                        imported_name=name,
                                        is_from_import=False,
                                        line=node.start_point[0] + 1,
                                    ))

            # Recurse into children
            for child in node.children:
                _walk_imports(child)

        _walk_imports(tree.root_node)
        return imap

    def _resolve_imports_regex(self, rel_path: str, content: str,
                                language: str, workspace: str) -> ImportMap:
        """Fallback: Parse imports using regex."""
        imap = ImportMap(file_path=rel_path)
        lines = content.split('\n')

        if language == 'python':
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # from module import name [as alias]
                m = re.match(r'^from\s+([\w.]+)\s+import\s+(.+)', stripped)
                if m:
                    module_path = m.group(1)
                    import_list = m.group(2)

                    # Handle star import
                    if import_list.strip() == '*':
                        module_path = self._resolve_relative_module(
                            module_path, rel_path, workspace
                        )
                        imap.star_imports.append(module_path)
                        imap.all_imports.append(ImportInfo(
                            local_name='*', module_path=module_path,
                            imported_name='*', is_from_import=True,
                            is_star=True, line=i,
                        ))
                        continue

                    # Parse individual imports
                    module_path = self._resolve_relative_module(
                        module_path, rel_path, workspace
                    )

                    for item in import_list.split(','):
                        item = item.strip()
                        m2 = re.match(r'(\w+)(?:\s+as\s+(\w+))?', item)
                        if m2:
                            orig_name = m2.group(1)
                            alias = m2.group(2) or orig_name
                            qname = f"{module_path}.{orig_name}"
                            imap.from_imports[alias] = qname
                            imap.imports[alias] = qname
                            imap.all_imports.append(ImportInfo(
                                local_name=alias,
                                module_path=module_path,
                                imported_name=orig_name,
                                is_from_import=True,
                                line=i,
                            ))
                    continue

                # import module [as alias]
                m = re.match(r'^import\s+([\w.]+)(?:\s+as\s+(\w+))?', stripped)
                if m:
                    module_path = m.group(1)
                    alias = m.group(2) or module_path.split('.')[0]
                    imap.imports[alias] = module_path
                    imap.module_imports[alias] = module_path
                    imap.all_imports.append(ImportInfo(
                        local_name=alias,
                        module_path=module_path,
                        imported_name=module_path,
                        is_from_import=False,
                        line=i,
                    ))

        elif language in ('javascript', 'typescript', 'tsx'):
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # import X from 'module'
                m = re.match(r"^import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]", stripped)
                if m:
                    name = m.group(1)
                    source = m.group(2)
                    module_path = self._js_source_to_module(source, rel_path, workspace)
                    qname = f"{module_path}.{name}" if module_path else name
                    imap.from_imports[name] = qname
                    imap.imports[name] = qname
                    imap.all_imports.append(ImportInfo(
                        local_name=name, module_path=module_path,
                        imported_name=name, is_from_import=True, line=i,
                    ))
                    continue

                # import { X, Y as Z } from 'module'
                m = re.match(r"^import\s*\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", stripped)
                if m:
                    items = m.group(1)
                    source = m.group(2)
                    module_path = self._js_source_to_module(source, rel_path, workspace)

                    for item in items.split(','):
                        item = item.strip()
                        m2 = re.match(r'(\w+)(?:\s+as\s+(\w+))?', item)
                        if m2:
                            orig = m2.group(1)
                            alias = m2.group(2) or orig
                            qname = f"{module_path}.{orig}" if module_path else orig
                            imap.from_imports[alias] = qname
                            imap.imports[alias] = qname
                            imap.all_imports.append(ImportInfo(
                                local_name=alias, module_path=module_path,
                                imported_name=orig, is_from_import=True, line=i,
                            ))
                    continue

                # import * as X from 'module'
                m = re.match(r"^import\s*\*\s*as\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]", stripped)
                if m:
                    alias = m.group(1)
                    source = m.group(2)
                    module_path = self._js_source_to_module(source, rel_path, workspace)
                    imap.module_imports[alias] = module_path
                    imap.imports[alias] = module_path
                    imap.all_imports.append(ImportInfo(
                        local_name=alias, module_path=module_path,
                        imported_name='*', is_from_import=True, line=i,
                    ))
                    continue

                # const X = require('module')
                m = re.match(r"(?:const|let|var)\s+(\w+)\s*=\s*require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", stripped)
                if m:
                    name = m.group(1)
                    source = m.group(2)
                    module_path = self._js_source_to_module(source, rel_path, workspace)
                    imap.module_imports[name] = module_path
                    imap.imports[name] = module_path
                    imap.all_imports.append(ImportInfo(
                        local_name=name, module_path=module_path,
                        imported_name=name, is_from_import=False, line=i,
                    ))

        return imap

    def _resolve_relative_module(self, module_path: str, current_file: str,
                                  workspace: str) -> str:
        """Resolve a relative import (e.g., .utils, ..models) to an absolute module path.

        For Python: from .utils import helper → package.utils
        """
        if not module_path.startswith('.'):
            return module_path

        # Calculate the package path from the current file
        file_dir = os.path.dirname(current_file)
        parts = file_dir.replace(os.sep, '.').split('.')

        # Count leading dots
        dots = 0
        for ch in module_path:
            if ch == '.':
                dots += 1
            else:
                break

        remaining = module_path[dots:]

        # Go up (dots - 1) levels
        parent_parts = parts[:len(parts) - (dots - 1)] if dots > 1 else parts
        if remaining:
            result = '.'.join(parent_parts + [remaining]) if parent_parts else remaining
        else:
            result = '.'.join(parent_parts)

        return result

    def _js_source_to_module(self, source: str, current_file: str,
                              workspace: str) -> str:
        """Convert a JS/TS import source to a module path.

        E.g., './utils' → 'src.utils', 'express' → 'express'
        """
        if not source:
            return source

        # Relative import
        if source.startswith('.'):
            file_dir = os.path.dirname(current_file)
            rel_path = os.path.normpath(os.path.join(file_dir, source))
            # Remove extension
            if rel_path.endswith(('.js', '.ts', '.tsx', '.jsx', '.mjs')):
                rel_path = os.path.splitext(rel_path)[0]
            return rel_path.replace(os.sep, '.')

        # Node module or absolute path
        return source

    def _resolve_re_exports(self, cg: CallGraph, workspace: str):
        """Resolve re-exports in __init__.py files.

        When __init__.py contains:
            from .utils import helper
        The name 'helper' is available as package.helper from outside.
        """
        for rel_path, imap in cg.import_map.items():
            if not rel_path.endswith('__init__.py'):
                continue

            package_dir = os.path.dirname(rel_path)
            package_name = package_dir.replace(os.sep, '.') if package_dir else ''

            for alias, qname in list(imap.from_imports.items()):
                # Re-export: make this available as package.alias
                if package_name:
                    re_export_qname = f"{package_name}.{alias}"
                    imap.re_exports[alias] = qname

                    # Also register in the import map so callers can find it
                    # When another file does "from package import helper",
                    # the resolution should find this mapping
                    if re_export_qname not in imap.from_imports:
                        imap.from_imports[re_export_qname] = qname

    # ── Call Site Parsing ─────────────────────────────────────

    def _parse_file_calls(self, file_path: str, content: str,
                           language: str, workspace: str) -> List[CallSite]:
        """Extract all call sites from a file using tree-sitter.

        Tracks the current function context for each call.
        """
        rel_path = os.path.relpath(file_path, workspace)
        parser = _get_parser(language)

        if parser and TREE_SITTER_AVAILABLE:
            return self._parse_calls_treesitter(rel_path, content, language, parser)
        else:
            return self._parse_calls_regex(rel_path, content, language)

    def _parse_calls_treesitter(self, rel_path: str, content: str,
                                 language: str, parser) -> List[CallSite]:
        """Extract call sites using tree-sitter AST."""
        calls = []

        try:
            tree = parser.parse(content.encode('utf-8'))
            if not tree or not tree.root_node:
                return self._parse_calls_regex(rel_path, content, language)
        except Exception:
            return self._parse_calls_regex(rel_path, content, language)

        # Track function scope stack
        scope_stack: List[str] = ["module"]
        class_stack: List[str] = []

        def _walk(node):
            nonlocal scope_stack, class_stack

            if language == 'python':
                if node.type == 'function_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        fn_name = content[name_node.start_byte:name_node.end_byte]
                        if class_stack:
                            qname = f"{rel_path}:{class_stack[-1]}.{fn_name}"
                        else:
                            qname = f"{rel_path}:{fn_name}"
                        scope_stack.append(qname)
                        # Recurse into body
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            _walk(body_node)
                        scope_stack.pop()
                    return

                elif node.type == 'class_definition':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        cls_name = content[name_node.start_byte:name_node.end_byte]
                        class_stack.append(cls_name)
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            for child in body_node.children:
                                _walk(child)
                        class_stack.pop()
                    return

                elif node.type == 'call':
                    self._extract_python_call(node, content, rel_path,
                                              scope_stack[-1], class_stack, calls)

            elif language in ('javascript', 'typescript', 'tsx'):
                if node.type == 'function_declaration':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        fn_name = content[name_node.start_byte:name_node.end_byte]
                        scope_stack.append(f"{rel_path}:{fn_name}")
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            _walk(body_node)
                        scope_stack.pop()
                    return

                elif node.type == 'class_declaration':
                    name_node = node.child_by_field_name('name')
                    if name_node:
                        cls_name = content[name_node.start_byte:name_node.end_byte]
                        class_stack.append(cls_name)
                        body_node = node.child_by_field_name('body')
                        if body_node:
                            for child in body_node.children:
                                _walk(child)
                        class_stack.pop()
                    return

                elif node.type == 'call_expression':
                    self._extract_js_call(node, content, rel_path,
                                          scope_stack[-1], class_stack, calls)

            # Recurse into children
            for child in node.children:
                _walk(child)

        _walk(tree.root_node)
        return calls

    def _extract_python_call(self, node, content: str, rel_path: str,
                              current_fn: str, class_stack: List[str],
                              calls: List[CallSite]):
        """Extract a Python call site from a tree-sitter call node."""
        # The function being called
        func_node = node.child_by_field_name('function')
        if not func_node:
            return

        # Extract callee name
        callee_name, receiver, is_method = self._resolve_python_callee(
            func_node, content, class_stack
        )

        if not callee_name:
            return

        # Skip Python builtins
        if callee_name in self.PYTHON_BUILTINS:
            return

        # Extract arguments
        args_node = node.child_by_field_name('arguments')
        arg_vars = self._extract_python_call_args(args_node, content)

        call_type = "method" if is_method else "direct"
        if callee_name in ('map', 'filter', 'apply', 'reduce', 'sorted'):
            call_type = "callback"
        elif receiver and receiver in ('self', 'cls'):
            call_type = "method"

        cs = CallSite(
            caller_function=current_fn,
            callee_name=callee_name,
            arguments=arg_vars,
            line=func_node.start_point[0] + 1,
            file_path=rel_path,
            is_method_call=is_method,
            receiver_expr=receiver,
            call_type=call_type,
        )
        calls.append(cs)

    def _resolve_python_callee(self, func_node, content: str,
                                class_stack: List[str]) -> Tuple[str, Optional[str], bool]:
        """Resolve a Python call target to its name.

        Returns (callee_name, receiver_expr, is_method_call)
        """
        if func_node.type == 'identifier':
            # Simple call: func()
            name = content[func_node.start_byte:func_node.end_byte]
            return name, None, False

        elif func_node.type == 'attribute':
            # Method call: obj.method() or module.func()
            # Get the attribute name (last part)
            attr_node = None
            obj_node = None
            for child in func_node.children:
                if child.type == 'identifier':
                    # Last identifier is the method name
                    attr_node = child
                elif child.type == '.':
                    pass
                else:
                    obj_node = child

            if not attr_node:
                return "", None, False

            method_name = content[attr_node.start_byte:attr_node.end_byte]

            # Get receiver expression
            receiver = ""
            if obj_node:
                receiver = content[obj_node.start_byte:obj_node.end_byte]

            # For self.method() or cls.method()
            if receiver in ('self', 'cls') and class_stack:
                return f"{class_stack[-1]}.{method_name}", receiver, True

            # For obj.method()
            if receiver:
                return f"{receiver}.{method_name}", receiver, True

            return method_name, None, False

        elif func_node.type == 'call':
            # Nested call: func()()
            inner_name, inner_recv, inner_method = self._resolve_python_callee(
                func_node.child_by_field_name('function'), content, class_stack
            )
            return inner_name, inner_recv, inner_method

        return "", None, False

    def _extract_python_call_args(self, args_node, content: str) -> List[str]:
        """Extract variable names from Python call arguments."""
        if not args_node:
            return []

        args = []
        for child in args_node.children:
            if child.type == 'argument_list':
                continue
            if child.type in ('(', ')', ','):
                continue

            # Extract variable references from argument
            arg_vars = self._extract_var_refs(child, content, 'python')
            if arg_vars:
                args.extend(arg_vars)
            else:
                # Include the expression text
                args.append(content[child.start_byte:child.end_byte].strip())

        return args

    def _extract_js_call(self, node, content: str, rel_path: str,
                          current_fn: str, class_stack: List[str],
                          calls: List[CallSite]):
        """Extract a JS/TS call site from a tree-sitter call_expression node."""
        func_node = node.child_by_field_name('function')
        if not func_node:
            return

        callee_name, receiver, is_method = self._resolve_js_callee(
            func_node, content, class_stack
        )

        if not callee_name:
            return

        # Skip JS builtins
        base_name = callee_name.split('.')[-1] if '.' in callee_name else callee_name
        if base_name in self.JS_BUILTINS:
            return

        # Extract arguments
        args_node = node.child_by_field_name('arguments')
        arg_vars = self._extract_js_call_args(args_node, content)

        call_type = "method" if is_method else "direct"
        if base_name in ('then', 'catch', 'finally', 'map', 'filter', 'reduce',
                          'forEach', 'apply', 'call', 'bind'):
            call_type = "callback"

        cs = CallSite(
            caller_function=current_fn,
            callee_name=callee_name,
            arguments=arg_vars,
            line=func_node.start_point[0] + 1,
            file_path=rel_path,
            is_method_call=is_method,
            receiver_expr=receiver,
            call_type=call_type,
        )
        calls.append(cs)

    def _resolve_js_callee(self, func_node, content: str,
                            class_stack: List[str]) -> Tuple[str, Optional[str], bool]:
        """Resolve a JS/TS call target to its name."""
        if func_node.type == 'identifier':
            name = content[func_node.start_byte:func_node.end_byte]
            return name, None, False

        elif func_node.type == 'member_expression':
            # obj.method()
            obj_node = func_node.child_by_field_name('object')
            prop_node = func_node.child_by_field_name('property')

            if not prop_node:
                return "", None, False

            method_name = content[prop_node.start_byte:prop_node.end_byte]
            receiver = ""
            if obj_node:
                receiver = content[obj_node.start_byte:obj_node.end_byte]

            if receiver:
                return f"{receiver}.{method_name}", receiver, True
            return method_name, None, False

        elif func_node.type == 'call_expression':
            # func()()
            inner_name, inner_recv, inner_method = self._resolve_js_callee(
                func_node.child_by_field_name('function'), content, class_stack
            )
            return inner_name, inner_recv, inner_method

        return "", None, False

    def _extract_js_call_args(self, args_node, content: str) -> List[str]:
        """Extract variable names from JS call arguments."""
        if not args_node:
            return []

        args = []
        for child in args_node.children:
            if child.type in ('(', ')', ','):
                continue

            arg_vars = self._extract_var_refs(child, content, 'javascript')
            if arg_vars:
                args.extend(arg_vars)

        return args

    def _extract_var_refs(self, node, content: str, language: str) -> List[str]:
        """Extract variable references from an expression node."""
        if not node:
            return []

        vars_found = []

        if node.type == 'identifier':
            vars_found.append(content[node.start_byte:node.end_byte])
        elif node.type in ('string', 'number', 'true', 'false', 'null', 'none'):
            pass  # Literal — no variable reference
        elif node.type == 'attribute':
            # Python: obj.attr
            for child in node.children:
                if child.type == 'identifier':
                    vars_found.append(content[child.start_byte:child.end_byte])
        elif node.type == 'member_expression':
            # JS: obj.prop
            obj_node = node.child_by_field_name('object')
            prop_node = node.child_by_field_name('property')
            if obj_node and obj_node.type == 'identifier':
                vars_found.append(content[obj_node.start_byte:obj_node.end_byte])
        elif node.type == 'binary_expression':
            left = node.child_by_field_name('left')
            right = node.child_by_field_name('right')
            if left:
                vars_found.extend(self._extract_var_refs(left, content, language))
            if right:
                vars_found.extend(self._extract_var_refs(right, content, language))
        elif node.type == 'call_expression':
            # Function call in argument position
            func_node = node.child_by_field_name('function')
            if func_node:
                vars_found.extend(self._extract_var_refs(func_node, content, language))
        elif node.type in ('keyword_argument', 'assignment_expression'):
            # keyword arg or assignment — get the value side
            for child in node.children:
                vars_found.extend(self._extract_var_refs(child, content, language))
        else:
            # Generic: recurse into children
            for child in node.children:
                vars_found.extend(self._extract_var_refs(child, content, language))

        return vars_found

    def _parse_calls_regex(self, rel_path: str, content: str,
                            language: str) -> List[CallSite]:
        """Fallback: Extract call sites using regex."""
        calls = []
        lines = content.split('\n')

        if language == 'python':
            current_fn = "module"
            current_class = None

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # Track class scope
                m = re.match(r'^class\s+(\w+)', stripped)
                if m:
                    current_class = m.group(1)
                    continue

                # Track function scope
                m = re.match(r'^(\s*)(?:async\s+)?def\s+(\w+)\s*\(', line)
                if m:
                    fn_name = m.group(2)
                    if current_class:
                        current_fn = f"{rel_path}:{current_class}.{fn_name}"
                    else:
                        current_fn = f"{rel_path}:{fn_name}"
                    continue

                # Find method calls: obj.method()
                for m in re.finditer(r'(\w+)\.(\w+)\s*\(', stripped):
                    receiver = m.group(1)
                    method = m.group(2)
                    if method in self.PYTHON_BUILTINS:
                        continue
                    if receiver in ('self', 'cls') and current_class:
                        callee = f"{current_class}.{method}"
                    else:
                        callee = f"{receiver}.{method}"
                    calls.append(CallSite(
                        caller_function=current_fn,
                        callee_name=callee,
                        arguments=[],
                        line=i,
                        file_path=rel_path,
                        is_method_call=True,
                        receiver_expr=receiver,
                        call_type="method",
                    ))

                # Find simple function calls: func()
                for m in re.finditer(r'(?<!\.)\b(\w+)\s*\(', stripped):
                    name = m.group(1)
                    if name in self.PYTHON_BUILTINS:
                        continue
                    if name.startswith(('if', 'for', 'while', 'with', 'class', 'def',
                                        'return', 'raise', 'assert', 'import', 'from',
                                        'elif', 'except', 'try', 'finally', 'async',
                                        'await', 'yield', 'del', 'not', 'and', 'or')):
                        continue
                    calls.append(CallSite(
                        caller_function=current_fn,
                        callee_name=name,
                        arguments=[],
                        line=i,
                        file_path=rel_path,
                        call_type="direct",
                    ))

        elif language in ('javascript', 'typescript', 'tsx'):
            current_fn = "module"

            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                m = re.match(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)', stripped)
                if m:
                    current_fn = f"{rel_path}:{m.group(1)}"
                    continue

                m = re.match(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', stripped)
                if m:
                    current_fn = f"{rel_path}:{m.group(1)}"
                    continue

                # Find method calls
                for m in re.finditer(r'(\w+)\.(\w+)\s*\(', stripped):
                    receiver = m.group(1)
                    method = m.group(2)
                    if method in self.JS_BUILTINS:
                        continue
                    calls.append(CallSite(
                        caller_function=current_fn,
                        callee_name=f"{receiver}.{method}",
                        arguments=[],
                        line=i,
                        file_path=rel_path,
                        is_method_call=True,
                        receiver_expr=receiver,
                        call_type="method",
                    ))

                # Find function calls
                for m in re.finditer(r'(?<!\.)\b(\w+)\s*\(', stripped):
                    name = m.group(1)
                    if name in self.JS_BUILTINS:
                        continue
                    if name.startswith(('if', 'for', 'while', 'switch', 'function',
                                        'return', 'throw', 'new', 'class', 'import',
                                        'export', 'typeof', 'instanceof', 'delete',
                                        'void', 'await', 'yield', 'try', 'catch')):
                        continue
                    calls.append(CallSite(
                        caller_function=current_fn,
                        callee_name=name,
                        arguments=[],
                        line=i,
                        file_path=rel_path,
                        call_type="direct",
                    ))

        return calls

    # ── Call Resolution ───────────────────────────────────────

    def _resolve_call(self, call_site: CallSite, import_map: Optional[ImportMap],
                       cg: CallGraph, workspace: str) -> Optional[str]:
        """Resolve a call site to a qualified function name.

        Resolution strategy:
        1. If callee_name is qualified (has dots), try direct resolution
        2. Use import_map to resolve imported names
        3. Look up in CallGraph's function registry
        4. Handle method calls on imported objects
        5. Best-effort for dynamic calls
        """
        callee = call_site.callee_name
        if not callee:
            return None

        # Strategy 1: Direct match in function registry
        direct_match = cg.resolve_function(callee, call_site.file_path)
        if direct_match:
            return direct_match.qualified_name

        # Strategy 2: Import resolution
        if import_map:
            # Simple name: from module import func → module.func
            if '.' not in callee:
                resolved = import_map.resolve(callee)
                if resolved:
                    # Check if the resolved name maps to a known function
                    func_match = cg.resolve_function(resolved)
                    if func_match:
                        return func_match.qualified_name
                    # Try the resolved name as-is (may match another file's function)
                    # Convert module.func to file:function format
                    file_func = self._module_to_file_function(resolved, cg)
                    if file_func:
                        return file_func
                    return resolved

            # Qualified name: module.func or obj.method
            else:
                parts = callee.split('.', 1)
                obj_name = parts[0]
                attr_name = parts[1]

                # obj.method where obj is imported
                resolved = import_map.resolve_attribute(obj_name, attr_name)
                if resolved:
                    func_match = cg.resolve_function(resolved)
                    if func_match:
                        return func_match.qualified_name
                    file_func = self._module_to_file_function(resolved, cg)
                    if file_func:
                        return file_func
                    return resolved

                # obj might be a local name for an imported module
                module_path = import_map.resolve(obj_name)
                if module_path:
                    qualified = f"{module_path}.{attr_name}"
                    func_match = cg.resolve_function(qualified)
                    if func_match:
                        return func_match.qualified_name
                    file_func = self._module_to_file_function(qualified, cg)
                    if file_func:
                        return file_func

        # Strategy 3: Class method resolution
        if call_site.is_method_call and call_site.receiver_expr:
            receiver = call_site.receiver_expr
            if receiver == 'self' or receiver == 'cls':
                # self.method() → find in current class
                method_name = callee.split('.')[-1] if '.' in callee else callee
                # Find class from caller context
                caller = call_site.caller_function
                if ':' in caller:
                    # Extract class name from "file:ClassName.method"
                    caller_parts = caller.split(':')
                    if len(caller_parts) >= 2:
                        class_part = caller_parts[1].split('.')[0]
                        method_def = cg.resolve_method(class_part, method_name,
                                                        call_site.file_path)
                        if method_def:
                            return method_def.qualified_name

            else:
                # obj.method() → obj could be an imported class
                method_name = callee.split('.')[-1] if '.' in callee else callee
                method_def = cg.resolve_method(receiver, method_name,
                                                call_site.file_path)
                if method_def:
                    return method_def.qualified_name

        # Strategy 4: Global short-name search
        short_name = callee.split('.')[-1] if '.' in callee else callee
        global_match = cg.resolve_function(short_name)
        if global_match:
            return global_match.qualified_name

        # Strategy 5: Best-effort dynamic resolution
        if call_site.call_type == "callback":
            # For callback patterns, we may not be able to resolve statically
            return None

        return None

    def _module_to_file_function(self, module_qualified: str,
                                  cg: CallGraph) -> Optional[str]:
        """Convert a module-style qualified name to file:function format.

        E.g., "utils.helper" → look for a file "utils.py" with function "helper"
        E.g., "myapp.db.query_user" → look for "myapp/db.py" with "query_user"

        Also follows re-export chains through __init__.py:
        E.g., "myapp.query_user" → check myapp/__init__.py re-exports
              → find myapp.db.query_user → myapp/db.py:query_user
        """
        parts = module_qualified.rsplit('.', 1)
        if len(parts) < 2:
            return None

        module_path = parts[0]
        func_name = parts[1]

        # Strategy 1: Direct module→file mapping
        # "utils.helper" → file "utils.py", function "helper"
        # "myapp.db.query_user" → file "myapp/db.py", function "query_user"
        for ext in ('.py', '.js', '.ts', '.tsx'):
            file_path = module_path.replace('.', os.sep) + ext
            file_funcs = cg.file_functions.get(file_path, [])
            for qname in file_funcs:
                if qname.split(':')[-1] == func_name or qname.endswith(f'.{func_name}'):
                    return qname

        # Strategy 2: Check __init__.py re-exports for the module path
        # "myapp.query_user" → check "myapp/__init__.py" re-exports
        init_path = os.path.join(module_path.replace('.', os.sep), '__init__.py')
        imap = cg.import_map.get(init_path)
        if imap:
            # Check re-exports
            re_exported = imap.re_exports.get(func_name)
            if re_exported:
                # Recurse: "myapp.db.query_user" → try to resolve again
                return self._module_to_file_function(re_exported, cg)

            # Check from_imports
            direct_import = imap.from_imports.get(func_name)
            if direct_import:
                return self._module_to_file_function(direct_import, cg)

        # Strategy 3: Search all files by function short name
        for file_path, func_list in cg.file_functions.items():
            # Only search in files that might be under the module path
            module_dir = module_path.replace('.', os.sep)
            if not file_path.startswith(module_dir):
                continue
            for qname in func_list:
                if qname.split(':')[-1] == func_name or qname.endswith(f'.{func_name}'):
                    return qname

        # Strategy 4: Global search by function short name
        for qname, fdef in cg.functions.items():
            if fdef.short_name == func_name:
                return qname

        return None

    def _timed_out(self) -> bool:
        return time.time() - self._start_time > self.timeout_sec


# ─── Data Flow Graph Builder ─────────────────────────────────

class DataFlowGraphBuilder:
    """Builds a workspace-wide data flow graph from the call graph and
    per-file taint analysis results.

    The DataFlowGraph connects taint states across files:
    - Function parameter flow (argument → parameter)
    - Return value flow (return → caller's variable)
    - Class attribute propagation (self.attr in different methods)
    - Callback flow (higher-order function arguments)
    """

    def __init__(self, max_depth: int = 20):
        self.max_depth = max_depth

    def build(self, call_graph: CallGraph,
              taint_results: Dict[str, List[Dict]],
              workspace: str = "") -> DataFlowGraph:
        """Build the data flow graph.

        Args:
            call_graph: The workspace-wide call graph.
            taint_results: Per-file taint results. file_path → list of findings.
            workspace: Workspace root path.

        Returns:
            DataFlowGraph with nodes and edges connecting taint across files.
        """
        dfg = DataFlowGraph()

        # Phase 1: Create DataFlowNodes from taint results
        self._create_nodes_from_taint(dfg, taint_results)

        # Phase 2: Create edges from call graph (parameter passing)
        self._create_parameter_edges(dfg, call_graph)

        # Phase 3: Create edges for return values
        self._create_return_edges(dfg, call_graph, taint_results)

        # Phase 4: Create edges for class attribute propagation
        self._create_class_attr_edges(dfg, call_graph, taint_results)

        # Phase 5: Create edges for callbacks and higher-order functions
        self._create_callback_edges(dfg, call_graph)

        # Phase 6: Propagate taint through the DFG
        self._propagate_taint(dfg)

        return dfg

    def _create_nodes_from_taint(self, dfg: DataFlowGraph,
                                  taint_results: Dict[str, List[Dict]]):
        """Create DataFlowNodes from per-file taint analysis results.

        Creates nodes for:
        1. The tainted variable that reaches a sink
        2. Parameter sources (e.g., <param:user_id>) — so we can connect them
           to caller arguments via the call graph
        3. All variables in the taint path for better cross-file flow tracking
        """
        for file_path, findings in taint_results.items():
            # Normalize file path to relative path
            norm_path = self._normalize_file_path(file_path)

            for finding in findings:
                var_name = finding.get("tainted_variable", "")
                if not var_name:
                    continue

                fn_name = finding.get("function", "module")
                # Try to resolve function name from the call graph
                if not fn_name or fn_name in ("?", "unknown", "module"):
                    fn_name = self._resolve_function_name(norm_path, finding)
                line = finding.get("line", 0)
                source_str = finding.get("source", "unknown")

                # Create node for the main tainted variable
                node = DataFlowNode(
                    var_name=var_name,
                    file_path=norm_path,
                    function_name=fn_name,
                    line=line,
                    is_tainted=True,
                    taint_sources={source_str},
                    taint_path=finding.get("taint_path", "").split(" → ") if finding.get("taint_path") else [],
                    is_sanitized=finding.get("sanitized", False),
                    sanitizers=set(finding.get("sanitizers_found", [])),
                    confidence=finding.get("confidence", 0.5)
                    if isinstance(finding.get("confidence"), float)
                    else 0.8,
                )
                dfg.add_node(node)

                # Create node for parameter sources (e.g., <param:user_id>)
                # This is essential for connecting per-file taint to cross-file flows
                if source_str.startswith("<param:"):
                    param_name = source_str[len("<param:"):-1]  # Extract "user_id"
                    param_node = DataFlowNode(
                        var_name=param_name,
                        file_path=norm_path,
                        function_name=fn_name,
                        line=line,
                        is_tainted=True,
                        taint_sources={source_str},
                        taint_path=[source_str],
                        is_sanitized=finding.get("sanitized", False),
                        sanitizers=set(finding.get("sanitizers_found", [])),
                        confidence=0.9,
                    )
                    dfg.add_node(param_node)

                # Create nodes for variables in the taint path
                taint_path_str = finding.get("taint_path", "")
                if taint_path_str:
                    path_steps = taint_path_str.split(" → ")
                    for step in path_steps:
                        # Skip non-variable steps (sources, sinks, operators)
                        if step.startswith("<") or step.startswith("→") or '.' in step:
                            continue
                        if step in (var_name, source_str):
                            continue  # Already created
                        # Check if this looks like a variable name
                        if step.isidentifier() or (step.startswith('*') and step[1:].isidentifier()):
                            existing = self._find_node_id(dfg, step, norm_path, fn_name)
                            if not existing:
                                path_node = DataFlowNode(
                                    var_name=step,
                                    file_path=norm_path,
                                    function_name=fn_name,
                                    line=0,
                                    is_tainted=True,
                                    taint_sources={source_str},
                                    taint_path=[source_str, step],
                                )
                                dfg.add_node(path_node)

    def _normalize_file_path(self, file_path: str) -> str:
        """Normalize a file path to a relative path.

        Taint results may use absolute paths; call graph uses relative paths.
        """
        # If it's already a relative path (no leading /), return as-is
        if not os.path.isabs(file_path):
            return file_path

        # Try to make it relative to workspace
        # This is a heuristic — we'll match by filename if needed
        return os.path.basename(file_path)

    def _resolve_function_name(self, norm_path: str, finding: Dict) -> str:
        """Try to resolve the function name from the finding context."""
        # Check if the taint path contains a function name
        taint_path = finding.get("taint_path", "")
        if taint_path:
            # The taint path might contain the function context
            pass

        # Default: use norm_path as prefix
        return f"{norm_path}:<unknown>"

    def _create_parameter_edges(self, dfg: DataFlowGraph, cg: CallGraph):
        """Create edges for function parameter passing.

        When function A calls function B(arg1, arg2):
        - arg1 flows to B's first parameter
        - arg2 flows to B's second parameter

        Always creates parameter edges for call graph edges, creating proxy
        nodes as needed. This ensures cross-file connections exist even when
        per-file analysis doesn't find taint in the caller.
        """
        for edge in cg.edges:
            caller_fn = cg.functions.get(edge.caller)
            callee_fn = cg.functions.get(edge.callee)

            if not caller_fn or not callee_fn:
                continue

            # Map arguments to parameters
            num_args = min(len(edge.arguments), len(callee_fn.params))
            for i in range(num_args):
                arg_expr = edge.arguments[i] if i < len(edge.arguments) else ""
                param_name = callee_fn.params[i] if i < len(callee_fn.params) else ""

                if not arg_expr or not param_name:
                    continue

                # Find or create source node (argument in caller)
                source_id = self._find_node_id_flexible(
                    dfg, arg_expr, edge.file_path, edge.caller
                )
                if not source_id:
                    source_node = DataFlowNode(
                        var_name=arg_expr,
                        file_path=edge.file_path,
                        function_name=edge.caller,
                        line=edge.line,
                        is_tainted=False,
                    )
                    dfg.add_node(source_node)
                    source_id = source_node.node_id

                # Find or create target node (parameter in callee)
                target_id = self._find_node_id_flexible(
                    dfg, param_name, callee_fn.file_path, edge.callee
                )
                if not target_id:
                    target_node = DataFlowNode(
                        var_name=param_name,
                        file_path=callee_fn.file_path,
                        function_name=edge.callee,
                        line=callee_fn.line,
                        is_tainted=False,
                    )
                    dfg.add_node(target_node)
                    target_id = target_node.node_id

                is_cross_file = edge.file_path != callee_fn.file_path

                dfg.add_edge(DataFlowEdge(
                    source_id=source_id,
                    target_id=target_id,
                    flow_type="parameter",
                    file_path=edge.file_path,
                    line=edge.line,
                    is_cross_file=is_cross_file,
                    detail=f"{arg_expr} → {callee_fn.short_name}({param_name})",
                ))

    def _create_return_edges(self, dfg: DataFlowGraph, cg: CallGraph,
                              taint_results: Dict[str, List[Dict]]):
        """Create edges for return value flow.

        When function B returns a value and function A captures it:
        result = B() → the return value flows from B to A's variable.
        """
        for edge in cg.edges:
            callee_fn = cg.functions.get(edge.callee)
            if not callee_fn:
                continue

            # Check if the callee function has any tainted variables
            # (that could flow through the return value)
            callee_tainted = [n for n in dfg.nodes.values()
                              if n.function_name == edge.callee and n.is_tainted]

            for tainted_node in callee_tainted:
                # Check if the tainted variable could be returned
                # (heuristic: if it's the only tainted variable, or matches return patterns)
                # Look for assignment of the call result in the caller
                if edge.arguments:
                    for arg in edge.arguments:
                        source_id = self._find_node_id(dfg, arg, edge.file_path, edge.caller)
                        if source_id and dfg.nodes.get(source_id, {}).is_tainted:
                            # The argument was tainted → callee return is tainted
                            # Create a proxy node for the return value
                            ret_var = f"__return_{callee_fn.short_name}"
                            ret_node = DataFlowNode(
                                var_name=ret_var,
                                file_path=edge.file_path,
                                function_name=edge.caller,
                                line=edge.line,
                                is_tainted=True,
                                taint_sources=tainted_node.taint_sources,
                                taint_path=tainted_node.taint_path + [ret_var],
                            )
                            dfg.add_node(ret_node)
                            dfg.add_edge(DataFlowEdge(
                                source_id=tainted_node.node_id,
                                target_id=ret_node.node_id,
                                flow_type="return",
                                file_path=edge.file_path,
                                line=edge.line,
                                is_cross_file=edge.file_path != callee_fn.file_path,
                                detail=f"{callee_fn.short_name}() → {ret_var}",
                            ))

    def _create_class_attr_edges(self, dfg: DataFlowGraph, cg: CallGraph,
                                  taint_results: Dict[str, List[Dict]]):
        """Create edges for class attribute taint propagation.

        If self.attr is tainted in __init__, it's also tainted in other methods.
        """
        for cls_key, methods in cg.class_methods.items():
            # Find tainted self.attr assignments in any method
            tainted_attrs: Dict[str, DataFlowNode] = {}

            for method_name, method_qname in methods.items():
                # Find tainted nodes in this method
                method_tainted = [n for n in dfg.nodes.values()
                                  if n.function_name == method_qname and n.is_tainted]

                for node in method_tainted:
                    # Check for self.attr patterns
                    if node.var_name.startswith('self.'):
                        attr_name = node.var_name  # e.g., "self.query"
                        if attr_name not in tainted_attrs:
                            tainted_attrs[attr_name] = node

            # Propagate tainted attributes to other methods
            for attr_name, source_node in tainted_attrs.items():
                for method_name, method_qname in methods.items():
                    if method_name == '__init__':
                        continue  # Already handled

                    # Create or update the target node for self.attr in this method
                    target_id = self._find_node_id(dfg, attr_name,
                                                    source_node.file_path, method_qname)
                    if not target_id:
                        target_node = DataFlowNode(
                            var_name=attr_name,
                            file_path=source_node.file_path,
                            function_name=method_qname,
                            line=0,
                            is_tainted=True,
                            taint_sources=source_node.taint_sources,
                            taint_path=source_node.taint_path,
                        )
                        dfg.add_node(target_node)
                        target_id = target_node.node_id

                    dfg.add_edge(DataFlowEdge(
                        source_id=source_node.node_id,
                        target_id=target_id,
                        flow_type="class_attr",
                        file_path=source_node.file_path,
                        line=0,
                        is_cross_file=False,
                        detail=f"{attr_name} propagated from __init__ to {method_name}",
                    ))

    def _create_callback_edges(self, dfg: DataFlowGraph, cg: CallGraph):
        """Create edges for callbacks and higher-order function patterns.

        Best-effort: if a function is passed as an argument to another function,
        and the receiver calls it, create a callback edge.
        """
        for edge in cg.edges:
            if edge.call_type != "callback":
                continue

            # The callee is a method like .then(), .map(), etc.
            # The argument is the callback function
            for arg in edge.arguments:
                # Try to resolve the argument as a function name
                func_def = cg.resolve_function(arg, edge.file_path)
                if func_def:
                    # This function is used as a callback
                    # Create a proxy edge from the callback to its actual body
                    source_id = self._find_node_id(dfg, arg, edge.file_path, edge.caller)
                    if source_id:
                        # The callback function receives data from the caller
                        for param in func_def.params:
                            target_id = self._find_node_id(dfg, param,
                                                            func_def.file_path,
                                                            func_def.qualified_name)
                            if not target_id:
                                target_node = DataFlowNode(
                                    var_name=param,
                                    file_path=func_def.file_path,
                                    function_name=func_def.qualified_name,
                                    line=func_def.line,
                                    is_tainted=dfg.nodes.get(source_id, DataFlowNode(
                                        var_name="", file_path="",
                                        function_name="", line=0)).is_tainted,
                                )
                                dfg.add_node(target_node)
                                target_id = target_node.node_id

                            dfg.add_edge(DataFlowEdge(
                                source_id=source_id,
                                target_id=target_id,
                                flow_type="callback",
                                file_path=edge.file_path,
                                line=edge.line,
                                is_cross_file=edge.file_path != func_def.file_path,
                                detail=f"callback: {arg}({param})",
                            ))

    def _propagate_taint(self, dfg: DataFlowGraph):
        """Propagate taint through the data flow graph.

        Forward propagation: if a source node is tainted and flows to a target,
        the target becomes tainted (unless sanitized).

        Reverse parameter propagation: if a callee's parameter is tainted
        (found by per-file analysis), the caller's argument becomes tainted.
        This is essential for detecting cross-file taint: e.g., tainted data
        in file A is passed to a function in file B where it reaches a sink.
        The per-file analysis of B finds the tainted parameter, and reverse
        propagation marks the caller's argument as tainted, creating the
        cross-file connection.
        """
        changed = True
        iterations = 0
        max_iterations = self.max_depth * max(len(dfg.nodes), 1)

        while changed and iterations < max_iterations:
            changed = False
            iterations += 1

            for edge in dfg.edges:
                source = dfg.nodes.get(edge.source_id)
                target = dfg.nodes.get(edge.target_id)

                if not source or not target:
                    continue

                # Forward propagation: source → target
                if source.is_tainted and not target.is_tainted and not target.is_sanitized:
                    target.is_tainted = True
                    target.taint_sources |= source.taint_sources
                    target.taint_path = source.taint_path + [target.var_name]
                    target.confidence = source.confidence * 0.9  # Slight decay per hop
                    changed = True

                elif source.is_tainted and target.is_tainted:
                    # Union taint sources
                    new_sources = source.taint_sources - target.taint_sources
                    if new_sources:
                        target.taint_sources |= new_sources
                        changed = True

                # Reverse parameter propagation: callee param → caller arg
                # If the callee's parameter (target) is tainted but the caller's
                # argument (source) is not, mark the caller's argument as tainted.
                # This connects per-file taint findings to cross-file flows.
                if edge.flow_type == "parameter" and target.is_tainted and not source.is_tainted:
                    source.is_tainted = True
                    source.taint_sources |= target.taint_sources
                    source.taint_path = target.taint_path + [source.var_name]
                    source.confidence = target.confidence * 0.95
                    changed = True

                # Reverse return propagation: return value → callee's tainted var
                # If the return value (target) is tainted, ensure the callee's
                # variable (source) is also tainted.
                if edge.flow_type == "return" and target.is_tainted and not source.is_tainted:
                    source.is_tainted = True
                    source.taint_sources |= target.taint_sources
                    source.taint_path = [source.var_name] + target.taint_path
                    source.confidence = target.confidence * 0.95
                    changed = True

    def _find_node_id(self, dfg: DataFlowGraph, var_name: str,
                       file_path: str, function_name: str) -> Optional[str]:
        """Find the node ID for a variable in a specific file and function."""
        for nid, node in dfg.nodes.items():
            if node.var_name == var_name and node.file_path == file_path:
                if node.function_name == function_name:
                    return nid
        return None

    def _find_node_id_flexible(self, dfg: DataFlowGraph, var_name: str,
                                file_path: str, function_name: str) -> Optional[str]:
        """Find the node ID for a variable, with flexible matching.

        Tries exact match first, then falls back to:
        1. Match by variable name + filename (ignoring path differences)
        2. Match by variable name + function short name
        """
        # Exact match
        result = self._find_node_id(dfg, var_name, file_path, function_name)
        if result:
            return result

        # Match by variable name + filename component
        base_file = os.path.basename(file_path)
        base_func = function_name.split(':')[-1] if ':' in function_name else function_name

        for nid, node in dfg.nodes.items():
            if node.var_name != var_name:
                continue

            # Check file match by basename
            node_base_file = os.path.basename(node.file_path)
            file_match = (node_base_file == base_file or
                          node.file_path == file_path or
                          node.file_path.endswith(file_path))

            # Check function match
            node_base_func = node.function_name.split(':')[-1] if ':' in node.function_name else node.function_name
            func_match = (node.function_name == function_name or
                          node_base_func == base_func or
                          (base_func == '<unknown>' and node.function_name != 'module') or
                          (node_base_func == '<unknown>' and function_name != 'module'))

            if file_match and func_match:
                return nid

        return None


# ─── Cross-File Taint Propagator ─────────────────────────────

class CrossFileTaintPropagator:
    """Propagates taint across file boundaries using the call graph and DFG.

    Finds cross-file taint paths that single-file analysis misses:
    - User input in file A → passed to function in file B → reaches sink in file B
    - Tainted variable stored as class attribute → accessed in different file's method
    - Return values from tainted functions in other files
    """

    # Sink patterns for cross-file detection
    SINK_PATTERNS = {
        'python': {
            'cursor.execute', 'db.execute', 'connection.execute',
            'os.system', 'os.popen',
            'subprocess.call', 'subprocess.run', 'subprocess.Popen',
            'eval', 'exec',
            'render_template_string', 'mark_safe',
            'pickle.loads', 'yaml.load',
        },
        'javascript': {
            'eval', 'Function', 'setTimeout', 'setInterval',
            'document.write', 'innerHTML',
            'exec', 'execSync', 'spawn', 'execFile',
            'query', 'execute',
        },
    }

    def __init__(self, max_propagation_depth: int = 10):
        self.max_depth = max_propagation_depth

    def propagate(self, dataflow_graph: DataFlowGraph,
                  taint_results: Dict[str, List[Dict]],
                  call_graph: CallGraph) -> List[Dict]:
        """Propagate taint across file boundaries and find cross-file vulnerabilities.

        Args:
            dataflow_graph: The workspace-wide data flow graph.
            taint_results: Per-file taint analysis results.
            call_graph: The workspace-wide call graph.

        Returns:
            List of cross-file taint findings.
        """
        cross_file_findings = []

        # Phase 1: Find tainted nodes that flow across file boundaries
        cross_file_edges = dataflow_graph.get_cross_file_edges()
        tainted_nodes = dataflow_graph.get_tainted_nodes()

        if not cross_file_edges and not tainted_nodes:
            return cross_file_findings

        # Phase 2: For each cross-file parameter flow, check if taint reaches a sink
        for edge in cross_file_edges:
            source_node = dataflow_graph.nodes.get(edge.source_id)
            target_node = dataflow_graph.nodes.get(edge.target_id)

            if not source_node or not target_node:
                continue

            if not source_node.is_tainted:
                continue

            # Build the cross-file taint path
            taint_path = self._build_cross_file_path(
                source_node, target_node, dataflow_graph, call_graph
            )

            # Check if the target node (in another file) reaches a sink
            sink_findings = self._find_sinks_downstream(
                target_node, dataflow_graph, call_graph, taint_results
            )

            for sink_info in sink_findings:
                finding = {
                    "rule_id": f"cross-file-taint-{len(cross_file_findings) + 1}",
                    "rule_name": "Cross-File Taint Propagation",
                    "severity": sink_info.get("severity", "high"),
                    "cwe": sink_info.get("cwe", "CWE-20"),
                    "message": (f"Tainted data from {source_node.file_path} flows to "
                                f"{sink_info.get('file', 'unknown')} via function call"),
                    "file": source_node.file_path,
                    "line": source_node.line,
                    "source": ", ".join(source_node.taint_sources) if source_node.taint_sources else "unknown",
                    "sink": sink_info.get("sink", "unknown"),
                    "tainted_variable": source_node.var_name,
                    "sanitized": target_node.is_sanitized,
                    "sanitizers_found": list(target_node.sanitizers),
                    "confidence": min(source_node.confidence, sink_info.get("confidence", 0.7)),
                    "taint_path": " → ".join(taint_path),
                    "cross_file": True,
                    "cross_file_source": source_node.file_path,
                    "cross_file_sink": sink_info.get("file", ""),
                    "flow_type": edge.flow_type,
                    "propagation_detail": edge.detail,
                }
                cross_file_findings.append(finding)

        # Phase 3: Check for return-value taint propagation
        return_findings = self._check_return_propagation(
            dataflow_graph, call_graph, taint_results
        )
        cross_file_findings.extend(return_findings)

        # Phase 4: Check for class attribute propagation across files
        attr_findings = self._check_class_attr_propagation(
            dataflow_graph, call_graph, taint_results
        )
        cross_file_findings.extend(attr_findings)

        # Deduplicate
        seen = set()
        unique = []
        for f in cross_file_findings:
            key = (f.get('file', ''), f.get('line', 0),
                   f.get('tainted_variable', ''), f.get('sink', ''))
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return unique

    def _build_cross_file_path(self, source_node: DataFlowNode,
                                target_node: DataFlowNode,
                                dfg: DataFlowGraph,
                                cg: CallGraph) -> List[str]:
        """Build a human-readable taint path across files."""
        path = []

        # Source side
        if source_node.taint_path:
            path.extend(source_node.taint_path)
        else:
            path.append(f"{source_node.var_name}@{source_node.file_path}:{source_node.line}")

        # Cross-file edge
        path.append(f"→[{target_node.file_path}]")

        # Target side
        if target_node.taint_path:
            path.extend(target_node.taint_path)
        else:
            path.append(f"{target_node.var_name}@{target_node.file_path}:{target_node.line}")

        return path

    def _find_sinks_downstream(self, start_node: DataFlowNode,
                                dfg: DataFlowGraph, cg: CallGraph,
                                taint_results: Dict[str, List[Dict]]) -> List[Dict]:
        """Find sinks reachable from a tainted node, potentially in other files."""
        sinks = []

        # Check taint results for the target file
        target_file = start_node.file_path
        file_findings = taint_results.get(target_file, [])

        for finding in file_findings:
            # If any finding in the target file has a sink and involves tainted data
            if finding.get("sink") and finding.get("severity") in ("critical", "high", "medium"):
                sinks.append({
                    "sink": finding.get("sink", "unknown"),
                    "file": target_file,
                    "line": finding.get("line", 0),
                    "severity": finding.get("severity", "high"),
                    "confidence": 0.85,
                    "cwe": finding.get("cwe", "CWE-20"),
                })

        # Also check via DFG edges
        visited = set()
        queue = deque([start_node.node_id])
        depth = 0

        while queue and depth < self.max_depth:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            depth += 1

            for edge in dfg.get_successors(current_id):
                target = dfg.nodes.get(edge.target_id)
                if target and target.is_tainted:
                    # Check if this node's variable is used in a sink
                    target_file_findings = taint_results.get(target.file_path, [])
                    for finding in target_file_findings:
                        if (finding.get("tainted_variable") == target.var_name
                                and finding.get("sink")):
                            sinks.append({
                                "sink": finding.get("sink"),
                                "file": target.file_path,
                                "line": finding.get("line", 0),
                                "severity": finding.get("severity", "high"),
                                "confidence": 0.7,
                                "cwe": finding.get("cwe", "CWE-20"),
                            })

                queue.append(edge.target_id)

        return sinks

    def _check_return_propagation(self, dfg: DataFlowGraph, cg: CallGraph,
                                   taint_results: Dict[str, List[Dict]]) -> List[Dict]:
        """Check for taint propagation through function return values."""
        findings = []

        for edge in dfg.edges:
            if edge.flow_type != "return":
                continue

            source = dfg.nodes.get(edge.source_id)
            target = dfg.nodes.get(edge.target_id)

            if not source or not target or not source.is_tainted:
                continue

            # Check if the return value reaches a sink in the caller's file
            caller_file = target.file_path
            file_findings = taint_results.get(caller_file, [])

            for finding in file_findings:
                if finding.get("tainted_variable") == target.var_name and finding.get("sink"):
                    findings.append({
                        "rule_id": f"cross-file-return-{len(findings) + 1}",
                        "rule_name": "Cross-File Return Value Taint",
                        "severity": finding.get("severity", "high"),
                        "cwe": finding.get("cwe", "CWE-20"),
                        "message": (f"Return value from {source.function_name} in "
                                    f"{source.file_path} carries taint to "
                                    f"{target.var_name} in {caller_file}"),
                        "file": source.file_path,
                        "line": source.line,
                        "source": ", ".join(source.taint_sources),
                        "sink": finding.get("sink"),
                        "tainted_variable": target.var_name,
                        "sanitized": target.is_sanitized,
                        "sanitizers_found": list(target.sanitizers),
                        "confidence": 0.75,
                        "taint_path": " → ".join(
                            source.taint_path + [f"return({source.function_name})"] +
                            target.taint_path
                        ),
                        "cross_file": True,
                        "cross_file_source": source.file_path,
                        "cross_file_sink": caller_file,
                        "flow_type": "return",
                    })

        return findings

    def _check_class_attr_propagation(self, dfg: DataFlowGraph, cg: CallGraph,
                                       taint_results: Dict[str, List[Dict]]) -> List[Dict]:
        """Check for taint propagation through class attributes across files."""
        findings = []

        for edge in dfg.edges:
            if edge.flow_type != "class_attr":
                continue

            source = dfg.nodes.get(edge.source_id)
            target = dfg.nodes.get(edge.target_id)

            if not source or not target or not source.is_tainted:
                continue

            # Check if the class attribute reaches a sink in the target method
            target_file = target.file_path
            file_findings = taint_results.get(target_file, [])

            for finding in file_findings:
                if finding.get("tainted_variable") == target.var_name and finding.get("sink"):
                    findings.append({
                        "rule_id": f"cross-file-attr-{len(findings) + 1}",
                        "rule_name": "Cross-File Class Attribute Taint",
                        "severity": finding.get("severity", "high"),
                        "cwe": finding.get("cwe", "CWE-20"),
                        "message": (f"Class attribute {source.var_name} set in "
                                    f"{source.file_path} carries taint to "
                                    f"{target.var_name} in {target_file}"),
                        "file": source.file_path,
                        "line": source.line,
                        "source": ", ".join(source.taint_sources),
                        "sink": finding.get("sink"),
                        "tainted_variable": target.var_name,
                        "sanitized": target.is_sanitized,
                        "sanitizers_found": list(target.sanitizers),
                        "confidence": 0.65,
                        "taint_path": " → ".join(
                            source.taint_path +
                            [f"self.{source.var_name}", target.var_name]
                        ),
                        "cross_file": True,
                        "cross_file_source": source.file_path,
                        "cross_file_sink": target_file,
                        "flow_type": "class_attr",
                    })

        return findings


# ─── Main Engine ──────────────────────────────────────────────

class EnhancedDataflowEngine:
    """Enhanced cross-file dataflow engine that integrates call graph resolution
    with per-file AST taint analysis.

    Usage:
        engine = EnhancedDataflowEngine(workspace)
        result = engine.analyze()
    """

    def __init__(self, workspace: str, rules_dir: Optional[str] = None,
                 max_files: int = 3000, timeout_sec: float = 120.0,
                 max_depth: int = 15):
        self.workspace = os.path.abspath(workspace)
        self.rules_dir = rules_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "rules"
        )
        self.max_files = max_files
        self.timeout_sec = timeout_sec
        self.max_depth = max_depth

    def analyze(self, languages: List[str] = None,
                source_filter: str = None,
                sink_filter: str = None) -> Dict[str, Any]:
        """Run the full enhanced cross-file dataflow analysis.

        Args:
            languages: List of languages to analyze. None = auto-detect.
            source_filter: Filter by source type (e.g., "user_input").
            sink_filter: Filter by sink type (e.g., "db_query").

        Returns:
            Dict with findings, call graph stats, data flow graph stats,
            and recommendations.
        """
        start_time = time.time()

        # Phase 1: Build call graph
        logger.info("[EnhancedDataflow] Phase 1: Building call graph...")
        cg_builder = CallGraphBuilder(
            max_files=self.max_files,
            timeout_sec=self.timeout_sec * 0.4,  # 40% budget for call graph
        )
        call_graph = cg_builder.build(self.workspace, languages=languages)
        cg_stats = call_graph.get_stats()

        elapsed_cg = time.time() - start_time
        logger.info(f"[EnhancedDataflow] Call graph built in {elapsed_cg:.1f}s: "
                     f"{cg_stats['total_functions']} functions, "
                     f"{cg_stats['total_edges']} edges")

        if time.time() - start_time > self.timeout_sec:
            return self._timeout_result(cg_stats, elapsed_cg)

        # Phase 2: Run per-file taint analysis
        logger.info("[EnhancedDataflow] Phase 2: Running per-file taint analysis...")
        taint_results = self._run_taint_analysis(call_graph, languages)
        total_taint_findings = sum(len(v) for v in taint_results.values())
        logger.info(f"[EnhancedDataflow] Per-file taint: {total_taint_findings} findings "
                     f"across {len(taint_results)} files")

        if time.time() - start_time > self.timeout_sec:
            return self._partial_result(cg_stats, taint_results, start_time)

        # Phase 3: Build data flow graph
        logger.info("[EnhancedDataflow] Phase 3: Building data flow graph...")
        dfg_builder = DataFlowGraphBuilder(max_depth=self.max_depth)
        dfg = dfg_builder.build(call_graph, taint_results, self.workspace)
        dfg_stats = {
            "total_nodes": len(dfg.nodes),
            "total_edges": len(dfg.edges),
            "tainted_nodes": len(dfg.get_tainted_nodes()),
            "cross_file_edges": len(dfg.get_cross_file_edges()),
        }
        logger.info(f"[EnhancedDataflow] DFG built: {dfg_stats['total_nodes']} nodes, "
                     f"{dfg_stats['total_edges']} edges, "
                     f"{dfg_stats['cross_file_edges']} cross-file edges")

        if time.time() - start_time > self.timeout_sec:
            return self._partial_result(cg_stats, taint_results, start_time,
                                         dfg_stats=dfg_stats)

        # Phase 4: Cross-file taint propagation
        logger.info("[EnhancedDataflow] Phase 4: Cross-file taint propagation...")
        propagator = CrossFileTaintPropagator(max_propagation_depth=self.max_depth)
        cross_file_findings = propagator.propagate(dfg, taint_results, call_graph)
        logger.info(f"[EnhancedDataflow] Cross-file findings: {len(cross_file_findings)}")

        # Phase 5: Combine all findings
        all_findings = []
        for file_path, findings in taint_results.items():
            all_findings.extend(findings)
        all_findings.extend(cross_file_findings)

        # Deduplicate
        seen = set()
        unique_findings = []
        for f in all_findings:
            key = (f.get('file', ''), f.get('line', 0),
                   f.get('rule_id', ''), f.get('tainted_variable', ''))
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        # Apply filters
        if source_filter:
            unique_findings = [f for f in unique_findings
                               if source_filter in f.get("source", "").lower()
                               or source_filter in f.get("taint_path", "").lower()]
        if sink_filter:
            unique_findings = [f for f in unique_findings
                               if sink_filter in f.get("sink", "").lower()
                               or sink_filter in f.get("taint_path", "").lower()]

        # Sort by severity
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        unique_findings.sort(
            key=lambda f: severity_order.get(f.get("severity", "medium"), 99)
        )

        # Compute stats
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        by_rule = {}
        cross_file_count = 0
        for f in unique_findings:
            sev = f.get("severity", "medium")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            rule_name = f.get("rule_name", "unknown")
            by_rule[rule_name] = by_rule.get(rule_name, 0) + 1
            if f.get("cross_file"):
                cross_file_count += 1

        risk = "critical" if by_severity.get("critical", 0) > 0 else \
               "high" if by_severity.get("high", 0) > 0 else \
               "medium" if by_severity.get("medium", 0) > 0 else "low"

        elapsed = time.time() - start_time

        return {
            "status": "ok",
            "engine": "callgraph_engine",
            "risk": risk,
            "total_findings": len(unique_findings),
            "findings": unique_findings,
            "stats": {
                "call_graph": cg_stats,
                "data_flow_graph": dfg_stats,
                "total_taint_findings": total_taint_findings,
                "cross_file_findings": cross_file_count,
                "files_analyzed": len(taint_results),
                "elapsed_seconds": round(elapsed, 2),
                "by_severity": by_severity,
                "by_rule": by_rule,
                "tree_sitter_available": TREE_SITTER_AVAILABLE,
            },
            "recommendations": self._generate_recommendations(
                unique_findings, call_graph
            ),
            "actionable_items": self._generate_actionable_items(unique_findings),
        }

    def _run_taint_analysis(self, call_graph: CallGraph,
                             languages: List[str] = None) -> Dict[str, List[Dict]]:
        """Run per-file taint analysis using the AST taint engine.

        Returns:
            Dict mapping file_path → list of findings.
        """
        taint_results: Dict[str, List[Dict]] = {}

        # Try to use the AST taint engine
        ast_available = False
        try:
            from ast_taint_engine import ASTTaintAnalyzer, is_available as ast_is_available
            ast_available = ast_is_available()
        except ImportError:
            pass

        if not ast_available:
            # Fall back to regex-based analysis
            return self._run_regex_taint(call_graph)

        # Load rules
        rules = self._load_rules()
        if not rules:
            return taint_results

        # Analyze each file
        for file_path, func_names in call_graph.file_functions.items():
            abs_path = os.path.join(self.workspace, file_path)
            content = safe_read_file(abs_path)
            if content is None:
                continue

            lang = _detect_language(abs_path)
            if not lang:
                continue
            if languages and lang not in languages:
                continue

            lang_rules = [r for r in rules if r.get('language', '').lower() == lang.lower()]
            if not lang_rules:
                continue

            try:
                analyzer = ASTTaintAnalyzer(rules=lang_rules, language=lang)
                findings = analyzer.analyze_file(abs_path, content=content,
                                                  language=lang, rules=lang_rules)
                if findings:
                    taint_results[file_path] = findings
            except Exception as e:
                logger.debug(f"[EnhancedDataflow] Taint analysis failed for {file_path}: {e}")

        return taint_results

    def _run_regex_taint(self, call_graph: CallGraph) -> Dict[str, List[Dict]]:
        """Fallback: Run regex-based taint analysis per file."""
        taint_results: Dict[str, List[Dict]] = {}
        rules = self._load_rules()

        if not rules:
            return taint_results

        for file_path, func_names in call_graph.file_functions.items():
            abs_path = os.path.join(self.workspace, file_path)
            content = safe_read_file(abs_path)
            if content is None:
                continue

            lang = _detect_language(abs_path)
            if not lang:
                continue

            lang_rules = [r for r in rules if r.get('language', '').lower() == lang.lower()]
            if not lang_rules:
                continue

            findings = self._simple_taint_scan(file_path, content, lang_rules, lang)
            if findings:
                taint_results[file_path] = findings

        return taint_results

    def _simple_taint_scan(self, rel_path: str, content: str,
                            rules: List[Dict], language: str) -> List[Dict]:
        """Simple regex-based taint scan for fallback."""
        findings = []
        lines = content.split('\n')

        for rule in rules:
            sources = rule.get('sources', [])
            sinks = rule.get('sinks', [])
            sanitizers = rule.get('sanitizers', [])

            # Find sources
            tainted_vars: Dict[str, Dict] = {}
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#'):
                    continue

                for source in sources:
                    source_name = source.split('.')[-1] if '.' in source else source
                    if source in stripped or source_name in stripped:
                        m = re.match(r'(?:const|let|var)?\s*(\w+)\s*[=:]\s*', stripped)
                        if m:
                            var_name = m.group(1)
                            tainted_vars[var_name] = {
                                "source": source,
                                "line": i,
                                "sanitized": False,
                                "sanitizers": [],
                            }

            # Check sanitization
            for i, line in enumerate(lines, 1):
                for sanitizer in sanitizers:
                    san_name = sanitizer.split('.')[-1] if '.' in sanitizer else sanitizer
                    if san_name in line:
                        for var_name in tainted_vars:
                            if var_name in line:
                                tainted_vars[var_name]["sanitized"] = True
                                tainted_vars[var_name]["sanitizers"].append(san_name)

            # Check sinks
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                for sink in sinks:
                    sink_name = sink.split('.')[-1] if '.' in sink else sink
                    if sink in stripped or sink_name + '(' in stripped:
                        for var_name, info in tainted_vars.items():
                            if var_name in stripped:
                                findings.append({
                                    "rule_id": rule.get('id', 'unknown'),
                                    "rule_name": rule.get('name', 'Unknown'),
                                    "severity": rule.get('severity', 'medium') if not info["sanitized"] else "info",
                                    "cwe": rule.get('cwe', ''),
                                    "message": rule.get('message', ''),
                                    "file": rel_path,
                                    "line": i,
                                    "source": info["source"],
                                    "sink": sink_name,
                                    "tainted_variable": var_name,
                                    "sanitized": info["sanitized"],
                                    "sanitizers_found": info["sanitizers"],
                                    "confidence": "medium",
                                    "taint_path": f"{info['source']} → {var_name} → {sink_name}",
                                    "engine": "callgraph_regex",
                                })

        return findings

    def _load_rules(self) -> List[Dict]:
        """Load YAML security rules."""
        if not os.path.isdir(self.rules_dir):
            return []

        rules = []
        for fname in sorted(os.listdir(self.rules_dir)):
            if not fname.endswith(('.yaml', '.yml')):
                continue
            fpath = os.path.join(self.rules_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and 'rules' in data:
                    for rule in data['rules']:
                        rule['_source_file'] = fname
                        rules.append(rule)
            except Exception as e:
                logger.warning(f"Failed to load rule file {fname}: {e}")

        return rules

    def _generate_recommendations(self, findings: List[Dict],
                                   call_graph: CallGraph) -> List[str]:
        """Generate actionable recommendations from findings."""
        recs = []

        if not findings:
            recs.append("No taint violations found. Data flow appears safe.")
            return recs

        critical = [f for f in findings if f.get("severity") == "critical"]
        cross_file = [f for f in findings if f.get("cross_file")]
        unsanitized = [f for f in findings if not f.get("sanitized")]

        if critical:
            recs.append(f"URGENT: {len(critical)} critical vulnerabilities — fix immediately")
            for c in critical[:3]:
                recs.append(f"  → {c['rule_name']}: {c.get('taint_path', 'unknown path')}")

        if cross_file:
            recs.append(
                f"{len(cross_file)} cross-file taint paths detected — "
                f"requires multi-file fix strategy"
            )
            for cf in cross_file[:3]:
                src = cf.get('cross_file_source', '?')
                snk = cf.get('cross_file_sink', '?')
                recs.append(f"  → {src} → {snk}: {cf.get('tainted_variable', '?')}")

        if unsanitized:
            recs.append(
                f"{len(unsanitized)} unsanitized taint paths — "
                f"add input validation/sanitization"
            )

        cg_stats = call_graph.get_stats()
        if cg_stats['unresolved_calls'] > cg_stats['total_edges'] * 0.3:
            recs.append(
                f"{cg_stats['unresolved_calls']} unresolved calls — "
                f"consider adding type annotations for better analysis"
            )

        return recs[:10]

    def _generate_actionable_items(self, findings: List[Dict]) -> List[Dict]:
        """Generate actionable items for AI-assisted fixing."""
        items = []
        crit_high = [f for f in findings
                     if f.get("severity") in ("critical", "high")]

        for f in crit_high[:10]:
            action = "FIX_IMMEDIATELY" if f.get("severity") == "critical" else "REVIEW_AND_FIX"
            items.append({
                "action": action,
                "rule": f.get("rule_id", ""),
                "file": f.get("file", ""),
                "line": f.get("line", 0),
                "message": f.get("message", ""),
                "taint_path": f.get("taint_path", ""),
                "cross_file": f.get("cross_file", False),
                "cross_file_source": f.get("cross_file_source", ""),
                "cross_file_sink": f.get("cross_file_sink", ""),
            })

        return items

    def _timeout_result(self, cg_stats: Dict, elapsed: float) -> Dict[str, Any]:
        """Return a result indicating the analysis timed out."""
        return {
            "status": "timeout",
            "engine": "callgraph_engine",
            "risk": "unknown",
            "total_findings": 0,
            "findings": [],
            "stats": {
                "call_graph": cg_stats,
                "elapsed_seconds": round(elapsed, 2),
                "timed_out": True,
            },
            "recommendations": [
                "Analysis timed out during call graph construction. "
                "Try reducing --max-files or increasing --timeout."
            ],
        }

    def _partial_result(self, cg_stats: Dict,
                         taint_results: Dict[str, List[Dict]],
                         start_time: float,
                         dfg_stats: Dict = None) -> Dict[str, Any]:
        """Return a partial result when time runs out mid-analysis."""
        all_findings = []
        for findings in taint_results.values():
            all_findings.extend(findings)

        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in all_findings:
            sev = f.get("severity", "medium")
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "status": "partial",
            "engine": "callgraph_engine",
            "risk": "critical" if by_severity.get("critical", 0) > 0 else
                    "high" if by_severity.get("high", 0) > 0 else "medium",
            "total_findings": len(all_findings),
            "findings": all_findings,
            "stats": {
                "call_graph": cg_stats,
                "data_flow_graph": dfg_stats or {},
                "total_taint_findings": len(all_findings),
                "cross_file_findings": 0,
                "files_analyzed": len(taint_results),
                "elapsed_seconds": round(time.time() - start_time, 2),
                "by_severity": by_severity,
                "partial": True,
            },
            "recommendations": [
                "Analysis incomplete — time budget expired. "
                "Cross-file propagation was not performed. "
                "Try increasing --timeout."
            ],
        }


# ─── Convenience Functions ────────────────────────────────────

def analyze_with_callgraph(workspace: str, language: str = None,
                            rules_dir: str = None,
                            max_files: int = 3000,
                            timeout_sec: float = 120.0,
                            max_depth: int = 15,
                            source_filter: str = None,
                            sink_filter: str = None) -> Dict[str, Any]:
    """Convenience function to run enhanced cross-file dataflow analysis.

    Args:
        workspace: Path to workspace root.
        language: Filter to a specific language. None = auto-detect.
        rules_dir: Directory containing YAML rule files.
        max_files: Maximum number of files to scan.
        timeout_sec: Maximum seconds for the analysis.
        max_depth: Maximum data flow chain depth.
        source_filter: Filter by source type.
        sink_filter: Filter by sink type.

    Returns:
        Dict with findings and analysis results.
    """
    languages = [language] if language else None
    engine = EnhancedDataflowEngine(
        workspace=workspace,
        rules_dir=rules_dir,
        max_files=max_files,
        timeout_sec=timeout_sec,
        max_depth=max_depth,
    )
    return engine.analyze(
        languages=languages,
        source_filter=source_filter,
        sink_filter=sink_filter,
    )


def build_call_graph(workspace: str, language: str = None,
                      max_files: int = 3000,
                      timeout_sec: float = 60.0) -> CallGraph:
    """Convenience function to build just the call graph.

    Useful for visualization, dependency analysis, or custom analysis.
    """
    languages = [language] if language else None
    builder = CallGraphBuilder(max_files=max_files, timeout_sec=timeout_sec)
    return builder.build(workspace, languages=languages)


def is_available() -> bool:
    """Check if the callgraph engine is available (requires tree-sitter)."""
    return TREE_SITTER_AVAILABLE


def get_supported_languages() -> List[str]:
    """Get list of languages supported by the callgraph engine."""
    if not TREE_SITTER_AVAILABLE:
        return []
    supported = []
    for lang in ('python', 'javascript', 'typescript', 'tsx'):
        if _get_parser(lang):
            supported.append(lang)
    return supported
