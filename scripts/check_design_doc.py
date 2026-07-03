# @WHO:   scripts/check_design_doc.py
# @WHAT:  CI check — require a design doc in docs/design/ for new-feature PRs
# @PART:  ci
# @ENTRY: main()
"""
Design Doc Checker — CI gate for issue #67 Phase 1.

Detects "new feature" PRs by file pattern and fails if no design doc is
included in docs/design/. The check is bypassable via the ``skip-design-doc``
PR label for genuinely trivial features.

Usage (GitHub Actions):
    The workflow at .github/workflows/design-doc-check.yml calls this script
    with the environment variables GITHUB_TOKEN, GITHUB_REPOSITORY, and
    PR_NUMBER set. The script fetches the PR's files and labels via the
    GitHub API, runs the check, and exits 0 (pass) or 1 (fail).

Usage (local testing):
    python3 scripts/check_design_doc.py --files <file1> <file2> ... [--labels label1 label2]
    This mode is for unit testing and local pre-flight checks. It does not
    call the GitHub API.

@FLOW:    DESIGN_DOC_CHECK
@CALLS:   check_pr() -> CheckResult
@CALLS:   _fetch_pr_files() / _fetch_pr_labels() -> GitHub API (CI mode only)
@MUTATES: none (pure check — exits 0/1, prints to stdout)
"""

import argparse
import json
import os
import sys
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple


# ─── Configuration ───────────────────────────────────────────


# File patterns that indicate a "new feature" PR. Each entry is a tuple of
# (directory_prefix, status_filter) where status_filter is "added" (only new
# files trigger) or "any" (any change triggers).
#
# Rationale:
# - scripts/commands/ + added  → a new CLI command is a new feature
# - scripts/*_engine.py + added → a new engine is a new feature
# - scripts/formatters/ + added → a new output format is a new feature
# - scripts/parsers/ (non-fallback) + added → a new language parser is a feature
# - scripts/parsers/fallback_*.py is EXCLUDED — fallbacks are regex shadows
#   of existing tree-sitter parsers, not new features
# - scripts/mcp_server.py is EXCLUDED from "added" (it always exists) but
#   flagged on "any" modification IF a new tool definition is added. We
#   can't reliably detect "new tool definition" from a diff, so we don't
#   flag mcp_server.py changes. The contributor should add a design doc
#   if they added a new MCP tool, but the CI check doesn't enforce it.
_FEATURE_PATTERNS: List[Tuple[str, str]] = [
    ("scripts/commands/", "added"),
    ("scripts/formatters/", "added"),
]

# Engine files live directly in scripts/ with the suffix _engine.py.
# We detect these separately because they're not in a subdirectory.
_ENGINE_SUFFIX = "_engine.py"

# Parser files: scripts/parsers/<lang>_parser.py is a new feature, but
# scripts/parsers/fallback_<lang>.py is NOT (it's a regex fallback for an
# existing tree-sitter parser).
_PARSER_DIR = "scripts/parsers/"
_PARSER_SUFFIX = "_parser.py"
_FALLBACK_PREFIX = "fallback_"

# PR label that bypasses the design doc requirement.
BYPASS_LABEL = "skip-design-doc"

# Design doc directory.
DESIGN_DOC_DIR = "docs/design/"

# Plan directory (recommended but not enforced).
PLAN_DIR = "docs/plans/"


# ─── Pure Logic (unit-testable) ──────────────────────────────


def is_feature_file(filename: str, status: str) -> bool:
    """Return True if a file change represents a new feature.

    Args:
        filename: Path to the file in the PR (relative to repo root).
        status: One of "added", "modified", "removed", "renamed".

    Returns:
        True if this file pattern + status combination indicates a new
        feature that requires a design doc.
    """
    # New CLI command
    if filename.startswith("scripts/commands/") and status == "added":
        return True

    # New formatter
    if filename.startswith("scripts/formatters/") and status == "added":
        return True

    # New engine (scripts/<name>_engine.py, added)
    if (
        filename.startswith("scripts/")
        and filename.endswith(_ENGINE_SUFFIX)
        and "/" not in filename[len("scripts/"):]  # directly in scripts/, not a subdir
        and status == "added"
    ):
        return True

    # New parser (scripts/parsers/<lang>_parser.py, added) — exclude fallbacks
    if (
        filename.startswith(_PARSER_DIR)
        and filename.endswith(_PARSER_SUFFIX)
        and status == "added"
    ):
        basename = filename[len(_PARSER_DIR):]
        if not basename.startswith(_FALLBACK_PREFIX):
            return True

    return False


def check_pr(
    pr_files: List[Dict[str, Any]],
    pr_labels: List[str],
) -> Dict[str, Any]:
    """Check whether a PR requires and includes a design doc.

    This is the pure-logic entry point — no I/O, no API calls. It takes the
    PR's files (as returned by the GitHub API, with ``filename`` and
    ``status`` keys) and labels (as a list of strings), and returns a
    result dict describing whether the check passed and why.

    Args:
        pr_files: List of dicts, each with at least ``filename`` and
            ``status`` keys (matching the GitHub PR files API response).
        pr_labels: List of label names on the PR.

    Returns:
        Dict with keys:
            - ``passed`` (bool): True if the PR passes the check
            - ``reason`` (str): Human-readable explanation
            - ``feature_files`` (list[str]): Files that triggered the
              feature requirement
            - ``design_docs`` (list[str]): Design docs added in this PR
            - ``bypassed`` (bool): True if the check was bypassed via label
    """
    # Detect feature files
    feature_files = [
        f["filename"] for f in pr_files
        if is_feature_file(f.get("filename", ""), f.get("status", ""))
    ]

    # Detect design docs added in this PR
    design_docs = [
        f["filename"] for f in pr_files
        if f.get("filename", "").startswith(DESIGN_DOC_DIR)
        and f.get("filename", "").endswith(".md")
        and f.get("status") in ("added", "modified", "renamed")
    ]

    # Bypass via label
    if BYPASS_LABEL in pr_labels:
        return {
            "passed": True,
            "reason": (
                f"PR has '{BYPASS_LABEL}' label — design doc requirement "
                f"bypassed."
            ),
            "feature_files": feature_files,
            "design_docs": design_docs,
            "bypassed": True,
        }

    # No feature files → check passes silently
    if not feature_files:
        return {
            "passed": True,
            "reason": (
                "PR does not add new feature files (no new commands, "
                "engines, formatters, or parsers). Design doc not required."
            ),
            "feature_files": [],
            "design_docs": design_docs,
            "bypassed": False,
        }

    # Feature files present → require a design doc
    if design_docs:
        return {
            "passed": True,
            "reason": (
                f"PR adds feature file(s) and includes design doc(s): "
                f"{', '.join(design_docs)}."
            ),
            "feature_files": feature_files,
            "design_docs": design_docs,
            "bypassed": False,
        }

    # Feature files present, no design doc → FAIL
    return {
        "passed": False,
        "reason": (
            f"PR adds new feature file(s) ({', '.join(feature_files)}) but "
            f"does not include a design doc in {DESIGN_DOC_DIR}. "
            f"Copy docs/design/template.md to docs/design/NNNN-feature-name.md "
            f"and describe the design decisions. "
            f"If this is genuinely trivial, add the '{BYPASS_LABEL}' label "
            f"to bypass this check."
        ),
        "feature_files": feature_files,
        "design_docs": [],
        "bypassed": False,
    }


# ─── GitHub API I/O (CI mode only) ───────────────────────────


def _github_api(url: str, token: str) -> Any:
    """Fetch JSON from the GitHub API with authentication."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "design-doc-checker",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def fetch_pr_files(repo: str, pr_number: int, token: str) -> List[Dict[str, Any]]:
    """Fetch the list of files changed in a PR via the GitHub API.

    Handles pagination — PRs with >100 files require multiple requests.
    """
    all_files: List[Dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
            f"?per_page=100&page={page}"
        )
        batch = _github_api(url, token)
        if not batch:
            break
        all_files.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return all_files


def fetch_pr_labels(repo: str, pr_number: int, token: str) -> List[str]:
    """Fetch the labels on a PR via the GitHub API."""
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    data = _github_api(url, token)
    return [label["name"] for label in data.get("labels", [])]


# ─── CLI Entry Point ─────────────────────────────────────────


def main() -> int:
    """CLI entry point.

    Two modes:
    1. CI mode (default): reads GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER
       env vars and fetches PR data from the GitHub API.
    2. Local mode (--files): reads file list and labels from command-line
       args, for unit testing and local pre-flight checks.

    Returns:
        0 if the check passes, 1 if it fails.
    """
    parser = argparse.ArgumentParser(
        description="Check whether a PR requires and includes a design doc.",
    )
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="Local mode: list of changed files (space-separated paths). "
             "When provided, the script does not call the GitHub API.",
    )
    parser.add_argument(
        "--labels", nargs="*", default=[],
        help="Local mode: PR labels (space-separated).",
    )
    parser.add_argument(
        "--status", nargs="*", default=None,
        help="Local mode: status for each file (--files), in the same order. "
             "Values: added, modified, removed, renamed. If omitted, all "
             "files are assumed 'added'.",
    )
    args = parser.parse_args()

    if args.files is not None:
        # Local mode
        statuses = args.status if args.status else ["added"] * len(args.files)
        if len(statuses) != len(args.files):
            print(
                f"Error: --files has {len(args.files)} items but --status has "
                f"{len(statuses)} items. They must be the same length.",
                file=sys.stderr,
            )
            return 2
        pr_files = [
            {"filename": f, "status": s}
            for f, s in zip(args.files, statuses)
        ]
        pr_labels = args.labels
    else:
        # CI mode — read env vars
        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY")
        pr_number_str = os.environ.get("PR_NUMBER")

        if not all([token, repo, pr_number_str]):
            print(
                "Error: CI mode requires GITHUB_TOKEN, GITHUB_REPOSITORY, "
                "and PR_NUMBER environment variables. For local testing, "
                "use --files <path1> <path2> ...",
                file=sys.stderr,
            )
            return 2

        pr_number = int(pr_number_str)
        print(f"Fetching PR #{pr_number} files and labels from {repo}...",
              file=sys.stderr)
        try:
            pr_files = fetch_pr_files(repo, pr_number, token)
            pr_labels = fetch_pr_labels(repo, pr_number, token)
        except Exception as exc:
            print(f"Error fetching PR data: {exc}", file=sys.stderr)
            return 2

    # Run the check
    result = check_pr(pr_files, pr_labels)

    # Print result
    status_word = "PASS" if result["passed"] else "FAIL"
    print(f"[design-doc-check] {status_word}")
    print(f"[design-doc-check] {result['reason']}")

    if result["feature_files"]:
        print(f"[design-doc-check] Feature files: {', '.join(result['feature_files'])}")
    if result["design_docs"]:
        print(f"[design-doc-check] Design docs: {', '.join(result['design_docs'])}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
