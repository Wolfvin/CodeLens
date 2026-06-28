"""
Tests for OSV cache staleness reporting and the vuln-scan refresh / max-age
flags (GitHub issue #30).

Covers:
  - OSVClient.get_cache_info(): shape, freshness, stale-packages, max-age.
  - OSVCache.peek(): pure inspection (no mutation of expired entries).
  - OSVClient.query_packages(force_refresh=...): bypasses cache, updates it.
  - OSVClient.query_packages(max_age=...): treats fresh entries as stale.
  - vuln-scan CLI: --refresh / --max-age wiring + _parse_max_age parsing.
  - scan_vulnerabilities(): cache_info present in output (additive).

All tests are network-free: the OSV API layer (_batch_query_api and friends)
is mocked, and the SQLite cache is seeded directly.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from osv_client import OSVClient, OSVPackage  # noqa: E402
from vulnscan_engine import scan_vulnerabilities  # noqa: E402
from commands.vuln_scan import _parse_max_age, execute as vuln_scan_execute  # noqa: E402


# ─── Helpers ───────────────────────────────────────────────────

def _make_workspace():
    """Create an empty temp workspace and return its path."""
    return tempfile.mkdtemp(prefix="codelens_vuln_test_")


def _seed_cache_entry(client, package, age_seconds, response=None, ttl=86400):
    """Insert a cache row for ``package`` aged ``age_seconds`` directly into SQLite.

    Bypasses OSVCache.set() so we can backdate the timestamp for staleness
    tests. ``response`` defaults to an empty list (no vulnerabilities).
    """
    if response is None:
        response = []
    conn = sqlite3.connect(client.cache.db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO cache "
            "(package_ecosystem_version, response_json, timestamp, ttl) "
            "VALUES (?, ?, ?, ?)",
            (package.cache_key(), json.dumps(response), time.time() - age_seconds, ttl),
        )
        conn.commit()
    finally:
        conn.close()


def _npm_package(name="lodash", version="4.17.15"):
    return OSVPackage(name=name, version=version, ecosystem="npm")


def _write_package_json(workspace, deps):
    """Write a minimal package.json with the given dependencies."""
    pkg = {"name": "test-pkg", "version": "1.0.0", "dependencies": deps}
    with open(os.path.join(workspace, "package.json"), "w") as f:
        json.dump(pkg, f)


# ─── get_cache_info ────────────────────────────────────────────

class TestGetCacheInfo:
    """OSVClient.get_cache_info() — issue #30 staleness reporting."""

    def test_shape_and_keys(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            info = client.get_cache_info([_npm_package()])
            assert set(info.keys()) == {
                "last_refresh", "age_hours", "ttl_hours",
                "is_stale", "stale_packages",
            }
            assert info["stale_packages"] == []
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_cache_is_stale_no_coverage(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            info = client.get_cache_info([_npm_package()])
            # OSV-queriable package exists but nothing cached → stale.
            assert info["last_refresh"] is None
            assert info["age_hours"] is None
            assert info["ttl_hours"] == 24.0
            assert info["is_stale"] is True
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_fresh_entry_not_stale(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=60)  # 1 minute old
            info = client.get_cache_info([pkg])
            assert info["is_stale"] is False
            assert info["last_refresh"] is not None
            assert info["last_refresh"].endswith("Z")
            assert info["age_hours"] is not None
            assert 0.0 <= info["age_hours"] < 1.0
            assert info["ttl_hours"] == 24.0
            assert info["stale_packages"] == []
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_expired_entry_is_stale_and_listed(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            pkg = _npm_package()
            # 25h old → past the 24h TTL.
            _seed_cache_entry(client, pkg, age_seconds=25 * 3600)
            info = client.get_cache_info([pkg])
            assert info["is_stale"] is True
            assert "lodash@4.17.15" in info["stale_packages"]
            assert info["age_hours"] >= 24.0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_max_age_makes_fresh_entry_stale(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            pkg = _npm_package()
            # 10h old — fresh per the 24h stored TTL, but stale per --max-age 6h.
            _seed_cache_entry(client, pkg, age_seconds=10 * 3600)
            info = client.get_cache_info([pkg], max_age=6 * 3600)
            assert info["ttl_hours"] == 6.0
            assert info["is_stale"] is True
            assert "lodash@4.17.15" in info["stale_packages"]
            # And without the override it is fresh.
            info_default = client.get_cache_info([pkg])
            assert info_default["ttl_hours"] == 24.0
            assert info_default["is_stale"] is False
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_peek_does_not_mutate_expired_entries(self):
        """get_cache_info must not delete expired entries (pure inspection)."""
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=48 * 3600)  # well past TTL
            # Inspect twice — the entry must survive the first inspection.
            client.get_cache_info([pkg])
            info = client.get_cache_info([pkg])
            assert info["is_stale"] is True
            assert info["last_refresh"] is not None  # entry still present
            # Direct peek confirmation:
            assert client.cache.peek(pkg.cache_key()) is not None
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_last_refresh_is_most_recent_among_packages(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            old_pkg = OSVPackage(name="left-pad", version="1.0.0", ecosystem="npm")
            new_pkg = OSVPackage(name="lodash", version="4.17.15", ecosystem="npm")
            _seed_cache_entry(client, old_pkg, age_seconds=20 * 3600)  # 20h
            _seed_cache_entry(client, new_pkg, age_seconds=1 * 3600)   # 1h
            info = client.get_cache_info([old_pkg, new_pkg])
            # last_refresh should reflect the 1h-old entry.
            assert info["age_hours"] is not None
            assert info["age_hours"] < 2.0
            assert info["is_stale"] is False  # newest entry is fresh
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── query_packages: --refresh ─────────────────────────────────

class TestRefreshFlag:
    """OSVClient.query_packages(force_refresh=...) — issue #30 --refresh."""

    def test_refresh_bypasses_cache_and_calls_api(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=False)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=60)  # cached & fresh
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], force_refresh=True)
            assert m.call_count == 1
            sent = m.call_args[0][0]
            assert len(sent) == 1 and sent[0].name == "lodash"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_default_uses_cache_no_api_call(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=False)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=60)
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], force_refresh=False)
            assert m.call_count == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_refresh_ignored_in_offline_mode(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=60)
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], force_refresh=True)
            assert m.call_count == 0  # cannot hit network → falls back to cache
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── query_packages: --max-age ─────────────────────────────────

class TestMaxAgeFlag:
    """OSVClient.query_packages(max_age=...) — issue #30 --max-age."""

    def test_max_age_treats_fresh_entry_as_stale(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=False)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=10 * 3600)  # 10h old
            # Without max-age: cache hit (10h < 24h stored TTL).
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg])
            assert m.call_count == 0
            # With max-age=6h: 10h > 6h → re-fetched.
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], max_age=6 * 3600)
            assert m.call_count == 1
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_max_age_below_age_uses_cache(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=False)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=2 * 3600)  # 2h old
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], max_age=6 * 3600)  # 2h < 6h → fresh
            assert m.call_count == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_max_age_ignored_when_force_refresh_set(self):
        ws = _make_workspace()
        try:
            client = OSVClient(workspace=ws, ttl=86400, offline=False)
            pkg = _npm_package()
            _seed_cache_entry(client, pkg, age_seconds=2 * 3600)
            with patch.object(client, "_batch_query_api", return_value=[]) as m:
                client.query_packages([pkg], force_refresh=True, max_age=6 * 3600)
            assert m.call_count == 1  # force_refresh wins; cache bypassed
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── _parse_max_age ────────────────────────────────────────────

class TestParseMaxAge:
    """vuln-scan --max-age duration parsing."""

    @pytest.mark.parametrize("raw,expected", [
        ("6h", 6 * 3600),
        ("30m", 30 * 60),
        ("90s", 90),
        ("2d", 2 * 86400),
        ("12", 12 * 3600),       # bare integer → hours
        ("1.5h", 5400),          # fractional
        ("  3h  ", 3 * 3600),    # surrounding whitespace
        ("6H", 6 * 3600),        # uppercase unit
    ])
    def test_valid(self, raw, expected):
        assert _parse_max_age(raw) == expected

    def test_none_returns_none(self):
        assert _parse_max_age(None) is None

    @pytest.mark.parametrize("raw", ["6x", "h", "abc", "6hr", "", "-3h"])
    def test_invalid_raises(self, raw):
        with pytest.raises(ValueError):
            _parse_max_age(raw)

    def test_zero_or_negative_rejected(self):
        with pytest.raises(ValueError):
            _parse_max_age("0h")
        with pytest.raises(ValueError):
            _parse_max_age("0")


# ─── vuln-scan command wiring ──────────────────────────────────

class _FakeArgs:
    """Minimal stand-in for an argparse Namespace for vuln-scan."""

    def __init__(self, **kwargs):
        self.workspace = kwargs.get("workspace", "/tmp/ws")
        self.severity = kwargs.get("severity", None)
        self.offline = kwargs.get("offline", False)
        self.osv_ttl = kwargs.get("osv_ttl", 86400)
        self.refresh = kwargs.get("refresh", False)
        self.max_age = kwargs.get("max_age", None)


class TestVulnScanCommandWiring:
    """vuln-scan execute() forwards flags to scan_vulnerabilities."""

    def test_execute_passes_refresh_and_max_age(self):
        captured = {}

        def fake_scan(workspace, **kwargs):
            captured.update(kwargs)
            captured["workspace"] = workspace
            return {"status": "ok"}

        with patch("commands.vuln_scan.scan_vulnerabilities", side_effect=fake_scan):
            args = _FakeArgs(refresh=True, max_age="6h")
            result = vuln_scan_execute(args, workspace="/tmp/ws")
        assert result["status"] == "ok"
        assert captured["refresh"] is True
        assert captured["max_age"] == 6 * 3600  # parsed to seconds
        assert captured["offline"] is False

    def test_execute_invalid_max_age_returns_error(self):
        with patch("commands.vuln_scan.scan_vulnerabilities") as m:
            args = _FakeArgs(max_age="not-a-duration")
            result = vuln_scan_execute(args, workspace="/tmp/ws")
        assert result["status"] == "error"
        assert result["error"] == "invalid_argument"
        assert "max-age" in result["message"]
        assert m.call_count == 0  # scan never invoked on bad input

    def test_execute_no_max_age_passes_none(self):
        captured = {}

        def fake_scan(workspace, **kwargs):
            captured.update(kwargs)
            return {"status": "ok"}

        with patch("commands.vuln_scan.scan_vulnerabilities", side_effect=fake_scan):
            args = _FakeArgs()
            vuln_scan_execute(args, workspace="/tmp/ws")
        assert captured["max_age"] is None
        assert captured["refresh"] is False


# ─── scan_vulnerabilities integration ──────────────────────────

class TestScanVulnerabilitiesCacheInfo:
    """scan_vulnerabilities() surfaces cache_info (additive, issue #30)."""

    def test_cache_info_present_no_deps(self):
        ws = _make_workspace()
        try:
            result = scan_vulnerabilities(
                ws, offline=True,
                config={"vulnscan": {"skip_audit_tools": True}},
            )
            assert result["status"] == "ok"
            assert "cache_info" in result
            info = result["cache_info"]
            assert info["is_stale"] is False  # no packages → nothing stale
            assert info["last_refresh"] is None
            assert info["ttl_hours"] == 24.0
            assert info["stale_packages"] == []
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_cache_info_reflects_seeded_fresh_cache(self):
        ws = _make_workspace()
        try:
            _write_package_json(ws, {"lodash": "4.17.15"})
            # Pre-seed the cache before running so offline mode finds it.
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            _seed_cache_entry(client, _npm_package(), age_seconds=120)
            result = scan_vulnerabilities(
                ws, offline=True,
                config={"vulnscan": {"skip_audit_tools": True}},
            )
            info = result["cache_info"]
            assert info["last_refresh"] is not None
            assert info["is_stale"] is False
            assert info["stale_packages"] == []
            assert info["ttl_hours"] == 24.0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_cache_info_with_max_age_reports_stale(self):
        ws = _make_workspace()
        try:
            _write_package_json(ws, {"lodash": "4.17.15"})
            client = OSVClient(workspace=ws, ttl=86400, offline=True)
            # 10h old — fresh per 24h stored TTL, stale per --max-age 6h.
            _seed_cache_entry(client, _npm_package(), age_seconds=10 * 3600)
            result = scan_vulnerabilities(
                ws, offline=True,
                config={"vulnscan": {"skip_audit_tools": True}},
                max_age=6 * 3600,
            )
            info = result["cache_info"]
            assert info["ttl_hours"] == 6.0
            assert info["is_stale"] is True
            assert "lodash@4.17.15" in info["stale_packages"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_existing_output_fields_unchanged(self):
        """cache_info is additive — pre-existing top-level keys still present."""
        ws = _make_workspace()
        try:
            result = scan_vulnerabilities(
                ws, offline=True,
                config={"vulnscan": {"skip_audit_tools": True}},
            )
            for key in ("status", "workspace", "stats", "risk", "findings",
                        "audit_available", "osv_stats", "recommendations", "cache_info"):
                assert key in result, f"missing pre-existing key: {key}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)
