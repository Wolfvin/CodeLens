"""
Tests for CLI arg errors surfacing on stdout for machine formats (issue #315).

An argparse error used to print to stderr and leave stdout empty, so an agent
parsing stdout saw "no results" instead of an error. For machine formats the
error must appear on stdout as JSON.

Subprocess-based (argparse lives at the process entry point). Every call passes
timeout= so a hang fails fast rather than stalling the suite (the #303 lesson).
"""

import json
import os
import subprocess
import sys

import pytest

CODELENS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "codelens.py",
)


def _run(args):
    return subprocess.run(
        [sys.executable, CODELENS, *args],
        capture_output=True, text=True, timeout=60,
    )


def test_arg_error_is_json_on_stdout_for_compact():
    # `.` is taken as the pattern; `execute` is an unrecognized extra arg.
    r = _run(["search", ".", "--mode", "symbol", "execute", "--format", "compact"])

    assert r.stdout.strip(), "stdout must not be empty on a CLI arg error"
    payload = json.loads(r.stdout)
    assert payload["s"] == "error"
    assert payload["error_type"] == "cli_argument"


def test_arg_error_is_json_on_stdout_for_json():
    r = _run(["search", ".", "--mode", "symbol", "execute", "--format", "json"])

    payload = json.loads(r.stdout)
    assert payload["s"] == "error"


def test_human_mode_keeps_error_on_stderr():
    """No machine format: the friendly stderr behaviour is unchanged."""
    r = _run(["search", ".", "--mode", "symbol", "execute"])

    assert "unrecognized arguments" in r.stderr
    assert not r.stdout.strip()


def test_valid_call_is_unaffected():
    """The error path must not touch normal parsing."""
    r = _run(["--command-count"])
    assert r.returncode == 0
    assert r.stdout.strip().isdigit()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
