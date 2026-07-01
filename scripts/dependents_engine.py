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


# ─── Issue #62 Phase 1: `affected` command helpers ────────────────────────
#
# Test-file detection heuristic. Returns True if the file path looks like a
# test file in any of the common conventions across ecosystems. Conservative
# by design — better to over-report (run an extra test) than to silently
# miss a regression.
#
# Patterns matched (case-insensitive basename or path segment):
#   *test*.py, *spec*.py          — pytest / unittest / nose
#   *test.js, *spec.js            — Jest / Mocha / Jasmine
#   *.test.ts(x), *.spec.ts(x)    — Jest / Vitest with TypeScript
#   test_*.py, *_test.py          — Python unittest conventions
#   *_test.go                     — Go testing
#   *Test.java, *Tests.java       — JUnit
#   *Test.cs                      — NUnit / xUnit
#   *.rs (with #[test])           — detected at content level, not here
#   tests/ directory              — common layout
#   __tests__/ directory          — Jest convention
#   spec/ directory               — RSpec / Jasmine convention

_TEST_BASENAME_RE = re.compile(
    r'^('
    r'test_.+|.+_test'        # test_foo.py, foo_test.py
    r'|.+tests?|.+specs?'     # FooTest.java, FooTests.java, foo.spec.ts, foo.specs.js
    r'|tests?|specs?'         # test.py, tests.py, spec.py, specs.py (exact stem)
    r')$',
    re.IGNORECASE,
)

_TEST_DIR_SEGMENTS = {'tests', 'test', '__tests__', '__test__', 'spec', 'specs'}

_TEST_EXTENSIONS = {
    '.py', '.pyw',
    '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx',
    '.go', '.rs', '.java', '.kt', '.cs', '.rb', '.php',
    '.dart', '.swift',
}


def is_test_file(path: str) -> bool:
    """Heuristic: return True if ``path`` looks like a test file.

    Conservative — over-reports rather than misses. Matches common test
    naming conventions across Python, JS/TS, Go, Rust, Java, C#, Ruby,
    PHP, Dart, Swift. Path can be absolute, relative, or just a basename.
    """
    if not path:
        return False
    # Normalize separators
    norm = path.replace('\\', '/')
    basename = norm.rsplit('/', 1)[-1]
    if not basename:
        return False
    stem, ext = os.path.splitext(basename)
    ext_lower = ext.lower()

    # 1. Skip non-source files (.md, .json, .txt, .gitignore, etc.)
    #    Empty extension is allowed (we'll gate it later).
    if ext_lower and ext_lower not in _TEST_EXTENSIONS:
        return False

    # 2. Path contains a test directory segment (tests/, __tests__/, spec/)
    #    This is the strongest signal — a file inside tests/ is a test file
    #    regardless of its basename. Check BEFORE the extension gate so
    #    that a file like `tests/conftest.py` (no test_ prefix) is caught.
    segments = [s.lower() for s in norm.split('/') if s]
    if any(seg in _TEST_DIR_SEGMENTS for seg in segments[:-1]):
        return True
    if '__tests__' in norm.lower():
        return True

    # 3. Require an extension for the basename-pattern match — a bare
    #    `test` or `tests` (no extension) is more likely a directory or
    #    symlink than an actual test file.
    if not ext_lower:
        return False

    # 4. Basename pattern: test_*, *_test, *test, *tests, *spec, *specs,
    #    exact `test`/`tests`/`spec`/`specs` stems
    if _TEST_BASENAME_RE.match(stem):
        return True
    if stem.lower().startswith(('test_', 'spec_')):
        return True

    return False


def get_affected_files(
    changed_files: List[str],
    workspace: str,
    depth: int = 5,
    file_filter: Optional[str] = None,
    include_source: bool = False,
) -> Dict[str, Any]:
    """Issue #62 Phase 1 — transitive affected-files analysis.

    Given a list of changed source files, walk the reverse dependency graph
    (depth-controlled BFS) and return every file that transitively imports
    one of the changed files. By default, only test files are returned
    (the CI use-case: ``pytest $AFFECTED``); pass ``include_source=True``
    to also return non-test dependents.

    Args:
        changed_files: list of file paths (absolute, relative, or bare
            basenames — resolution is forgiving). Files that cannot be
            resolved against the workspace are silently skipped.
        workspace: absolute workspace path.
        depth: BFS depth cap (default 5). ``0`` means only the changed
            files themselves; ``-1`` means unlimited (with a 5000-node
            safety cap to prevent runaway traversal on cyclic graphs).
        file_filter: optional glob; if given, only files matching this
            glob are returned in ``affected``. Does not affect traversal.
        include_source: if True, also return non-test dependents. If
            False (default), only test files are returned.

    Returns:
        Dict with keys:
            * ``status``       — "ok"
            * ``workspace``    — absolute workspace path
            * ``changed_files`` — resolved changed files that were found
            * ``unresolved``   — changed files that could not be resolved
            * ``affected``     — sorted list of affected test (or all) files
            * ``affected_by_source`` — dict {changed_file: [affected tests]}
            * ``depth``        — actual depth used
            * ``stats``        — counts
    """
    import fnmatch

    workspace = os.path.abspath(workspace)
    import_graph, reverse_graph = _build_import_graph(workspace)

    # Normalize changed files to workspace-relative paths
    all_known_files = set(import_graph.keys()) | set(reverse_graph.keys())
    resolved_changed: List[str] = []
    unresolved: List[str] = []
    for cf in changed_files:
        cf = cf.strip()
        if not cf:
            continue
        # Strip leading ./ and normalize
        cf_norm = cf.replace('\\', '/').lstrip('./')
        # Try: absolute path -> relative
        if os.path.isabs(cf):
            try:
                cf_rel = os.path.relpath(cf, workspace)
            except ValueError:
                cf_rel = cf_norm
        else:
            cf_rel = cf_norm
        # Try direct match
        if cf_rel in all_known_files:
            resolved_changed.append(cf_rel)
            continue
        # Try: maybe user passed full path that's already relative
        if os.path.isfile(os.path.join(workspace, cf_rel)):
            resolved_changed.append(cf_rel)
            continue
        # Try basename match (last resort — common in `git diff --name-only`
        # output where the user is in a subdirectory)
        basename = os.path.basename(cf_rel)
        candidates = [f for f in all_known_files if os.path.basename(f) == basename]
        if len(candidates) == 1:
            resolved_changed.append(candidates[0])
        elif len(candidates) > 1:
            # Ambiguous — pick the one whose path-suffix matches cf_rel
            # (e.g., "scripts/foo.py" matches "scripts/foo.py" out of
            # multiple "foo.py" files). If still ambiguous, skip.
            suffix_match = [c for c in candidates if c.endswith(cf_rel) or cf_rel.endswith(c)]
            if len(suffix_match) == 1:
                resolved_changed.append(suffix_match[0])
            else:
                unresolved.append(cf)
        else:
            unresolved.append(cf)

    # BFS over reverse_graph from each resolved changed file
    # Track depth per node so we can respect the depth cap
    visited: Dict[str, int] = {}  # file -> depth-at-which-first-reached
    queue: List[Tuple[str, int]] = [(cf, 0) for cf in resolved_changed]
    safety_cap = 5000
    while queue and len(visited) < safety_cap:
        current, d = queue.pop(0)
        if current in visited and visited[current] <= d:
            continue
        visited[current] = d
        if depth >= 0 and d >= depth:
            continue
        for dep in reverse_graph.get(current, set()):
            if dep not in visited or visited[dep] > d + 1:
                queue.append((dep, d + 1))

    # Build affected_by_source mapping for traceability
    affected_by_source: Dict[str, List[str]] = defaultdict(list)
    affected_set: Set[str] = set()
    for node, node_depth in visited.items():
        if node_depth == 0:
            # The changed file itself — only include if include_source
            # AND it passes the filter (test file or include_source).
            if include_source and (not file_filter or fnmatch.fnmatch(node, file_filter)):
                affected_set.add(node)
            continue
        # Apply filter
        if file_filter and not fnmatch.fnmatch(node, file_filter):
            continue
        # Apply test-file gate
        if not include_source and not is_test_file(node):
            continue
        affected_set.add(node)

    # Build affected_by_source: for each changed file, which affected files
    # are reachable from it? We re-walk per-source to keep this accurate.
    for cf in resolved_changed:
        per_visited: Set[str] = set()
        per_queue: List[Tuple[str, int]] = [(cf, 0)]
        while per_queue:
            current, d = per_queue.pop(0)
            if current in per_visited:
                continue
            per_visited.add(current)
            if depth >= 0 and d >= depth:
                continue
            for dep in reverse_graph.get(current, set()):
                if dep not in per_visited:
                    per_queue.append((dep, d + 1))
        # Filter per_visited to affected-only
        for v in per_visited:
            if v == cf:
                continue
            if file_filter and not fnmatch.fnmatch(v, file_filter):
                continue
            if not include_source and not is_test_file(v):
                continue
            affected_by_source[cf].append(v)

    affected_sorted = sorted(affected_set)
    test_count = sum(1 for f in affected_sorted if is_test_file(f))

    return {
        "status": "ok",
        "workspace": workspace,
        "changed_files": resolved_changed,
        "unresolved": unresolved,
        "affected": affected_sorted,
        "affected_by_source": {k: sorted(v) for k, v in affected_by_source.items()},
        "depth": depth,
        "stats": {
            "changed_count": len(resolved_changed),
            "unresolved_count": len(unresolved),
            "affected_count": len(affected_sorted),
            "affected_test_count": test_count,
            "affected_source_count": len(affected_sorted) - test_count,
            "visited_total": len(visited),
        },
    }


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

    # If no results, try fuzzy matching (e.g., models.py -> models/__init__.py)
    suggestion = None
    if not direct and file_path not in import_graph:
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        parent_dir = os.path.dirname(file_path)
        # Try: path/file.py -> path/file/__init__.py (Python package)
        candidate = os.path.join(parent_dir, base_name, '__init__.py') if parent_dir else os.path.join(base_name, '__init__.py')
        if candidate in reverse_graph or candidate in import_graph:
            suggestion = candidate
            direct = reverse_graph.get(candidate, set())
            file_path = candidate
        else:
            # Try substring match
            for key in reverse_graph:
                if base_name in os.path.basename(key) and key.endswith('__init__.py'):
                    suggestion = key
                    direct = reverse_graph.get(key, set())
                    file_path = key
                    break

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
        "suggestion": suggestion,
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
    js_extensions = {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.vue', '.svelte'}
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
    """Parse JS/TS import statements. Also handles Vue SFC and Svelte <script> sections."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return []

    # For .vue files, extract the script section first
    ext = os.path.splitext(file_path)[1].lower()
    if ext == '.vue':
        script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        if script_match:
            content = script_match.group(1)
        else:
            return []  # No script section in Vue SFC
    elif ext == '.svelte':
        # Svelte: extract <script> section
        script_match = re.search(r'<script[^>]*>(.*?)</script>', content, re.DOTALL)
        if script_match:
            content = script_match.group(1)
        else:
            return []  # No script section in Svelte component

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
    """Parse Rust use/mod declarations.

    Handles:
    - mod declarations (reference other Rust files/modules)
    - use declarations with crate:: prefix (resolve to local files when possible)
    - use declarations with super:: prefix (resolve to parent module)
    """
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

    # use declarations with super:: (resolve to parent module)
    for m in re.finditer(r'use\s+super::(\w+)', content):
        mod_name = m.group(1)
        parent_dir = os.path.dirname(file_dir)
        for ext in ['.rs', '/mod.rs']:
            mod_path = os.path.join(workspace, parent_dir, mod_name + ext)
            if os.path.exists(mod_path):
                imports.append(os.path.relpath(mod_path, workspace))
                break

    # use declarations with crate:: prefix (resolve relative to crate root)
    for m in re.finditer(r'use\s+crate::([\w:]+)', content):
        crate_path = m.group(1).replace('::', '/')
        # Try resolving from src/ root (most common Rust layout)
        for src_dir in ['src/', '']:
            for ext in ['.rs', '/mod.rs']:
                mod_path = os.path.join(workspace, src_dir, crate_path + ext)
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
        # Try resolving path aliases (@/ → src/)
        resolved_alias = _resolve_path_alias(raw_import, workspace)
        if resolved_alias:
            return resolved_alias
        return None  # External module

    if extensions is None:
        extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.vue',
                      '.svelte', '/index.js', '/index.ts', '/index.tsx', '/index.vue',
                      '/index.svelte']

    rel_path = os.path.normpath(os.path.join(from_dir, raw_import))

    for ext in extensions:
        full_path = os.path.join(workspace, rel_path + ext)
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)

    return None


def _resolve_path_alias(raw_import: str, workspace: str) -> Optional[str]:
    """Resolve common path aliases like @/ → src/, ~/ → src/, etc."""
    if not raw_import.startswith('@') and not raw_import.startswith('~'):
        return None

    # Common alias patterns to try
    alias_bases = []

    # @/ → src/ (most common Vue/Vite alias)
    if raw_import.startswith('@/'):
        alias_bases.append(('src/', raw_import[2:]))
        # Also try app/src/ for monorepos
        alias_bases.append(('app/src/', raw_import[2:]))

    # ~/ → src/
    if raw_import.startswith('~/'):
        alias_bases.append(('src/', raw_import[2:]))
        alias_bases.append(('app/src/', raw_import[2:]))

    extensions = ['', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.vue',
                  '.svelte', '/index.js', '/index.ts', '/index.tsx', '/index.vue',
                  '/index.svelte']

    for base_dir, rel_path in alias_bases:
        for ext in extensions:
            full_path = os.path.join(workspace, base_dir, rel_path + ext)
            if os.path.isfile(full_path):
                return os.path.relpath(full_path, workspace)

    return None


def _resolve_python_module(module_path: str, from_dir: str, workspace: str) -> Optional[str]:
    """Resolve a Python module to an actual file.

    Resolution order:
    1. Relative to the importing file's directory (``from_dir``).
    2. As a package (``__init__.py``) relative to ``from_dir``.
    3. From workspace root.
    4. As a package from workspace root.
    5. **Issue #62 Phase 1**: from ``scripts/`` — CodeLens convention is
       ``sys.path.insert(0, SCRIPT_DIR)`` in tests and commands, so
       ``from utils import X`` from ``tests/foo.py`` resolves to
       ``scripts/utils.py``. Without this fallback, the reverse-dependency
       graph misses test→script edges and ``codelens affected`` returns
       false negatives.
    6. **Issue #62 Phase 1**: from ``scripts/<from_dir>`` — handles the
       case where a test in ``tests/`` imports a sibling-named module
       that lives in ``scripts/<sibling>/``.
    """
    # 1. Try as a file, relative to from_dir
    full_path = os.path.join(workspace, from_dir, module_path + '.py')
    if os.path.isfile(full_path):
        return os.path.relpath(full_path, workspace)

    # 2. Try as a package, relative to from_dir
    init_path = os.path.join(workspace, from_dir, module_path, '__init__.py')
    if os.path.isfile(init_path):
        return os.path.relpath(init_path, workspace)

    # 3. Try from workspace root
    full_path = os.path.join(workspace, module_path + '.py')
    if os.path.isfile(full_path):
        return os.path.relpath(full_path, workspace)

    # 4. Try as a package from workspace root
    init_path = os.path.join(workspace, module_path, '__init__.py')
    if os.path.isfile(init_path):
        return os.path.relpath(init_path, workspace)

    # 5. Issue #62 Phase 1: try from scripts/ (CodeLens convention)
    #    Tests and commands do `sys.path.insert(0, SCRIPT_DIR)` then
    #    `from utils import X` — which resolves to scripts/utils.py.
    scripts_dir = os.path.join(workspace, 'scripts')
    if os.path.isdir(scripts_dir):
        full_path = os.path.join(scripts_dir, module_path + '.py')
        if os.path.isfile(full_path):
            return os.path.relpath(full_path, workspace)
        init_path = os.path.join(scripts_dir, module_path, '__init__.py')
        if os.path.isfile(init_path):
            return os.path.relpath(init_path, workspace)

    # 6. Issue #62 Phase 1: try from scripts/<from_dir basename> —
    #    handles `from commands.scan import X` from tests/, which should
    #    resolve to scripts/commands/scan.py.
    #    module_path here may be 'commands/scan' (after .replace('.','/'))
    if '/' in module_path:
        first_seg = module_path.split('/')[0]
        rest = module_path[len(first_seg) + 1:]
        candidate_dir = os.path.join(scripts_dir, first_seg)
        if os.path.isdir(candidate_dir):
            full_path = os.path.join(candidate_dir, rest + '.py')
            if os.path.isfile(full_path):
                return os.path.relpath(full_path, workspace)
            init_path = os.path.join(candidate_dir, rest, '__init__.py')
            if os.path.isfile(init_path):
                return os.path.relpath(init_path, workspace)

    return None
