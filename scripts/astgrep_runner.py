"""
ast-grep Runner — optional accelerator for rule pattern matching (issue #68).

Phase 1: binary auto-provisioning with SHA-256 verification and graceful
fallback. Downloads the ast-grep binary from GitHub releases per platform,
verifies its SHA-256, caches it at ``~/.codelens/ast-grep/<version>/<platform>/``,
and exposes a thin wrapper to invoke it.

If ast-grep is unavailable (download failed, SHA mismatch, platform
unsupported, or the user has no network), every function degrades
gracefully — :func:`is_available` returns ``False``, :func:`run` raises
``AstgrepUnavailable``, and callers should fall back to the native
Semgrep-YAML matcher from :mod:`rule_matcher`.

Phase 2 (not in this file) will add the rule-format bridge that routes
certain rule patterns to ast-grep for ~3x speedup.

Storage layout::

    ~/.codelens/ast-grep/
    |-- 0.44.0/
    |   |-- linux-x86_64/
    |   |   |-- ast-grep              # the binary (chmod +x)
    |   |   `-- .sha256               # SHA-256 of the binary, written at install time
    |   |-- darwin-x86_64/
    |   |-- darwin-arm64/
    |   `-- win32-x86_64/
    |       |-- ast-grep.exe
    |       `-- .sha256
    `-- astgrep.json                  # metadata: version, install timestamps

File header — CodeLens ast-grep accelerator (Phase 1).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The ast-grep version we pin and provision. Bump this to upgrade; the
#: SHA-256 cache will be invalidated automatically because the cache path
#: includes the version.
ASTGREP_VERSION = "0.44.0"

#: GitHub release download URL template.
ASTGREP_RELEASE_URL = (
    "https://github.com/ast-grep/ast-grep/releases/download/"
    "{version}/{asset}"
)

#: Map (os, machine) → release asset filename. Covers the 4 platforms
#: listed in issue #68 Phase 1. Platforms outside this map fall back to
#: the native matcher (graceful degradation).
PLATFORM_ASSET_MAP: dict[Tuple[str, str], str] = {
    ("linux", "x86_64"): "app-x86_64-unknown-linux-gnu.zip",
    ("linux", "aarch64"): "app-aarch64-unknown-linux-gnu.zip",
    ("darwin", "x86_64"): "app-x86_64-apple-darwin.zip",
    ("darwin", "arm64"): "app-aarch64-apple-darwin.zip",
    ("windows", "x86_64"): "app-x86_64-pc-windows-msvc.zip",
    ("windows", "amd64"): "app-x86_64-pc-windows-msvc.zip",  # alias
}

#: Map (os, machine) → human-readable platform string used in the cache path.
PLATFORM_LABEL_MAP: dict[Tuple[str, str], str] = {
    ("linux", "x86_64"): "linux-x86_64",
    ("linux", "aarch64"): "linux-aarch64",
    ("darwin", "x86_64"): "darwin-x86_64",
    ("darwin", "arm64"): "darwin-arm64",
    ("windows", "x86_64"): "win32-x86_64",
    ("windows", "amd64"): "win32-x86_64",
}

#: Known-good SHA-256 hashes per (version, platform_label). Populated by
#: the maintainer after verifying an official release. If a (version,
#: platform) entry is missing, the runner trusts HTTPS download (TLS
#: already provides integrity) and records the computed hash in
#: ``.sha256`` for future tampering detection. This is a pragmatic
#: compromise — full supply-chain verification requires pinning hashes
#: here, which is a maintenance task per release.
EXPECTED_SHA256: dict[Tuple[str, str], str] = {
    # Entries below are intentionally empty — see note above. To pin a
    # release, compute the SHA-256 of each downloaded zip and add it here:
    #   ("0.44.0", "linux-x86_64"): "abc123...",
    # Then re-run ``codelens test test_astgrep_runner`` to confirm.
}

#: Binary name inside the cache dir (with .exe on Windows).
def _binary_name() -> str:
    return "ast-grep.exe" if sys.platform == "win32" else "ast-grep"

#: Names the binary might have inside the zip — ast-grep ships the binary
#: under different names depending on the build target. We try each in order.
_CANDIDATE_BINARY_NAMES = ("ast-grep", "sg", "ast-grep.exe", "sg.exe")

#: Download timeout in seconds (per the issue spec — 60s default).
DOWNLOAD_TIMEOUT = 60

#: Run timeout in seconds for ast-grep invocations.
RUN_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AstgrepUnavailable(RuntimeError):
    """Raised when ast-grep is not installed and cannot be provisioned."""


class AstgrepVerificationError(RuntimeError):
    """Raised when a downloaded or cached binary fails SHA-256 verification."""


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------


def detect_platform() -> Tuple[str, str]:
    """Detect the current (os, machine) tuple.

    Returns one of the keys in :data:`PLATFORM_ASSET_MAP`, or raises
    ``AstgrepUnavailable`` if the platform is unsupported.
    """
    os_name = {
        "Linux": "linux",
        "Darwin": "darwin",
        "Windows": "windows",
    }.get(platform.system(), "")
    machine = platform.machine().lower()
    # Normalize common variants
    if machine in ("x86_64", "amd64", "x64"):
        machine = "x86_64" if os_name != "windows" else "amd64"
    elif machine in ("arm64", "aarch64"):
        # macOS reports "arm64", Linux reports "aarch64" — normalize per-OS
        if os_name == "darwin":
            machine = "arm64"
        else:
            machine = "aarch64"
    if not os_name or (os_name, machine) not in PLATFORM_ASSET_MAP:
        raise AstgrepUnavailable(
            f"unsupported platform: os={platform.system()!r}, machine={platform.machine()!r}. "
            f"Supported: {sorted(set(PLATFORM_ASSET_MAP.keys()))}"
        )
    return (os_name, machine)


def get_platform_label() -> str:
    """Return the human-readable platform label (e.g. ``linux-x86_64``)."""
    os_machine = detect_platform()
    return PLATFORM_LABEL_MAP[os_machine]


# ---------------------------------------------------------------------------
# Cache paths
# ---------------------------------------------------------------------------


def get_cache_root() -> Path:
    """Return the ast-grep cache root: ``~/.codelens/ast-grep/``."""
    return Path.home() / ".codelens" / "ast-grep"


def get_version_dir(version: str = ASTGREP_VERSION) -> Path:
    """Return the cache dir for a specific version + current platform."""
    label = get_platform_label()
    return get_cache_root() / version / label


def get_binary_path(version: str = ASTGREP_VERSION) -> Path:
    """Return the absolute path to the cached ast-grep binary."""
    return get_version_dir(version) / _binary_name()


def get_sha256_path(version: str = ASTGREP_VERSION) -> Path:
    """Return the path to the ``.sha256`` sidecar file."""
    return get_version_dir(version) / ".sha256"


def get_metadata_path() -> Path:
    """Return the path to ``astgrep.json`` (install metadata)."""
    return get_cache_root() / "astgrep.json"


# ---------------------------------------------------------------------------
# SHA-256 helpers
# ---------------------------------------------------------------------------


def compute_sha256(path: Path, chunk_size: int = 65536) -> str:
    """Compute the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(binary_path: Path, expected: Optional[str] = None) -> bool:
    """Verify the SHA-256 of a binary.

    If ``expected`` is provided, the binary's hash must match it exactly.
    If ``expected`` is ``None``, the hash is compared against the stored
    ``.sha256`` sidecar (detects post-install tampering). If no sidecar
    exists, the check is skipped (first install scenario).
    """
    if not binary_path.is_file():
        return False
    actual = compute_sha256(binary_path)
    if expected is not None:
        return actual == expected.lower()
    # Compare against stored sidecar
    sidecar = binary_path.parent / ".sha256"
    if not sidecar.is_file():
        return True  # no sidecar yet — caller should write one
    stored = sidecar.read_text(encoding="utf-8").strip().lower()
    return actual == stored


def _write_sha256_sidecar(binary_path: Path) -> str:
    """Compute + write the ``.sha256`` sidecar. Returns the hash."""
    h = compute_sha256(binary_path)
    sidecar = binary_path.parent / ".sha256"
    sidecar.write_text(h, encoding="utf-8")
    return h


# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def is_available(version: str = ASTGREP_VERSION) -> bool:
    """Return ``True`` if ast-grep is installed and passes SHA-256 verification.

    This is the main gate callers should use before attempting to invoke
    ast-grep. It never raises — on any error, it returns ``False`` so
    callers can fall back to the native matcher.
    """
    try:
        binary = get_binary_path(version)
        if not binary.is_file():
            return False
        # Re-verify the cached binary against the sidecar (detects
        # post-install tampering or corruption).
        return verify_sha256(binary, expected=None)
    except AstgrepUnavailable:
        # Unsupported platform
        return False
    except Exception:
        # Any other error (permissions, IO, etc.) — treat as unavailable
        return False


# ---------------------------------------------------------------------------
# Download + install
# ---------------------------------------------------------------------------


@dataclass
class InstallResult:
    """Outcome of an :func:`ensure_installed` call."""

    success: bool
    version: str
    platform_label: str
    binary_path: Optional[Path] = None
    sha256: Optional[str] = None
    error: Optional[str] = None
    from_cache: bool = False


def ensure_installed(
    version: str = ASTGREP_VERSION,
    timeout: int = DOWNLOAD_TIMEOUT,
    force: bool = False,
) -> InstallResult:
    """Ensure ast-grep is installed and verified. Downloads if needed.

    Args:
        version: ast-grep version to provision.
        timeout: download timeout in seconds.
        force: if ``True``, re-download even if a cached binary exists.

    Returns:
        :class:`InstallResult` with ``success=True`` on success.
    """
    try:
        os_machine = detect_platform()
    except AstgrepUnavailable as exc:
        return InstallResult(
            success=False,
            version=version,
            platform_label="unknown",
            error=str(exc),
        )

    label = PLATFORM_LABEL_MAP[os_machine]
    version_dir = get_version_dir(version)
    binary_path = version_dir / _binary_name()

    # Fast path: cached binary exists and passes verification
    if not force and binary_path.is_file():
        try:
            if verify_sha256(binary_path, expected=None):
                return InstallResult(
                    success=True,
                    version=version,
                    platform_label=label,
                    binary_path=binary_path,
                    sha256=compute_sha256(binary_path),
                    from_cache=True,
                )
        except Exception:
            # Sidecar missing or mismatch — fall through to re-download
            pass

    # Download the zip
    asset = PLATFORM_ASSET_MAP[os_machine]
    url = ASTGREP_RELEASE_URL.format(version=version, asset=asset)
    zip_path = version_dir / asset

    version_dir.mkdir(parents=True, exist_ok=True)

    try:
        _download(url, zip_path, timeout)
    except Exception as exc:
        return InstallResult(
            success=False,
            version=version,
            platform_label=label,
            error=f"download failed: {exc}",
        )

    # Verify the zip's SHA-256 against EXPECTED_SHA256 (if pinned)
    expected_zip_hash = EXPECTED_SHA256.get((version, label))
    if expected_zip_hash is not None:
        actual_zip_hash = compute_sha256(zip_path)
        if actual_zip_hash != expected_zip_hash.lower():
            zip_path.unlink(missing_ok=True)
            return InstallResult(
                success=False,
                version=version,
                platform_label=label,
                error=(
                    f"SHA-256 mismatch for {asset}: expected {expected_zip_hash}, "
                    f"got {actual_zip_hash}"
                ),
            )

    # Extract the binary from the zip
    try:
        extracted = _extract_binary(zip_path, version_dir)
    except Exception as exc:
        zip_path.unlink(missing_ok=True)
        return InstallResult(
            success=False,
            version=version,
            platform_label=label,
            error=f"extraction failed: {exc}",
        )
    finally:
        # Clean up the zip regardless of extraction outcome
        zip_path.unlink(missing_ok=True)

    # Move the extracted binary to its canonical name
    if extracted != binary_path:
        if binary_path.exists():
            binary_path.unlink()
        shutil.move(str(extracted), str(binary_path))

    # chmod +x on Unix
    if sys.platform != "win32":
        st = binary_path.stat()
        binary_path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Write the .sha256 sidecar for future tampering detection
    sha = _write_sha256_sidecar(binary_path)

    # Update metadata
    _update_metadata(version, label, binary_path, sha)

    return InstallResult(
        success=True,
        version=version,
        platform_label=label,
        binary_path=binary_path,
        sha256=sha,
        from_cache=False,
    )


def _download(url: str, dest: Path, timeout: int) -> None:
    """Download ``url`` to ``dest`` with a timeout."""
    req = urllib.request.Request(url, headers={"User-Agent": "codelens-astgrep-runner/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status} fetching {url}")
        with open(dest, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)


def _extract_binary(zip_path: Path, dest_dir: Path) -> Path:
    """Extract the ast-grep binary from the zip. Returns the path to the
    extracted binary (not yet renamed to canonical name).
    """
    with zipfile.ZipFile(zip_path) as zf:
        # Find the binary entry — try candidate names first, then any
        # file that looks like the ast-grep binary.
        names = zf.namelist()
        target_name = None
        for candidate in _CANDIDATE_BINARY_NAMES:
            for n in names:
                # Match basename (zip might have subdirectory structure)
                if os.path.basename(n).lower() == candidate.lower():
                    target_name = n
                    break
            if target_name:
                break
        if target_name is None:
            # Last resort: pick the first executable-looking file
            for n in names:
                base = os.path.basename(n).lower()
                if base.endswith(".exe") or "ast-grep" in base or base == "sg":
                    target_name = n
                    break
        if target_name is None:
            raise RuntimeError(
                f"could not find ast-grep binary in zip; entries: {names[:10]}"
            )
        zf.extract(target_name, dest_dir)
        extracted = dest_dir / target_name
        return extracted


def _update_metadata(
    version: str,
    platform_label: str,
    binary_path: Path,
    sha256: str,
) -> None:
    """Write/update ``astgrep.json`` with install metadata."""
    meta_path = get_metadata_path()
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        existing = {}
    installs = existing.setdefault("installs", {})
    installs[f"{version}/{platform_label}"] = {
        "version": version,
        "platform": platform_label,
        "binary": str(binary_path),
        "sha256": sha256,
        "installed_at": _utc_now_iso(),
    }
    existing["default_version"] = version
    existing["last_updated"] = _utc_now_iso()
    meta_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


def run(
    args: list[str],
    *,
    timeout: int = RUN_TIMEOUT,
    stdin: Optional[str] = None,
    version: str = ASTGREP_VERSION,
    auto_install: bool = True,
) -> subprocess.CompletedProcess:
    """Invoke ast-grep with ``args``. Returns the completed process.

    Raises :class:`AstgrepUnavailable` if ast-grep is not installed and
    cannot be provisioned (or if ``auto_install=False`` and it's missing).
    """
    if not is_available(version):
        if not auto_install:
            raise AstgrepUnavailable(
                f"ast-grep {version} is not installed. Run "
                f"`ensure_installed()` first or pass `auto_install=True`."
            )
        result = ensure_installed(version=version)
        if not result.success:
            raise AstgrepUnavailable(
                f"ast-grep {version} could not be installed: {result.error}"
            )
    binary = get_binary_path(version)
    cmd = [str(binary)] + list(args)
    return subprocess.run(
        cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,  # don't raise on non-zero exit — caller decides
    )


def get_version(version: str = ASTGREP_VERSION) -> Optional[str]:
    """Return the ast-grep version string (e.g. ``"ast-grep 0.44.0"``).

    Returns ``None`` if ast-grep is unavailable.
    """
    try:
        cp = run(["--version"], timeout=10, version=version, auto_install=False)
    except (AstgrepUnavailable, subprocess.TimeoutExpired):
        return None
    if cp.returncode != 0:
        return None
    return cp.stdout.strip()


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def clear_cache(version: Optional[str] = None) -> int:
    """Remove cached ast-grep binaries.

    Args:
        version: if given, only clear that version. If ``None``, clear all.

    Returns:
        Number of files removed.
    """
    root = get_cache_root()
    if not root.is_dir():
        return 0
    count = 0
    if version is not None:
        target = root / version
        if target.is_dir():
            for f in target.rglob("*"):
                if f.is_file():
                    f.unlink()
                    count += 1
            shutil.rmtree(target, ignore_errors=True)
    else:
        for f in root.rglob("*"):
            if f.is_file():
                f.unlink()
                count += 1
        shutil.rmtree(root, ignore_errors=True)
    return count


# ---------------------------------------------------------------------------
# CLI smoke entry
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    """``python -m astgrep_runner`` — print status and exit."""
    if len(argv) < 2:
        print(f"ast-grep runner — version {ASTGREP_VERSION}")
        print(f"cache root: {get_cache_root()}")
        try:
            label = get_platform_label()
            print(f"platform: {label}")
        except AstgrepUnavailable as exc:
            print(f"platform: unsupported ({exc})")
            return 1
        print(f"available: {is_available()}")
        return 0
    cmd = argv[1]
    if cmd == "install":
        r = ensure_installed(force="--force" in argv)
        if r.success:
            print(f"installed: {r.version}/{r.platform_label} at {r.binary_path}")
            print(f"sha256: {r.sha256}")
            print(f"from_cache: {r.from_cache}")
            return 0
        print(f"install failed: {r.error}", file=sys.stderr)
        return 1
    if cmd == "status":
        print(f"version: {ASTGREP_VERSION}")
        try:
            label = get_platform_label()
            print(f"platform: {label}")
        except AstgrepUnavailable as exc:
            print(f"platform: unsupported ({exc})")
            return 1
        print(f"available: {is_available()}")
        if is_available():
            v = get_version()
            print(f"runtime version: {v}")
        meta = get_metadata_path()
        if meta.is_file():
            print(f"metadata: {meta}")
        return 0
    if cmd == "clear":
        n = clear_cache()
        print(f"removed {n} file(s)")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    print("usage: python -m astgrep_runner [install|status|clear]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
