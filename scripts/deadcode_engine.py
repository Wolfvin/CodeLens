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
import time
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, safe_read_file, MAX_FILE_SIZE, logger, time_budget_expired

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".css", ".scss", ".less",
    ".go", ".cc", ".cpp", ".cxx", ".c", ".h", ".hpp", ".hxx",
    ".lua", ".java", ".cs", ".php", ".zig",
    ".rb", ".ex", ".exs", ".swift", ".scala", ".sc",
    ".nim", ".nims", ".sh", ".bash", ".zsh", ".dart",
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
    TIMEOUT_BUDGET = 90  # seconds — prevent hanging on huge repos

    start_time = time.time()
    timed_out = False

    # Collect all exports and imports for cross-file analysis
    all_exports: Dict[str, List[Dict]] = defaultdict(list)   # file → exports
    all_imports: Dict[str, Set[str]] = defaultdict(set)      # file → imported names
    same_file_usages: Dict[str, Set[str]] = defaultdict(set) # file → names used within the file

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

            # Time budget check — bail out before hanging
            if time_budget_expired(start_time, TIMEOUT_BUDGET):
                timed_out = True
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
            if "unreachable" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".php", ".rb", ".lua", ".ex", ".exs", ".nim", ".nims", ".java", ".cs", ".swift", ".scala", ".dart", ".sh", ".bash", ".zsh"}:
                if len(results["unreachable"]) < max_results:
                    unreachable = _detect_unreachable_code(content, ext, rel_path)
                    results["unreachable"].extend(unreachable)

            # ─── Unused Variables ────────────────────────
            if "unused_vars" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".php", ".rb", ".lua", ".ex", ".exs", ".nim", ".nims", ".java", ".cs", ".swift", ".scala", ".dart", ".sh", ".bash", ".zsh"}:
                if len(results["unused_vars"]) < max_results:
                    unused = _detect_unused_variables(content, ext, rel_path)
                    results["unused_vars"].extend(unused)

            # ─── Collect exports/imports ─────────────────
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                _collect_js_exports_imports(content, ext, rel_path, all_exports, all_imports)

            elif ext == ".py":
                _collect_py_exports_imports(content, rel_path, all_exports, all_imports)
                # Track same-file usage: find all names referenced in the file
                _collect_py_same_file_usages(content, rel_path, same_file_usages)

            elif ext == ".go":
                _collect_go_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".rs":
                _collect_rust_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
                _collect_c_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".lua":
                _collect_lua_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".php":
                _collect_php_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext in {".ex", ".exs"}:
                _collect_elixir_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".rb":
                _collect_ruby_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext in {".nim", ".nims"}:
                _collect_nim_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".java":
                _collect_java_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".cs":
                _collect_csharp_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".swift":
                _collect_swift_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext in {".scala", ".sc"}:
                _collect_scala_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext == ".dart":
                _collect_dart_exports_imports(content, rel_path, all_exports, all_imports)

            elif ext in {".sh", ".bash", ".zsh"}:
                _collect_shell_exports_imports(content, rel_path, all_exports, all_imports)

            # ─── Collect name references (usages) for improved cross-file analysis ───
            # For JS/TS/Python, import statements directly name what's imported, so
            # the imports dict already captures usage. For Go, Rust, C, Lua, PHP,
            # Elixir, Ruby etc., the import mechanism brings in packages/modules and
            # names are used via qualified access (pkg.Func) or direct calls.
            # This step collects those usage references so _detect_unused_exports
            # can check if an exported name is actually used anywhere.
            if ext in {".go", ".rs", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx",
                       ".lua", ".php", ".ex", ".exs", ".rb", ".java", ".cs", ".swift",
                       ".scala", ".sc", ".dart", ".nim", ".nims", ".sh", ".bash", ".zsh"}:
                _collect_name_references(content, ext, rel_path, all_imports)

        if truncated:
            break

    # ─── Unused Exports ──────────────────────────────────
    if "unused_exports" in categories:
        unused_exps = _detect_unused_exports(all_exports, all_imports, workspace, same_file_usages)
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

    # v6.4: Add source classification to all findings and downgrade non-core severity
    _TEST_EXAMPLE_PATTERNS = [
        '/test/', '/tests/', '/__test', '/__tests__/',
        '/example/', '/examples/', '/e2e/',
        '/fixture/', '/fixtures/', '/mock/', '/mocks/',
        '/stories/', '/storybook/', '/snippets/',
        '/docs_src/', '/doc_src/', '/docs/examples/',
        '/documentation/', '/tutorial/',
    ]
    _CONFIG_PATTERNS = [
        '.config.js', '.config.mjs', '.config.ts',
        'webpack.config.', 'vite.config.', 'jest.config.',
        'tsconfig.json', 'postcss.config.', 'tailwind.config.',
        'babel.config.', 'eslint.config.',
    ]

    def _classify_source(rel: str) -> str:
        normalized = '/' + rel if not rel.startswith('/') else rel
        for p in _TEST_EXAMPLE_PATTERNS:
            if p in normalized or normalized.startswith(p.lstrip('/')):
                return 'test'
        for p in _CONFIG_PATTERNS:
            if p in rel:
                return 'config'
        return 'core'

    by_source = {"core": 0, "test": 0, "config": 0, "library_api": 0}
    for cat, items in results.items():
        for item in items:
            # Preserve existing source if already set (e.g., library_api from unused_exports)
            if item.get('source') in ('library_api',):
                by_source['library_api'] = by_source.get('library_api', 0) + 1
                continue
            fpath = item.get('file', '')
            source = _classify_source(fpath)
            item['source'] = source
            by_source[source] = by_source.get(source, 0) + 1
            # Downgrade severity for non-core findings
            if source in ('test', 'config'):
                sev = item.get('severity', 'warning')
                if sev == 'critical':
                    item['severity'] = 'warning'
                    item['downgraded'] = True
                elif sev == 'warning':
                    item['severity'] = 'info'
                    item['downgraded'] = True

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

    # Build categories dict (same as results, for API compatibility)
    categories_dict = {k: v for k, v in results.items() if v}

    # v8.2 (issue #5): enrich every finding with a confidence score so
    # agents can rank actionable vs. needs-review findings. Scores are
    # category-driven with modifier adjustments (test files, library API,
    # downgraded severity, etc.). See scripts/confidence.py for the model.
    try:
        from confidence import enrich_findings
    except ImportError:
        # Defensive: never let confidence scoring break the engine.
        enrich_findings = None

    payload = {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "files_scanned": files_scanned,
            "total_dead_code": total,
            "by_category": by_category,
            "truncated": truncated,
            "by_source": by_source
        },
        "results": {k: v for k, v in results.items() if v},
        "categories": categories_dict,
        "categories_checked": list(categories),
        "removal_safety": removal_safety,
        "recommended_action": recommended_action,
        "timed_out": timed_out,
        "duration_ms": int((time.time() - start_time) * 1000),
    }

    if enrich_findings is not None:
        payload = enrich_findings("dead_code", payload)

    return payload

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
    terminal_indent = 0        # Python: indentation level of the terminal statement

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
        # Elixir: comments start with #
        # Ruby: comments start with #
        # Lua: comments start with --
        if ext in {".ex", ".exs", ".rb"}:
            if not stripped or stripped.startswith('#'):
                if found_terminal:
                    continue
                continue
        elif not stripped or stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('/*') or stripped.startswith('--'):
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
        elif ext == ".go":
            if re.match(r'\s*func\s+(?:\([^)]+\)\s+)?\w+\s*\(', stripped):
                in_function = True
                found_terminal = False
                function_start_depth = brace_depth
        elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
            if re.match(r'\s*(?:static\s+|inline\s+|extern\s+|virtual\s+|constexpr\s+)*'
                        r'(?:[\w:*&<>,\s]+?)\s+\w+(?:::\w+)*\s*\([^)]*\)\s*(?:const\s*)?(?:->\s*[\w:*&<>,\s]+\s*)?\{', stripped):
                in_function = True
                found_terminal = False
                function_start_depth = brace_depth
        elif ext == ".lua":
            if re.match(r'\s*(?:local\s+)?function\s+[\w:.]+\s*\(', stripped):
                in_function = True
                found_terminal = False
        elif ext == ".php":
            if re.match(r'\s*(?:(?:public|private|protected|static|abstract|final)\s+)*function\s+\w+\s*\(', stripped):
                in_function = True
                found_terminal = False
                function_start_depth = brace_depth
        elif ext in {".ex", ".exs"}:
            # Elixir: def/defp/defmacro start a function; they end at the next end
            if re.match(r'\s*(?:def|defp|defmacro|defmacrop)\s+\w+', stripped):
                in_function = True
                found_terminal = False
        elif ext == ".rb":
            # Ruby: def starts a method; ends at the next end
            if re.match(r'\s*def\s+\w+', stripped):
                in_function = True
                found_terminal = False

        # Detect terminal statements
        if in_function:
            # Elixir: raise is a terminal statement
            if ext in {".ex", ".exs"}:
                if re.match(r'(?:return|raise|throw|exit)\b', stripped):
                    found_terminal = True
                    terminal_line = i  # 0-based: next line has i+1 > i = True
                    terminal_type = stripped.split()[0]
                    terminal_depth = brace_depth
            # Ruby: raise/return/throw are terminal
            elif ext == ".rb":
                if re.match(r'(?:return|raise|throw|fail|exit)\b', stripped):
                    found_terminal = True
                    terminal_line = i  # 0-based: next line has i+1 > i = True
                    terminal_type = stripped.split()[0]
                    terminal_depth = brace_depth
            elif re.match(r'(?:return|throw|break|continue)\s', stripped):
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
                # v9: Multi-line return statements in Python.
                # If the return line has unclosed brackets/parens/braces, the
                # expression continues on the next line — don't flag as terminal yet.
                if ext == ".py":
                    open_count = stripped.count('(') + stripped.count('[') + stripped.count('{')
                    close_count = stripped.count(')') + stripped.count(']') + stripped.count('}')
                    if open_count > close_count:
                        # v10 (issue #105): Before skipping, check if we've already
                        # exited the block that contained the previous terminal
                        # statement. The classic false-positive pattern is:
                        #     if x:
                        #         return None       # terminal at indent 8
                        #     return {              # indent 4 — multiline start
                        #         "k": "v",          # indent 8 — was flagged as
                        #     }                      #   unreachable (same indent
                        #                            #   as the terminal inside if)
                        # The previous terminal was inside an `if` block; the
                        # current return is in the outer scope (lower indent),
                        # so the previous terminal is no longer relevant.
                        # Reset it so the multi-line return body is not flagged.
                        current_indent = len(line) - len(line.lstrip())
                        if found_terminal and terminal_indent > 0 and current_indent < terminal_indent:
                            found_terminal = False
                        continue  # Return expression continues on the next line
                found_terminal = True
                terminal_line = i  # 0-based: next line has i+1 > i = True
                terminal_type = stripped.split()[0]
                terminal_depth = brace_depth  # v7: record depth of terminal statement
                terminal_indent = len(lines[i]) - len(lines[i].lstrip())  # Python indent of terminal

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
            if ext not in {".py", ".lua", ".ex", ".exs", ".rb"} and brace_depth < function_start_depth:
                in_function = False
                found_terminal = False
                in_match = False
                continue

            # Lua: detect function end via 'end' keyword
            if ext == ".lua" and stripped == 'end':
                in_function = False
                found_terminal = False
                continue

            # Elixir: detect function end via 'end' keyword
            if ext in {".ex", ".exs"} and stripped == 'end':
                in_function = False
                found_terminal = False
                continue

            # Ruby: detect method end via 'end' keyword
            if ext == ".rb" and stripped == 'end':
                in_function = False
                found_terminal = False
                continue

            # v7: If we've exited the scope where the terminal statement was found
            #     (e.g., closing brace of an if-block that contained a return),
            #     the code after the closing brace is still reachable.
            #     Reset found_terminal when brace depth drops to or below terminal_depth.
            if found_terminal and ext != ".py" and brace_depth <= terminal_depth and stripped.startswith('}'):
                found_terminal = False
                continue

            # Python: if the current line is at a lower indent than the
            # terminal statement, we've exited the block containing the return.
            # Code at this level is in a different branch and is reachable.
            # Note: we use strict < (not <=) because code at the SAME indent
            # as a return is in the same block and IS unreachable.
            if ext == ".py" and in_function and found_terminal and terminal_indent > 0:
                current_indent = len(line) - len(line.lstrip()) if stripped else 0
                if current_indent < terminal_indent and stripped:
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
            _skip_prefixes = ('}', 'catch', 'except', 'elif', 'else', 'finally', '//', '#', 'end', '--')
            # Elixir/Ruby: also skip 'rescue', 'after'
            if ext in {".ex", ".exs"}:
                _skip_prefixes = ('}', 'catch', 'except', 'elif', 'else', 'finally', '//', '#', 'end', 'rescue', 'after')
            elif ext == ".rb":
                _skip_prefixes = ('}', 'catch', 'except', 'elif', 'else', 'finally', '//', '#', 'end', 'rescue', 'ensure', 'elsif')
            if found_terminal and i > terminal_line and not stripped.startswith(_skip_prefixes):
                items.append({
                    "file": rel_path,
                    "line": i + 1,
                    "after": terminal_type,
                    "after_line": terminal_line + 1,  # Convert to 1-based for output
                    "severity": "warning",
                    "message": f"Unreachable code after {terminal_type} on line {terminal_line + 1}",
                    "suggestion": f"Remove code after {terminal_type} or fix the control flow."
                })
                found_terminal = False  # Only report first unreachable
            elif found_terminal and stripped.startswith(('elif', 'else', 'except', 'finally')):
                # New branch starts after a terminal statement — code in the new branch
                # is reachable even though the previous branch had a return.
                # Reset the terminal flag so we don't falsely flag code in this new branch.
                found_terminal = False

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

            # Skip numeric literals that regex falsely captured as variable names
            # (e.g., 300_000, 10000 from patterns like const 300_000 = ...)
            if re.match(r'^\d[\d_]*$', var_name):
                continue

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

        # Detect unused Python imports
        # Collect all import names and check if they're used in the file
        import_names = []  # (name, line_num)
        for m in re.finditer(r'^import\s+(\w+)', clean_content, re.MULTILINE):
            name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            import_names.append((name, line_num))
        for m in re.finditer(r'^from\s+[\w.]+\s+import\s+(.+)', clean_content, re.MULTILINE):
            names_str = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            for name_match in re.finditer(r'(\w+)', names_str):
                name = name_match.group(1)
                if name == 'as':
                    continue
                import_names.append((name, line_num))

        _import_skip = {'os', 'sys', 'logging'}  # Commonly imported for side effects or implicit usage
        _typing_imports = {'List', 'Dict', 'Tuple', 'Set', 'Optional', 'Union', 'Any',
                           'Callable', 'Iterable', 'Iterator', 'Sequence', 'Mapping',
                           'Type', 'TypeVar', 'Generic', 'Protocol', 'Awaitable',
                           'AsyncIterator', 'AsyncIterable', 'Coroutine', 'Final',
                           'ClassVar', 'Literal', ' overload', 'NamedTuple', 'TypedDict'}
        for name, line_num in import_names:
            if name in _import_skip:
                continue
            if name in _typing_imports:
                continue  # Typing imports are used in annotations, hard to detect via regex
            if name.startswith('_'):
                continue
            # Check if the import is used in the file (not just the import line)
            usage_pattern = r'\b' + re.escape(name) + r'\b'
            all_occurrences = list(re.finditer(usage_pattern, clean_content))
            if len(all_occurrences) <= 1:
                items.append({
                    "file": rel_path,
                    "line": line_num,
                    "variable": name,
                    "severity": "info",
                    "message": f"Import '{name}' is never used",
                    "suggestion": f"Remove unused import '{name}'."
                })

    elif ext == ".go":
        # Find variable declarations: var x type, x := expr
        for m in re.finditer(r'(?:var\s+(\w+)\s+\w|(\w+)\s*:=)', clean_content):
            var_name = m.group(1) or m.group(2)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'err', 'ok', 'ctx', 'req', 'res', 'w', 'r', 'b'}
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
                    "message": f"Variable '{var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '{var_name}' or assign to '_'."
                })

    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
        # Find variable declarations: type name = ... or type name;
        for m in re.finditer(r'(?:int|char|float|double|long|short|unsigned|void|auto|bool|size_t|ssize_t)\s+\*?\s*(\w+)\s*(?:=|;|\))', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'i', 'j', 'k', 'n', 'ret', 'rc', 'err', 'len', 'size', 'argc', 'argv'}
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
                    "message": f"Variable '{var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '{var_name}' or cast to (void)."
                })

    elif ext == ".lua":
        # Find local variable declarations: local name = ...
        for m in re.finditer(r'local\s+(\w+)\s*=', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'self', 'err', 'ok', 'msg', 'k', 'v'}
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
                    "message": f"Variable '{var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '{var_name}' or prefix with _."
                })

    elif ext == ".php":
        # Find variable declarations: $name = ...
        for m in re.finditer(r'\$(\w+)\s*=', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'this', 'e', 'err', 'request', 'response', 'app', 'router'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            if var_name.isupper():
                continue
            usage_pattern = r'\$' + re.escape(var_name) + r'\b'
            all_occurrences = list(re.finditer(usage_pattern, clean_content))
            if len(all_occurrences) <= 1:
                items.append({
                    "file": rel_path,
                    "line": line_num,
                    "variable": '$' + var_name,
                    "severity": "info",
                    "message": f"Variable '${var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '${var_name}'."
                })

    elif ext == ".rs":
        # Rust: let bindings and let mut bindings
        # Find: let name = ... and let mut name = ...
        for m in re.finditer(r'\blet\s+(?:mut\s+)?(\w+)\s*(?::|=\s*)', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'err', 'ok', 'e', 'ctx', 'req', 'res', 'buf', 'cfg', 'result', 'input', 'output', 'ret'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            if var_name.isupper():
                continue
            # Skip common Rust patterns
            if var_name in {'self', 'Self', 'true', 'false', 'None', 'Some', 'Ok', 'Err'}:
                continue
            usage_pattern = r'\b' + re.escape(var_name) + r'\b'
            all_occurrences = list(re.finditer(usage_pattern, clean_content))
            if len(all_occurrences) <= 1:
                items.append({
                    "file": rel_path,
                    "line": line_num,
                    "variable": var_name,
                    "severity": "info",
                    "message": f"Variable '{var_name}' declared but never used",
                    "suggestion": f"Remove unused variable '{var_name}' or prefix with '_'."
                })

    elif ext in {".ex", ".exs"}:
        # Elixir: variable assignments (name starts with lowercase)
        for m in re.finditer(r'\b([a-z]\w*)\s*=\s*(?!=)', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'e', 'err', 'error', 'result', 'response', 'state', 'socket', 'conn', 'params', 'assigns'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            # Skip Elixir special forms and common patterns
            if var_name in {'def', 'defp', 'defmodule', 'do', 'end', 'true', 'false', 'nil', 'when', 'fn', 'use', 'import', 'alias', 'require'}:
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
                    "suggestion": f"Remove or prefix with '_'."
                })

    elif ext == ".rb":
        # Ruby: local variable assignments (name = value)
        for m in re.finditer(r'\b([a-z_]\w*)\s*=\s*', clean_content):
            var_name = m.group(1)
            line_num = clean_content[:m.start()].count('\n') + 1
            skip_names = {'_', 'e', 'err', 'error', 'result', 'response', 'request', 'params', 'session'}
            if var_name in skip_names or var_name.startswith('_'):
                continue
            if var_name in {'def', 'class', 'module', 'do', 'end', 'if', 'else', 'elsif', 'unless', 'true', 'false', 'nil', 'return', 'require', 'include', 'extend'}:
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
                    "suggestion": f"Remove or prefix with '_'."
                })

    return items[:100]  # Cap to avoid noise

def _collect_js_exports_imports(
    content: str, ext: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect JS/TS export and import declarations."""
    # Named exports: export const/function/class/abstract class/async function X
    for m in re.finditer(r'export\s+(?:abstract\s+)?(?:const|let|var|function|class|async\s+function)\s+(\w+)', content):
        exports[rel_path].append({
            "name": m.group(1),
            "type": "named_export",
            "line": content[:m.start()].count('\n') + 1
        })

    # TypeScript-specific exports: export interface/type/enum/declare
    if ext in {'.ts', '.tsx'}:
        for m in re.finditer(r'export\s+(?:interface|type|enum|declare\s+const|declare\s+function|declare\s+class)\s+(\w+)', content):
            exports[rel_path].append({
                "name": m.group(1),
                "type": "ts_export",
                "line": content[:m.start()].count('\n') + 1
            })

    # Default exports
    for m in re.finditer(r'export\s+default\s+(?:function\s+)?(\w+)', content):
        exports[rel_path].append({
            "name": m.group(1) or "default",
            "type": "default_export",
            "line": content[:m.start()].count('\n') + 1
        })

    # Re-exports: export { X } from ...  vs  local exports: export { X }
    # export { X } without 'from' is a local definition being made public API.
    # export { X } from './other' is a re-export from another module.
    # export type { X } from './other' is a TypeScript type-only re-export.
    # We distinguish these because local exports should not be flagged as unused
    # (they are intentionally public API), while re-exports from other modules
    # may be unnecessary if nothing imports them.
    #
    # Bug fix: a re-export ("export {X} from './y'" or "export type {X} from
    # './y'") consumes X from the source module './y' — it IS a usage of X as
    # far as the source file's own unused-exports check is concerned. Without
    # recording these names in `imports`, any symbol that is only ever
    # re-exported (never plain-imported) is incorrectly flagged as unused in
    # its defining file (found via real-codebase validation: ProductAccess in
    # google-auth-cache.ts, re-exported via `export type {...} from` in
    # google-auth.ts, was a false positive).
    for m in re.finditer(r'export\s+(?:type\s+)?\{([^}]+)\}(\s+from\s+[\'"\w./@-]+)?', content):
        has_from = m.group(2) is not None
        export_type = "re_export" if has_from else "local_export"
        names = [n.strip().split(' as ')[0].strip() for n in m.group(1).split(',')]
        for name in names:
            if name:
                exports[rel_path].append({
                    "name": name,
                    "type": export_type,
                    "line": content[:m.start()].count('\n') + 1
                })
                if has_from:
                    imports[rel_path].add(name)

    # Imports (including TypeScript type-only imports)
    for m in re.finditer(r'import\s+(?:type\s+)?(?:\{([^}]+)\}|\*\s+as\s+(\w+)|(\w+))\s+from', content):
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
        m = re.match(r'from\s+([\w.]+)\s+import\s+(.+)', stripped)
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


def _collect_py_same_file_usages(
    content: str, rel_path: str,
    usages: Dict[str, Set[str]]
):
    """Collect names that are referenced (used) within a Python file.

    This includes function calls, variable references, and attribute accesses.
    Used to determine if an export is used within its own file.
    """
    # Find all identifiers used in the file (excluding definitions)
    # Focus on names that appear as function calls or references
    used_names = set()

    # Find function/method calls: name( or obj.name(
    for m in re.finditer(r'\b([a-zA-Z_]\w*)\s*\(', content):
        used_names.add(m.group(1))

    # Find name references in expressions (variable access)
    # This is a broad match - we'll filter against exports later
    for m in re.finditer(r'\b([a-zA-Z_]\w*)\b', content):
        name = m.group(1)
        # Skip Python keywords
        if name in {'def', 'class', 'if', 'elif', 'else', 'for', 'while', 'return',
                    'import', 'from', 'as', 'with', 'try', 'except', 'finally',
                    'raise', 'yield', 'lambda', 'and', 'or', 'not', 'in', 'is',
                    'True', 'False', 'None', 'pass', 'break', 'continue', 'del',
                    'global', 'nonlocal', 'assert', 'async', 'await'}:
            continue
        used_names.add(name)

    usages[rel_path] = used_names

def _collect_go_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Go exports (capitalized functions/types/vars) and imports."""
    # Go: capitalized names are exported by convention
    for m in re.finditer(r'func\s+(?:\([^)]+\)\s+)?([A-Z]\w+)\s*\(', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        # Determine if this is a test/benchmark/example function
        export_type = "go_exported_func"
        if name.startswith('Test') or name.startswith('Benchmark') or name.startswith('Example') or name.startswith('Fuzz'):
            export_type = "go_test_func"
        exports[rel_path].append({
            "name": name,
            "type": export_type,
            "line": line_num
        })

    # Go: exported types (capitalized)
    for m in re.finditer(r'type\s+([A-Z]\w+)\s+(?:struct|interface)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "go_exported_type",
            "line": line_num
        })

    # Go: exported variables and constants (capitalized)
    for m in re.finditer(r'(?:var|const)\s+([A-Z]\w+)\s', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "go_exported_var",
            "line": line_num
        })

    # Go imports
    for m in re.finditer(r'import\s+(?:\([^)]+\)|"([^"]+)")', content, re.DOTALL):
        if m.group(1):
            imports[rel_path].add(m.group(1).split('/')[-1])
        else:
            # Multi-line import block
            block = m.group(0)
            for imp in re.finditer(r'"([^"]+)"', block):
                imports[rel_path].add(imp.group(1).split('/')[-1])

def _collect_rust_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Rust public items and use statements."""
    # Rust: pub fn, pub struct, pub enum, pub trait are exported
    for m in re.finditer(r'pub\s+(?:async\s+)?fn\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "rust_pub_fn",
            "line": line_num
        })

    for m in re.finditer(r'pub\s+(?:struct|enum|trait|type)\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "rust_pub_type",
            "line": line_num
        })

    # Rust use statements
    # Handle simple: use path::to::item;
    for m in re.finditer(r'use\s+([\w:]+)\s*;', content):
        name = m.group(1).split('::')[-1]
        imports[rel_path].add(name)

    # Handle grouped: use path::{item1, item2, module::item3};
    for m in re.finditer(r'use\s+[\w:]+\s*\{([^}]+)\}', content):
        group_content = m.group(1)
        for item_match in re.finditer(r'([\w:]+)', group_content):
            name = item_match.group(1).split('::')[-1]
            imports[rel_path].add(name)

    # Handle use with glob: use path::*;  (we can't resolve these, skip)
    # Handle use with self: use path::{self, item};  (add the last segment)

    # Rust mod declarations — these make child module items available
    for m in re.finditer(r'\bmod\s+(\w+)\s*;', content):
        imports[rel_path].add(m.group(1))

def _collect_c_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect C/C++ includes and function declarations."""
    # C/C++ #include
    for m in re.finditer(r'#include\s+[<"]([^>"]+)[>"]', content):
        name = m.group(1).split('/')[-1].replace('.h', '').replace('.hpp', '')
        imports[rel_path].add(name)

    # C/C++ function declarations (not definitions — skip body with {)
    for m in re.finditer(r'(?:static\s+|inline\s+|extern\s+)*'
                         r'(?:[\w:*&<>,\s]+?)\s+'
                         r'(\w+(?:::\w+)*)\s*\([^)]*\)\s*;', content):
        fn_name = m.group(1)
        skip = {'if', 'for', 'while', 'switch', 'return', 'catch', 'sizeof', 'typedef', 'class', 'struct'}
        if fn_name in skip:
            continue
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": fn_name,
            "type": "c_function_decl",
            "line": line_num
        })

def _collect_lua_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Lua module definitions and requires."""
    # Lua requires
    for m in re.finditer(r'(?:local\s+)?(?:\w+)\s*=\s*require\s*[("\']([^"\']+)["\')]', content):
        name = m.group(1).split('/')[-1]
        imports[rel_path].add(name)

    for m in re.finditer(r'require\s*[("\']([^"\']+)["\')]', content):
        name = m.group(1).split('/')[-1]
        imports[rel_path].add(name)

    # Lua module functions as exports
    for m in re.finditer(r'function\s+([\w:.]+)\s*\(', content):
        name = m.group(1).split(':')[-1].split('.')[-1]
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "lua_function",
            "line": line_num
        })

def _collect_php_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect PHP class/function definitions and use statements."""
    # PHP use statements
    for m in re.finditer(r'use\s+([\w\\]+)', content):
        name = m.group(1).split('\\')[-1]
        imports[rel_path].add(name)

    # PHP public functions
    for m in re.finditer(r'public\s+(?:static\s+)?function\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "php_public_method",
            "line": line_num
        })

    # PHP class definitions
    for m in re.finditer(r'(?:abstract\s+|final\s+)?class\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "php_class",
            "line": line_num
        })

def _collect_elixir_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Elixir function/macro definitions and alias/use/import references."""
    # Elixir alias/use/import
    for m in re.finditer(r'(?:alias|use|import)\s+([\w.]+)', content):
        name = m.group(1).split('.')[-1]
        imports[rel_path].add(name)

    # Elixir public functions (def, not defp)
    for m in re.finditer(r'\bdef\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "elixir_def",
            "line": line_num
        })

    # Elixir macros (defmacro)
    for m in re.finditer(r'\bdefmacro\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "elixir_macro",
            "line": line_num
        })


def _collect_ruby_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Ruby class/module definitions and require references."""
    # Ruby require
    for m in re.finditer(r'require\s+[\'"]([^\'"]+)[\'"]', content):
        name = m.group(1).split('/')[-1]
        imports[rel_path].add(name)

    # Ruby class definitions
    for m in re.finditer(r'class\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "ruby_class",
            "line": line_num
        })

    # Ruby module definitions
    for m in re.finditer(r'module\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "ruby_module",
            "line": line_num
        })

    # Ruby public method definitions
    for m in re.finditer(r'def\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "ruby_method",
            "line": line_num
        })


def _collect_nim_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Nim proc/func/type definitions and import references."""
    # Nim import
    for m in re.finditer(r'import\s+([\w/]+)', content):
        name = m.group(1).split('/')[-1]
        imports[rel_path].add(name)

    # Nim exported procs (marked with *)
    for m in re.finditer(r'proc\s+(\w+)\*', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "nim_proc",
            "line": line_num
        })

    # Nim exported types
    for m in re.finditer(r'type\s+(\w+)\*', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "nim_type",
            "line": line_num
        })


def _collect_java_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Java class definitions and import references."""
    # Java import
    for m in re.finditer(r'import\s+(?:static\s+)?([\w.]+)', content):
        name = m.group(1).split('.')[-1]
        imports[rel_path].add(name)

    # Java class definitions
    for m in re.finditer(r'(?:public\s+)?(?:abstract\s+|final\s+)?class\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "java_class",
            "line": line_num
        })

    # Java interface definitions
    for m in re.finditer(r'(?:public\s+)?interface\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "java_interface",
            "line": line_num
        })


def _collect_csharp_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect C# class definitions and using references."""
    # C# using
    for m in re.finditer(r'using\s+([\w.]+)', content):
        name = m.group(1).split('.')[-1]
        imports[rel_path].add(name)

    # C# class definitions
    for m in re.finditer(r'(?:public|internal)\s+(?:static\s+|sealed\s+|abstract\s+)?class\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "csharp_class",
            "line": line_num
        })


def _collect_swift_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Swift struct/class/func definitions and import references."""
    # Swift import
    for m in re.finditer(r'import\s+(\w+)', content):
        imports[rel_path].add(m.group(1))

    # Swift public functions
    for m in re.finditer(r'(?:public|open)\s+(?:static\s+)?func\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "swift_func",
            "line": line_num
        })

    # Swift public struct/class
    for m in re.finditer(r'(?:public|open)\s+(?:final\s+)?(?:struct|class)\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "swift_type",
            "line": line_num
        })


def _collect_scala_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Scala class/object definitions and import references."""
    # Scala import
    for m in re.finditer(r'import\s+([\w.]+)', content):
        name = m.group(1).split('.')[-1]
        imports[rel_path].add(name)

    # Scala class/object definitions
    for m in re.finditer(r'(?:class|object|trait|case\s+class)\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "scala_def",
            "line": line_num
        })


def _collect_dart_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Dart class/function definitions and import references."""
    # Dart import
    for m in re.finditer(r"import\s+['\"]([^'\"]+)['\"]", content):
        name = m.group(1).split('/')[-1].replace('.dart', '')
        imports[rel_path].add(name)

    # Dart class definitions
    for m in re.finditer(r'(?:class|abstract\s+class|enum|mixin)\s+(\w+)', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "dart_class",
            "line": line_num
        })


def _collect_shell_exports_imports(
    content: str, rel_path: str,
    exports: Dict[str, List[Dict]], imports: Dict[str, Set[str]]
):
    """Collect Shell function definitions and source references."""
    # Shell source/dot include
    for m in re.finditer(r'(?:source|\.)\s+([^\s;]+)', content):
        name = os.path.basename(m.group(1))
        imports[rel_path].add(name)

    # Shell function definitions
    for m in re.finditer(r'(?:function\s+)?(\w+)\s*\(\)\s*\{', content):
        name = m.group(1)
        line_num = content[:m.start()].count('\n') + 1
        exports[rel_path].append({
            "name": name,
            "type": "shell_function",
            "line": line_num
        })


def _collect_name_references(
    content: str, ext: str, rel_path: str,
    imports: Dict[str, Set[str]]
):
    """Collect name references (usages) in a file to improve unused export detection.

    For JS/TS/Python, import statements directly name what's imported, so the
    imports dict already captures usage.  For Go, Rust, C, Lua, PHP, Elixir,
    Ruby etc., the import mechanism brings in packages/modules and names are
    used via qualified access (pkg.Func) or direct calls.  This function
    collects those usage references so that _detect_unused_exports can check
    whether an exported name is actually used anywhere in the codebase.

    References are added to the ``imports`` dict (keyed by rel_path) so they
    are automatically included in ``all_imported_names`` during the unused-
    exports check.
    """
    # Strip comments to avoid false references from comment text
    clean = re.sub(r'//.*$', '', content, flags=re.MULTILINE)
    clean = re.sub(r'/\*[\s\S]{0,50000}?\*/', '', clean)
    # Strip string literals to avoid false refs from string content
    # For most languages, strip both double and single quoted strings
    # For Rust/Lua, single quotes are also used for char literals and lifetimes,
    # so we need to be careful — only strip character literals ('x', '\n'), not lifetimes
    # IMPORTANT: Use re.DOTALL so that \\. matches backslash + newline (Rust multi-line strings)
    clean = re.sub(r'"(?:[^"\\]|\\.)*"', '""', clean, flags=re.DOTALL)
    if ext == ".rs":
        # Rust: only strip char literals ('x', '\n', etc.), not lifetime annotations ('a)
        clean = re.sub(r"'(?:[^'\\]|\\.){1,2}'", "''", clean, flags=re.DOTALL)
    elif ext == ".lua":
        # Lua: single-quoted strings are common
        clean = re.sub(r"'(?:[^'\\]|\\.)*'", "''", clean, flags=re.DOTALL)
    else:
        # For other languages, strip single-quoted strings
        clean = re.sub(r"'(?:[^'\\]|\\.)*'", "''", clean, flags=re.DOTALL)

    if ext == ".go":
        # Go: pkg.FuncName(), FuncName(), StructName{}, &StructName{}
        # Uppercase names are exported in Go
        for m in re.finditer(r'\.([A-Z]\w+)\s*[\({]', clean):
            imports[rel_path].add(m.group(1))
        # Standalone exported function calls (not definitions)
        # Match: FuncName( but NOT: func FuncName(
        for m in re.finditer(r'(?<!func\s)(?<![.\w])([A-Z]\w+)\s*\(', clean):
            name = m.group(1)
            _go_kw = {'func', 'type', 'var', 'const', 'import', 'package',
                      'return', 'defer', 'go', 'select', 'switch', 'if',
                      'for', 'range', 'map', 'chan', 'interface', 'struct',
                      'true', 'false', 'nil', 'error', 'string', 'bool',
                      'int', 'int64', 'float64', 'byte', 'rune', 'make',
                      'new', 'len', 'cap', 'append', 'copy', 'delete',
                      'close', 'panic', 'recover', 'print', 'println'}
            if name not in _go_kw:
                imports[rel_path].add(name)
        # Struct/interface instantiation: Name{ or &Name{
        for m in re.finditer(r'(?:&|)\b([A-Z]\w+)\s*\{', clean):
            name = m.group(1)
            if name not in {'struct', 'interface', 'map', 'func'}:
                imports[rel_path].add(name)
        # Type assertion / conversion: .(TypeName), TypeName(expr)
        for m in re.finditer(r'\.\(([A-Z]\w+)\)', clean):
            imports[rel_path].add(m.group(1))
        # Type references in declarations, parameters, return types:
        # var x TypeName, func foo() TypeName, x TypeName{, Field TypeName
        # Catch all uppercase identifiers used as types/references (not just in call position)
        for m in re.finditer(r'\b([A-Z]\w{2,})\b', clean):
            name = m.group(1)
            _go_type_kw = {'Append', 'Copy', 'Delete', 'Close', 'Panic',
                           'Recover', 'Print', 'Println', 'Complex', 'Real',
                           'Imag', 'Make', 'New', 'Len', 'Cap', 'Errorf'}
            if name not in _go_type_kw:
                imports[rel_path].add(name)

    elif ext == ".rs":
        # Rust: function calls, struct instantiation, enum variants
        # Function calls: name(
        _rs_kw = {'fn', 'pub', 'let', 'if', 'while', 'for', 'match', 'return',
                  'use', 'mod', 'struct', 'enum', 'impl', 'trait', 'type',
                  'where', 'unsafe', 'async', 'await', 'self', 'Self', 'super',
                  'crate', 'true', 'false', 'as', 'break', 'continue', 'else',
                  'loop', 'move', 'mut', 'ref', 'static', 'const', 'extern',
                  'dyn', 'ref', 'in', 'ref'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _rs_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Qualified access: module::name or Type::method
        for m in re.finditer(r'(\w+)::(\w+)', clean):
            name = m.group(2)
            if name not in _rs_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Struct instantiation: Name { field: value, ... }
        for m in re.finditer(r'(?:^|[^\w.])([A-Z]\w+)\s*\{', clean):
            name = m.group(1)
            if name not in {'Some', 'None', 'Ok', 'Err', 'Self'}:
                imports[rel_path].add(name)

    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
        # C/C++: function calls, type usage
        _c_kw = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'typeof',
                 'catch', 'class', 'struct', 'enum', 'union', 'namespace',
                 'template', 'typename', 'new', 'delete', 'void', 'int',
                 'char', 'float', 'double', 'long', 'short', 'unsigned',
                 'signed', 'const', 'static', 'extern', 'inline', 'virtual',
                 'override', 'final', 'public', 'private', 'protected',
                 'true', 'false', 'nullptr', 'NULL', 'auto', 'register',
                 'volatile', 'typedef', 'using'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _c_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Qualified names: Class::method
        for m in re.finditer(r'(\w+)::(\w+)', clean):
            name = m.group(2)
            if name not in _c_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".lua":
        # Lua: function calls, module.func(), module:method()
        _lua_kw = {'function', 'local', 'if', 'then', 'else', 'elseif',
                   'for', 'while', 'do', 'return', 'end', 'repeat', 'until',
                   'not', 'and', 'or', 'nil', 'true', 'false', 'in',
                   'break', 'goto'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _lua_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Method calls: module.func( or obj:method(
        for m in re.finditer(r'[.:](\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _lua_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".php":
        # PHP: function calls, class usage, method calls
        _php_kw = {'if', 'else', 'elseif', 'for', 'while', 'switch', 'return',
                   'function', 'class', 'new', 'public', 'private', 'protected',
                   'static', 'abstract', 'final', 'try', 'catch', 'throw',
                   'foreach', 'isset', 'unset', 'echo', 'print', 'list',
                   'array', 'namespace', 'use', 'require', 'include',
                   'require_once', 'include_once', 'true', 'false', 'null',
                   'as', 'extends', 'implements', 'interface', 'trait',
                   'const', 'var', 'case', 'break', 'continue', 'default',
                   'do', 'global'}
        # Function calls (not preceded by $)
        for m in re.finditer(r'(?<!\$)\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _php_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Class instantiation: new ClassName
        for m in re.finditer(r'\bnew\s+(\w+)', clean):
            imports[rel_path].add(m.group(1))
        # Method calls: ->method( and ::method(
        for m in re.finditer(r'(?:->|::)(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _php_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext in {".ex", ".exs"}:
        # Elixir: function calls, Module.func()
        _ex_kw = {'def', 'defp', 'defmodule', 'defmacro', 'defmacrop',
                  'do', 'end', 'if', 'else', 'cond', 'case', 'receive',
                  'after', 'try', 'catch', 'rescue', 'raise', 'throw',
                  'for', 'unless', 'fn', 'when', 'use', 'import', 'alias',
                  'require', 'quote', 'unquote', 'nil', 'true', 'false',
                  'with', 'and', 'or', 'not', 'in', 'as'}
        for m in re.finditer(r'\b(\w+)\s*(?:\(|\[)', clean):
            name = m.group(1)
            if name not in _ex_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Remote function calls: Module.func(
        for m in re.finditer(r'\.(\w+)\s*(?:\(|\[)', clean):
            name = m.group(1)
            if name not in _ex_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".rb":
        # Ruby: method calls, Class.new, Module.method
        _rb_kw = {'def', 'class', 'module', 'if', 'else', 'elsif', 'unless',
                  'while', 'until', 'for', 'do', 'begin', 'rescue', 'ensure',
                  'raise', 'return', 'yield', 'nil', 'true', 'false',
                  'require', 'include', 'extend', 'attr', 'attr_accessor',
                  'attr_reader', 'attr_writer', 'new', 'end', 'then',
                  'and', 'or', 'not', 'in', 'case', 'when', 'break',
                  'next', 'redo', 'retry', 'super', 'self', 'defined?',
                  'lambda', 'proc', 'puts', 'print', 'p', 'pp'}
        # Method calls: name( or name (
        for m in re.finditer(r'(?:^|[\s.])([a-z_]\w*)\s*\(', clean):
            name = m.group(1)
            if name not in _rb_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Class instantiation: ClassName.new
        for m in re.finditer(r'\b([A-Z]\w*)\s*\.new\b', clean):
            imports[rel_path].add(m.group(1))
        # Class constant/method: ClassName.method
        for m in re.finditer(r'\b([A-Z]\w*)\s*\.\s*(\w+)', clean):
            imports[rel_path].add(m.group(1))
            imports[rel_path].add(m.group(2))

    elif ext == ".java":
        # Java: method calls, Class references
        _java_kw = {'if', 'else', 'for', 'while', 'switch', 'return', 'new',
                    'class', 'interface', 'extends', 'implements', 'import',
                    'package', 'public', 'private', 'protected', 'static',
                    'final', 'abstract', 'void', 'int', 'long', 'double',
                    'float', 'boolean', 'char', 'byte', 'short', 'true',
                    'false', 'null', 'this', 'super', 'try', 'catch',
                    'throw', 'throws', 'finally', 'synchronized'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _java_kw and len(name) > 1:
                imports[rel_path].add(name)
        # Qualified: Class.method or Class.field
        for m in re.finditer(r'\.(\w+)\s*[\(]', clean):
            name = m.group(1)
            if name not in _java_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".cs":
        # C#: method calls, type references
        _cs_kw = {'if', 'else', 'for', 'while', 'switch', 'return', 'new',
                  'class', 'struct', 'interface', 'enum', 'using', 'namespace',
                  'public', 'private', 'protected', 'internal', 'static',
                  'void', 'int', 'long', 'double', 'float', 'bool', 'string',
                  'true', 'false', 'null', 'this', 'base', 'try', 'catch',
                  'throw', 'finally', 'async', 'await', 'var', 'const',
                  'override', 'virtual', 'abstract', 'sealed'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _cs_kw and len(name) > 1:
                imports[rel_path].add(name)
        for m in re.finditer(r'\.(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _cs_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".swift":
        # Swift: function calls, type references
        _swift_kw = {'if', 'else', 'for', 'while', 'switch', 'return', 'func',
                     'class', 'struct', 'enum', 'protocol', 'import', 'let',
                     'var', 'guard', 'typealias', 'public', 'private', 'fileprivate',
                     'internal', 'open', 'static', 'override', 'true', 'false',
                     'nil', 'self', 'Self', 'super', 'init', 'deinit', 'try',
                     'catch', 'throw', 'throws', 'async', 'await'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _swift_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext in {".scala", ".sc"}:
        _scala_kw = {'if', 'else', 'for', 'while', 'match', 'return', 'def',
                     'class', 'object', 'trait', 'import', 'val', 'var',
                     'new', 'override', 'sealed', 'abstract', 'case',
                     'true', 'false', 'null', 'this', 'super', 'try',
                     'catch', 'throw', 'finally', 'yield', 'lazy', 'implicit'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _scala_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext == ".dart":
        _dart_kw = {'if', 'else', 'for', 'while', 'switch', 'return', 'class',
                    'import', 'void', 'int', 'double', 'bool', 'String',
                    'var', 'final', 'const', 'true', 'false', 'null',
                    'this', 'super', 'new', 'try', 'catch', 'throw',
                    'async', 'await', 'static', 'override', 'abstract'}
        for m in re.finditer(r'\b(\w+)\s*\(', clean):
            name = m.group(1)
            if name not in _dart_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext in {".nim", ".nims"}:
        _nim_kw = {'if', 'else', 'elif', 'for', 'while', 'case', 'return',
                   'proc', 'func', 'method', 'template', 'macro', 'import',
                   'var', 'let', 'const', 'type', 'true', 'false', 'nil',
                   'block', 'break', 'continue', 'when', 'discard'}
        for m in re.finditer(r'\b(\w+)\s*[\(\[]', clean):
            name = m.group(1)
            if name not in _nim_kw and len(name) > 1:
                imports[rel_path].add(name)

    elif ext in {".sh", ".bash", ".zsh"}:
        # Shell: function calls (command names)
        _sh_kw = {'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'do',
                  'done', 'case', 'esac', 'return', 'exit', 'function',
                  'local', 'export', 'readonly', 'declare', 'typeset',
                  'true', 'false', 'echo', 'printf', 'read', 'set',
                  'shift', 'test', 'cd', 'source'}
        for m in re.finditer(r'(?:^|;|&&|\|\|)\s*([a-zA-Z_]\w*)\s', clean):
            name = m.group(1)
            if name not in _sh_kw and len(name) > 1:
                imports[rel_path].add(name)


def _detect_unused_exports(
    all_exports: Dict[str, List[Dict]],
    all_imports: Dict[str, Set[str]],
    workspace: str,
    same_file_usages: Dict[str, Set[str]] = None
) -> List[Dict]:
    """Detect exports that are never imported anywhere."""
    # Build set of all imported names
    all_imported_names: Set[str] = set()
    for names in all_imports.values():
        all_imported_names.update(names)

    # Check if this looks like a library (package with __init__.py re-exports)
    # For libraries, exports are the public API and used by downstream consumers
    _is_library = _detect_library_package(workspace)

    unused = []
    for file_path, exports in all_exports.items():
        # Skip test files and index files (they may be entry points)
        if any(x in file_path for x in ['.test.', '.spec.', '__tests__']):
            continue
        # Skip docs/examples directories
        if any(x in file_path for x in ['/docs_src/', '/doc_src/', '/examples/', '/example/',
                                          '/documentation/', '/docs/examples/', '/snippets/']):
            continue
        if file_path.endswith('index.js') or file_path.endswith('index.ts'):
            continue
        # For Python packages, skip __init__.py — these are re-export entry points
        if file_path.endswith('__init__.py') or file_path.endswith('__init__.pyi'):
            continue
        # Go: skip test files entirely — functions in _test.go are called by the test runner
        if file_path.endswith('_test.go'):
            continue
        # Go: skip magefile.go — mage targets are called by the build tool
        if file_path.endswith('magefile.go'):
            continue

        # ─── Config/settings file heuristic ───
        # Functions in config/settings files are typically called at runtime
        # by the application framework, not via explicit imports. Skip them
        # from unused_exports detection entirely.
        _config_patterns = ['/config/', '/settings', '/conf/', 'config/', 'settings.py', 'conf/']
        _is_config_file = any(p in file_path for p in _config_patterns)
        if _is_config_file:
            continue

        # ─── Web handler / routes heuristic ───
        # Functions in routes/views/api files are typically called by the web
        # framework at runtime. Skip them from unused_exports detection entirely.
        _route_patterns = ['/routes', '/views', '/api/', '/endpoints/', '/controllers/',
                           'routes.py', 'views.py', 'api.py', 'controllers.py']
        _is_route_file = any(p in file_path for p in _route_patterns)
        if _is_route_file:
            continue

        for export in exports:
            name = export["name"]
            export_type = export.get("type", "")

            # Skip common entry-point exports
            if name in {'default', 'handler', 'app', 'server', 'router', 'main', 'configure', 'setup'}:
                continue

            # ─── JS/TS local export heuristic ───
            # export { X } without 'from' exports a locally-defined symbol as
            # public API. These are intentionally exported for external consumers
            # and should not be flagged as unused just because no file in the
            # current workspace imports them.
            if export_type == "local_export":
                continue

            # ─── Language-specific entry-point / framework skipping ───
            # Go: Test/Benchmark/Example/Fuzz functions are called by the test runner
            if export_type == "go_test_func":
                continue
            # Go: main function is the entry point
            if export_type.startswith("go_") and name == "Main":
                continue
            # Go: init functions are auto-called by the runtime
            if export_type.startswith("go_") and name == "Init":
                continue
            # Rust: main function is the entry point
            if export_type.startswith("rust_") and name == "main":
                continue
            # Rust: new is a conventional constructor, almost always used
            if export_type.startswith("rust_") and name == "new":
                continue
            # C/C++: main/winmain/dllmain are entry points
            if export_type.startswith("c_") and name in {'main', 'WinMain', 'DllMain', 'wmain', '_tmain'}:
                continue
            # Ruby: initialize is the constructor
            if export_type == "ruby_method" and name in {'initialize', 'to_s', 'to_str', 'inspect', 'hash', 'eql?', 'equal?', 'respond_to_missing?'}:
                continue
            # Elixir: init/1 is a callback
            if export_type == "elixir_def" and name in {'init', 'handle_call', 'handle_cast', 'handle_info', 'terminate', 'code_change', 'child_spec'}:
                continue
            # PHP: __construct, __destruct etc are magic methods
            if export_type == "php_public_method" and name.startswith('__'):
                continue

            # Skip names that are clearly public API (capitalized classes, common patterns)
            if _is_library and name[0:1].isupper():
                # Capitalized names in library code are likely public API
                continue

            # ─── Config/settings file heuristic ───
            # Functions in config/settings files are typically called at runtime
            # by the application framework, not via explicit imports.
            _config_patterns = ['/config/', '/settings', '/conf/', 'config/', 'settings.py', 'conf/']
            _is_config_file = any(p in file_path for p in _config_patterns)

            # ─── Web handler / routes heuristic ───
            # Functions in routes/views/api files are typically called by the web
            # framework at runtime (e.g., Flask routes, Django views, FastAPI endpoints).
            _route_patterns = ['/routes', '/views', '/api/', '/endpoints/', '/controllers/',
                               'routes.py', 'views.py', 'api.py', 'controllers.py']
            _is_route_file = any(p in file_path for p in _route_patterns)

            # Check if function signature suggests a web handler (has 'request' parameter)
            _is_handler = export.get("is_handler", False)

            if name not in all_imported_names:
                # Check if the export is used within its own file
                _used_in_same_file = (same_file_usages or {}).get(file_path, set())
                if name in _used_in_same_file:
                    continue  # Used within the same file, not dead
                # Determine severity with heuristic adjustments
                if _is_config_file or _is_route_file or _is_handler:
                    # Config and route functions are likely runtime-called — reduce severity
                    severity = "info"
                elif _is_library:
                    severity = "info"
                else:
                    severity = "warning"

                # Determine if this is "possibly used" rather than definitively dead
                possibly_used = _is_config_file or _is_route_file or _is_handler

                unused.append({
                    "file": file_path,
                    "line": export["line"],
                    "name": name,
                    "type": export["type"],
                    "severity": severity,
                    "source": "library_api" if _is_library else "core",
                    "message": f"Export '{name}' is never imported by any file" +
                               (" (library public API — may be used by consumers)" if _is_library else "") +
                               (" — possibly used at runtime" if possibly_used else ""),
                    "suggestion": f"Remove unused export '{name}' or add import where needed." +
                                  (" Consider adding __all__ if this is intentional public API." if _is_library else "")
                })

    return unused[:200]

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
        # exported symbols (JS/TS export), components (React/PascalCase classes),
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
            # Skip exported symbols (JS/TS) — they're part of the public API
            if node.get("exported", False):
                continue
            # Skip components (React/PascalCase classes) — consumed externally
            if node.get("component", False):
                continue
            # Skip test fixtures and example files
            # v6.4: Expanded to catch examples/, e2e/, __tests__/, stories/
            _test_example_patterns = [
                '/test/', '/tests/', '/__test', '/__tests__/',
                '/example/', '/examples/', '/e2e/',
                '/fixture/', '/fixtures/', '/mock/', '/mocks/',
                '/stories/', '/storybook/',
                '/docs_src/', '/doc_src/', '/docs/examples/',
                '/documentation/', '/snippets/',
            ]
            if any(p in file_path for p in _test_example_patterns):
                continue

            # Skip config/settings and routes/views files — functions in these
            # files are typically called at runtime by the framework
            _config_route_patterns = [
                '/config/', '/settings', '/conf/', 'config/', 'settings.py', 'conf/',
                '/routes', '/views', '/api/', '/endpoints/', '/controllers/',
                'routes.py', 'views.py', 'api.py', 'controllers.py',
            ]
            if any(p in file_path for p in _config_route_patterns):
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


def _detect_library_package(workspace: str) -> bool:
    """Detect if this workspace is a library package (vs an application).

    A library package's exports are its public API, meant for downstream consumers.
    Flagging them as "unused" is a false positive since they're used outside the repo.

    Indicators:
    - Python: Has a proper package structure with __init__.py + re-exports
    - JS/TS: Has "main"/"module"/"exports" in package.json but no "scripts.start"
    - Has pyproject.toml with library classifiers or no entry-point console_scripts
    """
    # Check for Python library indicators
    init_path = os.path.join(workspace, '__init__.py')
    src_init = os.path.join(workspace, 'src', '__init__.py')
    pkg_init = None
    # Look for top-level package __init__.py (not in tests/)
    for item in os.listdir(workspace):
        item_path = os.path.join(workspace, item)
        if os.path.isdir(item_path) and not item.startswith('.') and item not in ('tests', 'test', 'docs', 'docs_src', 'scripts'):
            candidate = os.path.join(item_path, '__init__.py')
            if os.path.isfile(candidate):
                pkg_init = candidate
                break

    if pkg_init:
        # Check if the __init__.py has re-exports (from .xxx import yyy)
        try:
            with open(pkg_init, 'r', encoding='utf-8', errors='ignore') as f:
                init_content = f.read()
            # If __init__.py has re-exports, it's a library
            if re.search(r'from\s+\.+\w+\s+import', init_content):
                return True
            # If __init__.py has __all__, it's definitely a library
            if '__all__' in init_content:
                return True
        except IOError:
            pass

    # Check pyproject.toml for library indicators
    pyproject_path = os.path.join(workspace, 'pyproject.toml')
    if os.path.isfile(pyproject_path):
        try:
            with open(pyproject_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # If it has [project.scripts], it's more likely a CLI app than a library
            if '[project.scripts]' in content:
                return False
            # If it has library classifiers
            if 'Library' in content and 'PyPI' in content:
                return True
        except IOError:
            pass

    # Check package.json for library indicators
    pkg_json_path = os.path.join(workspace, 'package.json')
    if os.path.isfile(pkg_json_path):
        try:
            with open(pkg_json_path, 'r', encoding='utf-8', errors='ignore') as f:
                pkg = json.load(f)
            # Has "main" or "module" or "exports" but no "scripts.start" → likely a library
            has_main = bool(pkg.get('main') or pkg.get('module') or pkg.get('exports'))
            has_start_script = 'start' in pkg.get('scripts', {})
            if has_main and not has_start_script:
                return True
        except (json.JSONDecodeError, IOError):
            pass

    return False


def _detect_zombie_css(workspace: str) -> List[Dict]:
    """Detect CSS classes defined but never used in HTML/JS/TSX.

    A CSS class is considered "zombie" only if:
    1. It has ref_count == 0 (not referenced in any JS/TSX code)
    2. It is NOT used in any HTML files (classes used in HTML are not zombie)
    3. It has an actual CSS definition (skip classes with no known CSS source)
    4. It is not a Tailwind utility class or a JS operator/expression
    """
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

    for cls in frontend.get("classes", []):
        name = cls["name"]
        if cls["status"] != "dead":
            continue

        # Skip Tailwind utility classes — they're framework-defined, not user-defined
        if has_tailwind_check and is_tailwind_class(name):
            continue
        # Skip names that look like JS operators/expressions (e.g., '!==', '===', etc.)
        if not re.match(r'^[a-zA-Z_]', name):
            continue
        # Skip classes used in HTML — they're not zombie CSS even without JS usage
        if cls.get("html"):
            continue
        # Skip classes with no CSS definition — they may be framework-generated
        # or defined in a way that the scanner couldn't track
        css_entries = cls.get("css", [])
        if not css_entries:
            # If no CSS definition exists and no JS usage, this is likely a
            # dynamically-applied or framework-generated class, not a zombie CSS rule
            continue

        # Use the first CSS definition's path and line
        first_css = css_entries[0] if css_entries else {}
        zombie.append({
            "file": first_css.get("path", "unknown"),
            "line": first_css.get("line", 0),
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
