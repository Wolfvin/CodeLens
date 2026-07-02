"""
Tests for issue #163: file size threshold too conservative.

Verifies that:
- Large Python files (>= 200 lines, the old threshold) are now parsed
- Large JS files (>= 100 lines, the old threshold) are now parsed
- The ``skipped`` field is always present in parser output
- Files above the absolute hard limit (10,000 lines) are explicitly
  skipped with an entry in the ``skipped[]`` list (not silently)
- Deeply-nested Python files (depth >= 100) parse without SIGSEGV
  (the original issue #116 segfault trigger)
"""

import os
import sys
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)


# Detect tree-sitter availability once at module load — used by skipif markers.
def _tree_sitter_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        from base_parser import BaseParser  # noqa: F401
        return True
    except ImportError:
        return False


_TS_AVAILABLE = _tree_sitter_available()
_TS_SKIP_REASON = "tree-sitter or base_parser not installed"


# ─── Fixture generators ─────────────────────────────────────────


def _gen_large_python(lines: int) -> str:
    """Generate a realistic large Python file — many classes/methods.

    Structure: N classes × M methods, shallow nesting (depth 3-4).
    Matches real-world codebase patterns (not pathological depth).
    """
    out = ['"""Large Python fixture for issue #163."""', '', 'import os', '']
    # Each list element is one line once joined with '\n'.
    # len(out) approximates the line count (off by at most 1).
    while len(out) < lines:
        for c in range(10):
            out.append(f'class Service{c}:')
            out.append(f'    """Service {c}."""')
            for m in range(10):
                out.append(f'    def method_{m}(self, x, y):')
                out.append(f'        """Method {m}."""')
                out.append(f'        if x > y:')
                out.append(f'            return self.helper(x)')
                out.append(f'        return self.helper(y)')
            out.append(f'    def helper(self, v):')
            out.append(f'        return v * 2')
            out.append('')
            if len(out) >= lines:
                break
    return '\n'.join(out)


def _gen_large_js(lines: int) -> str:
    """Generate a realistic large JS file — many functions with 2-level
    callback nesting (matches real fetch().then().then() patterns)."""
    out = ['// Large JS fixture for issue #163.', "'use strict';", '']
    i = 0
    while len(out) < lines:
        out.append(f'function handler_{i}(req, res) {{')
        out.append(f'  return fetch("/api/{i}")')
        out.append(f'    .then(r => r.json())')
        out.append(f'    .then(d => res.json(d));')
        out.append(f'}}')
        i += 1
    return '\n'.join(out)


def _gen_deeply_nested_python(depth: int) -> str:
    """Generate a Python file with deeply-nested function definitions.

    This is the original issue #116 segfault trigger: each nested
    function adds a level of AST depth.
    """
    out = ['"""Deeply nested Python fixture."""', 'import os', '']
    out.append('def outer():')
    for d in range(depth):
        indent = '    ' * (d + 1)
        out.append(f'{indent}def level_{d}(x):')
        out.append(f'{indent}    y = x + {d}')
        out.append(f'{indent}    if y > 0:')
    out.append('    ' * (depth + 2) + 'return y * 2')
    for d in reversed(range(depth)):
        indent = '    ' * (d + 1)
        out.append(f'{indent}    return level_{d}(y)')
        out.append(f'{indent}return level_{d}(0)')
    out.append('outer()')
    return '\n'.join(out)


# ─── Python parser tests ────────────────────────────────────────


class TestPythonParserLargeFiles:
    """Issue #163: large Python files must be parsed, not silently skipped."""

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_above_old_threshold_is_parsed(self):
        """Files > 200 lines (old MAX_SAFE_PY_LINES) must now be parsed."""
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        # 250 lines — just above the old 200-line threshold
        content = _gen_large_python(250)
        line_count = content.count('\n') + 1
        assert line_count > 200, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "large.py")

        # Must NOT be skipped — nodes should be extracted
        assert len(result["nodes"]) > 0, "large file was silently skipped"
        assert len(result["edges"]) > 0, "no edges extracted from large file"
        assert result["skipped"] == [], "file should not be in skipped[]"

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_3000_lines_parses_without_segfault(self):
        """DoD: files up to 3,000 lines parse without SIGSEGV."""
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        content = _gen_large_python(3000)
        line_count = content.count('\n') + 1
        assert line_count >= 3000, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "big.py")

        assert len(result["nodes"]) > 100, "expected many nodes from 3000-line file"
        assert result["skipped"] == []

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_deeply_nested_python_parses_without_segfault(self):
        """Issue #116 root cause: deeply-nested Python must not segfault.

        The old threshold (200 lines) was added to avoid this segfault.
        With the iterative walk + keep_alive fix, depth 100+ should work.
        """
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        content = _gen_deeply_nested_python(100)
        line_count = content.count('\n') + 1

        result = parser.extract_references(content, "nested.py")

        # 100 nested functions + outer = 101 nodes
        assert len(result["nodes"]) >= 100, (
            f"expected >=100 nodes from depth-100 nesting, got {len(result['nodes'])}"
        )

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_skipped_field_always_present(self):
        """The ``skipped`` field must always be present in the return value,
        even when nothing is skipped (forward-compat for issue #163)."""
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        result = parser.extract_references("def f(): pass\n", "small.py")
        assert "skipped" in result
        assert result["skipped"] == []

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_above_hard_limit_is_explicitly_skipped(self):
        """Files > 10,000 lines are skipped with an explicit ``skipped[]``
        entry — not silently. Issue #163 DoD: 'silent skip replaced with
        explicit skipped[] list'."""
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        content = _gen_large_python(10050)
        line_count = content.count('\n') + 1
        assert line_count > 10000, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "huge.py")

        assert result["nodes"] == [], "huge file should not produce nodes"
        assert len(result["skipped"]) == 1, (
            f"expected 1 skipped entry, got {len(result['skipped'])}"
        )
        skip = result["skipped"][0]
        assert skip["file"] == "huge.py"
        assert skip["reason"] == "file_too_large"
        assert skip["lines"] == line_count


# ─── JS backend parser tests ────────────────────────────────────


class TestJSBackendParserLargeFiles:
    """Issue #163: large JS files must be parsed, not silently skipped."""

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_above_old_threshold_is_parsed(self):
        """Files > 100 lines (old MAX_SAFE_JS_LINES) must now be parsed."""
        try:
            from parsers.js_backend_parser import JSBackendParser
        except (ImportError, RuntimeError) as e:
            pytest.skip(f"JSBackendParser not available: {e}")
        parser = JSBackendParser()
        # 500 lines — well above the old 100-line threshold
        content = _gen_large_js(500)
        line_count = content.count('\n') + 1
        assert line_count > 100, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "large.js")

        assert len(result["nodes"]) > 0, "large file was silently skipped"
        assert len(result["edges"]) > 0, "no edges extracted from large file"
        assert result["skipped"] == [], "file should not be in skipped[]"

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_3000_lines_parses_without_segfault(self):
        """DoD: files up to 3,000 lines parse without SIGSEGV."""
        try:
            from parsers.js_backend_parser import JSBackendParser
        except (ImportError, RuntimeError) as e:
            pytest.skip(f"JSBackendParser not available: {e}")
        parser = JSBackendParser()
        content = _gen_large_js(3000)
        line_count = content.count('\n') + 1
        assert line_count >= 3000, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "big.js")

        assert len(result["nodes"]) > 100, "expected many nodes from 3000-line file"
        assert result["skipped"] == []

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_skipped_field_always_present(self):
        """The ``skipped`` field must always be present in the return value."""
        try:
            from parsers.js_backend_parser import JSBackendParser
        except (ImportError, RuntimeError) as e:
            pytest.skip(f"JSBackendParser not available: {e}")
        parser = JSBackendParser()
        result = parser.extract_references(
            "function f() { return 42; }", "small.js"
        )
        assert "skipped" in result
        assert result["skipped"] == []

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_file_above_hard_limit_is_explicitly_skipped(self):
        """Files > 10,000 lines are skipped with an explicit ``skipped[]``
        entry — not silently."""
        try:
            from parsers.js_backend_parser import JSBackendParser
        except (ImportError, RuntimeError) as e:
            pytest.skip(f"JSBackendParser not available: {e}")
        parser = JSBackendParser()
        content = _gen_large_js(10050)
        line_count = content.count('\n') + 1
        assert line_count > 10000, f"fixture too small: {line_count} lines"

        result = parser.extract_references(content, "huge.js")

        assert result["nodes"] == [], "huge file should not produce nodes"
        assert len(result["skipped"]) == 1, (
            f"expected 1 skipped entry, got {len(result['skipped'])}"
        )
        skip = result["skipped"][0]
        assert skip["file"] == "huge.js"
        assert skip["reason"] == "file_too_large"
        assert skip["lines"] == line_count


# ─── Backward compat: existing small-file behavior unchanged ────


class TestBackwardCompatSmallFiles:
    """Small files (< 100 lines) must continue to parse exactly as before."""

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_small_python_file_unchanged(self):
        from parsers.python_parser import PythonParser
        parser = PythonParser()
        content = "def hello():\n    return 42\n"
        result = parser.extract_references(content, "small.py")
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["fn"] == "hello"
        assert result["skipped"] == []

    @pytest.mark.skipif(not _TS_AVAILABLE, reason=_TS_SKIP_REASON)
    def test_small_js_file_unchanged(self):
        try:
            from parsers.js_backend_parser import JSBackendParser
        except (ImportError, RuntimeError) as e:
            pytest.skip(f"JSBackendParser not available: {e}")
        parser = JSBackendParser()
        content = "function hello() { return 42; }"
        result = parser.extract_references(content, "small.js")
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["fn"] == "hello"
        assert result["skipped"] == []
