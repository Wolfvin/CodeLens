"""
Tests for the CI/CD git integration helpers (issue #57 Phase 1).

Covers ``scripts/git_integration.py``:
- ``list_staged_files`` / ``list_working_tree_changes`` / ``list_diff_vs``
  against a real temporary git repository (no mocking needed because
  we create a fresh repo via subprocess).
- ``resolve_baseline_sha`` resolution order (explicit > env > HEAD~1).
- ``detect_ci_environment`` recognition of GitHub/GitLab/Jenkins/etc
  env vars.
- Graceful failure when the workspace is not a git repo.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pytest

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from git_integration import (  # noqa: E402
    ENV_BASELINE_SHA,
    detect_ci_environment,
    list_diff_vs,
    list_staged_files,
    list_working_tree_changes,
    resolve_baseline_sha,
)


# ─── Helpers ─────────────────────────────────────────────────


def _git(workspace, *args):
    """Run a git command inside workspace, return CompletedProcess."""
    return subprocess.run(
        ["git", *args], cwd=workspace, capture_output=True, text=True, check=True
    )


def _make_repo(tmp_path):
    """Create a fresh git repo with one commit, return the path."""
    ws = str(tmp_path / "repo")
    os.makedirs(ws, exist_ok=True)
    _git(ws, "init", "--quiet")
    _git(ws, "config", "user.email", "test@example.com")
    _git(ws, "config", "user.name", "Test")
    # First commit
    with open(os.path.join(ws, "a.py"), "w") as f:
        f.write("print('hello')\n")
    _git(ws, "add", "a.py")
    _git(ws, "commit", "--quiet", "-m", "initial")
    return ws


def _make_second_commit(ws):
    """Add a second commit on top so HEAD~1 exists."""
    with open(os.path.join(ws, "b.py"), "w") as f:
        f.write("print('world')\n")
    _git(ws, "add", "b.py")
    _git(ws, "commit", "--quiet", "-m", "second")
    return ws


# ─── Non-git workspace ───────────────────────────────────────


class TestNonGitWorkspace:
    def test_all_functions_return_empty_on_non_git_dir(self, tmp_path):
        ws = str(tmp_path / "not-a-repo")
        os.makedirs(ws, exist_ok=True)
        assert list_staged_files(ws) == []
        assert list_working_tree_changes(ws) == []
        assert list_diff_vs(ws, "main") == []
        # resolve_baseline_sha falls back to HEAD~1 which doesn't exist
        # in a non-git repo → returns None
        assert resolve_baseline_sha(ws, None) is None

    def test_detect_ci_environment_no_env(self, monkeypatch):
        for var in (
            "GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL",
            "BITBUCKET_BUILD_NUMBER", "CIRCLECI",
        ):
            monkeypatch.delenv(var, raising=False)
        assert detect_ci_environment() is None


# ─── detect_ci_environment ────────────────────────────────────


class TestDetectCiEnvironment:
    def test_github_actions(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        for var in ("GITLAB_CI", "JENKINS_URL", "BITBUCKET_BUILD_NUMBER", "CIRCLECI"):
            monkeypatch.delenv(var, raising=False)
        assert detect_ci_environment() == "github"

    def test_gitlab(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv("GITLAB_CI", "true")
        for var in ("JENKINS_URL", "BITBUCKET_BUILD_NUMBER", "CIRCLECI"):
            monkeypatch.delenv(var, raising=False)
        assert detect_ci_environment() == "gitlab"

    def test_jenkins(self, monkeypatch):
        for var in ("GITHUB_ACTIONS", "GITLAB_CI", "BITBUCKET_BUILD_NUMBER", "CIRCLECI"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("JENKINS_URL", "https://jenkins.example.com")
        assert detect_ci_environment() == "jenkins"

    def test_bitbucket(self, monkeypatch):
        for var in ("GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "CIRCLECI"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("BITBUCKET_BUILD_NUMBER", "42")
        assert detect_ci_environment() == "bitbucket"

    def test_circleci(self, monkeypatch):
        for var in ("GITHUB_ACTIONS", "GITLAB_CI", "JENKINS_URL", "BITBUCKET_BUILD_NUMBER"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CIRCLECI", "true")
        assert detect_ci_environment() == "circleci"


# ─── list_staged_files ────────────────────────────────────────


class TestListStagedFiles:
    def test_returns_empty_with_no_staged_changes(self, tmp_path):
        ws = _make_repo(tmp_path)
        assert list_staged_files(ws) == []

    def test_returns_staged_files(self, tmp_path):
        ws = _make_repo(tmp_path)
        # Create a new file and stage it
        with open(os.path.join(ws, "new.py"), "w") as f:
            f.write("x = 1\n")
        _git(ws, "add", "new.py")
        staged = list_staged_files(ws)
        assert "new.py" in staged

    def test_filters_non_acmr(self, tmp_path):
        ws = _make_repo(tmp_path)
        # Create a file, commit, then delete it (D filter should exclude it)
        with open(os.path.join(ws, "to_delete.py"), "w") as f:
            f.write("y = 2\n")
        _git(ws, "add", "to_delete.py")
        _git(ws, "commit", "--quiet", "-m", "add to_delete")
        _git(ws, "rm", "--quiet", "to_delete.py")
        # Staged deletion should NOT appear (--diff-filter=ACMR excludes D)
        staged = list_staged_files(ws)
        assert "to_delete.py" not in staged


# ─── list_working_tree_changes ────────────────────────────────


class TestListWorkingTreeChanges:
    def test_returns_empty_with_no_changes(self, tmp_path):
        ws = _make_repo(tmp_path)
        assert list_working_tree_changes(ws) == []

    def test_returns_modified_files(self, tmp_path):
        ws = _make_repo(tmp_path)
        # Modify a.py without staging
        with open(os.path.join(ws, "a.py"), "w") as f:
            f.write("print('modified')\n")
        changes = list_working_tree_changes(ws)
        assert "a.py" in changes

    def test_includes_untracked_files_after_add(self, tmp_path):
        ws = _make_repo(tmp_path)
        # Create untracked file (no add)
        with open(os.path.join(ws, "untracked.py"), "w") as f:
            f.write("z = 3\n")
        # git diff HEAD does NOT show untracked, only modified
        # (this is a documented behaviour — the test documents it)
        changes = list_working_tree_changes(ws)
        assert "untracked.py" not in changes


# ─── list_diff_vs ─────────────────────────────────────────────


class TestListDiffVs:
    def test_returns_empty_for_same_ref(self, tmp_path):
        ws = _make_repo(tmp_path)
        assert list_diff_vs(ws, "HEAD") == []

    def test_returns_files_changed_vs_old_commit(self, tmp_path):
        ws = _make_repo(tmp_path)
        first_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True
        ).strip()
        _make_second_commit(ws)
        # Diff against first commit should show b.py
        changed = list_diff_vs(ws, first_sha)
        assert "b.py" in changed

    def test_invalid_ref_returns_empty(self, tmp_path):
        ws = _make_repo(tmp_path)
        assert list_diff_vs(ws, "nonexistent-branch") == []

    def test_empty_ref_returns_empty(self, tmp_path):
        ws = _make_repo(tmp_path)
        assert list_diff_vs(ws, "") == []


# ─── resolve_baseline_sha ─────────────────────────────────────


class TestResolveBaselineSha:
    def test_explicit_sha_wins(self, tmp_path, monkeypatch):
        ws = _make_repo(tmp_path)
        _make_second_commit(ws)
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True
        ).strip()
        # Even with env set, explicit arg wins
        monkeypatch.setenv(ENV_BASELINE_SHA, "env-value-that-doesnt-exist")
        result = resolve_baseline_sha(ws, head_sha)
        assert result == head_sha

    def test_env_var_used_when_no_explicit(self, tmp_path, monkeypatch):
        ws = _make_repo(tmp_path)
        _make_second_commit(ws)
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True
        ).strip()
        monkeypatch.setenv(ENV_BASELINE_SHA, head_sha)
        result = resolve_baseline_sha(ws, None)
        assert result == head_sha

    def test_head_parent_fallback(self, tmp_path, monkeypatch):
        ws = _make_repo(tmp_path)
        _make_second_commit(ws)
        parent_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD~1"], cwd=ws, text=True
        ).strip()
        for var in (ENV_BASELINE_SHA,):
            monkeypatch.delenv(var, raising=False)
        result = resolve_baseline_sha(ws, None)
        assert result == parent_sha

    def test_returns_none_for_invalid_explicit(self, tmp_path, monkeypatch):
        ws = _make_repo(tmp_path)
        # Single commit → HEAD~1 doesn't exist; invalid explicit SHA → None
        for var in (ENV_BASELINE_SHA,):
            monkeypatch.delenv(var, raising=False)
        result = resolve_baseline_sha(ws, "totally-invalid-sha")
        assert result is None

    def test_short_sha_resolved_to_full(self, tmp_path, monkeypatch):
        ws = _make_repo(tmp_path)
        _make_second_commit(ws)
        head_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ws, text=True
        ).strip()
        short = head_sha[:8]
        for var in (ENV_BASELINE_SHA,):
            monkeypatch.delenv(var, raising=False)
        result = resolve_baseline_sha(ws, short)
        assert result == head_sha
