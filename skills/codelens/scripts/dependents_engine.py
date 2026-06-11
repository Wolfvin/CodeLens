"""
Dependents Engine for CodeLens
Module/file-level import tracking — who imports this file?
Builds a complete import dependency graph for workspace-level analysis.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger


def get_dependents(
    file_path: str,
    workspace: str,
    depth: int = 3
) -> Dict[str, Any]:
    """
    Get all files that import (depend on) the given file.

    Args:
        file_path: Relative file path to query
        workspace: Absolute workspace path
        depth: How deep to trace (transitive dependents)

    Returns:
        Dict with direct dependents, transitive dependents, and stats
    """
    workspace = os.path.abspath(workspace)

    # Normalize the query path
    if os.path.isabs(file_path):
        file_path = os.path.relpath(file_path, workspace)

    # Build import graph
    import_graph, reverse_graph = _build_import_graph(workspace)

    # Direct dependents
    direct = reverse_graph.get(file_path, set())
    direct_list = sorted(direct)

    # Transitive dependents (BFS)
    transitive = set()
    visited = {file_path}
    queue = list(direct)

    while queue and len(transitive) < 500:  # Safety limit
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        transitive.add(current)

        for dep in reverse_graph.get(current, set()):
            if dep not in visited:
                queue.append(dep)

    transitive -= direct  # Don't double-count direct

    return {
        "status": "ok",
        "file": file_path,
        "workspace": workspace,
        "direct_dependents": direct_list,
        "transitive_dependents": sorted(transitive),
        "stats": {
            "direct_count": len(direct_list),
            "transitive_count": len(transitive),
            "total_impact": len(direct_list) + len(transitive)
        }
    }


def get_dependencies(
    file_path: str,
    workspace: str,
    depth: int = 3
) -> Dict[str, Any]:
    """
    Get all files that the given file imports (depends on).

    Args:
        file_path: Relative file path to query
        workspace: Absolute workspace path
        depth: How deep to trace

    Returns:
        Dict with direct and transitive dependencies
    """
    workspace = os.path.abspath(workspace)

    if os.path.isabs(file_path):
        file_path = os.path.relpath(file_path, workspace)

    import_graph, reverse_graph = _build_import_graph(workspace)

    # Direct dependencies
    direct = import_graph.get(file_path, set())
    direct_list = sorted(direct)

    # Transitive dependencies (BFS)
    transitive = set()
    visited = {file_path}
    queue = list(direct)

    while queue and len(transitive) < 500:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        transitive.add(current)

        for dep in import_graph.get(current, set()):
            if dep not in visited:
                queue.append(dep)

    transitive -= direct

    return {
        "status": "ok",
        "file": file_path,
        "workspace": workspace,
        "direct_dependencies": direct_list,
        "transitive_dependencies": sorted(transitive),
        "stats": {
            "direct_count": len(direct_list),
            "transitive_count": len(transitive),
            "total": len(direct_list) + len(transitive)
        }
    }


def get_dependency_graph(
    workspace: str,
    file_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the complete import dependency graph for the workspace.

    Returns adjacency lists for both directions.
    """
    workspace = os.path.abspath(workspace)
    import_graph, reverse_graph = _build_import_graph(workspace)

    # Convert to serializable format
    graph = {}
    for file_path, deps in sorted(import_graph.items()):
        if file_filter and file_filter not in file_path:
            continue
        graph[file_path] = sorted(deps)

    reverse = {}
    for file_path, deps in sorted(reverse_graph.items()):
        if file_filter and file_filter not in file_path:
            continue
        reverse[file_path] = sorted(deps)

    # Find leaf files (no dependencies) and root files (no dependents)
    all_files = set(import_graph.keys()) | set(reverse_graph.keys())
    leaves = sorted(all_files - set(import_graph.keys()))
    roots = sorted(all_files - set(reverse_graph.keys()))

    # Most depended-on files
    dep_counts = [(f, len(deps)) for f, deps in reverse_graph.items()]
    dep_counts.sort(key=lambda x: x[1], reverse=True)
    most_depended = [{"file": f, "dependent_count": c} for f, c in dep_counts[:20]]

    return {
        "status": "ok",
        "workspace": workspace,
        "graph": graph,
        "reverse": reverse,
        "stats": {
            "total_files": len(all_files),
            "total_import_edges": sum(len(deps) for deps in import_graph.values()),
            "leaf_files": len(leaves),
            "root_files": len(roots)
        },
        "leaf_files": leaves[:50],
        "root_files": roots[:50],
        "most_depended_on": most_depended
    }


# ─── Import Graph Builder ───────────────────────────────

def _build_import_graph(workspace: str) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    """
    Build the import dependency graph for the entire workspace.

    Returns:
        (import_graph, reverse_graph)
        import_graph[file] = set of files that file imports
        reverse_graph[file] = set of files that import file
    """
    import_graph: Dict[str, Set[str]] = defaultdict(set)
    reverse_graph: Dict[str, Set[str]] = defaultdict(set)

    ignore_dirs = set(DEFAULT_IGNORE_DIRS)

    # JS/TS imports
    js_extensions = {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx'}
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            if ext in js_extensions:
                imports = _parse_js_imports(file_path, rel_path, workspace)
                for imp in imports:
                    import_graph[rel_path].add(imp)
                    reverse_graph[imp].add(rel_path)

            elif ext == '.rs':
                imports = _parse_rust_imports(file_path, rel_path, workspace)
                for imp in imports:
                    import_graph[rel_path].add(imp)
                    reverse_graph[imp].add(rel_path)

            elif ext == '.py':
                imports = _parse_python_imports(file_path, rel_path, workspace)
                for imp in imports:
                    import_graph[rel_path].add(imp)
                    reverse_graph[imp].add(rel_path)

            elif ext in ('.css', '.scss', '.less', '.sass'):
                imports = _parse_css_imports(file_path, rel_path, workspace)
                for imp in imports:
                    import_graph[rel_path].add(imp)
                    reverse_graph[imp].add(rel_path)

    return import_graph, reverse_graph


# ─── Import Parsers ──────────────────────────────────────

def _parse_js_imports(file_path: str, rel_path: str, workspace: str) -> List[str]:
    """Parse JS/TS import statements."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    imports = []
    file_dir = os.path.dirname(rel_path)

    # ES imports
    for m in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
        resolved = _resolve_relative_import(m.group(1), file_dir, workspace)
        if resolved:
            imports.append(resolved)

    # Dynamic imports
    for m in re.finditer(r'import\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
        resolved = _resolve_relative_import(m.group(1), file_dir, workspace)
        if resolved:
            imports.append(resolved)

    # CommonJS
    for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
        resolved = _resolve_relative_import(m.group(1), file_dir, workspace)
        if resolved:
            imports.append(resolved)

    return imports


def _parse_rust_imports(file_path: str, rel_path: str, workspace: str) -> List[str]:
    """Parse Rust use/mod declarations."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    imports = []
    file_dir = os.path.dirname(rel_path)

    # mod declarations (reference other Rust files)
    for m in re.finditer(r'mod\s+(\w+)', content):
        mod_name = m.group(1)
        # Try to find the module file
        for ext in ['.rs', '/mod.rs']:
            mod_path = os.path.join(workspace, file_dir, mod_name + ext)
            if os.path.exists(mod_path):
                imports.append(os.path.relpath(mod_path, workspace))
                break

    return imports


def _parse_python_imports(file_path: str, rel_path: str, workspace: str) -> List[str]:
    """Parse Python import statements."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    imports = []
    file_dir = os.path.dirname(rel_path)

    for line in content.split('\n'):
        stripped = line.strip()

        # from X import Y
        m = re.match(r'from\s+([\w.]+)\s+import', stripped)
        if m:
            module_path = m.group(1).replace('.', '/')
            resolved = _resolve_python_module(module_path, file_dir, workspace)
            if resolved:
                imports.append(resolved)
            continue

        # import X
        m = re.match(r'import\s+([\w.]+)', stripped)
        if m:
            module_path = m.group(1).replace('.', '/')
            resolved = _resolve_python_module(module_path, file_dir, workspace)
            if resolved:
                imports.append(resolved)

    return imports


def _parse_css_imports(file_path: str, rel_path: str, workspace: str) -> List[str]:
    """Parse CSS @import statements."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    imports = []
    file_dir = os.path.dirname(rel_path)

    for m in re.finditer(r'@import\s+(?:url\()?["\']?([^;"\')\s]+)', content):
        raw = m.group(1)
        if raw.startswith('.') or raw.startswith('/'):
            resolved = _resolve_relative_import(raw.lstrip('/'), file_dir, workspace,
                                                extensions=['', '.css', '.scss', '.less', '.sass'])
            if resolved:
                imports.append(resolved)

    return imports


# ─── Import Resolution ──────────────────────────────────

def _resolve_relative_import(
    raw_import: str,
    from_dir: str,
    workspace: str,
    extensions: Optional[List[str]] = None
) -> Optional[str]:
    """Resolve a relative import to an actual file."""
    if not (raw_import.startswith('./') or raw_import.startswith('../') or raw_import.startswith('.')):
        return None  # External module

    if extensions is None:
        extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
                      '/index.js', '/index.ts', '/index.tsx']

    rel_path = os.path.normpath(os.path.join(from_dir, raw_import))

    for ext in extensions:
        full_path = os.path.join(workspace, rel_path + ext)
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)

    return None


def _resolve_python_module(module_path: str, from_dir: str, workspace: str) -> Optional[str]:
    """Resolve a Python module to an actual file."""
    # Try as a file
    full_path = os.path.join(workspace, from_dir, module_path + '.py')
    if os.path.isfile(full_path):
        return os.path.relpath(full_path, workspace)

    # Try as a package
    init_path = os.path.join(workspace, from_dir, module_path, '__init__.py')
    if os.path.isfile(init_path):
        return os.path.relpath(init_path, workspace)

    # Try from workspace root
    full_path = os.path.join(workspace, module_path + '.py')
    if os.path.isfile(full_path):
        return os.path.relpath(full_path, workspace)

    init_path = os.path.join(workspace, module_path, '__init__.py')
    if os.path.isfile(init_path):
        return os.path.relpath(init_path, workspace)

    return None
