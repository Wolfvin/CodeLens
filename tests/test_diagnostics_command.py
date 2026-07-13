# @WHO:   tests/test_diagnostics_command.py
# @WHAT:  Tests for LSP diagnostics surfacing (issue #253)
# @PART:  tests
"""Tests for `context --check diagnostics` (issue #253).

Verifies the two halves of the feature that are independent of a live
language server:

1. ``LSPClient.get_diagnostics`` — the notification-filtering logic: given
   publishDiagnostics notifications sitting in ``_notification_list``,
   return the latest one matching the file's URI.
2. ``commands.diagnostics.execute`` — the raw-LSP → finding transformation
   (severity mapping, 0→1-indexed line conversion) and the graceful
   degradation paths (no --file, file missing, LSP unavailable).

NOTE on end-to-end coverage: a full end-to-end test through a real
language server could not be run in the dev environment — rust-analyzer
(the only installed server) does not respond to `initialize` within 60s
on this machine (a pre-existing rust-analyzer startup issue, unrelated to
this code — the `initialize()` method is untouched by #253). The mocked
tests below cover every line of logic #253 actually adds; the live path is
exercised by the same `_notification_list` capture the other LSP features
(find_references, go_to_definition) already rely on in production.
"""

import argparse
import os
import sys
import tempfile
from unittest import mock

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from lsp_client import LSPClient, _path_to_uri  # noqa: E402
from commands import diagnostics  # noqa: E402


class TestLSPClientGetDiagnostics:
    def _client(self):
        c = LSPClient.__new__(LSPClient)  # bypass __init__ (no real process)
        import threading
        c._initialized = True
        c._lock = threading.Lock()
        c._notification_list = []
        return c

    def test_returns_diagnostics_matching_uri(self):
        c = self._client()
        target = os.path.abspath("foo.rs")
        uri = _path_to_uri(target)
        c._notification_list = [
            {"method": "textDocument/publishDiagnostics",
             "params": {"uri": uri, "diagnostics": [
                 {"severity": 1, "message": "mismatched types",
                  "range": {"start": {"line": 1, "character": 17}}},
             ]}},
        ]
        with mock.patch.object(c, "open_file"):
            result = c.get_diagnostics(target, wait_timeout=0.5)
        assert len(result) == 1
        assert result[0]["message"] == "mismatched types"

    def test_ignores_other_files_diagnostics(self):
        c = self._client()
        target = os.path.abspath("foo.rs")
        other_uri = _path_to_uri(os.path.abspath("bar.rs"))
        c._notification_list = [
            {"method": "textDocument/publishDiagnostics",
             "params": {"uri": other_uri, "diagnostics": [
                 {"severity": 1, "message": "in another file"}]}},
        ]
        with mock.patch.object(c, "open_file"):
            result = c.get_diagnostics(target, wait_timeout=0.4)
        assert result == []

    def test_latest_notification_wins(self):
        c = self._client()
        target = os.path.abspath("foo.rs")
        uri = _path_to_uri(target)

        def _inject(*_a, **_k):
            # First a stale (empty) push, then the real one — simulate a
            # server that pushes progressively. (*args: open_file is called
            # with the file path, which the mock forwards to side_effect.)
            c._notification_list.append(
                {"method": "textDocument/publishDiagnostics",
                 "params": {"uri": uri, "diagnostics": []}})
            c._notification_list.append(
                {"method": "textDocument/publishDiagnostics",
                 "params": {"uri": uri, "diagnostics": [
                     {"severity": 2, "message": "unused variable"}]}})

        with mock.patch.object(c, "open_file", side_effect=_inject):
            result = c.get_diagnostics(target, wait_timeout=0.5)
        assert len(result) == 1
        assert result[0]["message"] == "unused variable"

    def test_not_initialized_returns_empty(self):
        c = self._client()
        c._initialized = False
        assert c.get_diagnostics("foo.rs", wait_timeout=0.1) == []


class TestDiagnosticsCommand:
    def _args(self, **kw):
        ns = argparse.Namespace(workspace=".", file=None, timeout=1.0)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_missing_file_errors(self):
        result = diagnostics.execute(self._args(file=None), ".")
        assert result["status"] == "error"
        assert "--file" in result["error"]

    def test_file_not_found_errors(self):
        result = diagnostics.execute(self._args(file="does_not_exist_xyz.rs"), ".")
        assert result["status"] == "error"
        assert "not found" in result["error"]

    def test_lsp_unavailable_degrades_gracefully(self):
        with tempfile.TemporaryDirectory() as ws:
            f = os.path.join(ws, "a.py")
            open(f, "w").close()
            fake_engine = mock.Mock()
            fake_engine.lsp_active = False
            with mock.patch("hybrid_engine.create_hybrid_engine", return_value=fake_engine):
                result = diagnostics.execute(self._args(file="a.py"), ws)
        assert result["status"] == "ok"
        assert result["lsp_available"] is False
        assert result["diagnostics"] == []
        assert "note" in result

    def test_raw_diagnostics_transformed_to_findings(self):
        with tempfile.TemporaryDirectory() as ws:
            f = os.path.join(ws, "a.rs")
            open(f, "w").close()
            fake_engine = mock.Mock()
            fake_engine.lsp_active = True
            fake_engine.get_diagnostics.return_value = [
                {"severity": 1, "message": "mismatched types", "source": "rustc",
                 "code": "E0308", "range": {"start": {"line": 1, "character": 17}}},
                {"severity": 2, "message": "unused variable: x", "source": "rustc",
                 "range": {"start": {"line": 4, "character": 8}}},
            ]
            with mock.patch("hybrid_engine.create_hybrid_engine", return_value=fake_engine):
                result = diagnostics.execute(self._args(file="a.rs"), ws)

        assert result["status"] == "ok"
        assert result["lsp_available"] is True
        assert result["total"] == 2
        assert result["by_severity"] == {"error": 1, "warning": 1}
        # 0-indexed LSP line 1 must be reported as 1-indexed line 2
        assert result["diagnostics"][0]["line"] == 2
        assert result["diagnostics"][0]["severity"] == "error"
        assert result["diagnostics"][0]["code"] == "E0308"
        assert result["diagnostics"][1]["line"] == 5
        assert result["diagnostics"][1]["severity"] == "warning"
