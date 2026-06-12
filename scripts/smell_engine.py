"""
Code Smell Detector for CodeLens — v3.1
Systematically detects code smells that AI struggles to find without reading every file.

Smell Categories:
1. God Object / God Function — too large, too many responsibilities
2. Deep Nesting — callback/promise/conditional hell
3. Long Function — function body exceeds threshold
4. Too Many Parameters — function signature overload
5. Duplicate Code — repeated patterns across files
6. Inconsistent Patterns — different styles for same operation
7. Magic Numbers / Strings — unexplained constants
8. Callback Hell — deeply nested callbacks/promises
9. Large File — file with too many lines
10. Complex Conditional — overly complex if/switch/ternary
11. Mutable Default Argument — Python mutable defaults (list/dict/set)
12. SQL Injection Risk — f-string/format SQL queries

Each smell gets a severity (info, warning, critical) and refactoring suggestion.
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, safe_read_file, is_generated_file


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    # Web frontend
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".vue", ".svelte",
    # Python
    ".py",
    # Rust
    ".rs",
    # C/C++
    ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx",
    # Go
    ".go",
    # Java/C#
    ".java", ".cs",
    # PHP
    ".php",
    # Lua
    ".lua",
    # Ruby
    ".rb",
    # Elixir
    ".ex", ".exs",
    # Swift
    ".swift",
    # Scala
    ".scala", ".sc",
    # Nim
    ".nim", ".nims",
    # Shell
    ".sh", ".bash", ".zsh",
    # Dart
    ".dart",
    # Zig
    ".zig",
    # Shader
    ".wgsl",
}

# Thresholds
LONG_FUNCTION_LINES = 50
LONG_FUNCTION_LINES_CRITICAL = 100
TOO_MANY_PARAMS = 5
TOO_MANY_PARAMS_CRITICAL = 8
DEEP_NESTING_LEVEL = 5
DEEP_NESTING_CRITICAL = 8
LARGE_FILE_LINES = 500
LARGE_FILE_LINES_CRITICAL = 1000
GOD_CLASS_METHODS = 20
GOD_CLASS_METHODS_CRITICAL = 35

# C/C++-specific thresholds: C projects use deeper nesting idiomatically
# (error-handling if-chains, platform #ifdef, switch-case nesting).
# Deep nesting in C is very common with error-handling patterns like
# if (step1() == OK) { if (step2() == OK) { ... } } which is standard C.
C_CPP_DEEP_NESTING_LEVEL = 8
C_CPP_DEEP_NESTING_CRITICAL = 11
C_CPP_LONG_FN_LINES = 80
C_CPP_LONG_FN_LINES_CRITICAL = 150
# C/C++ many-params: C functions inherently have more parameters since C lacks
# optional params, overloading, and default values. Callbacks and struct
# manipulation functions commonly accept 6-8 parameters.
C_CPP_TOO_MANY_PARAMS = 7
C_CPP_TOO_MANY_PARAMS_CRITICAL = 10

# Maximum findings per category per file (prevents noise on large files)
MAX_FINDINGS_PER_FILE = 20
# C/C++ files are typically much larger; reduce per-file cap to prevent
# massive aggregate counts on projects like nginx (1000+ C files).
C_CPP_MAX_FINDINGS_PER_FILE = 10

# Rust-specific thresholds: Rust idiomatically uses large impl blocks
# (e.g., builder pattern, ECS types, trait implementations). A Rust impl
# block with 30 methods is often perfectly normal. Only flag when
# significantly higher than idiomatic patterns.
RUST_GOD_IMPL_METHODS = 35
RUST_GOD_IMPL_METHODS_CRITICAL = 60
MAX_FILE_SIZE = 500 * 1024  # 500KB


def detect_smells(
    workspace: str,
    categories: Optional[List[str]] = None,
    severity_filter: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = 5000
) -> Dict[str, Any]:
    """
    Detect code smells across the workspace.

    Args:
        workspace: Absolute path to workspace
        categories: Optional list of smell categories to check
                   (long_fn, deep_nesting, many_params, large_file,
                    callback_hell, magic_values, god_object, complex_conditional,
                    duplicate_pattern, inconsistent)
        severity_filter: Optional filter: "info", "warning", "critical"
        config: CodeLens config
        max_files: Maximum number of files to scan (default: 5000)

    Returns:
        Dict with smells found, categorized and prioritized
    """
    workspace = os.path.abspath(workspace)

    valid_categories = {
        "long_fn", "deep_nesting", "many_params", "large_file",
        "callback_hell", "magic_values", "god_object",
        "complex_conditional", "duplicate_pattern", "inconsistent",
        "mutable_default", "sql_injection"
    }

    if categories:
        categories = [c for c in categories if c in valid_categories]
    else:
        categories = list(valid_categories)

    all_smells: Dict[str, List[Dict]] = {cat: [] for cat in valid_categories}
    files_scanned = 0
    files_truncated = False
    production_files_scanned = 0

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if files_scanned >= max_files:
                files_truncated = True
                break

            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip minified files
            if '.min.' in filename:
                continue

            # Skip generated files (generated/, vendor/, _pb2.py, etc.)
            # Note: is_generated_file expects a filename, not a path — pass both
            # the filename (for exact match) and the rel_path (for extension checks)
            if is_generated_file(filename) or is_generated_file(rel_path):
                continue

            # Skip files exceeding size cap
            try:
                if os.path.getsize(file_path) > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            content = safe_read_file(file_path, max_size=MAX_FILE_SIZE)
            if content is None:
                continue

            files_scanned += 1
            lines = content.split('\n')
            line_count = len(lines)

            # Track if this is a docs/examples/test file for scoring
            is_docs_or_example = _is_docs_or_example(rel_path)
            if not is_docs_or_example:
                production_files_scanned += 1

            # Large file detection
            if "large_file" in categories:
                if line_count > LARGE_FILE_LINES_CRITICAL:
                    all_smells["large_file"].append({
                        "file": rel_path,
                        "line_count": line_count,
                        "severity": "critical",
                        "message": f"File has {line_count} lines (threshold: {LARGE_FILE_LINES_CRITICAL})",
                        "suggestion": "Split into multiple modules. Extract related functionality."
                    })
                elif line_count > LARGE_FILE_LINES:
                    all_smells["large_file"].append({
                        "file": rel_path,
                        "line_count": line_count,
                        "severity": "warning",
                        "message": f"File has {line_count} lines (threshold: {LARGE_FILE_LINES})",
                        "suggestion": "Consider splitting into smaller modules."
                    })

            # Long function detection
            if "long_fn" in categories:
                fns = _detect_long_functions(content, ext, rel_path)
                all_smells["long_fn"].extend(fns)

            # Deep nesting detection
            if "deep_nesting" in categories:
                nested = _detect_deep_nesting(content, ext, rel_path)
                all_smells["deep_nesting"].extend(nested)

            # Too many parameters
            if "many_params" in categories:
                params = _detect_many_params(content, ext, rel_path)
                all_smells["many_params"].extend(params)

            # Callback hell
            if "callback_hell" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                cb = _detect_callback_hell(content, rel_path)
                all_smells["callback_hell"].extend(cb)

            # Magic values
            if "magic_values" in categories:
                magic = _detect_magic_values(content, ext, rel_path)
                all_smells["magic_values"].extend(magic)

            # Complex conditionals
            if "complex_conditional" in categories:
                conds = _detect_complex_conditionals(content, ext, rel_path)
                all_smells["complex_conditional"].extend(conds)

            # God object (classes/modules with too many methods)
            # Skip test/mock files — they inherently have many methods and are not production code
            if "god_object" in categories and not _is_test_or_mock_file(rel_path):
                gods = _detect_god_objects(content, ext, rel_path)
                all_smells["god_object"].extend(gods)

            # Mutable default argument detection (Python-specific)
            if "mutable_default" in categories and ext == ".py":
                mut_defaults = _detect_mutable_defaults(content, rel_path)
                all_smells["mutable_default"].extend(mut_defaults)

            # SQL injection risk (Python f-string/format SQL)
            if "sql_injection" in categories and ext == ".py":
                sql_inj = _detect_sql_injection(content, rel_path)
                all_smells["sql_injection"].extend(sql_inj)

    # Duplicate pattern detection (cross-file, only if requested)
    if "duplicate_pattern" in categories:
        dupes = _detect_duplicate_patterns(workspace)
        all_smells["duplicate_pattern"] = dupes

    # Inconsistent patterns (cross-file)
    if "inconsistent" in categories:
        inconsistent = _detect_inconsistent_patterns(workspace)
        all_smells["inconsistent"] = inconsistent

    # Apply severity filter
    if severity_filter:
        for cat in all_smells:
            all_smells[cat] = [
                s for s in all_smells[cat]
                if s.get("severity") == severity_filter
            ]

    # Compute totals
    total_smells = sum(len(v) for v in all_smells.values())
    critical_count = sum(
        1 for cat in all_smells.values()
        for s in cat if s.get("severity") == "critical"
    )
    warning_count = sum(
        1 for cat in all_smells.values()
        for s in cat if s.get("severity") == "warning"
    )
    info_count = total_smells - critical_count - warning_count

    # Compute health score (0-100) — percentile-based
    # Old formula: max(0, 100 - (critical*10 + warning*3 + info))
    # Problem: always returns 0 for medium+ projects.
    # New formula: density-based tiers + critical ratio adjustment
    # Weight info-level smells less so they don't inflate density
    # Use production_files_scanned for health score (exclude docs/examples/tests)
    # so that documentation code doesn't penalize the project health
    score_files = max(production_files_scanned, 1)
    # Count smells in production code only for health score
    prod_smells = 0
    prod_critical = 0
    prod_warning = 0
    for cat in all_smells.values():
        for s in cat:
            fpath = s.get("file", "")
            if not _is_docs_or_example(fpath):
                prod_smells += 1
                if s.get("severity") == "critical":
                    prod_critical += 1
                elif s.get("severity") == "warning":
                    prod_warning += 1
    prod_info = prod_smells - prod_critical - prod_warning
    weighted_smells = prod_critical * 3 + prod_warning * 1 + prod_info * 0.1
    density = weighted_smells / score_files  # weighted smells per production file

    if density <= 0.5:
        base_score = 95
    elif density <= 2:
        base_score = 85
    elif density <= 5:
        base_score = 70
    elif density <= 10:
        base_score = 55
    elif density <= 20:
        base_score = 40
    elif density <= 50:
        base_score = 25
    elif density <= 100:
        base_score = 20
    else:
        base_score = 8

    # Critical penalty: based on critical count per production file (capped)
    # v6.1: Fixed — any critical smells should always reduce health below 95
    critical_per_file = prod_critical / score_files
    if prod_critical == 0:
        critical_penalty = 0
    elif critical_per_file <= 0.01:
        critical_penalty = 3  # Even a single critical in a large project hurts
    elif critical_per_file <= 1:
        critical_penalty = 5
    elif critical_per_file <= 5:
        critical_penalty = 10
    elif critical_per_file <= 10:
        critical_penalty = 15
    elif critical_per_file <= 20:
        critical_penalty = 20
    else:
        critical_penalty = min(35, int(critical_per_file * 0.5))

    # v6.1: Absolute minimum penalty if any critical smells exist
    # A project with critical code smells should never score 95+
    if prod_critical > 0 and critical_penalty < 5:
        critical_penalty = 5

    # Critical ratio adjustment: fewer criticals relative to total = healthier
    critical_ratio = prod_critical / max(prod_smells, 1)
    if critical_ratio < 0.1:
        ratio_bonus = 5
    elif critical_ratio < 0.3:
        ratio_bonus = 0
    else:
        ratio_bonus = -5

    health_score = max(0, min(100, base_score - critical_penalty + ratio_bonus))

    # Top priority smells (critical first, then by category importance)
    priority_order = ["god_object", "sql_injection", "mutable_default", "long_fn", "deep_nesting", "callback_hell",
                      "many_params", "complex_conditional", "large_file",
                      "magic_values", "duplicate_pattern", "inconsistent"]
    top_smells = []
    for cat in priority_order:
        for smell in all_smells.get(cat, []):
            if smell.get("severity") == "critical":
                top_smells.append({**smell, "category": cat})
    for cat in priority_order:
        for smell in all_smells.get(cat, []):
            if smell.get("severity") == "warning" and len(top_smells) < 20:
                top_smells.append({**smell, "category": cat})

    # Build by_category with only non-empty categories
    by_category = {
        cat: smells for cat, smells in all_smells.items() if smells
    }

    # total_findings: correct sum of all findings across all categories
    total_findings = sum(len(v) for v in by_category.values())

    return {
        "status": "ok",
        "workspace": workspace,
        "health_score": health_score,  # v5.8: Also at top-level for easy access
        "total_findings": total_findings,
        "stats": {
            "files_scanned": files_scanned,
            "total_smells": total_smells,
            "total_findings": total_findings,
            "critical": critical_count,
            "warning": warning_count,
            "info": info_count,
            "health_score": health_score,
            "by_category": {cat: len(smells) for cat, smells in by_category.items()},
        },
        "files_truncated": files_truncated,
        "by_category": by_category,
        "top_priority": top_smells[:20],
        "categories_checked": list(categories)
    }


# ─── Individual Smell Detectors ────────────────────────────────

def _detect_long_functions(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect functions that are too long."""
    smells = []

    # v5.9.2: Skip test/story/fixture files — long functions are expected there
    # v6.5: Use comprehensive _is_test_or_mock_file() for broader matching
    if _is_test_or_mock_file(rel_path):
        return smells

    lines = content.split('\n')

    # Find function definitions and their line ranges
    fn_starts = []

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        for i, line in enumerate(lines):
            # function declarations
            if re.match(r'(?:export\s+)?(?:async\s+)?function\s+\w+', line.strip()):
                fn_starts.append((i, _extract_fn_name_js(line)))
            # arrow functions with name
            elif re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', line.strip()):
                m = re.match(r'(?:export\s+)?(?:const|let|var)\s+(\w+)', line.strip())
                if m:
                    fn_starts.append((i, m.group(1)))
            # class methods with access modifiers: public/private/protected [static] [async] name(...)
            # Require access modifier to avoid false positives from function calls inside methods
            elif re.match(
                r'(?:(?:public|private|protected)\s+)(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?:readonly\s+)?(?:\*\s*)?(\w+)\s*(?:<[^>]*>)?\s*\(',
                line.strip()
            ):
                m = re.match(
                    r'(?:(?:public|private|protected)\s+)(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?:readonly\s+)?(?:\*\s*)?(\w+)',
                    line.strip()
                )
                if m:
                    fn_starts.append((i, m.group(1)))
            # constructor
            elif re.match(r'constructor\s*\(', line.strip()):
                fn_starts.append((i, 'constructor'))

    elif ext == ".py":
        for i, line in enumerate(lines):
            if re.match(r'(?:async\s+)?def\s+\w+', line.strip()):
                m = re.match(r'(?:async\s+)?def\s+(\w+)', line.strip())
                if m:
                    fn_starts.append((i, m.group(1)))

    elif ext == ".rs":
        for i, line in enumerate(lines):
            if re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+', line.strip()):
                m = re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', line.strip())
                if m:
                    fn_starts.append((i, m.group(1)))

    elif ext == ".php":
        for i, line in enumerate(lines):
            stripped = line.strip()
            # PHP method with visibility: public function, private function, protected function
            m = re.match(r'(?:public|private|protected)\s+(?:static\s+)?function\s+(\w+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))
            # PHP standalone function
            elif re.match(r'function\s+(\w+)', stripped):
                m = re.match(r'function\s+(\w+)', stripped)
                if m:
                    fn_starts.append((i, m.group(1)))

    elif ext in {".ex", ".exs"}:
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Elixir: def, defp, defmacro, defmacrop
            m = re.match(r'(?:def|defp|defmacro|defmacrop)\s+([\w!?]+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext == ".rb":
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Ruby: def method_name, def self.method_name
            m = re.match(r'def\s+(?:self\.)?(\w+[?!]?)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext == ".swift":
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Swift: func name(), static func name()
            m = re.match(r'(?:static\s+)?func\s+(\w+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext in {".scala", ".sc"}:
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Scala: def name(), private def name()
            m = re.match(r'(?:private|protected)?\s*def\s+(\w+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext in {".nim", ".nims"}:
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Nim: proc name(), func name(), template name(), macro name()
            m = re.match(r'(?:proc|func|template|macro)\\s+(\w+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext in {".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Go: func name()
            m = re.match(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)', stripped)
            if m and m.group(1) not in ('init', 'main'):
                fn_starts.append((i, m.group(1)))
            # C/C++: type name(...)
            elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}:
                m = re.match(r'(?:static\s+|inline\s+)*(?:\w+[\s*]+)+(\w+)\s*\(', stripped)
                if m and m.group(1) not in ('if', 'for', 'while', 'switch', 'return', 'sizeof', 'include',
                                                   'define', 'ifdef', 'ifndef', 'elif', 'pragma'):
                    # v6.4: Skip C/C++ function declarations (no body) in header files.
                    # A declaration ends with ';' on the same or next few lines — no '{' body.
                    # Only register functions that have an actual body definition.
                    is_header = ext in {'.h', '.hpp', '.hxx'}
                    # Check if this line or the next few lines contain '{' (definition)
                    # or ';' (declaration) to distinguish
                    found_brace = '{' in line or stripped.endswith('{')
                    found_semi = False
                    if not found_brace:
                        # Look ahead a few lines for opening brace or semicolon
                        for lookahead in range(i + 1, min(i + 5, len(lines))):
                            la_stripped = lines[lookahead].strip()
                            if '{' in lines[lookahead]:
                                found_brace = True
                                break
                            if la_stripped.endswith(';'):
                                found_semi = True
                                break
                            if not la_stripped:  # blank line
                                continue
                    if found_semi and not found_brace:
                        # This is a declaration, not a definition — skip for long_fn detection
                        # But still track it for many_params (parameter count is still relevant)
                        continue
                    if is_header and not found_brace:
                        # In header files, if we can't find a brace, it's likely a declaration
                        continue
                    fn_starts.append((i, m.group(1)))

    elif ext == ".lua":
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Lua: function name(), local function name()
            m = re.match(r'(?:local\s+)?function\s+([\w.:]+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    elif ext == ".zig":
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Zig: pub fn name(), fn name()
            m = re.match(r'(?:pub\s+)?fn\s+(\w+)', stripped)
            if m:
                fn_starts.append((i, m.group(1)))

    # v6.4: For C/C++ headers, apply a further sanity check:
    # If _find_function_end returns the max (300 lines or end-of-file),
    # the function likely has no body (it's a declaration we missed).
    is_c_cpp_header = ext in {'.h', '.hpp', '.hxx'}
    is_c_cpp = ext in {'.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx'}

    # v6.4: Use higher long-fn thresholds for C/C++ (idiomatically longer functions)
    long_fn_threshold = C_CPP_LONG_FN_LINES if is_c_cpp else LONG_FUNCTION_LINES
    long_fn_critical = C_CPP_LONG_FN_LINES_CRITICAL if is_c_cpp else LONG_FUNCTION_LINES_CRITICAL

    # Calculate function lengths
    for idx, (start, name) in enumerate(fn_starts):
        # Find end of function
        end = _find_function_end(lines, start, ext)
        length = end - start

        # v6.4: For C/C++ header files, skip extremely long "functions"
        # that span most of the file — these are almost certainly
        # declarations without bodies that slipped through the initial check.
        if is_c_cpp_header and length >= 200:
            continue

        if length > long_fn_critical:
            smells.append({
                "file": rel_path,
                "line": start + 1,
                "fn": name,
                "length": length,
                "severity": "critical",
                "message": f"Function '{name}' is {length} lines (critical threshold: {long_fn_critical})",
                "suggestion": "Break into smaller functions. Each function should do one thing."
            })
        elif length > long_fn_threshold:
            smells.append({
                "file": rel_path,
                "line": start + 1,
                "fn": name,
                "length": length,
                "severity": "warning",
                "message": f"Function '{name}' is {length} lines (threshold: {long_fn_threshold})",
                "suggestion": "Consider extracting helper functions."
            })

    return smells


def _find_function_end(lines: List[str], start: int, ext: str) -> int:
    """Find the end line of a function starting at `start`."""
    if ext == ".py":
        # Python: function ends when indentation returns to same or lower level
        base_indent = len(lines[start]) - len(lines[start].lstrip())
        for i in range(start + 1, len(lines)):
            stripped = lines[i].rstrip()
            if not stripped or stripped.startswith('#'):
                continue
            current_indent = len(lines[i]) - len(lines[i].lstrip())
            if current_indent <= base_indent and stripped:
                return i
        return len(lines)
    elif ext in {".ex", ".exs"}:
        # Elixir: count do/end pairs
        depth = 0
        for i in range(start, min(start + 200, len(lines))):
            stripped = lines[i].strip()
            depth += stripped.count(' do') + stripped.count(' do,') + stripped.endswith(' do')
            depth -= stripped.count('end')
            if depth <= 0 and i > start:
                return i + 1
        return min(start + 200, len(lines))
    elif ext == ".rb":
        # Ruby: count do/end, def/end
        depth = 0
        found_def = False
        for i in range(start, min(start + 300, len(lines))):
            stripped = lines[i].strip()
            if i == start:
                depth = 1
                found_def = True
                continue
            if found_def:
                depth += stripped.count(' do') + stripped.count(' do|') + stripped.startswith('do|')
                depth += stripped.startswith('if ') + stripped.startswith('unless ') + stripped.startswith('while ')
                depth -= stripped == 'end'
                if depth <= 0:
                    return i + 1
        return min(start + 300, len(lines))
    elif ext == ".lua":
        # Lua: count function/end, if/end, for/end, while/end
        depth = 0
        for i in range(start, min(start + 300, len(lines))):
            stripped = lines[i].strip()
            if i == start:
                depth = 1
                continue
            depth += len(re.findall(r'\b(?:function|if|for|while|do)\b', stripped))
            depth -= stripped.count('end')
            if depth <= 0:
                return i + 1
        return min(start + 300, len(lines))
    elif ext in {".go", ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx",
                 ".java", ".cs", ".swift", ".scala", ".sc", ".zig"}:
        # Brace-based languages: count { and }
        brace_count = 0
        for i in range(start, min(start + 300, len(lines))):
            for ch in lines[i]:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return i + 1
        return min(start + 300, len(lines))
    else:
        # JS/TS/Rust: count braces
        brace_count = 0
        for i in range(start, min(start + 300, len(lines))):
            for ch in lines[i]:
                if ch == '{':
                    brace_count += 1
                elif ch == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        return i + 1
        return min(start + 300, len(lines))


def _extract_fn_name_js(line: str) -> str:
    """Extract function name from JS/TS line."""
    m = re.search(r'function\s+(\w+)', line)
    if m:
        return m.group(1)
    m = re.search(r'(?:const|let|var)\s+(\w+)', line)
    if m:
        return m.group(1)
    return "anonymous"


def _detect_deep_nesting(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect deeply nested code blocks.
    
    Reports only the entry point of each deeply-nested block (where the
    nesting first exceeds the threshold), not every line inside the block.
    This avoids inflating the smell count with hundreds of duplicate findings.
    """
    smells = []
    
    # Skip test/story/fixture files — deep nesting is expected there
    # v6.5: Use comprehensive _is_test_or_mock_file() to also catch
    # test/ directory patterns like neovim's test/unit/, test/functional/
    if _is_test_or_mock_file(rel_path):
        return smells
    
    # v6.5: Skip C/C++ header files — headers contain macro definitions,
    # inline functions, and declarations that appear deeply indented but
    # don't represent actual control-flow nesting complexity.
    is_c_cpp_header = ext in {".h", ".hpp", ".hxx"}
    if is_c_cpp_header:
        return smells
    
    # v6.4: Use higher thresholds for C/C++ (idiomatic deeper nesting)
    is_c_cpp = ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}
    nesting_level = C_CPP_DEEP_NESTING_LEVEL if is_c_cpp else DEEP_NESTING_LEVEL
    nesting_critical = C_CPP_DEEP_NESTING_CRITICAL if is_c_cpp else DEEP_NESTING_CRITICAL
    max_findings = C_CPP_MAX_FINDINGS_PER_FILE if is_c_cpp else MAX_FINDINGS_PER_FILE
    
    lines = content.split('\n')
    
    prev_level = 0
    in_deep_block = False
    deep_block_level = 0
    deep_block_start = 0

    for i, line in enumerate(lines):
        # Calculate indentation level
        stripped = line.lstrip()
        if not stripped or stripped.startswith('//') or stripped.startswith('#'):
            continue

        # v6.5: For C/C++, skip preprocessor continuation lines, case/default
        # labels, and goto labels — these inflate indentation without
        # representing actual control-flow nesting.
        if is_c_cpp:
            # Skip case/default labels (idiomatic switch-case nesting)
            if re.match(r'\s*(case\s|default\s*:)', stripped):
                continue
            # Skip goto labels (e.g., `cleanup:`)
            if re.match(r'^[a-zA-Z_]\w*:\s*$', stripped):
                continue

        indent = len(line) - len(stripped)

        if ext == ".py":
            # Python: 4 spaces per level
            level = indent // 4
        elif ext in {".rs", ".go", ".java", ".cs", ".swift", ".scala", ".sc",
                     ".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx", ".zig"}:
            # Rust/Go/Java/C#/Swift/Scala/C/C++/Zig: 4 spaces per level
            level = indent // 4
        elif ext in {".ex", ".exs", ".rb", ".nim", ".nims"}:
            # Elixir/Ruby/Nim: 2 spaces per level
            level = indent // 2
        else:
            # JS/TS/Lua/PHP/Shell/Dart: 2 spaces per level
            level = indent // 2

        # Detect when we first enter a deep nesting block
        if level >= nesting_level and not in_deep_block:
            in_deep_block = True
            deep_block_level = level
            deep_block_start = i + 1
        # Detect when we exit the deep nesting block (return to shallower level)
        elif in_deep_block and level < nesting_level:
            in_deep_block = False
            severity = "critical" if deep_block_level >= nesting_critical else "warning"
            threshold = nesting_critical if severity == "critical" else nesting_level
            smells.append({
                "file": rel_path,
                "line": deep_block_start,
                "nesting_level": deep_block_level,
                "severity": severity,
                "message": f"Code is nested {deep_block_level} levels deep (threshold: {threshold})",
                "suggestion": "Extract inner logic into separate functions. Use early returns."
            })
            # v6.5: Cap findings per file to prevent noise
            if len(smells) >= max_findings:
                return smells
        
        # Track the deepest level within the block
        if in_deep_block and level > deep_block_level:
            deep_block_level = level

        prev_level = level

    # Handle case where file ends while still in a deep block
    if in_deep_block:
        severity = "critical" if deep_block_level >= nesting_critical else "warning"
        threshold = nesting_critical if severity == "critical" else nesting_level
        smells.append({
            "file": rel_path,
            "line": deep_block_start,
            "nesting_level": deep_block_level,
            "severity": severity,
            "message": f"Code is nested {deep_block_level} levels deep (threshold: {threshold})",
            "suggestion": "Extract inner logic into separate functions. Use early returns."
        })

    # v6.5: Cap total findings for C/C++ files to prevent noise
    if is_c_cpp and len(smells) > C_CPP_MAX_FINDINGS_PER_FILE:
        smells = smells[:C_CPP_MAX_FINDINGS_PER_FILE]

    return smells


def _detect_many_params(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect functions with too many parameters."""
    smells = []

    # v6.5: Skip test files — test helpers often have many params for setup
    if _is_test_or_mock_file(rel_path):
        return smells

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Function declarations: function name(params)
        for m in re.finditer(r'function\s+\w+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options object or builder pattern."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider grouping related parameters into an object."
                })

        # Arrow functions: const/let/var name = (params) =>
        for m in re.finditer(r'(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options object or builder pattern."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider grouping related parameters into an object."
                })

        # Class methods with access modifiers: public/private/protected name(params)
        # Only match methods with explicit access modifiers to avoid false positives
        for m in re.finditer(
            r'(?:public|private|protected)\s+(?:static\s+)?(?:async\s+)?(?:get\s+|set\s+)?(?:abstract\s+)?(?:\*\s*)?(\w+)\s*(?:<[^>]*>)?\s*\(([^)]*)\)\s*(?::\s*[^{]+)?\{',
            content
        ):
            params_str = m.group(2).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Method has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options object or builder pattern."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Method has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider grouping related parameters into an object."
                })

    elif ext == ".py":
        for m in re.finditer(r'(?:async\s+)?def\s+\w+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip() and p.strip() != 'self']
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use kwargs or a dataclass for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using keyword arguments or a config object."
                })

    elif ext == ".rs":
        for m in re.finditer(r'(?:pub\s+)?(?:async\s+)?fn\s+\w+\s*(?:<[^>]+>)?\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use a struct for grouping parameters."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using a builder pattern or struct."
                })

    elif ext == ".php":
        # PHP function/method: (public|private|protected) function name(params)
        for m in re.finditer(r'(?:public|private|protected)\s+(?:static\s+)?function\s+\w+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options array or DTO class for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using an associative array or config object."
                })

        # PHP standalone functions: function name(params)
        for m in re.finditer(r'\bfunction\s+(\w+)\s*\(([^)]*)\)', content):
            params_str = m.group(2).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)

            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options array or DTO class for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path,
                    "line": line_num,
                    "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using an associative array or config object."
                })

    elif ext in {".ex", ".exs"}:
        # Elixir: def name(arg1, arg2), defp name(arg1, arg2)
        for m in re.finditer(r'(?:def|defp|defmacro|defmacrop)\s+[\w!?]+\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use a keyword list or struct for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using a keyword list or map."
                })

    elif ext == ".rb":
        # Ruby: def name(arg1, arg2)
        for m in re.finditer(r'def\s+(?:self\.)?\w+[?!]?\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Method has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options hash for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Method has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using keyword arguments or a config hash."
                })

    elif ext == ".go":
        # Go: func name(params) or func (r Type) name(params)
        for m in re.finditer(r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an options struct for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using a struct or functional options pattern."
                })

    elif ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx", ".java", ".cs", ".swift", ".scala", ".sc", ".zig"}:
        # Brace-based languages: type name(params)
        is_c_cpp = ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}
        # v6.5: C/C++ uses higher param thresholds (no optional params, overloading,
        # or default values; callbacks commonly accept 6-8 params).
        param_threshold = C_CPP_TOO_MANY_PARAMS if is_c_cpp else TOO_MANY_PARAMS
        param_critical = C_CPP_TOO_MANY_PARAMS_CRITICAL if is_c_cpp else TOO_MANY_PARAMS_CRITICAL
        for m in re.finditer(r'(?:static\s+|inline\s+|public\s+|private\s+|protected\s+)*(?:\w+[\s*]+)+(\w+)\s*\(([^)]*)\)', content):
            params_str = m.group(2).strip()
            fn_name = m.group(1)
            if fn_name in ('if', 'for', 'while', 'switch', 'return', 'sizeof', 'catch', 'new', 'delete'):
                continue
            if not params_str:
                continue
            # v6.5: Skip C/C++ forward declarations (end with ';', no '{')
            # These are parameter declarations, not function definitions.
            if is_c_cpp:
                # Look for ';' or '{' after the closing ')'
                after_match = content[m.end():m.end() + 200]
                # Find the next non-whitespace char after the closing paren
                after_stripped = after_match.lstrip()
                # If the line ends with ';' before any '{', it's a declaration
                semi_pos = after_stripped.find(';')
                brace_pos = after_stripped.find('{')
                if semi_pos >= 0 and (brace_pos < 0 or semi_pos < brace_pos):
                    continue  # Forward declaration, skip
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= param_critical:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {param_critical})",
                    "suggestion": "Use a struct/class for grouping parameters."
                })
            elif param_count >= param_threshold:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {param_threshold})",
                    "suggestion": "Consider using a parameter object or builder pattern."
                })

    elif ext == ".lua":
        # Lua: function name(params)
        for m in re.finditer(r'(?:local\s+)?function\s+[\w.:]+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Function has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use a table for grouping parameters."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Function has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using a table for parameter grouping."
                })

    elif ext in {".nim", ".nims"}:
        # Nim: proc name(params)
        for m in re.finditer(r'(?:proc|func|template|macro)\s+\w+\s*\(([^)]*)\)', content):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            params = [p.strip() for p in params_str.split(',') if p.strip()]
            param_count = len(params)
            if param_count >= TOO_MANY_PARAMS_CRITICAL:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "critical",
                    "message": f"Proc has {param_count} parameters (critical threshold: {TOO_MANY_PARAMS_CRITICAL})",
                    "suggestion": "Use an object type for grouping."
                })
            elif param_count >= TOO_MANY_PARAMS:
                line_num = content[:m.start()].count('\n') + 1
                smells.append({
                    "file": rel_path, "line": line_num, "param_count": param_count,
                    "severity": "warning",
                    "message": f"Proc has {param_count} parameters (threshold: {TOO_MANY_PARAMS})",
                    "suggestion": "Consider using an object for parameter grouping."
                })

    # v6.5: Cap many_params findings for C/C++ files
    is_c_cpp = ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}
    if is_c_cpp and len(smells) > C_CPP_MAX_FINDINGS_PER_FILE:
        smells = smells[:C_CPP_MAX_FINDINGS_PER_FILE]

    return smells


def _detect_callback_hell(content: str, rel_path: str) -> List[Dict]:
    """Detect callback hell / deeply nested promises."""
    smells = []
    lines = content.split('\n')

    # Look for patterns of deeply nested callbacks or .then chains
    then_chain_depth = 0
    chain_start_line = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Count consecutive .then() or .catch() chains
        if '.then(' in stripped or '.catch(' in stripped:
            if then_chain_depth == 0:
                chain_start_line = i + 1
            then_chain_depth += 1
        else:
            if then_chain_depth >= 5:
                smells.append({
                    "file": rel_path,
                    "line": chain_start_line,
                    "chain_depth": then_chain_depth,
                    "severity": "critical" if then_chain_depth >= 7 else "warning",
                    "message": f"Promise chain is {then_chain_depth} levels deep",
                    "suggestion": "Use async/await instead of chained .then() calls."
                })
            then_chain_depth = 0

    # Also detect nested callback patterns (function(err, result))
    callback_depth = 0
    cb_start_line = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.search(r'function\s*\(\s*(?:err|error)', stripped) or re.search(r'\(err(?:or)?\)', stripped):
            if callback_depth == 0:
                cb_start_line = i + 1
            callback_depth += 1

        if callback_depth >= 3:
            smells.append({
                "file": rel_path,
                "line": cb_start_line,
                "callback_depth": callback_depth,
                "severity": "critical" if callback_depth >= 5 else "warning",
                "message": f"Nested callbacks {callback_depth} levels deep",
                "suggestion": "Refactor to use async/await or Promises."
            })
            callback_depth = 0

    return smells


def _detect_magic_values(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect magic numbers and strings (unexplained constants).

    v2 improvements:
    - Skip generated files (path checked externally, but also skip by content markers)
    - Python-aware: skip numbers in const assignments (UPPER_CASE =), type annotations,
      default arguments, f-strings, docstrings, and known Python patterns
    - Expanded common_numbers with common Python/Rust constants
    - Skip numbers in dict/list literals (likely config)
    - Skip numbers that are part of string content
    v6.5 improvements:
    - Skip test/spec files entirely (test data inherently has magic numbers)
    - Skip C/C++ crypto files and #define lines
    - Higher per-file caps for C/C++ files
    """
    smells = []
    lines = content.split('\n')

    # v6.5: Skip test/spec files — test data inherently contains many
    # literal values that are NOT magic numbers (they're test expectations).
    if _is_test_or_mock_file(rel_path):
        return smells

    # Skip magic number detection entirely for config/framework config files
    config_file_keywords = [
        'config', 'eslint', 'prettier', 'vitest', 'jest',
        'playwright', 'postcss', 'next.config', 'tsconfig',
        '.fixture.', '.stories.', '.story.', '.test.', '.spec.',
        'constants', 'const.py', 'consts', 'enums',
    ]
    rel_lower = rel_path.lower()
    if any(kw in rel_lower for kw in config_file_keywords):
        return smells

    # v6.5: Skip crypto/hashing algorithm files — they contain thousands of
    # legitimate numeric constants (S-boxes, round constants, lookup tables).
    crypto_file_keywords = [
        'sha1', 'sha256', 'sha512', 'md5', 'crc32', 'crc64',
        'aes', 'des', 'rsa', 'hmac', 'blake', 'chacha', 'salsa',
        'huff', 'huffman', 'lookup', 'table', 'lut',
    ]
    if any(kw in rel_lower for kw in crypto_file_keywords):
        return smells

    # Numbers that are likely NOT magic (common constants, HTTP codes, etc.)
    common_numbers = {
        0, 1, -1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 16, 20, 24, 30, 32, 36,
        48, 50, 60, 64, 100, 128, 200, 256, 300, 360, 500, 512, 1000, 1024,
        # HTTP status codes
        200, 201, 202, 204, 206, 301, 302, 304, 307, 308,
        400, 401, 403, 404, 405, 409, 422, 429, 500, 502, 503, 504,
        # v6.5: Common C/system constants (buffer sizes, page sizes, masks)
        4096, 8192, 16384, 32768, 65535, 65536,
        2048, 4096, 8192, 0xffff, 0xff,
    }

    # Context patterns that indicate config-like lines (skip numbers on these)
    config_context_patterns = [
        '.config.', '.config(', 'eslint', 'prettier', 'vitest',
        'jest', 'playwright', 'tailwind',
    ]

    # JSX/TSX style prop patterns — numbers in style/CSS props are not magic values
    jsx_style_patterns = [
        r'width\s*[:=]', r'height\s*[:=]', r'padding\s*[:=]', r'margin\s*[:=]',
        r'gap\s*[:=]', r'fontSize\s*[:=]', r'lineHeight\s*[:=]', r'borderRadius\s*[:=]',
        r'top\s*[:=]', r'left\s*[:=]', r'right\s*[:=]', r'bottom\s*[:=]',
        r'maxWidth\s*[:=]', r'minWidth\s*[:=]', r'maxHeight\s*[:=]',
        r'zIndex\s*[:=]', r'opacity\s*[:=]', r'delay\s*[:=]', r'duration\s*[:=]',
        r'timeout\s*[:=]', r'port\s*[:=]',
    ]

    # Python-specific skip patterns — these are NOT magic values
    python_skip_patterns = [
        r'^\s*[A-Z_][A-Z0-9_]*\s*=',     # UPPER_CASE = constant assignment
        r'^\s*def\s+\w+',                   # function definition (default args)
        r'^\s*class\s+\w+',                 # class definition
        r'.*:\s*(int|float|str|bool)\s*=',   # type annotation with default
        r'.*#.*type:\s*ignore',              # type: ignore comments
        r'^\s*"""', r'^\s*"""',             # docstrings
        r'^\s*return\s+',                   # return statements (often correct)
        r'.*range\(',                        # range() calls
        r'.*enumerate\(',                    # enumerate() calls
        r'.*\.format\(',                     # .format() calls
        r'.*%[sd]$',                         # %-formatting
        r'.*os\.path\.',                     # os.path operations
        r'.*logging\.',                      # logging configuration
        r'.*assert\s+',                      # assert statements
        r'.*pytest\.',                       # pytest configuration
        r'.*@pytest\.',                      # pytest decorators
        r'.*unittest\.',                     # unittest configuration
        r'.*__version__',                    # version declarations
        r'.*__all__',                        # __all__ exports
        r'.*typing\.',                       # typing module
        r'.*Optional\[',                     # Optional types
        r'.*Union\[',                        # Union types
    ]

    in_docstring = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track docstring boundaries
        if '"""' in stripped or "'''" in stripped:
            count = stripped.count('"""') + stripped.count("'''")
            if count == 1:
                in_docstring = not in_docstring
            continue  # Skip docstring lines entirely
        if in_docstring:
            continue

        # Skip comments, imports, and console/logs
        if stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('import'):
            continue
        if stripped.startswith('from ') and ' import ' in stripped:
            continue
        if 'console.' in stripped or 'print(' in stripped or 'log!' in stripped:
            continue

        # Skip lines in config-like contexts
        stripped_lower = stripped.lower()
        if any(pat in stripped_lower for pat in config_context_patterns):
            continue

        # Skip JSX style prop lines in TSX/JSX files
        if ext in {'.tsx', '.jsx'}:
            if any(re.search(pat, stripped) for pat in jsx_style_patterns):
                continue

        # Python-specific skips
        if ext == '.py':
            if any(re.search(pat, stripped) for pat in python_skip_patterns):
                continue

        # v6.5: C/C++-specific skips
        is_c_cpp = ext in {'.c', '.cpp', '.cxx', '.cc', '.h', '.hpp', '.hxx'}
        if is_c_cpp:
            # #define lines are NAMED constants — the opposite of magic values
            if stripped.startswith('#define') or stripped.startswith('# '):
                continue
            # case/default labels contain legitimate constants
            if re.match(r'(case\s|default\s*:)', stripped):
                continue
            # #include, #ifdef, #ifndef etc. — skip entirely
            if stripped.startswith('#'):
                continue
            # UPPER_CASE macro/constant assignments
            if re.match(r'^[A-Z_][A-Z0-9_]*\s*=', stripped):
                continue
            # sizeof() / offsetof() / alignof() — not magic
            if 'sizeof(' in stripped or 'offsetof(' in stripped or 'alignof(' in stripped:
                continue
            # Hexadecimal constants (0x...) are usually register addresses/masks
            if re.search(r'0x[0-9a-fA-F]+', stripped):
                continue

        # Check for magic numbers
        for m in re.finditer(r'(?<![.\w])(\d+)(?![.\w])', stripped):
            try:
                num = int(m.group(1))
            except ValueError:
                continue

            if num in common_numbers or num > 10000:
                continue

            # Check if number is part of a const/let/var/UPPER_CASE declaration
            if 'const ' in stripped or 'let ' in stripped or 'var ' in stripped:
                continue

            # Python: skip UPPER_CASE constant assignments
            if ext == '.py' and re.match(r'^\s*[A-Z_][A-Z0-9_]*\s*=', stripped):
                continue

            # Check if it's in an array literal or object/dict (likely config)
            if stripped.startswith('[') or stripped.startswith('{'):
                continue

            # Python: skip if number is in a dict literal context (key: value)
            if ext == '.py' and ':' in stripped and not stripped.startswith('if ') and not stripped.startswith('elif '):
                # Could be dict literal {key: 42} or type annotation
                if re.search(r'[:=]\s*\d+', stripped):
                    # Check if it's a variable assignment like x: int = 42
                    if re.match(r'^\s*\w+\s*:\s*\w+\s*=\s*', stripped):
                        continue

            smells.append({
                "file": rel_path,
                "line": i + 1,
                "value": num,
                "type": "magic_number",
                "severity": "info",
                "message": f"Magic number {num} found without explanation",
                "suggestion": f"Extract into a named constant (e.g., MAX_RETRIES = {num})"
            })
            break  # One per line is enough

        # v6.5: Cap magic_values per file for C/C++ to prevent noise
        if is_c_cpp and len(smells) >= C_CPP_MAX_FINDINGS_PER_FILE:
            break

    return smells


def _detect_complex_conditionals(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect overly complex conditional expressions."""
    smells = []
    lines = content.split('\n')
    is_c_cpp = ext in {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}

    # v6.5: Skip test files — test conditionals are expected to be complex
    if _is_test_or_mock_file(rel_path):
        return smells

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments and preprocessor directives
        if stripped.startswith('//') or stripped.startswith('#'):
            continue

        # v6.5: For C/C++, skip #if defined() / #ifdef chains — preprocessor
        # conditionals with || / && are platform detection, not code complexity.
        if is_c_cpp and stripped.startswith('#'):
            continue

        # Count &&, || operators in a single line
        and_count = stripped.count('&&') + stripped.count(' and ')
        or_count = stripped.count('||') + stripped.count(' or ')
        total_ops = and_count + or_count

        # v6.5: For C/C++, use higher threshold (3+ operators is common in
        # error-checking chains: if (rc == NGX_OK && ptr != NULL && ...)
        cc_threshold = 5 if is_c_cpp else 3
        cc_critical = 7 if is_c_cpp else 5

        if total_ops >= cc_critical:
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "operator_count": total_ops,
                "severity": "critical",
                "message": f"Complex conditional with {total_ops} logical operators",
                "suggestion": "Extract sub-conditions into named boolean variables."
            })
        elif total_ops >= cc_threshold:
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "operator_count": total_ops,
                "severity": "warning",
                "message": f"Conditional with {total_ops} logical operators",
                "suggestion": "Consider simplifying with guard clauses or extracted methods."
            })

        # v6.5: Cap findings per file for C/C++
        if is_c_cpp and len(smells) >= C_CPP_MAX_FINDINGS_PER_FILE:
            break

    return smells


def _detect_god_objects(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect god objects (classes/modules with too many methods)."""
    smells = []

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # v6.3: Count class methods using brace-depth tracking (like Rust impl blocks).
        # Previous regex counted ALL function-like patterns in the entire file,
        # causing 10-30x inflation on files with many top-level functions.
        # Now we only count methods inside actual class body blocks.
        lines = content.split('\n')
        class_blocks = []  # list of (class_name, method_count)
        in_class = False
        class_name = ""
        class_start_depth = 0
        method_count = 0
        brace_depth = 0

        for line in lines:
            stripped = line.strip()

            # Track brace depth
            for ch in stripped:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1

            # Detect class start: class Foo { or class Foo extends Bar {
            class_match = re.match(
                r'(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)',
                stripped
            )
            if class_match:
                # If we were already inside a class, save it before starting a new one
                if in_class and method_count >= GOD_CLASS_METHODS:
                    class_blocks.append((class_name, method_count))

                in_class = True
                class_name = class_match.group(1)
                class_start_depth = brace_depth  # will be incremented when { is found
                method_count = 0
                continue

            if in_class:
                # Count method-like patterns inside the class body
                # Matches: method(), async method(), private method(), static method(), get/set accessor()
                if re.match(
                    r'(?:readonly\s+)?(?:abstract\s+)?(?:private|public|protected|static)\s+(?:override\s+)?(?:async\s+)?(?:get|set\s+)?\w+\s*(?:<[^>]*>)?\s*\(',
                    stripped
                ) or re.match(
                    r'(?:async\s+)?(?:get|set)\s+\w+\s*\(',
                    stripped
                ):
                    method_count += 1

                # End class block when brace depth returns to start level
                if brace_depth < class_start_depth:
                    in_class = False
                    if method_count >= GOD_CLASS_METHODS:
                        class_blocks.append((class_name, method_count))

        # Handle class still open at end of file
        if in_class and method_count >= GOD_CLASS_METHODS:
            class_blocks.append((class_name, method_count))

        for name, count in class_blocks:
            if count >= GOD_CLASS_METHODS_CRITICAL:
                smells.append({
                    "file": rel_path,
                    "class": name,
                    "method_count": count,
                    "severity": "critical",
                    "message": f"Class '{name}' has {count} methods (critical threshold: {GOD_CLASS_METHODS_CRITICAL})",
                    "suggestion": "Split into smaller, focused classes following Single Responsibility Principle."
                })
            elif count >= GOD_CLASS_METHODS:
                smells.append({
                    "file": rel_path,
                    "class": name,
                    "method_count": count,
                    "severity": "warning",
                    "message": f"Class '{name}' has {count} methods (threshold: {GOD_CLASS_METHODS})",
                    "suggestion": "Consider extracting some methods into a separate class."
                })

    elif ext == ".py":
        # Count class methods in Python with proper scoping
        lines = content.split('\n')
        class_starts = []  # (line_idx, class_name, indent_level)
        for i, line in enumerate(lines):
            m = re.match(r'^(\s*)class\s+(\w+)', line)
            if m:
                class_starts.append((i, m.group(2), len(m.group(1))))
        
        for start_idx, class_name, class_indent in class_starts:
            method_count = 0
            for i in range(start_idx + 1, len(lines)):
                line = lines[i]
                if not line.strip():
                    continue
                # Get current line indent
                stripped = line.lstrip()
                current_indent = len(line) - len(stripped)
                # If we've dedented past the class level, we're out of the class
                if current_indent <= class_indent and stripped:
                    break
                # Count methods (def at one indent level deeper than class)
                if current_indent > class_indent and re.match(r'\s+def\s+\w+', line):
                    method_count += 1
            
            if method_count >= GOD_CLASS_METHODS_CRITICAL:
                smells.append({
                    "file": rel_path,
                    "class": class_name,
                    "method_count": method_count,
                    "severity": "critical",
                    "message": f"Class '{class_name}' has {method_count} methods",
                    "suggestion": "Split into smaller, focused classes."
                })
            elif method_count >= GOD_CLASS_METHODS:
                smells.append({
                    "file": rel_path,
                    "class": class_name,
                    "method_count": method_count,
                    "severity": "warning",
                    "message": f"Class '{class_name}' has {method_count} methods",
                    "suggestion": "Consider extracting some methods."
                })

    elif ext == ".rs":
        # Count impl methods — only count fn inside impl blocks using brace-depth tracking
        # This avoids counting top-level functions, test functions, etc.
        lines = content.split('\n')
        impl_blocks = []  # list of (impl_name, method_count)
        in_impl = False
        impl_name = ""
        impl_start_depth = 0
        brace_depth = 0

        for line in lines:
            stripped = line.strip()

            # Track brace depth
            for ch in stripped:
                if ch == '{':
                    brace_depth += 1
                elif ch == '}':
                    brace_depth -= 1

            # Detect impl block start
            impl_match = re.match(r'impl\s+(?:<[^>]+>\s*)?(?:(?:\w+)\s+for\s+)?(\w+)', stripped)
            if impl_match and '{' in stripped:
                in_impl = True
                impl_name = impl_match.group(1)
                impl_start_depth = brace_depth
                impl_method_count = 0
                continue
            elif impl_match:
                # impl without opening brace on same line (rare)
                in_impl = True
                impl_name = impl_match.group(1)
                impl_start_depth = brace_depth + 1  # brace will be on next line
                impl_method_count = 0
                continue

            if in_impl:
                # Count fn inside impl block
                if re.match(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+', stripped):
                    impl_method_count += 1

                # End impl block when brace depth returns to start level
                if brace_depth < impl_start_depth:
                    in_impl = False
                    if impl_method_count >= RUST_GOD_IMPL_METHODS:
                        impl_blocks.append((impl_name, impl_method_count))

        for name, count in impl_blocks:
            if count >= RUST_GOD_IMPL_METHODS_CRITICAL:
                smells.append({
                    "file": rel_path,
                    "impl_for": name,
                    "method_count": count,
                    "severity": "critical",
                    "message": f"Impl block for '{name}' has {count} methods",
                    "suggestion": "Split into multiple impl blocks or traits. Consider grouping related methods into separate modules or using extension traits."
                })
            elif count >= RUST_GOD_IMPL_METHODS:
                smells.append({
                    "file": rel_path,
                    "impl_for": name,
                    "method_count": count,
                    "severity": "warning",
                    "message": f"Impl block for '{name}' has {count} methods",
                    "suggestion": "Consider extracting some methods into separate traits or helper modules."
                })

    return smells


def _detect_duplicate_patterns(workspace: str) -> List[Dict]:
    """Detect potential duplicate code patterns across files (lightweight)."""
    smells = []

    # Collect function signatures across files
    fn_signatures: Dict[str, List[Dict]] = defaultdict(list)

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

            # Skip minified files
            if '.min.' in filename:
                continue

            # Skip files exceeding size cap
            try:
                if os.path.getsize(file_path) > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            content = safe_read_file(file_path, max_size=MAX_FILE_SIZE)
            if content is None:
                continue

            # Extract function bodies (first line only as signature)
            for m in re.finditer(
                r'(?:function\s+\w+|const\s+\w+\s*=\s*(?:async\s+)?\(|def\s+\w+|(?:pub\s+)?fn\s+\w+)\s*\([^)]*\)',
                content
            ):
                sig = m.group(0).strip()
                # Normalize signature for comparison
                normalized = re.sub(r'\s+', ' ', sig)
                line_num = content[:m.start()].count('\n') + 1
                fn_signatures[normalized].append({
                    "file": rel_path,
                    "line": line_num,
                    "signature": sig
                })

    # Find signatures that appear in multiple files
    for sig, locations in fn_signatures.items():
        unique_files = set(loc["file"] for loc in locations)
        if len(unique_files) >= 3:
            smells.append({
                "files": list(unique_files),
                "occurrences": len(locations),
                "signature": sig,
                "severity": "warning" if len(unique_files) >= 5 else "info",
                "message": f"Similar function signature found in {len(unique_files)} files",
                "suggestion": "Extract into a shared utility module."
            })

    return smells[:30]  # Cap results


def _detect_inconsistent_patterns(workspace: str) -> List[Dict]:
    """Detect inconsistent coding patterns across the workspace."""
    smells = []

    # Track error handling patterns
    error_patterns = {
        "try_catch": 0,
        "promise_catch": 0,
        "result_type": 0,  # Rust-style
        "exception": 0,    # Python-style
    }

    # Track async patterns
    async_patterns = {
        "async_await": 0,
        "promise_then": 0,
        "callback": 0,
    }

    # Track export patterns
    export_patterns = {
        "es_module": 0,
        "commonjs": 0,
    }

    file_count = 0
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs"}:
                continue

            file_path = os.path.join(root, filename)

            # Skip minified files
            if '.min.' in filename:
                continue

            # Skip files exceeding size cap
            try:
                if os.path.getsize(file_path) > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue

            content = safe_read_file(file_path, max_size=MAX_FILE_SIZE)
            if content is None:
                continue

            file_count += 1

            # Error handling patterns
            if 'try' in content and 'catch' in content:
                error_patterns["try_catch"] += 1
            if '.catch(' in content:
                error_patterns["promise_catch"] += 1
            if 'Result<' in content or 'Ok(' in content:
                error_patterns["result_type"] += 1
            if 'try:' in content and 'except' in content:
                error_patterns["exception"] += 1

            # Async patterns
            if 'async ' in content or 'await ' in content:
                async_patterns["async_await"] += 1
            if '.then(' in content:
                async_patterns["promise_then"] += 1
            if re.search(r'function\s*\(\s*err', content):
                async_patterns["callback"] += 1

            # Export patterns
            if re.search(r'export\s+(default\s+)?', content):
                export_patterns["es_module"] += 1
            if 'module.exports' in content or 'require(' in content:
                export_patterns["commonjs"] += 1

    if file_count == 0:
        return smells

    # Check for inconsistency in error handling
    total_error = sum(error_patterns.values())
    if total_error > 3:
        dominant = max(error_patterns, key=error_patterns.get)
        for pattern, count in error_patterns.items():
            if pattern != dominant and count > 0 and count < total_error * 0.3:
                smells.append({
                    "type": "error_handling_inconsistency",
                    "severity": "warning",
                    "message": f"Mixed error handling: {pattern} ({count} files) vs {dominant} ({error_patterns[dominant]} files)",
                    "suggestion": f"Standardize on {dominant} pattern across the codebase."
                })

    # Check for async inconsistency
    total_async = sum(async_patterns.values())
    if total_async > 3:
        if async_patterns["async_await"] > 0 and async_patterns["promise_then"] > 0:
            smells.append({
                "type": "async_style_inconsistency",
                "severity": "info",
                "message": f"Mixed async styles: async/await ({async_patterns['async_await']}) vs .then() ({async_patterns['promise_then']})",
                "suggestion": "Prefer async/await for consistency."
            })

    # Check for module system inconsistency
    if export_patterns["es_module"] > 0 and export_patterns["commonjs"] > 0:
        smells.append({
            "type": "module_system_inconsistency",
            "severity": "warning",
            "message": f"Mixed module systems: ES modules ({export_patterns['es_module']}) vs CommonJS ({export_patterns['commonjs']})",
            "suggestion": "Standardize on one module system (prefer ES modules)."
        })

    return smells


def _is_docs_or_example(rel_path: str) -> bool:
    """Check if a file path is in a documentation, examples, or test directory.

    These files are excluded from health score calculations since they
    are not production code and typically have different quality standards.
    Note: rel_path may start without a leading slash (e.g., "docs_src/foo.py"),
    so we check both "/dir/" (middle of path) and "dir/" (start of path).
    """
    # Normalize to have leading slash for consistent matching
    normalized = '/' + rel_path if not rel_path.startswith('/') else rel_path
    docs_indicators = [
        '/docs/', '/doc/', '/documentation/',
        '/examples/', '/example/', '/demos/', '/demo/',
        '/docs_src/', '/snippets/',
        '/tutorial/', '/tutorials/', '/guides/',
        '/tests/', '/test/', '/__tests__/', '/spec/',
        '/fixtures/', '/fixture/',
        '/migrations/',
        '/stories/', '/storybook/',  # v6.1: Storybook stories are not production code
    ]
    # Also match paths that START with these directory names
    # (no leading slash in rel_path, e.g., "tests/foo.py" or "docs_src/bar.py")
    start_indicators = [
        'docs/', 'doc/', 'documentation/',
        'examples/', 'example/', 'demos/', 'demo/',
        'docs_src/', 'snippets/',
        'tutorial/', 'tutorials/', 'guides/',
        'tests/', 'test/', '__tests__/', 'spec/',
        'fixtures/', 'fixture/',
        'migrations/',
        'stories/', 'storybook/',  # v6.1: Storybook stories are not production code
    ]
    return (any(indicator in normalized for indicator in docs_indicators) or
            any(rel_path.startswith(indicator) for indicator in start_indicators))


def _is_test_or_mock_file(rel_path: str) -> bool:
    """Check if a file is a test, mock, or fixture file.

    These files inherently have many methods (describe/it blocks, mock classes)
    and should not be flagged as god objects.
    """
    basename = os.path.basename(rel_path).lower()
    test_patterns = (
        '.test.', '.spec.', '.e2e.', '.e2e-spec.',
        '_test.', '_spec.', '.stories.',
    )
    mock_patterns = (
        'mock', 'stub', 'fake', 'fixture', 'dummy',
    )

    # Check file name patterns
    for pattern in test_patterns:
        if pattern in basename:
            return True

    # Check for mock/stub in filename
    for pattern in mock_patterns:
        if pattern in basename.lower():
            return True

    # Check path patterns
    normalized = '/' + rel_path if not rel_path.startswith('/') else rel_path
    test_dirs = [
        '/tests/', '/test/', '/__tests__/', '/spec/',
        '/fixtures/', '/fixture/', '/mocks/', '/mock/',
        '/e2e/', '/integration/',
    ]
    for d in test_dirs:
        if d in normalized:
            return True

    return False


# ─── New Smell Detectors (v3.1) ────────────────────────────────────

def _detect_mutable_defaults(content: str, rel_path: str) -> List[Dict]:
    """Detect mutable default arguments in Python functions.

    This is one of the most common Python bugs — mutable default arguments
    (list, dict, set) are shared across all calls, causing unexpected behavior.

    Catches:
    - def foo(x=[]): ...
    - def foo(x={}): ...
    - def foo(x=set()): ...
    - def foo(x=list()): ...
    - def foo(x=dict()): ...
    """
    smells = []
    lines = content.split('\n')

    # Pattern: function definition with mutable default argument
    # Matches: def func(param=[], param2={}, param3=set())
    mutable_default_pattern = re.compile(
        r'^\s*(?:async\s+)?def\s+\w+\s*\((.*?)\)\s*:',
        re.DOTALL
    )

    for i, line in enumerate(lines):
        # Quick pre-check for common mutable defaults
        if '=[]' not in line and '={}' not in line and '=set()' not in line \
                and '=list()' not in line and '=dict()' not in line:
            continue

        # Check if this is a function definition with mutable defaults
        m = re.match(r'^\s*(?:async\s+)?def\s+(\w+)\s*\((.*?)\)\s*(?:->.*?)?:', line)
        if not m:
            continue

        fn_name = m.group(1)
        params_str = m.group(2)

        # Parse parameters for mutable defaults
        mutable_types = {
            '[]': 'list',
            '{}': 'dict',
            'set()': 'set',
            'list()': 'list',
            'dict()': 'dict',
        }

        found_mutables = []
        for param in params_str.split(','):
            param = param.strip()
            for default_val, type_name in mutable_types.items():
                if f'={default_val}' in param:
                    # Extract parameter name
                    param_name = param.split('=')[0].strip().split(':')[
0].strip()
                    found_mutables.append((param_name, type_name))

        for param_name, type_name in found_mutables:
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "fn": fn_name,
                "param": param_name,
                "mutable_type": type_name,
                "severity": "critical",
                "message": f"Mutable default argument '{param_name}={type_name}()' in function '{fn_name}'",
                "suggestion": f"Use None as default and initialize inside the function: def {fn_name}({param_name}=None): if {param_name} is None: {param_name} = {type_name}()"
            })

    return smells


def _detect_sql_injection(content: str, rel_path: str) -> List[Dict]:
    """Detect potential SQL injection vulnerabilities in Python code.

    Catches:
    - f-string SQL queries: f"SELECT * FROM users WHERE id = {user_id}"
    - .format() SQL queries: "SELECT * FROM users WHERE id = {}".format(user_id)
    - % formatting SQL queries: "SELECT * FROM users WHERE id = '%s'" % user_id

    Does NOT flag:
    - Parameterized queries with placeholders (?, %s without % operator)
    - Static SQL strings without variable interpolation
    """
    smells = []
    lines = content.split('\n')

    # SQL keywords to detect SQL statements
    sql_keywords = re.compile(
        r'(?i)\b(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b'
    )

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments
        if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
            continue

        # Skip test files for severity reduction
        is_test = _is_test_or_mock_file(rel_path)

        # Check for f-string SQL injection
        # Pattern: f"SELECT ..." or f"INSERT ..." etc. with {variable} inside
        fstring_sql = re.findall(
            r'f["\'](.{0,200}(?:SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC).{0,200})["\']',
            stripped, re.IGNORECASE
        )
        for sql_str in fstring_sql:
            # Check if it contains variable interpolation
            if '{' in sql_str and '}' in sql_str:
                severity = "warning" if is_test else "critical"
                smells.append({
                    "file": rel_path,
                    "line": i + 1,
                    "pattern": "f-string_sql",
                    "severity": severity,
                    "message": f"Potential SQL injection: f-string used in SQL query",
                    "suggestion": "Use parameterized queries with placeholders (? or %s) instead of f-string interpolation."
                })
                break  # One finding per line is enough

        # Check for .format() SQL injection
        if '.format(' in stripped:
            # Find SQL strings followed by .format()
            format_sql = re.search(
                r'["\'](.{0,200}(?:SELECT|INSERT|UPDATE|DELETE|DROP).{0,200})["\']\s*\.format\(',
                stripped, re.IGNORECASE
            )
            if format_sql:
                severity = "warning" if is_test else "critical"
                smells.append({
                    "file": rel_path,
                    "line": i + 1,
                    "pattern": "format_sql",
                    "severity": severity,
                    "message": f"Potential SQL injection: .format() used in SQL query",
                    "suggestion": "Use parameterized queries with placeholders (? or %s) instead of .format()."
                })

        # Check for % formatting SQL injection
        # Pattern: "SELECT ... %s ..." % variable (but not just "SELECT ... %s" alone)
        pct_sql = re.search(
            r'["\'](.{0,200}(?:SELECT|INSERT|UPDATE|DELETE|DROP).{0,200})["\']\s*%\s*\(',
            stripped, re.IGNORECASE
        )
        if pct_sql:
            severity = "warning" if is_test else "critical"
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "pattern": "percent_format_sql",
                "severity": severity,
                "message": f"Potential SQL injection: % formatting used in SQL query",
                "suggestion": "Use parameterized queries with cursor.execute(query, params) instead of % string formatting."
            })

    return smells
