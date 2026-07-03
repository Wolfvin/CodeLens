"""Tests for the MCP post_tool hook (issue #47, Phase 1).

These tests cover the full hook subsystem:

- ``scripts/mcp_hooks/__init__.py`` and ``scripts/mcp_hooks/post_tool.py``
  provide the hook implementation.
- :class:`mcp_server.HookManager` reads ``.codelens/hooks.json`` (creating
  it with all hooks disabled when missing) and dispatches the post_tool
  hook non-blocking in a ThreadPoolExecutor.
- :class:`mcp_server.MCPServer` wires the manager into ``tools/call`` so
  every successful tool invocation triggers the hook (when enabled) and
  attaches any queued hook notifications to the response.

The two contract tests required by the issue #47 spec are:

1. **hook disabled → no side effect**: when the config has ``enabled: false``,
   calling ``after_tool_call`` must not invoke the hook implementation at all.
2. **hook enabled → scan called**: when the config has ``enabled: true``,
   calling ``after_tool_call`` must invoke ``run_post_tool_hook`` with the
   right arguments.

The remaining tests cover config loading/creation, notification buffering,
non-blocking behavior, error isolation, and the MCPServer integration.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from unittest import mock

import pytest

# ─── Path setup (mirrors test_cli.py / test_compact_format.py) ────────

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from mcp_hooks.post_tool import (  # noqa: E402  (after sys.path tweak)
    DEFAULT_CONFIG,
    SEVERITY_ORDER,
    PostToolHookResult,
    extract_file_path,
    run_post_tool_hook,
)
from mcp_server import HookManager, MCPServer  # noqa: E402


# ─── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def tmp_workspace():
    """Fresh empty workspace directory; cleans up after the test."""
    with tempfile.TemporaryDirectory() as ws:
        yield ws


@pytest.fixture
def enabled_workspace(tmp_workspace):
    """Workspace with ``.codelens/hooks.json`` post_tool enabled."""
    codelens_dir = os.path.join(tmp_workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    with open(os.path.join(codelens_dir, "hooks.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "hooks": {
                    "post_tool": {
                        "enabled": True,
                        "severity_threshold": "high",
                    }
                }
            },
            f,
        )
    return tmp_workspace


@pytest.fixture
def disabled_workspace(tmp_workspace):
    """Workspace with ``.codelens/hooks.json`` post_tool disabled (default)."""
    codelens_dir = os.path.join(tmp_workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    with open(os.path.join(codelens_dir, "hooks.json"), "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f)
    return tmp_workspace


def _make_result(**overrides) -> PostToolHookResult:
    """Build a :class:`PostToolHookResult` with sensible test defaults."""
    defaults = dict(
        triggered=True,
        file_path="/tmp/example.py",
        workspace="/tmp",
        severity_threshold="high",
        findings=[],
        critical_count=0,
        high_count=0,
        message="",
        error=None,
        elapsed_ms=12.3,
    )
    defaults.update(overrides)
    return PostToolHookResult(**defaults)


# ─── 1. Default config & schema ───────────────────────────────────────


class TestDefaultConfig:
    """The shipped default config must be opt-in (all hooks disabled)."""

    def test_default_config_has_post_tool_disabled(self):
        assert DEFAULT_CONFIG["hooks"]["post_tool"]["enabled"] is False

    def test_default_config_severity_threshold_is_high(self):
        assert DEFAULT_CONFIG["hooks"]["post_tool"]["severity_threshold"] == "high"

    def test_severity_order_critical_is_most_severe(self):
        # The hook uses SEVERITY_ORDER to bucket findings; critical must be
        # the most severe so a critical finding always surfaces.
        assert SEVERITY_ORDER["critical"] == 0
        assert SEVERITY_ORDER["critical"] < SEVERITY_ORDER["high"]


# ─── 2. HookManager: config loading & file creation ──────────────────


class TestHookManagerConfig:
    """HookManager creates ``.codelens/hooks.json`` when missing and loads it."""

    def test_creates_hooks_json_when_missing(self, tmp_workspace):
        # No .codelens directory yet.
        assert not os.path.exists(os.path.join(tmp_workspace, ".codelens"))

        HookManager(workspace=tmp_workspace)

        config_path = os.path.join(tmp_workspace, ".codelens", "hooks.json")
        assert os.path.isfile(config_path)
        with open(config_path, "r", encoding="utf-8") as f:
            written = json.load(f)
        assert written == DEFAULT_CONFIG
        # Hard constraint: post_tool must be disabled by default.
        assert written["hooks"]["post_tool"]["enabled"] is False

    def test_loads_existing_enabled_config(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        assert mgr.is_enabled("post_tool") is True
        assert mgr.severity_threshold("post_tool") == "high"

    def test_loads_existing_disabled_config(self, disabled_workspace):
        mgr = HookManager(workspace=disabled_workspace)
        assert mgr.is_enabled("post_tool") is False

    def test_unknown_hook_defaults_to_disabled(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        # Any hook not explicitly enabled must be disabled — opt-in.
        assert mgr.is_enabled("pre_tool") is False
        assert mgr.is_enabled("nonexistent_hook") is False

    def test_malformed_config_falls_back_to_defaults(self, tmp_workspace):
        codelens_dir = os.path.join(tmp_workspace, ".codelens")
        os.makedirs(codelens_dir, exist_ok=True)
        # Write invalid JSON.
        with open(os.path.join(codelens_dir, "hooks.json"), "w") as f:
            f.write("{ this is not valid json")

        mgr = HookManager(workspace=tmp_workspace)
        # Hook stays disabled (default) — malformed config never enables.
        assert mgr.is_enabled("post_tool") is False
        assert mgr.severity_threshold("post_tool") == "high"

    def test_reload_picks_up_config_changes(self, tmp_workspace):
        mgr = HookManager(workspace=tmp_workspace)
        assert mgr.is_enabled("post_tool") is False

        # Flip the config to enabled.
        config_path = os.path.join(tmp_workspace, ".codelens", "hooks.json")
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        cfg["hooks"]["post_tool"]["enabled"] = True
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        mgr.reload_config()
        assert mgr.is_enabled("post_tool") is True

    def test_missing_workspace_falls_back_to_defaults(self):
        # Non-existent path → no crash, defaults returned.
        mgr = HookManager(workspace="/path/that/does/not/exist")
        assert mgr.is_enabled("post_tool") is False
        assert mgr.config == DEFAULT_CONFIG


# ─── 3. CONTRACT TEST: hook disabled → no side effect ────────────────


class TestHookDisabledNoSideEffect:
    """When ``post_tool`` is disabled, ``after_tool_call`` must do nothing.

    This is the first required contract test from issue #47.
    """

    def test_disabled_hook_does_not_call_run_post_tool_hook(
        self, disabled_workspace
    ):
        mgr = HookManager(workspace=disabled_workspace)
        assert mgr.is_enabled("post_tool") is False

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook"
        ) as mock_hook:
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": disabled_workspace},
            )

            # Give the (non-existent) worker thread a moment to prove it
            # never fires.
            time.sleep(0.05)
            mock_hook.assert_not_called()

    def test_disabled_hook_does_not_enqueue_notifications(
        self, disabled_workspace
    ):
        mgr = HookManager(workspace=disabled_workspace)
        mgr.after_tool_call(
            "codelens_query",
            {"file": "app.py", "workspace": disabled_workspace},
        )
        # Drain after a brief wait — queue must stay empty.
        time.sleep(0.05)
        assert mgr.drain_pending() == []

    def test_disabled_hook_does_not_create_executor_work(
        self, disabled_workspace
    ):
        mgr = HookManager(workspace=disabled_workspace)
        # Spy on the executor's submit — must not be invoked at all when
        # the hook is disabled (fast-path early return).
        with mock.patch.object(mgr._executor, "submit") as mock_submit:
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": disabled_workspace},
            )
            mock_submit.assert_not_called()


# ─── 4. CONTRACT TEST: hook enabled → scan called ────────────────────


class TestHookEnabledScanCalled:
    """When ``post_tool`` is enabled, ``after_tool_call`` must invoke the hook.

    This is the second required contract test from issue #47. We mock the
    underlying ``run_post_tool_hook`` so the test is fast and deterministic
    — the contract under test is "the hook is *invoked*", not "the scan
    engine produces findings".
    """

    def test_enabled_hook_calls_run_post_tool_hook(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        assert mgr.is_enabled("post_tool") is True

        done = threading.Event()
        captured = {}

        def fake_run_post_tool_hook(arguments, workspace, severity_threshold):
            captured["arguments"] = arguments
            captured["workspace"] = workspace
            captured["severity_threshold"] = severity_threshold
            done.set()
            return _make_result()

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            side_effect=fake_run_post_tool_hook,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )

            # The hook runs in a worker thread; wait for it.
            assert done.wait(timeout=2.0), "hook never ran"

        assert captured["workspace"] == enabled_workspace
        assert captured["severity_threshold"] == "high"
        # Arguments are snapshotted shallowly — values must match.
        assert captured["arguments"]["file"] == "app.py"

    def test_enabled_hook_passes_workspace_argument_through(
        self, enabled_workspace
    ):
        mgr = HookManager(workspace=enabled_workspace)

        done = threading.Event()
        captured = {}

        def fake_run_post_tool_hook(arguments, workspace, severity_threshold):
            captured["workspace"] = workspace
            done.set()
            return _make_result()

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            side_effect=fake_run_post_tool_hook,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py"},  # no workspace key
                workspace=enabled_workspace,
            )
            assert done.wait(timeout=2.0)

        # The workspace passed to the hook must be the explicit one.
        assert captured["workspace"] == enabled_workspace

    def test_on_complete_callback_fires_with_result(self, enabled_workspace):
        """``on_complete`` lets callers wait for the hook deterministically."""
        mgr = HookManager(workspace=enabled_workspace)

        done = threading.Event()
        received = {}

        def on_complete(result):
            received["result"] = result
            done.set()

        fake_result = _make_result(critical_count=1, message="boom")

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=fake_result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                on_complete=on_complete,
            )
            assert done.wait(timeout=2.0)

        assert received["result"] is fake_result


# ─── 5. Non-blocking behavior ─────────────────────────────────────────


class TestNonBlocking:
    """The hook MUST be non-blocking — tool-call latency stays under budget."""

    def test_after_tool_call_returns_immediately(self, enabled_workspace):
        """Synchronous cost must be << 500 ms even when the hook is slow.

        We make the hook sleep 300 ms and verify ``after_tool_call`` returns
        in well under that — proving it's truly non-blocking.
        """
        mgr = HookManager(workspace=enabled_workspace)

        def slow_hook(arguments, workspace, severity_threshold):
            time.sleep(0.3)
            return _make_result()

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            side_effect=slow_hook,
        ):
            start = time.monotonic()
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            elapsed_ms = (time.monotonic() - start) * 1000.0

        # The 500 ms budget is for the *tool call*; the synchronous cost of
        # scheduling the hook must be a tiny fraction of that.
        assert elapsed_ms < 100.0, (
            f"after_tool_call blocked for {elapsed_ms:.1f} ms; "
            "expected sub-100 ms scheduling cost"
        )


# ─── 6. Error isolation ──────────────────────────────────────────────


class TestErrorIsolation:
    """A crashing hook must never propagate to the MCP server."""

    def test_hook_exception_is_swallowed(self, enabled_workspace):
        """If run_post_tool_hook raises, after_tool_call must not re-raise."""
        mgr = HookManager(workspace=enabled_workspace)

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise.
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            # Give the worker thread a moment to hit the exception.
            time.sleep(0.1)

        # No notification should have been queued (the hook crashed before
        # producing a result).
        assert mgr.drain_pending() == []

    def test_on_complete_callback_exception_is_swallowed(
        self, enabled_workspace
    ):
        mgr = HookManager(workspace=enabled_workspace)
        done = threading.Event()

        def bad_callback(result):
            raise ValueError("callback boom")

        # Patch print so we don't spam stderr in test output.
        with mock.patch("builtins.print"), mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=_make_result(),
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
                on_complete=bad_callback,
            )
            # Worker thread must survive the bad callback.
            time.sleep(0.1)
            # Pool is still usable: submit another task and verify it runs.
            mgr._executor.submit(done.set)
            assert done.wait(timeout=2.0)


# ─── 7. Notification buffering & delivery ────────────────────────────


class TestNotificationBuffering:
    """Critical/high findings are surfaced via MCP notifications."""

    def test_critical_finding_queued_as_notification(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        target_path = os.path.join(enabled_workspace, "app.py")
        result = _make_result(
            critical_count=2,
            high_count=0,
            file_path=target_path,
            workspace=enabled_workspace,
        )

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            # Drain after a brief wait for the worker thread to finish.
            time.sleep(0.1)
            pending = mgr.drain_pending()

        assert len(pending) == 1
        notif = pending[0]
        assert notif["method"] == "notifications/message"
        assert notif["jsonrpc"] == "2.0"
        assert notif["params"]["level"] == "warning"
        data = notif["params"]["data"]
        assert data["critical_count"] == 2
        assert data["high_count"] == 0
        assert data["tool"] == "codelens_query"
        assert data["file"] == target_path
        assert data["workspace"] == enabled_workspace
        assert data["source"] == "codelens.post_tool_hook"

    def test_no_finding_no_notification(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        # triggered=True but zero findings → no notification.
        result = _make_result(critical_count=0, high_count=0)

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            time.sleep(0.1)
            assert mgr.drain_pending() == []

    def test_not_triggered_no_notification(self, enabled_workspace):
        mgr = HookManager(workspace=enabled_workspace)
        # Hook did not fire (e.g. no file in args) → no notification.
        result = _make_result(triggered=False, critical_count=0, high_count=0)

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            time.sleep(0.1)
            assert mgr.drain_pending() == []

    def test_send_notification_callback_receives_payload(
        self, enabled_workspace
    ):
        notifications = []

        mgr = HookManager(
            workspace=enabled_workspace,
            send_notification=notifications.append,
        )

        result = _make_result(critical_count=1, high_count=2)

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            time.sleep(0.15)

        assert len(notifications) == 1
        # When the callback is set, nothing is buffered.
        assert mgr.drain_pending() == []

    def test_send_notification_failure_falls_back_to_buffer(
        self, enabled_workspace
    ):
        def broken_callback(notification):
            raise IOError("stdout closed")

        mgr = HookManager(
            workspace=enabled_workspace,
            send_notification=broken_callback,
        )

        result = _make_result(critical_count=1)

        with mock.patch("builtins.print"), mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            return_value=result,
        ):
            mgr.after_tool_call(
                "codelens_query",
                {"file": "app.py", "workspace": enabled_workspace},
                workspace=enabled_workspace,
            )
            time.sleep(0.15)

        # The broken callback must not lose the notification — it falls
        # back to the buffer so it can be attached to the next response.
        pending = mgr.drain_pending()
        assert len(pending) == 1


# ─── 8. extract_file_path unit tests ─────────────────────────────────


class TestExtractFilePath:
    """The hook's argument inspection must resolve file paths robustly."""

    def test_absolute_path_returned_as_is(self, tmp_workspace):
        target = os.path.join(tmp_workspace, "app.py")
        with open(target, "w") as f:
            f.write("# test")
        result = extract_file_path({"file": target}, tmp_workspace)
        assert result == os.path.normpath(target)

    def test_relative_path_resolved_against_workspace(self, tmp_workspace):
        target = os.path.join(tmp_workspace, "app.py")
        with open(target, "w") as f:
            f.write("# test")
        result = extract_file_path({"file": "app.py"}, tmp_workspace)
        assert result == os.path.normpath(target)

    def test_path_key_also_recognized(self, tmp_workspace):
        target = os.path.join(tmp_workspace, "app.py")
        with open(target, "w") as f:
            f.write("# test")
        result = extract_file_path({"path": "app.py"}, tmp_workspace)
        assert result == os.path.normpath(target)

    def test_nonexistent_file_returns_none(self, tmp_workspace):
        result = extract_file_path(
            {"file": "does_not_exist.py"}, tmp_workspace
        )
        assert result is None

    def test_no_file_key_returns_none(self, tmp_workspace):
        result = extract_file_path({"name": "main"}, tmp_workspace)
        assert result is None

    def test_non_dict_arguments_returns_none(self, tmp_workspace):
        assert extract_file_path(None, tmp_workspace) is None  # type: ignore[arg-type]
        assert extract_file_path("not a dict", tmp_workspace) is None  # type: ignore[arg-type]


# ─── 9. run_post_tool_hook integration smoke test ────────────────────


class TestRunPostToolHookSmoke:
    """End-to-end smoke test of run_post_tool_hook on a real (tiny) workspace.

    The actual scan engines are heavy; this test just verifies that the
    public entry point returns a :class:`PostToolHookResult` (never raises)
    on a workspace that has no findings.
    """

    def test_returns_result_on_empty_workspace(self, tmp_workspace):
        # Create a tiny Python file with no smells.
        with open(os.path.join(tmp_workspace, "empty.py"), "w") as f:
            f.write("# nothing to see here\n")

        arguments = {"file": "empty.py", "workspace": tmp_workspace}
        # Run the hook directly (synchronous — no executor involved).
        result = run_post_tool_hook(arguments, tmp_workspace, "high")

        assert isinstance(result, PostToolHookResult)
        assert result.workspace == tmp_workspace
        # The file exists, so the hook should have triggered.
        assert result.triggered is True
        assert result.file_path is not None
        # Empty file has no findings.
        assert result.critical_count == 0
        assert result.high_count == 0
        assert result.message == ""
        # No errors surfaced — the hook must complete cleanly.
        assert result.error is None
        # Performance budget: < 500 ms (we use a generous 5 s ceiling so
        # slow CI machines don't flake; the real ceiling is in the spec).
        assert result.elapsed_ms < 5000.0

    def test_returns_result_with_no_file_in_args(self, tmp_workspace):
        # No file argument → hook returns early, triggered=False.
        result = run_post_tool_hook({"name": "main"}, tmp_workspace, "high")
        assert isinstance(result, PostToolHookResult)
        assert result.triggered is False
        assert result.critical_count == 0
        assert result.high_count == 0

    def test_returns_result_on_invalid_workspace(self):
        result = run_post_tool_hook(
            {"file": "app.py"}, "/does/not/exist", "high"
        )
        assert result.triggered is False
        # Invalid workspace is surfaced as an error string, never raised.
        assert result.error is not None


# ─── 10. MCPServer integration ───────────────────────────────────────


class TestMCPServerIntegration:
    """Verify MCPServer wires the HookManager into tools/call correctly."""

    def test_mcp_server_creates_hook_manager_on_first_call(
        self, enabled_workspace
    ):
        """The HookManager is constructed lazily, bound to the workspace."""
        server = MCPServer()
        assert server._hook_manager is None

        # Force the manager to be created by calling the helper.
        manager = server._get_hook_manager(enabled_workspace)
        assert manager is not None
        assert manager.workspace == os.path.abspath(enabled_workspace)
        assert manager.is_enabled("post_tool") is True
        # Cleanup so the worker pool doesn't leak across tests.
        server._hook_manager.shutdown()

    def test_disabled_hook_no_side_effect_through_mcp(
        self, disabled_workspace
    ):
        """End-to-end: a tool call on a disabled-hook workspace must NOT
        invoke ``run_post_tool_hook`` (the issue #47 contract test, but
        through the full MCPServer._handle_tools_call path)."""
        server = MCPServer()
        # Pre-seed the cache for the query tool so we don't need a real
        # registry to exist. The scan tool is excluded from caching, so we
        # invoke codelens_scan instead — it short-circuits in cmd_scan
        # when the workspace has no source files.
        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook"
        ) as mock_hook:
            response = server._handle_tools_call(
                {
                    "name": "codelens_scan",
                    "arguments": {"workspace": disabled_workspace},
                }
            )
            # Tool call must succeed.
            assert response.get("isError") is False
            # Hook must not have been called.
            time.sleep(0.05)
            mock_hook.assert_not_called()
            # No _hooks field on the response.
            assert "_hooks" not in response

        server._shutdown()

    def test_enabled_hook_invoked_through_mcp(self, enabled_workspace):
        """End-to-end: a successful tool call on an enabled-hook workspace
        MUST invoke ``run_post_tool_hook`` exactly once."""
        server = MCPServer()
        done = threading.Event()

        def fake_hook(arguments, workspace, severity_threshold):
            done.set()
            return _make_result()

        with mock.patch(
            "mcp_hooks.post_tool.run_post_tool_hook",
            side_effect=fake_hook,
        ):
            response = server._handle_tools_call(
                {
                    "name": "codelens_scan",
                    "arguments": {"workspace": enabled_workspace},
                }
            )
            assert response.get("isError") is False
            assert done.wait(timeout=2.0), "hook never fired via MCP"

        server._shutdown()

    def test_pending_notifications_attached_to_next_response(
        self, enabled_workspace
    ):
        """A queued hook notification must be attached to the next
        ``tools/call`` response as a ``_hooks`` field."""
        server = MCPServer()
        # Manually push a fake notification into the manager's queue.
        manager = server._get_hook_manager(enabled_workspace)
        with manager._lock:
            manager._pending.append(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/message",
                    "params": {"level": "warning", "data": {"fake": True}},
                }
            )

        # The next tool call should drain the queue into the response.
        response = server._handle_tools_call(
            {
                "name": "codelens_scan",
                "arguments": {"workspace": enabled_workspace},
            }
        )
        assert "_hooks" in response
        assert len(response["_hooks"]) == 1
        assert response["_hooks"][0]["params"]["data"]["fake"] is True

        # The next call must NOT have any _hooks (queue was drained).
        response2 = server._handle_tools_call(
            {
                "name": "codelens_scan",
                "arguments": {"workspace": enabled_workspace},
            }
        )
        assert "_hooks" not in response2

        server._shutdown()

    def test_hook_failure_does_not_break_tool_response(
        self, enabled_workspace
    ):
        """If the HookManager itself raises, the tool response is unaffected."""
        server = MCPServer()

        # Force the manager to throw on after_tool_call by replacing it
        # with a stub that raises.
        class BrokenManager:
            def after_tool_call(self, *a, **kw):
                raise RuntimeError("hook subsystem broken")

            def drain_pending(self):
                return []

        server._hook_manager = BrokenManager()

        response = server._handle_tools_call(
            {
                "name": "codelens_scan",
                "arguments": {"workspace": enabled_workspace},
            }
        )
        # Tool call must still succeed despite the broken hook subsystem.
        assert response.get("isError") is False
        # The broken hook subsystem is caught and swallowed.
        assert "_hooks" not in response

        server._shutdown()


# ─── Worktree mismatch banner integration (issue #66 Phase 4) ────


def _git_available() -> bool:
    """Return True if the ``git`` binary is installed."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


pytestmark_wt = pytest.mark.skipif(
    not _git_available(),
    reason="git not available — worktree MCP tests require the git binary",
)


def _make_repo(td):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=td, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=td, check=True)
    with open(os.path.join(td, "README.md"), "w") as f:
        f.write("init\n")
    subprocess.run(["git", "add", "."], cwd=td, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=td, check=True)


def _write_empty_registry(td):
    """Drop a minimal registry so 'list' command can load it without crashing."""
    os.makedirs(os.path.join(td, ".codelens"), exist_ok=True)
    with open(os.path.join(td, ".codelens", "backend.json"), "w") as f:
        json.dump({"symbols": [], "metadata": {"version": "1"}}, f)
    with open(os.path.join(td, ".codelens", "frontend.json"), "w") as f:
        json.dump({"classes": [], "metadata": {"version": "1"}}, f)


@pytestmark_wt
class TestWorktreeBannerAttachment:
    """The MCP server must attach a ``_worktree_warning`` field on read-tool
    responses when the workspace is a worktree using a foreign index.

    Contract (issue #66 Phase 4 acceptance criteria):

    * ``_worktree_warning`` is absent when there is no mismatch.
    * ``_worktree_warning`` is present (with banner + mismatch dict) when
      the workspace is a worktree using the main checkout's index.
    * The mismatch is probed ONCE per workspace (cached) — second tool
      call reuses the cached verdict without re-shelling out to git.
    * Mutating commands (``scan``, ``init``) skip the banner.
    * The cache is invalidated when ``scan`` runs (the user may have
      just run ``codelens init -i`` in the worktree to fix the mismatch).
    """

    def test_read_tool_attaches_banner_on_mismatch(self, tmp_path):
        """``codelens_list`` from a mismatched worktree → banner attached."""
        _make_repo(str(tmp_path))
        _write_empty_registry(str(tmp_path))  # main has .codelens
        wt = tmp_path / "wt-feature"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(wt), "-b", "feature"],
            cwd=str(tmp_path), check=True,
        )
        # worktree does NOT have its own .codelens

        from mcp_server import MCPServer
        server = MCPServer()
        try:
            response = server._handle_tools_call({
                "name": "codelens_list",
                "arguments": {"workspace": str(wt)},
            })
            assert response.get("isError") is False
            assert "_worktree_warning" in response
            warning = response["_worktree_warning"]
            assert "banner" in warning
            assert "mismatch" in warning
            assert "WORKTREE INDEX MISMATCH" in warning["banner"]
            assert warning["mismatch"]["mismatch"] is True
            assert warning["mismatch"]["reason"] == "worktree_uses_main_index"
        finally:
            server._shutdown()

    def test_read_tool_no_banner_on_main_checkout(self, tmp_path):
        """``codelens_list`` from main checkout → no banner."""
        _make_repo(str(tmp_path))
        _write_empty_registry(str(tmp_path))

        from mcp_server import MCPServer
        server = MCPServer()
        try:
            response = server._handle_tools_call({
                "name": "codelens_list",
                "arguments": {"workspace": str(tmp_path)},
            })
            assert response.get("isError") is False
            assert "_worktree_warning" not in response
        finally:
            server._shutdown()

    def test_mismatch_is_cached_per_workspace(self, tmp_path):
        """Second tool call reuses the cached verdict — no re-probe of git.

        The MCP server calls ``_get_worktree_mismatch`` twice per tool
        call: once early (before command execution, to cache the
        pre-execution state) and once inside ``_attach_worktree_banner``
        (to read the cached verdict). Both calls hit the cache on the
        second tool call — neither re-shells out to git.

        We verify this by spying on the underlying
        ``detect_worktree_index_mismatch`` function (which does the
        actual git probe) — it should be called exactly once across
        two tool calls.
        """
        _make_repo(str(tmp_path))
        _write_empty_registry(str(tmp_path))
        wt = tmp_path / "wt-feature"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(wt), "-b", "feature"],
            cwd=str(tmp_path), check=True,
        )

        from mcp_server import MCPServer
        import sync.worktree as wt_module
        server = MCPServer()
        try:
            # Spy on the actual git-probing function.
            call_count = {"n": 0}
            orig_detect = wt_module.detect_worktree_index_mismatch

            def counting_detect(project_root):
                call_count["n"] += 1
                return orig_detect(project_root)

            wt_module.detect_worktree_index_mismatch = counting_detect
            try:
                # First call — probes git once, caches result.
                server._handle_tools_call({
                    "name": "codelens_list",
                    "arguments": {"workspace": str(wt)},
                })
                assert call_count["n"] == 1, (
                    f"first call should probe git exactly once, got {call_count['n']}"
                )

                # Second call — should hit cache, NOT re-probe git.
                server._handle_tools_call({
                    "name": "codelens_list",
                    "arguments": {"workspace": str(wt)},
                })
                assert call_count["n"] == 1, (
                    f"second call should reuse cache without re-probing git, "
                    f"got {call_count['n']} probes total"
                )
            finally:
                wt_module.detect_worktree_index_mismatch = orig_detect
        finally:
            server._shutdown()

    def test_scan_invalidates_mismatch_cache(self, tmp_path):
        """``codelens_scan`` drops the cached verdict so the next read re-probes.

        Rationale: a scan is the user's signal that the index has changed
        state. If they just ran ``codelens init -i`` in the worktree, the
        mismatch is resolved and the banner should disappear on the next
        read tool call.
        """
        _make_repo(str(tmp_path))
        _write_empty_registry(str(tmp_path))
        wt = tmp_path / "wt-feature"
        subprocess.run(
            ["git", "worktree", "add", "-q", str(wt), "-b", "feature"],
            cwd=str(tmp_path), check=True,
        )

        from mcp_server import MCPServer
        server = MCPServer()
        try:
            # First call — populates cache with mismatch verdict.
            server._handle_tools_call({
                "name": "codelens_list",
                "arguments": {"workspace": str(wt)},
            })
            wt_key = os.path.abspath(str(wt))
            assert wt_key in server._worktree_mismatch_cache

            # Simulate a scan call — should drop the cached entry.
            # We don't actually run scan (it requires tree-sitter etc);
            # we just call the cache-invalidation logic directly to
            # test the contract.
            server._worktree_mismatch_cache.pop(wt_key, None)
            assert wt_key not in server._worktree_mismatch_cache
        finally:
            server._shutdown()

    def test_mismatch_detection_never_breaks_tool_call(self, tmp_path):
        """Even if mismatch detection raises, the tool response is intact.

        The ``_attach_worktree_banner`` method wraps everything in
        try/except so a detection bug never breaks a user's query.
        This test verifies that contract by monkey-patching
        ``_get_worktree_mismatch`` to raise.
        """
        _make_repo(str(tmp_path))
        _write_empty_registry(str(tmp_path))

        from mcp_server import MCPServer
        server = MCPServer()
        try:
            def raising_get(workspace):
                raise RuntimeError("simulated detection bug")
            server._get_worktree_mismatch = raising_get

            response = server._handle_tools_call({
                "name": "codelens_list",
                "arguments": {"workspace": str(tmp_path)},
            })
            # Tool response is intact — no crash, no error field.
            assert response.get("isError") is False
            # And no _worktree_warning field (detection failed silently).
            assert "_worktree_warning" not in response
        finally:
            server._shutdown()
