"""
Tests for scripts/check_design_doc.py — the CI check that enforces the
issue #67 Phase 1 design-doc requirement.

These tests do NOT shell out to git. They import the script as a module and
exercise the pure functions (is_feature_class, is_design_doc, is_plan_doc,
evaluate) directly. The git interaction (added_files) is tested via a single
end-to-end test that creates a temp git repo.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make scripts/ importable
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_design_doc as cdd  # noqa: E402


# --- is_feature_class -----------------------------------------------------

class TestIsFeatureClass:
    """Verify the feature-class file detection regex."""

    def test_new_command_is_feature_class(self):
        assert cdd.is_feature_class("scripts/commands/mycommand.py")

    def test_new_parser_is_feature_class(self):
        assert cdd.is_feature_class("scripts/parsers/elixir_parser.py")

    def test_new_engine_is_feature_class(self):
        assert cdd.is_feature_class("scripts/contracts_engine.py")

    def test_new_mcp_hook_is_feature_class(self):
        assert cdd.is_feature_class("scripts/mcp_hooks/pre_tool.py")

    def test_init_py_under_commands_is_not_feature_class(self):
        # __init__.py is scaffolding, not a new command
        assert not cdd.is_feature_class("scripts/commands/__init__.py")

    def test_init_py_under_parsers_is_not_feature_class(self):
        assert not cdd.is_feature_class("scripts/parsers/__init__.py")

    def test_init_py_under_mcp_hooks_is_not_feature_class(self):
        assert not cdd.is_feature_class("scripts/mcp_hooks/__init__.py")

    def test_top_level_init_py_is_not_feature_class(self):
        assert not cdd.is_feature_class("scripts/__init__.py")

    def test_fallback_parser_is_feature_class(self):
        # fallback parsers live under scripts/parsers/ but don't end in _parser.py
        # by convention — they end in _fallback_<lang>.py. These are NOT
        # feature-class (they are alternative implementations of an existing
        # parser, not a new language).
        # However the regex scripts/parsers/[^/]+_parser.py does not match
        # fallback_rust.py — verify this.
        assert not cdd.is_feature_class("scripts/parsers/fallback_rust.py")

    def test_test_file_is_not_feature_class(self):
        assert not cdd.is_feature_class("tests/test_foo.py")

    def test_docs_file_is_not_feature_class(self):
        assert not cdd.is_feature_class("docs/design/foo.md")

    def test_config_file_is_not_feature_class(self):
        assert not cdd.is_feature_class("pyproject.toml")

    def test_engine_subpackage_file_is_not_feature_class(self):
        # scripts/security/path_traversal.py is a module inside a subpackage,
        # not a top-level engine. The regex scripts/[^/]+_engine.py does not
        # match it because the path has two slashes.
        assert not cdd.is_feature_class("scripts/security/path_traversal.py")


# --- is_design_doc / is_plan_doc ------------------------------------------

class TestIsDesignOrPlanDoc:
    def test_design_doc_in_correct_dir(self):
        assert cdd.is_design_doc("docs/design/cross-file-taint.md")

    def test_plan_doc_in_correct_dir(self):
        assert cdd.is_plan_doc("docs/plans/cross-file-taint.md")

    def test_design_template_is_not_counted(self):
        # template.md and README.md are scaffolding, not feature docs
        assert not cdd.is_design_doc("docs/design/template.md")

    def test_design_readme_is_not_counted(self):
        assert not cdd.is_design_doc("docs/design/README.md")

    def test_plan_template_is_not_counted(self):
        assert not cdd.is_plan_doc("docs/plans/template.md")

    def test_plan_readme_is_not_counted(self):
        assert not cdd.is_plan_doc("docs/plans/README.md")

    def test_doc_in_wrong_dir_is_not_counted(self):
        assert not cdd.is_design_doc("docs/plans/foo.md")
        assert not cdd.is_plan_doc("docs/design/foo.md")

    def test_non_md_file_is_not_counted(self):
        assert not cdd.is_design_doc("docs/design/foo.txt")
        assert not cdd.is_plan_doc("docs/plans/foo.yaml")

    def test_doc_at_root_is_not_counted(self):
        assert not cdd.is_design_doc("README.md")
        assert not cdd.is_plan_doc("CONTRIBUTING.md")


# --- evaluate --------------------------------------------------------------

class TestEvaluate:
    def test_no_feature_files_passes(self):
        ok, msg = cdd.evaluate(
            added={"README.md", "tests/test_foo.py"},
            labels=set(),
        )
        assert ok
        assert msg == ""

    def test_feature_file_with_both_docs_passes(self):
        ok, msg = cdd.evaluate(
            added={
                "scripts/commands/mycommand.py",
                "docs/design/mycommand.md",
                "docs/plans/mycommand.md",
            },
            labels=set(),
        )
        assert ok
        assert msg == ""

    def test_feature_file_missing_design_doc_fails(self):
        ok, msg = cdd.evaluate(
            added={
                "scripts/commands/mycommand.py",
                "docs/plans/mycommand.md",
            },
            labels=set(),
        )
        assert not ok
        assert "design doc" in msg

    def test_feature_file_missing_plan_doc_fails(self):
        ok, msg = cdd.evaluate(
            added={
                "scripts/commands/mycommand.py",
                "docs/design/mycommand.md",
            },
            labels=set(),
        )
        assert not ok
        assert "plan doc" in msg

    def test_feature_file_missing_both_docs_lists_both(self):
        ok, msg = cdd.evaluate(
            added={"scripts/commands/mycommand.py"},
            labels=set(),
        )
        assert not ok
        assert "design doc" in msg
        assert "plan doc" in msg

    def test_skip_design_doc_label_exempts(self):
        ok, msg = cdd.evaluate(
            added={"scripts/commands/mycommand.py"},
            labels={"skip-design-doc"},
        )
        assert ok
        assert msg == ""

    def test_bug_label_exempts(self):
        ok, msg = cdd.evaluate(
            added={"scripts/commands/mycommand.py"},
            labels={"bug"},
        )
        assert ok

    def test_chore_label_exempts(self):
        ok, msg = cdd.evaluate(
            added={"scripts/commands/mycommand.py"},
            labels={"chore"},
        )
        assert ok

    def test_case_insensitive_labels(self):
        ok, msg = cdd.evaluate(
            added={"scripts/commands/mycommand.py"},
            labels={"Skip-Design-Doc"},
        )
        assert ok

    def test_template_only_does_not_satisfy(self):
        # Adding template.md as a "new" file does not count as adding a design doc
        ok, msg = cdd.evaluate(
            added={
                "scripts/commands/mycommand.py",
                "docs/design/template.md",
                "docs/plans/template.md",
            },
            labels=set(),
        )
        assert not ok

    def test_multiple_feature_files_listed_in_message(self):
        ok, msg = cdd.evaluate(
            added={
                "scripts/commands/foo.py",
                "scripts/commands/bar.py",
                "scripts/parsers/elixir_parser.py",
            },
            labels=set(),
        )
        assert not ok
        assert "scripts/commands/foo.py" in msg
        assert "scripts/commands/bar.py" in msg
        assert "scripts/parsers/elixir_parser.py" in msg


# --- End-to-end with real git ---------------------------------------------

class TestEndToEndWithGit:
    """Smoke-test the git interaction by creating a real (tiny) git repo,
    making a branch, adding files, and running the full main() entry point."""

    def test_passes_when_no_feature_files_added(self, tmp_path, monkeypatch):
        repo = _make_test_repo(tmp_path)
        # Add a non-feature file on a branch
        _commit(repo, "feature-branch", {"README.md": "# hi"})
        rc = _run_check(repo, "main", "feature-branch")
        assert rc == 0

    def test_fails_when_feature_file_added_without_docs(self, tmp_path):
        repo = _make_test_repo(tmp_path)
        _commit(repo, "feature-branch", {
            "scripts/commands/newcmd.py": "# new command",
        })
        rc = _run_check(repo, "main", "feature-branch")
        assert rc == 1

    def test_passes_when_feature_file_added_with_docs(self, tmp_path):
        repo = _make_test_repo(tmp_path)
        _commit(repo, "feature-branch", {
            "scripts/commands/newcmd.py": "# new command",
            "docs/design/newcmd.md": "# design",
            "docs/plans/newcmd.md": "# plan",
        })
        rc = _run_check(repo, "main", "feature-branch")
        assert rc == 0

    def test_passes_when_exempt_label_set(self, tmp_path, monkeypatch):
        repo = _make_test_repo(tmp_path)
        _commit(repo, "feature-branch", {
            "scripts/commands/newcmd.py": "# new command",
        })
        monkeypatch.setenv("GITHUB_PR_LABELS", "chore,dependencies")
        rc = _run_check(repo, "main", "feature-branch")
        assert rc == 0


# --- Helpers ---------------------------------------------------------------

def _make_test_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with one initial commit on `main`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.test"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    # Initial commit — at least one file so main is not empty
    (repo / ".gitignore").write_text("*.pyc\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True,
                   capture_output=True)
    return repo


def _commit(repo: Path, branch: str, files: dict) -> None:
    """Create `branch` from current HEAD, write `files`, commit them."""
    subprocess.run(["git", "checkout", "-b", branch], cwd=repo, check=True,
                   capture_output=True)
    for relpath, content in files.items():
        full = repo / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "test"], cwd=repo, check=True,
                   capture_output=True)


def _run_check(repo: Path, base: str, head: str) -> int:
    """Invoke check_design_doc.main() as a subprocess, return its exit code.

    The subprocess inherits the parent env (including any monkeypatched
    GITHUB_PR_LABELS). Tests that want to assert "no label set" should
    explicitly use monkeypatch.delenv to clear the var.
    """
    env = os.environ.copy()
    # Ensure a deterministic default: if no test has set GITHUB_PR_LABELS,
    # treat it as empty (no labels). Tests that need labels use
    # monkeypatch.setenv("GITHUB_PR_LABELS", "...") which writes into
    # os.environ before this copy is made.
    env.setdefault("GITHUB_PR_LABELS", "")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_design_doc.py"),
         "--base", base, "--head", head, "--repo-root", str(repo)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode
