"""
Circular Dependency Detector for CodeLens
Detects circular references in:
1. Function call graphs (backend)
2. Import/require chains (JS/TS)
3. CSS @import chains
Uses DFS with coloring (white/gray/black) for efficient cycle detection.

Performance: Includes max_cycles limit to prevent timeout on very large
codebases with many cycles (e.g., 65K+ nodes, 320K+ edges).

v5.9 fix: Early return from DFS due to max_cycles limit no longer corrupts
path/color state. Uses a `stopped` flag to propagate early exit and ensure
proper unwinding of the DFS stack.

v5.10: Rust trait impl false positive filtering. Cycles composed entirely of
conversion trait methods (from_*/into_*/to_*/as_*) and very long chains (>8
nodes) are classified as 'info' severity instead of 'warning', since they are
intentional bidirectional conversions or spurious name-matching artifacts.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

# Performance limit: max cycles to report per detection run
MAX_CYCLES_PER_TYPE = 100


def detect_circular(workspace: str, domain: str = "all", max_cycles: int = MAX_CYCLES_PER_TYPE) -> Dict[str, Any]:
    """
    Detect all circular dependencies in the workspace.

    Args:
        workspace: Absolute path to workspace
        domain: "backend" (function calls), "imports" (import chains), "css" (@import), or "all"
        max_cycles: Max cycles to report per type (default 100)

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
        cycles["function_calls"] = _detect_function_cycles(workspace, max_cycles)

    # ─── Import Chain Cycles ────────────────────────────
    if domain in ("imports", "all"):
        cycles["import_chains"] = _detect_import_cycles(workspace, max_cycles)

    # ─── CSS @import Cycles ─────────────────────────────
    if domain in ("css", "all"):
        cycles["css_imports"] = _detect_css_import_cycles(workspace, max_cycles)

    total_cycles = sum(len(v) for v in cycles.values())

    # Count severity levels across all cycle types
    warning_count = 0
    info_count = 0
    critical_count = 0
    for cat_cycles in cycles.values():
        for cycle in cat_cycles:
            sev = cycle.get("severity", "warning")
            if sev == "critical":
                critical_count += 1
            elif sev == "warning":
                warning_count += 1
            else:
                info_count += 1

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
        },
        "severity_breakdown": {
            "genuine_warning": warning_count,
            "likely_false_positive_info": info_count,
            "critical": critical_count
        }
    }


# ─── Function Call Cycle Detection ──────────────────────

def _detect_function_cycles(workspace: str, max_cycles: int = 100) -> List[Dict]:
    """Detect circular function call chains using backend registry."""
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
    except Exception:
        logger.warning("Failed to load backend registry for cycle detection", exc_info=True)
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
        if from_id and to_id and to_id in node_by_id and edge.get("resolved", True) is not False:
            adj[from_id].append(to_id)

    # Collect self-edges (recursion) before removing them from adjacency list
    self_edges = []
    for nid in adj:
        for neighbor in adj[nid]:
            if neighbor == nid:
                node = node_by_id.get(nid, {})
                self_edges.append((nid, node.get("fn", "unknown")))

    # Remove self-edges (recursion is not a circular dependency)
    for nid in list(adj.keys()):
        adj[nid] = [neighbor for neighbor in adj[nid] if neighbor != nid]

    # DFS with coloring to find cycles
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_by_id}
    parent = {nid: None for nid in node_by_id}
    cycles_found = []
    seen_cycles = set()
    stopped = [False]  # Mutable flag for early exit propagation

    def dfs_cycle(node_id: str, path: List[str]):
        color[node_id] = GRAY
        path.append(node_id)

        for neighbor in adj[node_id]:
            if stopped[0]:
                break

            if color[neighbor] == GRAY:
                # Found a cycle — extract it
                try:
                    cycle_start = path.index(neighbor)
                except ValueError:
                    # Safety: neighbor is GRAY but not in current path
                    # (shouldn't happen with proper unwinding, but handle gracefully)
                    continue
                cycle_path = path[cycle_start:] + [neighbor]

                # Skip self-loops (recursive calls) — these are not circular dependencies
                if len(cycle_path) == 2 and cycle_path[0] == cycle_path[1]:
                    continue

                # Normalize cycle (start from smallest ID to deduplicate)
                cycle_key = _normalize_cycle(cycle_path)
                if cycle_key not in seen_cycles:
                    seen_cycles.add(cycle_key)
                    cycle_detail = _format_function_cycle(cycle_path, node_by_id)
                    cycles_found.append(cycle_detail)
                    if len(cycles_found) >= max_cycles:
                        stopped[0] = True

            elif color[neighbor] == WHITE:
                parent[neighbor] = node_id
                dfs_cycle(neighbor, path)
                if stopped[0]:
                    break

        path.pop()
        color[node_id] = BLACK

    for nid in node_by_id:
        if stopped[0]:
            break
        if color[nid] == WHITE:
            dfs_cycle(nid, [])

    # Report self-edges as recursion (info-level, not a circular dependency)
    seen_self = set()
    for nid, fn_name in self_edges:
        if nid not in seen_self:
            seen_self.add(nid)
            node = node_by_id.get(nid, {})
            cycles_found.append({
                "type": "recursion",
                "chain": [{
                    "id": nid,
                    "fn": fn_name,
                    "file": node.get("file", ""),
                    "line": node.get("line", 0)
                }],
                "cycle": f"{fn_name} → {fn_name}",
                "length": 1,
                "severity": "info",
                "message": f"Recursive function call: {fn_name}"
            })

    return cycles_found


def _is_conversion_trait_fn(fn_name: str) -> bool:
    """Check if a function name looks like a Rust conversion trait implementation.

    Rust's From/Into/TryFrom/TryInto/AsRef/AsMut traits generate impl methods
    like `from_<type>`, `into_<type>`, `to_<type>`, `as_<type>`, etc.
    These bidirectional conversions commonly create apparent circular chains
    (e.g. From<A> for B and From<B> for A) that are intentional and safe.
    """
    fn_lower = fn_name.lower().rsplit("::", 1)[-1]  # strip module path
    # Match common Rust conversion trait impl patterns
    if fn_lower.startswith(("from_", "into_", "try_from_", "try_into_")):
        return True
    # to_ / as_ are more ambiguous, but in Rust trait impls they follow
    # the pattern `<Type as Trait>::to_<type>` or similar
    if fn_lower.startswith(("to_", "as_")) and "::" in fn_name.lower():
        return True
    # Also match the standard From::from / Into::into trait methods themselves
    if fn_lower in ("from", "into", "try_from", "try_into"):
        return True
    return False


def _classify_cycle_severity(chain: List[Dict], cycle_length: int) -> str:
    """Classify a cycle's severity based on its characteristics.

    Rules:
    - If ALL functions in the chain are Rust conversion trait impls (from_*/into_*/etc.),
      classify as 'info' — these are intentional bidirectional conversions, not real cycles.
    - If the cycle is very long (>8 nodes), classify as 'info' — likely a false positive
      from name matching that creates spurious chains across unrelated modules.
    - Short chains (2-3 nodes) with non-conversion functions are genuine: 'warning'.
    """
    fn_names = [c.get("fn", "unknown") for c in chain]

    # Check if every function in the chain is a conversion trait impl
    all_conversion = all(_is_conversion_trait_fn(fn) for fn in fn_names)
    if all_conversion:
        return "info"

    # Very long chains are almost always false positives from name matching
    if cycle_length > 8:
        return "info"

    # Short chains with non-conversion functions are genuine cycles
    return "warning"


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
    cycle_length = len(cycle_path) - 1

    # Classify severity using the new heuristic
    severity = _classify_cycle_severity(chain, cycle_length)

    # Build a descriptive message that explains the classification
    message = f"Circular function call: {cycle_str}"
    if severity == "info" and all(_is_conversion_trait_fn(c.get("fn", "")) for c in chain):
        message += " (likely intentional bidirectional trait impl)"
    elif severity == "info" and cycle_length > 8:
        message += " (long chain, likely false positive from name matching)"

    return {
        "type": "function_call_cycle",
        "chain": chain,
        "cycle": cycle_str,
        "length": cycle_length,
        "severity": severity,
        "message": message
    }


# ─── Import Chain Cycle Detection ───────────────────────

def _detect_import_cycles(workspace: str, max_cycles: int = 100) -> List[Dict]:
    """Detect circular import/require chains by parsing import statements."""
    import_graph: Dict[str, Set[str]] = defaultdict(set)
    file_map: Dict[str, str] = {}  # module name → file path

    # Scan for import statements
    extensions = {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)

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
    stopped = [False]  # Mutable flag for early exit propagation

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in import_graph}

    def dfs_import(node: str, path: List[str]):
        color[node] = GRAY
        path.append(node)

        for neighbor in import_graph.get(node, set()):
            if stopped[0]:
                break

            if neighbor not in color:
                continue  # External module

            if color[neighbor] == GRAY:
                try:
                    cycle_start = path.index(neighbor)
                except ValueError:
                    # Safety: neighbor is GRAY but not in current path
                    # This can happen due to state corruption from a previous
                    # early return. Skip this edge gracefully.
                    logger.debug(f"Circular engine: skipping GRAY node not in path: {neighbor}")
                    continue
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
                    if len(cycles_found) >= max_cycles:
                        stopped[0] = True
            elif color[neighbor] == WHITE:
                dfs_import(neighbor, path)
                if stopped[0]:
                    break

        path.pop()
        color[node] = BLACK

    for f in import_graph:
        if stopped[0]:
            break
        if color.get(f, WHITE) == WHITE:
            dfs_import(f, [])

    return cycles_found


def _parse_js_imports(content: str, file_rel_path: str, workspace: str) -> List[str]:
    """Parse import/require statements and resolve to relative paths."""
    imports = []
    file_dir = os.path.dirname(file_rel_path)

    # ES module imports: import X from './path' or '../path'
    for m in re.finditer(r'import\s+.*?from\s+["\'](\.{1,2}/[^"\']+)["\']', content):
        raw = m.group(1)
        resolved = _resolve_import_path(raw, file_dir, workspace)
        if resolved:
            imports.append(resolved)

    # CommonJS: require('./path') or require('../path')
    for m in re.finditer(r'require\s*\(\s*["\'](\.{1,2}/[^"\']+)["\']\s*\)', content):
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
    extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '/index.js', '/index.ts', '/index.tsx']
    for ext in extensions:
        full_path = os.path.join(workspace, rel_path + ext)
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)

    return rel_path  # Return unresolved path


# ─── CSS @import Cycle Detection ────────────────────────

def _detect_css_import_cycles(workspace: str, max_cycles: int = 100) -> List[Dict]:
    """Detect circular CSS @import chains."""
    import_graph: Dict[str, Set[str]] = defaultdict(set)

    ignore_dirs = set(DEFAULT_IGNORE_DIRS)

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
    stopped = [False]  # Mutable flag for early exit propagation

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {f: WHITE for f in import_graph}

    def dfs_css(node: str, path: List[str]):
        color[node] = GRAY
        path.append(node)

        for neighbor in import_graph.get(node, set()):
            if stopped[0]:
                break

            if neighbor not in color:
                continue

            if color[neighbor] == GRAY:
                try:
                    cycle_start = path.index(neighbor)
                except ValueError:
                    # Safety: neighbor is GRAY but not in current path
                    logger.debug(f"Circular engine: skipping GRAY node not in path: {neighbor}")
                    continue
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
                    if len(cycles_found) >= max_cycles:
                        stopped[0] = True
            elif color[neighbor] == WHITE:
                dfs_css(neighbor, path)
                if stopped[0]:
                    break

        path.pop()
        color[node] = BLACK

    for f in import_graph:
        if stopped[0]:
            break
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
