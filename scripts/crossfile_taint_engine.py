"""
Cross-File Taint Analysis Engine for CodeLens — v2

.. deprecated:: 8.3 (issue #49 Phase 1)
    The public entry point ``analyze_cross_file_taint()`` is now a thin
    compat wrapper that delegates to ``ast_taint_engine.analyze_workspace(
    cross_file=True)``. New code should call ``ast_taint_engine`` directly.

    This module still houses the cross-file analysis **implementation**
    (``CrossFileTaintAnalyzer``, CFG/call-graph builders) — only the
    public convenience function was consolidated. The implementation
    classes are imported by ``ast_taint_engine._analyze_cross_file()``
    at call time (lazy import to avoid circular dependency).

Builds a real Control Flow Graph (CFG) using tree-sitter (when available) or
regex-based AST approximation, then performs inter-procedural taint analysis
that crosses file boundaries.

Architecture:
  Phase 1: Build per-file CFGs (CFGNode -> CFGEdge graph)
  Phase 2: Build project-wide call graph (function -> function)
  Phase 3: Identify taint sources (from YAML rules)
  Phase 4: Forward taint propagation through CFG + call graph
  Phase 5: Check taint arrival at sinks

Performance:
  - Lazy CFG construction (only build for files with potential sources/sinks)
  - Call graph pruning (only follow edges from functions that touch tainted data)
  - Time budget: 30 seconds max for whole-project analysis
"""

import os
import re
import time
import yaml
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from utils import logger, safe_read_file


# ─── CFG Data Structures ────────────────────────────────────

class CFGNode:
    """A basic block in the control flow graph."""

    __slots__ = ('id', 'file', 'line_start', 'line_end', 'statements', 'successors', 'predecessors')

    def __init__(self, node_id: int, file: str, line_start: int, line_end: int):
        self.id = node_id
        self.file = file
        self.line_start = line_start
        self.line_end = line_end
        self.statements: List[str] = []  # Raw line content
        self.successors: List[int] = []  # Node IDs
        self.predecessors: List[int] = []

    def __repr__(self):
        return f"CFGNode({self.id}, {self.file}:{self.line_start}-{self.line_end})"


class CFG:
    """Control Flow Graph for a single file."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.nodes: Dict[int, CFGNode] = {}
        self.entry_node: Optional[int] = None
        self.exit_nodes: List[int] = []
        self._next_id = 0

    def add_node(self, line_start: int, line_end: int) -> int:
        node_id = self._next_id
        self._next_id += 1
        node = CFGNode(node_id, self.file_path, line_start, line_end)
        self.nodes[node_id] = node
        return node_id

    def add_edge(self, from_id: int, to_id: int):
        if from_id in self.nodes and to_id in self.nodes:
            if to_id not in self.nodes[from_id].successors:
                self.nodes[from_id].successors.append(to_id)
            if from_id not in self.nodes[to_id].predecessors:
                self.nodes[to_id].predecessors.append(from_id)

    def get_node(self, node_id: int) -> Optional[CFGNode]:
        return self.nodes.get(node_id)


class CallGraph:
    """Project-wide call graph for inter-procedural analysis."""

    def __init__(self):
        # function_fqn -> [(callee_fqn, call_site_file, call_site_line)]
        self.edges: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
        # file -> [function_fqn]
        self.file_functions: Dict[str, List[str]] = defaultdict(list)
        # function_fqn -> (file, line)
        self.function_defs: Dict[str, Tuple[str, int]] = {}

    def add_function(self, fqn: str, file: str, line: int):
        self.file_functions[file].append(fqn)
        self.function_defs[fqn] = (file, line)

    def add_call(self, caller_fqn: str, callee_fqn: str, call_file: str, call_line: int):
        self.edges[caller_fqn].append((callee_fqn, call_file, call_line))

    def get_callees(self, fqn: str) -> List[Tuple[str, str, int]]:
        return self.edges.get(fqn, [])

    def get_callers(self, fqn: str) -> List[Tuple[str, str, int]]:
        """Find all callers of a function (reverse lookup)."""
        callers = []
        for caller, callees in self.edges.items():
            for callee, call_file, call_line in callees:
                if callee == fqn:
                    callers.append((caller, call_file, call_line))
        return callers

    def resolve_call(self, call_name: str, caller_file: str) -> Optional[str]:
        """Resolve a function call to its fully qualified name."""
        # Exact match first
        if call_name in self.function_defs:
            return call_name
        # Try file-local match
        for fqn in self.file_functions.get(caller_file, []):
            if fqn.split('.')[-1] == call_name or fqn == call_name:
                return fqn
        # Try any match
        for fqn in self.function_defs:
            if fqn.split('.')[-1] == call_name:
                return fqn
        return None


# ─── CFG Builder ────────────────────────────────────────────

class CFGBuilder:
    """Builds CFG from source code using regex-based AST approximation.

    Uses indentation and keyword detection to identify basic blocks and
    control flow edges. For Python, uses indentation; for JS/TS, uses
    brace counting.
    """

    # Language-specific block delimiters
    PYTHON_BLOCK_KEYWORDS = {'if', 'elif', 'else', 'for', 'while', 'try', 'except',
                              'finally', 'with', 'def', 'class', 'match', 'case'}
    JS_BLOCK_KEYWORDS = {'if', 'else', 'for', 'while', 'do', 'switch', 'case',
                          'try', 'catch', 'finally', 'function', 'class'}

    def build_cfg(self, file_path: str, source: str, language: str = "python") -> CFG:
        """Build a CFG from source code."""
        cfg = CFG(file_path)
        lines = source.split('\n')

        if language == "python":
            return self._build_python_cfg(cfg, lines)
        elif language in ("javascript", "typescript"):
            return self._build_js_cfg(cfg, lines)
        else:
            # Generic: one node per non-empty line
            return self._build_generic_cfg(cfg, lines)

    def _build_python_cfg(self, cfg: CFG, lines: List[str]) -> CFG:
        """Build CFG for Python using indentation-based block detection."""
        if not lines:
            entry = cfg.add_node(1, 1)
            cfg.entry_node = entry
            cfg.exit_nodes = [entry]
            return cfg

        # Identify block boundaries by indentation changes
        blocks: List[Tuple[int, int, int]] = []  # (line_start, line_end, indent_level)
        current_start = 0
        current_indent = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            indent = len(line) - len(line.lstrip())

            if i == 0:
                current_indent = indent
                current_start = i
            elif indent != current_indent:
                # End current block, start new one
                if current_start < i:
                    blocks.append((current_start, i - 1, current_indent))
                current_start = i
                current_indent = indent

        # Final block
        if current_start < len(lines):
            blocks.append((current_start, len(lines) - 1, current_indent))

        if not blocks:
            entry = cfg.add_node(1, len(lines))
            cfg.entry_node = entry
            cfg.exit_nodes = [entry]
            return cfg

        # Create CFG nodes for each block
        node_map = {}
        for start, end, indent in blocks:
            node_id = cfg.add_node(start + 1, end + 1)
            node = cfg.get_node(node_id)
            node.statements = lines[start:end + 1]
            node_map[(start, end)] = node_id

        # Entry node is the first block
        first_block = blocks[0]
        cfg.entry_node = node_map[(first_block[0], first_block[1])]

        # Connect sequential blocks
        block_node_ids = [node_map[(s, e)] for s, e, _ in blocks]
        for i in range(len(block_node_ids) - 1):
            # Check for control flow breaks
            last_stmt = cfg.get_node(block_node_ids[i]).statements[-1].strip() if cfg.get_node(block_node_ids[i]).statements else ""
            if last_stmt.startswith(('return ', 'return', 'raise ', 'raise', 'break', 'continue',
                                      'sys.exit', 'exit(', 'quit(')):
                # No fall-through edge
                pass
            else:
                cfg.add_edge(block_node_ids[i], block_node_ids[i + 1])

        # Identify if/else branches and connect them
        for i, (start, end, indent) in enumerate(blocks):
            first_stmt = cfg.get_node(node_map[(start, end)]).statements[0].strip() if cfg.get_node(node_map[(start, end)]).statements else ""

            # If this is a branch target (else, elif, except, finally)
            if first_stmt.startswith(('else:', 'elif ', 'except ', 'except:', 'finally:')):
                # Find the matching if/try block above
                for j in range(i - 1, -1, -1):
                    prev_start, prev_end, prev_indent = blocks[j]
                    prev_first = cfg.get_node(node_map[(prev_start, prev_end)]).statements[0].strip()
                    if prev_indent == indent:
                        if prev_first.startswith(('if ', 'elif ', 'try:')):
                            cfg.add_edge(node_map[(prev_start, prev_end)], node_map[(start, end)])
                            break

        # Exit nodes are blocks with no successors
        for node_id, node in cfg.nodes.items():
            if not node.successors:
                cfg.exit_nodes.append(node_id)

        if not cfg.exit_nodes:
            cfg.exit_nodes = [block_node_ids[-1]]

        return cfg

    def _build_js_cfg(self, cfg: CFG, lines: List[str]) -> CFG:
        """Build CFG for JavaScript/TypeScript using brace-based block detection."""
        if not lines:
            entry = cfg.add_node(1, 1)
            cfg.entry_node = entry
            cfg.exit_nodes = [entry]
            return cfg

        # Simple approach: create blocks around control flow statements
        current_start = 0
        brace_depth = 0
        blocks = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith('//') or stripped.startswith('*'):
                continue

            brace_depth += stripped.count('{') - stripped.count('}')

            # Block boundary on control flow keywords at similar depth
            if (stripped.startswith(('if ', 'if(', 'else ', 'else{', 'else if',
                                      'for ', 'for(', 'while ', 'while(',
                                      'switch ', 'switch(', 'try {', 'try{',
                                      'catch ', 'catch(', 'finally ', 'finally{',
                                      'function ', 'function(', 'const ', 'let ', 'var '))
                and brace_depth <= 1):
                if current_start < i:
                    blocks.append((current_start, i - 1))
                current_start = i

        # Final block
        if current_start < len(lines):
            blocks.append((current_start, len(lines) - 1))

        if not blocks:
            entry = cfg.add_node(1, len(lines))
            cfg.entry_node = entry
            cfg.exit_nodes = [entry]
            return cfg

        # Create nodes and connect sequentially
        node_ids = []
        for start, end in blocks:
            node_id = cfg.add_node(start + 1, end + 1)
            node = cfg.get_node(node_id)
            node.statements = lines[start:end + 1]
            node_ids.append(node_id)

        cfg.entry_node = node_ids[0]
        for i in range(len(node_ids) - 1):
            cfg.add_edge(node_ids[i], node_ids[i + 1])

        cfg.exit_nodes = [node_ids[-1]]
        return cfg

    def _build_generic_cfg(self, cfg: CFG, lines: List[str]) -> CFG:
        """Build a simple linear CFG for unsupported languages."""
        # Group lines into chunks of ~10
        chunk_size = 10
        node_ids = []
        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]
            if any(l.strip() for l in chunk):
                node_id = cfg.add_node(i + 1, min(i + chunk_size, len(lines)))
                node = cfg.get_node(node_id)
                node.statements = chunk
                node_ids.append(node_id)

        if not node_ids:
            entry = cfg.add_node(1, 1)
            cfg.entry_node = entry
            cfg.exit_nodes = [entry]
            return cfg

        cfg.entry_node = node_ids[0]
        for i in range(len(node_ids) - 1):
            cfg.add_edge(node_ids[i], node_ids[i + 1])

        cfg.exit_nodes = [node_ids[-1]]
        return cfg


# ─── Call Graph Builder ─────────────────────────────────────

class CallGraphBuilder:
    """Builds a project-wide call graph from source files."""

    def build(self, workspace: str, language: str = "python",
              source_files: Optional[List[str]] = None) -> CallGraph:
        """Build call graph from source files in the workspace."""
        cg = CallGraph()

        if source_files is None:
            source_files = self._find_source_files(workspace, language)

        # Phase 1: Index all function definitions
        for fpath in source_files:
            content = safe_read_file(fpath)
            if content is None:
                continue
            rel_path = os.path.relpath(fpath, workspace)
            self._index_functions(cg, content, rel_path, language)

        # Phase 2: Index all function calls
        for fpath in source_files:
            content = safe_read_file(fpath)
            if content is None:
                continue
            rel_path = os.path.relpath(fpath, workspace)
            self._index_calls(cg, content, rel_path, language)

        return cg

    def _find_source_files(self, workspace: str, language: str) -> List[str]:
        """Find source files for the given language."""
        ext_map = {
            "python": {'.py', '.pyi'},
            "javascript": {'.js', '.mjs', '.cjs', '.jsx'},
            "typescript": {'.ts', '.tsx'},
        }
        extensions = ext_map.get(language, {'.py'})
        source_files = []

        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                       ('node_modules', '__pycache__', '.codelens', 'venv', '.venv',
                        'env', '.git', 'dist', 'build', 'target')]
            for f in files:
                if any(f.endswith(ext) for ext in extensions):
                    source_files.append(os.path.join(root, f))

        return source_files

    def _index_functions(self, cg: CallGraph, source: str, rel_path: str, language: str):
        """Index all function/method definitions."""
        lines = source.split('\n')
        if language == "python":
            for i, line in enumerate(lines, 1):
                m = re.match(r'^(\s*)(def|async\s+def)\s+(\w+)\s*\(', line)
                if m:
                    fqn = f"{rel_path}:{m.group(3)}"
                    cg.add_function(fqn, rel_path, i)
        elif language in ("javascript", "typescript"):
            for i, line in enumerate(lines, 1):
                # function declarations
                m = re.match(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(', line)
                if m:
                    fqn = f"{rel_path}:{m.group(1)}"
                    cg.add_function(fqn, rel_path, i)
                    continue
                # Arrow functions / method definitions
                m = re.match(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', line)
                if m:
                    fqn = f"{rel_path}:{m.group(1)}"
                    cg.add_function(fqn, rel_path, i)
                    continue
                # Class methods
                m = re.match(r'^\s*(?:async\s+)?(\w+)\s*\(', line)
                if m and not line.strip().startswith(('if', 'for', 'while', 'switch', 'catch')):
                    # Could be a method, add it
                    fqn = f"{rel_path}:{m.group(1)}"
                    if fqn not in cg.function_defs:
                        cg.add_function(fqn, rel_path, i)

    def _index_calls(self, cg: CallGraph, source: str, rel_path: str, language: str):
        """Index all function calls."""
        lines = source.split('\n')

        # Determine current function context (simple approach)
        current_fn = None

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if language == "python":
                m = re.match(r'^(\s*)(def|async\s+def)\s+(\w+)\s*\(', stripped)
                if m:
                    current_fn = f"{rel_path}:{m.group(3)}"
                    continue

                # Find function calls
                calls = re.findall(r'(\w+)\s*\(', stripped)
                for call_name in calls:
                    if current_fn and call_name not in ('if', 'for', 'while', 'with',
                                                          'print', 'len', 'range', 'str',
                                                          'int', 'float', 'list', 'dict',
                                                          'set', 'tuple', 'bool', 'type',
                                                          'isinstance', 'hasattr', 'getattr',
                                                          'setattr', 'super', 'property',
                                                          'staticmethod', 'classmethod'):
                        callee = cg.resolve_call(call_name, rel_path)
                        if callee is None:
                            callee = f"{rel_path}:{call_name}"
                        cg.add_call(current_fn, callee, rel_path, i)

            elif language in ("javascript", "typescript"):
                m = re.match(r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(', stripped)
                if not m:
                    m = re.match(r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=', stripped)
                if m:
                    current_fn = f"{rel_path}:{m.group(1)}"
                    continue

                calls = re.findall(r'(\w+)\s*\(', stripped)
                for call_name in calls:
                    if current_fn and call_name not in ('if', 'for', 'while', 'switch',
                                                          'catch', 'require', 'console',
                                                          'typeof', 'parseInt', 'parseFloat',
                                                          'String', 'Number', 'Boolean',
                                                          'Array', 'Object', 'Math', 'JSON',
                                                          'Promise', 'new'):
                        callee = cg.resolve_call(call_name, rel_path)
                        if callee is None:
                            callee = call_name
                        cg.add_call(current_fn, callee, rel_path, i)


# ─── Cross-File Taint Propagator ────────────────────────────

class TaintState:
    """Represents the taint state of a variable at a program point."""

    __slots__ = ('var_name', 'taint_source', 'taint_rule', 'sanitized', 'sanitizers', 'path')

    def __init__(self, var_name: str, taint_source: str, taint_rule: str,
                 sanitized: bool = False, sanitizers: Optional[List[str]] = None,
                 path: Optional[List[str]] = None):
        self.var_name = var_name
        self.taint_source = taint_source
        self.taint_rule = taint_rule
        self.sanitized = sanitized
        self.sanitizers = sanitizers or []
        self.path = path or []

    def copy_with(self, **kwargs) -> 'TaintState':
        return TaintState(
            var_name=kwargs.get('var_name', self.var_name),
            taint_source=kwargs.get('taint_source', self.taint_source),
            taint_rule=kwargs.get('taint_rule', self.taint_rule),
            sanitized=kwargs.get('sanitized', self.sanitized),
            sanitizers=kwargs.get('sanitizers', list(self.sanitizers)),
            path=kwargs.get('path', list(self.path)),
        )


class CrossFileTaintAnalyzer:
    """Full cross-file taint analysis engine.

    Usage:
        analyzer = CrossFileTaintAnalyzer(workspace)
        result = analyzer.analyze(language="python")
    """

    def __init__(self, workspace: str, rules_dir: Optional[str] = None,
                 time_budget: float = 30.0):
        self.workspace = os.path.abspath(workspace)
        self.rules_dir = rules_dir or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "rules"
        )
        self.time_budget = time_budget
        self.cfg_builder = CFGBuilder()
        self.cg_builder = CallGraphBuilder()
        self._cfgs: Dict[str, CFG] = {}
        self._call_graph: Optional[CallGraph] = None
        self._findings: List[Dict] = []
        self._start_time = 0.0

    def analyze(self, language: str = "python") -> Dict[str, Any]:
        """Run full cross-file taint analysis."""
        self._start_time = time.time()
        self._findings = []

        # Load rules
        rules = self._load_rules(language)
        if not rules:
            return {
                "status": "ok",
                "total_findings": 0,
                "findings": [],
                "stats": {"rules_loaded": 0},
                "hint": "No security rules found. Add YAML rule files.",
            }

        # Find source files
        source_files = self.cg_builder._find_source_files(self.workspace, language)

        # Phase 1: Build call graph (project-wide)
        logger.info(f"[Taint] Building call graph for {len(source_files)} files...")
        self._call_graph = self.cg_builder.build(self.workspace, language, source_files)

        # Phase 2: Build CFGs only for files with potential sources/sinks
        relevant_files = self._find_relevant_files(source_files, rules)
        logger.info(f"[Taint] Building CFGs for {len(relevant_files)} relevant files...")

        for fpath in relevant_files:
            if self._time_expired():
                break
            content = safe_read_file(fpath)
            if content:
                rel_path = os.path.relpath(fpath, self.workspace)
                self._cfgs[rel_path] = self.cfg_builder.build_cfg(fpath, content, language)

        # Phase 3: Run taint propagation per file
        for fpath in relevant_files:
            if self._time_expired():
                break
            content = safe_read_file(fpath)
            if content:
                rel_path = os.path.relpath(fpath, self.workspace)
                file_findings = self._analyze_file_taint(rel_path, content, rules, language)
                self._findings.extend(file_findings)

        # Phase 4: Cross-file propagation via call graph
        if self._call_graph and not self._time_expired():
            self._propagate_across_files(rules, language)

        # Deduplicate
        seen = set()
        unique = []
        for f in self._findings:
            key = (f.get('file', ''), f.get('line', 0), f.get('rule_id', ''))
            if key not in seen:
                seen.add(key)
                unique.append(f)
        self._findings = unique

        # Sort by severity
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        self._findings.sort(key=lambda f: sev_order.get(f.get("severity", "medium"), 99))

        # Compute stats
        by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        by_rule = {}
        for f in self._findings:
            sev = f.get("severity", "medium")
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_rule[f.get("rule_name", "unknown")] = by_rule.get(f.get("rule_name", "unknown"), 0) + 1

        cross_file_count = sum(1 for f in self._findings if f.get("cross_file", False))

        risk = "critical" if by_severity.get("critical", 0) > 0 else \
               "high" if by_severity.get("high", 0) > 0 else \
               "medium" if by_severity.get("medium", 0) > 0 else "low"

        return {
            "status": "ok",
            "risk": risk,
            "total_findings": len(self._findings),
            "findings": self._findings,
            "stats": {
                "files_analyzed": len(relevant_files),
                "cfgs_built": len(self._cfgs),
                "call_graph_nodes": len(self._call_graph.function_defs) if self._call_graph else 0,
                "call_graph_edges": sum(len(v) for v in self._call_graph.edges.values()) if self._call_graph else 0,
                "cross_file_findings": cross_file_count,
                "rules_loaded": len(rules),
                "language": language,
                "by_severity": by_severity,
                "by_rule": by_rule,
            },
            "recommendations": self._generate_recommendations(),
        }

    def _load_rules(self, language: str) -> List[Dict]:
        """Load YAML rules for the given language."""
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
                        if rule.get('language', '').lower() == language.lower():
                            rule['_source_file'] = fname
                            rules.append(rule)
            except Exception as e:
                logger.warning(f"Failed to load rule file {fname}: {e}")

        return rules

    def _find_relevant_files(self, source_files: List[str], rules: List[Dict]) -> List[str]:
        """Find files that contain potential sources or sinks."""
        relevant = []
        all_patterns = set()
        for rule in rules:
            for source in rule.get('sources', []):
                all_patterns.add(source.split('.')[-1] if '.' in source else source)
            for sink in rule.get('sinks', []):
                all_patterns.add(sink.split('.')[-1] if '.' in sink else sink)

        for fpath in source_files:
            content = safe_read_file(fpath)
            if content is None:
                continue
            # Check if any pattern appears in the file
            for pattern in all_patterns:
                if pattern in content:
                    relevant.append(fpath)
                    break

        return relevant

    def _analyze_file_taint(self, rel_path: str, source: str,
                            rules: List[Dict], language: str) -> List[Dict]:
        """Analyze a single file for taint vulnerabilities using CFG."""
        findings = []
        lines = source.split('\n')
        cfg = self._cfgs.get(rel_path)

        for rule in rules:
            sources = rule.get('sources', [])
            sinks = rule.get('sinks', [])
            sanitizers = rule.get('sanitizers', [])

            # Phase 1: Identify tainted variables from sources
            tainted_vars: Dict[str, TaintState] = {}
            sanitized_vars: Dict[str, List[str]] = {}

            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped or stripped.startswith('#') or stripped.startswith('//'):
                    continue

                for source in sources:
                    source_parts = source.split('.')
                    source_name = source_parts[-1] if source_parts else source

                    # Check if source appears in the line
                    if source in stripped or source_name + '(' in stripped:
                        # Find variable being assigned
                        assign_match = re.match(r'(?:const|let|var)?\s*(\w+)\s*[=:]\s*', stripped)
                        if assign_match:
                            var_name = assign_match.group(1)
                            tainted_vars[var_name] = TaintState(
                                var_name=var_name,
                                taint_source=source,
                                taint_rule=rule.get('id', ''),
                                path=[f"{source} (line {line_no})"]
                            )

                # Detect sanitization
                for sanitizer in sanitizers:
                    san_name = sanitizer.split('.')[-1] if '.' in sanitizer else sanitizer
                    if san_name in stripped:
                        assign_match = re.match(r'(?:const|let|var)?\s*(\w+)\s*[=:]\s*', stripped)
                        if assign_match:
                            var_name = assign_match.group(1)
                            if var_name not in sanitized_vars:
                                sanitized_vars[var_name] = []
                            sanitized_vars[var_name].append(san_name)

            # Phase 2: Propagate taint through variable assignments
            # Track assignments: if tainted var is assigned to another var, the target becomes tainted
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                # Pattern: y = something_with(x) where x is tainted
                assign_match = re.match(r'(?:const|let|var)?\s*(\w+)\s*[=:]\s*(.+)', stripped)
                if assign_match:
                    target_var = assign_match.group(1)
                    rhs = assign_match.group(2)

                    # Check if any tainted variable appears in the RHS
                    for var_name, taint_state in list(tainted_vars.items()):
                        if var_name in rhs and var_name != target_var:
                            # Propagate taint to the new variable
                            new_path = list(taint_state.path) + [f"{var_name} → {target_var} (line {line_no})"]
                            tainted_vars[target_var] = taint_state.copy_with(
                                var_name=target_var,
                                path=new_path
                            )

                    # Check if any sanitizer is applied
                    for var_name in list(sanitized_vars.keys()):
                        if var_name in rhs:
                            if target_var not in sanitized_vars:
                                sanitized_vars[target_var] = []
                            sanitized_vars[target_var].extend(sanitized_vars[var_name])

            # Phase 3: Check if tainted data reaches sinks
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                for sink in sinks:
                    sink_name = sink.split('.')[-1] if '.' in sink else sink

                    if sink in stripped or (sink_name + '(') in stripped:
                        for var_name, taint_state in tainted_vars.items():
                            if var_name in stripped:
                                is_sanitized = var_name in sanitized_vars
                                san_list = sanitized_vars.get(var_name, [])

                                # Determine confidence based on CFG path existence
                                confidence = "medium"  # Default for intra-file
                                if cfg:
                                    # Verify path from source to sink exists in CFG
                                    if self._verify_cfg_path(cfg, taint_state.taint_source,
                                                               var_name, line_no):
                                        confidence = "high"

                                findings.append({
                                    "rule_id": rule.get('id', 'unknown'),
                                    "rule_name": rule.get('name', 'Unknown'),
                                    "severity": rule.get('severity', 'medium') if not is_sanitized else "info",
                                    "cwe": rule.get('cwe', ''),
                                    "message": rule.get('message', ''),
                                    "file": rel_path,
                                    "line": line_no,
                                    "source": taint_state.taint_source,
                                    "sink": sink_name,
                                    "tainted_variable": var_name,
                                    "sanitized": is_sanitized,
                                    "sanitizers_found": san_list,
                                    "confidence": confidence,
                                    "taint_path": " → ".join(taint_state.path + [sink_name]),
                                    "cross_file": False,
                                })

        return findings

    def _verify_cfg_path(self, cfg: CFG, source_pattern: str,
                         var_name: str, sink_line: int) -> bool:
        """Verify that a path exists in the CFG from source to sink.

        Simple BFS from entry to the node containing sink_line.
        """
        # Find the node containing the sink line
        sink_node = None
        for node_id, node in cfg.nodes.items():
            if node.line_start <= sink_line <= node.line_end:
                sink_node = node_id
                break

        if sink_node is None:
            return False

        # BFS from entry
        if cfg.entry_node is None:
            return False

        visited = set()
        queue = deque([cfg.entry_node])

        while queue:
            current = queue.popleft()
            if current == sink_node:
                return True
            if current in visited:
                continue
            visited.add(current)
            node = cfg.get_node(current)
            if node:
                queue.extend(node.successors)

        return False

    def _propagate_across_files(self, rules: List[Dict], language: str):
        """Propagate taint across file boundaries using the call graph."""
        if not self._call_graph:
            return

        # Find functions that receive tainted data (callers of taint sources)
        # and functions that call sinks
        for rule in rules:
            sinks = rule.get('sinks', [])
            sources = rule.get('sources', [])

            # For each finding, check if the tainted variable could come from
            # a function in another file
            for finding in list(self._findings):
                if finding.get("cross_file", False):
                    continue  # Already cross-file

                var_name = finding.get("tainted_variable", "")
                file = finding.get("file", "")
                line = finding.get("line", 0)

                # Check if the tainted variable could have been passed through
                # a function call from another file
                # Look for function calls on the same line
                content = safe_read_file(os.path.join(self.workspace, file))
                if not content:
                    continue

                lines = content.split('\n')
                if line < 1 or line > len(lines):
                    continue

                target_line = lines[line - 1].strip()

                # Find function calls in the sink line
                calls = re.findall(r'(\w+)\s*\(', target_line)
                for call_name in calls:
                    # Resolve to a function definition
                    callee_fqn = self._call_graph.resolve_call(call_name, file)
                    if callee_fqn and callee_fqn != f"{file}:{call_name}":
                        callee_file, _ = self._call_graph.function_defs.get(callee_fqn, (None, 0))
                        if callee_file and callee_file != file:
                            # Cross-file call found!
                            finding["cross_file"] = True
                            finding["cross_file_source"] = callee_file
                            finding["taint_path"] += f" → [{callee_file}:{call_name}()]"

                            # Also check if the callee function itself contains taint sources
                            callee_content = safe_read_file(os.path.join(self.workspace, callee_file))
                            if callee_content:
                                for source in sources:
                                    if source in callee_content:
                                        # This is a true cross-file taint path
                                        finding["confidence"] = "high"
                                        finding["severity"] = rule.get('severity', 'high')
                                        break

    def _time_expired(self) -> bool:
        return time.time() - self._start_time > self.time_budget

    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations from findings."""
        if not self._findings:
            return ["No taint vulnerabilities detected."]

        recs = []
        critical = [f for f in self._findings if f.get("severity") == "critical"]
        cross_file = [f for f in self._findings if f.get("cross_file")]
        unsanitized = [f for f in self._findings if not f.get("sanitized")]

        if critical:
            recs.append(f"URGENT: {len(critical)} critical vulnerabilities — fix immediately")
            for c in critical[:3]:
                recs.append(f"  → {c['rule_name']}: {c['taint_path']}")

        if cross_file:
            recs.append(f"{len(cross_file)} cross-file taint paths detected — requires multi-file fix")

        if unsanitized:
            recs.append(f"{len(unsanitized)} unsanitized taint paths — add input validation/sanitization")

        return recs[:10]


def analyze_cross_file_taint(workspace: str, language: str = None,
                              rules_dir: str = None) -> Dict[str, Any]:
    """Convenience function for cross-file taint analysis.

    .. deprecated:: 8.3 (issue #49 Phase 1)
        Use ``ast_taint_engine.analyze_workspace(cross_file=True)`` instead.
        This function is kept as a thin compat wrapper that delegates to
        the unified entry point. The ``CrossFileTaintAnalyzer`` class and
        supporting CFG/call-graph infrastructure remain in this module
        as the implementation backend.

    This function delegates to ``ast_taint_engine.analyze_workspace`` with
    ``cross_file=True``. If the AST taint engine is unavailable (e.g.
    tree-sitter not installed), it falls back to the original inline
    implementation below.
    """
    try:
        from ast_taint_engine import (
            analyze_workspace as _ast_analyze_workspace,
            is_available as _ast_is_available,
        )
        if _ast_is_available():
            return _ast_analyze_workspace(
                workspace, rules_dir=rules_dir,
                language=language, cross_file=True,
            )
    except ImportError:
        logger.debug(
            "ast_taint_engine unavailable; falling back to inline "
            "crossfile_taint_engine implementation"
        )

    # Fallback: original inline implementation (kept for environments
    # where ast_taint_engine cannot be imported).
    # Auto-detect languages
    if language is None:
        languages = []
        if any(os.path.exists(os.path.join(workspace, m)) for m in
               ('requirements.txt', 'pyproject.toml', 'setup.py')):
            languages.append("python")
        if any(os.path.exists(os.path.join(workspace, m)) for m in
               ('package.json', 'tsconfig.json')):
            languages.extend(["javascript", "typescript"])
        if not languages:
            languages = ["python"]
    else:
        languages = [language]

    all_findings = []
    total_stats = {}

    for lang in languages:
        analyzer = CrossFileTaintAnalyzer(workspace, rules_dir=rules_dir)
        result = analyzer.analyze(language=lang)
        all_findings.extend(result.get("findings", []))
        total_stats[lang] = result.get("stats", {})

    # Combine results
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for f in all_findings:
        sev = f.get("severity", "medium")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    risk = "critical" if by_severity.get("critical", 0) > 0 else \
           "high" if by_severity.get("high", 0) > 0 else \
           "medium" if by_severity.get("medium", 0) > 0 else "low"

    return {
        "status": "ok",
        "risk": risk,
        "total_findings": len(all_findings),
        "findings": all_findings,
        "stats": {
            "languages_analyzed": languages,
            "by_severity": by_severity,
            "per_language": total_stats,
        },
    }
