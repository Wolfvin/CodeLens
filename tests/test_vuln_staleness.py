"""
Tests for OSV cache staleness flags (issue #30).

Covers the three deliverables of issue #30:

1. ``cache_info`` block in vuln-scan output (``last_refresh``, ``age_hours``,
   ``ttl_hours``, ``is_stale``, ``stale_packages``).
2. ``--refresh`` flag — bypasses the OSV cache and forces fresh API calls.
3. ``--max-age Nh`` flag — treats cache entries older than N hours as stale
   for the current run only (stored TTL unchanged).

Network access is never required: API calls are mocked via
``unittest.mock.patch.object(OSVClient, "_batch_query_api", ...)``.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import time
from argparse import Namespace
from unittest.mock import patch

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from osv_client import DEFAULT_TTL, OSVCache, OSVClient, OSVPackage  # noqa: E402
from commands.vuln_scan import _parse_max_age  # noqa: E402
from commands import vuln_scan as vuln_scan_cmd  # noqa: E402
from vulnscan_engine import scan_vulnerabilities  # noqa: E402

FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks",
    "fixtures",
)


# ─── Fixtures & helpers ────────────────────────────────────────


@pytest.fixture
def tmp_workspace():
    """Provide a temp workspace dir, cleaned up after the test."""
    ws = tempfile.mkdtemp(prefix="codelens_vuln_test_")
    yield ws
    shutil.rmtree(ws, ignore_errors=True)


@pytest.fixture
def fresh_client(tmp_workspace):
    """OSVClient in offline mode against an empty cache."""
    return OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=True)


def _make_pkg(name="lodash", version="4.17.15", ecosystem="npm"):
    """Build an OSVPackage with a supported ecosystem by default."""
    return OSVPackage(name=name, version=version, ecosystem=ecosystem)


def _fake_vuln(name="lodash", ecosystem="npm"):
    """Minimal OSV vuln dict that ``_parse_single_vuln`` can handle."""
    return {
        "id": "GHSA-test-test-test",
        "summary": f"Test vulnerability for {name}",
        "severity": [{"type": "CVSS_V3", "score": "7.5"}],
        "affected": [
            {
                "package": {"name": name, "ecosystem": ecosystem},
                "ranges": [
                    {
                        "type": "SEMVER",
                        "events": [
                            {"introduced": "0"},
                            {"fixed": "4.17.21"},
                        ],
                    }
                ],
            }
        ],
        "references": [],
    }


def _set_cache_timestamp(cache, key, age_seconds):
    """Rewrite a cache entry's timestamp to make it artificially old.

    Used to simulate stale cache entries without waiting for real time
    to pass.
    """
    conn = sqlite3.connect(cache.db_path)
    try:
        conn.execute(
            "UPDATE cache SET timestamp = ? "
            "WHERE package_ecosystem_version = ?",
            (time.time() - age_seconds, key),
        )
        conn.commit()
    finally:
        conn.close()


# ─── _parse_max_age ────────────────────────────────────────────


class TestParseMaxAge:
    """``--max-age`` duration string parsing."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("6h", 21600),
            ("30m", 1800),
            ("2d", 172800),
            ("90s", 90),
            ("48", 172800),  # bare integer → hours (matches --osv-ttl semantics)
            ("1.5h", 5400),
            ("1H", 3600),  # case-insensitive unit
            ("  12h  ", 43200),  # whitespace tolerated
        ],
    )
    def test_valid_forms(self, raw, expected):
        assert _parse_max_age(raw) == expected

    def test_none_returns_none(self):
        assert _parse_max_age(None) is None

    @pytest.mark.parametrize("raw", ["abc", "-5h", "", "h", "5x", "5hrs"])
    def test_invalid_raises_value_error(self, raw):
        with pytest.raises(ValueError):
            _parse_max_age(raw)


# ─── OSVCache.peek ─────────────────────────────────────────────


class TestOSVCachePeek:
    """``OSVCache.peek()`` returns entries without TTL check or deletion."""

    def test_missing_key_returns_none(self, tmp_workspace):
        cache = OSVCache(tmp_workspace)
        assert cache.peek("nonexistent|key|1.0.0") is None

    def test_returns_entry_tuple(self, tmp_workspace):
        cache = OSVCache(tmp_workspace)
        cache.set("npm|lodash|4.17.15", [{"id": "VULN-1"}], ttl=3600)
        entry = cache.peek("npm|lodash|4.17.15")
        assert entry is not None
        response, timestamp, ttl = entry
        assert response == [{"id": "VULN-1"}]
        assert isinstance(timestamp, float)
        assert ttl == 3600

    def test_does_not_apply_ttl(self, tmp_workspace):
        """An entry past its TTL should still be returned by ``peek()``.

        This is what distinguishes ``peek`` from ``get`` and is what
        ``--max-age`` relies on to apply its own per-run threshold.
        """
        cache = OSVCache(tmp_workspace, ttl=1)
        cache.set("npm|lodash|4.17.15", [{"id": "VULN-1"}], ttl=1)
        _set_cache_timestamp(cache, "npm|lodash|4.17.15", age_seconds=3600)

        # peek ignores TTL — entry is still returned
        assert cache.peek("npm|lodash|4.17.15") is not None
        # get applies TTL — same entry is treated as expired and deleted
        assert cache.get("npm|lodash|4.17.15") is None

    def test_corrupt_json_returns_none_and_deletes(self, tmp_workspace):
        cache = OSVCache(tmp_workspace)
        # Insert a corrupt-JSON entry directly into the DB.
        conn = sqlite3.connect(cache.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO cache "
                "(package_ecosystem_version, response_json, timestamp, ttl) "
                "VALUES (?, ?, ?, ?)",
                ("npm|corrupt|1.0.0", "{not valid json", time.time(), 86400),
            )
            conn.commit()
        finally:
            conn.close()

        assert cache.peek("npm|corrupt|1.0.0") is None

        # Corrupt entry should have been deleted.
        conn = sqlite3.connect(cache.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM cache "
                "WHERE package_ecosystem_version = ?",
                ("npm|corrupt|1.0.0",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == 0


# ─── OSVClient.get_cache_info ──────────────────────────────────


class TestGetCacheInfo:
    """``OSVClient.get_cache_info()`` — the ``cache_info`` block (issue #30)."""

    def test_empty_packages(self, fresh_client):
        info = fresh_client.get_cache_info([])
        assert info == {
            "last_refresh": None,
            "age_hours": None,
            "ttl_hours": 24.0,
            "is_stale": False,
            "stale_packages": [],
        }

    def test_no_cache_entries_all_stale(self, fresh_client):
        """Packages with no cache entries are reported as stale."""
        pkgs = [
            _make_pkg("lodash", "4.17.15"),
            _make_pkg("express", "4.17.0"),
        ]
        info = fresh_client.get_cache_info(pkgs)
        assert info["is_stale"] is True
        assert sorted(info["stale_packages"]) == ["express@4.17.0", "lodash@4.17.15"]
        assert info["last_refresh"] is None
        assert info["age_hours"] is None
        assert info["ttl_hours"] == 24.0

    def test_all_fresh_entries(self, fresh_client):
        pkg = _make_pkg()
        fresh_client.cache.set(pkg.cache_key(), [_fake_vuln()])
        info = fresh_client.get_cache_info([pkg])

        assert info["is_stale"] is False
        assert info["stale_packages"] == []
        assert info["last_refresh"] is not None
        # ISO 8601 UTC with a trailing Z
        assert info["last_refresh"].endswith("Z")
        assert "T" in info["last_refresh"]
        # age_hours should be small (entry was just written)
        assert info["age_hours"] is not None
        assert info["age_hours"] < 1.0
        assert info["ttl_hours"] == 24.0

    def test_one_stale_entry(self, fresh_client):
        fresh = _make_pkg("fresh", "1.0.0")
        stale = _make_pkg("stale", "2.0.0")
        fresh_client.cache.set(fresh.cache_key(), [])
        fresh_client.cache.set(stale.cache_key(), [])
        # Make 'stale' artificially old (48h, past the 24h TTL).
        _set_cache_timestamp(fresh_client.cache, stale.cache_key(), age_seconds=48 * 3600)

        info = fresh_client.get_cache_info([fresh, stale])
        assert info["is_stale"] is True
        assert info["stale_packages"] == ["stale@2.0.0"]
        # last_refresh & age_hours reflect the FRESH (most recent) entry
        assert info["last_refresh"] is not None
        assert info["age_hours"] < 1.0

    def test_stale_packages_sorted(self, fresh_client):
        pkgs = [
            _make_pkg("zebra", "1.0.0"),
            _make_pkg("alpha", "1.0.0"),
            _make_pkg("mid", "1.0.0"),
        ]
        info = fresh_client.get_cache_info(pkgs)
        assert info["stale_packages"] == [
            "alpha@1.0.0",
            "mid@1.0.0",
            "zebra@1.0.0",
        ]

    def test_ttl_hours_reflects_cache_ttl(self, tmp_workspace):
        client = OSVClient(workspace=tmp_workspace, ttl=3600, offline=True)
        info = client.get_cache_info([])
        assert info["ttl_hours"] == 1.0


# ─── OSVClient.query_packages: force_refresh ───────────────────


class TestForceRefresh:
    """``--refresh`` flag bypasses the OSV cache."""

    def test_force_refresh_bypasses_cache(self, tmp_workspace):
        """With ``force_refresh=True``, cached entries are ignored and the API is hit."""
        # Online client so force_refresh actually takes effect.
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        # Pre-populate cache with a vuln that would be returned if the
        # cache was consulted.
        client.cache.set(pkg.cache_key(), [_fake_vuln()])

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            result = client.query_packages([pkg], force_refresh=True)
            # Cache was bypassed → only the mocked API (empty) contributed.
            assert result == []
            # API was called for the force-refreshed package.
            mock_api.assert_called_once()

    def test_no_force_refresh_uses_cache(self, tmp_workspace):
        """Without ``force_refresh``, cached entries are used and the API is NOT hit."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()])

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            result = client.query_packages([pkg], force_refresh=False)
            # Cache was used → vuln returned.
            assert len(result) == 1
            assert result[0].id == "GHSA-test-test-test"
            # API was NOT called.
            mock_api.assert_not_called()

    def test_force_refresh_ignored_in_offline(self, tmp_workspace):
        """In offline mode, ``--refresh`` is silently ignored (no network)."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=True)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()])

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            result = client.query_packages([pkg], force_refresh=True)
            # Cache was used (force_refresh ignored in offline mode).
            assert len(result) == 1
            mock_api.assert_not_called()


# ─── OSVClient.query_packages: max_age ─────────────────────────


class TestMaxAge:
    """``--max-age`` flag overrides TTL for the current run only."""

    def test_max_age_marks_old_entry_stale(self, tmp_workspace):
        """An entry older than ``max_age`` is re-fetched from the API."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()])
        # Make entry 10h old.
        _set_cache_timestamp(client.cache, pkg.cache_key(), age_seconds=10 * 3600)

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            # max_age=6h → entry is stale (10h > 6h) → API hit
            result = client.query_packages([pkg], max_age=6 * 3600)
            assert result == []  # mocked API returned nothing
            mock_api.assert_called_once()

    def test_max_age_keeps_fresh_entry(self, tmp_workspace):
        """An entry younger than ``max_age`` is served from the cache."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()])
        # Make entry 10h old.
        _set_cache_timestamp(client.cache, pkg.cache_key(), age_seconds=10 * 3600)

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            # max_age=24h → entry is fresh (10h < 24h) → cache used
            result = client.query_packages([pkg], max_age=24 * 3600)
            assert len(result) == 1
            assert result[0].id == "GHSA-test-test-test"
            mock_api.assert_not_called()

    def test_max_age_does_not_change_stored_ttl(self, tmp_workspace):
        """``--max-age`` must NOT modify the stored TTL (per-run override only)."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()], ttl=86400)
        _set_cache_timestamp(client.cache, pkg.cache_key(), age_seconds=10 * 3600)

        with patch.object(client, "_batch_query_api", return_value=[]):
            client.query_packages([pkg], max_age=6 * 3600)

        entry = client.cache.peek(pkg.cache_key())
        assert entry is not None
        _, _, stored_ttl = entry
        assert stored_ttl == 86400

    def test_max_age_zero_acts_like_refresh(self, tmp_workspace):
        """``max_age=0`` treats every entry as stale (force-refresh equivalent)."""
        client = OSVClient(workspace=tmp_workspace, ttl=DEFAULT_TTL, offline=False)
        pkg = _make_pkg()
        client.cache.set(pkg.cache_key(), [_fake_vuln()])
        # Even a freshly-written entry (age ~0s) is stale per max_age=0.

        with patch.object(client, "_batch_query_api", return_value=[]) as mock_api:
            result = client.query_packages([pkg], max_age=0)
            assert result == []
            mock_api.assert_called_once()


# ─── scan_vulnerabilities: cache_info in output ────────────────


class TestScanVulnerabilitiesCacheInfo:
    """End-to-end: ``scan_vulnerabilities()`` output includes ``cache_info``."""

    def test_clean_app_no_deps_has_cache_info(self):
        """``clean_app`` has no dependency files → empty ``cache_info``."""
        fixture = os.path.join(FIXTURES_DIR, "clean_app")
        result = scan_vulnerabilities(fixture, offline=True)
        assert result["status"] == "ok"
        assert "cache_info" in result
        info = result["cache_info"]
        # No packages queried → cache_info takes the empty shape.
        assert info["is_stale"] is False
        assert info["stale_packages"] == []
        assert info["ttl_hours"] == 24.0

    def test_vulnerable_app_has_stale_cache_info(self):
        """``vulnerable_app`` has npm deps; offline mode → all stale."""
        fixture = os.path.join(FIXTURES_DIR, "vulnerable_app")
        result = scan_vulnerabilities(fixture, offline=True)
        assert result["status"] == "ok"
        assert "cache_info" in result
        info = result["cache_info"]
        # Offline mode → no cache entries written → all queried packages stale.
        assert info["is_stale"] is True
        assert len(info["stale_packages"]) > 0
        # npm packages from vulnerable_app's package.json
        assert "lodash@4.17.15" in info["stale_packages"]

    def test_cache_info_shape(self):
        """``cache_info`` dict has exactly the keys specified in issue #30."""
        fixture = os.path.join(FIXTURES_DIR, "clean_app")
        result = scan_vulnerabilities(fixture, offline=True)
        info = result["cache_info"]
        expected_keys = {
            "last_refresh",
            "age_hours",
            "ttl_hours",
            "is_stale",
            "stale_packages",
        }
        assert set(info.keys()) == expected_keys

    def test_cache_info_is_additive(self):
        """Adding cache_info must not remove or rename existing output keys."""
        fixture = os.path.join(FIXTURES_DIR, "clean_app")
        result = scan_vulnerabilities(fixture, offline=True)
        # Pre-issue-#30 output keys must still be present.
        for key in (
            "status",
            "workspace",
            "stats",
            "risk",
            "findings",
            "audit_available",
            "osv_stats",
            "recommendations",
        ):
            assert key in result, f"missing pre-existing key: {key}"


# ─── vuln-scan CLI: arg parsing & wiring ───────────────────────


class TestVulnScanCLI:
    """``--refresh`` and ``--max-age`` flags are parsed and wired through."""

    def test_execute_passes_refresh_and_max_age(self, tmp_workspace):
        """``execute()`` forwards ``--refresh`` and ``--max-age`` to the engine."""
        args = Namespace(
            workspace=None,
            severity=None,
            offline=True,
            osv_ttl=86400,
            refresh=True,
            max_age="6h",
        )
        with patch.object(
            vuln_scan_cmd, "scan_vulnerabilities", return_value={"status": "ok"}
        ) as mock_scan:
            result = vuln_scan_cmd.execute(args, tmp_workspace)
            assert result == {"status": "ok"}
            mock_scan.assert_called_once()
            _, kwargs = mock_scan.call_args
            assert kwargs.get("refresh") is True
            assert kwargs.get("max_age") == 21600  # 6h in seconds

    def test_execute_invalid_max_age_returns_error(self, tmp_workspace):
        args = Namespace(
            workspace=None,
            severity=None,
            offline=False,
            osv_ttl=86400,
            refresh=False,
            max_age="not-a-duration",
        )
        result = vuln_scan_cmd.execute(args, tmp_workspace)
        assert result["status"] == "error"
        assert result["error"] == "invalid_argument"
        assert "--max-age" in result["message"]

    def test_execute_no_flags_passes_defaults(self, tmp_workspace):
        args = Namespace(
            workspace=None,
            severity=None,
            offline=False,
            osv_ttl=86400,
            refresh=False,
            max_age=None,
        )
        with patch.object(
            vuln_scan_cmd, "scan_vulnerabilities", return_value={"status": "ok"}
        ) as mock_scan:
            vuln_scan_cmd.execute(args, tmp_workspace)
            _, kwargs = mock_scan.call_args
            assert kwargs.get("refresh") is False
            assert kwargs.get("max_age") is None
