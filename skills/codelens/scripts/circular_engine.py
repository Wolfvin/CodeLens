"""
Circular Dependency Detector for CodeLens
Detects circular references in:
1. Function call graphs (backend)
2. Import/require chains (JS/TS)
3. CSS @import chains
Uses DFS with coloring (white/gray/black) for efficient cycle detection.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import logger


def detect_circular(workspace: str, domain: str = "all") -> Dict[str, Any]:
    """
    Detect all circular dependencies in the workspace.

    Args:
        workspace: Absolute path to workspace
        domain: "backend" (function calls), "imports" (import chains), "css" (@import), or "all"

    Returns:
        Dict with cycles found, categorized by type
    """
    workspace = os.path.abspath(workspace)
    cycles = {
        "function_calls": [],
        "import_chains": [],
        "css_imports": []
    }

    # ─── Function Call Cycles ───────────────────────────
    if domain in ("backend", "all"):
        cycles["function_calls"] = _detect_function_cycles(workspace)

    # ─── Import Chain Cycles ────────────────────────────
    if domain in ("imports", "all"):
        cycles["import_chains"] = _detect_import_cycles(workspace)

    # ─── CSS @import Cycles ─────────────────────────────
    if domain in ("css", "all"):
        cycles["css_imports"] = _detect_css_import_cycles(workspace)

    total_cycles = sum(len(v) for v in cycles.values())

    return {
        "status": "ok",
        "workspace": workspace,
        "domain": domain,
        "total_cycles": total_cycles,
        "cycles": cycles,
        "summary": {
            "function_call_cycles": len(cycles["function_calls"]),
            "import_chain_cycles": len(cycles["import_chains"]),
            "css_import_cycles": len(cycles["css_imports"])
        }
    }


# ─── Function Call Cycle Detection ──────────────────────

def _detect_function_cycles(workspace: str) -> List[Dict]:
    """Detect circular function call chains using backend registry."""
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
    except Exception:
        logger.debug("Circular dependency detection failed", exc_info=True)
        return []

    nodes = backend.get("nodes", [])
    edges = backend.get("edges", [])

    # Build adjacency list (only resolved edges)
    adj: Dict[str, List[str]] = defaultdict(list)
    node_by_id: Dict[str, Dict] = {}

    for node in nodes:
        node_by_id[node["id"]] = node
        adj[node["id"]] = []

    for edge in edges:
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        if from_id and to_id and to_id in node_by_id:
            adj[from_id].append(to_id)

    # DFS with coloring to find cycles
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_by_id}
    parent = {nid: None for nid in node_by_id}
    cycles_found = []
    seen_cycles = set()

    # Track path index for O(1) cycle extraction (instead of path.index())
    path_index: Dict[str, int] = {}

    def dfs_cycle(node_id: str, path: List[str]) -> bool:
        color[node_id] = GRAY
        path_index[node_id] = len(path)
        path.append(node_id)

        for neighbor in adj[node_id]:
            if color[neighbor] == GRAY:
                # Found a cycle — extract it using pre-computed index
                cycle_start = path_index[neighbor]
                cycle_path = path[cycle_start:] + [neighbor]

                # Normalize cycle (start from smallest ID to deduplicate)
                cycle_key = _normalize_cycle(cycle_path)
                if cycle_key not in seen_cycles:
                    seen_cycles.add(cycle_key)
                    cycle_detail = _format_function_cycle(cycle_path, node_by_id)
                    cycles_found.append(cycle_detail)

            elif color[neighbor] == WHITE:
                parent[neighbor] = node_id
                dfs_cycle(neighbor, path)

        path.pop()
        path_index.pop(node_id, None)
        color[node_id] = BLACK
        return False

    for nid in node_by_id:
        if color[nid] == WHITE:
            dfs_cycle(nid, [])

    return cycles_found


def _format_function_cycle(cycle_path: List[str], node_by_id: Dict) -> Dict:
    """Format a function call cycle for output."""
    chain = []
    for nid in cycle_path:
        node = node_by_id.get(nid, {})
        chain.append({
            "id": nid,
            "fn": node.get("fn", "unknown"),
            "file": node.get("file", ""),
            "line": node.get("line", 0)
        })

    # Human-readable cycle string
    fn_names = [c["fn"] for c in chain]
    cycle_str = " → ".join(fn_names)

    return {
        "type": "function_call_cycle",
        "chain": chain,
        "cycle": cycle_str,
        "length": len(cycle_path) - 1,
        "severity": "warning" if len(cycle_path) <= 3 else "info",
        "message": f"Circular function call: {cycle_str}"
    }


# ─── Import Chain Cycle Detection ───────────────────────

def _detect_import_cycles(workspace: str) -> List[Dict]:
    """Detect circular import/require chains by parsing import statements."""
    import_graph: Dict[str, Set[str]] = defaultdict(set)
    file_map: Dict[str, str] = {}  # module name → file path

    # Scan for import statements
    extensions = {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}
    ignore_dirs = {"node_modules", ".git", "dist", "build", "target",
                   "__pycache__", ".codelens", ".next", ".cache"}

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in extensions:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            file_map[rel_path] = file_path

            # Parse imports
            imports = _parse_js_imports(content, rel_path, workspace)
            for imp in imports:
                import_graph[rel_path].add(imp)
                file_map[imp] = imp

    # DFS cycle detection on import graph
    cycles_found = []
    seen_cycles = set()

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in import_graph}
    path_index: Dict[str, int] = {}

    def dfs_import(node: str, path: List[str]):
        color[node] = GRAY
        path_index[node] = len(path)
        path.append(node)

        for neighbor in import_graph.get(node, set()):
            if neighbor not in color:
                continue  # External module

            if color[neighbor] == GRAY:
                cycle_start = path_index[neighbor]
                cycle_path = path[cycle_start:] + [neighbor]
                cycle_key = _normalize_cycle(cycle_path)
                if cycle_key not in seen_cycles:
                    seen_cycles.add(cycle_key)
                    cycles_found.append({
                        "type": "import_cycle",
                        "chain": cycle_path,
                        "cycle": " → ".join(cycle_path),
                        "length": len(cycle_path) - 1,
                        "severity": "critical" if len(cycle_path) <= 2 else "warning",
                        "message": f"Circular import: {' → '.join(cycle_path)}"
                    })
            elif color[neighbor] == WHITE:
                dfs_import(neighbor, path)

        path.pop()
        path_index.pop(node, None)
        color[node] = BLACK

    for f in import_graph:
        if color.get(f, WHITE) == WHITE:
            dfs_import(f, [])

    return cycles_found


def _parse_js_imports(content: str, file_rel_path: str, workspace: str) -> List[str]:
    """Parse import/require statements and resolve to relative paths."""
    imports = []
    file_dir = os.path.dirname(file_rel_path)

    # ES module imports: import X from './path'
    for m in re.finditer(r'import\s+.*?from\s+["\'](\.\/[^"\']+)["\']', content):
        raw = m.group(1)
        resolved = _resolve_import_path(raw, file_dir, workspace)
        if resolved:
            imports.append(resolved)

    # CommonJS: require('./path')
    for m in re.finditer(r'require\s*\(\s*["\'](\.\/[^"\']+)["\']\s*\)', content):
        raw = m.group(1)
        resolved = _resolve_import_path(raw, file_dir, workspace)
        if resolved:
            imports.append(resolved)

    return imports


def _resolve_import_path(raw_import: str, from_dir: str, workspace: str) -> Optional[str]:
    """Resolve a relative import to an actual file path."""
    # Normalize the import path
    if raw_import.startswith('./'):
        rel_path = os.path.normpath(os.path.join(from_dir, raw_import))
    elif raw_import.startswith('../'):
        rel_path = os.path.normpath(os.path.join(from_dir, raw_import))
    else:
        return None  # Skip non-relative imports

    # Try with extensions
    extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '/index.js', '/index.ts']
    for ext in extensions:
        full_path = os.path.join(workspace, rel_path + ext)
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)

    return None


# ─── CSS @import Cycle Detection ────────────────────────

def _detect_css_import_cycles(workspace: str) -> List[Dict]:
    """Detect circular CSS @import chains."""
    import_graph: Dict[str, Set[str]] = defaultdict(set)

    ignore_dirs = {"node_modules", ".git", "dist", "build", "target",
                   "__pycache__", ".codelens", ".next", ".cache"}

    css_extensions = {'.css', '.scss', '.less', '.sass'}

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in css_extensions:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Parse @import statements
            for m in re.finditer(r'@import\s+(?:url\()?["\']?([^;"\')\s]+)', content):
                raw = m.group(1)
                if raw.startswith('.') or raw.startswith('/'):
                    resolved = _resolve_css_import(raw, os.path.dirname(rel_path), workspace)
                    if resolved:
                        import_graph[rel_path].add(resolved)

    # DFS cycle detection
    cycles_found = []
    seen_cycles = set()

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in import_graph}
    path_index: Dict[str, int] = {}

    def dfs_css(node: str, path: List[str]):
        color[node] = GRAY
        path_index[node] = len(path)
        path.append(node)

        for neighbor in import_graph.get(node, set()):
            if neighbor not in color:
                continue

            if color[neighbor] == GRAY:
                cycle_start = path_index[neighbor]
                cycle_path = path[cycle_start:] + [neighbor]
                cycle_key = _normalize_cycle(cycle_path)
                if cycle_key not in seen_cycles:
                    seen_cycles.add(cycle_key)
                    cycles_found.append({
                        "type": "css_import_cycle",
                        "chain": cycle_path,
                        "cycle": " → ".join(cycle_path),
                        "length": len(cycle_path) - 1,
                        "severity": "warning",
                        "message": f"Circular CSS @import: {' → '.join(cycle_path)}"
                    })
            elif color[neighbor] == WHITE:
                dfs_css(neighbor, path)

        path.pop()
        path_index.pop(node, None)
        color[node] = BLACK

    for f in import_graph:
        if color.get(f, WHITE) == WHITE:
            dfs_css(f, [])

    return cycles_found


def _resolve_css_import(raw_import: str, from_dir: str, workspace: str) -> Optional[str]:
    """Resolve a CSS @import path."""
    if raw_import.startswith('.'):
        rel_path = os.path.normpath(os.path.join(from_dir, raw_import))
    elif raw_import.startswith('/'):
        rel_path = raw_import.lstrip('/')
    else:
        return None  # Skip external imports

    extensions = ['', '.css', '.scss', '.less', '.sass']
    for ext in extensions:
        full_path = os.path.join(workspace, rel_path + ext)
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)

    return rel_path


# ─── Helpers ─────────────────────────────────────────────

def _normalize_cycle(cycle_path: List[str]) -> str:
    """Normalize a cycle path for deduplication.
    Rotate to start from the lexicographically smallest element."""
    if len(cycle_path) < 2:
        return str(cycle_path)

    # Remove the duplicate last element (it's the same as the first)
    nodes = cycle_path[:-1] if cycle_path[-1] == cycle_path[0] else cycle_path

    if not nodes:
        return ""

    # Find the rotation starting from the smallest element
    min_idx = nodes.index(min(nodes))
    rotated = nodes[min_idx:] + nodes[:min_idx]
    return " → ".join(rotated)
