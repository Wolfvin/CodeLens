"""
Enhanced Dead Code Detection Engine for CodeLens — v3
Goes beyond the basic 0-ref_count check to find:
1. Unreachable code branches (code after return/throw/break)
2. Unused exports (exported but never imported)
3. Zombie CSS (CSS classes defined but never referenced in HTML/JS)
4. Dead event listeners (listeners on elements that don't exist)
5. Unused variables (declared but never read)
6. Unreachable catch blocks (catch for error type that can't be thrown)
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".css", ".scss", ".less"
}

def detect_dead_code(
    workspace: str,
    categories: Optional[List[str]] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Enhanced dead code detection beyond basic ref_count==0.

    Args:
        workspace: Absolute path to workspace
        categories: Optional list of categories to check
                   (unreachable, unused_exports, zombie_css, unused_vars, dead_listeners)
        config: CodeLens config

    Returns:
        Dict with all detected dead code, categorized and prioritized
    """
    workspace = os.path.abspath(workspace)

    valid_categories = {
        "unreachable", "unused_exports", "zombie_css",
        "unused_vars", "dead_listeners"
    }

    if categories:
        categories = [c for c in categories if c in valid_categories]
    else:
        categories = list(valid_categories)

    results: Dict[str, List[Dict]] = {cat: [] for cat in valid_categories}
    files_scanned = 0

    # Collect all exports and imports for cross-file analysis
    all_exports: Dict[str, List[Dict]] = defaultdict(list)   # file → exports
    all_imports: Dict[str, Set[str]] = defaultdict(set)      # file → imported names

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1
            lines = content.split('\n')

            # ─── Unreachable Code ────────────────────────
            if "unreachable" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}:
                unreachable = _detect_unreachable_code(content, ext, rel_path)
                results["unreachable"].extend(unreachable)

            # ─── Unused Variables ────────────────────────
            if "unused_vars" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}:
                unused = _detect_unused_variables(content, ext, rel_path)
                results["unused_vars"].extend(unused)

            # ─── Collect exports/imports ─────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                _collect_js_exports_imports(content, ext, rel_path, all_exports, all_imports)

            elif ext == ".py":
                _collect_py_exports_imports(content, rel_path, all_exports, all_imports)

    # ─── Unused Exports ──────────────────────────────────
    if "unused_exports" in categories:
        unused_exps = _detect_unused_exports(all_exports, all_imports, workspace)
        results["unused_exports"] = unused_exps

    # ─── Zombie CSS ──────────────────────────────────────
    if "zombie_css" in categories:
        zombie = _detect_zombie_css(workspace)
        results["zombie_css"] = zombie

    # ─── Dead Event Listeners ────────────────────────────
    if "dead_listeners" in categories:
        dead = _detect_dead_listeners(workspace)
        results["dead_listeners"] = dead

    # Compute totals
    total = sum(len(v) for v in results.values())
    by_category = {k: len(v) for k, v in results.items() if v}

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "files_scanned": files_scanned,
            "total_dead_code": total,
            "by_category": by_category
        },
        "results": {k: v for k, v in results.items() if v},
        "categories_checked": list(categories)
    }

def _detect_unreachable_code(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect code that comes after return/throw/break/continue and is therefore unreachable."""
    items = []
    lines = content.split('\n')

    # Track function scope boundaries
    in_function = False
    found_terminal = False
    terminal_line = 0
    terminal_type = ""

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('/*'):
            if found_terminal:
                continue
            continue

        # Detect function start
        if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
            if re.match(r'(?:export\s+)?(?:async\s+)?function\s+\w+', stripped):
                in_function = True
                found_terminal = False
        elif ext == ".py":
            if re.match(r'(?:async\s+)?def\s+\w+', stripped):
                in_function = True
                found_terminal = False
        elif ext == ".rs":
            if re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+', stripped):
                in_function = True
                found_terminal = False

        # Detect terminal statements
        if in_function:
            if re.match(r'(?:return|throw|break|continue)\s', stripped):
                found_terminal = True
                terminal_line = i + 1
                terminal_type = stripped.split()[0]

            # Detect closing brace (function end)
            if ext != ".py" and stripped == '}':
                in_function = False
                found_terminal = False
                continue

            # Check if we're at a lower indentation (function ended in Python)
            if ext == ".py" and in_function and found_terminal:
                base_indent = len(lines[terminal_line - 1]) - len(lines[terminal_line - 1].lstrip())
                current_indent = len(line) - len(line.lstrip()) if stripped else 0
                if current_indent <= base_indent and stripped:
                    in_function = False
                    found_terminal = False
                    continue

            # If we found a terminal statement and this is the next real code
            if found_terminal and i > terminal_line and not stripped.startswith(('}', 'catch', 'except', 'elif', 'else', 'finally', '//', '#')):
                items.append({
                    "file": rel_path,
                    "line": i + 1,
                    "after": terminal_type,
                    "after_line": terminal_line,
                    "severity": "warning",
                    "message": f"Unreachable code after {terminal_type} on line {terminal_line}",
                    "suggestion": f"Remove code after {terminal_type} or fix the control flow."
                })
                found_terminal = False  # Only report first unreachable

    return items

def _detect_unused_variables(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect variables that are declared but never read."""
    items = []

    # Remove comments and strings for more accurate detection
    # Use negative lookbehind to avoid stripping URLs (https://...)
    clean_content = re.sub(r'(?<!:)//.*$', '', content, flags=re.MULTILINE)
    clean_content = re.sub(r'/\*.*?\*/', '', clean_content, flags=re.DOTALL)

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Find const/let/var declarations
        for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1

            # Skip common patterns that are used indirectly
            skip_names = {'_', 'e', 'err', 'error', 'res', 'req', 'ctx', 'props', 'state', 'ref', 'config', 'module'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            if var_name.isupper():  # Constants are often used elsewhere
                continue

            # Check if variable is used anywhere else in the file
            # Count occurrences excluding the declaration
            usage_pattern = r'\b' + re.escape(var_name) + r'\b'
            all_occurrences = list(re.finditer(usage_pattern, clean_content))

            if len(all_occurrences) <= 1:
                items.append({
                    "file": rel_path,
                    "line": line_num,
                    "variable": var_name,
                    "severity": "info",
                    "message": f"Variable '{var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '{var_name}' or prefix with _ to suppress."
                })

    elif ext == ".py":
        # Find variable assignments (not in function signatures)
        for m in re.finditer(r'^(\w+)\s*=\s*', clean_content, re.MULTILINE):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1

            skip_names = {'_', 'e', 'err', 'error', 'self', 'cls', 'main', 'logger'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            if var_name.isupper():
                continue

            usage_pattern = r'\b' + re.escape(var_name) + r'\b'
            all_occurrences = list(re.finditer(usage_pattern, clean_content))

            if len(all_occurrences) <= 1:
                items.append({
                    "file": rel_path,
                    "line": line_num,
                    "variable": var_name,
                    "severity": "info",
                    "message": f"Variable '{var_name}' assigned but never used",
                    "suggestion": f"Remove or use the variable."
                })

    return items[:100]  # Cap to avoid noise

def _collect_js_exports_imports(
    content: str, ext: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect JS/TS export and import declarations."""
    # Named exports: export const/function/class X
    for m in re.finditer(r'export\s+(?:const|let|var|function|class|async\s+function)\s+(\w+)', content):
        exports[rel_path].append({
            "name": m.group(1),
            "type": "named_export",
            "line": content[:m.start()].count('\n') + 1
        })

    # Default exports
    for m in re.finditer(r'export\s+default\s+(?:function\s+)?(\w+)', content):
        exports[rel_path].append({
            "name": m.group(1) or "default",
            "type": "default_export",
            "line": content[:m.start()].count('\n') + 1
        })

    # Re-exports: export { X } from ...
    for m in re.finditer(r'export\s+\{([^}]+)\}', content):
        names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
        for name in names:
            if name:
                exports[rel_path].append({
                    "name": name,
                    "type": "re_export",
                    "line": content[:m.start()].count('\n') + 1
                })

    # Imports
    for m in re.finditer(r'import\s+(?:\{([^}]+)\}|\*\s+as\s+(\w+)|(\w+))\s+from', content):
        if m.group(1):  # Named imports
            names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
            for name in names:
                if name:
                    imports[rel_path].add(name)
        elif m.group(2):  # Namespace import
            imports[rel_path].add(m.group(2))
        elif m.group(3):  # Default import
            imports[rel_path].add(m.group(3))

def _collect_py_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Python imports and module-level definitions."""
    for line in content.split('\n'):
        stripped = line.strip()

        # Imports
        m = re.match(r'from\s+(\w+)\s+import\s+(.+)', stripped)
        if m:
            names = [n.strip() for n in m.group(2).split(',')]
            for name in names:
                imports[rel_path].add(name.split(' as ')[0].strip())

        m = re.match(r'import\s+(.+)', stripped)
        if m:
            names = [n.strip() for n in m.group(1).split(',')]
            for name in names:
                imports[rel_path].add(name.split(' as ')[0].strip())

    # Top-level functions and classes as potential exports
    for m in re.finditer(r'^(?:async\s+)?def\s+(\w+)|^class\s+(\w+)', content, re.MULTILINE):
        name = m.group(1) or m.group(2)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "python_definition",
            "line": line_num
        })

def _detect_unused_exports(
    all_exports: Dict[str, List[Dict]],
    all_imports: Dict[str, Set[str]],
    workspace: str
) -> List[Dict]:
    """Detect exports that are never imported anywhere."""
    # Build set of all imported names
    all_imported_names: Set[str] = set()
    for names in all_imports.values():
        all_imported_names.update(names)

    unused = []
    for file_path, exports in all_exports.items():
        # Skip test files and index files (they may be entry points)
        if any(x in file_path for x in ['.test.', '.spec.', '__tests__']):
            continue
        if file_path.endswith('index.js') or file_path.endswith('index.ts'):
            continue

        for export in exports:
            name = export["name"]

            # Skip common entry-point exports
            if name in {'default', 'app', 'server', 'main', 'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'configure', 'setup'}:
                continue

            if name not in all_imported_names:
                unused.append({
                    "file": file_path,
                    "line": export["line"],
                    "name": name,
                    "type": export["type"],
                    "severity": "warning",
                    "message": f"Export '{name}' is never imported by any file",
                    "suggestion": f"Remove unused export '{name}' or add import where needed."
                })

    return unused[:50]

def _detect_zombie_css(workspace: str) -> List[Dict]:
    """Detect CSS classes defined but never used in HTML/JS/TSX."""
    try:
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)
    except Exception:
        logger.debug("Dead code analysis failed", exc_info=True)
        return []

    zombie = []

    # CSS classes with ref_count == 0 AND no JS usage
    for cls in frontend.get("classes", []):
        if cls["status"] == "dead" and not cls.get("js"):
            zombie.append({
                "file": cls.get("css", [{}])[0].get("path", "unknown") if cls.get("css") else "unknown",
                "line": cls.get("css", [{}])[0].get("line", 0) if cls.get("css") else 0,
                "class": cls["name"],
                "severity": "info",
                "message": f"CSS class '.{cls['name']}' defined but never used in HTML or JS",
                "suggestion": f"Remove unused CSS class '.{cls['name']}' or add to HTML/JSX."
            })

    return zombie[:50]

def _detect_dead_listeners(workspace: str) -> List[Dict]:
    """Detect event listeners that listen for events on selectors that don't exist in HTML."""
    try:
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)
    except Exception:
        logger.debug("Dead code analysis failed", exc_info=True)
        return []

    # Get all known IDs and classes
    known_ids = {id_entry["name"] for id_entry in frontend.get("ids", [])}
    known_classes = {cls["name"] for cls in frontend.get("classes", [])}

    dead = []

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            # Find addEventListener or .on() with selectors
            for m in re.finditer(
                r'(?:addEventListener|\.on)\s*\(\s*["\'](\w+)["\']',
                content
            ):
                line_num = content[:m.start()].count('\n') + 1
                # Check if the selector references an unknown ID/class
                # This is a heuristic — we look for getElementById or querySelector nearby
                context_start = max(0, m.start() - 100)
                context = content[context_start:m.end()]

                for id_match in re.finditer(r'getElementById\s*\(\s*["\']([^"\']+)["\']', context):
                    if id_match.group(1) not in known_ids:
                        dead.append({
                            "file": rel_path,
                            "line": line_num,
                            "selector_type": "id",
                            "selector": id_match.group(1),
                            "severity": "warning",
                            "message": f"Event listener on #{id_match.group(1)} which doesn't exist in HTML",
                            "suggestion": f"Check if '#{id_match.group(1)}' was renamed or removed."
                        })

                for class_match in re.finditer(r'getElementsByClassName\s*\(\s*["\']([^"\']+)["\']', context):
                    if class_match.group(1) not in known_classes:
                        dead.append({
                            "file": rel_path,
                            "line": line_num,
                            "selector_type": "class",
                            "selector": class_match.group(1),
                            "severity": "info",
                            "message": f"Event listener on .{class_match.group(1)} which isn't in registry",
                            "suggestion": f"Verify that '.{class_match.group(1)}' class still exists."
                        })

    return dead[:30]
