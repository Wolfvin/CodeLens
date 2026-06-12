"""
Enhanced Dead Code Detection Engine for CodeLens — v3
Goes beyond the basic 0-ref_count check to find:
1. Unreachable code branches (code after return/throw/break)
2. Unused exports (exported but never imported)
3. Zombie CSS (CSS classes defined but never referenced in HTML/JS)
4. Dead event listeners (listeners on elements that don't exist)
5. Unused variables (declared but never read)
6. Unreachable catch blocks (catch for error type that can't be thrown)

Performance: Includes --max-results cap and file-count limits to prevent
timeout on very large codebases (100k+ files).
"""

import os
import re
import json
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, safe_read_file, MAX_FILE_SIZE, logger

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".css", ".scss", ".less",
    ".go", ".cc", ".cpp", ".cxx", ".c", ".h", ".hpp",
    ".lua", ".java", ".cs", ".php", ".zig",
}

# Performance limits for large codebases
MAX_FILES_PER_CATEGORY = 5000    # Max files to scan per category
MAX_RESULTS_PER_CATEGORY = 200   # Max results to return per category


def detect_dead_code(
    workspace: str,
    categories: Optional[List[str]] = None,
    config: Optional[Dict] = None,
    max_results: int = MAX_RESULTS_PER_CATEGORY,
    max_files: int = MAX_FILES_PER_CATEGORY
) -> Dict[str, Any]:
    """
    Enhanced dead code detection beyond basic ref_count==0.

    Args:
        workspace: Absolute path to workspace
        categories: Optional list of categories to check
                   (unreachable, unused_exports, zombie_css, unused_vars, dead_listeners)
        config: CodeLens config
        max_results: Max results per category (default 200)
        max_files: Max files to scan per category (default 5000)

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
    truncated = False

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

            # File-count limit to prevent timeout on huge repos
            if files_scanned >= max_files:
                truncated = True
                break

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Use safe_read_file with size limit to avoid slow scans
            content = safe_read_file(file_path, MAX_FILE_SIZE)
            if content is None:
                continue

            files_scanned += 1
            lines = content.split('\n')

            # ─── Unreachable Code ────────────────────────
            if "unreachable" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
                if len(results["unreachable"]) < max_results:
                    unreachable = _detect_unreachable_code(content, ext, rel_path)
                    results["unreachable"].extend(unreachable)

            # ─── Unused Variables ────────────────────────
            if "unused_vars" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
                if len(results["unused_vars"]) < max_results:
                    unused = _detect_unused_variables(content, ext, rel_path)
                    results["unused_vars"].extend(unused)

            # ─── Collect exports/imports ─────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                _collect_js_exports_imports(content, ext, rel_path, all_exports, all_imports)

            elif ext == ".py":
                _collect_py_exports_imports(content, rel_path, all_exports, all_imports)

        if truncated:
            break

    # ─── Unused Exports ──────────────────────────────────
    if "unused_exports" in categories:
        unused_exps = _detect_unused_exports(all_exports, all_imports, workspace)
        results["unused_exports"] = unused_exps[:max_results]

    # ─── Zombie CSS ──────────────────────────────────────
    if "zombie_css" in categories:
        zombie = _detect_zombie_css(workspace)
        results["zombie_css"] = zombie[:max_results]

    # ─── Dead Event Listeners ────────────────────────────
    if "dead_listeners" in categories:
        dead = _detect_dead_listeners(workspace)
        results["dead_listeners"] = dead[:max_results]

    # Truncate any remaining categories
    for cat in results:
        if len(results[cat]) > max_results:
            results[cat] = results[cat][:max_results]
            truncated = True

    # v6: Use the backend registry's ref_count data when available.
    #     Functions with ref_count == 0 and status == "dead" from the scan
    #     should be reported as dead code.
    registry_dead = _detect_dead_from_registry(workspace)
    if registry_dead:
        results["registry_dead"] = registry_dead[:max_results]

    # Compute totals
    total = sum(len(v) for v in results.values())
    by_category = {k: len(v) for k, v in results.items() if v}

    # Determine removal safety and recommended action based on findings
    high_severity = sum(
        1 for items in results.values()
        for item in items
        if item.get("severity") == "critical"
    )
    if high_severity > 0:
        removal_safety = "dangerous"
        recommended_action = "Review critical dead code before removal — some may be dynamically accessed"
    elif total > 50:
        removal_safety = "cautious"
        recommended_action = "Large amount of dead code found — remove in batches with testing"
    elif total > 10:
        removal_safety = "mostly_safe"
        recommended_action = "Moderate dead code found — review and remove with standard testing"
    elif total > 0:
        removal_safety = "safe"
        recommended_action = "Small amount of dead code found — safe to remove"
    else:
        removal_safety = "clean"
        recommended_action = "No dead code detected"

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "files_scanned": files_scanned,
            "total_dead_code": total,
            "by_category": by_category,
            "truncated": truncated
        },
        "results": {k: v for k, v in results.items() if v},
        "categories_checked": list(categories),
        "removal_safety": removal_safety,
        "recommended_action": recommended_action
    }

def _detect_unreachable_code(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect code that comes after return/throw/break/continue and is therefore unreachable.

    v6: Fixed function scope tracking by using brace depth tracking instead of
    resetting in_function on every closing brace. Now only exits function scope
    when the brace depth returns to the level it was at before the function started.

    v5.10: Fixed Rust match arm false positives. In Rust, each match arm ends
    with a terminal statement (return/expression), but the next arm is a separate
    branch and NOT unreachable. We now track match arm boundaries (comma after
    expression or closing brace) and reset the terminal flag at each new arm.
    """
    items = []
    lines = content.split('\n')

    # v6: Track brace depth to know when a function truly ends
    brace_depth = 0           # current brace nesting level
    function_start_depth = -1  # brace depth when the current function started
    in_function = False
    found_terminal = False
    terminal_line = 0
    terminal_type = ""
    terminal_depth = 0         # v7: brace depth where the terminal statement was found

    # v5.10: Rust match arm tracking
    in_match = False
    match_start_depth = 0
    last_arm_depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # v6: Update brace depth for every line (even comments/blanks may contain braces)
        if ext != ".py":
            for ch in stripped:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1

        # Skip empty lines and comments
        if not stripped or stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('/*'):
            if found_terminal:
                continue
            continue

        # v5.10: Track Rust match expressions
        if ext == ".rs":
            if re.match(r'\s*match\s+', stripped):
                in_match = True
                match_start_depth = brace_depth
            # End match when we return to the depth where match started
            if in_match and brace_depth <= match_start_depth and '{' not in stripped:
                in_match = False

        # Detect function start
        if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
            if re.match(r'(?:export\s+)?(?:async\s+)?function\s+\w+', stripped):
                in_function = True
                found_terminal = False
                function_start_depth = brace_depth  # v6: record depth at function start
        elif ext == ".py":
            if re.match(r'(?:async\s+)?def\s+\w+', stripped):
                in_function = True
                found_terminal = False
                # For Python, track the indentation of the def line
                function_indent = len(line) - len(line.lstrip())
        elif ext == ".rs":
            if re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+', stripped):
                in_function = True
                found_terminal = False
                function_start_depth = brace_depth  # v6: record depth at function start

        # Detect terminal statements
        if in_function:
            if re.match(r'(?:return|throw|break|continue)\s', stripped):
                # v5.10: In Rust match arms, terminal statements are normal —
                # the next arm is NOT unreachable. Skip reporting if we're in a match.
                if ext == ".rs" and in_match:
                    found_terminal = False  # Reset, don't flag match arm terminals
                    continue
                # v8: Multi-line return statements in Rust/C-like languages.
                # If the return line doesn't end with ';' or '}' or ')' or ']', the
                # return expression continues on the next line — don't flag as terminal yet.
                if ext in {".rs", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                    if not stripped.endswith(';') and not stripped.endswith('}') and not stripped.endswith(')') and not stripped.endswith(']'):
                        continue  # Not a complete return statement yet
                found_terminal = True
                terminal_line = i + 1
                terminal_type = stripped.split()[0]
                terminal_depth = brace_depth  # v7: record depth of terminal statement

            # v5.10: Rust match arm separator — new arm starts after => or pattern
            if ext == ".rs" and in_match:
                # A new match arm pattern resets the terminal flag
                if re.match(r'\s*[\w].*=>', stripped) or re.match(r'\s*_\s*=>', stripped):
                    found_terminal = False
                    continue
                # Comma at match depth signals end of arm — next arm is not unreachable
                if stripped.endswith(',') and brace_depth <= match_start_depth + 1:
                    found_terminal = False
                    continue

            # v6: Detect function end via brace depth — only end function when
            #     depth returns to the level before the function started.
            #     This avoids resetting on every '}' (e.g. if-blocks inside functions).
            if ext != ".py" and brace_depth < function_start_depth:
                in_function = False
                found_terminal = False
                in_match = False
                continue

            # v7: If we've exited the scope where the terminal statement was found
            #     (e.g., closing brace of an if-block that contained a return),
            #     the code after the closing brace is still reachable.
            #     Reset found_terminal when brace depth drops to or below terminal_depth.
            if found_terminal and ext != ".py" and brace_depth <= terminal_depth and stripped.startswith('}'):
                found_terminal = False
                continue

            # Check if we're at a lower indentation (function ended in Python)
            if ext == ".py" and in_function and found_terminal:
                current_indent = len(line) - len(line.lstrip()) if stripped else 0
                if current_indent <= function_indent and stripped:
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
    clean_content = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    # Use bounded quantifier to avoid catastrophic backtracking
    clean_content = re.sub(r'/\*[\s\S]{0,50000}?\*/', '', clean_content)

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Find const/let/var declarations (including destructuring)
        declared_vars = []

        # Standard declarations: const/let/var x = ...
        for m in re.finditer(r'(?:const|let|var)\s+(\w+)\s*=', clean_content):
            declared_vars.append((m.group(1), m.start()))

        # Object destructuring: const { a, b, c } = ...
        for m in re.finditer(r'(?:const|let|var)\s*\{\s*([^}]+)\}\s*=', clean_content):
            names_str = m.group(1)
            for name_match in re.finditer(r'(\w+)(?:\s*:\s*\w+)?', names_str):
                declared_vars.append((name_match.group(1), m.start()))

        # Array destructuring: const [a, b, c] = ...
        for m in re.finditer(r'(?:const|let|var)\s*\[\s*([^\]]+)\]\s*=', clean_content):
            names_str = m.group(1)
            for name_match in re.finditer(r'(\w+)', names_str):
                declared_vars.append((name_match.group(1), m.start()))

        for var_name, start_pos in declared_vars:
            line_num = clean_content[:start_pos].count('\n') + 1

            # Skip common patterns that are used indirectly
            skip_names = {'_', 'e', 'err', 'error', 'res', 'req', 'ctx', 'props', 'state', 'ref', 'config', 'module'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            # v6: Keep the ALL_CAPS skip but note that cross-file usage analysis
            #     would be more accurate. Constants like API_URL, MAX_RETRIES are
            #     typically used across files — skipping avoids false positives.
            #     TODO: Cross-file reference check for ALL_CAPS vars.
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
            # Skip ALL_CAPS names — they are module-level constants often imported elsewhere
            if var_name.isupper():
                continue

            # Skip Python type aliases: names ending in "Types" or "Type" that are
            # type alias definitions (e.g., URLTypes = ..., HeaderTypes = ...).
            # These are used in type annotations, not as runtime variables.
            line_text = clean_content.split('\n')[line_num - 1] if line_num <= len(clean_content.split('\n')) else ''
            if var_name.endswith('Types') or var_name.endswith('Type'):
                # Check if RHS contains type-related patterns
                rhs = line_text.split('=', 1)[1].strip() if '=' in line_text else ''
                type_indicators = ['Union', 'Optional', 'List', 'Dict', 'Tuple', 'Set',
                                   'Callable', 'Type', 'Sequence', 'Mapping', 'Iterable',
                                   'AsyncIterator', 'Iterator', 'Any', 'Protocol',
                                   'typing.', 'Annotated']
                if any(ind in rhs for ind in type_indicators):
                    continue

            # Skip TypeAlias annotations: e.g., URLTypes: TypeAlias = ...
            if ': TypeAlias' in line_text or ': typealias' in line_text.lower():
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
            if name in {'default', 'handler', 'app', 'server', 'router', 'main', 'configure', 'setup'}:
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

def _detect_dead_from_registry(workspace: str) -> List[Dict]:
    """v6: Read the backend registry from .codelens/backend.json and report
    functions with ref_count == 0 and status == 'dead' as dead code."""
    registry_path = os.path.join(workspace, '.codelens', 'backend.json')
    if not os.path.isfile(registry_path):
        return []

    try:
        with open(registry_path, 'r', encoding='utf-8') as f:
            registry = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    dead_items = []
    nodes = registry.get("nodes", [])
    if not isinstance(nodes, list):
        return []

    for node in nodes:
        if not isinstance(node, dict):
            continue
        ref_count = node.get("ref_count", -1)
        status = node.get("status", "")
        # Backend registry uses "fn" for function name, not "name"
        name = node.get("fn", "") or node.get("name", "")
        file_path = node.get("file", "")
        line = node.get("line", 0)
        node_type = node.get("type", "function")
        impl_for = node.get("impl_for", "")
        is_pub = node.get("pub", False)

        # v6: Report functions with ref_count == 0 and status == "dead"
        # But skip: main() functions (entry points), pub functions (public API),
        # and functions in test files
        if ref_count == 0 and status == "dead":
            # Skip main functions — they're entry points, not dead code
            # Handle both simple "main" and qualified names like "crate::main"
            bare_name = name.split('::')[-1] if '::' in name else name
            if bare_name == "main":
                continue
            # Also skip Rust #[tokio::main] and #[actix::main] entry point functions
            # These are async entry points that appear as "main" in the registry
            if file_path.endswith('.rs') and name == "main":
                continue
            # Skip pub functions — they're public API, likely used externally
            if is_pub:
                continue
            # Skip test fixtures and example files
            if any(x in file_path for x in ['/test', '/tests', '/__test', '/example', '/fixture', '/mock']):
                continue

            # v6.4: Skip Rust trait implementation methods that are required by the trait.
            # Methods like Default::default, From::from, Display::fmt, etc. are called
            # implicitly through the trait dispatch, so ref_count == 0 is a false positive.
            if file_path.endswith('.rs') and impl_for:
                # Known standard library traits whose methods are called implicitly
                _rust_std_traits = {
                    'Default', 'From', 'Into', 'TryFrom', 'TryInto',
                    'Display', 'Debug', 'Fmt', 'Write',
                    'Clone', 'Copy', 'PartialEq', 'Eq', 'PartialOrd', 'Ord',
                    'Hash', 'Iterator', 'IntoIterator', 'FromIterator',
                    'Add', 'Sub', 'Mul', 'Div', 'Rem', 'Not', 'Neg',
                    'Index', 'IndexMut', 'Deref', 'DerefMut', 'Drop',
                    'Fn', 'FnMut', 'FnOnce', 'AsRef', 'AsMut',
                    'ToString', 'ToStr', 'Borrow', 'BorrowMut',
                    'Serialize', 'Deserialize',  # serde traits
                    'Read', 'Write', 'Seek',  # std::io traits
                    'Error',  # std::error::Error
                    'Sum', 'Product',  # iterator aggregation
                }
                # Skip if impl_for matches a known standard trait
                impl_trait = impl_for.split('<')[0].split('+')[0].strip()
                if impl_trait in _rust_std_traits:
                    continue
                # Also skip impl blocks where the function name matches
                # a standard trait method pattern (e.g., "default", "from", "fmt")
                _rust_trait_methods = {
                    'default', 'from', 'into', 'try_from', 'try_into',
                    'fmt', 'clone', 'hash', 'next', 'iter',
                    'deref', 'deref_mut', 'drop', 'as_ref', 'as_mut',
                    'to_string', 'borrow', 'borrow_mut',
                    'read', 'write', 'seek', 'description', 'source',
                    'call', 'call_mut', 'call_once',
                    'add', 'sub', 'mul', 'div', 'rem', 'not', 'neg',
                    'index', 'index_mut', 'sum', 'product',
                    'serialize', 'deserialize',
                }
                if bare_name in _rust_trait_methods:
                    continue

            # v6.4: Skip Rust #[cfg(test)] module functions
            # Functions inside #[cfg(test)] blocks are only compiled in test mode
            # and would show as "dead" in a normal scan.
            if file_path.endswith('.rs'):
                # Check if the function name starts with test_ or is in a test module
                if bare_name.startswith('test_') or bare_name.startswith('it_'):
                    continue
                # Check if the file is a test-only file (heuristic: file name starts with test_)
                file_basename = os.path.basename(file_path)
                if file_basename.startswith('test_'):
                    continue

            # v6.4: Skip Rust build.rs functions
            # Functions in build.rs are called by the Cargo build system, not by other code.
            if file_path.endswith('build.rs'):
                continue

            # v6.3: Skip known C/C++ entry point function patterns
            # These are almost never dead code — they're called by the OS/runtime
            _c_entry_patterns = {
                'main', 'WinMain', 'DllMain', 'wmain', '_tmain',
                'nvim_main',  # neovim pattern
            }
            if name in _c_entry_patterns and file_path.endswith(('.c', '.h', '.cpp', '.hpp')):
                continue

            # v6.3: Skip functions with _main, _init, _start, _entry suffix/prefix in C files
            # These are typically called by runtime/linker, not by other code
            if file_path.endswith(('.c', '.h', '.cpp', '.hpp')):
                lower_name = name.lower()
                if any(lower_name.endswith(s) for s in ('_main', '_init', '_start', '_entry', '_begin')):
                    continue
                if any(lower_name.startswith(s) for s in ('main', 'init', 'start', 'entry')):
                    # Only skip if the function is at the top level (not a method)
                    if node_type == "function":
                        continue

            display_name = f"{impl_for}::{name}" if impl_for else name
            dead_items.append({
                "file": file_path,
                "line": line,
                "name": display_name,
                "type": node_type,
                "severity": "warning",
                "message": f"{node_type.capitalize()} '{display_name}' has zero references (marked dead in registry)",
                "suggestion": f"Remove unused {node_type} '{display_name}' or add a reference where needed."
            })

    return dead_items


def _detect_zombie_css(workspace: str) -> List[Dict]:
    """Detect CSS classes defined but never used in HTML/JS/TSX."""
    try:
        from registry import load_frontend_registry
        frontend = load_frontend_registry(workspace)
    except Exception:
        logger.debug("Dead code analysis failed", exc_info=True)
        return []

    # Load Tailwind detector to skip Tailwind utility classes
    try:
        from parsers.tailwind_detector import is_tailwind_class
        has_tailwind_check = True
    except ImportError:
        has_tailwind_check = False

    zombie = []

    # CSS classes with ref_count == 0 AND no JS usage
    for cls in frontend.get("classes", []):
        name = cls["name"]
        if cls["status"] == "dead" and not cls.get("js"):
            # Skip Tailwind utility classes — they're framework-defined, not user-defined
            if has_tailwind_check and is_tailwind_class(name):
                continue
            # Skip names that look like JS operators/expressions (e.g., '!==', '===', etc.)
            if not re.match(r'^[a-zA-Z_]', name):
                continue
            zombie.append({
                "file": cls.get("css", [{}])[0].get("path", "unknown") if cls.get("css") else "unknown",
                "line": cls.get("css", [{}])[0].get("line", 0) if cls.get("css") else 0,
                "class": name,
                "severity": "info",
                "message": f"CSS class '.{name}' defined but never used in HTML or JS",
                "suggestion": f"Remove unused CSS class '.{name}' or add to HTML/JSX."
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

            content = safe_read_file(file_path, MAX_FILE_SIZE)
            if content is None:
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
