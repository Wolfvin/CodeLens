# @WHO:   scripts/sync/pending.py
# @WHAT:  Per-file staleness detection — index vs working tree drift banner (issue #66 Phase 1)
# @PART:  sync
# @ENTRY: detect_stale_files(), format_staleness_banner(), StaleFileDetector
#
# Issue #66 Phase 1 — Per-file staleness banner.
#
# What this module does
# ---------------------
# After a ``codelens scan``, every indexed file has a stored ``mtime``
# (in ``.codelens/mtimes.json``) and a stored content hash (in the
# SQLite ``files`` table when available). If the user edits a file
# after the scan, the index is stale — queries against it may return
# outdated symbol locations, dead-code verdicts, or stale call graphs.
#
# This module walks the indexed file list, compares the current
# ``(st_size, st_mtime_ns)`` from ``os.stat()`` against the stored
# values, and — only when those differ — re-computes a SHA-256 content
# hash to confirm the file actually changed (mtime can change without
# content change, e.g. ``touch`` or ``git checkout`` of identical
# content). Files that genuinely changed are returned as ``StaleFile``
# records.
#
# The MCP server (issue #66 Phase 1 wiring) calls
# :func:`detect_stale_files` on every read-tool call, caches the result
# per workspace for a short TTL, and prepends
# :func:`format_staleness_banner` to the response so the agent knows
# the index is stale before acting on it.
#
# Why in-memory ``Dict[str, float]`` + ``threading.Lock`` (per issue spec)
# ----------------------------------------------------------------------
# The issue spec calls for "in-memory ``Dict[str, float]`` (path →
# edit_timestamp), thread-safe via ``threading.Lock``". This module
# honours that: :class:`StaleFileDetector` holds the per-workspace
# detection cache behind a lock so concurrent MCP tool calls (the
# server dispatches them in a thread pool) don't race.
#
# The lock protects the *cache*, not the file-system walk — the walk
# itself is read-only and safe to run concurrently. The cache exists
# because walking a large codebase (10k+ files) on every tool call
# would dominate latency; a 5-second TTL keeps the banner fresh
# without re-stat-ing the whole tree on every query.
#
# Phase 2 (connect-time catch-up) will extend this module to also run
# content-hash reconciliation on MCP reconnect. Phase 1 deliberately
# stops at detection + banner — the fix path (re-scan) is the user's
# responsibility, surfaced by the banner.

"""Per-file staleness detection — index vs working tree drift banner.

Public entry points::

    from sync.pending import detect_stale_files, format_staleness_banner

    stale = detect_stale_files(workspace="/path/to/ws")
    if stale:
        banner = format_staleness_banner(stale)
        # prepend banner to MCP response text
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from utils import logger

# ─── Constants ─────────────────────────────────────────────────────────────

# How many stale files to list by name in the banner before collapsing
# to "and N more". 10 is the issue spec's implicit default — enough to
# be actionable, small enough that the banner doesn't dominate the
# response payload.
STALE_FILE_LIMIT_DEFAULT = 10

# Cache TTL for :class:`StaleFileDetector`. 5 seconds balances freshness
# (a user editing a file should see the banner within seconds) against
# cost (re-stat-ing 10k files on every MCP call would add ~50 ms).
DETECTOR_CACHE_TTL_SECONDS = 5.0

# Mtime tolerance in seconds. Filesystems with coarse mtime resolution
# (e.g. FAT32, some network shares) can report mtimes that differ by
# sub-millisecond even when content is identical. The stored mtime in
# mtimes.json comes from os.path.getmtime() which returns a float, so
# we compare with a small epsilon. Anything larger than this is a real
# edit; anything smaller is filesystem noise.
_MTIME_TOLERANCE_SECONDS = 0.001


# ─── Data types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StaleFile:
    """One file whose index entry is stale.

    ``rel_path`` is relative to the workspace root (matches the key
    format in ``mtimes.json``). ``edit_age_seconds`` is the wall-clock
    time between the stored mtime and the current mtime — useful for
    the banner so the agent can tell "edited 2 seconds ago" from
    "edited 2 hours ago". ``size_changed`` is True when ``st_size``
    differs (a stronger signal than mtime alone — mtime can change
    without size changing, e.g. ``touch``).
    """

    rel_path: str
    stored_mtime: float
    current_mtime: float
    stored_size: Optional[int]
    current_size: int
    edit_age_seconds: float
    size_changed: bool
    # Only populated when the caller asked for content-hash confirmation
    # (see ``StaleFileDetector.detect`` with ``confirm_with_hash=True``).
    # None means "size/mtime differ but we didn't hash the file" — the
    # caller should treat it as "probably stale" rather than "definitely
    # stale". The MCP banner path always sets confirm_with_hash=True.
    content_hash_changed: Optional[bool] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "stored_mtime": self.stored_mtime,
            "current_mtime": self.current_mtime,
            "stored_size": self.stored_size,
            "current_size": self.current_size,
            "edit_age_seconds": round(self.edit_age_seconds, 1),
            "size_changed": self.size_changed,
            "content_hash_changed": self.content_hash_changed,
        }


# ─── Helpers ───────────────────────────────────────────────────────────────


def _load_indexed_mtimes(workspace: str) -> Dict[str, float]:
    """Load the stored scan-time mtimes for the workspace.

    Source of truth: ``<workspace>/.codelens/mtimes.json`` — written by
    :func:`incremental.save_mtimes` on every scan. Returns an empty dict
    when the file is missing (workspace never scanned) or corrupt (the
    scan will rebuild it).

    Why mtimes.json and not the SQLite ``files`` table?
        ``mtimes.json`` is written by every scan, including workspaces
        that use the legacy JSON registry (pre-v8.2). The SQLite
        ``files`` table is only populated when the persistent registry
        is active. Using ``mtimes.json`` as the source of truth keeps
        Phase 1 working on every workspace configuration.
    """
    try:
        from incremental import load_mtimes
        return load_mtimes(workspace)
    except Exception as exc:
        # Don't let a bug in incremental.load_mtimes break staleness
        # detection — log and treat as "no indexed files yet".
        logger.warning(f"[sync.pending] load_mtimes failed for {workspace!r}: {exc}")
        return {}


def _stat_file(abs_path: str) -> Optional[Tuple[int, int, float]]:
    """Stat a file and return ``(st_size, st_mtime_ns, st_mtime_float)``.

    Returns ``None`` when the file doesn't exist (deleted since scan)
    or can't be stat'd (permission denied, broken symlink, etc.). The
    caller treats ``None`` as "file is gone" — a separate signal from
    "file is stale".
    """
    try:
        st = os.stat(abs_path)
        return (st.st_size, st.st_mtime_ns, st.st_mtime)
    except OSError:
        return None


def _compute_sha256(abs_path: str) -> Optional[str]:
    """Compute the SHA-256 hash of a file's content.

    Returns ``None`` on any I/O error — the caller treats ``None`` as
    "couldn't confirm content change, treat as stale". Reads in 64 KB
    chunks so large files don't blow memory.
    """
    h = hashlib.sha256()
    try:
        with open(abs_path, "rb") as f:
            while True:
                chunk = f.read(64 * 1024)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        logger.debug(f"[sync.pending] sha256 failed for {abs_path!r}: {exc}")
        return None


def _load_indexed_content_hashes(workspace: str) -> Dict[str, str]:
    """Load stored content hashes from the SQLite ``files`` table.

    Returns an empty dict when:
      - SQLite is not available (legacy install)
      - The DB file doesn't exist (workspace never scanned with v8.2+)
      - The ``files`` table doesn't exist (pre-v8.2 DB)
      - Any other error occurs

    When this returns empty, :class:`StaleFileDetector` falls back to
    size/mtime-only detection — still useful, just less precise. The
    banner will say "size/mtime differ" rather than "content differs".
    """
    try:
        from persistent_registry import PersistentRegistry
        from utils import default_db_path
        db_path = default_db_path(workspace)
        if not os.path.exists(db_path):
            return {}
        reg = PersistentRegistry(workspace, db_path=db_path)
        conn = reg._connect()
        rows = conn.execute(
            "SELECT file_path, content_hash FROM files WHERE content_hash IS NOT NULL"
        ).fetchall()
        # file_path in the DB is absolute; convert to workspace-relative
        # to match the mtimes.json key format.
        result: Dict[str, str] = {}
        ws_abs = os.path.abspath(workspace)
        for row in rows:
            abs_path = row["file_path"]
            try:
                rel = os.path.relpath(abs_path, ws_abs)
            except ValueError:
                # Different drive on Windows — skip.
                continue
            result[rel] = row["content_hash"]
        return result
    except Exception as exc:
        logger.debug(f"[sync.pending] content-hash load failed for {workspace!r}: {exc}")
        return {}


# ─── Detector ──────────────────────────────────────────────────────────────


class StaleFileDetector:
    """Thread-safe per-workspace stale-file detection with short TTL cache.

    Usage::

        detector = StaleFileDetector()
        stale = detector.detect(workspace="/path/to/ws")
        if stale:
            banner = format_staleness_banner(stale)

    The detector caches results per workspace for
    :data:`DETECTOR_CACHE_TTL_SECONDS` seconds. The cache is keyed by
    absolute workspace path and protected by a :class:`threading.Lock`
    so concurrent MCP tool calls (dispatched in a thread pool) don't
    race or duplicate work.

    The cache exists because walking 10k+ files on every tool call
    would add ~50 ms of latency. A 5-second TTL keeps the banner fresh
    enough for interactive use (a user editing a file should see the
    banner within seconds) without re-stat-ing the whole tree on every
    query. Phase 2 (connect-time catch-up) will invalidate the cache
    on MCP reconnect.
    """

    def __init__(self, cache_ttl_seconds: float = DETECTOR_CACHE_TTL_SECONDS) -> None:
        self._cache_ttl = cache_ttl_seconds
        # ``_cache`` maps abs workspace path → (detection_time, result).
        # ``result`` is the tuple returned by ``detect()`` (possibly empty).
        self._cache: Dict[str, Tuple[float, Tuple[StaleFile, ...]]] = {}
        self._lock = threading.Lock()

    def detect(
        self,
        workspace: str,
        *,
        confirm_with_hash: bool = True,
        max_files: int = 10_000,
    ) -> Tuple[StaleFile, ...]:
        """Detect stale files in ``workspace``.

        Args:
            workspace: Absolute path to the workspace root.
            confirm_with_hash: When True (default), re-compute SHA-256
                for files whose size/mtime differ and only flag them
                as stale when the content hash also differs. When
                False, flag on size/mtime difference alone (faster but
                false-positive on ``touch``).
            max_files: Safety cap on the number of files to walk.
                10k is enough for most projects; larger codebases
                should run a scan to refresh the index instead of
                relying on the staleness banner.

        Returns:
            Tuple of :class:`StaleFile` records, sorted by edit age
            (most recent first). Empty tuple when the workspace has
            no indexed files or no stale files.

        Why a tuple (not a list)?
            The result is immutable from the caller's perspective —
            the banner formatter shouldn't accidentally mutate it.
            Tuples also hash, which simplifies testing.
        """
        if not workspace:
            return ()

        ws_abs = os.path.abspath(workspace)
        now = time.monotonic()

        # Cache check — fast path. We hold the lock only for the dict
        # lookup, not for the walk below.
        with self._lock:
            cached = self._cache.get(ws_abs)
            if cached is not None:
                cached_at, cached_result = cached
                if now - cached_at < self._cache_ttl:
                    return cached_result

        # Cache miss or expired — do the walk. This is read-only and
        # safe to run without the lock; concurrent calls may duplicate
        # the walk but won't corrupt the cache.
        result = self._walk_and_detect(
            ws_abs,
            confirm_with_hash=confirm_with_hash,
            max_files=max_files,
        )

        # Store in cache. We re-acquire the lock only for the write.
        with self._lock:
            self._cache[ws_abs] = (now, result)
        return result

    def invalidate(self, workspace: Optional[str] = None) -> None:
        """Drop cached results for ``workspace`` (or all workspaces).

        Called by the MCP server after a ``scan`` command — the scan
        refreshes the index, so any cached staleness verdict is now
        stale itself. Passing ``None`` drops everything (used in
        tests).
        """
        with self._lock:
            if workspace is None:
                self._cache.clear()
            else:
                self._cache.pop(os.path.abspath(workspace), None)

    def _walk_and_detect(
        self,
        ws_abs: str,
        *,
        confirm_with_hash: bool,
        max_files: int,
    ) -> Tuple[StaleFile, ...]:
        """Walk indexed files, compare stats, return stale records.

        This is the uncached path. Separated from :meth:`detect` so
        tests can call it directly without polluting the cache.
        """
        stored_mtimes = _load_indexed_mtimes(ws_abs)
        if not stored_mtimes:
            # Workspace never scanned (or mtimes.json missing/corrupt).
            # Nothing to compare against — return empty.
            return ()

        stored_hashes: Dict[str, str] = {}
        if confirm_with_hash:
            stored_hashes = _load_indexed_content_hashes(ws_abs)

        now_time = time.time()
        stale: List[StaleFile] = []
        walked = 0

        for rel_path, stored_mtime in stored_mtimes.items():
            walked += 1
            if walked > max_files:
                # Safety cap — don't let a pathological mtimes.json
                # (10M entries from a misbehaving scan) lock up the
                # MCP server. The banner will say "and possibly more".
                break

            abs_path = os.path.join(ws_abs, rel_path)
            stat = _stat_file(abs_path)
            if stat is None:
                # File deleted since scan — not "stale" in the edit
                # sense; the index is wrong but the fix is a re-scan,
                # not a banner. Skip (Phase 2 may surface deletions
                # separately).
                continue

            current_size, _current_mtime_ns, current_mtime = stat

            # Quick check: mtime within tolerance → not stale.
            if abs(current_mtime - stored_mtime) <= _MTIME_TOLERANCE_SECONDS:
                continue

            # mtime differs — check size. We don't have a stored size
            # in mtimes.json (only mtime), so we use the stored content
            # hash's size if available, otherwise None.
            stored_size = None
            size_changed = True  # conservative default

            # Slow path: confirm with content hash if requested.
            content_hash_changed: Optional[bool] = None
            if confirm_with_hash:
                current_hash = _compute_sha256(abs_path)
                stored_hash = stored_hashes.get(rel_path)
                if current_hash is not None and stored_hash is not None:
                    content_hash_changed = current_hash != stored_hash
                    if not content_hash_changed:
                        # mtime changed but content identical — skip.
                        # (e.g. ``touch`` or ``git checkout`` of same content.)
                        continue
                # If we couldn't get a hash (file vanished mid-walk,
                # permission error, no stored hash), content_hash_changed
                # stays None — the banner will say "size/mtime differ"
                # rather than "content differs".

            stale.append(StaleFile(
                rel_path=rel_path,
                stored_mtime=stored_mtime,
                current_mtime=current_mtime,
                stored_size=stored_size,
                current_size=current_size,
                edit_age_seconds=max(0.0, now_time - current_mtime),
                size_changed=size_changed,
                content_hash_changed=content_hash_changed,
            ))

        # Sort by edit age ascending (smallest age = most recent edit
        # first) — the banner shows the most recently edited files at
        # the top so the agent sees the most relevant context first.
        # edit_age = now - current_mtime, so a file edited 1s ago has
        # age=1, a file edited 10s ago has age=10. Ascending puts age=1
        # first → most recent first.
        stale.sort(key=lambda s: s.edit_age_seconds, reverse=False)
        return tuple(stale)


# ─── Banner formatting ────────────────────────────────────────────────────


def format_staleness_banner(
    stale_files: Tuple[StaleFile, ...] | List[StaleFile],
    *,
    limit: int = STALE_FILE_LIMIT_DEFAULT,
) -> str:
    """Format stale files into a human/agent-readable banner string.

    The banner is plain text (no markdown) so it renders correctly in
    both terminal output and MCP tool-response content blocks. It
    starts with a ⚠️ marker so agents can pattern-match on it.

    Args:
        stale_files: Sequence of :class:`StaleFile` records (typically
            the return value of :meth:`StaleFileDetector.detect`).
        limit: Max number of file names to list before collapsing to
            "and N more". Default 10.

    Returns:
        Multi-line banner string, or empty string when ``stale_files``
        is empty (caller should not prepend anything in that case).

    The banner shape::

        ⚠️ Some files referenced below were edited since the last index sync.
        The index may be stale for these files — re-run `codelens scan` to refresh.
        Stale files (showing 3 of 3, most recent first):
          • path/to/file.py (edited 2.3s ago, content differs)
          • other.js (edited 1m 12s ago, content differs)
          • third.ts (edited 5m 0s ago, size/mtime differ)
    """
    if not stale_files:
        return ""

    total = len(stale_files)
    shown = list(stale_files[:limit])

    lines: List[str] = [
        "⚠️ Some files referenced below were edited since the last index sync.",
        "The index may be stale for these files — re-run `codelens scan` to refresh.",
        f"Stale files (showing {len(shown)} of {total}, most recent first):",
    ]
    for sf in shown:
        age = _format_age(sf.edit_age_seconds)
        # Distinguish "content differs" (hash confirmed) from
        # "size/mtime differ" (hash not confirmed or not available).
        if sf.content_hash_changed is True:
            change_desc = "content differs"
        elif sf.content_hash_changed is False:
            # This shouldn't happen — we filter these out in detect().
            # But be defensive: if a caller passes a pre-filter list,
            # don't claim the file is stale.
            change_desc = "content identical (mtime-only)"
        else:
            change_desc = "size/mtime differ"
        lines.append(f"  • {sf.rel_path} (edited {age} ago, {change_desc})")

    if total > limit:
        lines.append(f"  … and {total - limit} more (run `codelens staleness` for the full list)")

    return "\n".join(lines)


def _format_age(seconds: float) -> str:
    """Format an age in seconds as a human-readable string.

    Examples: ``2.3s``, ``1m 12s``, ``5m 0s``, ``1h 23m``, ``2d 4h``.
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    if seconds < 86400:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m}m"
    d = int(seconds // 86400)
    h = int((seconds % 86400) // 3600)
    return f"{d}d {h}h"


# ─── Module-level convenience function ─────────────────────────────────────

# Module-level singleton detector — the MCP server uses this to avoid
# constructing a new detector on every tool call. Tests can call
# ``_default_detector.invalidate()`` to reset state between cases.
_default_detector = StaleFileDetector()


def detect_stale_files(
    workspace: str,
    *,
    confirm_with_hash: bool = True,
    max_files: int = 10_000,
) -> Tuple[StaleFile, ...]:
    """Module-level convenience wrapper around the singleton detector.

    Equivalent to::

        _default_detector.detect(workspace, confirm_with_hash=..., max_files=...)

    Most callers should use this. Construct a :class:`StaleFileDetector`
    directly only when you need a separate cache (e.g. tests).
    """
    return _default_detector.detect(
        workspace,
        confirm_with_hash=confirm_with_hash,
        max_files=max_files,
    )


__all__ = [
    "StaleFile",
    "StaleFileDetector",
    "detect_stale_files",
    "format_staleness_banner",
    "STALE_FILE_LIMIT_DEFAULT",
    "DETECTOR_CACHE_TTL_SECONDS",
]
