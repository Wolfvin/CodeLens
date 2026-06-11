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
import time
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS

# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte"
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

# Performance limits
MAX_FILE_SIZE = 200 * 1024  # 200KB — skip files larger than this
MAX_LINE_LENGTH = 500       # Lines longer than this indicate minified/bundled files
MAX_RESULTS_PER_CATEGORY = 100  # Cap results per category to avoid explosion
PER_FILE_TIMEOUT_SEC = 8    # Max seconds per file across all detectors

def detect_smells(
    workspace: str,
    categories: Optional[List[str]] = None,
    severity_filter: Optional[str] = None,
    config: Optional[Dict] = None
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
                file_size = os.path.getsize(file_path)
                if file_size > MAX_FILE_SIZE:
                    files_scanned += 1
                    continue
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            lines = content.split('\n')
            line_count = len(lines)

            # Skip minified/bundled files (very long lines = not human-written code)
            if line_count > 0 and line_count < 50:
                avg_line_len = len(content) / line_count
                if avg_line_len > MAX_LINE_LENGTH:
                    files_scanned += 1
                    continue

            # Skip files that are almost certainly auto-generated
            first_lines = '\n'.join(lines[:5]).lower()
            if any(marker in first_lines for marker in ['/*!', '/*!', 'minified', 'uglify', 'webpack', 'bundled']):
                files_scanned += 1
                continue

            files_scanned += 1
            file_start = time.monotonic()

            # Large file detection
            if "large_file" in categories and len(all_smells["large_file"]) < MAX_RESULTS_PER_CATEGORY:
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

            # Per-file timeout check before running expensive detectors
            if time.monotonic() - file_start > PER_FILE_TIMEOUT_SEC:
                continue

            # Long function detection
            if "long_fn" in categories and len(all_smells["long_fn"]) < MAX_RESULTS_PER_CATEGORY:
                fns = _detect_long_functions(content, ext, rel_path)
                all_smells["long_fn"].extend(fns)

            # Per-file timeout check
            if time.monotonic() - file_start > PER_FILE_TIMEOUT_SEC:
                continue

            # Deep nesting detection
            if "deep_nesting" in categories and len(all_smells["deep_nesting"]) < MAX_RESULTS_PER_CATEGORY:
                nested = _detect_deep_nesting(content, ext, rel_path)
                all_smells["deep_nesting"].extend(nested)

            # Too many parameters
            if "many_params" in categories and len(all_smells["many_params"]) < MAX_RESULTS_PER_CATEGORY:
                params = _detect_many_params(content, ext, rel_path)
                all_smells["many_params"].extend(params)

            # Callback hell
            if "callback_hell" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"} and len(all_smells["callback_hell"]) < MAX_RESULTS_PER_CATEGORY:
                cb = _detect_callback_hell(content, rel_path)
                all_smells["callback_hell"].extend(cb)

            # Magic values
            if "magic_values" in categories and len(all_smells["magic_values"]) < MAX_RESULTS_PER_CATEGORY:
                magic = _detect_magic_values(content, ext, rel_path)
                all_smells["magic_values"].extend(magic)

            # Complex conditionals
            if "complex_conditional" in categories and len(all_smells["complex_conditional"]) < MAX_RESULTS_PER_CATEGORY:
                conds = _detect_complex_conditionals(content, ext, rel_path)
                all_smells["complex_conditional"].extend(conds)

            # God object (classes/modules with too many methods)
            if "god_object" in categories and len(all_smells["god_object"]) < MAX_RESULTS_PER_CATEGORY:
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
    files_scanned_safe = max(files_scanned, 1)
    weighted_smells = critical_count * 3 + warning_count * 1 + info_count * 0.1
    density = weighted_smells / files_scanned_safe  # weighted smells per file

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

    # Critical penalty: based on critical count per file (capped)
    critical_per_file = critical_count / files_scanned_safe
    if critical_per_file <= 1:
        critical_penalty = 0
    elif critical_per_file <= 5:
        critical_penalty = 5
    elif critical_per_file <= 10:
        critical_penalty = 10
    elif critical_per_file <= 20:
        critical_penalty = 15
    else:
        critical_penalty = min(25, int(critical_per_file * 0.5))

    # Critical ratio adjustment: fewer criticals relative to total = healthier
    critical_ratio = critical_count / max(total_smells, 1)
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
        for m in re.finditer(
            r'(?:function\s+\w+|(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(|(?:async\s+)?\w+\s*\()\s*\(([^)]*)\)',
            content
        ):
            params_str = m.group(1).strip()
            if not params_str:
                continue
            # Count parameters (handle destructuring, rest params, default values)
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
    """Detect magic numbers and strings (unexplained constants)."""
    smells = []
    lines = content.split('\n')

    # Skip magic number detection entirely for config/framework config files
    config_file_keywords = [
        'config', 'eslint', 'prettier', 'vitest', 'jest',
        'playwright', 'postcss', 'next.config', 'tsconfig',
        '.fixture.', '.stories.', '.story.', '.test.', '.spec.',
    ]
    rel_lower = rel_path.lower()
    if any(kw in rel_lower for kw in config_file_keywords):
        return smells

    # Numbers that are likely magic (not 0, 1, -1, 2, or common HTTP codes)
    common_numbers = {0, 1, -1, 2, 3, 10, 100, 256, 1000, 200, 201, 204, 301, 302, 400, 401, 403, 404, 500, 502, 503}

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

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Skip comments, imports, and console/logs
        if stripped.startswith('//') or stripped.startswith('#') or stripped.startswith('import'):
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

        # Check for magic numbers
        for m in re.finditer(r'(?<![.\w])(\d+)(?![.\w])', stripped):
            try:
                num = int(m.group(1))
            except ValueError:
                continue

            if num in common_numbers or num > 10000:
                continue

            # Check if number is part of a const/let/var declaration
            if 'const ' in stripped or 'let ' in stripped or 'var ' in stripped:
                continue

            # Check if it's in an array literal or object (likely config)
            if stripped.startswith('[') or stripped.startswith('{'):
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
        # Count impl methods
        impl_match = re.search(r'impl\s+(?:<[^>]+>\s*)?(\w+)', content)
        method_count = len(re.findall(r'\s*(?:pub\s+)?(?:async\s+)?fn\s+\w+', content))

        if impl_match and method_count >= GOD_CLASS_METHODS_CRITICAL:
            smells.append({
                "file": rel_path,
                "impl_for": impl_match.group(1),
                "method_count": method_count,
                "severity": "critical",
                "message": f"Impl block for '{impl_match.group(1)}' has {method_count} methods",
                "suggestion": "Split into multiple impl blocks or traits."
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

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
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

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
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
