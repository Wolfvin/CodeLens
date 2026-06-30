"""
CodeLens MCP Hooks — auto-trigger scan/check after AI agent file writes.

Implements the hook system described in issue #47 (Phase 1: post_tool hook).

Hooks are *opt-in*: every hook defaults to ``enabled: false`` in
``.codelens/hooks.json``. The MCP server (:class:`mcp_server.HookManager`)
loads that config on first use, creates the default file if it is missing,
and runs each enabled hook non-blocking in a ThreadPoolExecutor so a hook
failure can never crash the server or stall a tool response.

Public API
----------
- :func:`post_tool.run_post_tool_hook` — single entry point used by
  :class:`mcp_server.HookManager`.
"""

from .post_tool import (
    run_post_tool_hook,
    PostToolHookResult,
    DEFAULT_CONFIG,
    SEVERITY_ORDER,
)

__all__ = [
    "run_post_tool_hook",
    "PostToolHookResult",
    "DEFAULT_CONFIG",
    "SEVERITY_ORDER",
]

__version__ = "1.0.0"
