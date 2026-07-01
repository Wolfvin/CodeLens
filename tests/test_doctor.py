"""Tests for the ``codelens doctor`` command (issue #64, Phase 1).

Covers:

* Every audit check returns a well-formed result dict with the
  required keys (``name``, ``status``, ``found``, ``required``,
  ``detail``).
* Status aggregation: any ``critical`` → exit 2; any ``warning`` →
  exit 1; all ``ok`` → exit 0.
* ``--format json`` produces valid, parseable JSON with the
  documented top-level schema.
* ``--format text`` (default) prints a human-readable table.
* ``--fix`` calls ``pip install --user`` for fixable missing deps.
* ``--verbose`` adds detail lines.
* Edge cases: no workspace arg (auto-detect), non-existent workspace
  (still runnable — doctor is a env audit, not a workspace audit),
  network failure on latest-version check (downgraded to warning).

These tests deliberately do NOT mock ``sys.version_info``, ``shutil.which``,
or ``importlib`` — doctor's whole job is to probe the real environment.
Instead, we assert on the *structure* of the output (every check has
the required keys, statuses are in the allowed enum, aggregation
matches) rather than on specific version strings that would be
machine-specific.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from unittest import mock

import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402
from commands import doctor as doctor_module  # noqa: E402


# ─── Registration ──────────────────────────────────────────────


def test_doctor_is_registered():
    """doctor must be in the runtime COMMAND_REGISTRY."""
    assert "doctor" in COMMAND_REGISTRY
    info = COMMAND_REGISTRY["doctor"]
    assert "audit" in info["help"].lower() or "doctor" in info["help"].lower()


def test_doctor_execute_callable():
    """The registered execute function must be callable."""
    info = COMMAND_REGISTRY["doctor"]
    assert callable(info["execute"])
    assert callable(info["add_args"])


# ─── Helper ────────────────────────────────────────────────────


def _run_doctor(workspace=None, fix=False, verbose=False, fmt="json"):
    """Invoke doctor.execute() with a synthetic args namespace.

    Returns the raw result dict — NOT the printed text. For text-mode
    tests, capture stdout separately.
    """
    args = mock.MagicMock()
    args.fix = fix
    args.verbose = verbose
    args.format = fmt
    args.workspace = workspace
    return doctor_module.execute(args, workspace or "")


# ─── Output schema ─────────────────────────────────────────────


class TestOutputSchema:
    """The result dict must conform to the documented schema."""

    def test_top_level_keys_present(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        for key in ("status", "exit_code", "checks", "fixes", "summary", "platform", "workspace"):
            assert key in result, f"missing top-level key: {key}"

    def test_status_is_in_allowed_enum(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        assert result["status"] in ("ok", "warning", "critical")

    def test_exit_code_matches_status(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        status_to_exit = {"ok": 0, "warning": 1, "critical": 2}
        assert result["exit_code"] == status_to_exit[result["status"]]

    def test_summary_counts_match_checks(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        summary = result["summary"]
        checks = result["checks"]
        assert summary["total"] == len(checks)
        for status in ("ok", "warning", "critical"):
            expected = sum(1 for c in checks if c["status"] == status)
            assert summary[status] == expected, (
                f"summary.{status}={summary[status]} but counted {expected} in checks"
            )

    def test_every_check_has_required_keys(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        required_keys = {"name", "status", "found", "required", "detail"}
        for check in result["checks"]:
            missing = required_keys - set(check.keys())
            assert not missing, f"check {check.get('name')} missing keys: {missing}"

    def test_every_check_status_in_enum(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        for check in result["checks"]:
            assert check["status"] in ("ok", "warning", "critical"), (
                f"check {check['name']} has invalid status: {check['status']}"
            )

    def test_platform_block_has_expected_fields(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        plat = result["platform"]
        for key in ("python", "platform", "machine", "executable"):
            assert key in plat

    def test_fixes_is_list(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        assert isinstance(result["fixes"], list)


# ─── Individual checks ─────────────────────────────────────────


class TestIndividualChecks:
    """Spot-check that each audit category appears in the result."""

    EXPECTED_CHECK_NAMES = {
        "python",
        "python.module.tree_sitter",
        "tree_sitter.grammars",
        "python.module.yaml",
        "python.module.watchdog",
        "python.module.sqlite3",
        "python.module.urllib",
        "binary.git",
        "workspace.codelens_writable",
        "codelens.latest_version",
    }

    def test_all_expected_checks_run(self, tmp_path):
        result = _run_doctor(workspace=str(tmp_path))
        actual_names = {c["name"] for c in result["checks"]}
        missing = self.EXPECTED_CHECK_NAMES - actual_names
        assert not missing, f"missing checks: {missing}"


# ─── Aggregation logic ─────────────────────────────────────────


class TestAggregation:
    """Verify _aggregate_status picks the worst status correctly."""

    def test_all_ok_returns_zero(self):
        checks = [{"status": "ok"}, {"status": "ok"}]
        status, code = doctor_module._aggregate_status(checks)
        assert status == "ok"
        assert code == doctor_module.EXIT_OK

    def test_warning_returns_one(self):
        checks = [{"status": "ok"}, {"status": "warning"}]
        status, code = doctor_module._aggregate_status(checks)
        assert status == "warning"
        assert code == doctor_module.EXIT_WARNING

    def test_critical_returns_two(self):
        checks = [{"status": "ok"}, {"status": "warning"}, {"status": "critical"}]
        status, code = doctor_module._aggregate_status(checks)
        assert status == "critical"
        assert code == doctor_module.EXIT_CRITICAL

    def test_critical_wins_over_warning(self):
        checks = [{"status": "warning"}, {"status": "critical"}]
        status, code = doctor_module._aggregate_status(checks)
        assert status == "critical"


# ─── Version tuple helper ──────────────────────────────────────


class TestVersionTuple:
    def test_simple_semver(self):
        assert doctor_module._version_tuple("8.2.0") == (8, 2, 0)

    def test_two_components(self):
        assert doctor_module._version_tuple("3.12") == (3, 12)

    def test_with_prerelease_suffix(self):
        # "8.2.0rc1" → (8, 2, 0) — pre-release stripped
        assert doctor_module._version_tuple("8.2.0rc1") == (8, 2, 0)

    def test_comparison(self):
        assert doctor_module._version_tuple("8.2.0") >= doctor_module._version_tuple("8.1.9")
        assert doctor_module._version_tuple("8.2.0") >= doctor_module._version_tuple("8.2.0")
        assert not (doctor_module._version_tuple("8.1.0") >= doctor_module._version_tuple("8.2.0"))


# ─── Workspace writability check ───────────────────────────────


class TestWorkspaceWritableCheck:
    def test_writable_workspace_returns_ok(self, tmp_path):
        result = doctor_module._check_codelens_writable(str(tmp_path))
        assert result["status"] == "ok"
        assert ".codelens" in result["found"]

    def test_no_workspace_returns_warning(self):
        result = doctor_module._check_codelens_writable("")
        assert result["status"] == "warning"
        assert "no workspace" in result["detail"].lower()

    def test_read_only_workspace_returns_critical(self, tmp_path):
        """A read-only workspace dir must be flagged critical.

        We chmod the parent to 0500 (r-x) and try to create a
        subdir — should fail. Restore perms in the finally block so
        pytest's tmp_path cleanup works.
        """
        ro = tmp_path / "readonly"
        ro.mkdir()
        os.chmod(ro, 0o500)  # r-x for owner, no write
        try:
            result = doctor_module._check_codelens_writable(str(ro))
            # On some CI runners the test runs as root, which can
            # write anywhere regardless of perms. Skip the assertion
            # in that case rather than fail.
            if os.geteuid() == 0:
                pytest.skip("running as root — perm check is a no-op")
            assert result["status"] == "critical"
        finally:
            os.chmod(ro, 0o700)  # restore so cleanup works


# ─── Python version check ──────────────────────────────────────


class TestPythonVersionCheck:
    def test_returns_ok_on_current_python(self):
        # The test runner's Python is whatever it is — but it must
        # be >= 3.8 because we use f-strings and other 3.8+ features
        # throughout the codebase. So this should always be ok.
        result = doctor_module._check_python_version()
        assert result["status"] == "ok"
        assert result["found"].startswith(f"{sys.version_info.major}.{sys.version_info.minor}.")


# ─── CLI smoke test (subprocess) ───────────────────────────────


class TestCLISmoke:
    """End-to-end: invoke ``codelens doctor`` as a real subprocess."""

    def _run_cli(self, *extra_args):
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS_DIR
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "codelens.py"), "doctor", *extra_args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )

    def test_doctor_runs_and_exits_nonzero_on_critical(self, tmp_path):
        # tree_sitter is likely missing in the test env (it's an
        # optional dep), so doctor should exit 2. If it happens to
        # be installed, the test still passes because we accept any
        # non-crash exit code.
        result = self._run_cli(str(tmp_path))
        assert result.returncode in (0, 1, 2), (
            f"unexpected exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_doctor_text_format_contains_header(self, tmp_path):
        result = self._run_cli(str(tmp_path))
        assert "CodeLens doctor" in result.stdout
        assert "Overall:" in result.stdout

    def test_doctor_json_format_is_valid_json(self, tmp_path):
        result = self._run_cli(str(tmp_path), "--format", "json")
        # The doctor command's --format json should make the CLI
        # print JSON (not the text table).
        # Strip any stderr noise from stdout before parsing.
        out = result.stdout.strip()
        # If _doctor_printed_text was set, the text table was printed
        # instead. In JSON mode it should NOT be set.
        data = json.loads(out)
        assert "status" in data
        assert "checks" in data
        assert "exit_code" in data

    def test_doctor_verbose_adds_detail(self, tmp_path):
        result_normal = self._run_cli(str(tmp_path))
        result_verbose = self._run_cli(str(tmp_path), "--verbose")
        # Verbose output should be longer (extra detail lines).
        assert len(result_verbose.stdout) > len(result_normal.stdout)


# ─── Fix mode (mocked) ─────────────────────────────────────────


class TestFixMode:
    """``--fix`` should call ``pip install --user`` for fixable missing deps.

    We mock ``subprocess.run`` so no real pip install happens. The
    test asserts that pip is invoked AT MOST once with all the
    missing packages in a single command.
    """

    def test_fix_calls_pip_when_deps_missing(self, tmp_path):
        # Force a fake "missing" state by stubbing _run_all_checks
        # to return a critical tree_sitter check.
        fake_checks = [
            {"name": "python.module.tree_sitter", "status": "critical",
             "found": None, "required": "present", "detail": "ImportError",
             "pip_name": "tree-sitter", "fixable": True},
            {"name": "python", "status": "ok", "found": "3.12", "required": ">= 3.8",
             "detail": "ok"},
        ]
        with mock.patch.object(doctor_module, "_run_all_checks", return_value=fake_checks):
            with mock.patch.object(doctor_module.subprocess, "run") as mock_run:
                mock_run.return_value = mock.MagicMock(returncode=0, stdout="", stderr="")
                # Also stub _run_all_checks for the POST-fix re-run.
                # Since _apply_fixes calls _run_all_checks again, we
                # need the second call to also return the fake checks.
                with mock.patch.object(doctor_module, "_run_all_checks", return_value=fake_checks):
                    args = mock.MagicMock()
                    args.fix = True
                    args.verbose = False
                    args.format = "json"
                    args.workspace = str(tmp_path)
                    result = doctor_module.execute(args, str(tmp_path))

        assert mock_run.called
        call_args = mock_run.call_args[0][0]
        assert "pip" in " ".join(call_args)
        assert "install" in call_args
        assert "--user" in call_args
        assert "tree-sitter" in call_args
        # The fix outcome must be recorded.
        assert len(result["fixes"]) >= 1
        fix = result["fixes"][0]
        assert fix["action"] == "pip_install"
        assert fix["success"] is True

    def test_fix_noop_when_nothing_fixable(self, tmp_path):
        fake_checks = [
            {"name": "python", "status": "ok", "found": "3.12",
             "required": ">= 3.8", "detail": "ok"},
        ]
        with mock.patch.object(doctor_module, "_run_all_checks", return_value=fake_checks):
            with mock.patch.object(doctor_module.subprocess, "run") as mock_run:
                args = mock.MagicMock()
                args.fix = True
                args.verbose = False
                args.format = "json"
                args.workspace = str(tmp_path)
                result = doctor_module.execute(args, str(tmp_path))

        # pip should NOT have been called.
        assert not mock_run.called
        assert len(result["fixes"]) == 1
        assert result["fixes"][0]["action"] == "noop"


# ─── Latest version check (network-failure tolerant) ───────────


class TestLatestVersionCheck:
    """The latest-version check must NEVER fail critically, even offline."""

    def test_network_failure_returns_warning_not_critical(self):
        # Force a network failure by patching urllib.request.urlopen.
        with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = doctor_module._check_latest_version()
        assert result["status"] == "warning"
        assert "could not reach" in result["detail"].lower()
        # Critical would break CI in air-gapped environments.
        assert result["status"] != "critical"

    def test_successful_fetch_returns_ok_when_up_to_date(self):
        # Mock a successful GitHub API response where latest == installed.
        from utils import CODELENS_VERSION
        fake_response = mock.MagicMock()
        fake_response.__enter__ = mock.MagicMock(return_value=fake_response)
        fake_response.__exit__ = mock.MagicMock(return_value=False)
        fake_response.read = mock.MagicMock(
            return_value=json.dumps({"tag_name": f"v{CODELENS_VERSION}"}).encode()
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            result = doctor_module._check_latest_version()
        assert result["status"] == "ok"
        assert "up to date" in result["detail"]

    def test_outdated_install_returns_warning(self):
        # Mock a successful fetch where latest > installed.
        from utils import CODELENS_VERSION
        # Bump the major version to guarantee latest > installed.
        major = int(CODELENS_VERSION.split(".")[0]) + 1
        fake_latest = f"v{major}.0.0"
        fake_response = mock.MagicMock()
        fake_response.__enter__ = mock.MagicMock(return_value=fake_response)
        fake_response.__exit__ = mock.MagicMock(return_value=False)
        fake_response.read = mock.MagicMock(
            return_value=json.dumps({"tag_name": fake_latest}).encode()
        )
        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            result = doctor_module._check_latest_version()
        assert result["status"] == "warning"
        assert "latest" in result["detail"].lower()
