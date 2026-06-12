"""
Code Smell Detector for CodeLens — v3
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

Each smell gets a severity (info, warning, critical) and refactoring suggestion.
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, safe_read_file, is_generated_file


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte",
    ".php", ".go", ".java", ".cs", ".dart", ".lua",
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
        "complex_conditional", "duplicate_pattern", "inconsistent"
    }

    if categories:
        categories = [c for c in categories if c in valid_categories]
    else:
        categories = list(valid_categories)

    all_smells: Dict[str, List[Dict]] = {cat: [] for cat in valid_categories}
    files_scanned = 0
    production_files_scanned = 0

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

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            # Skip minified files
            if '.min.' in filename:
                continue

            # Skip generated files (generated/, vendor/, _pb2.py, etc.)
            if is_generated_file(rel_path):
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
    priority_order = ["god_object", "long_fn", "deep_nesting", "callback_hell",
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

    return {
        "status": "ok",
        "workspace": workspace,
        "health_score": health_score,  # v5.8: Also at top-level for easy access
        "stats": {
            "files_scanned": files_scanned,
            "total_smells": total_smells,
            "critical": critical_count,
            "warning": warning_count,
            "info": info_count,
            "health_score": health_score
        },
        "by_category": {
            cat: smells for cat, smells in all_smells.items() if smells
        },
        "top_priority": top_smells[:20],
        "categories_checked": list(categories)
    }


# ─── Individual Smell Detectors ────────────────────────────────

def _detect_long_functions(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect functions that are too long."""
    smells = []
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

    # Calculate function lengths
    for idx, (start, name) in enumerate(fn_starts):
        # Find end of function
        end = _find_function_end(lines, start, ext)
        length = end - start

        if length > LONG_FUNCTION_LINES_CRITICAL:
            smells.append({
                "file": rel_path,
                "line": start + 1,
                "fn": name,
                "length": length,
                "severity": "critical",
                "message": f"Function '{name}' is {length} lines (critical threshold: {LONG_FUNCTION_LINES_CRITICAL})",
                "suggestion": "Break into smaller functions. Each function should do one thing."
            })
        elif length > LONG_FUNCTION_LINES:
            smells.append({
                "file": rel_path,
                "line": start + 1,
                "fn": name,
                "length": length,
                "severity": "warning",
                "message": f"Function '{name}' is {length} lines (threshold: {LONG_FUNCTION_LINES})",
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
    skip_keywords = ['.test.', '.spec.', '.fixture.', '.stories.', '.story.', '__tests__']
    if any(kw in rel_path for kw in skip_keywords):
        return smells
    
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

        indent = len(line) - len(stripped)

        if ext == ".py":
            # Python: 4 spaces per level
            level = indent // 4
        elif ext == ".rs":
            # Rust: 4 spaces per level
            level = indent // 4
        else:
            # JS/TS: 2 spaces per level
            level = indent // 2

        # Detect when we first enter a deep nesting block
        if level >= DEEP_NESTING_LEVEL and not in_deep_block:
            in_deep_block = True
            deep_block_level = level
            deep_block_start = i + 1
        # Detect when we exit the deep nesting block (return to shallower level)
        elif in_deep_block and level < DEEP_NESTING_LEVEL:
            in_deep_block = False
            severity = "critical" if deep_block_level >= DEEP_NESTING_CRITICAL else "warning"
            threshold = DEEP_NESTING_CRITICAL if severity == "critical" else DEEP_NESTING_LEVEL
            smells.append({
                "file": rel_path,
                "line": deep_block_start,
                "nesting_level": deep_block_level,
                "severity": severity,
                "message": f"Code is nested {deep_block_level} levels deep (threshold: {threshold})",
                "suggestion": "Extract inner logic into separate functions. Use early returns."
            })
        
        # Track the deepest level within the block
        if in_deep_block and level > deep_block_level:
            deep_block_level = level

        prev_level = level

    # Handle case where file ends while still in a deep block
    if in_deep_block:
        severity = "critical" if deep_block_level >= DEEP_NESTING_CRITICAL else "warning"
        threshold = DEEP_NESTING_CRITICAL if severity == "critical" else DEEP_NESTING_LEVEL
        smells.append({
            "file": rel_path,
            "line": deep_block_start,
            "nesting_level": deep_block_level,
            "severity": severity,
            "message": f"Code is nested {deep_block_level} levels deep (threshold: {threshold})",
            "suggestion": "Extract inner logic into separate functions. Use early returns."
        })

    return smells


def _detect_many_params(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect functions with too many parameters."""
    smells = []

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
    """
    smells = []
    lines = content.split('\n')

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

    # Numbers that are likely NOT magic (common constants, HTTP codes, etc.)
    common_numbers = {
        0, 1, -1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 16, 20, 24, 30, 32, 36,
        48, 50, 60, 64, 100, 128, 200, 256, 300, 360, 500, 512, 1000, 1024,
        # HTTP status codes
        200, 201, 202, 204, 206, 301, 302, 304, 307, 308,
        400, 401, 403, 404, 405, 409, 422, 429, 500, 502, 503, 504,
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

    return smells


def _detect_complex_conditionals(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect overly complex conditional expressions."""
    smells = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Count &&, || operators in a single line
        and_count = stripped.count('&&') + stripped.count(' and ')
        or_count = stripped.count('||') + stripped.count(' or ')
        total_ops = and_count + or_count

        if total_ops >= 5:
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "operator_count": total_ops,
                "severity": "critical",
                "message": f"Complex conditional with {total_ops} logical operators",
                "suggestion": "Extract sub-conditions into named boolean variables."
            })
        elif total_ops >= 3:
            smells.append({
                "file": rel_path,
                "line": i + 1,
                "operator_count": total_ops,
                "severity": "warning",
                "message": f"Conditional with {total_ops} logical operators",
                "suggestion": "Consider simplifying with guard clauses or extracted methods."
            })

    return smells


def _detect_god_objects(content: str, ext: str, rel_path: str) -> List[Dict]:
    """Detect god objects (classes/modules with too many methods)."""
    smells = []

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Count class methods
        method_count = len(re.findall(r'(?:async\s+)?(?:private|public|protected|static)?\s*(?:get|set)?\s*\w+\s*\(', content))
        class_match = re.search(r'class\s+(\w+)', content)

        if class_match and method_count >= GOD_CLASS_METHODS_CRITICAL:
            smells.append({
                "file": rel_path,
                "class": class_match.group(1),
                "method_count": method_count,
                "severity": "critical",
                "message": f"Class '{class_match.group(1)}' has {method_count} methods (critical threshold: {GOD_CLASS_METHODS_CRITICAL})",
                "suggestion": "Split into smaller, focused classes following Single Responsibility Principle."
            })
        elif class_match and method_count >= GOD_CLASS_METHODS:
            smells.append({
                "file": rel_path,
                "class": class_match.group(1),
                "method_count": method_count,
                "severity": "warning",
                "message": f"Class '{class_match.group(1)}' has {method_count} methods (threshold: {GOD_CLASS_METHODS})",
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
                    if impl_method_count >= GOD_CLASS_METHODS:
                        impl_blocks.append((impl_name, impl_method_count))

        for name, count in impl_blocks:
            if count >= GOD_CLASS_METHODS_CRITICAL:
                smells.append({
                    "file": rel_path,
                    "impl_for": name,
                    "method_count": count,
                    "severity": "critical",
                    "message": f"Impl block for '{name}' has {count} methods",
                    "suggestion": "Split into multiple impl blocks or traits."
                })
            elif count >= GOD_CLASS_METHODS:
                smells.append({
                    "file": rel_path,
                    "impl_for": name,
                    "method_count": count,
                    "severity": "warning",
                    "message": f"Impl block for '{name}' has {count} methods",
                    "suggestion": "Consider extracting some methods into separate traits."
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

# _is_docs_or_example is defined above. Note: paths like "docs_src/foo.py"
# start without a leading slash, so we also match on path-starts-with.
