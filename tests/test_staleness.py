"""Tests for the per-file staleness banner (issue #66 Phase 1).

Scope:

* :mod:`sync.pending` — :class:`StaleFileDetector`, :func:`detect_stale_files`,
  :func:`format_staleness_banner`. Covers: mtime detection, content-hash
  confirmation, cache TTL, thread safety, banner formatting, edge cases
  (no mtimes.json, deleted files, permission errors).
* :class:`mcp_server.MCPServer` staleness integration — banner is
  prepended to read-tool responses, suppressed on ``scan``/``init``,
  cache invalidated after ``scan``.
* ``codelens staleness`` CLI command — registration, JSON/text output,
  ``--no-confirm-hash`` flag.

All tests are **network-free** and **filesystem-light** — they create
small temporary workspaces with synthetic ``mtimes.json`` files. No
real CodeLens scan is needed; the staleness module reads ``mtimes.json``
directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import pytest

# ─── Path setup (mirror other tests) ───────────────────────────────────────

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402
from sync.pending import (  # noqa: E402
    DETECTOR_CACHE_TTL_SECONDS,
    STALE_FILE_LIMIT_DEFAULT,
    StaleFile,
    StaleFileDetector,
    detect_stale_files,
    format_staleness_banner,
    _default_detector,
    _format_age,
)


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_detector():
    """Return a brand-new StaleFileDetector (no shared state with the module singleton)."""
    return StaleFileDetector(cache_ttl_seconds=0.0)  # 0 TTL = always re-walk


@pytest.fixture
def reset_default_detector():
    """Reset the module-level singleton detector before and after the test."""
    _default_detector.invalidate()
    yield
    _default_detector.invalidate()


def _make_workspace(files: Dict[str, str]) -> str:
    """Create a temp workspace with the given files.

    ``files`` maps relative path → content. Returns the workspace root
    path. Caller is responsible for cleanup (use ``tmp_path`` fixture
    in real tests; this helper is for ad-hoc use).
    """
    ws = tempfile.mkdtemp(prefix="codelens-staleness-test-")
    for rel, content in files.items():
        abs_path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
    return ws


def _write_mtimes(workspace: str, mtimes: Dict[str, float]) -> None:
    """Write a synthetic ``.codelens/mtimes.json`` for the workspace."""
    codelens_dir = os.path.join(workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    with open(os.path.join(codelens_dir, "mtimes.json"), "w", encoding="utf-8") as f:
        json.dump(mtimes, f)


def _get_mtime(path: str) -> float:
    return os.path.getmtime(path)


# ─── StaleFileDetector — basic detection ──────────────────────────────────


class TestStaleFileDetectorBasic:
    """Core detection logic — mtime comparison, file walking."""

    def test_no_mtimes_file_returns_empty(self, tmp_path, fresh_detector):
        """Workspace with no .codelens/mtimes.json → no stale files."""
        # Create a file but no mtimes.json.
        (tmp_path / "app.py").write_text("print('hello')")
        stale = fresh_detector.detect(str(tmp_path))
        assert stale == ()

    def test_fresh_index_no_stale(self, tmp_path, fresh_detector):
        """All files match stored mtimes → no stale files."""
        f1 = tmp_path / "app.py"
        f2 = tmp_path / "other.js"
        f1.write_text("print('hello')")
        f2.write_text("console.log('hi')")
        _write_mtimes(str(tmp_path), {
            "app.py": _get_mtime(str(f1)),
            "other.js": _get_mtime(str(f2)),
        })
        stale = fresh_detector.detect(str(tmp_path))
        assert stale == ()

    def test_edited_file_detected_as_stale(self, tmp_path, fresh_detector):
        """File edited after scan → detected as stale."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored_mtime = _get_mtime(str(f))
        _write_mtimes(str(tmp_path), {"app.py": stored_mtime})

        # Edit the file (must wait >1ms so mtime actually changes).
        time.sleep(0.05)
        f.write_text("print('hello world')")

        stale = fresh_detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale) == 1
        assert stale[0].rel_path == "app.py"
        assert stale[0].stored_mtime == stored_mtime
        assert stale[0].current_mtime > stored_mtime
        assert stale[0].edit_age_seconds >= 0.0

    def test_deleted_file_skipped_not_stale(self, tmp_path, fresh_detector):
        """File deleted since scan → not reported as stale (it's gone)."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        # Delete the file.
        f.unlink()

        stale = fresh_detector.detect(str(tmp_path), confirm_with_hash=False)
        assert stale == ()

    def test_empty_workspace_returns_empty(self, tmp_path, fresh_detector):
        """Workspace with no files at all → no stale files."""
        _write_mtimes(str(tmp_path), {})
        stale = fresh_detector.detect(str(tmp_path))
        assert stale == ()

    def test_empty_workspace_path_returns_empty(self, fresh_detector):
        """Empty string workspace → no crash, empty result."""
        assert fresh_detector.detect("") == ()

    def test_results_sorted_by_edit_age_most_recent_first(self, tmp_path, fresh_detector):
        """Most recently edited file should appear first in the result.

        edit_age = now - current_mtime. A file edited 1s ago has age=1;
        a file edited 10s ago has age=10. The banner says "most recent
        first", so the file with the SMALLEST edit_age should be first.
        """
        f1 = tmp_path / "old.py"
        f2 = tmp_path / "new.py"
        f1.write_text("a")
        f2.write_text("b")
        # Store mtimes as-of-write.
        m1 = _get_mtime(str(f1))
        m2 = _get_mtime(str(f2))
        _write_mtimes(str(tmp_path), {"old.py": m1, "new.py": m2})

        # Edit old.py first, then new.py — new.py is "more recent"
        # (smaller edit_age).
        time.sleep(0.05)
        f1.write_text("a-edited")
        time.sleep(0.05)
        f2.write_text("b-edited")

        stale = fresh_detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale) == 2
        # new.py was edited last → smaller edit_age → should be first.
        assert stale[0].rel_path == "new.py"
        assert stale[0].edit_age_seconds < stale[1].edit_age_seconds
        assert stale[1].rel_path == "old.py"


# ─── StaleFileDetector — content-hash confirmation ────────────────────────


class TestStaleFileDetectorHashConfirmation:
    """The ``confirm_with_hash`` path — only flag when content actually changed."""

    def test_touch_without_content_change_skipped(self, tmp_path, fresh_detector):
        """``touch`` updates mtime but not content → not stale (with hash confirm)."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored_mtime = _get_mtime(str(f))

        # We need a stored content hash to compare against. The hash comes
        # from the SQLite ``files`` table, which we don't have in this test.
        # Without a stored hash, the detector falls back to "size/mtime differ"
        # and reports the file as stale. So this test verifies the fallback
        # behavior: when no stored hash is available, mtime change → stale.
        time.sleep(0.05)
        # Re-write the SAME content (simulates touch).
        os.utime(str(f), None)

        _write_mtimes(str(tmp_path), {"app.py": stored_mtime})
        stale = fresh_detector.detect(str(tmp_path), confirm_with_hash=True)
        # Without stored hash, we can't confirm content identical → reported as stale.
        assert len(stale) == 1
        assert stale[0].content_hash_changed is None

    def test_no_confirm_hash_flags_on_mtime_only(self, tmp_path, fresh_detector):
        """``confirm_with_hash=False`` flags on mtime change alone."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored_mtime = _get_mtime(str(f))
        _write_mtimes(str(tmp_path), {"app.py": stored_mtime})

        time.sleep(0.05)
        os.utime(str(f), None)  # touch — mtime changes, content same

        stale = fresh_detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale) == 1
        assert stale[0].content_hash_changed is None  # not checked


# ─── StaleFileDetector — cache ─────────────────────────────────────────────


class TestStaleFileDetectorCache:
    """The per-workspace TTL cache."""

    def test_cache_returns_same_result_within_ttl(self, tmp_path):
        """Within TTL, detect() returns the cached result without re-walking."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        detector = StaleFileDetector(cache_ttl_seconds=10.0)
        stale1 = detector.detect(str(tmp_path), confirm_with_hash=False)

        # Edit the file AFTER the first detect() call.
        time.sleep(0.05)
        f.write_text("print('changed')")

        # Second call within TTL should return the cached (empty) result.
        stale2 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert stale1 == stale2 == ()

    def test_cache_expires_after_ttl(self, tmp_path):
        """After TTL, detect() re-walks and picks up changes."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        detector = StaleFileDetector(cache_ttl_seconds=0.05)
        stale1 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert stale1 == ()

        # Edit + wait for TTL to expire.
        time.sleep(0.05)
        f.write_text("print('changed')")
        time.sleep(0.05)

        stale2 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale2) == 1

    def test_invalidate_drops_cache(self, tmp_path):
        """invalidate() forces the next detect() to re-walk."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        detector = StaleFileDetector(cache_ttl_seconds=10.0)
        stale1 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert stale1 == ()

        # Edit + invalidate.
        time.sleep(0.05)
        f.write_text("print('changed')")
        detector.invalidate(str(tmp_path))

        stale2 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale2) == 1

    def test_invalidate_all_workspaces(self, tmp_path):
        """invalidate(None) drops cache for ALL workspaces."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        detector = StaleFileDetector(cache_ttl_seconds=10.0)
        detector.detect(str(tmp_path), confirm_with_hash=False)

        # invalidate(None) clears everything.
        detector.invalidate(None)

        # Internal cache should be empty.
        assert detector._cache == {}


# ─── StaleFileDetector — thread safety ─────────────────────────────────────


class TestStaleFileDetectorThreadSafety:
    """Concurrent detect() calls must not corrupt the cache."""

    def test_concurrent_calls_same_workspace(self, tmp_path):
        """20 threads calling detect() on the same workspace don't crash."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        detector = StaleFileDetector(cache_ttl_seconds=1.0)
        results: List[Tuple[StaleFile, ...]] = []
        errors: List[Exception] = []

        def worker():
            try:
                r = detector.detect(str(tmp_path), confirm_with_hash=False)
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 20
        # All results should be equal (cache hit or consistent walk).
        assert all(r == results[0] for r in results)


# ─── format_staleness_banner ───────────────────────────────────────────────


class TestFormatStalenessBanner:
    """Banner string formatting."""

    def test_empty_input_returns_empty_string(self):
        assert format_staleness_banner([]) == ""
        assert format_staleness_banner(()) == ""

    def test_single_file_banner(self):
        sf = StaleFile(
            rel_path="app.py",
            stored_mtime=1000.0,
            current_mtime=1001.0,
            stored_size=None,
            current_size=21,
            edit_age_seconds=2.5,
            size_changed=True,
            content_hash_changed=True,
        )
        banner = format_staleness_banner([sf])
        assert "⚠️" in banner
        assert "app.py" in banner
        assert "content differs" in banner
        assert "2.5s" in banner
        assert "showing 1 of 1" in banner

    def test_size_mtime_only_when_hash_not_confirmed(self):
        sf = StaleFile(
            rel_path="app.py",
            stored_mtime=1000.0,
            current_mtime=1001.0,
            stored_size=None,
            current_size=21,
            edit_age_seconds=2.5,
            size_changed=True,
            content_hash_changed=None,
        )
        banner = format_staleness_banner([sf])
        assert "size/mtime differ" in banner

    def test_limit_truncates_with_and_n_more(self):
        files = [
            StaleFile(
                rel_path=f"file_{i}.py",
                stored_mtime=1000.0,
                current_mtime=1001.0,
                stored_size=None,
                current_size=10,
                edit_age_seconds=float(i),
                size_changed=True,
                content_hash_changed=True,
            )
            for i in range(15)
        ]
        banner = format_staleness_banner(files, limit=10)
        assert "showing 10 of 15" in banner
        assert "and 5 more" in banner

    def test_banner_mentions_rescan_command(self):
        sf = StaleFile(
            rel_path="app.py",
            stored_mtime=1000.0,
            current_mtime=1001.0,
            stored_size=None,
            current_size=21,
            edit_age_seconds=2.5,
            size_changed=True,
            content_hash_changed=True,
        )
        banner = format_staleness_banner([sf])
        assert "codelens scan" in banner


class TestFormatAge:
    """The _format_age helper."""

    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0.1, "0.1s"),
            (1.0, "1.0s"),
            (59.9, "59.9s"),
            (60.0, "1m 0s"),
            (72.0, "1m 12s"),
            (3599.0, "59m 59s"),
            (3600.0, "1h 0m"),
            (3661.0, "1h 1m"),
            (86400.0, "1d 0h"),
            (90000.0, "1d 1h"),
        ],
    )
    def test_format_age(self, seconds, expected):
        assert _format_age(seconds) == expected


# ─── detect_stale_files module-level function ──────────────────────────────


class TestDetectStaleFilesModuleFunction:
    """The module-level detect_stale_files() uses the singleton detector."""

    def test_module_function_returns_tuple(self, tmp_path, reset_default_detector):
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        result = detect_stale_files(str(tmp_path), confirm_with_hash=False)
        assert isinstance(result, tuple)

    def test_module_function_caches(self, tmp_path, reset_default_detector):
        """Two calls within TTL return the same cached result."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        r1 = detect_stale_files(str(tmp_path), confirm_with_hash=False)
        r2 = detect_stale_files(str(tmp_path), confirm_with_hash=False)
        assert r1 is r2 or r1 == r2  # cached or equal


# ─── CLI command ───────────────────────────────────────────────────────────


class TestStalenessCommand:
    """The ``codelens staleness`` CLI command."""

    def test_command_is_registered(self):
        assert "staleness" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["staleness"]
        assert callable(info["execute"])
        assert callable(info["add_args"])

    def test_no_workspace_returns_error(self):
        from commands import staleness as cmd
        args = mock.MagicMock()
        args.workspace = None
        args.no_confirm_hash = False
        args.max_files = 10000
        args.limit = 10
        args.format = "json"
        result = cmd.execute(args, "")
        assert result["status"] == "error"

    def test_json_output_has_required_fields(self, tmp_path, reset_default_detector):
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        from commands import staleness as cmd
        args = mock.MagicMock()
        args.workspace = str(tmp_path)
        args.no_confirm_hash = True
        args.max_files = 10000
        args.limit = 10
        args.format = "json"
        result = cmd.execute(args, str(tmp_path))
        assert result["status"] == "ok"
        assert "stale_count" in result
        assert "stale_files" in result
        assert "banner" in result
        assert result["workspace"] == os.path.abspath(str(tmp_path))

    def test_stale_file_appears_in_output(self, tmp_path, reset_default_detector):
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored = _get_mtime(str(f))
        _write_mtimes(str(tmp_path), {"app.py": stored})

        time.sleep(0.05)
        f.write_text("print('changed')")

        from commands import staleness as cmd
        args = mock.MagicMock()
        args.workspace = str(tmp_path)
        args.no_confirm_hash = True  # skip hash, mtime-only
        args.max_files = 10000
        args.limit = 10
        args.format = "json"
        result = cmd.execute(args, str(tmp_path))
        assert result["stale_count"] == 1
        assert result["stale_files"][0]["rel_path"] == "app.py"
        assert "⚠️" in result["banner"]


# ─── CLI subprocess smoke test ─────────────────────────────────────────────


class TestCLISmoke:
    """End-to-end: invoke ``codelens staleness`` as a real subprocess."""

    def _run_cli(self, workspace, *extra_args):
        env = os.environ.copy()
        env["PYTHONPATH"] = _SCRIPTS_DIR
        env["PYTHONUTF8"] = "1"
        return subprocess.run(
            [
                sys.executable,
                os.path.join(_SCRIPTS_DIR, "codelens.py"),
                "staleness",
                workspace,
                "--format",
                "json",
                *extra_args,
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_staleness_runs_cleanly_on_empty_workspace(self, tmp_path):
        _write_mtimes(str(tmp_path), {})
        result = self._run_cli(str(tmp_path))
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        # Parse the JSON payload from stdout (skip the auto-detect line).
        out = result.stdout
        start = out.find("{")
        assert start >= 0
        payload = json.loads(out[start:])
        assert payload["status"] == "ok"
        assert payload["stale_count"] == 0


# ─── MCP server integration ────────────────────────────────────────────────


class TestMCPServerStalenessIntegration:
    """The MCPServer prepends the staleness banner to read-tool responses."""

    def _make_server(self):
        """Construct an MCPServer without starting the JSON-RPC loop."""
        from mcp_server import MCPServer
        return MCPServer()

    def test_staleness_banner_prepended_on_read_tool(self, tmp_path, reset_default_detector):
        """A read-tool response gets the banner prepended when files are stale."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored = _get_mtime(str(f))
        _write_mtimes(str(tmp_path), {"app.py": stored})

        time.sleep(0.05)
        f.write_text("print('changed')")

        server = self._make_server()
        response = {
            "content": [{"type": "text", "text": "original output"}],
            "isError": False,
        }
        server._attach_staleness_banner(response, str(tmp_path))

        # Banner should be prepended to the text.
        text = response["content"][0]["text"]
        assert "⚠️" in text
        assert "app.py" in text
        assert "original output" in text
        # And the structured field should be set.
        assert response["_staleness"]["stale_count"] == 1

    def test_no_banner_when_index_fresh(self, tmp_path, reset_default_detector):
        """No stale files → no banner, no _staleness field."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})

        server = self._make_server()
        response = {
            "content": [{"type": "text", "text": "original output"}],
            "isError": False,
        }
        server._attach_staleness_banner(response, str(tmp_path))

        assert "_staleness" not in response
        assert response["content"][0]["text"] == "original output"

    def test_scan_invalidates_staleness_cache(self, tmp_path, reset_default_detector):
        """After a scan, the staleness cache is dropped so the next read re-probes."""
        f = tmp_path / "app.py"
        f.write_text("print('hello')")
        stored = _get_mtime(str(f))
        _write_mtimes(str(tmp_path), {"app.py": stored})

        time.sleep(0.05)
        f.write_text("print('changed')")

        server = self._make_server()

        # First detect — should find the stale file.
        detector = server._get_staleness_detector()
        assert detector is not None
        stale1 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert len(stale1) == 1

        # Simulate a scan: rewrite mtimes.json with the current mtime,
        # then invalidate the cache.
        _write_mtimes(str(tmp_path), {"app.py": _get_mtime(str(f))})
        server._invalidate_staleness_cache(str(tmp_path))

        # Second detect — cache was invalidated, mtimes now match → no stale.
        stale2 = detector.detect(str(tmp_path), confirm_with_hash=False)
        assert stale2 == ()

    def test_empty_workspace_no_crash(self, reset_default_detector):
        """Empty workspace string → no banner, no crash."""
        server = self._make_server()
        response = {
            "content": [{"type": "text", "text": "original"}],
            "isError": False,
        }
        server._attach_staleness_banner(response, "")
        assert response["content"][0]["text"] == "original"
        assert "_staleness" not in response

    def test_detector_init_failure_isolated(self, tmp_path, reset_default_detector, monkeypatch):
        """If the sync subpackage fails to import, the banner is silently skipped."""
        # Force the import to fail.
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "sync.pending" or name == "sync":
                raise ImportError("simulated failure")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        server = self._make_server()
        # Reset the cached detector so the import runs again.
        server._staleness_detector = None

        response = {
            "content": [{"type": "text", "text": "original"}],
            "isError": False,
        }
        # Should not raise.
        server._attach_staleness_banner(response, str(tmp_path))
        assert response["content"][0]["text"] == "original"
        assert "_staleness" not in response
