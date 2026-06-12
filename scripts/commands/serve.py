"""Serve command — Start CodeLens MCP server for AI agent integration.

Provides persistent JSON-RPC server mode over stdio (MCP protocol).
AI agents can connect and call any CodeLens command as an MCP tool
without the cold-start overhead of spawning a new process each time.

Usage:
    codelens serve                  # Start MCP server (stdio transport)
    codelens serve --watch          # Auto-watch mode for live updates
    codelens serve --port 8080      # HTTP/SSE transport (optional)
    codelens serve --config         # Print MCP client configuration
"""

import os
import json
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted, used for --watch)")
    parser.add_argument("--watch", action="store_true", default=False,
                        help="Auto-watch files for live registry updates")
    parser.add_argument("--port", type=int, default=None,
                        help="HTTP/SSE port for remote access (in addition to stdio)")
    parser.add_argument("--config", action="store_true", default=False,
                        help="Print MCP client configuration for Claude Desktop, Cursor, etc.")


def execute(args, workspace):
    """Execute the serve command. Starts the MCP server."""
    if getattr(args, 'config', False):
        # --config is a quick one-shot command, print directly and exit
        import sys
        from mcp_server import generate_mcp_config
        config = generate_mcp_config()
        result = {
            "status": "ok",
            "message": "MCP client configurations generated. Add to your AI tool's config file.",
            "configs": config
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0)

    from mcp_server import run_mcp_server
    watch = getattr(args, 'watch', False)
    port = getattr(args, 'port', None)

    # This is a long-running command — it takes over the process
    run_mcp_server(watch=watch, port=port)

    return {"status": "stopped"}


def _print_config():
    """Print MCP client configuration for popular AI tools."""
    from mcp_server import generate_mcp_config
    config = generate_mcp_config()
    return {
        "status": "ok",
        "message": "MCP client configurations generated. Add to your AI tool's config file.",
        "configs": config
    }


register_command("serve", "Start MCP server for AI agent integration (JSON-RPC over stdio)", add_args, execute)
