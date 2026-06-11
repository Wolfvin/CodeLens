"""
Debug Leak Detector for CodeLens — v3
Detects leftover debug code that shouldn't be in production — console.log, print(),
debugger statements, TODO/FIXME/HACK markers, commented-out code blocks, test skips,
mock data in non-test files, and dev-only guards.

Categories:
1. console_log   — console.log/warn/error/debug/info (except console.error in catch blocks)
2. print_statement — print(), pprint(), echo, fmt.Println, println!
3. debugger      — debugger; breakpoint(), pdb.set_trace(), debug! macro
4. todo_fixme    — TODO, FIXME, HACK, XXX, TEMP, BODGE comments
5. commented_code — 3+ consecutive commented lines that look like code
6. test_skip     — .skip(), xit(), xdescribe(), @pytest.mark.skip, @skip, #[ignore]
7. mock_data     — Hardcoded test data in non-test files (fakeData, mockUser, testXYZ)
8. dev_only      — if (DEBUG), if (process.env.NODE_ENV !== 'production'), #ifdef DEBUG

Each finding includes: category, file, line, match, severity, should_remove flag.
"""

import os
import re
from typing import Dict, List, Any, Optional
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".vue", ".svelte", ".go", ".rb",
}

# Test-file patterns — findings in these files are downgraded
TEST_FILE_PATTERNS = {
    ".test.", ".spec.", "_test.", "_spec.",
    "__tests__", "/tests/", "/test/",
    "test_", "spec_", "_test.py", "_test.rs",
}

# Performance limits for large codebases
MAX_FILES_PER_RUN = 3000


# ─── Category-specific Patterns ────────────────────────────────

CONSOLE_PATTERNS = [
    (r'\bconsole\.log\s*\(', "console.log"),
    (r'\bconsole\.warn\s*\(', "console.warn"),
    (r'\bconsole\.debug\s*\(', "console.debug"),
    (r'\bconsole\.info\s*\(', "console.info"),
    (r'\bconsole\.error\s*\(', "console.error"),  # checked for catch context later
]

PRINT_PATTERNS = [
    (r'\bprint\s*\([^)]*\)', "print()"),
    (r'\bpprint\.pprint\s*\(', "pprint.pprint()"),
    (r'\bpprint\s*\(', "pprint()"),
    (r'\becho\s*\(', "echo()"),
    (r'\bfmt\.Println\s*\(', "fmt.Println()"),
    (r'\bfmt\.Printf\s*\(', "fmt.Printf()"),
    (r'\bprintln!\s*\(', "println!()"),
    (r'\beprintln!\s*\(', "eprintln!()"),
    (r'\blog\.Debug\s*\(', "log.Debug()"),
    (r'\blog\.Info\s*\(', "log.Info()"),
]

DEBUGGER_PATTERNS = [
    (r'\bdebugger\s*;?', "debugger"),
    (r'\bbreakpoint\s*\(\s*\)', "breakpoint()"),
    (r'\bpdb\.set_trace\s*\(\s*\)', "pdb.set_trace()"),
    (r'\bpdb\s*\(\s*\)', "pdb()"),
    (r'\bipdb\s*\(\s*\)', "ipdb()"),
    (r'\bdebug!\s*\(', "debug!()"),
    (r'\bdbg!\s*\(', "dbg!()"),
    (r'\btrap\s*\(\s*\)', "trap()"),        # Delphi / old JS
    (r'\bdebugger;\s*//', "debugger with comment"),
    (r'\bnode\s+--inspect\b', "node --inspect"),
]

TODO_FIXME_PATTERNS = [
    (r'\bTODO\b', "TODO"),
    (r'\bFIXME\b', "FIXME"),
    (r'\bHACK\b', "HACK"),
    (r'\bXXX\b', "XXX"),
    (r'\bTEMP\b', "TEMP"),
    (r'\bBODGE\b', "BODGE"),
    (r'\bWORKAROUND\b', "WORKAROUND"),
    (r'\bKLUDGE\b', "KLUDGE"),
]

TEST_SKIP_PATTERNS = [
    (r'\.skip\s*\(', ".skip()"),
    (r'\bxit\s*\(', "xit()"),
    (r'\bxdescribe\s*\(', "xdescribe()"),
    (r'\bxit\s*\(', "xit()"),
    (r'@pytest\.mark\.skip', "@pytest.mark.skip"),
    (r'@pytest\.mark\.xfail', "@pytest.mark.xfail"),
    (r'@skip\b', "@skip"),
    (r'@Ignore\b', "@Ignore"),
    (r'#\[ignore\]', "#[ignore]"),
    (r'\.pend\s*\(', ".pend()"),
    (r'\.todo\s*\(', ".todo()"),
]

MOCK_DATA_PATTERNS = [
    (r'\bfakeData\b', "fakeData"),
    (r'\bfake[A-Z]\w+', "fakeCamelCase"),
    (r'\bmockData\b', "mockData"),
    (r'\bmock[A-Z]\w+', "mockCamelCase"),
    (r'\btestData\b', "testData"),
    (r'\btest[A-Z]\w+', "testCamelCase"),
    (r'\bstubData\b', "stubData"),
    (r'\bstub[A-Z]\w+', "stubCamelCase"),
    (r'\bfixtureData\b', "fixtureData"),
    (r'\bdummyData\b', "dummyData"),
    (r'\bdummy[A-Z]\w+', "dummyCamelCase"),
    (r'\bplaceholderData\b', "placeholderData"),
    (r'\bsampleData\b', "sampleData"),
    (r'\bMOCK_\w+', "MOCK_CONSTANT"),
    (r'\bFAKE_\w+', "FAKE_CONSTANT"),
    (r'\bTEST_\w+', "TEST_CONSTANT"),
]

DEV_ONLY_PATTERNS = [
    (r'\bif\s*\(\s*DEBUG\s*\)', "if (DEBUG)"),
    (r'\bif\s*\(\s*process\.env\.NODE_ENV\s*!==?\s*["\']production["\']\s*\)', "NODE_ENV check"),
    (r'\bif\s*\(\s*process\.env\.NODE_ENV\s*===?\s*["\']development["\']\s*\)', "NODE_ENV development"),
    (r'#ifdef\s+DEBUG\b', "#ifdef DEBUG"),
    (r'#if\s+DEBUG\b', "#if DEBUG"),
    (r'\bisDebug\b', "isDebug"),
    (r'\bisDev\b', "isDev"),
    (r'\b__DEV__\b', "__DEV__"),
    (r'\bDEBUG\b\s*===?\s*true', "DEBUG === true"),
    (r'\bprocess\.env\.DEBUG\b', "process.env.DEBUG"),
    (r'\bcfg\.Debug\b', "cfg.Debug"),
    (r'\bdebug_mode\b', "debug_mode"),
    (r'\bDEV_MODE\b', "DEV_MODE"),
]


# ─── Main Entry Point ──────────────────────────────────────────

def detect_debug_leaks(
    workspace: str,
    category: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = MAX_FILES_PER_RUN
) -> Dict[str, Any]:
    """
    Detect leftover debug code that shouldn't be in production.

    Args:
        workspace: Absolute path to workspace root
        category: Optional category filter — one of:
                  console_log, print_statement, debugger, todo_fixme,
                  commented_code, test_skip, mock_data, dev_only
        config: CodeLens configuration dict

    Returns:
        Dict with status, stats, leaks list, cleanup priority, and recommendations
    """
    workspace = os.path.abspath(workspace)

    valid_categories = {
        "console_log", "print_statement", "debugger", "todo_fixme",
        "commented_code", "test_skip", "mock_data", "dev_only"
    }

    if category:
        if category not in valid_categories:
            return {
                "status": "error",
                "message": f"Invalid category '{category}'. Valid: {sorted(valid_categories)}"
            }
        categories = {category}
    else:
        categories = valid_categories

    leaks: List[Dict] = []
    files_scanned = 0
    truncated = False

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

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1
            is_test_file = any(p in rel_path for p in TEST_FILE_PATTERNS)
            lines = content.split('\n')

            # ─── console_log ──────────────────────────────
            if "console_log" in categories and ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}:
                _detect_console_logs(lines, rel_path, is_test_file, leaks)

            # ─── print_statement ──────────────────────────
            if "print_statement" in categories:
                _detect_print_statements(lines, rel_path, ext, is_test_file, leaks)

            # ─── debugger ─────────────────────────────────
            if "debugger" in categories:
                _detect_debugger_statements(lines, rel_path, ext, is_test_file, leaks)

            # ─── todo_fixme ───────────────────────────────
            if "todo_fixme" in categories:
                _detect_todo_fixme(lines, rel_path, is_test_file, leaks)

            # ─── commented_code ───────────────────────────
            if "commented_code" in categories:
                _detect_commented_code(lines, rel_path, ext, is_test_file, leaks)

            # ─── test_skip ────────────────────────────────
            if "test_skip" in categories:
                _detect_test_skips(lines, rel_path, ext, is_test_file, leaks)

            # ─── mock_data ────────────────────────────────
            if "mock_data" in categories:
                _detect_mock_data(lines, rel_path, ext, is_test_file, leaks)

            # ─── dev_only ─────────────────────────────────
            if "dev_only" in categories:
                _detect_dev_only(lines, rel_path, ext, is_test_file, leaks)

        if truncated:
            break

    # ─── Aggregate Stats ──────────────────────────────────
    by_category = defaultdict(int)
    by_severity = defaultdict(int)
    for leak in leaks:
        by_category[leak["category"]] += 1
        by_severity[leak["severity"]] += 1

    # ─── Cleanup Priority ─────────────────────────────────
    severity_order = {"high": 0, "medium": 1, "low": 2}
    cleanup_priority = sorted(
        leaks,
        key=lambda x: (severity_order.get(x["severity"], 3), x["file"], x["line"])
    )

    # ─── Recommendations ──────────────────────────────────
    recommendations = _generate_recommendations(leaks, by_category, by_severity)

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_leaks": len(leaks),
            "files_scanned": files_scanned,
            "by_category": dict(by_category),
            "by_severity": dict(by_severity),
            "truncated": truncated
        },
        "leaks": leaks,
        "cleanup_priority": cleanup_priority[:50],
        "recommendations": recommendations,
    }


# ─── Category Detectors ────────────────────────────────────────

def _detect_console_logs(
    lines: List[str], rel_path: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect console.log/warn/error/debug/info statements."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comment-only lines
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue

        for pattern, label in CONSOLE_PATTERNS:
            m = re.search(pattern, stripped)
            if not m:
                continue

            # console.error in catch blocks is legitimate
            if label == "console.error":
                # Check surrounding context for catch
                context_start = max(0, i - 3)
                context = '\n'.join(lines[context_start:i + 1])
                if re.search(r'\bcatch\s*\(', context):
                    continue
                # Also skip if it's in a dedicated error-handling utility
                if re.search(r'(logError|handleError|reportError|onError)', context):
                    continue
                # console.error is typically legitimate error logging, not a debug leak
                # Only flag as info severity and don't suggest removal
                severity = "info"
                should_remove = False

            # console.warn in catch blocks is also somewhat legitimate
            elif label == "console.warn":
                context_start = max(0, i - 2)
                context = '\n'.join(lines[context_start:i + 1])
                if re.search(r'\bcatch\s*\(', context):
                    continue
                # console.warn is typically legitimate warning logging, not a debug leak
                # Only flag as info severity
                severity = "info"
                should_remove = False

            else:
                severity = "medium"
                should_remove = True

            # In test files, console.log is less severe
            if is_test_file:
                severity = "low"
                should_remove = False

            leaks.append({
                "category": "console_log",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break  # One match per line


def _detect_print_statements(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect print(), pprint(), echo, fmt.Println, println! statements."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comment-only lines and string-only lines
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue

        for pattern, label in PRINT_PATTERNS:
            # Filter by language relevance
            if label in ("fmt.Println()", "fmt.Printf()") and ext not in {".go"}:
                continue
            if label in ("println!()", "eprintln!()") and ext not in {".rs"}:
                continue
            if label in ("print()", "pprint()", "pprint.pprint()") and ext not in {".py", ".rs"}:
                continue

            m = re.search(pattern, stripped)
            if not m:
                continue

            # In Python, skip if it's inside __main__ block or a CLI entry point
            if ext == ".py":
                context_start = max(0, i - 5)
                context = '\n'.join(lines[context_start:i + 1])
                if '__main__' in context and 'if __name__' in context:
                    continue

            # Rust: println!/eprintln! are standard output mechanisms, not debug leaks.
            # Only flag them if they're in test functions or contain debug patterns.
            # In production Rust code, println! is the equivalent of console.log in Node.js
            # CLI apps, and eprintln! is for stderr output — neither is a debug leak.
            if ext == ".rs" and label in ("println!()", "eprintln!()"):
                # Check if inside a test function
                context_start = max(0, i - 15)
                context = '\n'.join(lines[context_start:i + 1])
                is_in_test = bool(re.search(r'#\[test\]|#\[tokio::test\]|fn test_|fn it_', context))
                # Check if the line contains debug-specific patterns
                has_debug_pattern = bool(re.search(
                    r'\bdbg!\(|debug|todo|fixme|FIXME|TODO|hack|HACK|TEMP|temp\b',
                    stripped, re.IGNORECASE
                ))
                if not is_in_test and not has_debug_pattern:
                    continue  # Standard Rust output, not a debug leak

            severity = "medium"
            should_remove = True

            if is_test_file:
                severity = "low"
                should_remove = False

            leaks.append({
                "category": "print_statement",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


def _detect_debugger_statements(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect debugger; breakpoint(); pdb.set_trace(); debug! macro."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue

        for pattern, label in DEBUGGER_PATTERNS:
            # Language filter
            if label in ("debug!()", "dbg!()") and ext not in {".rs"}:
                continue
            if label in ("pdb.set_trace()", "pdb()", "ipdb()", "breakpoint()") and ext not in {".py"}:
                continue
            if label == "debugger" and ext not in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}:
                continue

            m = re.search(pattern, stripped)
            if not m:
                continue

            severity = "high"
            should_remove = True

            leaks.append({
                "category": "debugger",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


def _detect_todo_fixme(
    lines: List[str], rel_path: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect TODO, FIXME, HACK, XXX, TEMP, BODGE comments."""
    for i, line in enumerate(lines):
        stripped = line.strip()

        for pattern, label in TODO_FIXME_PATTERNS:
            m = re.search(pattern, stripped, re.IGNORECASE)
            if not m:
                continue

            # Only count if it's in a comment context
            # (TODOs in code identifiers are not meaningful)
            is_comment = (
                stripped.startswith('//') or
                stripped.startswith('*') or
                stripped.startswith('#') or
                stripped.startswith('/*') or
                stripped.startswith('<!--') or
                '//' in stripped[:stripped.upper().find(label)] or
                '#' in stripped[:stripped.upper().find(label)]
            )
            if not is_comment and not _is_in_string(stripped, label):
                # Also check if the line itself is a comment (shebang, docstring)
                if not (stripped.startswith('"""') or stripped.startswith("'''")):
                    continue

            # Severity varies by marker
            severity_map = {
                "FIXME": "medium",
                "HACK": "medium",
                "XXX": "medium",
                "BODGE": "medium",
                "TODO": "low",
                "TEMP": "low",
                "WORKAROUND": "low",
                "KLUDGE": "low",
            }
            severity = severity_map.get(label, "low")

            should_remove = label in {"HACK", "BODGE", "TEMP", "WORKAROUND", "KLUDGE"}

            if is_test_file:
                should_remove = False

            leaks.append({
                "category": "todo_fixme",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


def _detect_commented_code(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect 3+ consecutive commented lines that look like code."""
    comment_prefix = _get_comment_prefix(ext)
    if not comment_prefix:
        return

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        # Check if this is a comment line
        if not stripped.startswith(comment_prefix):
            i += 1
            continue

        # Count consecutive commented lines
        block_start = i
        while i < len(lines) and lines[i].strip().startswith(comment_prefix):
            i += 1
        block_end = i

        # Need at least 3 consecutive commented lines
        if block_end - block_start < 3:
            continue

        # Check if the block looks like code
        comment_lines = []
        for j in range(block_start, block_end):
            line_content = lines[j].strip()[len(comment_prefix):].strip()
            comment_lines.append(line_content)

        code_score = _score_commented_code_likelihood(comment_lines, ext)

        if code_score >= 2:
            severity = "low"
            should_remove = True

            if is_test_file:
                should_remove = False

            leaks.append({
                "category": "commented_code",
                "file": rel_path,
                "line": block_start + 1,
                "match": f"{block_end - block_start} commented lines (code score: {code_score})",
                "severity": severity,
                "should_remove": should_remove,
            })


def _detect_test_skips(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect test skip markers (.skip, xit, @pytest.mark.skip, #[ignore])."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            # But #[ignore] IS a comment-style annotation in Rust
            if '#[ignore]' not in stripped:
                continue

        for pattern, label in TEST_SKIP_PATTERNS:
            # Language filter
            if label in ("@pytest.mark.skip", "@pytest.mark.xfail", "@skip") and ext != ".py":
                continue
            if label == "#[ignore]" and ext != ".rs":
                continue
            if label in (".skip()", ".pend()", ".todo()") and ext not in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}:
                continue

            m = re.search(pattern, stripped)
            if not m:
                continue

            # .skip() and .todo() can be legitimate in tests
            # Only flag if it's in a non-test file or there are too many
            severity = "high" if not is_test_file else "medium"
            should_remove = not is_test_file

            leaks.append({
                "category": "test_skip",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


def _detect_mock_data(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect hardcoded test data in non-test files."""
    if is_test_file:
        return  # Mock data is expected in test files

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            continue

        for pattern, label in MOCK_DATA_PATTERNS:
            # Skip constants that are just ALL_CAPS naming
            if label in ("MOCK_CONSTANT", "FAKE_CONSTANT", "TEST_CONSTANT"):
                # Only flag if it's assigned an object literal or array
                if '=' not in stripped and ':' not in stripped:
                    continue

            m = re.search(pattern, stripped)
            if not m:
                continue

            # Additional check: is this actually an assignment/declaration?
            # We want to avoid flagging function parameters like `mockData` in tests
            # that were imported. Since this is a non-test file, we flag assignments.
            is_assignment = (
                '=' in stripped or
                ':' in stripped or
                'const ' in stripped or
                'let ' in stripped or
                'var ' in stripped or
                (ext == ".py" and ' = ' in stripped)
            )

            severity = "medium" if is_assignment else "low"
            should_remove = is_assignment

            leaks.append({
                "category": "mock_data",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


def _detect_dev_only(
    lines: List[str], rel_path: str, ext: str, is_test_file: bool, leaks: List[Dict]
) -> None:
    """Detect dev-only guards and debug conditionals."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('#'):
            # But #ifdef is a comment-style preprocessor directive
            if '#ifdef' not in stripped and '#if' not in stripped:
                continue

        for pattern, label in DEV_ONLY_PATTERNS:
            m = re.search(pattern, stripped)
            if not m:
                continue

            severity = "medium"
            should_remove = False  # Dev guards are often intentional

            # Some dev-only checks are legitimate (feature flags)
            # But hardcoded DEBUG checks in production code are suspect
            if label in ("if (DEBUG)", "#ifdef DEBUG", "DEBUG === true", "debug_mode"):
                should_remove = True
                severity = "medium"

            leaks.append({
                "category": "dev_only",
                "file": rel_path,
                "line": i + 1,
                "match": label,
                "severity": severity,
                "should_remove": should_remove,
            })
            break


# ─── Helpers ───────────────────────────────────────────────────

def _get_comment_prefix(ext: str) -> str:
    """Get the line comment prefix for a file type."""
    prefixes = {
        ".js": "//", ".mjs": "//", ".cjs": "//",
        ".ts": "//", ".tsx": "//", ".jsx": "//",
        ".py": "#", ".rs": "//", ".go": "//",
        ".rb": "#", ".vue": "//", ".svelte": "//",
    }
    return prefixes.get(ext, "")


def _is_in_string(line: str, marker: str) -> bool:
    """Heuristic: check if a marker appears inside a string literal."""
    idx = line.upper().find(marker)
    if idx < 0:
        return False
    # Count quotes before the marker
    before = line[:idx]
    single_count = before.count("'") - before.count("\\'")
    double_count = before.count('"') - before.count('\\"')
    return (single_count % 2 == 1) or (double_count % 2 == 1)


def _score_commented_code_likelihood(comment_lines: List[str], ext: str) -> int:
    """
    Score how likely a block of commented lines is actually commented-out code.
    Returns 0-5+ score; 2+ is considered likely code.
    """
    score = 0

    # Patterns that strongly indicate code
    code_indicators_js = [
        r'(?:const|let|var|function|class|import|export|return|if|else|for|while|switch|try|catch)\s',
        r'[{}();]',
        r'=>',
        r'\w+\.\w+\(',
        r'\w+\s*=\s*',
        r'console\.\w+',
        r'await\s',
        r'new\s+\w+',
    ]
    code_indicators_py = [
        r'(?:def|class|import|from|return|if|elif|else|for|while|try|except|with|raise|yield)\s',
        r'[:()\[\]]',
        r'\w+\s*=\s*',
        r'\w+\.\w+\(',
        r'self\.\w+',
        r'print\s*\(',
    ]
    code_indicators_rs = [
        r'(?:fn|let|mut|pub|impl|use|mod|struct|enum|trait|return|if|else|for|while|match|loop)\s',
        r'[{}();]',
        r'->',
        r'::',
        r'\w+\.\w+\(',
    ]

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte"}:
        indicators = code_indicators_js
    elif ext == ".py":
        indicators = code_indicators_py
    elif ext == ".rs":
        indicators = code_indicators_rs
    else:
        indicators = code_indicators_js  # Default to JS-like

    for line in comment_lines:
        if not line:
            continue
        for indicator in indicators:
            if re.search(indicator, line):
                score += 1
                break  # One indicator per line max

    # Bonus: if block has consistent indentation (like code)
    indents = [len(line) - len(line.lstrip()) for line in comment_lines if line.strip()]
    if len(set(indents)) <= 2 and len(indents) >= 3:
        score += 1

    return score


def _generate_recommendations(
    leaks: List[Dict],
    by_category: Dict[str, int],
    by_severity: Dict[str, int]
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    high_count = by_severity.get("high", 0)
    if high_count > 0:
        recs.append(
            f"CRITICAL: {high_count} high-severity debug leaks found (debugger statements, "
            f"test skips in production). Remove these before deploying."
        )

    console_count = by_category.get("console_log", 0)
    if console_count > 5:
        recs.append(
            f"Found {console_count} console statements. Consider using a logging library "
            f"(e.g., winston, pino, structlog) that can be configured per environment."
        )
    elif console_count > 0:
        recs.append(
            f"Found {console_count} console statements. Remove or replace with proper logging."
        )

    debugger_count = by_category.get("debugger", 0)
    if debugger_count > 0:
        recs.append(
            f"Found {debugger_count} debugger/breakpoint statements. These WILL halt execution "
            f"in production. Remove immediately."
        )

    todo_count = by_category.get("todo_fixme", 0)
    if todo_count > 10:
        recs.append(
            f"Found {todo_count} TODO/FIXME markers. Consider using an issue tracker "
            f"instead of code comments for tracking work items."
        )

    commented_count = by_category.get("commented_code", 0)
    if commented_count > 0:
        recs.append(
            f"Found {commented_count} commented-out code blocks. Use version control "
            f"instead — delete the code, you can always recover it from git."
        )

    mock_count = by_category.get("mock_data", 0)
    if mock_count > 0:
        recs.append(
            f"Found {mock_count} mock/test data objects in production code. "
            f"Move these to test fixtures or mock files."
        )

    dev_only_count = by_category.get("dev_only", 0)
    if dev_only_count > 0:
        recs.append(
            f"Found {dev_only_count} dev-only guards. Consider using feature flags "
            f"or environment-based configuration instead of hardcoded DEBUG checks."
        )

    print_count = by_category.get("print_statement", 0)
    if print_count > 0:
        recs.append(
            f"Found {print_count} print/echo statements. Replace with structured logging "
            f"that supports log levels and output configuration."
        )

    skip_count = by_category.get("test_skip", 0)
    if skip_count > 0:
        recs.append(
            f"Found {skip_count} skipped/ignored tests. Either fix the tests or remove them — "
            f"skipped tests hide regressions."
        )

    if not leaks:
        recs.append("No debug leaks detected. Codebase looks clean for production deployment.")

    return recs
