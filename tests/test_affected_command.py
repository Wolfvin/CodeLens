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
    """The command should be auto-registered via commands/__init__.py."""
    from commands import COMMAND_REGISTRY

    assert "affected" in COMMAND_REGISTRY
    entry = COMMAND_REGISTRY["affected"]
    assert entry["help"]
    assert callable(entry["add_args"])
    assert callable(entry["execute"])
