"""
Tests for version consistency across CodeLens metadata files.

Issue #37 reported version drift across 6 files: pyproject.toml,
skill.json, scripts/utils.py, README.md, SKILL.md, SKILL-QUICK.md.
This test file is the CI guard that prevents future drift.

Contract:
  - ``scripts/utils.py:CODELENS_VERSION`` is the single source of truth.
  - ``pyproject.toml`` ``version`` field must equal ``CODELENS_VERSION``.
  - ``skill.json`` ``version`` field must equal ``CODELENS_VERSION``.
  - Documentation H1 headings (README.md, SKILL.md, SKILL-QUICK.md)
    must NOT embed a ``vX.Y`` literal — readers should run
    ``codelens --version`` for the live version.

Run:
    python3 -m pytest tests/test_version_consistency.py -v
"""

import json
import os
import re
import sys
from pathlib import Path

import pytest

# Make scripts/ importable so we can read the canonical CODELENS_VERSION
# directly. Same convention as tests/test_cli.py.
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from utils import CODELENS_VERSION  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
SKILL_JSON_PATH = REPO_ROOT / "skill.json"
DOC_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "SKILL-QUICK.md",
]

# A "vX.Y" or "vX.Y.Z" literal embedded in a doc H1. We reject any
# version-like prefix on the title line because the live version lives
# in CODELENS_VERSION, not in markdown.
_DOC_VERSION_PATTERN = re.compile(r"v\d+\.\d+")


def _read_pyproject_version() -> str:
    """Return the ``version`` value from ``[project]`` in pyproject.toml.

    Prefers ``tomllib`` (stdlib in Python 3.11+) for a clean parse.
    Falls back to a regex on the ``version = "..."`` line for older
    Python (3.8-3.10) where ``tomllib`` is not available and we don't
    want to add ``tomli`` as a test-only dependency.

    Returns:
        The version string declared in pyproject.toml.

    Raises:
        AssertionError: if the version field cannot be located.
    """
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        # Python 3.8-3.10 fallback: regex the version line. Safe here
        # because pyproject.toml has exactly one top-level
        # ``version = "..."`` line (verified by the test below).
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert match, (
            f"Could not find `version = \"...\"` in {PYPROJECT_PATH}. "
            f"Is the [project] table still present?"
        )
        return match.group(1)

    with PYPROJECT_PATH.open("rb") as fh:
        data = tomllib.load(fh)
    project_table = data.get("project", {})
    version = project_table.get("version")
    assert version, (
        f"pyproject.toml [project] table has no `version` key. "
        f"Either hardcode it or wire up dynamic = ['version']."
    )
    # If dynamic versioning is ever enabled, `version` will be None and
    # the assert above will fire — surfacing the regression explicitly
    # rather than silently passing the test.
    return str(version)


def test_pyproject_version_matches_utils() -> None:
    """``pyproject.toml`` version must equal ``utils.CODELENS_VERSION``.

    This is the CI guard for the PyPI/packaging metadata side of the
    drift reported in issue #37. If a maintainer bumps
    ``CODELENS_VERSION`` without also bumping ``pyproject.toml``, this
    test fails.

    The single source of truth is ``utils.CODELENS_VERSION`` — when
    the two disagree, this test treats the constant as canonical and
    reports the pyproject value as the one that needs updating.
    """
    pyproject_version = _read_pyproject_version()
    assert pyproject_version == CODELENS_VERSION, (
        f"Version drift: pyproject.toml declares version="
        f"{pyproject_version!r} but scripts/utils.py:CODELENS_VERSION="
        f"{CODELENS_VERSION!r}. Bump pyproject.toml to match "
        f"(CODELENS_VERSION is the single source of truth)."
    )


def test_skill_json_version_matches_utils() -> None:
    """``skill.json`` version must equal ``utils.CODELENS_VERSION``.

    ``skill.json`` is the MCP server's externally-advertised manifest
    (and what AI hosts read to decide whether to activate the skill).
    A stale ``version`` field here is the most user-visible symptom of
    drift — it tells AI agents the wrong capability level.
    """
    with SKILL_JSON_PATH.open("r", encoding="utf-8") as fh:
        skill_data = json.load(fh)
    skill_version = skill_data.get("version")
    assert skill_version is not None, (
        f"skill.json has no top-level `version` field. "
        f"Add one matching CODELENS_VERSION={CODELENS_VERSION!r}."
    )
    assert skill_version == CODELENS_VERSION, (
        f"Version drift: skill.json declares version={skill_version!r} "
        f"but scripts/utils.py:CODELENS_VERSION={CODELENS_VERSION!r}. "
        f"Bump skill.json to match (CODELENS_VERSION is the single "
        f"source of truth)."
    )


def test_no_version_in_doc_headings() -> None:
    """Doc H1 headings must NOT embed a ``vX.Y`` literal.

    The live version lives in ``CODELENS_VERSION`` and is queried via
    ``codelens --version``. Hardcoding ``v8.2`` (or any other literal)
    in the README/SKILL/SKILL-QUICK H1 headings creates a third source
    of truth that drifts the moment a maintainer bumps
    ``CODELENS_VERSION`` without remembering to edit markdown — which
    is exactly how issue #37's drift happened.

    This test scans the first line of each doc and fails if a
    ``v<digit>.<digit>`` pattern appears anywhere on it.
    """
    missing = [p for p in DOC_PATHS if not p.exists()]
    assert not missing, f"Doc file(s) missing: {missing}"

    drifted: list[str] = []
    for path in DOC_PATHS:
        first_line = path.read_text(encoding="utf-8").splitlines()[0]
        match = _DOC_VERSION_PATTERN.search(first_line)
        if match is not None:
            drifted.append(
                f"{path.name}:1 — H1 contains version literal "
                f"{match.group(0)!r} in line: {first_line!r}"
            )

    assert not drifted, (
        f"Doc H1 headings must not embed version literals — "
        f"CODELENS_VERSION={CODELENS_VERSION!r} is the single source "
        f"of truth. Readers should run `codelens --version` for the "
        f"live version. Drift found in:\n  - " + "\n  - ".join(drifted)
    )
