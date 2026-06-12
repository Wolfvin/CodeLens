"""
Complexity Engine for CodeLens — v3
Computes cyclomatic and cognitive complexity per function with actual numbers.
Different from smell_engine.py which detects patterns qualitatively — this engine
produces precise numerical complexity metrics per function.

Metrics per function:
1. Cyclomatic Complexity (CC) — decision points + 1
   - Counts: if, elif, else, for, while, case, &&, ||, try/except, ternary, ??
   - Thresholds: 1-5 simple, 6-10 moderate, 11-20 complex, 21-50 very complex, 50+ untamable

2. Cognitive Complexity — per SonarSource spec
   - +1 for each break in linear flow (if, elif, else, for, while, switch, catch)
   - +1 nesting increment for each nested structure
   - No increment for else/elif after if (already counted), but nesting still applies
   - No increment for function/method definitions (just structure)

3. Lines of Code (LOC) for the function body
4. Parameter count
5. Maximum nesting depth

Languages: JS/TS/JSX/TSX, Python, Rust
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".go",
    ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp",
    ".nim", ".nims",
}

# Cyclomatic complexity thresholds
CC_SIMPLE = 5
CC_MODERATE = 10
CC_COMPLEX = 20
CC_VERY_COMPLEX = 50

# Cognitive complexity thresholds (same breakpoints but different scale)
COG_SIMPLE = 5
COG_MODERATE = 10
COG_COMPLEX = 20
COG_VERY_COMPLEX = 30

# LOC thresholds for refactoring suggestions
LOC_MODERATE = 50
LOC_HIGH = 100

# Parameter count thresholds
PARAM_MODERATE = 4
PARAM_HIGH = 7

# Nesting depth thresholds
NESTING_MODERATE = 4
NESTING_HIGH = 6


# ─── Main Entry Point ──────────────────────────────────────────

def compute_complexity(
    workspace: str,
    function_name: Optional[str] = None,
    file_filter: Optional[str] = None,
    threshold: Optional[int] = None,
    config: Optional[Dict] = None,
    sort_by: Optional[str] = None,
    limit: Optional[int] = None,
    max_files: int = 5000
) -> Dict[str, Any]:
    """
    Compute cyclomatic and cognitive complexity for all functions in the workspace.

    Args:
        workspace: Absolute path to workspace root
        function_name: Optional specific function to analyze
        file_filter: Optional file path glob filter
        threshold: Optional minimum cyclomatic complexity to report
        config: CodeLens configuration dict
        sort_by: Sort results by 'complexity' (cyclomatic desc), 'cognitive', 'loc', or None (file order)
        limit: Max number of functions to return in the 'functions' list

    Returns:
        Dict with status, stats, function list, hotspots, and recommendations
    """
    workspace = os.path.abspath(workspace)
    min_cc = threshold or 0

    function_results: List[Dict] = []
    files_scanned = 0
    MAX_FUNCTIONS = 8000  # Cap total functions to analyze

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if files_scanned >= max_files:
                break

            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            # Skip minified and declaration files
            if any(filename.endswith(ig) for ig in ('.min.js', '.min.css', '.map', '.d.ts')):
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip large files
            try:
                if os.path.getsize(file_path) > 500 * 1024:
                    continue
            except OSError:
                continue

            # Apply file filter
            if file_filter and file_filter not in rel_path:
                continue

            # Early exit if too many functions already
            if len(function_results) >= MAX_FUNCTIONS:
                break

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1
            lines = content.split('\n')

            # Extract functions from the file
            functions = _extract_functions(content, ext, rel_path)

            for fn_info in functions:
                # If searching for a specific function, skip non-matching
                if function_name and fn_info["name"] != function_name:
                    continue

                # Extract the function body
                fn_body, fn_end = _get_function_body_and_end(lines, fn_info, ext)

                if not fn_body.strip():
                    continue

                # Compute metrics
                cyclomatic = _compute_cyclomatic(fn_body, ext)
                cognitive = _compute_cognitive(fn_body, ext)
                loc = _count_loc(fn_body)
                params = fn_info.get("param_count", _count_params(fn_info.get("params_str", ""), ext))
                max_nesting = _compute_max_nesting(fn_body, ext)

                # Skip if below threshold
                if cyclomatic < min_cc:
                    continue

                # Determine complexity level
                complexity_level = _classify_complexity(cyclomatic)

                # Generate refactoring suggestion
                suggestion = _generate_refactoring_suggestion(
                    cyclomatic, cognitive, loc, params, max_nesting, fn_info["name"]
                )

                function_results.append({
                    "name": fn_info["name"],
                    "file": rel_path,
                    "line": fn_info["line"],
                    "cyclomatic": cyclomatic,
                    "cognitive": cognitive,
                    "loc": loc,
                    "params": params,
                    "max_nesting": max_nesting,
                    "complexity_level": complexity_level,
                    "refactoring_suggestion": suggestion,
                })

    # If searching for a specific function, return early
    if function_name:
        if function_results:
            return {
                "status": "ok",
                "workspace": workspace,
                "function": function_name,
                "result": function_results[0],
            }
        else:
            return {
                "status": "not_found",
                "workspace": workspace,
                "function": function_name,
                "message": f"Function '{function_name}' not found or below threshold.",
            }

    # ─── Aggregate Stats ──────────────────────────────────
    total_functions = len(function_results)
    avg_cyclomatic = 0.0
    avg_cognitive = 0.0
    if total_functions > 0:
        avg_cyclomatic = round(
            sum(f["cyclomatic"] for f in function_results) / total_functions, 2
        )
        avg_cognitive = round(
            sum(f["cognitive"] for f in function_results) / total_functions, 2
        )

    high_complexity = sum(1 for f in function_results if f["cyclomatic"] > CC_COMPLEX)

    by_level = defaultdict(int)
    for f in function_results:
        by_level[f["complexity_level"]] += 1

    # ─── Sort results if requested ────────────────────────
    if sort_by == "complexity":
        function_results.sort(key=lambda x: (-x["cyclomatic"], -x["cognitive"]))
    elif sort_by == "cognitive":
        function_results.sort(key=lambda x: (-x["cognitive"], -x["cyclomatic"]))
    elif sort_by == "loc":
        function_results.sort(key=lambda x: -x["loc"])

    # ─── Apply limit ─────────────────────────────────────
    displayed_functions = function_results[:limit] if limit else function_results

    # ─── Hotspots (top 10 by cyclomatic, then cognitive) ──
    hotspots = sorted(
        function_results,
        key=lambda x: (-x["cyclomatic"], -x["cognitive"], -x["loc"])
    )[:10]

    # ─── Recommendations ──────────────────────────────────
    recommendations = _generate_recommendations(
        function_results, avg_cyclomatic, avg_cognitive, high_complexity, dict(by_level)
    )

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_functions": total_functions,
            "files_scanned": files_scanned,
            "avg_cyclomatic": avg_cyclomatic,
            "avg_cognitive": avg_cognitive,
            "high_complexity": high_complexity,
            "by_complexity_level": dict(by_level),
        },
        "functions": displayed_functions,
        "hotspots": hotspots,
        "recommendations": recommendations,
    }


# ─── Function Extraction ───────────────────────────────────────

def _extract_functions(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Extract function definitions with their locations and metadata."""
    functions = []
    lines = content.split('\n')

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        functions = _extract_js_functions(lines, content, ext)
    elif ext == ".py":
        functions = _extract_py_functions(lines, content)
    elif ext == ".rs":
        functions = _extract_rs_functions(lines, content)
    elif ext == ".go":
        functions = _extract_go_functions(lines, content)
    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
        functions = _extract_c_cpp_functions(lines, content, ext)

    return functions


def _extract_js_functions(lines: List[str], content: str, ext: str) -> List[Dict]:
    """Extract JS/TS function definitions."""
    functions = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        # function declarations: function name() or async function name()
        m = re.match(
            r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
            stripped
        )
        if m:
            functions.append({
                "name": m.group(1),
                "line": i + 1,
                "type": "function",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })
            continue

        # Arrow functions: const name = () => or const name = async () =>
        m = re.match(
            r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*(?::\s*[^=]+?)?\s*=>',
            stripped
        )
        if m:
            functions.append({
                "name": m.group(1),
                "line": i + 1,
                "type": "arrow",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })
            continue

        # Method definitions in classes: name() { or async name() {
        m = re.match(
            r'(?:(?:public|private|protected|static|async|abstract|override)\s+)*(\w+)\s*\(([^)]*)\)\s*(?::\s*[^{]+?)?\s*\{',
            stripped
        )
        if m and m.group(1) not in {'if', 'for', 'while', 'switch', 'catch', 'class', 'constructor'}:
            # Check it's inside a class
            context = content[:sum(len(lines[j]) + 1 for j in range(i))]
            if re.search(r'class\s+\w+', context[max(0, len(context) - 2000):]):
                functions.append({
                    "name": m.group(1),
                    "line": i + 1,
                    "type": "method",
                    "params_str": m.group(2),
                    "start_col": len(line) - len(line.lstrip()),
                })

    return functions


def _extract_py_functions(lines: List[str], content: str) -> List[Dict]:
    """Extract Python function definitions."""
    functions = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        m = re.match(r'(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)', stripped)
        if m:
            functions.append({
                "name": m.group(1),
                "line": i + 1,
                "type": "def",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })

    return functions


def _extract_rs_functions(lines: List[str], content: str) -> List[Dict]:
    """Extract Rust function definitions."""
    functions = []

    for i, line in enumerate(lines):
        m = re.match(
            r'\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*(?:<[^>]+>)?\s*\(([^)]*)\)',
            line
        )
        if m:
            functions.append({
                "name": m.group(1),
                "line": i + 1,
                "type": "fn",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })

    return functions


def _extract_go_functions(lines: List[str], content: str) -> List[Dict]:
    """Extract Go function definitions."""
    functions = []

    for i, line in enumerate(lines):
        # Match: func Name(params) or func (receiver) Name(params)
        m = re.match(
            r'\s*func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(([^)]*)\)',
            line
        )
        if m:
            fn_name = m.group(1)
            # Skip init() and main() as they are entry points
            functions.append({
                "name": fn_name,
                "line": i + 1,
                "type": "func",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })

    return functions


def _extract_c_cpp_functions(lines: List[str], content: str, ext: str) -> List[Dict]:
    """Extract C/C++ function definitions.

    Handles both single-line and multi-line signatures where the opening
    brace may be on the next line (common in C projects like nginx).
    """
    functions = []

    for i, line in enumerate(lines):
        # C/C++ function definition pattern:
        # type name(params) {  or  type Class::name(params) {
        # Also handles: type name(params)\n{  (brace on next line)
        # Also handles: type calling_conv\nname(params)\n{ (like int ngx_cdecl\nmain())
        m = re.match(
            r'\s*(?:static\s+|inline\s+|extern\s+|virtual\s+|constexpr\s+)*'
            r'(?:[\w:*&<>,\s]+?)\s+'
            r'(\w+(?:::\w+)*)\s*\(([^)]*)\)\s*(?:const\s*)?(?:->\s*[\w:*&<>,\s]+\s*)?\{',
            line
        )
        if m:
            fn_name = m.group(1)
            skip_names = {'if', 'for', 'while', 'switch', 'catch', 'return',
                         'class', 'struct', 'enum', 'union', 'namespace', 'typedef',
                         'using', 'template', 'include', 'define', 'ifdef', 'endif'}
            if fn_name in skip_names:
                continue
            functions.append({
                "name": fn_name,
                "line": i + 1,
                "type": "function",
                "params_str": m.group(2),
                "start_col": len(line) - len(line.lstrip()),
            })
            continue

        # Try multi-line pattern: function signature on this line, brace on next line
        # e.g., "ngx_int_t ngx_get_options(int argc, char *const *argv)"
        #        "{"
        m = re.match(
            r'\s*(?:static\s+|inline\s+|extern\s+|virtual\s+|constexpr\s+)*'
            r'(?:[\w:*&<>,\s]+?)\s+'
            r'(\w+(?:::\w+)*)\s*\(([^)]*)\)\s*(?:const\s*)?(?:->\s*[\w:*&<>,\s]+\s*)?$',
            line
        )
        if m:
            fn_name = m.group(1)
            skip_names = {'if', 'for', 'while', 'switch', 'catch', 'return',
                         'class', 'struct', 'enum', 'union', 'namespace', 'typedef',
                         'using', 'template', 'include', 'define', 'ifdef', 'endif',
                         'ifdef', 'ifndef', 'endif', 'pragma', 'elif'}
            if fn_name in skip_names:
                continue
            # Check if next non-empty line starts with '{'
            next_brace = False
            for j in range(i + 1, min(i + 3, len(lines))):
                stripped_next = lines[j].strip()
                if not stripped_next:
                    continue
                if stripped_next.startswith('{'):
                    next_brace = True
                break
            if next_brace:
                functions.append({
                    "name": fn_name,
                    "line": i + 1,
                    "type": "function",
                    "params_str": m.group(2),
                    "start_col": len(line) - len(line.lstrip()),
                })

        # Also handle calling-convention split: "int ngx_cdecl\nmain(...)"
        # The function name appears alone on a line with just params
        m2 = re.match(r'^(\w+)\s*\(([^)]*)\)\s*$', line.strip())
        if m2 and not m:  # Don't double-match
            fn_name = m2.group(1)
            if fn_name in ('if', 'for', 'while', 'switch', 'catch', 'return',
                          'class', 'struct', 'enum', 'union', 'namespace',
                          'ifdef', 'ifndef', 'endif', 'define', 'include'):
                continue
            # Check if previous line has a type/return type
            if i > 0:
                prev_stripped = lines[i - 1].strip()
                # Previous line should look like a return type (ends without semicolon/brace)
                if prev_stripped and not prev_stripped.endswith(';') and not prev_stripped.endswith('{') \
                   and not prev_stripped.startswith('//') and not prev_stripped.startswith('/*') \
                   and not prev_stripped.startswith('#'):
                    # Check next line for opening brace
                    next_brace = False
                    for j in range(i + 1, min(i + 3, len(lines))):
                        stripped_next = lines[j].strip()
                        if not stripped_next:
                            continue
                        if stripped_next.startswith('{'):
                            next_brace = True
                        break
                    if next_brace:
                        functions.append({
                            "name": fn_name,
                            "line": i + 1,
                            "type": "function",
                            "params_str": m2.group(2),
                            "start_col": len(line) - len(line.lstrip()),
                        })

    return functions


# ─── Function Body Extraction ──────────────────────────────────

def _get_function_body_and_end(
    lines: List[str], fn_info: Dict, ext: str
) -> Tuple[str, int]:
    """
    Extract the function body text and end line number.
    Returns (body_text, end_line_index).
    """
    start = fn_info["line"] - 1
    if start >= len(lines):
        return "", start

    if ext == ".py":
        return _get_py_function_body(lines, start)
    else:
        return _get_brace_function_body(lines, start)


def _get_py_function_body(lines: List[str], start: int) -> Tuple[str, int]:
    """Extract Python function body using indentation."""
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    body_lines = [lines[start]]

    for i in range(start + 1, len(lines)):
        line = lines[i]
        stripped = line.rstrip()

        # Empty lines are part of the function
        if not stripped:
            body_lines.append(line)
            continue

        current_indent = len(line) - len(line.lstrip())

        # If we return to same or lower indentation, function ended
        if current_indent <= base_indent:
            break

        body_lines.append(line)

    return '\n'.join(body_lines), start + len(body_lines)


def _get_brace_function_body(lines: List[str], start: int) -> Tuple[str, int]:
    """Extract JS/TS/Rust function body using brace counting."""
    brace_count = 0
    started = False
    body_lines = []

    for i in range(start, min(start + 500, len(lines))):
        line = lines[i]
        body_lines.append(line)

        # Skip string contents (rough heuristic)
        in_string = False
        j = 0
        while j < len(line):
            ch = line[j]
            if ch in ('"', "'", '`') and (j == 0 or line[j-1] != '\\'):
                in_string = not in_string
            elif not in_string:
                if ch == '{':
                    brace_count += 1
                    started = True
                elif ch == '}':
                    brace_count -= 1
                    if started and brace_count == 0:
                        return '\n'.join(body_lines), i
            j += 1

        if started and brace_count == 0:
            return '\n'.join(body_lines), i

    return '\n'.join(body_lines), start + len(body_lines)


# ─── Cyclomatic Complexity ─────────────────────────────────────

def _compute_cyclomatic(fn_body: str, ext: str) -> int:
    """
    Compute cyclomatic complexity = decision points + 1.

    Decision points:
    - if, elif, else (Python: elif, JS/TS: else if)
    - for, while, do-while
    - case (switch/case)
    - &&, ||
    - try/except (each except clause)
    - ternary ?:
    - nullish coalesce ?? (when used in conditional context)
    - catch blocks
    """
    decisions = 0

    # Remove string literals to avoid false positives
    clean = _remove_strings(fn_body, ext)
    # Remove comments
    clean = _remove_comments(clean, ext)

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        decisions += _count_js_decisions(clean)
    elif ext == ".py":
        decisions += _count_py_decisions(clean)
    elif ext == ".rs":
        decisions += _count_rs_decisions(clean)
    elif ext == ".go":
        decisions += _count_go_decisions(clean)
    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
        decisions += _count_c_cpp_decisions(clean)

    return decisions + 1


def _count_js_decisions(clean: str) -> int:
    """Count decision points in JS/TS code."""
    count = 0

    # if statements (but not else if — those are counted via else)
    count += len(re.findall(r'\bif\s*\(', clean))
    # else (standalone, not else if)
    count += len(re.findall(r'\belse\s+(?!if\b)', clean))
    # else if
    count += len(re.findall(r'\belse\s+if\s*\(', clean))
    # for loops
    count += len(re.findall(r'\bfor\s*\(', clean))
    # for...of / for...in
    count += len(re.findall(r'\bfor\s*\(', clean))  # already counted above
    # while loops
    count += len(re.findall(r'\bwhile\s*\(', clean))
    # do-while
    count += len(re.findall(r'\bdo\s*\{', clean))
    # switch cases (each case is a decision)
    count += len(re.findall(r'\bcase\s+', clean))
    # catch blocks
    count += len(re.findall(r'\bcatch\s*\(', clean))
    # && and ||
    count += clean.count('&&')
    count += clean.count('||')
    # Ternary operators
    count += len(re.findall(r'\?\s*[^.?]', clean))
    # Nullish coalescing (in conditional context)
    count += clean.count('??')

    return count


def _count_py_decisions(clean: str) -> int:
    """Count decision points in Python code."""
    count = 0

    # if statements
    count += len(re.findall(r'\bif\s+', clean))
    # elif statements
    count += len(re.findall(r'\belif\s+', clean))
    # else (standalone)
    count += len(re.findall(r'\belse\s*:', clean))
    # for loops
    count += len(re.findall(r'\bfor\s+', clean))
    # while loops
    count += len(re.findall(r'\bwhile\s+', clean))
    # except clauses (each is a decision)
    count += len(re.findall(r'\bexcept\s+', clean))
    # and / or operators
    count += len(re.findall(r'\band\b', clean))
    count += len(re.findall(r'\bor\b', clean))
    # Ternary / conditional expression: x if cond else y
    count += len(re.findall(r'\bif\b.*\belse\b', clean))
    # walrus operator (:=) adds a decision point
    count += clean.count(':=')
    # match/case (Python 3.10+)
    count += len(re.findall(r'\bcase\s+', clean))

    return count


def _count_rs_decisions(clean: str) -> int:
    """Count decision points in Rust code."""
    count = 0

    # if statements
    count += len(re.findall(r'\bif\s+', clean))
    # else if
    count += len(re.findall(r'\belse\s+if\s+', clean))
    # else
    count += len(re.findall(r'\belse\s*\{', clean))
    # for loops
    count += len(re.findall(r'\bfor\s+', clean))
    # while loops
    count += len(re.findall(r'\bwhile\s+', clean))
    # loop (always counts)
    count += len(re.findall(r'\bloop\s*\{', clean))
    # match arms — each arm is a decision
    count += len(re.findall(r'=>\s*$', clean, re.MULTILINE))
    # && and ||
    count += clean.count('&&')
    count += clean.count('||')
    # Ternary
    # Rust doesn't have ternary but has if-as-expression

    return count


def _count_go_decisions(clean: str) -> int:
    """Count decision points in Go code."""
    count = 0

    # if statements
    count += len(re.findall(r'\bif\s+', clean))
    # else if
    count += len(re.findall(r'\belse\s+if\s+', clean))
    # else
    count += len(re.findall(r'\belse\s*\{', clean))
    # for loops
    count += len(re.findall(r'\bfor\s+', clean))
    # switch cases — each case is a decision
    count += len(re.findall(r'\bcase\s+', clean))
    # select cases — each case in a select statement
    count += len(re.findall(r'\bcase\s+<-', clean))
    # && and ||
    count += clean.count('&&')
    count += clean.count('||')

    return count


def _count_c_cpp_decisions(clean: str) -> int:
    """Count decision points in C/C++ code."""
    count = 0

    # if statements
    count += len(re.findall(r'\bif\s*\(', clean))
    # else if
    count += len(re.findall(r'\belse\s+if\s*\(', clean))
    # else
    count += len(re.findall(r'\belse\s*\{', clean))
    # for loops
    count += len(re.findall(r'\bfor\s*\(', clean))
    # while loops
    count += len(re.findall(r'\bwhile\s*\(', clean))
    # do-while
    count += len(re.findall(r'\bdo\s*\{', clean))
    # switch cases — each case is a decision
    count += len(re.findall(r'\bcase\s+', clean))
    # catch blocks
    count += len(re.findall(r'\bcatch\s*\(', clean))
    # && and ||
    count += clean.count('&&')
    count += clean.count('||')
    # Ternary operator
    count += len(re.findall(r'\?\s*[^:]+\s*:', clean))
    # Preprocessor #if (each is a decision branch)
    count += len(re.findall(r'^\s*#\s*if\b', clean, re.MULTILINE))
    count += len(re.findall(r'^\s*#\s*elif\b', clean, re.MULTILINE))

    return count


# ─── Cognitive Complexity ──────────────────────────────────────

def _compute_cognitive(fn_body: str, ext: str) -> int:
    """
    Compute cognitive complexity per the SonarSource specification.

    Rules:
    - +1 for each break in linear flow (if, elif, else, for, while, switch, catch)
    - +1 nesting increment for each nested structure
    - else / elif / else if: no additional increment for the keyword,
      but nesting increment still applies
    - No increment for function/method definitions
    - Nesting increments: the total nesting level at each structural element
      adds to the complexity
    """
    clean = _remove_strings(fn_body, ext)
    clean = _remove_comments(clean, ext)
    lines = clean.split('\n')

    total = 0
    nesting = 0

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        total = _cognitive_js(lines)
    elif ext == ".py":
        total = _cognitive_py(lines)
    elif ext == ".rs":
        total = _cognitive_rs(lines)
    elif ext == ".go":
        total = _cognitive_brace_based(lines)
    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}:
        total = _cognitive_brace_based(lines)

    return total


def _cognitive_js(lines: List[str]) -> int:
    """Compute cognitive complexity for JS/TS code."""
    total = 0
    nesting = 0
    # Track nesting via braces (simplified)
    brace_stack = []  # Stack of (char, nesting_at_entry)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Increment for control flow breaks
        # Check 'else if' BEFORE 'if' — else-if lines also match \bif\s*\(
        if re.search(r'\belse\s+if\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\bif\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\belse\s*', stripped) and not re.search(r'\belse\s+if', stripped):
            # else doesn't get the +1 base increment, only nesting
            total += nesting
        elif re.search(r'\bfor\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\bwhile\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\bdo\s*\{', stripped):
            total += 1 + nesting
        elif re.search(r'\bswitch\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\bcase\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bcatch\s*\(', stripped):
            total += 1 + nesting

        # Logical operators add +1 regardless of nesting
        total += stripped.count('&&')
        total += stripped.count('||')

        # Ternary
        ternary_count = len(re.findall(r'\?\s*[^.?*]', stripped))
        total += ternary_count * (1 + nesting)

        # Track nesting by counting braces
        for ch in stripped:
            if ch == '{':
                brace_stack.append(nesting)
                nesting += 1
            elif ch == '}':
                if brace_stack:
                    nesting = brace_stack.pop()
                elif nesting > 0:
                    nesting -= 1

    return total


def _cognitive_py(lines: List[str]) -> int:
    """
    Compute cognitive complexity for Python code.
    Uses indentation tracking for nesting.
    """
    total = 0
    indent_stack = [0]  # Stack of indent levels

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_indent = len(line) - len(line.lstrip())

        # Pop indent stack back to current level
        while indent_stack and indent_stack[-1] >= current_indent and len(indent_stack) > 1:
            indent_stack.pop()

        nesting = len(indent_stack) - 1

        # Control flow breaks
        if re.search(r'\bif\s+', stripped):
            total += 1 + nesting
            if stripped.endswith(':'):
                indent_stack.append(current_indent)
        elif re.search(r'\belif\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\belse\s*:', stripped):
            total += nesting  # No base increment for else
        elif re.search(r'\bfor\s+', stripped):
            total += 1 + nesting
            if stripped.endswith(':'):
                indent_stack.append(current_indent)
        elif re.search(r'\bwhile\s+', stripped):
            total += 1 + nesting
            if stripped.endswith(':'):
                indent_stack.append(current_indent)
        elif re.search(r'\bexcept\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\btry\s*:', stripped):
            total += 1 + nesting
            indent_stack.append(current_indent)
        elif re.search(r'\bwith\s+', stripped):
            total += 1 + nesting
            if stripped.endswith(':'):
                indent_stack.append(current_indent)
        elif re.search(r'\bcase\s+', stripped):
            total += 1 + nesting
            if stripped.endswith(':'):
                indent_stack.append(current_indent)

        # Logical operators
        total += len(re.findall(r'\band\b', stripped))
        total += len(re.findall(r'\bor\b', stripped))

        # Ternary: x if cond else y
        if re.search(r'\bif\b.*\belse\b', stripped) and not stripped.startswith(('if', 'elif')):
            total += 1 + nesting

    return total


def _cognitive_rs(lines: List[str]) -> int:
    """Compute cognitive complexity for Rust code."""
    total = 0
    nesting = 0
    brace_stack = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if re.search(r'\belse\s+if\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bif\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\belse\s*\{', stripped):
            total += nesting
        elif re.search(r'\bfor\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bwhile\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bloop\s*\{', stripped):
            total += 1 + nesting
        elif re.search(r'\bmatch\s+', stripped):
            total += 1 + nesting
        elif re.search(r'=>', stripped) and stripped.rstrip().endswith(','):
            # Match arm
            total += 1 + nesting

        # Logical operators
        total += stripped.count('&&')
        total += stripped.count('||')

        # Track nesting
        for ch in stripped:
            if ch == '{':
                brace_stack.append(nesting)
                nesting += 1
            elif ch == '}':
                if brace_stack:
                    nesting = brace_stack.pop()
                elif nesting > 0:
                    nesting -= 1

    return total


def _cognitive_brace_based(lines: List[str]) -> int:
    """Compute cognitive complexity for brace-based languages (Go, C/C++)."""
    total = 0
    nesting = 0
    brace_stack = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Control flow increments
        if re.search(r'\bif\s*', stripped):
            total += 1 + nesting
        elif re.search(r'\belse\s+if\b', stripped):
            total += 1 + nesting
        elif re.search(r'\belse\s*\{', stripped) or re.search(r'\belse\s*$', stripped):
            total += nesting
        elif re.search(r'\bfor\s*', stripped):
            total += 1 + nesting
        elif re.search(r'\bwhile\s*\(', stripped):
            total += 1 + nesting
        elif re.search(r'\bdo\s*\{', stripped):
            total += 1 + nesting
        elif re.search(r'\bswitch\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bcase\s+', stripped):
            total += 1 + nesting
        elif re.search(r'\bcatch\s*\(', stripped):
            total += 1 + nesting
        # Go-specific: select statement
        elif re.search(r'\bselect\s*\{', stripped):
            total += 1 + nesting

        # Logical operators
        total += stripped.count('&&')
        total += stripped.count('||')
        # C/C++ ternary
        if '?' in stripped and ':' in stripped:
            total += 1

        # Track nesting
        for ch in stripped:
            if ch == '{':
                brace_stack.append(nesting)
                nesting += 1
            elif ch == '}':
                if brace_stack:
                    nesting = brace_stack.pop()
                elif nesting > 0:
                    nesting -= 1

    return total


# ─── LOC Counting ──────────────────────────────────────────────

def _count_loc(fn_body: str) -> int:
    """Count lines of code (non-blank, non-comment-only lines)."""
    lines = fn_body.split('\n')
    loc = 0
    in_block_comment = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        # Block comment tracking (simplified)
        if in_block_comment:
            if '*/' in stripped:
                in_block_comment = False
                stripped = stripped[stripped.index('*/') + 2:].strip()
                if not stripped:
                    continue
            else:
                continue

        if stripped.startswith('/*'):
            if '*/' in stripped:
                stripped = stripped[stripped.index('*/') + 2:].strip()
                if not stripped:
                    continue
            else:
                in_block_comment = True
                continue

        # Single-line comments
        if stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('*'):
            continue

        loc += 1

    return loc


# ─── Parameter Counting ────────────────────────────────────────

def _count_params(params_str: str, ext: str) -> int:
    """Count the number of parameters in a function signature."""
    params_str = params_str.strip()
    if not params_str:
        return 0

    # Remove type annotations for counting
    if ext == ".py":
        # Remove self/cls
        params_str = re.sub(r'\bself\s*,?\s*', '', params_str)
        params_str = re.sub(r'\bcls\s*,?\s*', '', params_str)
        # Remove type hints
        params_str = re.sub(r':\s*[^,=)]+', '', params_str)
        # Remove default values
        params_str = re.sub(r'=\s*[^,)]+', '', params_str)

    elif ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Remove type annotations (TS)
        params_str = re.sub(r':\s*[^,)=]+', '', params_str)
        # Remove default values
        params_str = re.sub(r'=\s*[^,)]+', '', params_str)
        # Remove rest spread for counting (counts as 1 param)
        params_str = re.sub(r'\.\.\.', 'rest_', params_str)

    elif ext == ".rs":
        # Remove type annotations
        params_str = re.sub(r':\s*[^,)]+', '', params_str)
        # Remove mut keyword
        params_str = re.sub(r'\bmut\s+', '', params_str)

    # Count comma-separated items
    params = [p.strip() for p in params_str.split(',') if p.strip()]
    return len(params)


# ─── Nesting Depth ─────────────────────────────────────────────

def _compute_max_nesting(fn_body: str, ext: str) -> int:
    """Compute maximum nesting depth in the function body."""
    clean = _remove_strings(fn_body, ext)
    clean = _remove_comments(clean, ext)

    if ext == ".py":
        return _max_nesting_python(clean)
    else:
        return _max_nesting_brace(clean)


def _max_nesting_python(clean: str) -> int:
    """Compute max nesting depth for Python using indentation."""
    lines = clean.split('\n')
    max_depth = 0
    prev_indents = [0]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_indent = len(line) - len(line.lstrip())

        # Track indentation levels
        while prev_indents and prev_indents[-1] > current_indent:
            prev_indents.pop()

        if current_indent > (prev_indents[-1] if prev_indents else 0):
            prev_indents.append(current_indent)

        depth = len(prev_indents) - 1
        max_depth = max(max_depth, depth)

    return max_depth


def _max_nesting_brace(clean: str) -> int:
    """Compute max nesting depth for brace-based languages."""
    max_depth = 0
    current_depth = 0

    for ch in clean:
        if ch == '{':
            current_depth += 1
            max_depth = max(max_depth, current_depth)
        elif ch == '}':
            current_depth = max(0, current_depth - 1)

    return max_depth


# ─── Classification and Suggestions ────────────────────────────

def _classify_complexity(cyclomatic: int) -> str:
    """Classify cyclomatic complexity into a level."""
    if cyclomatic <= CC_SIMPLE:
        return "simple"
    elif cyclomatic <= CC_MODERATE:
        return "moderate"
    elif cyclomatic <= CC_COMPLEX:
        return "complex"
    elif cyclomatic <= CC_VERY_COMPLEX:
        return "very_complex"
    else:
        return "untamable"


def _generate_refactoring_suggestion(
    cc: int, cog: int, loc: int, params: int, nesting: int, fn_name: str
) -> str:
    """Generate a specific refactoring suggestion based on the metrics."""
    suggestions = []

    if cc > CC_COMPLEX:
        suggestions.append(
            f"Reduce {cc - 1} decision points by extracting conditional logic into "
            f"separate helper functions or using polymorphism instead of switch/if chains."
        )
    elif cc > CC_MODERATE:
        suggestions.append(
            f"Consider using guard clauses or early returns to reduce branching."
        )

    if cog > COG_COMPLEX:
        suggestions.append(
            f"Cognitive complexity {cog} is very high — deeply nested logic is hard to reason about. "
            f"Flatten nesting with early returns or extract nested blocks into named functions."
        )

    if nesting > NESTING_HIGH:
        suggestions.append(
            f"Nesting depth {nesting} is excessive. Use guard clauses, extract methods, "
            f"or use Optional/Monad patterns to flatten."
        )
    elif nesting > NESTING_MODERATE:
        suggestions.append(
            f"Nesting depth {nesting} is moderate. Consider early returns to reduce it."
        )

    if loc > LOC_HIGH:
        suggestions.append(
            f"Function is {loc} lines long — split into smaller functions with single responsibilities."
        )
    elif loc > LOC_MODERATE:
        suggestions.append(
            f"Function is {loc} lines — consider extracting helper functions."
        )

    if params > PARAM_HIGH:
        suggestions.append(
            f"{params} parameters is too many. Use an options object, builder pattern, or parameter object."
        )
    elif params > PARAM_MODERATE:
        suggestions.append(
            f"{params} parameters — consider grouping related params into an object/struct."
        )

    if not suggestions:
        return "Function complexity is within acceptable limits."

    return " | ".join(suggestions)


def _generate_recommendations(
    functions: List[Dict],
    avg_cc: float,
    avg_cog: float,
    high_cc_count: int,
    by_level: Dict[str, int]
) -> List[str]:
    """Generate workspace-level recommendations."""
    recs = []

    if avg_cc > CC_MODERATE:
        recs.append(
            f"Average cyclomatic complexity is {avg_cc} — above the recommended threshold of "
            f"{CC_MODERATE}. Prioritize refactoring the most complex functions first."
        )
    elif avg_cc > CC_SIMPLE:
        recs.append(
            f"Average cyclomatic complexity is {avg_cc} — within acceptable range but "
            f"could be improved by simplifying moderate-complexity functions."
        )
    else:
        recs.append(
            f"Average cyclomatic complexity is {avg_cc} — codebase is well-structured."
        )

    if high_cc_count > 0:
        recs.append(
            f"{high_cc_count} functions have cyclomatic complexity > {CC_COMPLEX}. "
            f"These are the highest priority refactoring targets — start with the hotspots."
        )

    untamable = by_level.get("untamable", 0)
    very_complex = by_level.get("very_complex", 0)
    if untamable > 0:
        recs.append(
            f"CRITICAL: {untamable} functions are 'untamable' (CC > {CC_VERY_COMPLEX}). "
            f"These need immediate refactoring — they are virtually untestable and unmaintainable."
        )
    if very_complex > 0:
        recs.append(
            f"WARNING: {very_complex} functions are 'very complex' (CC {CC_COMPLEX+1}-{CC_VERY_COMPLEX}). "
            f"Plan refactoring sprints for these functions."
        )

    complex_count = by_level.get("complex", 0)
    if complex_count > 5:
        recs.append(
            f"{complex_count} functions are 'complex' (CC {CC_MODERATE+1}-{CC_COMPLEX}). "
            f"Consider pair programming sessions to refactor these systematically."
        )

    if avg_cog > COG_MODERATE:
        recs.append(
            f"Average cognitive complexity is {avg_cog} — this indicates the codebase has "
            f"significant nesting and would benefit from flattening control flow."
        )

    # Identify functions with high CC but reasonable LOC (condensed complexity)
    dense_functions = [
        f for f in functions
        if f["cyclomatic"] > CC_MODERATE and f["loc"] < 30
    ]
    if dense_functions:
        recs.append(
            f"{len(dense_functions)} functions have high complexity in few lines of code — "
            f"these use dense conditional expressions (ternaries, && chains). "
            f"Prefer explicit if/else for readability."
        )

    if not recs:
        recs.append("Codebase complexity metrics are healthy. No major refactoring needed.")

    return recs


# ─── String/Comment Removal Helpers ────────────────────────────

def _remove_strings(code: str, ext: str) -> str:
    """Remove string literals to avoid false positive matches."""
    # Replace string contents with placeholders
    result = code

    # Template literals (backtick strings)
    result = re.sub(r'`[^`]*`', '``', result)

    # Double-quoted strings
    result = re.sub(r'"(?:[^"\\]|\\.)*"', '""', result)

    # Single-quoted strings
    result = re.sub(r"'(?:[^'\\]|\\.)*'", "''", result)

    # Python triple-quoted strings
    if ext == ".py":
        result = re.sub(r'"""(?:[^"]|"[^"]|""[^"])*?"""', '""""""', result, flags=re.DOTALL)
        result = re.sub(r"'''(?:[^']|'[^']|''[^'])*?'''", "''''''", result, flags=re.DOTALL)

    # Rust raw strings
    if ext == ".rs":
        result = re.sub(r'r"(?:#*)"[^"]*"(?:#*)"', 'r""', result)
        result = re.sub(r"r'(?:#*)'[^']*'(?:#*)'", "r''", result)

    return result


def _remove_comments(code: str, ext: str) -> str:
    """Remove comments to avoid false positive matches."""
    result = code

    # Block comments — use non-greedy with bounded quantifier to avoid catastrophic backtracking
    # on files with /* but no matching */
    result = re.sub(r'/\*[\s\S]{0,50000}?\*/', '', result)

    # Line comments
    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs"}:
        result = re.sub(r'//.*$', '', result, flags=re.MULTILINE)
    elif ext == ".py":
        result = re.sub(r'#.*$', '', result, flags=re.MULTILINE)

    return result
