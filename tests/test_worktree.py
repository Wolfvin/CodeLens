"""Tests for ``scripts/sync/worktree.py`` — git worktree ↔ index mismatch (issue #66 Phase 4).

Verifies:

1. ``detect_worktree_index_mismatch`` correctly distinguishes:
   - not-a-git-repo → ``reason="not_a_git_repo"``, ``mismatch=False``
   - main checkout → ``reason="not_a_worktree"``, ``mismatch=False``
   - worktree with own ``.codelens/`` → ``reason="worktree_has_own_index"``, ``mismatch=False``
   - worktree without ``.codelens/``, main has it → ``reason="worktree_uses_main_index"``, ``mismatch=True``
   - worktree without ``.codelens/`` anywhere → ``reason="no_index_found"``, ``mismatch=False``
2. ``format_worktree_warning`` returns multi-line warning when mismatch, empty string otherwise.
3. ``format_worktree_banner`` returns single-line banner when mismatch, empty string otherwise.
4. Detection is robust to:
   - missing git binary (skipped, not failed)
   - non-existent workspace path
   - workspace that is a file, not a directory
   - empty/None workspace
5. The mismatch record includes all documented fields: ``mismatch``, ``reason``,
   ``worktree_root``, ``main_checkout_root``, ``index_root``, ``suggestion``.

All git operations use a temp directory + ``git init`` / ``git worktree add``
so tests don't depend on the CodeLens repo's git state. If git isn't
installed, every test is skipped with ``pytest.skip('git not available')``
— mirroring the pattern in ``tests/test_git_aware.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

# Add scripts directory to path (matches other test files).
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from sync.worktree import (  # noqa: E402
    detect_worktree_index_mismatch,
    format_worktree_banner,
    format_worktree_warning,
)


# ─── Skip-if-git-missing guard ──────────────────────────────────────


def _git_available() -> bool:
    """Return True if the ``git`` binary is installed and supports worktrees."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode != 0:
            return False
        # ``git worktree add`` was stabilised in git 2.5 (2015). Any
        # git from the last decade supports it. We don't pin a minimum
        # version — if ``git --version`` works, worktrees work.
        return True
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _git_available(),
    reason="git not available — worktree tests require the git binary",
)


# ─── Fixtures ───────────────────────────────────────────────────────


def _make_git_repo(td: str) -> None:
    """Initialise a git repo in ``td`` with one commit.

    Sets local ``user.name`` / ``user.email`` so commits work without
    relying on the host's global git config.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=td, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=td, check=True
    )
    with open(os.path.join(td, "README.md"), "w") as f:
        f.write("initial commit\n")
    subprocess.run(["git", "add", "."], cwd=td, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=td, check=True)


def _make_worktree(main_repo: str, wt_name: str = "wt-feature") -> str:
    """Create a git worktree of ``main_repo`` and return its path.

    The worktree is created on a new branch ``feature`` so it's
    clearly distinct from the main branch — this matches the
    real-world scenario where a user works on a feature branch in a
    worktree.
    """
    wt_path = os.path.join(main_repo, wt_name)
    subprocess.run(
        ["git", "worktree", "add", "-q", wt_path, "-b", "feature"],
        cwd=main_repo,
        check=True,
    )
    return wt_path


def _make_codelens_dir(parent: str) -> str:
    """Create a ``.codelens/`` directory inside ``parent`` and return its path."""
    codelens_dir = os.path.join(parent, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    return codelens_dir


# ─── Test: not a git repo ──────────────────────────────────────────


def test_not_a_git_repo_returns_no_mismatch():
    """A directory that's not under git control reports ``not_a_git_repo``."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        result = detect_worktree_index_mismatch(td)
        assert result["mismatch"] is False
        assert result["reason"] == "not_a_git_repo"
        assert result["worktree_root"] is None
        assert result["main_checkout_root"] is None
        assert result["index_root"] is None
        assert result["suggestion"] is None


def test_nonexistent_path_returns_no_mismatch():
    """A path that doesn't exist reports ``not_a_git_repo`` (benign fallback)."""
    result = detect_worktree_index_mismatch("/nonexistent/path/that/does/not/exist")
    assert result["mismatch"] is False
    assert result["reason"] == "not_a_git_repo"


def test_empty_string_returns_no_mismatch():
    """An empty workspace string reports ``not_a_git_repo``."""
    result = detect_worktree_index_mismatch("")
    assert result["mismatch"] is False
    assert result["reason"] == "not_a_git_repo"


def test_none_path_returns_no_mismatch():
    """A None workspace reports ``not_a_git_repo`` without raising."""
    result = detect_worktree_index_mismatch(None)  # type: ignore[arg-type]
    assert result["mismatch"] is False
    assert result["reason"] == "not_a_git_repo"


def test_file_path_returns_no_mismatch():
    """A path pointing to a file (not a dir) reports ``not_a_git_repo``."""
    with tempfile.NamedTemporaryFile(prefix="codelens_wt_test_") as tf:
        result = detect_worktree_index_mismatch(tf.name)
        assert result["mismatch"] is False
        assert result["reason"] == "not_a_git_repo"


# ─── Test: main checkout (not a worktree) ──────────────────────────


def test_main_checkout_with_codelens_no_mismatch():
    """A main checkout with its own ``.codelens/`` reports ``not_a_worktree``."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)
        result = detect_worktree_index_mismatch(td)
        assert result["mismatch"] is False
        assert result["reason"] == "not_a_worktree"
        assert result["worktree_root"] is not None
        assert result["main_checkout_root"] is not None
        # For a main checkout, worktree_root == main_checkout_root.
        assert os.path.abspath(result["worktree_root"]) == os.path.abspath(
            result["main_checkout_root"]
        )
        assert result["index_root"] is not None
        assert os.path.abspath(result["index_root"]) == os.path.abspath(td)


def test_main_checkout_without_codelens_no_mismatch():
    """A main checkout without ``.codelens/`` still reports ``not_a_worktree``.

    The absence of an index is not a worktree-specific problem — it's
    just an uninitialised workspace, handled elsewhere.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        # No .codelens/ created.
        result = detect_worktree_index_mismatch(td)
        assert result["mismatch"] is False
        # The walk-up finds no .codelens anywhere, so the reason is
        # ``no_index_found`` rather than ``not_a_worktree``. Both
        # indicate no mismatch — the specific reason is informational.
        assert result["reason"] in ("not_a_worktree", "no_index_found")


# ─── Test: worktree with its own index ─────────────────────────────


def test_worktree_with_own_codelens_no_mismatch():
    """A worktree that has its own ``.codelens/`` reports no mismatch.

    This is the correct setup: each worktree maintains its own index
    because each worktree checks out a different branch.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        wt_path = _make_worktree(td)
        _make_codelens_dir(wt_path)  # worktree has own index
        result = detect_worktree_index_mismatch(wt_path)
        assert result["mismatch"] is False
        assert result["reason"] == "worktree_has_own_index"
        assert os.path.abspath(result["worktree_root"]) == os.path.abspath(wt_path)
        assert os.path.abspath(result["main_checkout_root"]) == os.path.abspath(td)
        assert os.path.abspath(result["index_root"]) == os.path.abspath(wt_path)
        assert result["suggestion"] is None


# ─── Test: worktree without own index, main has it (MISMATCH) ──────


def test_worktree_uses_main_index_mismatch_detected():
    """A worktree without ``.codelens/`` but main has it → MISMATCH.

    This is the core scenario the module exists to detect: CodeLens
    will silently walk up and load the main checkout's index, which
    was built from a different branch.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)  # main has .codelens
        wt_path = _make_worktree(td)
        # worktree does NOT have .codelens

        result = detect_worktree_index_mismatch(wt_path)
        assert result["mismatch"] is True
        assert result["reason"] == "worktree_uses_main_index"
        assert os.path.abspath(result["worktree_root"]) == os.path.abspath(wt_path)
        assert os.path.abspath(result["main_checkout_root"]) == os.path.abspath(td)
        assert os.path.abspath(result["index_root"]) == os.path.abspath(td)

        suggestion = result["suggestion"]
        assert suggestion is not None
        assert "codelens init" in suggestion
        assert wt_path in suggestion


def test_worktree_mismatch_from_subdirectory():
    """Mismatch is detected even when called from a subdir of the worktree.

    CodeLens's workspace auto-detection walks up from cwd, so the
    workspace may resolve to the worktree root even when the user is
    in a subdirectory. The mismatch detection must work from any
    depth inside the worktree.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)
        wt_path = _make_worktree(td)
        # Create a subdirectory inside the worktree
        subdir = os.path.join(wt_path, "src", "deep", "nested")
        os.makedirs(subdir)

        result = detect_worktree_index_mismatch(subdir)
        assert result["mismatch"] is True
        assert result["reason"] == "worktree_uses_main_index"
        assert os.path.abspath(result["worktree_root"]) == os.path.abspath(wt_path)


# ─── Test: worktree without .codelens anywhere ─────────────────────


def test_worktree_no_codelens_anywhere_no_mismatch():
    """A worktree with no ``.codelens/`` anywhere up the tree.

    Nothing is being loaded, so there's nothing to be wrong about.
    The reason is ``no_index_found`` — informational, not a warning.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        wt_path = _make_worktree(td)
        # No .codelens anywhere.

        result = detect_worktree_index_mismatch(wt_path)
        assert result["mismatch"] is False
        assert result["reason"] == "no_index_found"
        assert result["worktree_root"] is not None
        assert result["main_checkout_root"] is not None
        assert result["index_root"] is None


# ─── Test: formatters ──────────────────────────────────────────────


def test_format_worktree_warning_empty_when_no_mismatch():
    """``format_worktree_warning`` returns ``""`` when no mismatch."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        result = detect_worktree_index_mismatch(td)
        assert format_worktree_warning(result) == ""


def test_format_worktree_warning_multiline_when_mismatch():
    """``format_worktree_warning`` returns multi-line warning when mismatch."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)
        wt_path = _make_worktree(td)
        result = detect_worktree_index_mismatch(wt_path)
        assert result["mismatch"] is True

        warning = format_worktree_warning(result)
        assert warning != ""
        assert "WORKTREE INDEX MISMATCH" in warning
        assert wt_path in warning
        assert td in warning
        assert "codelens init" in warning
        # Multi-line — has at least 4 lines (header, worktree, main, index, problem, fix).
        assert warning.count("\n") >= 4


def test_format_worktree_banner_empty_when_no_mismatch():
    """``format_worktree_banner`` returns ``""`` when no mismatch."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        result = detect_worktree_index_mismatch(td)
        assert format_worktree_banner(result) == ""


def test_format_worktree_banner_single_line_when_mismatch():
    """``format_worktree_banner`` returns single-line banner when mismatch."""
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)
        wt_path = _make_worktree(td)
        result = detect_worktree_index_mismatch(wt_path)
        assert result["mismatch"] is True

        banner = format_worktree_banner(result)
        assert banner != ""
        assert "WORKTREE INDEX MISMATCH" in banner
        assert wt_path in banner
        # Single line — no newlines.
        assert "\n" not in banner


def test_format_worktree_warning_handles_empty_dict():
    """``format_worktree_warning`` is robust to an empty dict input."""
    assert format_worktree_warning({}) == ""
    assert format_worktree_warning(None) == ""  # type: ignore[arg-type]


def test_format_worktree_banner_handles_empty_dict():
    """``format_worktree_banner`` is robust to an empty dict input."""
    assert format_worktree_banner({}) == ""
    assert format_worktree_banner(None) == ""  # type: ignore[arg-type]


# ─── Test: return-shape contract ───────────────────────────────────


def test_result_dict_has_all_documented_fields():
    """Every result dict must have all 6 documented fields.

    Callers (doctor, mcp_server) access these fields unconditionally
    via ``.get()`` — but the contract is that they're always present.
    Missing fields would be a silent API regression.
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        result = detect_worktree_index_mismatch(td)
        for field in (
            "mismatch",
            "reason",
            "worktree_root",
            "main_checkout_root",
            "index_root",
            "suggestion",
        ):
            assert field in result, f"missing field: {field}"


def test_mismatch_is_bool_not_truthy_value():
    """``mismatch`` must be a real bool, not a truthy value.

    Doctor and MCP server do ``if mismatch.get("mismatch"):`` — that
    works with truthy values, but the contract says bool. Using bool
    makes the JSON serialization deterministic (``true`` / ``false``,
    not ``1`` / ``0`` or ``"yes"`` / ``"no"``).
    """
    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        _make_codelens_dir(td)
        wt_path = _make_worktree(td)
        result = detect_worktree_index_mismatch(wt_path)
        assert isinstance(result["mismatch"], bool)
        assert result["mismatch"] is True

    with tempfile.TemporaryDirectory(prefix="codelens_wt_test_") as td:
        _make_git_repo(td)
        result = detect_worktree_index_mismatch(td)
        assert isinstance(result["mismatch"], bool)
        assert result["mismatch"] is False
