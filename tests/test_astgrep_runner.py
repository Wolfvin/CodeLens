"""
Tests for the ast-grep runner (issue #68 Phase 1).

Covers:
- platform detection + labeling
- cache path structure
- SHA-256 compute + verify (match, mismatch, missing sidecar)
- is_available() gate (False when not installed, True when cached + verified)
- ensure_installed() with mocked download (success, download failure,
  extraction failure, SHA mismatch on pinned hash, force re-download)
- run() with mocked subprocess + auto-install gate
- clear_cache() cleanup
- graceful fallback on unsupported platform

Tests are hermetic — no real network calls, no real binary execution.
All downloads are mocked via monkeypatching ``urllib.request.urlopen``
and all subprocess calls via ``subprocess.run``.

Run with::

    python -m pytest tests/test_astgrep_runner.py -v
"""

from __future__ import annotations

import io
import json
import os
import platform as _platform
import stat
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

import astgrep_runner as ag  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_cache_root(tmp_path, monkeypatch):
    """Redirect ``~/.codelens/ast-grep/`` to a temp dir."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home / ".codelens" / "ast-grep"


@pytest.fixture
def supported_platform(monkeypatch):
    """Force-detect as linux-x86_64 regardless of the real platform."""
    monkeypatch.setattr(_platform, "system", lambda: "Linux")
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
    return ("linux", "x86_64")


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def test_detect_platform_linux_x86_64(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "Linux")
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
    assert ag.detect_platform() == ("linux", "x86_64")


def test_detect_platform_darwin_arm64(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "Darwin")
    monkeypatch.setattr(_platform, "machine", lambda: "arm64")
    assert ag.detect_platform() == ("darwin", "arm64")


def test_detect_platform_windows_x86_64(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "Windows")
    monkeypatch.setattr(_platform, "machine", lambda: "AMD64")
    assert ag.detect_platform() == ("windows", "amd64")


def test_detect_platform_unsupported(monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
    with pytest.raises(ag.AstgrepUnavailable, match="unsupported platform"):
        ag.detect_platform()


def test_get_platform_label(supported_platform):
    assert ag.get_platform_label() == "linux-x86_64"


# ---------------------------------------------------------------------------
# Cache paths
# ---------------------------------------------------------------------------


def test_cache_root_under_home(fake_cache_root):
    root = ag.get_cache_root()
    assert root == fake_cache_root
    assert str(root).endswith(os.path.join(".codelens", "ast-grep"))


def test_version_dir_includes_version_and_platform(fake_cache_root, supported_platform):
    vd = ag.get_version_dir("0.44.0")
    assert "0.44.0" in str(vd)
    assert "linux-x86_64" in str(vd)


def test_binary_path_has_correct_name(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    bp = ag.get_binary_path("0.44.0")
    assert bp.name == "ast-grep"


def test_binary_path_has_exe_on_windows(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    bp = ag.get_binary_path("0.44.0")
    assert bp.name == "ast-grep.exe"


# ---------------------------------------------------------------------------
# SHA-256
# ---------------------------------------------------------------------------


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    # Known SHA-256 of "hello world"
    assert ag.compute_sha256(f) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def test_verify_sha256_with_expected_match(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert ag.verify_sha256(f, expected=expected) is True


def test_verify_sha256_with_expected_mismatch(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    expected = "0000000000000000000000000000000000000000000000000000000000000000"
    assert ag.verify_sha256(f, expected=expected) is False


def test_verify_sha256_case_insensitive_expected(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    expected = "B94D27B9934D3E08A52E52D7DA7DABFAC484EFE37A5380EE9088F7ACE2EFCDE9"
    assert ag.verify_sha256(f, expected=expected) is True


def test_verify_sha256_missing_file(tmp_path):
    f = tmp_path / "nonexistent"
    assert ag.verify_sha256(f, expected="anything") is False


def test_verify_sha256_no_sidecar_returns_true(tmp_path):
    """Without an expected hash and no sidecar file, verify returns True
    (first-install scenario — caller should write a sidecar)."""
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    assert ag.verify_sha256(f, expected=None) is True


def test_verify_sha256_sidecar_match(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    sidecar = tmp_path / ".sha256"
    sidecar.write_text("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
    assert ag.verify_sha256(f, expected=None) is True


def test_verify_sha256_sidecar_mismatch_detects_tampering(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"tampered content")
    sidecar = tmp_path / ".sha256"
    sidecar.write_text("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
    assert ag.verify_sha256(f, expected=None) is False


def test_write_sha256_sidecar(tmp_path):
    f = tmp_path / "bin"
    f.write_bytes(b"hello world")
    sha = ag._write_sha256_sidecar(f)
    assert sha == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    sidecar = tmp_path / ".sha256"
    assert sidecar.is_file()
    assert sidecar.read_text() == sha


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------


def test_is_available_false_when_not_installed(fake_cache_root, supported_platform):
    assert ag.is_available() is False


def test_is_available_false_on_unsupported_platform(fake_cache_root, monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")
    assert ag.is_available() is False


def test_is_available_true_when_cached_and_verified(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # Simulate an installed binary + sidecar
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"fake binary content")
    ag._write_sha256_sidecar(binary)
    assert ag.is_available() is True


def test_is_available_false_when_sidecar_mismatch(fake_cache_root, supported_platform, monkeypatch):
    """Tampered binary (hash doesn't match sidecar) → unavailable."""
    monkeypatch.setattr(sys, "platform", "linux")
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"tampered")
    sidecar = version_dir / ".sha256"
    sidecar.write_text("0" * 64)  # wrong hash
    assert ag.is_available() is False


# ---------------------------------------------------------------------------
# ensure_installed() — mocked download
# ---------------------------------------------------------------------------


def _make_fake_zip(zip_path: Path, binary_name: str = "ast-grep", content: bytes = b"fake binary") -> None:
    """Create a zip file containing a single binary entry."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(binary_name, content)


def _mock_download_success(zip_content: bytes):
    """Return a monkeypatch callable that yields ``zip_content`` bytes."""
    class _FakeResponse:
        def __init__(self, content):
            self._content = content
            self.status = 200
        def read(self, n=-1):
            if n is None or n < 0:
                data, self._content = self._content, b""
            else:
                data, self._content = self._content[:n], self._content[n:]
            return data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _fake_urlopen(req, timeout=None):
        return _FakeResponse(zip_content)
    return _fake_urlopen


def test_ensure_installed_success(fake_cache_root, supported_platform, monkeypatch):
    """Full happy path: download → extract → chmod → sidecar → metadata."""
    monkeypatch.setattr(sys, "platform", "linux")
    # Build a real zip in memory
    import io as _io
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ast-grep", b"#!/bin/sh\necho fake\n")
    zip_bytes = buf.getvalue()

    monkeypatch.setattr(urllib.request, "urlopen", _mock_download_success(zip_bytes))

    result = ag.ensure_installed()
    assert result.success is True
    assert result.version == ag.ASTGREP_VERSION
    assert result.platform_label == "linux-x86_64"
    assert result.binary_path is not None
    assert result.binary_path.is_file()
    assert result.sha256 is not None
    assert result.from_cache is False

    # Sidecar written
    sidecar = result.binary_path.parent / ".sha256"
    assert sidecar.is_file()

    # Metadata written
    meta = ag.get_metadata_path()
    assert meta.is_file()
    data = json.loads(meta.read_text())
    key = f"{ag.ASTGREP_VERSION}/linux-x86_64"
    assert key in data["installs"]

    # Binary is executable on Unix
    st = result.binary_path.stat()
    assert st.st_mode & stat.S_IXUSR


def test_ensure_installed_from_cache(fake_cache_root, supported_platform, monkeypatch):
    """Second call should hit the cache, not re-download."""
    monkeypatch.setattr(sys, "platform", "linux")

    # Pre-populate cache
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"cached binary")
    ag._write_sha256_sidecar(binary)

    # urlopen should NOT be called
    def _fail_urlopen(*a, **kw):
        raise AssertionError("should not download — cache hit expected")
    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)

    result = ag.ensure_installed()
    assert result.success is True
    assert result.from_cache is True
    assert result.binary_path == binary


def test_ensure_installed_force_redownload(fake_cache_root, supported_platform, monkeypatch):
    """``force=True`` should re-download even if cache exists."""
    monkeypatch.setattr(sys, "platform", "linux")

    # Pre-populate cache
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"old binary")
    ag._write_sha256_sidecar(binary)

    # Mock download with new binary content
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ast-grep", b"new binary")
    monkeypatch.setattr(urllib.request, "urlopen", _mock_download_success(buf.getvalue()))

    result = ag.ensure_installed(force=True)
    assert result.success is True
    assert result.from_cache is False
    assert result.binary_path.read_bytes() == b"new binary"


def test_ensure_installed_download_failure(fake_cache_root, supported_platform, monkeypatch):
    """Network failure → graceful failure, not crash."""
    monkeypatch.setattr(sys, "platform", "linux")

    def _fail_urlopen(*a, **kw):
        raise urllib.error.URLError("network unreachable")
    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)

    result = ag.ensure_installed()
    assert result.success is False
    assert "download failed" in result.error
    assert result.binary_path is None


def test_ensure_installed_unsupported_platform(fake_cache_root, monkeypatch):
    monkeypatch.setattr(_platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(_platform, "machine", lambda: "x86_64")

    result = ag.ensure_installed()
    assert result.success is False
    assert "unsupported platform" in result.error


def test_ensure_installed_sha_mismatch_on_pinned_hash(fake_cache_root, supported_platform, monkeypatch):
    """When EXPECTED_SHA256 has a pinned hash and the download doesn't match,
    install must fail and the zip must be deleted."""
    monkeypatch.setattr(sys, "platform", "linux")

    # Pin a wrong hash
    fake_hash = "0" * 64
    monkeypatch.setitem(
        ag.EXPECTED_SHA256,
        (ag.ASTGREP_VERSION, "linux-x86_64"),
        fake_hash,
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ast-grep", b"real binary content")
    monkeypatch.setattr(urllib.request, "urlopen", _mock_download_success(buf.getvalue()))

    result = ag.ensure_installed()
    assert result.success is False
    assert "SHA-256 mismatch" in result.error
    # Binary should NOT be installed
    assert not ag.get_binary_path().is_file()


def test_ensure_installed_extraction_failure(fake_cache_root, supported_platform, monkeypatch):
    """If the zip is corrupt, install fails gracefully."""
    monkeypatch.setattr(sys, "platform", "linux")
    # Pass invalid zip bytes
    monkeypatch.setattr(urllib.request, "urlopen", _mock_download_success(b"not a zip file"))

    result = ag.ensure_installed()
    assert result.success is False
    assert "extraction failed" in result.error


def test_ensure_installed_zip_cleaned_up_after_success(fake_cache_root, supported_platform, monkeypatch):
    """The downloaded zip should be removed after successful extraction."""
    monkeypatch.setattr(sys, "platform", "linux")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ast-grep", b"binary")
    monkeypatch.setattr(urllib.request, "urlopen", _mock_download_success(buf.getvalue()))

    ag.ensure_installed()
    # No .zip files should remain in the version dir
    version_dir = ag.get_version_dir()
    zips = list(version_dir.glob("*.zip"))
    assert zips == []


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def test_run_raises_when_not_installed_and_no_auto_install(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ag.AstgrepUnavailable, match="not installed"):
        ag.run(["--version"], auto_install=False)


def test_run_auto_installs_on_first_call(fake_cache_root, supported_platform, monkeypatch):
    """run() with auto_install=True should trigger ensure_installed()."""
    monkeypatch.setattr(sys, "platform", "linux")

    # Pre-populate cache so run() doesn't actually download
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"#!/bin/sh\necho 'ast-grep 0.44.0'\n")
    ag._write_sha256_sidecar(binary)
    binary.chmod(0o755)

    # Mock subprocess.run to avoid actually executing the binary
    def _fake_run(cmd, **kw):
        return subprocess.CompletedProcess(
            cmd, returncode=0, stdout="ast-grep 0.44.0\n", stderr=""
        )
    monkeypatch.setattr(subprocess, "run", _fake_run)

    cp = ag.run(["--version"], auto_install=True)
    assert cp.returncode == 0
    assert "0.44.0" in cp.stdout


def test_run_passes_args_through(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"fake")
    ag._write_sha256_sidecar(binary)

    captured_cmd = []
    def _fake_run(cmd, **kw):
        captured_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    ag.run(["scan", "foo.py", "--rule", "bar.yaml"])
    assert captured_cmd[0][1:] == ["scan", "foo.py", "--rule", "bar.yaml"]


def test_run_timeout(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"fake")
    ag._write_sha256_sidecar(binary)

    def _fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 30))
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(subprocess.TimeoutExpired):
        ag.run(["scan"], timeout=5)


def test_get_version_returns_none_when_unavailable(fake_cache_root, supported_platform):
    assert ag.get_version() is None


def test_get_version_returns_string_when_available(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    binary = version_dir / "ast-grep"
    binary.write_bytes(b"fake")
    ag._write_sha256_sidecar(binary)

    def _fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="ast-grep 0.44.0\n", stderr="")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    v = ag.get_version()
    assert v is not None
    assert "0.44.0" in v


# ---------------------------------------------------------------------------
# clear_cache()
# ---------------------------------------------------------------------------


def test_clear_cache_removes_everything(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # Populate
    version_dir = ag.get_version_dir()
    version_dir.mkdir(parents=True)
    (version_dir / "ast-grep").write_bytes(b"binary")
    (version_dir / ".sha256").write_text("hash")
    ag._update_metadata(ag.ASTGREP_VERSION, "linux-x86_64", version_dir / "ast-grep", "hash")

    n = ag.clear_cache()
    assert n >= 2  # at least the binary + sidecar + metadata
    assert not ag.get_cache_root().is_dir()


def test_clear_cache_specific_version(fake_cache_root, supported_platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    # Populate two versions
    for v in ["0.43.0", "0.44.0"]:
        vd = ag.get_version_dir(v)
        vd.mkdir(parents=True)
        (vd / "ast-grep").write_bytes(b"binary")
        (vd / ".sha256").write_text("hash")

    n = ag.clear_cache(version="0.43.0")
    assert n >= 2
    assert not ag.get_version_dir("0.43.0").is_dir()
    assert ag.get_version_dir("0.44.0").is_dir()


def test_clear_cache_empty_returns_zero(fake_cache_root):
    assert ag.clear_cache() == 0


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_status_when_unavailable(fake_cache_root, supported_platform, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    rc = ag._main(["astgrep_runner", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "version" in out
    assert "available: False" in out


def test_cli_no_args_prints_summary(fake_cache_root, supported_platform, capsys):
    rc = ag._main(["astgrep_runner"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ast-grep runner" in out
    assert "cache root" in out
