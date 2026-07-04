"""LSP status command — check which language servers are available.

Issue #33: this subcommand and the top-level ``--lsp-status`` flag (intercepted
in ``codelens.py``) MUST return the same payload. Both entry points therefore
delegate to :func:`hybrid_engine.get_lsp_status` — the single source of truth
for LSP availability. The MCP server dynamically discovers this subcommand, so
unifying here also fixes the CLI/MCP divergence described in the issue.
"""

from commands import register_command


def add_args(sub):
    """No additional arguments for lsp-status."""
    pass


def execute(args, workspace):
    """Check which LSP servers are available on the system.

    Delegates to :func:`hybrid_engine.get_lsp_status` so that
    ``codelens lsp-status``, ``codelens --lsp-status``, and the MCP
    ``codelens_lsp_status`` tool all return the same payload.
    """
    try:
        from hybrid_engine import get_lsp_status
    except ImportError:
        return {
            "status": "ok",
            "lsp_available": False,
            "available_count": 0,
            "total_servers": 0,
            "servers": {},
            "recommendation": (
                "hybrid_engine.py not found. Install hybrid analysis support "
                "to enable LSP status checks."
            ),
        }

    return get_lsp_status()

# Issue #199: deprecated "lsp-status" alias registration removed; this module is now an implementation module imported by the "doctor" umbrella command.
