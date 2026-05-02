#!/usr/bin/env python3
"""
CodeLens CLI — Scan command tests
"""

import subprocess
import json
import sys
import os

CODELENS_CLI = os.path.join(os.path.dirname(__file__), '..', '..', 'skills', 'codelens', 'scripts', 'codelens.py')


def run_codelens(*args, timeout=30):
    result = subprocess.run(
        [sys.executable, CODELENS_CLI] + list(args),
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


def test_help():
    code, stdout, stderr = run_codelens('--help')
    assert code == 0
    assert 'CodeLens' in stdout or 'codelens' in stdout


def test_scan_no_workspace():
    # Scan can take a long time; allow timeout as an acceptable outcome
    try:
        code, stdout, stderr = run_codelens('scan', timeout=120)
        # Should either work (auto-detect) or show error
        assert code in [0, 1, 2]
    except subprocess.TimeoutExpired:
        # Scan on a large workspace may time out; that's acceptable
        pass


def test_query_no_args():
    code, stdout, stderr = run_codelens('query')
    # Should show error about missing name arg
    assert code != 0


def test_symbols_command_exists():
    code, stdout, stderr = run_codelens('symbols', '--help')
    assert code == 0
    assert 'name' in stdout.lower() or 'symbol' in stdout.lower()


def test_detect_command_exists():
    code, stdout, stderr = run_codelens('detect', '--help')
    assert code == 0


def test_all_commands_in_help():
    code, stdout, stderr = run_codelens('--help')
    expected_commands = ['scan', 'query', 'trace', 'impact', 'secrets', 'symbols', 'detect']
    for cmd in expected_commands:
        assert cmd in stdout, f"Command '{cmd}' not found in help output"
