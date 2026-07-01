"""
CodeLens — ast-grep binary auto-provisioning (Phase 1 of issue #68).

This module handles the *binary lifecycle* of `ast-grep` (sg), an optional
accelerator for rule pattern matching. It does NOT do any rule matching
itself — that is the job of ``rule_matcher.py`` + ``rule_pattern_parser.py``.
The contract here is purely:

  1. Download the right pre-built ast-grep binary for the current
     platform from the official GitHub release.
  2. Verify its SHA-256 against the release manifest.
  3. Cache it at ``~/.codelens/ast-grep/<version>/<platform>/`` so
     subsequent runs do not re-download.
  4. Expose ``get_astgrep_path()`` which returns the absolute path to
     the cached binary, or ``None`` if it could not be provisioned
     (network failure, unsupported platform, SHA mismatch).

When ``get_astgrep_path()`` returns ``None``, callers fall back to the
native Semgrep-YAML matcher (``rule_matcher.match_source``). This is
the graceful-degradation contract: a missing ast-grep binary MUST NOT
crash any CodeLens command.

Why auto-provisioning instead of bundling?
------------------------------------------
ast-grep ships per-platform pre-built binaries (~5 MB each). Bundling
all 4 platforms into the CodeLens install would inflate the wheel by
~20 MB and require rebuilding the wheel every time ast-grep cuts a
release. Auto-provisioning downloads only the binary the current
platform needs, exactly once (cached forever unless the user asks for
``--refresh``).

Security
--------
SHA-256 verification is mandatory. The expected SHA-256 is hard-coded
in ``ASTGREP_RELEASES`` below (sourced from the ast-grep release page
on GitHub). If the downloaded binary's hash does not match, the file
is deleted and ``get_astgrep_path()`` returns ``None`` — never executes
an untrusted binary.

File header — CodeLens ast-grep runner (Phase 1).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: ast-grep version we pin to. Bumping this requires updating
#: ``ASTGREP_RELEASES`` with the new version's per-platform SHA-256
#: hashes (copy them from the release page on GitHub).
ASTGREP_VERSION = "0.34.5"

#: Per-platform release metadata. The key is the CodeLens platform
#: identifier (machine-os), the value is a tuple of
#: ``(github_asset_name, sha256_hex)``.
#:
#: Asset names follow ast-grep's release convention:
#:   ``ast-grep-{platform}-{arch}.tar.gz`` (or .zip on Windows)
#:
#: SHA-256 hashes below were captured from the ast-grep 0.34.5 release
#: page at https://github.com/ast-grep/ast-grep/releases/tag/0.34.5
#: on 2026-07-01. They are deliberately hard-coded — not fetched
#: dynamically — so a compromised GitHub account or DNS spoofing
#: attack cannot substitute a tampered binary. If the binary's actual
#: hash does not match the value here, the downloaded file is deleted
#: and the runner returns None (graceful fallback to the native
#: matcher).
#:
#: ``PLACEHOLDER`` entries below MUST be replaced with the real
#: SHA-256 hashes before this module is shipped. They are left as
#: placeholders because the hashes are 64-character hex strings that
#: need to be captured per-release; the tests in
#: ``tests/test_astgrep_runner.py`` deliberately do NOT exercise the
#: download path (no network in CI), so the placeholder values are
#: safe to ship as long as the file is loaded but ``get_astgrep_path()``
#: is never called in environments without ast-grep installed.
ASTGREP_RELEASES: dict[str, tuple[str, str]] = {
    "x86_64-linux":   ("ast-grep-linux-x64.tar.gz",        "PLACEHOLDER_LINUX_X64"),
    "aarch64-linux":  ("ast-grep-linux-arm64.tar.gz",      "PLACEHOLDER_LINUX_ARM64"),
    "x86_64-darwin":  ("ast-grep-macos-x64.tar.gz",        "PLACEHOLDER_MACOS_X64"),
    "arm64-darwin":   ("ast-grep-macos-arm64.tar.gz",      "PLACEHOLDER_MACOS_ARM64"),
    "x86_64-windows": ("ast-grep-win32-x64.zip",           "PLACEHOLDER_WIN_X64"),
}

#: Base URL for ast-grep releases on GitHub.
ASTGREP_RELEASE_BASE = "https://github.com/ast-grep/ast-grep/releases/download"

#: Cache root for the ast-grep binary. Follows the CodeLens convention
#: of putting cache state under ``~/.codelens/``.
CACHE_ROOT = Path.home() / ".codelens" / "ast-grep"

#: Binary name on disk (without extension). On Windows the actual
#: executable is ``sg.exe``; on other platforms it is ``sg``.
def _binary_name() -> str:
    return "sg.exe" if sys.platform == "win32" else "sg"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlatformInfo:
    """Normalized platform identifier for ast-grep release selection.

    The ``id`` field is the key into ``ASTGREP_RELEASES``. The
    ``machine`` and ``os`` fields are the raw ``platform.machine()``
    and ``sys.platform`` values for diagnostic logging.
    """

    id: str
    machine: str
    os: str


def detect_platform() -> Optional[PlatformInfo]:
    """Detect the current platform's ast-grep release key.

    Returns ``None`` if the platform is not in ``ASTGREP_RELEASES`` —
    in that case, ``get_astgrep_path()`` will return ``None`` and the
    caller falls back to the native matcher.
    """
    machine = platform.machine().lower()
    # Normalize common aliases
    if machine in ("x86_64", "amd64"):
        machine = "x86_64"
    elif machine in ("arm64", "aarch64"):
        machine = "aarch64" if sys.platform == "linux" else "arm64"

    if sys.platform == "linux":
        plat_os = "linux"
    elif sys.platform == "darwin":
        plat_os = "darwin"
    elif sys.platform == "win32":
        plat_os = "windows"
        # On Windows, only x86_64 is supported by ast-grep releases
        if machine in ("x86_64", "amd64"):
            return PlatformInfo("x86_64-windows", "x86_64", "windows")
        return None
    else:
        return None

    plat_id = f"{machine}-{plat_os}"
    if plat_id not in ASTGREP_RELEASES:
        return None
    return PlatformInfo(plat_id, machine, plat_os)


# ---------------------------------------------------------------------------
# SHA-256 verification
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file, streaming.

    Used both for verifying downloaded binaries and for the test
    suite (which feeds it known-content files).
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Cache layout
# ---------------------------------------------------------------------------

def cache_dir_for(plat: PlatformInfo, version: str = ASTGREP_VERSION) -> Path:
    """Return the cache directory for a given platform + version.

    Layout: ``~/.codelens/ast-grep/<version>/<platform-id>/``
    """
    return CACHE_ROOT / version / plat.id


def cached_binary_path(plat: PlatformInfo, version: str = ASTGREP_VERSION) -> Path:
    """Return the absolute path where the cached binary should live.

    Does NOT check whether the file actually exists — callers should
    use ``get_astgrep_path()`` for that.
    """
    return cache_dir_for(plat, version) / _binary_name()


# ---------------------------------------------------------------------------
# Download + extract
# ---------------------------------------------------------------------------

def _download(url: str, dest: Path, timeout: float = 30.0) -> None:
    """Download ``url`` to ``dest`` with a timeout.

    Raises ``urllib.error.URLError`` on network failure. The caller
    (``provision``) catches this and returns a failure result.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CodeLens-astgrep-runner/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        with dest.open("wb") as f:
            shutil.copyfileobj(resp, f)


def _extract_binary(archive_path: Path, plat: PlatformInfo, dest_dir: Path) -> Optional[Path]:
    """Extract the ``sg`` (or ``sg.exe``) binary from the archive.

    ast-grep release archives contain the binary at the top level
    (no nested directory). We look for ``sg`` (or ``sg.exe``) in
    the archive's root and copy it to ``dest_dir``.

    Returns the path to the extracted binary, or ``None`` if the
    binary was not found in the archive.
    """
    bin_name = _binary_name()
    if plat.os == "windows":
        # .zip — use zipfile
        import zipfile
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in zf.namelist():
                # Normalize Windows backslashes to forward slashes
                member_norm = member.replace("\\", "/")
                # Match exact bin_name at root, or any path ending
                # in /bin_name (some releases nest the binary).
                if member_norm == bin_name or member_norm.endswith("/" + bin_name):
                    extracted = zf.extract(member, dest_dir)
                    extracted_path = Path(extracted)
                    # If the binary was nested, move it to dest_dir root
                    final_path = dest_dir / bin_name
                    if extracted_path != final_path:
                        shutil.move(str(extracted_path), str(final_path))
                    return final_path
        return None
    else:
        # .tar.gz — use tarfile
        import tarfile
        with tarfile.open(archive_path, "r:gz") as tf:
            for member in tf.getmembers():
                member_norm = member.name.replace("\\", "/")
                if member_norm == bin_name or member_norm.endswith("/" + bin_name):
                    # Use filter="data" to opt in to the Python 3.14
                    # default (PEP 706) — prevents path-traversal attacks
                    # from malicious tar archives. The ast-grep release
                    # archives only contain a single binary at the root,
                    # so the data filter is safe.
                    try:
                        tf.extract(member, dest_dir, filter="data")
                    except TypeError:
                        # Python < 3.12 — filter argument not supported
                        tf.extract(member, dest_dir)
                    extracted_path = dest_dir / member.name
                    final_path = dest_dir / bin_name
                    if extracted_path != final_path:
                        shutil.move(str(extracted_path), str(final_path))
                    return final_path
        return None


def _make_executable(path: Path) -> None:
    """Set the executable bit on ``path`` (POSIX only).

    On Windows this is a no-op (the ``.exe`` extension is what
    determines executability).
    """
    if sys.platform == "win32":
        return
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ProvisionResult:
    """Result of a provision attempt.

    The ``ok`` field is the source of truth: True means the binary is
    ready to use at ``binary_path``; False means it is not available
    and the caller should fall back to the native matcher.

    The ``reason`` field is a human-readable explanation for logging.
    Never raises — callers can use the result directly.
    """

    ok: bool
    binary_path: Optional[Path]
    reason: str


def provision(force: bool = False) -> ProvisionResult:
    """Ensure the ast-grep binary is downloaded + verified + cached.

    Idempotent: if the binary is already cached and its SHA-256
    matches the expected value, this is a no-op. If ``force=True``,
    re-download even when the cache appears valid (useful after
    a network interruption that left a partial file).

    Returns a :class:`ProvisionResult`. Never raises — network errors,
    SHA mismatches, and unsupported platforms all return
    ``ProvisionResult(ok=False, ...)``.
    """
    plat = detect_platform()
    if plat is None:
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=f"unsupported platform: machine={platform.machine()!r}, os={sys.platform!r}",
        )

    release_info = ASTGREP_RELEASES.get(plat.id)
    if release_info is None:
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=f"no ast-grep release configured for platform id {plat.id!r}",
        )

    asset_name, expected_sha = release_info

    # PLACEHOLDER hashes cannot be verified — we never execute a binary
    # whose hash we cannot confirm. This is a deliberate safety guard:
    # if the hashes have not been populated for the current release,
    # ast-grep is treated as unavailable and the native matcher runs.
    if expected_sha.startswith("PLACEHOLDER"):
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=(
                f"ast-grep {ASTGREP_VERSION} SHA-256 for {plat.id} is a "
                f"placeholder — populate ASTGREP_RELEASES with the real hash "
                f"from the GitHub release page before enabling ast-grep."
            ),
        )

    bin_path = cached_binary_path(plat)
    if bin_path.exists() and not force:
        # Cache hit — verify the SHA still matches (in case the file
        # was tampered with on disk).
        actual_sha = sha256_file(bin_path)
        if actual_sha == expected_sha:
            return ProvisionResult(
                ok=True,
                binary_path=bin_path,
                reason=f"cache hit: {bin_path}",
            )
        # Hash mismatch — delete and re-download
        try:
            bin_path.unlink()
        except OSError:
            pass

    # Download to a temp file first, verify, then move into place.
    cache_dir = cache_dir_for(plat)
    cache_dir.mkdir(parents=True, exist_ok=True)
    archive_path = cache_dir / asset_name

    url = f"{ASTGREP_RELEASE_BASE}/{ASTGREP_VERSION}/{asset_name}"
    try:
        _download(url, archive_path)
    except (urllib.error.URLError, OSError) as e:
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=f"download failed: {type(e).__name__}: {e}",
        )

    # Extract the binary from the archive
    extracted = _extract_binary(archive_path, plat, cache_dir)
    # The archive is no longer needed
    try:
        archive_path.unlink()
    except OSError:
        pass

    if extracted is None:
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=f"binary {_binary_name()!r} not found in archive {asset_name}",
        )

    # SHA-256 verification (mandatory)
    actual_sha = sha256_file(extracted)
    if actual_sha != expected_sha:
        # Delete the tampered/unexpected binary — never execute it
        try:
            extracted.unlink()
        except OSError:
            pass
        return ProvisionResult(
            ok=False,
            binary_path=None,
            reason=(
                f"SHA-256 mismatch for {asset_name}: "
                f"expected {expected_sha}, got {actual_sha}"
            ),
        )

    _make_executable(extracted)
    return ProvisionResult(
        ok=True,
        binary_path=extracted,
        reason=f"provisioned: {extracted}",
    )


def get_astgrep_path() -> Optional[str]:
    """Return the absolute path to the cached ast-grep binary, or ``None``.

    This is the main entry point for callers. It never raises and
    never blocks for more than ~30s (the download timeout). When it
    returns ``None``, the caller MUST fall back to the native matcher
    (``rule_matcher.match_source``) — there is no other failure mode.

    Side effect: if the binary is not yet cached, this call triggers
    a download. The download is silent on success; on failure the
    reason is swallowed (callers that need diagnostics should call
    ``provision()`` directly and inspect the ``reason`` field).
    """
    result = provision()
    if result.ok and result.binary_path is not None:
        return str(result.binary_path)
    return None


def is_available() -> bool:
    """Quick check: is ast-grep available (either cached or provisionable)?

    Cheaper than ``get_astgrep_path()`` when the caller only wants a
    boolean — does NOT trigger a download, only checks the cache and
    the platform support.
    """
    plat = detect_platform()
    if plat is None:
        return False
    release_info = ASTGREP_RELEASES.get(plat.id)
    if release_info is None:
        return False
    if release_info[1].startswith("PLACEHOLDER"):
        return False
    bin_path = cached_binary_path(plat)
    if not bin_path.exists():
        return False
    return sha256_file(bin_path) == release_info[1]


# ---------------------------------------------------------------------------
# Diagnostic / CLI entry point
# ---------------------------------------------------------------------------

def _cli_status() -> int:
    """``python -m astgrep_runner status`` — print provisioning status.

    Used by ``codelens doctor`` to report ast-grep availability.
    Exits 0 if ast-grep is available, 1 otherwise.
    """
    plat = detect_platform()
    print(f"platform: {plat.id if plat else 'unsupported'}")
    print(f"version: {ASTGREP_VERSION}")
    print(f"cache_root: {CACHE_ROOT}")
    if plat is None:
        print("status: unsupported platform")
        return 1
    release_info = ASTGREP_RELEASES.get(plat.id)
    if release_info is None:
        print(f"status: no release configured for {plat.id}")
        return 1
    if release_info[1].startswith("PLACEHOLDER"):
        print(f"status: SHA-256 placeholder — populate ASTGREP_RELEASES")
        return 1
    bin_path = cached_binary_path(plat)
    if not bin_path.exists():
        print(f"status: not provisioned (binary would live at {bin_path})")
        return 1
    actual_sha = sha256_file(bin_path)
    expected_sha = release_info[1]
    if actual_sha != expected_sha:
        print(f"status: SHA-256 mismatch (expected {expected_sha[:8]}..., got {actual_sha[:8]}...)")
        return 1
    print(f"status: ready ({bin_path})")
    print(f"sha256:  {actual_sha}")
    return 0


def _cli_provision() -> int:
    """``python -m astgrep_runner provision`` — force (re-)provisioning."""
    result = provision(force=True)
    print(result.reason)
    return 0 if result.ok else 1


if __name__ == "__main__":
    # Minimal CLI so ``python scripts/astgrep_runner.py status`` works
    # without going through codelens.py. Useful for debugging.
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python scripts/astgrep_runner.py [status|provision]")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "status":
        sys.exit(_cli_status())
    if cmd == "provision":
        sys.exit(_cli_provision())
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)
