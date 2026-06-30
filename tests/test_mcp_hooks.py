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
