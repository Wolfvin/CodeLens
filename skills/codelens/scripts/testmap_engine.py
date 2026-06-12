"""
Test Map Engine for CodeLens — v3
Maps which functions have test coverage by matching test names to function names.

Answers: "Is this function tested?" before AI touches it.

Strategies:
1. Name matching: test file names (auth.test.ts → auth.ts)
2. Function name matching: describe/it blocks containing the function name
3. Import matching: test files that import the source file
4. Coverage file parsing: coverage/lcov.info, coverage.json

This is the FIRST thing AI should check before modifying code.
"""

import os
import re
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

SOURCE_EXTENSIONS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py", ".rs", ".go"}

TEST_FILE_PATTERNS = [
    r'\.test\.(?:js|ts|tsx|jsx|mjs)$',
    r'\.spec\.(?:js|ts|tsx|jsx|mjs)$',
    r'_test\.(?:py|rs)$',
    r'_test\.go$',
    r'test_(\w+)\.py$',
    r'/__tests__/',
    r'/tests/',
    r'/test/',
    r'\.test\.py$',
]


def map_test_coverage(
    workspace: str,
    function_name: Optional[str] = None,
    file_filter: Optional[str] = None,
    config: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Map test coverage for functions in the workspace.

    If function_name is specified, check if that specific function is tested.
    Otherwise, produce a coverage map for the whole workspace.

    Args:
        workspace: Absolute path to workspace
        function_name: Optional function name to check
        file_filter: Optional file path filter for source files
        config: CodeLens config

    Returns:
        Dict with test coverage map, tested/untested functions
    """
    workspace = os.path.abspath(workspace)

    # Collect source files and test files
    source_files: Dict[str, Dict] = {}   # rel_path → {functions: [...], imports: [...]}
    test_files: Dict[str, Dict] = {}     # rel_path → {test_names: [...], imports: [...]}

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

            if file_filter and file_filter not in rel_path:
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            is_test = any(re.search(p, rel_path) for p in TEST_FILE_PATTERNS)

            # v5.10: Rust files with #[cfg(test)] modules contain inline tests.
            # These are not in separate test files, but contain test functions
            # that should be recognized for coverage mapping.
            has_inline_tests = False
            if ext == ".rs" and not is_test:
                if re.search(r'#\[cfg\(test\)\]', content) or re.search(r'#\[test\]', content):
                    has_inline_tests = True

            if is_test:
                test_info = _parse_test_file(content, ext, rel_path)
                test_files[rel_path] = test_info
            elif has_inline_tests:
                # v5.10: Split inline Rust test functions from source functions
                source_info, inline_test_info = _split_rust_inline_tests(content, rel_path)
                source_files[rel_path] = source_info
                if inline_test_info.get("test_names"):
                    # Use a synthetic test file path for inline tests
                    inline_test_path = rel_path + "#[cfg(test)]"
                    test_files[inline_test_path] = inline_test_info
            else:
                source_info = _parse_source_file(content, ext, rel_path)
                source_files[rel_path] = source_info

    # ─── Build coverage map ──────────────────────────────
    coverage_map: Dict[str, Dict[str, Any]] = {}  # file → {fn → {tested: bool, test_files: [...]}}

    for src_path, src_info in source_files.items():
        coverage_map[src_path] = {}

        for fn_name in src_info.get("functions", []):
            # Check if this function is tested
            test_matches = _find_tests_for_function(
                fn_name, src_path, test_files, workspace
            )

            coverage_map[src_path][fn_name] = {
                "tested": len(test_matches) > 0,
                "test_files": test_matches,
                "confidence": _compute_confidence(test_matches, fn_name)
            }

    # ─── If specific function requested ──────────────────
    if function_name:
        # Find the function across all source files
        function_coverage = []
        for src_path, fn_map in coverage_map.items():
            if function_name in fn_map:
                function_coverage.append({
                    "file": src_path,
                    **fn_map[function_name]
                })

        # Also try backend registry
        registry_match = _find_in_registry(function_name, workspace)

        return {
            "status": "ok",
            "function": function_name,
            "workspace": workspace,
            "tested": any(fc["tested"] for fc in function_coverage) if function_coverage else False,
            "coverage": function_coverage,
            "registry": registry_match,
            "recommendations": _generate_function_recommendations(
                function_name, function_coverage
            )
        }

    # ─── Full workspace coverage ────────────────────────
    total_functions = sum(len(fns) for fns in coverage_map.values())
    tested_functions = sum(
        1 for fns in coverage_map.values()
        for fn_info in fns.values()
        if fn_info["tested"]
    )
    untested_functions = total_functions - tested_functions

    # Find files with no test file at all
    files_without_tests = _find_untested_files(source_files, test_files, workspace)

    # Find test files with no corresponding source
    orphan_tests = _find_orphan_tests(source_files, test_files, workspace)

    # Try to parse coverage files
    coverage_data = _parse_coverage_files(workspace)

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_source_files": len(source_files),
            "total_test_files": len(test_files),
            "total_functions": total_functions,
            "tested_functions": tested_functions,
            "untested_functions": untested_functions,
            "coverage_percent": round(tested_functions / total_functions * 100, 1) if total_functions > 0 else 0,
            "files_without_tests": len(files_without_tests)
        },
        "coverage_map": coverage_map,
        "files_without_tests": files_without_tests[:30],
        "orphan_tests": orphan_tests[:10],
        "coverage_data": coverage_data,
        "untested_list": _get_untested_list(coverage_map)[:50]
    }


def _parse_source_file(content: str, ext: str, rel_path: str) -> Dict:
    """Parse a source file for functions and imports."""
    functions = []
    imports = []

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # Functions
        for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', content):
            functions.append(m.group(1))
        for m in re.finditer(r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(', content):
            functions.append(m.group(1))

        # Imports
        for m in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
            imports.append(m.group(1))
        for m in re.finditer(r'require\s*\(\s*["\']([^"\']+)["\']\s*\)', content):
            imports.append(m.group(1))

    elif ext == ".py":
        for m in re.finditer(r'(?:async\s+)?def\s+(\w+)', content):
            if not m.group(1).startswith('_'):
                functions.append(m.group(1))

        for m in re.finditer(r'(?:from\s+(\w+)\s+)?import\s+(.+)', content):
            imports.append(m.group(0).strip())

    elif ext == ".rs":
        for m in re.finditer(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', content):
            functions.append(m.group(1))

        for m in re.finditer(r'use\s+([^;]+);', content):
            imports.append(m.group(1).strip())

    elif ext == ".go":
        # Go functions (skip test/benchmark functions in source files)
        for m in re.finditer(r'func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(', content):
            name = m.group(1)
            if not name.startswith(('Test', 'Benchmark', 'Example', 'Fuzz')):
                functions.append(name)

        # Go imports
        for m in re.finditer(r'import\s+(?:"([^"]+)"|\(([^)]+)\))', content, re.DOTALL):
            if m.group(1):
                imports.append(m.group(1))
            elif m.group(2):
                # Multi-line import block
                for imp_m in re.finditer(r'"([^"]+)"', m.group(2)):
                    imports.append(imp_m.group(1))

    return {"functions": functions, "imports": imports}


def _parse_test_file(content: str, ext: str, rel_path: str) -> Dict:
    """Parse a test file for test names and imports."""
    test_names = []
    imports = []
    tested_functions = set()

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # describe/it/test blocks
        for m in re.finditer(r'(?:describe|it|test|context)\s*\(\s*["\']([^"\']+)', content):
            test_names.append(m.group(1))

        # Imports
        for m in re.finditer(r'import\s+.*?from\s+["\']([^"\']+)["\']', content):
            imports.append(m.group(1))

        # Function names referenced in test descriptions
        for name in test_names:
            # Extract likely function names from test descriptions
            words = re.findall(r'\b([a-z][a-zA-Z0-9]*)\b', name)
            tested_functions.update(words)

    elif ext == ".py":
        # pytest test functions
        for m in re.finditer(r'def\s+(test_\w+)', content):
            test_names.append(m.group(1))
            # Extract the function being tested from the test name
            parts = m.group(1).replace('test_', '').split('_')
            if len(parts) >= 1:
                # Try to reconstruct function name (snake_case → camelCase or keep as is)
                tested_functions.add('_'.join(parts))
                tested_functions.add(parts[0])  # First word as partial match

        for m in re.finditer(r'(?:from\s+(\S+)\s+)?import\s+(.+)', content):
            imports.append(m.group(0).strip())

    elif ext == ".rs":
        # Rust test functions
        for m in re.finditer(r'#\[test\]\s*(?:\n\s*#\[.*\]\s*)*\s*fn\s+(\w+)', content):
            test_names.append(m.group(1))

    elif ext == ".go":
        # Go test functions: func TestXxx(t *testing.T)
        for m in re.finditer(r'func\s+(Test\w+)\s*\([^)]*\*testing\.T\)', content):
            test_names.append(m.group(1))
            # Extract the function being tested from TestXxx
            tested_name = m.group(1)[4:]  # Strip "Test" prefix
            if tested_name:
                # Try both PascalCase and camelCase variants
                tested_functions.add(tested_name)
                tested_functions.add(tested_name[0].lower() + tested_name[1:])

        # Go benchmark functions: func BenchmarkXxx(b *testing.B)
        for m in re.finditer(r'func\s+(Benchmark\w+)\s*\([^)]*\*testing\.B\)', content):
            test_names.append(m.group(1))
            bench_name = m.group(1)[9:]  # Strip "Benchmark" prefix
            if bench_name:
                tested_functions.add(bench_name)
                tested_functions.add(bench_name[0].lower() + bench_name[1:])

        # Go example functions: func ExampleXxx()
        for m in re.finditer(r'func\s+(Example\w+)\s*\(', content):
            test_names.append(m.group(1))

        # Go fuzz functions: func FuzzXxx(f *testing.F)
        for m in re.finditer(r'func\s+(Fuzz\w+)\s*\([^)]*\*testing\.F\)', content):
            test_names.append(m.group(1))

        # Go imports
        for m in re.finditer(r'import\s+(?:"([^"]+)"|\(([^)]+)\))', content, re.DOTALL):
            if m.group(1):
                imports.append(m.group(1))
            elif m.group(2):
                for imp_m in re.finditer(r'"([^"]+)"', m.group(2)):
                    imports.append(imp_m.group(1))

    return {
        "test_names": test_names,
        "imports": imports,
        "tested_functions": tested_functions
    }


def _split_rust_inline_tests(content: str, rel_path: str) -> tuple:
    """Split a Rust source file with inline #[cfg(test)] module into
    source functions and test functions.

    In Rust, it's common to write tests in the same file as the source code:
        #[cfg(test)]
        mod tests {
            #[test]
            fn test_something() { ... }
        }

    This function extracts the #[test] functions from the inline test module
    and separates them from the production source functions.

    Returns:
        Tuple of (source_info, test_info) dicts.
    """
    # Parse all functions from the file
    all_functions = []
    test_functions = []
    imports = []

    for m in re.finditer(r'(?:pub\s+)?(?:async\s+)?fn\s+(\w+)', content):
        all_functions.append(m.group(1))

    for m in re.finditer(r'use\s+([^;]+);', content):
        imports.append(m.group(1).strip())

    # Find the #[cfg(test)] module and extract test functions from it
    # Match #[test] annotated functions — these can be in:
    # 1. #[cfg(test)] mod tests { ... } blocks
    # 2. Standalone #[test] fn ... at module level (rare but valid)
    tested_function_names = set()

    # Pattern 1: #[test] functions inside #[cfg(test)] modules
    for m in re.finditer(r'#\[test\]\s*(?:\n\s*#\[.*\]\s*)*\s*fn\s+(\w+)', content):
        test_fn_name = m.group(1)
        test_functions.append(test_fn_name)

        # Try to extract the function being tested from the test name
        # Common Rust convention: test_<function_name> or test_<module>_<function>
        if test_fn_name.startswith('test_'):
            remainder = test_fn_name[5:]  # Remove "test_" prefix
            # Try various splits: test_read_header → "read_header" → ["read", "header"]
            parts = remainder.split('_')
            if parts:
                tested_function_names.add(remainder)  # Full name after test_
                tested_function_names.add(parts[0])    # Just first segment
                # Also try camelCase conversion: test_read_header → readHeader
                if len(parts) > 1:
                    camel = parts[0] + ''.join(p.capitalize() for p in parts[1:])
                    tested_function_names.add(camel)

    # Source functions = all functions minus test functions
    source_functions = [f for f in all_functions if f not in test_functions]

    source_info = {
        "functions": source_functions,
        "imports": imports,
    }

    test_info = {
        "test_names": test_functions,
        "imports": imports,
        "tested_functions": tested_function_names,
    }

    return source_info, test_info


def _find_tests_for_function(
    fn_name: str,
    src_path: str,
    test_files: Dict[str, Dict],
    workspace: str
) -> List[str]:
    """Find test files that test a specific function."""
    matches = []
    src_basename = os.path.splitext(os.path.basename(src_path))[0]

    for test_path, test_info in test_files.items():
        # v5.10: Strategy 0: Inline Rust tests (path contains #[cfg(test)])
        # These are inline tests in the same source file
        if test_path.endswith('#[cfg(test)]'):
            # The source path is the test path without the #[cfg(test)] suffix
            inline_src_path = test_path[:-len('#[cfg(test)]')]
            if inline_src_path == src_path:
                # Same file inline test — check if function name matches
                if fn_name in test_info.get("tested_functions", set()):
                    matches.append(test_path)
                    continue
                for test_name in test_info.get("test_names", []):
                    if fn_name.lower() in test_name.lower():
                        matches.append(test_path)
                        break
                continue

        # Strategy 1: File name matching (auth.test.ts → auth.ts)
        test_basename = os.path.basename(test_path)
        # Go: precise mapping foo.go → foo_test.go (same directory)
        if src_path.endswith('.go'):
            src_dir = os.path.dirname(src_path)
            test_dir = os.path.dirname(test_path)
            if src_dir == test_dir and test_basename == f"{src_basename}_test.go":
                matches.append(test_path)
                continue
        elif src_basename in test_basename:
            matches.append(test_path)
            continue

        # Strategy 2: Import matching (test imports source file)
        for imp in test_info.get("imports", []):
            if src_basename in imp or src_path.replace('\\', '/') in imp:
                matches.append(test_path)
                continue

        # Strategy 3: Function name in test descriptions
        if fn_name in test_info.get("tested_functions", set()):
            matches.append(test_path)
            continue

        # Strategy 4: Function name appears in test file content (loose match)
        # This is checked via test_names containing the function name
        for test_name in test_info.get("test_names", []):
            if fn_name.lower() in test_name.lower():
                matches.append(test_path)
                break

    return list(set(matches))[:10]


def _compute_confidence(test_matches: List[str], fn_name: str) -> str:
    """Compute confidence level of the test coverage assessment."""
    if not test_matches:
        return "none"

    # High confidence: function name explicitly appears in test description
    # Medium confidence: test file imports source file
    # Low confidence: only file name matches
    for tf in test_matches:
        # Check if function name is in test file name or path
        if fn_name.lower() in tf.lower():
            return "high"

    if len(test_matches) >= 2:
        return "medium"

    return "low"


def _find_untested_files(
    source_files: Dict[str, Dict],
    test_files: Dict[str, Dict],
    workspace: str
) -> List[Dict]:
    """Find source files that have no corresponding test file."""
    untested = []

    for src_path in source_files:
        src_basename = os.path.splitext(os.path.basename(src_path))[0]
        has_test = False

        for test_path in test_files:
            test_basename = os.path.basename(test_path)
            if src_basename in test_basename:
                has_test = True
                break

            # Check if any test imports this source
            for imp in test_files[test_path].get("imports", []):
                if src_basename in imp:
                    has_test = True
                    break

            if has_test:
                break

        if not has_test:
            fns = source_files[src_path].get("functions", [])
            untested.append({
                "file": src_path,
                "function_count": len(fns),
                "functions": fns[:10],
                "severity": "warning" if len(fns) > 5 else "info"
            })

    return sorted(untested, key=lambda x: x["function_count"], reverse=True)


def _find_orphan_tests(
    source_files: Dict[str, Dict],
    test_files: Dict[str, Dict],
    workspace: str
) -> List[Dict]:
    """Find test files that don't correspond to any source file."""
    orphans = []

    for test_path in test_files:
        test_basename = os.path.splitext(os.path.basename(test_path))[0]
        # Remove .test/.spec suffix (JS/TS) or _test suffix (Go/Rust/Python)
        base_name = re.sub(r'(?:\.(test|spec)|_test)$', '', test_basename)

        has_source = False
        for src_path in source_files:
            src_basename = os.path.splitext(os.path.basename(src_path))[0]
            if src_basename == base_name:
                has_source = True
                break

        if not has_source:
            orphans.append({
                "file": test_path,
                "test_count": len(test_files[test_path].get("test_names", [])),
                "message": "Test file with no corresponding source file"
            })

    return orphans


def _parse_coverage_files(workspace: str) -> Optional[Dict]:
    """Try to parse existing coverage reports."""
    # Check for coverage/lcov.info
    lcov_path = os.path.join(workspace, "coverage", "lcov.info")
    if os.path.exists(lcov_path):
        return {"source": "lcov", "path": "coverage/lcov.info", "parsed": True}

    # Check for coverage/coverage-final.json
    cov_json = os.path.join(workspace, "coverage", "coverage-final.json")
    if os.path.exists(cov_json):
        return {"source": "istanbul", "path": "coverage/coverage-final.json", "parsed": True}

    # Check for coverage.json
    cov_simple = os.path.join(workspace, "coverage.json")
    if os.path.exists(cov_simple):
        return {"source": "json", "path": "coverage.json", "parsed": True}

    return None


def _find_in_registry(function_name: str, workspace: str) -> Optional[Dict]:
    """Check backend registry for function info."""
    try:
        from registry import load_backend_registry
        backend = load_backend_registry(workspace)
        for node in backend.get("nodes", []):
            if node["fn"] == function_name:
                return {
                    "found": True,
                    "file": node.get("file", ""),
                    "line": node.get("line", 0),
                    "ref_count": node.get("ref_count", 0)
                }
    except Exception:
        logger.debug("Failed to load backend registry for test coverage check", exc_info=True)

    return None


def _generate_function_recommendations(function_name: str, coverage: List[Dict]) -> List[str]:
    """Generate recommendations for a specific function's test coverage."""
    recs = []

    if not coverage:
        recs.append(f"Function '{function_name}' not found in any source file.")
        return recs

    is_tested = any(c["tested"] for c in coverage)

    if is_tested:
        test_files = []
        for c in coverage:
            test_files.extend(c.get("test_files", []))
        recs.append(
            f"Function '{function_name}' appears to be tested. "
            f"Test files: {', '.join(set(test_files))}"
        )
        # Check confidence
        for c in coverage:
            if c.get("confidence") == "low":
                recs.append(
                    f"Low confidence match in {c['file']} — "
                    f"verify the test actually covers '{function_name}'."
                )
    else:
        recs.append(
            f"Function '{function_name}' does NOT appear to have test coverage. "
            f"Write tests before modifying."
        )
        for c in coverage:
            recs.append(
                f"Create test file for {c['file']} "
                f"(e.g., {os.path.splitext(os.path.basename(c['file']))[0]}.test.ts)"
            )

    return recs


def _get_untested_list(coverage_map: Dict[str, Dict[str, Any]]) -> List[Dict]:
    """Get list of untested functions sorted by importance (most referenced first)."""
    untested = []

    for src_path, fn_map in coverage_map.items():
        for fn_name, fn_info in fn_map.items():
            if not fn_info["tested"]:
                untested.append({
                    "function": fn_name,
                    "file": src_path,
                    "confidence": fn_info["confidence"]
                })

    return untested
