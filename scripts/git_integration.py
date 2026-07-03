# @WHO:   scripts/git_integration.py
# @WHAT:  CI/CD git integration helpers — staged/working-tree/diff-vs file lists + CI env detection
# @PART:  ci
# @ENTRY: list_staged_files(), list_working_tree_changes(), list_diff_vs(), resolve_baseline_sha()
"""
CodeLens CI/CD git integration helpers (issue #57, Phase 1).

Thin wrapper around ``git_aware.py`` that adds the CI/CD-specific diff
modes needed by the new ``--diff-scan`` / ``--staged`` / ``--diff-vs`` /
``--baseline-commit`` flags:

- ``list_staged_files(workspace)``         → ``git diff --cached --name-only --diff-filter=ACMR``
- ``list_working_tree_changes(workspace)`` → ``git diff --name-only HEAD``
- ``list_diff_vs(workspace, ref)``         → ``git diff --name-only <ref>``
- ``resolve_baseline_sha(workspace, requested_sha)``:
    * If ``requested_sha`` is None and env var ``CODELENS_BASELINE_SHA``
      is set → use it (GitHub Actions PR base SHA injection point).
    * Otherwise fall back to ``HEAD~1`` (single-commit parent), or None
      if the repo has no commits.

This module is optional in the sense that every function returns an
empty list / None when git is unavailable or the workspace is not a
git repo, so the caller can degrade gracefully.

Design rules (issue #57):
- No external deps (uses ``subprocess`` via git_aware._run_git).
- Pure helpers — no finding logic, no SARIF, no VULN_DB lookups here.
- Reuses git_aware._run_git so we get the same "git optional" semantics
  as the rest of the codebase.
"""

from __future__ import annotations

import os
from typing import List, Optional

from git_aware import _run_git
from utils import logger


# Env var that GitHub Actions / GitLab CI workflows can set to inject
# the PR base SHA. ``codelens ci`` (Phase 3, future PR) will set this
# automatically; for now users can set it manually.
ENV_BASELINE_SHA = "CODELENS_BASELINE_SHA"


def list_staged_files(workspace: str) -> List[str]:
    """Return files staged for commit (Added/Copied/Modified/Renamed).

    Equivalent to ``git diff --cached --name-only --diff-filter=ACMR``.
    Returns ``[]`` if git is unavailable, the workspace is not a git
    repo, or there are no staged changes.
    """
    out = _run_git(
        workspace,
        ["diff", "--cached", "--name-only", "--diff-filter=ACMR"],
    )
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def list_working_tree_changes(workspace: str) -> List[str]:
    """Return files changed in the working tree vs HEAD (uncommitted).

    Equivalent to ``git diff --name-only HEAD``. Includes both staged
    and unstaged changes. Returns ``[]`` if git is unavailable or
    there are no changes.
    """
    out = _run_git(workspace, ["diff", "--name-only", "HEAD"])
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def list_diff_vs(workspace: str, ref: str) -> List[str]:
    """Return files changed between ``ref`` and the working tree.

    Equivalent to ``git diff --name-only <ref>``. The ``ref`` may be a
    commit SHA, a branch name, or any git rev-parse-able expression
    (``HEAD~3``, ``origin/main``, ``v1.2.0``, etc.).
    """
    if not ref:
        return []
    # Validate the ref exists before diffing — ``git diff`` on a bad
    # ref prints to stderr and exits non-zero, which _run_git turns
    # into None. We log a clearer message here.
    rev_check = _run_git(workspace, ["rev-parse", "--verify", ref])
    if not rev_check:
        logger.warning(
            "git_integration: baseline ref %r could not be resolved — "
            "no diff will be computed (returning empty file list)", ref,
        )
        return []
    out = _run_git(workspace, ["diff", "--name-only", ref])
    if not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def resolve_baseline_sha(
    workspace: str, requested_sha: Optional[str] = None
) -> Optional[str]:
    """Resolve the baseline commit SHA for ``--baseline-commit``.

    Resolution order:
    1. ``requested_sha`` (explicit ``--baseline-commit <SHA>`` arg).
    2. ``$CODELENS_BASELINE_SHA`` env var (CI injection point).
    3. ``HEAD~1`` (the parent of the current commit) — only meaningful
       in a non-bare repo with at least 2 commits.

    Returns ``None`` if none of the above resolve to a valid SHA.
    """
    candidates: List[str] = []
    if requested_sha:
        candidates.append(requested_sha)
    env_sha = os.environ.get(ENV_BASELINE_SHA)
    if env_sha:
        candidates.append(env_sha)

    for cand in candidates:
        # Normalise: accept short SHAs by resolving via rev-parse.
        verified = _run_git(workspace, ["rev-parse", "--verify", cand])
        if verified:
            return verified

    # Fall back to HEAD~1.
    head_parent = _run_git(workspace, ["rev-parse", "--verify", "HEAD~1"])
    if head_parent:
        return head_parent

    logger.debug(
        "git_integration: no baseline SHA resolved (requested=%r, env=%r, HEAD~1 unavailable)",
        requested_sha, env_sha,
    )
    return None


def detect_ci_environment() -> Optional[str]:
    """Detect which CI/CD platform we are running under.

    Returns one of: ``"github"``, ``"gitlab"``, ``"jenkins"``,
    ``"bitbucket"``, ``"circleci"``, or ``None`` if no known CI env
    vars are set.

    Phase 3 (``codelens ci`` command) uses this to pick the right
    SARIF upload behaviour. Exposed here so tests can mock it.
    """
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return "github"
    if os.environ.get("GITLAB_CI"):
        return "gitlab"
    if os.environ.get("JENKINS_URL"):
        return "jenkins"
    if os.environ.get("BITBUCKET_BUILD_NUMBER"):
        return "bitbucket"
    if os.environ.get("CIRCLECI"):
        return "circleci"
    return None


__all__ = [
    "ENV_BASELINE_SHA",
    "list_staged_files",
    "list_working_tree_changes",
    "list_diff_vs",
    "resolve_baseline_sha",
    "detect_ci_environment",
]
