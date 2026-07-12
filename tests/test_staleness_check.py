"""Tests for _check_staleness() — always-warm registry (issue #237).

Registry staleness vs git HEAD was previously only surfaced passively via
`history --check git-status`'s "re-scan recommendation" field — no other
command read it, so every analysis command could silently answer from a
stale graph. `_check_staleness()` is called for every command except
`scan` itself: small diffs (<= threshold files) trigger a transparent
incremental re-scan; larger diffs just attach a hint instead of forcing
a possibly-slow rescan on every call.
"""

import argparse
import os
import sys
from unittest import mock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from codelens import _check_staleness, _AUTO_RESCAN_FILE_THRESHOLD  # noqa: E402


def _args(command="context", db_path=None):
    return argparse.Namespace(command=command, db_path=db_path)


class TestCheckStaleness:
    def test_scan_command_never_checked(self):
        """scan itself must never trigger staleness checking — it's the
        command that WOULD update the staleness, checking before running
        it would be circular."""
        with mock.patch("codelens._registry_exists", return_value=True):
            result = _check_staleness(".", _args(command="scan"))
        assert result is None

    def test_no_registry_returns_none(self):
        with mock.patch("codelens._registry_exists", return_value=False):
            result = _check_staleness(".", _args())
        assert result is None

    def test_not_stale_returns_none(self):
        with mock.patch("codelens._registry_exists", return_value=True), \
             mock.patch("git_aware.rescan_recommended", return_value=False):
            result = _check_staleness(".", _args())
        assert result is None

    def test_small_diff_auto_rescans(self):
        """A diff at or below the threshold triggers a transparent
        incremental rescan and reports auto_rescanned=True."""
        changed = [f"file{i}.py" for i in range(_AUTO_RESCAN_FILE_THRESHOLD)]
        with mock.patch("codelens._registry_exists", return_value=True), \
             mock.patch("git_aware.rescan_recommended", return_value=True), \
             mock.patch("git_aware.get_last_indexed_sha", return_value="abc123"), \
             mock.patch("git_aware.get_changed_files", return_value=changed), \
             mock.patch("commands.scan.cmd_scan") as mock_scan:
            result = _check_staleness(".", _args())

        mock_scan.assert_called_once_with(".", incremental=True)
        assert result["was_stale"] is True
        assert result["auto_rescanned"] is True
        assert result["changed_files_count"] == _AUTO_RESCAN_FILE_THRESHOLD
        assert "hint" not in result

    def test_large_diff_hints_without_rescanning(self):
        """A diff above the threshold must NOT trigger an automatic
        rescan (could be slow/expensive) — just a hint."""
        changed = [f"file{i}.py" for i in range(_AUTO_RESCAN_FILE_THRESHOLD + 1)]
        with mock.patch("codelens._registry_exists", return_value=True), \
             mock.patch("git_aware.rescan_recommended", return_value=True), \
             mock.patch("git_aware.get_last_indexed_sha", return_value="abc123"), \
             mock.patch("git_aware.get_changed_files", return_value=changed), \
             mock.patch("commands.scan.cmd_scan") as mock_scan:
            result = _check_staleness(".", _args())

        mock_scan.assert_not_called()
        assert result["was_stale"] is True
        assert result["auto_rescanned"] is False
        assert result["changed_files_count"] == _AUTO_RESCAN_FILE_THRESHOLD + 1
        assert "hint" in result

    def test_branch_switch_no_last_sha_treated_as_large_diff(self):
        """detect_branch_switch (via rescan_recommended) can fire with no
        resolvable last_sha — must not crash trying to diff against None,
        and must not silently auto-rescan an unknown-size change."""
        with mock.patch("codelens._registry_exists", return_value=True), \
             mock.patch("git_aware.rescan_recommended", return_value=True), \
             mock.patch("git_aware.get_last_indexed_sha", return_value=None), \
             mock.patch("commands.scan.cmd_scan") as mock_scan:
            result = _check_staleness(".", _args())

        mock_scan.assert_not_called()
        assert result["changed_files_count"] == 0
        assert result["auto_rescanned"] is False

    def test_exception_in_git_aware_never_propagates(self):
        """Not a git repo / git binary missing must degrade to None, not
        crash the command that was actually requested."""
        with mock.patch("codelens._registry_exists", return_value=True), \
             mock.patch("git_aware.rescan_recommended", side_effect=RuntimeError("no git")):
            result = _check_staleness(".", _args())
        assert result is None
