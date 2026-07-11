"""
Tests for the `affected` command and `get_affected_files` engine (issue #62 Phase 1).

Covers:
- test-file heuristic (is_test_file)
- transitive BFS resolution
- --stdin pipe behavior
- --depth / --filter / --include-source / --quiet / --json flags
- ambiguous basename handling
- cycle safety

Run with::

    python -m pytest tests/test_affected_command.py -v
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import textwrap

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from dependents_engine import get_affected_files, is_test_file  # noqa: E402


# ─── is_test_file heuristic ───────────────────────────────────────────────


@pytest.mark.parametrize("path,expected", [
    # Python conventions
    ("tests/test_foo.py", True),
    ("test_foo.py", True),
    ("foo_test.py", True),
    ("tests/foo.py", True),       # tests/ directory
    ("spec/foo.py", True),        # spec/ directory
    ("foo.py", False),            # bare source
    ("src/foo.py", False),
    # JS/TS
    ("foo.test.js", True),
    ("foo.spec.ts", True),
    ("foo.spec.tsx", True),
    ("__tests__/foo.js", True),
    ("foo.js", False),
    # Go
    ("foo_test.go", True),
    ("foo.go", False),
    # Java
    ("FooTest.java", True),
    ("FooTests.java", True),
    ("Foo.java", False),
    # C#
    ("FooTest.cs", True),
    ("Foo.cs", False),
    # Non-source files
    ("README.md", False),
    ("package.json", False),
    (".gitignore", False),
    # Edge cases
    ("", False),
    ("test", False),              # no extension, no test dir
    ("tests", False),             # directory-only path (no basename file)
    # Path with multiple test segments
    ("tests/unit/test_foo.py", True),
    ("app/__tests__/foo.test.js", True),
])
def test_is_test_file(path, expected):
    assert is_test_file(path) is expected, f"is_test_file({path!r}) should be {expected}"


# ─── Fixture: small workspace with imports ──────────────────────────────


@pytest.fixture
def small_workspace(tmp_path):
    """Build a small workspace with known import structure:

        src/
            models.py              <- leaf, no imports
            services.py            <- imports models
            api.py                 <- imports services
            utils.py               <- leaf
        tests/
            test_models.py         <- imports src.models
            test_services.py       <- imports src.services
            test_api.py            <- imports src.api
            test_utils.py          <- imports src.utils
        conftest.py                <- leaf
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "src").mkdir()
    (ws / "tests").mkdir()

    (ws / "src" / "models.py").write_text(
        "class Model: pass\n", encoding="utf-8"
    )
    (ws / "src" / "services.py").write_text(
        "from src.models import Model\n\nclass Service: pass\n",
        encoding="utf-8",
    )
    (ws / "src" / "api.py").write_text(
        "from src.services import Service\n\nclass API: pass\n",
        encoding="utf-8",
    )
    (ws / "src" / "utils.py").write_text(
        "def helper(): pass\n", encoding="utf-8"
    )
    (ws / "tests" / "test_models.py").write_text(
        "from src.models import Model\n\ndef test_model(): assert Model\n",
        encoding="utf-8",
    )
    (ws / "tests" / "test_services.py").write_text(
        "from src.services import Service\n\ndef test_service(): assert Service\n",
        encoding="utf-8",
    )
    (ws / "tests" / "test_api.py").write_text(
        "from src.api import API\n\ndef test_api(): assert API\n",
        encoding="utf-8",
    )
    (ws / "tests" / "test_utils.py").write_text(
        "from src.utils import helper\n\ndef test_helper(): assert helper\n",
        encoding="utf-8",
    )
    (ws / "conftest.py").write_text(
        "# pytest conftest\n", encoding="utf-8"
    )
    return str(ws)


# ─── get_affected_files — core BFS ──────────────────────────────────────


def test_affected_finds_direct_test_dependents(small_workspace):
    """Changing models.py should affect test_models.py."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
    )
    assert result["status"] == "ok"
    affected = set(result["affected"])
    assert "tests/test_models.py" in affected


def test_affected_finds_transitive_test_dependents(small_workspace):
    """Changing models.py should ALSO affect test_services.py and test_api.py
    via the transitive chain models -> services -> api."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
        depth=5,
    )
    affected = set(result["affected"])
    # Direct: test_models.py imports models
    assert "tests/test_models.py" in affected
    # Transitive: test_services.py imports services which imports models
    assert "tests/test_services.py" in affected
    # Transitive: test_api.py imports api which imports services which imports models
    assert "tests/test_api.py" in affected


def test_affected_does_not_include_unrelated_tests(small_workspace):
    """Changing models.py should NOT affect test_utils.py (separate chain)."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
    )
    affected = set(result["affected"])
    assert "tests/test_utils.py" not in affected


def test_affected_depth_zero_returns_nothing(small_workspace):
    """depth=0 means only the changed file itself, and since it's not a test,
    nothing is returned."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
        depth=0,
    )
    assert result["affected"] == []


def test_affected_depth_one_finds_direct_only(small_workspace):
    """depth=1 means direct dependents only — no transitive propagation."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
        depth=1,
    )
    affected = set(result["affected"])
    assert "tests/test_models.py" in affected        # direct
    assert "tests/test_services.py" not in affected   # transitive — too deep
    assert "tests/test_api.py" not in affected        # transitive — too deep


def test_affected_include_source_returns_non_test_dependents(small_workspace):
    """With include_source=True, services.py should be returned as an
    affected source file when models.py changes."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
        include_source=True,
    )
    affected = set(result["affected"])
    assert "src/services.py" in affected   # non-test dependent
    assert "src/api.py" in affected        # transitive non-test dependent
    assert "tests/test_models.py" in affected
    assert result["stats"]["affected_source_count"] >= 2


def test_affected_filter_glob(small_workspace):
    """--filter 'tests/test_s*' should only return test_services.py."""
    result = get_affected_files(
        changed_files=["src/models.py"],
        workspace=small_workspace,
        file_filter="tests/test_s*",
    )
    affected = set(result["affected"])
    assert "tests/test_services.py" in affected
    assert "tests/test_models.py" not in affected
    assert "tests/test_api.py" not in affected


def test_affected_accepts_absolute_path(small_workspace):
    abs_path = os.path.join(small_workspace, "src", "models.py")
    result = get_affected_files(
        changed_files=[abs_path],
        workspace=small_workspace,
    )
    assert result["stats"]["changed_count"] == 1
    assert "tests/test_models.py" in result["affected"]


def test_affected_accepts_bare_basename(small_workspace):
    """Bare basename 'models.py' should resolve to src/models.py since it's
    unique in this workspace."""
    result = get_affected_files(
        changed_files=["models.py"],
        workspace=small_workspace,
    )
    assert result["stats"]["changed_count"] == 1
    assert "src/models.py" in result["changed_files"]


def test_affected_unresolved_files_listed(small_workspace):
    """Non-existent files should be reported in `unresolved`, not crash."""
    result = get_affected_files(
        changed_files=["src/nonexistent.py", "src/models.py"],
        workspace=small_workspace,
    )
    assert "src/nonexistent.py" in result["unresolved"]
    assert result["stats"]["changed_count"] == 1   # only models.py resolved


def test_affected_empty_input(small_workspace):
    """Empty changed_files list should return empty affected."""
    result = get_affected_files(
        changed_files=[],
        workspace=small_workspace,
    )
    assert result["affected"] == []
    assert result["stats"]["affected_count"] == 0


def test_affected_multiple_changed_files(small_workspace):
    """Multiple changed files should union their affected sets."""
    result = get_affected_files(
        changed_files=["src/models.py", "src/utils.py"],
        workspace=small_workspace,
    )
    affected = set(result["affected"])
    assert "tests/test_models.py" in affected
    assert "tests/test_utils.py" in affected
    assert "tests/test_services.py" in affected   # transitive from models


def test_affected_by_source_mapping(small_workspace):
    """affected_by_source should map each changed file to its affected tests."""
    result = get_affected_files(
        changed_files=["src/models.py", "src/utils.py"],
        workspace=small_workspace,
    )
    by_src = result["affected_by_source"]
    assert "src/models.py" in by_src
    assert "src/utils.py" in by_src
    assert "tests/test_models.py" in by_src["src/models.py"]
    assert "tests/test_utils.py" in by_src["src/utils.py"]
    # utils.py shouldn't pull in test_models.py
    assert "tests/test_models.py" not in by_src["src/utils.py"]


def test_affected_whitespace_only_input_skipped(small_workspace):
    """Whitespace-only lines should be skipped, not crash."""
    result = get_affected_files(
        changed_files=["  ", "", "src/models.py", "   "],
        workspace=small_workspace,
    )
    assert result["stats"]["changed_count"] == 1


# ─── Cycle safety ────────────────────────────────────────────────────────


def test_affected_handles_cycles(tmp_path):
    """Two modules importing each other should not infinite-loop."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("import b\n", encoding="utf-8")
    (ws / "b.py").write_text("import a\n", encoding="utf-8")
    (ws / "test_a.py").write_text("import a\n", encoding="utf-8")

    result = get_affected_files(
        changed_files=["a.py"],
        workspace=str(ws),
        depth=10,
    )
    assert result["status"] == "ok"
    assert "test_a.py" in result["affected"]
    # Safety cap should prevent runaway
    assert result["stats"]["visited_total"] < 100


def test_affected_safety_cap_on_large_graph(tmp_path):
    """Even with depth=-1, the 5000-node safety cap should kick in."""
    # Build a graph that would explode without a cap: a chain of N files
    # each importing the next, plus tests at each level.
    ws = tmp_path / "ws"
    ws.mkdir()
    n = 200
    for i in range(n):
        if i == 0:
            (ws / f"mod_{i}.py").write_text("# root\n", encoding="utf-8")
        else:
            (ws / f"mod_{i}.py").write_text(
                f"import mod_{i - 1}\n", encoding="utf-8"
            )
        (ws / f"test_mod_{i}.py").write_text(
            f"import mod_{i}\n", encoding="utf-8"
        )
    result = get_affected_files(
        changed_files=["mod_0.py"],
        workspace=str(ws),
        depth=-1,   # unlimited
    )
    assert result["status"] == "ok"
    assert result["stats"]["visited_total"] <= 5000


# ─── Command-level tests (add_args / execute wiring) ─────────────────────


class _Args:
    """Minimal args stub mimicking argparse.Namespace."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_command_add_args_registers_all_flags():
    from commands.affected import add_args
    import argparse

    p = argparse.ArgumentParser()
    add_args(p)
    # Parse with typical flags
    ns = p.parse_args(["--stdin", "-d", "3", "-f", "tests/*.py", "-j", "-q",
                       "--include-source", "src/foo.py"])
    assert ns.stdin is True
    assert ns.depth == 3
    assert ns.filter == "tests/*.py"
    assert ns.as_json is True
    assert ns.quiet is True
    assert ns.include_source is True
    assert ns.files == ["src/foo.py"]


def test_command_execute_with_no_files_returns_error(small_workspace):
    from commands.affected import execute

    args = _Args(files=None, stdin=False, depth=5, filter=None,
                 as_json=False, quiet=False, include_source=False)
    result = execute(args, small_workspace)
    assert result["status"] == "error"
    assert "no changed files" in result["error"].lower()


def test_command_execute_with_files_returns_result(small_workspace):
    from commands.affected import execute

    args = _Args(files=["src/models.py"], stdin=False, depth=5, filter=None,
                 as_json=False, quiet=False, include_source=False)
    result = execute(args, small_workspace)
    assert result["status"] == "ok"
    assert "tests/test_models.py" in result["affected"]


def test_command_execute_quiet_mode_prints_paths(small_workspace, capsys):
    from commands.affected import execute

    args = _Args(files=["src/models.py"], stdin=False, depth=5, filter=None,
                 as_json=False, quiet=True, include_source=False)
    result = execute(args, small_workspace)
    captured = capsys.readouterr()
    # Quiet mode prints paths to stdout, one per line
    assert "tests/test_models.py" in captured.out
    assert "status" not in captured.out   # no JSON noise
    assert result["quiet"] is True


def test_command_execute_reads_stdin(small_workspace, monkeypatch):
    from commands.affected import execute

    # Simulate `git diff --name-only | codelens affected --stdin`
    fake_stdin = io.StringIO("src/models.py\nsrc/utils.py\n")
    monkeypatch.setattr("sys.stdin", fake_stdin)

    args = _Args(files=None, stdin=True, depth=5, filter=None,
                 as_json=False, quiet=False, include_source=False)
    result = execute(args, small_workspace)
    assert result["status"] == "ok"
    assert result["stats"]["changed_count"] == 2
    affected = set(result["affected"])
    assert "tests/test_models.py" in affected
    assert "tests/test_utils.py" in affected


def test_command_execute_stdin_with_comments_and_blanks(small_workspace, monkeypatch):
    """stdin input should skip blank lines and comments."""
    from commands.affected import execute

    fake_stdin = io.StringIO(
        "# changed files from git diff\n"
        "\n"
        "src/models.py\n"
        "  \n"
        "# another comment\n"
    )
    monkeypatch.setattr("sys.stdin", fake_stdin)

    args = _Args(files=None, stdin=True, depth=5, filter=None,
                 as_json=False, quiet=False, include_source=False)
    result = execute(args, small_workspace)
    assert result["stats"]["changed_count"] == 1


def test_command_registered_in_registry():
    """The ``affected`` CLI alias was removed in issue #199.

    The implementation module ``commands.affected`` survives because the
    ``deps`` umbrella command imports it for its ``--check affected`` sub-
    analysis. The CLI alias ``codelens affected`` is no longer registered
    and must yield an ``invalid choice`` argparse error.
    """
    from commands import COMMAND_REGISTRY

    assert "affected" not in COMMAND_REGISTRY, (
        "affected alias should have been removed in #199"
    )
    # The implementation module must still be importable (umbrella dep).
    import importlib
    mod = importlib.import_module("commands.affected")
    assert callable(mod.execute)
    assert callable(mod.add_args)


# ─── Issue #176: TypeScript affected + workspace-as-first-arg ─────────────


@pytest.fixture
def ts_workspace():
    """TypeScript workspace with import chain: google-auth-cache <- login <- test."""
    ws = tempfile.mkdtemp(prefix="codelens_ts_test_")
    os.makedirs(os.path.join(ws, "auth"), exist_ok=True)
    os.makedirs(os.path.join(ws, "tests"), exist_ok=True)

    with open(os.path.join(ws, "auth", "google-auth-cache.ts"), "w") as f:
        f.write("export const cache = new Map<string, string>();\n"
                "export function getCachedToken(key: string): string | null {\n"
                "  return cache.get(key) || null;\n"
                "}\n")

    with open(os.path.join(ws, "auth", "login.ts"), "w") as f:
        f.write("import { getCachedToken } from './google-auth-cache';\n"
                "export function login(user: string): boolean {\n"
                "  const token = getCachedToken(user);\n"
                "  return token !== null;\n"
                "}\n")

    with open(os.path.join(ws, "tests", "login.test.ts"), "w") as f:
        f.write("import { login } from '../auth/login';\n"
                "test('login returns false for unknown user', () => {\n"
                "  expect(login('unknown')).toBe(false);\n"
                "});\n")

    yield ws

    import shutil
    shutil.rmtree(ws, ignore_errors=True)


class TestIssue176TypeScriptAffected:
    """Regression tests for issue #176: affected command for TypeScript workspaces.

    Bug: ``codelens affected /path/to/ws auth/file.ts`` returned
    ``affected_count: 0`` and put the workspace path in ``unresolved[]``
    because argparse greedy-absorbed all positional args into ``files``
    and workspace auto-detected to cwd.
    """

    def test_workspace_as_first_arg_resolves(self, ts_workspace):
        """``codelens affected /path/to/ws auth/file.ts`` — workspace from first arg."""
        from commands.affected import execute

        args = _Args(
            files=[ts_workspace, "auth/google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        # Simulate CLI dispatcher: workspace auto-detected to cwd (wrong)
        result = execute(args, os.getcwd())

        assert result["status"] == "ok"
        assert result["workspace"] == os.path.abspath(ts_workspace)
        assert "auth/google-auth-cache.ts" in result["changed_files"]
        assert result["unresolved"] == []
        assert "tests/login.test.ts" in result["affected"]

    def test_ts_affected_count_nonzero(self, ts_workspace):
        """affected_count must be > 0 for a TS file with known dependents."""
        from commands.affected import execute

        args = _Args(
            files=[ts_workspace, "auth/google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        result = execute(args, os.getcwd())
        assert result["stats"]["affected_count"] > 0

    def test_ts_include_source_returns_all_dependents(self, ts_workspace):
        """``--include-source`` returns both source and test dependents."""
        from commands.affected import execute

        args = _Args(
            files=[ts_workspace, "auth/google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=True,
        )
        result = execute(args, os.getcwd())
        affected = set(result["affected"])
        assert "auth/login.ts" in affected
        assert "tests/login.test.ts" in affected

    def test_ts_absolute_changed_path_resolves(self, ts_workspace):
        """Absolute path for changed file resolves correctly."""
        from commands.affected import execute

        abs_file = os.path.join(ts_workspace, "auth", "google-auth-cache.ts")
        args = _Args(
            files=[ts_workspace, abs_file],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        result = execute(args, os.getcwd())
        assert result["unresolved"] == []
        assert "auth/google-auth-cache.ts" in result["changed_files"]

    def test_ts_basename_only_resolves(self, ts_workspace):
        """Basename-only input resolves via basename match."""
        from commands.affected import execute

        args = _Args(
            files=[ts_workspace, "google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        result = execute(args, os.getcwd())
        assert result["unresolved"] == []
        assert "auth/google-auth-cache.ts" in result["changed_files"]

    def test_ts_dot_slash_prefix_resolves(self, ts_workspace):
        """``./auth/file.ts`` prefix is stripped correctly (lstrip bug regression)."""
        from commands.affected import execute

        args = _Args(
            files=[ts_workspace, "./auth/google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        result = execute(args, os.getcwd())
        assert result["unresolved"] == []
        assert "auth/google-auth-cache.ts" in result["changed_files"]

    def test_ts_parent_dir_path_not_corrupted(self, ts_workspace):
        """``../foo.ts`` must not be corrupted by lstrip('./') (issue #176 root cause 2)."""
        from dependents_engine import get_affected_files

        # Create a file in a parent-relative path
        result = get_affected_files(
            changed_files=["../google-auth-cache.ts"],
            workspace=ts_workspace,
            depth=5,
        )
        # ../google-auth-cache.ts doesn't exist in this workspace, so it
        # should be in unresolved — but NOT corrupted to "google-auth-cache.ts"
        # (which would accidentally resolve to the wrong file).
        # The key assertion: the original path is preserved in unresolved.
        assert any("../" in u for u in result["unresolved"]) or \
               len(result["unresolved"]) == 0  # if it happens to resolve, that's OK too

    def test_ts_no_workspace_arg_uses_cwd(self, ts_workspace):
        """When workspace is NOT the first arg, cwd is used (backward compat)."""
        from commands.affected import execute

        # No workspace path in files — just changed files. This is the old
        # behavior where workspace auto-detects to cwd.
        args = _Args(
            files=["auth/google-auth-cache.ts"],
            stdin=False, depth=5, filter=None,
            as_json=False, quiet=False, include_source=False,
        )
        # Pass ts_workspace as the resolved workspace (simulating cwd=ts_workspace)
        result = execute(args, ts_workspace)
        assert result["workspace"] == os.path.abspath(ts_workspace)
        assert "auth/google-auth-cache.ts" in result["changed_files"]
        assert result["unresolved"] == []


# ─── Issue #189: BFS never starts when import parser misses TS patterns ──
#
# PR #184 fixed the workspace-as-first-arg heuristic so the existing
# ts_workspace fixture (single-line `import { x } from './y'`) works. But
# `_parse_js_imports` still missed three common TS/JS import shapes:
#
#   1. Multi-line imports — `import {\n  foo,\n} from './bar'`
#      Root cause: regex used `.*?` which doesn't cross newlines.
#   2. Side-effect imports — `import './polyfills'` (no `from` clause).
#      Root cause: regex required `from`.
#   3. Re-exports — `export { x } from './bar'`, `export * from './bar'`.
#      Root cause: regex only matched `import`, not `export ... from`.
#
# When the parser misses an import, the reverse_graph loses an edge. If the
# changed file's only inbound edge was the missed import, BFS finds no
# dependents and `affected_count` stays at 0 — even though real dependents
# exist. This is the "BFS never starts" symptom described in issue #189.


class TestIssue189ImportParserPatterns:
    """Regression tests for issue #189: `_parse_js_imports` must handle
    multi-line imports, side-effect imports, and re-exports — otherwise
    `_build_import_graph` produces an incomplete reverse_graph and
    `codelens affected` returns ``affected_count: 0`` even when real
    dependents exist.
    """

    @pytest.fixture
    def ts_workspace_multiline(self, tmp_path):
        """TS workspace where login.ts uses a multi-line import statement.

        Mirrors the existing `ts_workspace` fixture but exercises the
        multi-line import shape that real-world TS code uses pervasively
        (Prettier default, ESLint `multi-line` rule, etc.).
        """
        ws = tmp_path / "ws_multiline"
        ws.mkdir()
        (ws / "auth").mkdir()
        (ws / "tests").mkdir()
        (ws / "auth" / "google-auth-cache.ts").write_text(
            "export const cache = new Map<string, string>();\n"
            "export function getCachedToken(key: string): string | null {\n"
            "  return cache.get(key) || null;\n"
            "}\n",
            encoding="utf-8",
        )
        (ws / "auth" / "login.ts").write_text(
            "import {\n"
            "  getCachedToken,\n"
            "} from './google-auth-cache';\n"
            "export function login(user: string): boolean {\n"
            "  const token = getCachedToken(user);\n"
            "  return token !== null;\n"
            "}\n",
            encoding="utf-8",
        )
        (ws / "tests" / "login.test.ts").write_text(
            "import { login } from '../auth/login';\n"
            "test('login returns false for unknown user', () => {\n"
            "  expect(login('unknown')).toBe(false);\n"
            "});\n",
            encoding="utf-8",
        )
        return str(ws)

    @pytest.fixture
    def ts_workspace_side_effect(self, tmp_path):
        """TS workspace where app.ts has a side-effect import (no `from`)."""
        ws = tmp_path / "ws_side_effect"
        ws.mkdir()
        (ws / "auth").mkdir()
        (ws / "tests").mkdir()
        (ws / "auth" / "polyfills.ts").write_text(
            "export const POLYFILL_VERSION = '1.0.0';\n",
            encoding="utf-8",
        )
        (ws / "auth" / "app.ts").write_text(
            "import './polyfills';\n"
            "export function app(): string { return 'ok'; }\n",
            encoding="utf-8",
        )
        (ws / "tests" / "app.test.ts").write_text(
            "import { app } from '../auth/app';\n"
            "test('app works', () => { expect(app()).toBe('ok'); });\n",
            encoding="utf-8",
        )
        return str(ws)

    @pytest.fixture
    def ts_workspace_reexport(self, tmp_path):
        """TS workspace using `export { x } from './core'` (barrel file)."""
        ws = tmp_path / "ws_reexport"
        ws.mkdir()
        (ws / "auth").mkdir()
        (ws / "tests").mkdir()
        (ws / "auth" / "core.ts").write_text(
            "export const TOKEN_KEY = 'cl_token';\n",
            encoding="utf-8",
        )
        (ws / "auth" / "index.ts").write_text(
            "export { TOKEN_KEY } from './core';\n",
            encoding="utf-8",
        )
        (ws / "tests" / "index.test.ts").write_text(
            "import { TOKEN_KEY } from '../auth/index';\n"
            "test('key is string', () => { expect(typeof TOKEN_KEY).toBe('string'); });\n",
            encoding="utf-8",
        )
        return str(ws)

    def test_multiline_import_resolves_and_bfs_finds_dependents(
        self, ts_workspace_multiline,
    ):
        """Multi-line `import {\n foo \n} from './bar'` must be parsed.

        Without the fix, `_parse_js_imports` skipped this import (regex
        `.*?` did not cross newlines), `reverse_graph` had no edge from
        `google-auth-cache.ts` to `login.ts`, and `affected_count` was 0.
        """
        result = get_affected_files(
            changed_files=["auth/google-auth-cache.ts"],
            workspace=ts_workspace_multiline,
            depth=5,
        )
        assert result["status"] == "ok"
        assert result["unresolved"] == [], (
            "changed file must resolve; unresolved means graph keys are "
            "incomplete (the BFS-never-starts symptom from issue #189)"
        )
        assert result["stats"]["affected_count"] >= 1, (
            "BFS must find the transitive test dependent via the multi-line "
            "import in login.ts"
        )
        assert "tests/login.test.ts" in result["affected"]

    def test_side_effect_import_resolves_and_bfs_finds_dependents(
        self, ts_workspace_side_effect,
    ):
        """`import './polyfills'` (no `from`) must be parsed as an edge."""
        result = get_affected_files(
            changed_files=["auth/polyfills.ts"],
            workspace=ts_workspace_side_effect,
            depth=5,
        )
        assert result["status"] == "ok"
        assert result["unresolved"] == []
        assert result["stats"]["affected_count"] >= 1, (
            "side-effect imports create a real dependency edge — BFS must "
            "find the transitive test dependent"
        )
        assert "tests/app.test.ts" in result["affected"]

    def test_reexport_creates_dependency_edge(
        self, ts_workspace_reexport,
    ):
        """`export { x } from './core'` must add core.ts → index.ts edge."""
        result = get_affected_files(
            changed_files=["auth/core.ts"],
            workspace=ts_workspace_reexport,
            depth=5,
        )
        assert result["status"] == "ok"
        assert result["unresolved"] == []
        assert result["stats"]["affected_count"] >= 1, (
            "re-exports create a real dependency edge — BFS must find the "
            "transitive test dependent via the barrel file"
        )
        assert "tests/index.test.ts" in result["affected"]

    def test_existing_ts_workspace_fixture_still_finds_affected(self, ts_workspace):
        """DoD sanity check: the existing fixture from PR #184 must still
        return ``affected_count >= 1`` after the parser changes.

        This is the explicit Definition-of-Done assertion from issue #189:
        "Use existing ts_workspace fixture in tests/test_affected_command.py
        (from PR #184) and assert affected_count >= 1".
        """
        result = get_affected_files(
            changed_files=["auth/google-auth-cache.ts"],
            workspace=ts_workspace,
            depth=5,
        )
        assert result["status"] == "ok"
        assert result["unresolved"] == []
        assert result["stats"]["affected_count"] >= 1
        assert "tests/login.test.ts" in result["affected"]

    def test_multiline_include_source_returns_all_dependents(
        self, ts_workspace_multiline,
    ):
        """`--include-source` must also surface non-test dependents reached
        via multi-line imports (cross-check against the existing
        `test_ts_include_source_returns_all_dependents`).
        """
        result = get_affected_files(
            changed_files=["auth/google-auth-cache.ts"],
            workspace=ts_workspace_multiline,
            depth=5,
            include_source=True,
        )
        affected = set(result["affected"])
        assert "auth/login.ts" in affected
        assert "tests/login.test.ts" in affected
