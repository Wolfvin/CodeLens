"""3-tier .codelensignore support for CodeLens (issue #55).

Loads ignore patterns from three sources, in priority order
(highest → lowest):

1. **Workspace** — ``<project_root>/.codelensignore``
2. **User**      — ``~/.codelensignore``
3. **Builtin**   — ``scripts/data/default-codelensignore``

Pattern syntax follows the gitignore spec (``**``, ``*``, ``?``, ``!``
negation, ``/``-anchored patterns). The optional ``pathspec`` library
is used when available for full gitignore compatibility; otherwise we
fall back to a ``fnmatch``-based matcher that supports a useful subset
(negation via leading ``!``, ``*`` and ``?`` wildcards, ``/``-anchored
prefixes). The fallback is intentionally permissive — pattern authors
who need full gitignore semantics should install ``pathspec``.

Precedence across the three tiers follows gitignore semantics: when a
path matches multiple patterns across tiers, the **last matching
pattern** wins. Concretely, builtin patterns are evaluated first, then
user, then workspace — so a ``!``-negation in the workspace file can
re-include a path that was ignored by the builtin or user tier.

Public API:
    is_ignored(path, project_root) -> bool
        Return True if *path* is ignored by any tier's positive pattern
        AND not re-included by a higher-priority ``!``-negation.

    load_patterns(project_root) -> list[str]
        Return the merged pattern list (builtin + user + workspace).

    suggest_ignore_directories(project_root, top_n=10) -> list[dict]
        Return top-N largest directories (by total file size) that are
        NOT currently ignored — used by ``scan --suggest-ignore``.
"""

from __future__ import annotations

import fnmatch
import os
import re
from typing import List, Optional, Tuple

# ── Optional pathspec dependency ──────────────────────────────────
# Gracefully degrade to fnmatch if pathspec is not installed.
try:  # pragma: no cover - exercised on systems with/without pathspec
    import pathspec  # type: ignore

    _HAS_PATHSPEC = True
except ImportError:  # pragma: no cover
    _HAS_PATHSPEC = False


# ── Path constants ────────────────────────────────────────────────

_BUILTIN_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'data',
    'default-codelensignore',
)


def _user_ignore_path() -> str:
    """Return the path to the user-level ~/.codelensignore file."""
    return os.path.join(os.path.expanduser('~'), '.codelensignore')


def _workspace_ignore_path(project_root: str) -> str:
    """Return the path to the workspace-level .codelensignore file."""
    return os.path.join(project_root, '.codelensignore')


# ── Pattern loading ───────────────────────────────────────────────

def _read_patterns(path: str) -> List[str]:
    """Read non-empty, non-comment pattern lines from a file.

    Args:
        path: Filesystem path to an ignore file.

    Returns:
        List of stripped pattern strings (comments and blank lines removed).
        Returns ``[]`` if the file does not exist or cannot be read.
    """
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except OSError:
        return []

    out: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        out.append(stripped)
    return out


def builtin_patterns() -> List[str]:
    """Return the builtin (lowest-priority) pattern list."""
    return _read_patterns(_BUILTIN_PATH)


def user_patterns() -> List[str]:
    """Return the user-level pattern list from ~/.codelensignore."""
    return _read_patterns(_user_ignore_path())


def workspace_patterns(project_root: str) -> List[str]:
    """Return the workspace-level pattern list from <project_root>/.codelensignore."""
    return _read_patterns(_workspace_ignore_path(project_root))


def load_patterns(project_root: str) -> List[str]:
    """Merge all three tiers into a single ordered pattern list.

    Order: builtin → user → workspace. In gitignore semantics, the last
    matching pattern wins, so this ordering gives workspace patterns
    the highest priority (including ``!``-negation overrides).
    """
    return (
        builtin_patterns()
        + user_patterns()
        + workspace_patterns(project_root)
    )


# ── Matchers ──────────────────────────────────────────────────────

class _PathspecMatcher:
    """Full gitignore-spec matcher backed by ``pathspec.PathSpec``."""

    __slots__ = ('_spec',)

    def __init__(self, patterns: List[str]):
        # ``gitignore`` factory handles ``!`` negation, ``**`` recursion,
        # ``/``-anchored patterns, and trailing-slash directory markers.
        self._spec = pathspec.PathSpec.from_lines('gitignore', patterns)

    def is_ignored(self, rel_path: str) -> bool:
        # pathspec expects forward-slash-separated relative paths.
        rel = rel_path.replace('\\', '/')
        if not rel or rel == '.':
            return False
        # pathspec's gitignore mode treats ``dir/`` patterns as matching
        # paths INSIDE the directory but not the directory path itself
        # (e.g., pattern ``node_modules/`` does NOT match the path
        # ``node_modules`` without a trailing slash). To give users the
        # expected "is this directory ignored?" behavior when they pass
        # a bare directory path, we also try matching with a trailing slash.
        if self._spec.match_file(rel):
            return True
        if not rel.endswith('/'):
            return bool(self._spec.match_file(rel + '/'))
        return False


class _FnmatchMatcher:
    """Fallback matcher using ``fnmatch`` when pathspec is unavailable.

    Supports a useful subset of gitignore syntax:
    * Leading ``!`` → negation (last match wins).
    * ``*`` and ``?`` wildcards.
    * Trailing ``/`` → directory-only marker (treated as path prefix).
    * Leading ``/`` → anchored to project root.

    Does NOT support ``**`` recursion or bracket character classes the
    same way gitignore does, but is sufficient for the common cases.
    """

    __slots__ = ('_rules',)

    def __init__(self, patterns: List[str]):
        # Each rule: (is_negation, compiled_regex, anchored, dir_only)
        rules: List[Tuple[bool, 're.Pattern', bool, bool]] = []
        for pat in patterns:
            is_neg = pat.startswith('!')
            if is_neg:
                pat = pat[1:]
            anchored = pat.startswith('/')
            if anchored:
                pat = pat[1:]
            dir_only = pat.endswith('/')
            if dir_only:
                pat = pat[:-1]
            # Convert fnmatch glob → regex.
            # We treat ``**`` like ``*`` for simplicity in fallback mode.
            pat_normalized = pat.replace('\\', '/')
            regex = fnmatch.translate(pat_normalized)
            # fnmatch.translate produces a regex anchored at both ends;
            # we want to match the full path (or a prefix when dir_only).
            rules.append((
                is_neg,
                re.compile(regex),
                anchored,
                dir_only,
            ))
        self._rules = rules

    def is_ignored(self, rel_path: str) -> bool:
        rel = rel_path.replace('\\', '/')
        if not rel or rel == '.':
            return False

        result = False
        for is_neg, rx, anchored, dir_only in self._rules:
            if dir_only:
                matched = self._match_dir_prefix(rx, rel, anchored)
            else:
                matched = bool(rx.match(rel))
            if matched:
                result = not is_neg
        return result

    @staticmethod
    def _match_dir_prefix(rx: 're.Pattern', rel: str, anchored: bool = True) -> bool:
        """True if *rel* is inside a directory matched by *rx*.

        For an *anchored* pattern (``/target/``) only root-relative ancestor
        directories count. For a *non-anchored* pattern (``target/`` — the
        gitignore default) the directory may sit at ANY depth, so a whole path
        segment matching the pattern is enough. Segment matching (not substring)
        keeps ``build/`` from matching ``build-tools/`` (issue #271 / gitignore
        backward-compat): ``src/target/debug/x`` is ignored by ``target/`` but
        ``build-tools/config`` is not ignored by ``build/``.
        """
        # Check the full path first (handles patterns with wildcards/subpaths).
        if rx.match(rel):
            return True
        parts = rel.split('/')
        if anchored:
            # Root-anchored: only ancestor paths measured from the root.
            for i in range(1, len(parts)):
                if rx.match('/'.join(parts[:i])):
                    return True
        else:
            # Non-anchored: the pattern (single- or multi-segment) may sit at
            # any depth → test every sub-path that both starts and ends on a
            # segment boundary. This matches `target/` against `src/target/x`
            # and `build/keep/` against `build/keep/x`, while whole-segment
            # boundaries keep `build/` from matching `build-tools/`.
            n = len(parts)
            for i in range(n):
                for j in range(i + 1, n + 1):
                    if rx.match('/'.join(parts[i:j])):
                        return True
        return False


def _build_matcher(patterns: List[str]):
    """Return a matcher instance for the given patterns.

    Uses ``pathspec`` if available; otherwise falls back to the
    ``fnmatch``-based matcher. Returns ``None`` if *patterns* is empty
    so callers can short-circuit the no-op case.
    """
    if not patterns:
        return None
    if _HAS_PATHSPEC:
        return _PathspecMatcher(patterns)
    return _FnmatchMatcher(patterns)


# ── Cache ─────────────────────────────────────────────────────────
# Per-process cache keyed by (project_root, signature). The signature
# is a string concatenation of (mtime, size) for the 3 source files
# so the cache auto-invalidates when any source changes.

_CACHE: dict = {}


def _signature(project_root: str) -> str:
    """Build a cache signature from the mtimes/sizes of all 3 source files."""
    parts = []
    for p in (
        _BUILTIN_PATH,
        _user_ignore_path(),
        _workspace_ignore_path(project_root),
    ):
        try:
            st = os.stat(p)
            parts.append(f"{p}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{p}:-")
    return "|".join(parts)


def _get_matcher(project_root: str):
    """Return a cached matcher for *project_root*, rebuilding if sources changed."""
    sig = _signature(project_root)
    key = (project_root, sig)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    # Build new matcher
    patterns = load_patterns(project_root)
    matcher = _build_matcher(patterns)
    # Evict stale entries for the same project_root to bound cache size.
    stale_keys = [k for k in _CACHE if k[0] == project_root]
    for k in stale_keys:
        del _CACHE[k]
    _CACHE[key] = (matcher, patterns)
    return matcher, patterns


# ── Public API ────────────────────────────────────────────────────

def is_ignored(path: str, project_root: str) -> bool:
    """Check if *path* is ignored by any of the 3 .codelensignore tiers.

    Args:
        path: Absolute path OR path relative to *project_root*.
              Both forms are normalized internally.
        project_root: Absolute path to the project root.

    Returns:
        True if *path* matches a positive pattern in any tier AND is not
        re-included by a higher-priority ``!``-negation. False otherwise,
        including when no .codelensignore files exist at all.
    """
    project_root = os.path.abspath(project_root)

    # Compute a workspace-relative path (forward-slash normalized).
    if os.path.isabs(path):
        try:
            rel = os.path.relpath(path, project_root)
        except ValueError:
            # Windows: different drive letters — fall back to original.
            rel = path
    else:
        rel = path

    # Never ignore the project root itself.
    if rel in ('.', '', '.'):
        return False

    matcher, _ = _get_matcher(project_root)
    if matcher is None:
        return False
    return matcher.is_ignored(rel)


def suggest_ignore_directories(
    project_root: str,
    top_n: int = 10,
) -> List[dict]:
    """Return the top-N largest directories not currently ignored.

    Walks the workspace, sums file sizes per directory (non-recursively),
    and returns the largest directories that are NOT ignored by the
    3-tier system. Useful for the ``scan --suggest-ignore`` flag.

    Args:
        project_root: Absolute path to the project root.
        top_n: Maximum number of directories to return (default 10).

    Returns:
        List of dicts sorted descending by ``size_bytes``, each with:
        * ``path`` — workspace-relative directory path (``.`` for root).
        * ``size_bytes`` — total size of files directly in the directory.
        * ``size_human`` — e.g. ``"1.23 MB"``.
        * ``file_count`` — number of files counted in the directory.
    """
    project_root = os.path.abspath(project_root)
    dir_stats: dict = {}

    for root, dirs, filenames in os.walk(project_root):
        rel_root = os.path.relpath(root, project_root)
        if rel_root == '.':
            rel_root_norm = ''
        else:
            rel_root_norm = rel_root.replace('\\', '/')

        # Skip this dir if it's already ignored (don't recurse).
        if rel_root_norm and is_ignored(rel_root_norm, project_root):
            dirs.clear()
            continue

        # Skip the project root's own .codelens dir (always internal).
        if '.codelens' in root and root != project_root:
            dirs.clear()
            continue

        # Filter subdirs: skip ignored ones so we don't recurse into them.
        kept_dirs = []
        for d in dirs:
            sub_rel = f"{rel_root_norm}/{d}" if rel_root_norm else d
            if is_ignored(sub_rel, project_root):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs

        # Sum file sizes (non-recursive: only files directly in this dir).
        total_size = 0
        file_count = 0
        for fn in filenames:
            fp = os.path.join(root, fn)
            try:
                total_size += os.path.getsize(fp)
                file_count += 1
            except OSError:
                pass

        display_path = rel_root_norm if rel_root_norm else '.'
        dir_stats[display_path] = (total_size, file_count)

    # Rank by size, descending.
    ranked = sorted(
        dir_stats.items(),
        key=lambda kv: kv[1][0],
        reverse=True,
    )[:top_n]

    return [
        {
            'path': path,
            'size_bytes': size,
            'size_human': _human_size(size),
            'file_count': count,
        }
        for path, (size, count) in ranked
        if size > 0  # skip empty dirs
    ]


def _human_size(n: int) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            if unit == 'B':
                return f"{n} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} TB"


__all__ = [
    'is_ignored',
    'load_patterns',
    'builtin_patterns',
    'user_patterns',
    'workspace_patterns',
    'suggest_ignore_directories',
    'HAS_PATHSPEC',
]

# Re-export for tests/inspection.
HAS_PATHSPEC = _HAS_PATHSPEC
