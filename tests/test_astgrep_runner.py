"""
Tests for scripts/astgrep_runner.py — Phase 1 of issue #68.

Covers the binary auto-provisioning contract:
  1. Platform detection — known + unknown platforms.
  2. SHA-256 verification — correct + mismatched hashes.
  3. Cache layout — directory structure + idempotent cache hits.
  4. Graceful fallback — network failure, SHA mismatch, unsupported
     platform, placeholder hash all return ProvisionResult(ok=False)
     instead of raising.
  5. is_available() — quick boolean check without triggering download.
  6. CLI entry points (status / provision) — exit codes.

These tests deliberately do NOT hit the network. The download path
is exercised only via mocks (monkeypatched ``_download``), so the
tests run in CI / sandboxes without internet access.

Run: python -m pytest tests/test_astgrep_runner.py -v
"""

from __future__ import annotations

import hashlib
import os
import platform as _platform
import sys
import tarfile
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import astgrep_runner  # noqa: E402
from astgrep_runner import (  # noqa: E402
    ASTGREP_RELEASES,
    ASTGREP_VERSION,
    CACHE_ROOT,
    PlatformInfo,
    ProvisionResult,
    cache_dir_for,
    cached_binary_path,
    detect_platform,
    get_astgrep_path,
    is_available,
    provision,
    sha256_file,
)


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


class TestPlatformDetection:
    """detect_platform() must identify the host platform or return None."""

    def test_detect_platform_returns_platforminfo_or_none(self):
        """On any host, detect_platform returns PlatformInfo or None."""
        result = detect_platform()
        assert result is None or isinstance(result, PlatformInfo)

    def test_detect_platform_for_current_host_matches_release_dict(self):
        """If detect_platform returns a value, its id must be in ASTGREP_RELEASES."""
        result = detect_platform()
        if result is None:
            pytest.skip("current platform not in ASTGREP_RELEASES — test only meaningful on supported hosts")
        assert result.id in ASTGREP_RELEASES, (
            f"detect_platform returned id={result.id!r} but ASTGREP_RELEASES "
            f"has no entry for it"
        )

    def test_detect_platform_unknown_os_returns_none(self):
        """A platform with sys.platform='freebsd9' should return None."""
        with patch.object(sys, "platform", "freebsd9"):
            with patch.object(_platform, "machine", return_value="x86_64"):
                assert detect_platform() is None

    def test_detect_platform_normalizes_amd64_to_x86_64(self):
        """``amd64`` and ``x86_64`` must both map to the same release id."""
        with patch.object(sys, "platform", "linux"):
            with patch.object(_platform, "machine", return_value="amd64"):
                result = detect_platform()
                assert result is not None
                assert result.id == "x86_64-linux"

    def test_detect_platform_normalizes_aarch64_to_aarch64_linux(self):
        """``aarch64`` on Linux maps to ``aarch64-linux``."""
        with patch.object(sys, "platform", "linux"):
            with patch.object(_platform, "machine", return_value="aarch64"):
                result = detect_platform()
                assert result is not None
                assert result.id == "aarch64-linux"


# ---------------------------------------------------------------------------
# SHA-256 verification
# ---------------------------------------------------------------------------


class TestSha256File:
    """sha256_file() must match hashlib.sha256 for known content."""

    def test_sha256_file_matches_hashlib(self, tmp_path):
        content = b"hello ast-grep\n"
        p = tmp_path / "bin"
        p.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert sha256_file(p) == expected

    def test_sha256_file_empty_file(self, tmp_path):
        p = tmp_path / "empty"
        p.write_bytes(b"")
        assert sha256_file(p) == hashlib.sha256(b"").hexdigest()

    def test_sha256_file_large_file_streamed(self, tmp_path):
        """File larger than the 64KB read chunk must hash correctly."""
        p = tmp_path / "large"
        content = b"x" * (200 * 1024)  # 200 KB
        p.write_bytes(content)
        assert sha256_file(p) == hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------


class TestCacheLayout:
    """cache_dir_for() + cached_binary_path() must follow the documented layout."""

    def test_cache_dir_layout(self):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        d = cache_dir_for(plat, version="9.9.9")
        assert d == CACHE_ROOT / "9.9.9" / "x86_64-linux"

    def test_cached_binary_path_uses_sg_on_posix(self):
        with patch.object(sys, "platform", "linux"):
            plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
            p = cached_binary_path(plat, version="9.9.9")
            assert p.name == "sg"

    def test_cached_binary_path_uses_sg_exe_on_windows(self):
        with patch.object(sys, "platform", "win32"):
            plat = PlatformInfo("x86_64-windows", "x86_64", "windows")
            p = cached_binary_path(plat, version="9.9.9")
            assert p.name == "sg.exe"


# ---------------------------------------------------------------------------
# Graceful fallback — provision() must never raise
# ---------------------------------------------------------------------------


class TestProvisionGracefulFallback:
    """provision() must return ProvisionResult(ok=False) for every failure mode.

    This is the core safety contract: ast-grep unavailability must
    NEVER crash a CodeLens command. Every failure path (network,
    SHA mismatch, unsupported platform, placeholder hash) must return
    a structured result, not raise.
    """

    def test_provision_unsupported_platform_returns_ok_false(self):
        """When detect_platform returns None, provision returns ok=False."""
        with patch.object(astgrep_runner, "detect_platform", return_value=None):
            result = provision()
        assert isinstance(result, ProvisionResult)
        assert result.ok is False
        assert result.binary_path is None
        assert "unsupported platform" in result.reason.lower()

    def test_provision_placeholder_hash_returns_ok_false(self):
        """When ASTGREP_RELEASES hash is a placeholder, provision refuses to
        download (safety guard: cannot verify SHA without the real hash)."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        # Force the release entry to have a placeholder hash
        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", "PLACEHOLDER_TEST")},
            ):
                result = provision()
        assert result.ok is False
        assert "placeholder" in result.reason.lower()

    def test_provision_network_failure_returns_ok_false(self, tmp_path, monkeypatch):
        """When download fails (URLError), provision returns ok=False, no exception."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        # Real SHA-256 of the test binary we'll stage
        test_binary_content = b"#!/bin/sh\necho fake ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        # Redirect CACHE_ROOT to tmp_path so we don't pollute the real cache
        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        def fake_download(url, dest, timeout=30.0):
            raise urllib.error.URLError("simulated network failure")

        def fake_extract(archive_path, plat, dest_dir):
            # Should never be called because download failed
            raise AssertionError("extract should not be called when download fails")

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        result = provision()
        assert result.ok is False
        assert "download failed" in result.reason.lower()
        assert result.binary_path is None

    def test_provision_sha_mismatch_deletes_binary_and_returns_ok_false(
        self, tmp_path, monkeypatch
    ):
        """When downloaded binary's SHA does not match, it is deleted and
        provision returns ok=False. The tampered binary is NEVER executed."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho fake ast-grep\n"
        actual_sha = hashlib.sha256(test_binary_content).hexdigest()
        # An obviously-wrong expected hash
        wrong_sha = "0" * 64

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        def fake_download(url, dest, timeout=30.0):
            # Stage a fake archive that extract will pull from
            dest.write_bytes(b"fake archive content")

        def fake_extract(archive_path, plat, dest_dir):
            # Write the "binary" to dest_dir
            bin_path = dest_dir / "sg"
            bin_path.write_bytes(test_binary_content)
            return bin_path

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", wrong_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        result = provision()

        assert result.ok is False
        assert "sha-256 mismatch" in result.reason.lower()
        # The tampered binary MUST have been deleted — never leave it on disk
        bin_path = cached_binary_path(plat)
        assert not bin_path.exists(), (
            f"tampered binary must be deleted after SHA mismatch; found at {bin_path}"
        )

    def test_provision_success_returns_ok_true_with_path(self, tmp_path, monkeypatch):
        """Happy path: download + extract + SHA match → ok=True with binary_path."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho real ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        def fake_download(url, dest, timeout=30.0):
            dest.write_bytes(b"fake archive content")

        def fake_extract(archive_path, plat, dest_dir):
            bin_path = dest_dir / "sg"
            bin_path.write_bytes(test_binary_content)
            return bin_path

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        result = provision()

        assert result.ok is True
        assert result.binary_path is not None
        assert result.binary_path.exists()
        # Binary should be executable on POSIX
        if sys.platform != "win32":
            import stat as _stat
            mode = result.binary_path.stat().st_mode
            assert mode & _stat.S_IXUSR, "binary must be executable by owner"

    def test_provision_cache_hit_is_idempotent(self, tmp_path, monkeypatch):
        """A second provision() call with a valid cache must not re-download."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho real ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        download_call_count = [0]

        def fake_download(url, dest, timeout=30.0):
            download_call_count[0] += 1
            dest.write_bytes(b"fake archive content")

        def fake_extract(archive_path, plat, dest_dir):
            bin_path = dest_dir / "sg"
            bin_path.write_bytes(test_binary_content)
            return bin_path

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        first = provision()
                        second = provision()

        assert first.ok is True
        assert second.ok is True
        assert download_call_count[0] == 1, (
            f"second provision() must hit cache, not re-download. "
            f"Download was called {download_call_count[0]} times."
        )
        assert second.binary_path == first.binary_path

    def test_provision_force_redownloads_even_on_cache_hit(self, tmp_path, monkeypatch):
        """force=True must re-download even when the cache is valid."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho real ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        download_call_count = [0]

        def fake_download(url, dest, timeout=30.0):
            download_call_count[0] += 1
            dest.write_bytes(b"fake archive content")

        def fake_extract(archive_path, plat, dest_dir):
            bin_path = dest_dir / "sg"
            bin_path.write_bytes(test_binary_content)
            return bin_path

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        provision()
                        provision(force=True)

        assert download_call_count[0] == 2, (
            f"force=True must trigger re-download. "
            f"Download was called {download_call_count[0]} times."
        )


# ---------------------------------------------------------------------------
# get_astgrep_path / is_available — public API
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """get_astgrep_path() and is_available() never raise."""

    def test_get_astgrep_path_returns_none_on_unsupported_platform(self):
        with patch.object(astgrep_runner, "detect_platform", return_value=None):
            assert get_astgrep_path() is None

    def test_get_astgrep_path_returns_string_when_provisioned(
        self, tmp_path, monkeypatch
    ):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho real ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")

        def fake_download(url, dest, timeout=30.0):
            dest.write_bytes(b"fake archive content")

        def fake_extract(archive_path, plat, dest_dir):
            bin_path = dest_dir / "sg"
            bin_path.write_bytes(test_binary_content)
            return bin_path

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                with patch.object(astgrep_runner, "_download", side_effect=fake_download):
                    with patch.object(astgrep_runner, "_extract_binary", side_effect=fake_extract):
                        path = get_astgrep_path()
        assert path is not None
        assert isinstance(path, str)
        assert os.path.exists(path)

    def test_is_available_returns_false_on_unsupported_platform(self):
        with patch.object(astgrep_runner, "detect_platform", return_value=None):
            assert is_available() is False

    def test_is_available_returns_false_when_hash_is_placeholder(self):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", "PLACEHOLDER_TEST")},
            ):
                assert is_available() is False

    def test_is_available_returns_true_when_cached_and_verified(
        self, tmp_path, monkeypatch
    ):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho real ast-grep\n"
        expected_sha = hashlib.sha256(test_binary_content).hexdigest()

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")
        # Pre-populate the cache
        bin_path = cached_binary_path(plat)
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_bytes(test_binary_content)

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", expected_sha)},
            ):
                assert is_available() is True

    def test_is_available_returns_false_when_sha_does_not_match(
        self, tmp_path, monkeypatch
    ):
        """If the cached binary's SHA does not match the expected value
        (e.g. file was tampered with on disk), is_available returns False."""
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        test_binary_content = b"#!/bin/sh\necho tampered\n"

        monkeypatch.setattr(astgrep_runner, "CACHE_ROOT", tmp_path / "cache")
        bin_path = cached_binary_path(plat)
        bin_path.parent.mkdir(parents=True, exist_ok=True)
        bin_path.write_bytes(test_binary_content)

        with patch.object(astgrep_runner, "detect_platform", return_value=plat):
            with patch.dict(
                astgrep_runner.ASTGREP_RELEASES,
                {"x86_64-linux": ("ast-grep-linux-x64.tar.gz", "0" * 64)},
            ):
                assert is_available() is False


# ---------------------------------------------------------------------------
# Extract helpers — archive format support
# ---------------------------------------------------------------------------


class TestExtractBinary:
    """_extract_binary must find sg / sg.exe in tar.gz and zip archives."""

    def test_extract_binary_from_tar_gz_posix(self, tmp_path):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        # Build a tar.gz with a single `sg` file inside
        archive = tmp_path / "ast-grep.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            bin_content = b"#!/bin/sh\necho ast-grep\n"
            info = tarfile.TarInfo(name="sg")
            info.size = len(bin_content)
            import io
            tf.addfile(info, io.BytesIO(bin_content))

        dest_dir = tmp_path / "extract"
        dest_dir.mkdir()
        extracted = astgrep_runner._extract_binary(archive, plat, dest_dir)
        assert extracted is not None
        assert extracted.name == "sg"
        assert extracted.read_bytes() == bin_content

    def test_extract_binary_from_zip_windows(self, tmp_path):
        plat = PlatformInfo("x86_64-windows", "x86_64", "windows")
        archive = tmp_path / "ast-grep.zip"
        bin_content = b"fake windows binary\r\n"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("sg.exe", bin_content)

        dest_dir = tmp_path / "extract"
        dest_dir.mkdir()
        with patch.object(sys, "platform", "win32"):
            extracted = astgrep_runner._extract_binary(archive, plat, dest_dir)
        assert extracted is not None
        assert extracted.name == "sg.exe"
        assert extracted.read_bytes() == bin_content

    def test_extract_binary_returns_none_when_binary_missing_from_archive(
        self, tmp_path
    ):
        plat = PlatformInfo("x86_64-linux", "x86_64", "linux")
        archive = tmp_path / "ast-grep.tar.gz"
        # Archive contains only a README, not the `sg` binary
        with tarfile.open(archive, "w:gz") as tf:
            info = tarfile.TarInfo(name="README.md")
            info.size = len(b"readme")
            import io
            tf.addfile(info, io.BytesIO(b"readme"))

        dest_dir = tmp_path / "extract"
        dest_dir.mkdir()
        extracted = astgrep_runner._extract_binary(archive, plat, dest_dir)
        assert extracted is None


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


class TestModuleInvariants:
    """Static invariants of ASTGREP_RELEASES that must always hold."""

    def test_every_release_entry_has_2_tuple(self):
        for plat_id, entry in ASTGREP_RELEASES.items():
            assert isinstance(entry, tuple), f"{plat_id}: entry must be tuple"
            assert len(entry) == 2, f"{plat_id}: entry must be 2-tuple"
            asset, sha = entry
            assert isinstance(asset, str) and asset, f"{plat_id}: asset name non-empty str"
            assert isinstance(sha, str) and sha, f"{plat_id}: sha non-empty str"

    def test_placeholder_hashes_are_marked(self):
        """Until real hashes are populated, entries start with PLACEHOLDER_."""
        # This is a deliberate safety guard: a placeholder hash means
        # ast-grep is treated as unavailable rather than executing an
        # unverified binary. When the hashes are populated for real,
        # this test should be updated to assert they are 64-char hex.
        for plat_id, (_, sha) in ASTGREP_RELEASES.items():
            if not sha.startswith("PLACEHOLDER"):
                # Real hash — must be 64-char lowercase hex
                assert len(sha) == 64, f"{plat_id}: real SHA-256 must be 64 chars"
                assert all(c in "0123456789abcdef" for c in sha), (
                    f"{plat_id}: real SHA-256 must be lowercase hex"
                )

    def test_version_is_string(self):
        assert isinstance(ASTGREP_VERSION, str)
        assert ASTGREP_VERSION

    def test_cache_root_under_home_codelens(self):
        """CACHE_ROOT must live under ~/.codelens/ per the project convention."""
        assert ".codelens" in CACHE_ROOT.parts
        assert CACHE_ROOT.parts[-2:] == ("ast-grep",) or CACHE_ROOT.parts[-1] == "ast-grep"
