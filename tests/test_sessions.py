"""Tests for the ``codelens sessions`` command (issue #64, Phase 2).

Covers:

* Session log reading from both JSON sidecar and Markdown fallback.
* ``--entries N`` filtering (last N sessions, most-recent-first).
* ``--json`` machine-readable output.
* ``--raw`` verbatim Markdown output.
* ``--config-dir`` custom location (for test isolation).
* Rotation: when the JSON sidecar exceeds 1 MB, trim to last 50.
* ``setup.sh`` integration: running setup.sh appends a session entry
  to both ``session.md`` and ``session.json``.

The tests use ``tmp_path`` + ``--config-dir`` for isolation — they
do NOT touch the user's real ``~/.codelens/`` directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List

import pytest

SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from commands import COMMAND_REGISTRY  # noqa: E402
from commands import sessions as sessions_module  # noqa: E402


# ─── Registration ──────────────────────────────────────────────


def test_sessions_is_registered():
    """sessions must be in the runtime COMMAND_REGISTRY."""
    assert "sessions" in COMMAND_REGISTRY
    info = COMMAND_REGISTRY["sessions"]
    assert "session" in info["help"].lower()


# ─── Helpers ───────────────────────────────────────────────────


def _make_session(idx: int, **overrides) -> Dict:
    """Build a synthetic session dict for test fixtures."""
    base = {
        "timestamp": f"2026-06-{28 + idx:02d}T09:14:3{idx}Z",
        "duration_sec": 10 + idx,
        "exit_code": 0,
        "python": "3.12.0",
        "os": "Linux",
        "arch": "x86_64",
        "agents_detected": ["claude-code"] if idx % 2 == 0 else [],
        "deps_installed": ["tree-sitter", "tree-sitter-python"],
        "warnings": None if idx % 3 != 0 else f"warning on session {idx}",
        "errors": None,
        "title": "setup",
    }
    base.update(overrides)
    return base


def _write_sessions(config_dir: str, sessions: List[Dict]) -> None:
    """Write a list of sessions to the JSON sidecar (and MD log)."""
    os.makedirs(config_dir, exist_ok=True)
    json_path = os.path.join(config_dir, sessions_module.SESSION_JSON_FILENAME)
    md_path = os.path.join(config_dir, sessions_module.SESSION_MD_FILENAME)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)
    # Write a minimal MD log too so --raw has something to show.
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# CodeLens install sessions\n\n")
        for s in sessions:
            f.write(f"## {s['timestamp']} — {s.get('title', 'setup')}\n\n")
            for k, v in s.items():
                if k in ("timestamp", "title"):
                    continue
                f.write(f"- **{k}**: {v}\n")
            f.write("\n")


def _run_sessions_cmd(config_dir: str, *extra_args) -> Dict:
    """Invoke sessions.execute() with a synthetic args namespace."""
    args = type("Args", (), {})()
    args.workspace = None
    args.entries = sessions_module.DEFAULT_ENTRIES
    args.raw = False
    args.json_output = False
    args.config_dir = config_dir
    for i, a in enumerate(extra_args):
        if a == "--entries":
            args.entries = int(extra_args[i + 1])
        elif a == "--raw":
            args.raw = True
        elif a == "--json":
            args.json_output = True
        elif a == "--config-dir":
            args.config_dir = extra_args[i + 1]
    return sessions_module.execute(args, "")


# ─── Reading sessions ──────────────────────────────────────────


class TestReadSessions:
    """Verify the JSON sidecar is the preferred read source."""

    def test_empty_config_dir_returns_empty_list(self, tmp_path):
        result = _run_sessions_cmd(str(tmp_path))
        assert result["status"] == "ok"
        assert result["total_sessions"] == 0
        assert result["returned_sessions"] == 0
        assert result["sessions"] == []

    def test_reads_from_json_sidecar(self, tmp_path):
        sessions = [_make_session(0), _make_session(1)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path))
        assert result["total_sessions"] == 2
        assert result["returned_sessions"] == 2

    def test_falls_back_to_md_when_json_missing(self, tmp_path):
        """If the JSON sidecar is missing/empty, parse the Markdown log."""
        md_path = os.path.join(str(tmp_path), sessions_module.SESSION_MD_FILENAME)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# CodeLens install sessions\n\n")
            f.write("## 2026-06-28T09:14:31Z — setup\n\n")
            f.write("- **duration_sec**: 42\n")
            f.write("- **python**: 3.12.0\n\n")
        result = _run_sessions_cmd(str(tmp_path))
        assert result["status"] == "ok"
        # MD parsing is best-effort — should at least find 1 session.
        assert result["total_sessions"] >= 1

    def test_falls_back_to_md_when_json_corrupt(self, tmp_path):
        """A corrupt JSON sidecar should not crash — fall back to MD."""
        json_path = os.path.join(str(tmp_path), sessions_module.SESSION_JSON_FILENAME)
        with open(json_path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        md_path = os.path.join(str(tmp_path), sessions_module.SESSION_MD_FILENAME)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# CodeLens install sessions\n\n")
            f.write("## 2026-06-28T09:14:31Z — setup\n\n")
        result = _run_sessions_cmd(str(tmp_path))
        assert result["status"] == "ok"

    def test_md_only_no_sessions_returns_empty(self, tmp_path):
        """If neither file exists, return empty — don't crash."""
        result = _run_sessions_cmd(str(tmp_path))
        assert result["total_sessions"] == 0


# ─── --entries filtering ───────────────────────────────────────


class TestEntriesFilter:
    """``--entries N`` shows only the last N sessions."""

    def test_entries_limits_to_last_n(self, tmp_path):
        sessions = [_make_session(i) for i in range(10)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path), "--entries", "3")
        # total still 10, but only 3 returned
        assert result["total_sessions"] == 10
        assert result["returned_sessions"] == 3
        # The 3 returned should be the LAST 3 (most recent).
        returned_timestamps = [s["timestamp"] for s in result["sessions"]]
        assert returned_timestamps == [sessions[7]["timestamp"],
                                        sessions[8]["timestamp"],
                                        sessions[9]["timestamp"]]

    def test_entries_zero_returns_all(self, tmp_path):
        """``--entries 0`` means "all sessions"."""
        sessions = [_make_session(i) for i in range(7)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path), "--entries", "0")
        assert result["returned_sessions"] == 7

    def test_entries_larger_than_total_returns_all(self, tmp_path):
        sessions = [_make_session(0), _make_session(1)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path), "--entries", "100")
        assert result["returned_sessions"] == 2

    def test_default_entries_is_5(self, tmp_path):
        """Without --entries, the default is 5."""
        sessions = [_make_session(i) for i in range(10)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path))
        assert result["returned_sessions"] == 5


# ─── --json output ─────────────────────────────────────────────


class TestJsonOutput:
    """``--json`` produces a valid JSON array on stdout."""

    def test_json_output_is_valid_array(self, tmp_path, capsys):
        sessions = [_make_session(0), _make_session(1)]
        _write_sessions(str(tmp_path), sessions)
        _run_sessions_cmd(str(tmp_path), "--json")
        captured = capsys.readouterr()
        # The printed output should be a valid JSON array.
        # Strip any stderr noise from stdout.
        out = captured.out.strip()
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["timestamp"] == sessions[0]["timestamp"]

    def test_json_output_respects_entries(self, tmp_path, capsys):
        sessions = [_make_session(i) for i in range(8)]
        _write_sessions(str(tmp_path), sessions)
        _run_sessions_cmd(str(tmp_path), "--json", "--entries", "2")
        captured = capsys.readouterr()
        data = json.loads(captured.out.strip())
        assert len(data) == 2


# ─── --raw output ──────────────────────────────────────────────


class TestRawOutput:
    """``--raw`` prints the Markdown log verbatim."""

    def test_raw_prints_md_content(self, tmp_path, capsys):
        sessions = [_make_session(0)]
        _write_sessions(str(tmp_path), sessions)
        _run_sessions_cmd(str(tmp_path), "--raw")
        captured = capsys.readouterr()
        # The raw MD should contain the heading we wrote.
        assert "# CodeLens install sessions" in captured.out
        assert sessions[0]["timestamp"] in captured.out

    def test_raw_when_no_log_prints_not_found_message(self, tmp_path, capsys):
        _run_sessions_cmd(str(tmp_path), "--raw")
        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "no install sessions" in captured.out.lower()


# ─── Rotation ──────────────────────────────────────────────────


class TestRotation:
    """When the JSON sidecar exceeds 1 MB, trim to last 50 sessions."""

    def test_no_rotation_under_threshold(self, tmp_path):
        sessions = [_make_session(i) for i in range(10)]
        _write_sessions(str(tmp_path), sessions)
        result = _run_sessions_cmd(str(tmp_path))
        assert result["rotated"] is False
        assert result["total_sessions"] == 10

    def test_rotation_when_over_threshold(self, tmp_path):
        """Force the JSON sidecar over 1 MB by making sessions large."""
        # Build 100 sessions with big bodies to exceed 1 MB.
        big_body = "x" * 20_000  # 20 KB per session → 100 sessions = ~2 MB
        sessions = []
        for i in range(100):
            s = _make_session(i)
            s["body"] = big_body
            sessions.append(s)
        _write_sessions(str(tmp_path), sessions)
        # Call with --entries 0 so all (post-rotation) sessions are
        # returned — otherwise the default --entries 5 would limit
        # the result and we couldn't verify the rotation count.
        result = _run_sessions_cmd(str(tmp_path), "--entries", "0")
        assert result["rotated"] is True
        # After rotation, only 50 sessions remain.
        assert result["total_sessions"] == 50
        assert result["returned_sessions"] == 50
        # The 50 kept should be the most recent (indices 50-99).
        kept_timestamps = [s["timestamp"] for s in result["sessions"]]
        # Take the last 50 of the original (indices 50-99).
        expected_last_50 = sessions[-50:]
        expected_timestamps = [s["timestamp"] for s in expected_last_50]
        assert sorted(kept_timestamps) == sorted(expected_timestamps)

    def test_rotation_is_idempotent(self, tmp_path):
        """A second call after rotation should not rotate again."""
        big_body = "x" * 20_000
        sessions = [_make_session(i) for i in range(100)]
        for s in sessions:
            s["body"] = big_body
        _write_sessions(str(tmp_path), sessions)
        first = _run_sessions_cmd(str(tmp_path))
        assert first["rotated"] is True
        # Second call — already trimmed, under threshold.
        second = _run_sessions_cmd(str(tmp_path))
        assert second["rotated"] is False


# ─── setup.sh integration ──────────────────────────────────────


class TestSetupShIntegration:
    """End-to-end: running setup.sh appends a session entry."""

    def test_setup_sh_appends_to_session_md(self, tmp_path):
        """After running setup.sh, ``session.md`` should have a new entry."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "CODELENS_CONFIG_DIR": str(tmp_path)}
        result = subprocess.run(
            ["bash", os.path.join(repo_root, "setup.sh")],
            capture_output=True, text=True, env=env, timeout=120,
        )
        # setup.sh may fail on missing tree-sitter (test env), but it
        # should still have written a session entry. The exit code
        # reflects whether the install succeeded, not whether the log
        # was written.
        md_path = os.path.join(str(tmp_path), sessions_module.SESSION_MD_FILENAME)
        assert os.path.exists(md_path), (
            f"session.md not created.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        content = open(md_path, encoding="utf-8").read()
        assert "## " in content  # at least one session heading
        assert "duration_sec" in content

    def test_setup_sh_appends_to_session_json(self, tmp_path):
        """After running setup.sh, ``session.json`` should be a valid JSON array."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "CODELENS_CONFIG_DIR": str(tmp_path)}
        subprocess.run(
            ["bash", os.path.join(repo_root, "setup.sh")],
            capture_output=True, text=True, env=env, timeout=120,
        )
        json_path = os.path.join(str(tmp_path), sessions_module.SESSION_JSON_FILENAME)
        assert os.path.exists(json_path)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 1
        entry = data[-1]
        # Every entry should have these required fields.
        for key in ("timestamp", "duration_sec", "exit_code", "python", "os", "arch"):
            assert key in entry, f"missing key in session entry: {key}"

    def test_multiple_setup_runs_append_multiple_sessions(self, tmp_path):
        """Running setup.sh twice should produce 2 session entries."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "CODELENS_CONFIG_DIR": str(tmp_path)}
        for _ in range(2):
            subprocess.run(
                ["bash", os.path.join(repo_root, "setup.sh")],
                capture_output=True, text=True, env=env, timeout=120,
            )
        json_path = os.path.join(str(tmp_path), sessions_module.SESSION_JSON_FILENAME)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2


# ─── CLI smoke test ────────────────────────────────────────────


class TestCLISmoke:
    """End-to-end: invoke ``codelens sessions`` as a real subprocess."""

    def _run_cli(self, *extra_args):
        env = os.environ.copy()
        env["PYTHONPATH"] = SCRIPTS_DIR
        return subprocess.run(
            [sys.executable, os.path.join(SCRIPTS_DIR, "codelens.py"), "sessions", *extra_args],
            capture_output=True, text=True, env=env, timeout=30,
        )

    def test_sessions_cli_runs_without_crash(self, tmp_path):
        result = self._run_cli("--config-dir", str(tmp_path))
        assert result.returncode == 0
        assert "sessions" in result.stdout.lower()

    def test_sessions_cli_with_existing_log(self, tmp_path):
        sessions = [_make_session(0)]
        _write_sessions(str(tmp_path), sessions)
        result = self._run_cli("--config-dir", str(tmp_path))
        assert result.returncode == 0
        assert "showing 1 of 1" in result.stdout

    def test_sessions_cli_json_mode(self, tmp_path):
        sessions = [_make_session(0)]
        _write_sessions(str(tmp_path), sessions)
        result = self._run_cli("--config-dir", str(tmp_path), "--json")
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert isinstance(data, list)
        assert len(data) == 1


# ─── Default config dir ────────────────────────────────────────


class TestDefaultConfigDir:
    """When --config-dir is not passed, defaults to ~/.codelens."""

    def test_default_config_dir_used_when_not_specified(self):
        """The result dict should report the default config dir."""
        # Don't actually run the command against the real ~/.codelens —
        # just verify the default is picked up correctly by setting
        # an env override (sessions.py reads DEFAULT_CONFIG_DIR at
        # module import, so we test the constant directly).
        assert sessions_module.DEFAULT_CONFIG_DIR.endswith(".codelens")
