# @WHO:   scripts/orient_lib/file_ranker.py
# @WHAT:  Start Here file ranking — score source files by reading priority
# @PART:  orient
# @ENTRY: rank_start_here_files()

"""
Start Here file ranker for the ``codelens orient`` command.

Scores every source file in the workspace and returns the top N files
that a developer should read first when entering an unfamiliar repo.
Scoring criteria (each contributes to a 0–100 score):

- **Filename pattern** — ``main``, ``app``, ``index``, ``server`` score
  high; test/migration/generated files are skipped entirely.
- **Directory depth** — shallower files score higher (root-level files
  are usually entry points or key configs).
- **Line count** — 50–500 lines is the sweet spot; very small or very
  large files get penalized.
- **Directory context** — files in ``src/``, ``lib/``, ``app/``,
  ``cmd/``, ``internal/`` score higher than ``vendor/`` or ``dist/``.

Skip rules (file is excluded entirely):
- test files (``test_*``, ``*_test.py``, ``*.spec.ts``, ``__tests__``)
- migrations (``migrations/``, ``alembic/``)
- generated code (``*.generated.*``, ``dist/``, ``build/``)
- config-only files (``*.config.js``, ``*.json``, ``*.lock`` — except
  ``package.json`` which is handled by entry point detection)

Reference: issue #160.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Tuple

__all__ = ["rank_start_here_files"]

_logger = logging.getLogger("codelens.orient.file_ranker")


# ─── Source file extensions (by ecosystem) ─────────────────────
#
# Only source files are scored — configs, lockfiles, and binaries are
# excluded so the ranker focuses on code a developer reads.

_SOURCE_EXTENSIONS = frozenset({
    # Python
    ".py",
    # JavaScript / TypeScript
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    # Go
    ".go",
    # Rust
    ".rs",
    # Java / Kotlin
    ".java", ".kt", ".kts",
    # C / C++
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx",
    # C#
    ".cs",
    # Ruby
    ".rb",
    # PHP
    ".php",
    # Swift
    ".swift",
    # Scala
    ".scala",
    # Dart
    ".dart",
    # Lua
    ".lua",
    # Shell (only top-level scripts, not nested)
    ".sh",
    # Vue / Svelte
    ".vue", ".svelte",
})


# ─── Skip rules ────────────────────────────────────────────────
#
# A file is skipped if any rule matches. Rules are checked in order;
# the first match wins.

_SKIP_FILENAME_PATTERNS = (
    "test_", "_test.", ".test.", ".spec.", "_spec.",
    "conftest.", "fixtures.", "__tests__",
    ".generated.", ".gen.", ".min.", ".bundle.",
)

_SKIP_DIR_PATTERNS = (
    "test", "tests", "__tests__", "__specs__", "spec", "specs",
    "migrations", "alembic", "versions",
    "dist", "build", "out", "target", "node_modules", "vendor",
    ".next", ".nuxt", ".output", ".turbo", ".cache",
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "coverage", ".nyc_output", ".pytest_cache", ".mypy_cache", ".ruff_cache",
)

# Directory context bonuses — files in these dirs get extra points.
_DIR_CONTEXT_BONUS = {
    "src": 15, "lib": 12, "app": 12, "cmd": 12, "internal": 10,
    "server": 10, "api": 8, "core": 8, "main": 6,
    "pages": 5, "routes": 5, "controllers": 5, "handlers": 5,
}

# Filename pattern bonuses — applied to the basename (without ext).
_FILENAME_BONUS = {
    "main": 25, "app": 22, "index": 20, "server": 18,
    "cli": 15, "run": 15, "start": 15, "entry": 12,
    "init": 8, "setup": 6, "config": 5,
}


def _should_skip(rel_path: str, basename: str) -> bool:
    """Return True if the file should be excluded from ranking."""
    lower_base = basename.lower()
    for pat in _SKIP_FILENAME_PATTERNS:
        if pat in lower_base:
            return True
    # Check directory components in the relative path.
    parts = rel_path.replace("\\", "/").lower().split("/")
    for part in parts[:-1]:  # exclude the filename itself
        for skip_dir in _SKIP_DIR_PATTERNS:
            if part == skip_dir:
                return True
    return False


def _count_lines(path: str, max_bytes: int = 512 * 1024) -> int:
    """Count lines in a file, capped at max_bytes to avoid huge files."""
    try:
        with open(path, "rb") as f:
            data = f.read(max_bytes)
        return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    except OSError:
        return 0


def _line_count_score(lines: int) -> float:
    """Score line count on a 0–20 scale.

    Sweet spot: 50–500 lines (full 20 points). Below 50: too small to
    be informative. Above 500: too long for a first read.
    """
    if lines == 0:
        return 0.0
    if 50 <= lines <= 500:
        return 20.0
    if lines < 50:
        return (lines / 50.0) * 20.0
    # Above 500: decay gradually, floor at 5 points.
    excess = min(lines - 500, 2000)
    return max(5.0, 20.0 - (excess / 2000.0) * 15.0)


def _depth_score(rel_path: str) -> float:
    """Score directory depth on a 0–15 scale (shallower = higher)."""
    depth = rel_path.replace("\\", "/").count("/")
    if depth == 0:
        return 15.0
    if depth == 1:
        return 12.0
    if depth == 2:
        return 8.0
    if depth == 3:
        return 4.0
    return 1.0


def _filename_bonus(basename: str) -> float:
    """Return bonus points for high-priority filenames (0–25)."""
    stem = os.path.splitext(basename)[0].lower()
    for pattern, bonus in _FILENAME_BONUS.items():
        if stem == pattern or stem.startswith(pattern + ".") or stem.startswith(pattern + "_"):
            return float(bonus)
    return 0.0


def _dir_context_bonus(rel_path: str) -> float:
    """Return bonus points for files in high-value directories (0–15)."""
    parts = rel_path.replace("\\", "/").lower().split("/")
    bonus = 0.0
    for part in parts[:-1]:
        bonus = max(bonus, _DIR_CONTEXT_BONUS.get(part, 0.0))
    return bonus


def _score_file(rel_path: str, abs_path: str) -> Tuple[float, str]:
    """Score a single file and return ``(score, reason_string)``."""
    basename = os.path.basename(rel_path)
    lines = _count_lines(abs_path)

    fb = _filename_bonus(basename)
    dc = _dir_context_bonus(rel_path)
    dp = _depth_score(rel_path)
    lc = _line_count_score(lines)
    score = fb + dc + dp + lc

    parts: List[str] = []
    if fb:
        parts.append(f"filename={basename.split('.')[0]}")
    if dc:
        parts.append(f"dir={rel_path.replace(chr(92),'/').split('/')[0]}")
    if dp >= 12:
        parts.append("shallow depth")
    if 50 <= lines <= 500:
        parts.append(f"{lines} lines")
    elif lines:
        parts.append(f"{lines} lines")
    reason = ", ".join(parts) if parts else "general source file"
    return score, reason


# @FLOW:    ORIENT_START_HERE
# @CALLS:   _should_skip() -> exclude tests/migrations/generated
#           _score_file() -> weighted score + reason string
# @MUTATES: (none — pure read)


def rank_start_here_files(
    workspace: str, top_n: int = 8, max_files: int = 5000
) -> List[Dict[str, Any]]:
    """Rank source files by reading priority and return the top N.

    Args:
        workspace: Absolute path to the project root.
        top_n: Maximum number of files to return (default 8).
        max_files: Safety cap on total files scanned (default 5000).

    Returns:
        List of dicts, highest score first, each::

            {
                "path": "src/app/page.tsx",
                "score": 87,
                "reason": "filename=page, dir=src, shallow depth, 120 lines"
            }
    """
    workspace = os.path.abspath(workspace)
    scored: List[Dict[str, Any]] = []
    scanned = 0

    for root, dirs, files in os.walk(workspace):
        # Prune skip directories in-place so os.walk doesn't descend.
        dirs[:] = [
            d for d in dirs
            if d.lower() not in _SKIP_DIR_PATTERNS and not d.startswith(".")
        ]
        for fname in files:
            if scanned >= max_files:
                _logger.debug(
                    "[orient/file_ranker] max_files=%d reached, stopping", max_files
                )
                break
            ext = os.path.splitext(fname)[1].lower()
            if ext not in _SOURCE_EXTENSIONS:
                continue
            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, workspace)
            if _should_skip(rel_path, fname):
                continue
            score, reason = _score_file(rel_path, abs_path)
            scored.append({
                "path": rel_path.replace("\\", "/"),
                "score": int(round(score)),
                "reason": reason,
            })
            scanned += 1
        if scanned >= max_files:
            break

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
