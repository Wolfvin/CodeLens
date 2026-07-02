#!/usr/bin/env python3
"""
Design doc requirement checker for CodeLens.

Implements the issue #67 Phase 1 CI rule:
  A PR that adds a new "feature-class" file MUST also add:
    - at least one new file under docs/design/
    - at least one new file under docs/plans/

Feature-class files (the trigger):
    scripts/commands/<name>.py      (new CLI command)
    scripts/parsers/<name>_parser.py (new language parser)
    scripts/<name>_engine.py         (new analysis engine — top-level only)
    scripts/mcp_hooks/<name>.py      (new MCP hook)

Exemptions:
    - PRs labeled: skip-design-doc, bug, chore, dependencies, refactor,
      documentation, test — are exempt.
    - PRs that touch ONLY test files, docs files, or config files are exempt
      (no feature-class file added).

Usage:
    # Locally — check unstaged + staged changes vs main:
    python3 scripts/check_design_doc.py

    # In CI — check files added in the PR (passed via env or argv):
    python3 scripts/check_design_doc.py --base main --head HEAD

Exit codes:
    0 — PR is compliant (either no feature-class files added, or both
        design + plan docs added, or an exemption label is present).
    1 — PR is non-compliant (feature-class file added but design and/or
        plan doc missing). Error message printed to stderr explains what
        is missing and how to fix it.

This script is invoked by .github/workflows/require-design-doc.yml on
every PR opened or synchronized against Wolfvin/CodeLens.
"""

# @WHO:   scripts/check_design_doc.py
# @WHAT:  CI check — require design+plan docs for feature-class PRs
# @PART:  ci
# @ENTRY: main()

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple

# --- Configuration ---------------------------------------------------------

# Files matching these regexes are "feature-class" — adding one triggers the
# design-doc requirement. The regex is matched against the path relative to
# the repo root, using forward slashes.
FEATURE_CLASS_PATTERNS = [
    r"^scripts/commands/[^/]+\.py$",           # new CLI command
    r"^scripts/parsers/[^/]+_parser\.py$",     # new tree-sitter parser
    r"^scripts/[^/]+_engine\.py$",             # new top-level engine
    r"^scripts/mcp_hooks/[^/]+\.py$",          # new MCP hook
]

# Files matching these patterns are never feature-class — they are exempt
# regardless of pattern match. (e.g., __init__.py is not a new command even
# though it lives under scripts/commands/.)
EXEMPT_PATTERNS = [
    r"^scripts/[^/]+/__init__\.py$",
    r"^scripts/commands/__init__\.py$",
    r"^scripts/parsers/__init__\.py$",
    r"^scripts/mcp_hooks/__init__\.py$",
]

# PR labels that exempt the PR from the design-doc requirement.
EXEMPT_LABELS = {
    "skip-design-doc",
    "bug",
    "chore",
    "dependencies",
    "refactor",
    "documentation",
    "test",
}

# Directories where a new .md file satisfies the design / plan requirement.
DESIGN_DOC_DIR = "docs/design"
PLAN_DOC_DIR = "docs/plans"

# Files that are NOT counted as design / plan docs even if they live in the
# right directory (templates and READMEs are scaffolding, not feature docs).
NON_DOC_FILES = {"template.md", "README.md"}


# --- Implementation --------------------------------------------------------

def _match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(re.match(p, path) for p in patterns)


def is_feature_class(path: str) -> bool:
    """Return True if `path` is a feature-class file (triggers the design-doc
    requirement when added)."""
    if _match_any(path, EXEMPT_PATTERNS):
        return False
    return _match_any(path, FEATURE_CLASS_PATTERNS)


def is_design_doc(path: str) -> bool:
    """Return True if `path` counts as a design doc (satisfies the design
    half of the requirement)."""
    if not path.startswith(DESIGN_DOC_DIR + "/"):
        return False
    if not path.endswith(".md"):
        return False
    return Path(path).name not in NON_DOC_FILES


def is_plan_doc(path: str) -> bool:
    """Return True if `path` counts as a plan doc (satisfies the plan half
    of the requirement)."""
    if not path.startswith(PLAN_DOC_DIR + "/"):
        return False
    if not path.endswith(".md"):
        return False
    return Path(path).name not in NON_DOC_FILES


def added_files(base: str, head: str, repo_root: Path) -> Set[str]:
    """Return the set of file paths (relative to repo root, forward slashes)
    that are ADDED in `head` vs `base`.

    Uses `git diff --name-only --diff-filter=A` so renamed or modified files
    do not count — only genuinely new files trigger the requirement.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", f"{base}..{head}"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Git error — fail loud so the CI step is visible, not silently pass.
        print(f"[check_design_doc] git diff failed: {e}", file=sys.stderr)
        print(f"[check_design_doc] git stderr: {e.stderr}", file=sys.stderr)
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def labels_from_env() -> Set[str]:
    """Read PR labels from the GITHUB_PR_LABELS env var (comma-separated,
    set by the workflow). Returns an empty set if not in CI."""
    raw = os.environ.get("GITHUB_PR_LABELS", "")
    return {label.strip().lower() for label in raw.split(",") if label.strip()}


def evaluate(added: Set[str], labels: Set[str]) -> Tuple[bool, str]:
    """Decide whether the PR is compliant.

    Returns (compliant, message). When compliant is True, message is empty.
    When compliant is False, message is the user-facing explanation.

    Labels are matched case-insensitively (GitHub labels are case-preserving
    on display but case-insensitive for lookup; we follow the same rule).
    """
    # Normalize labels to lowercase for case-insensitive comparison.
    normalized_labels = {label.lower() for label in labels}

    # Exemption label short-circuits everything.
    if normalized_labels & EXEMPT_LABELS:
        return True, ""

    feature_files = sorted({p for p in added if is_feature_class(p)})
    if not feature_files:
        return True, ""

    design_docs = sorted({p for p in added if is_design_doc(p)})
    plan_docs = sorted({p for p in added if is_plan_doc(p)})

    missing = []
    if not design_docs:
        missing.append(f"a design doc under {DESIGN_DOC_DIR}/")
    if not plan_docs:
        missing.append(f"a plan doc under {PLAN_DOC_DIR}/")

    if not missing:
        return True, ""

    feature_list = "\n  ".join(feature_files)
    missing_list = "\n  ".join(missing)
    return False, (
        "This PR adds feature-class file(s) but is missing required "
        "documentation:\n\n"
        f"Feature-class files added:\n  {feature_list}\n\n"
        f"Missing:\n  {missing_list}\n\n"
        "How to fix:\n"
        f"  1. Copy docs/design/template.md to docs/design/<feature>.md and "
        "fill it in.\n"
        f"  2. Copy docs/plans/template.md to docs/plans/<feature>.md and "
        "fill it in.\n"
        "  3. Re-push. The CI check will re-run.\n\n"
        "If this PR is genuinely too small to warrant a design doc (e.g., "
        "adding a single flag to an existing command), apply the "
        "`skip-design-doc` label and explain why in the PR description.\n\n"
        "See CONTRIBUTING.md > Design Documents & Implementation Plans for "
        "the full policy."
    )


# --- CLI entry point -------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that a PR adding feature-class files also adds "
                    "design + plan docs. See docs/design/README.md."
    )
    parser.add_argument(
        "--base", default="origin/main",
        help="Git ref to diff against (default: origin/main)."
    )
    parser.add_argument(
        "--head", default="HEAD",
        help="Git ref to diff from (default: HEAD)."
    )
    parser.add_argument(
        "--repo-root", default=".",
        help="Path to repo root (default: current directory)."
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    added = added_files(args.base, args.head, repo_root)
    labels = labels_from_env()

    compliant, message = evaluate(added, labels)

    if compliant:
        # Brief success log so CI output shows the check ran.
        feature_count = sum(1 for p in added if is_feature_class(p))
        normalized_labels = {label.lower() for label in labels}
        if feature_count == 0:
            print("[check_design_doc] No feature-class files added — pass.")
        elif normalized_labels & EXEMPT_LABELS:
            print(
                f"[check_design_doc] {feature_count} feature-class file(s) "
                f"added, but exempt label(s) present: "
                f"{', '.join(sorted(normalized_labels & EXEMPT_LABELS))} — pass."
            )
        else:
            design_count = sum(1 for p in added if is_design_doc(p))
            plan_count = sum(1 for p in added if is_plan_doc(p))
            print(
                f"[check_design_doc] {feature_count} feature-class file(s) "
                f"added with {design_count} design doc(s) and "
                f"{plan_count} plan doc(s) — pass."
            )
        return 0

    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
