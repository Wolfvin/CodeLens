"""LSP status command — check which language servers are available."""

from commands import register_command


def add_args(sub):
    """No additional arguments for lsp-status."""
    pass


def execute(args, workspace):
    """Check which LSP servers are available on the system."""
    try:
        from lsp_client import detect_available_servers, LSP_SERVERS
    except ImportError:
        return {
            "status": "ok",
            "lsp_available": False,
            "servers": {},
            "hint": "lsp_client.py not found. Install hybrid analysis support.",
        }

    available = detect_available_servers()
    servers = {}
    for name, info in available.items():
        servers[name] = {
            "available": info.get("available", False),
            "languages": info.get("languages", []),
            "install_hint": info.get("install_hint", ""),
        }

    any_available = any(s["available"] for s in servers.values())

    return {
        "status": "ok",
        "lsp_available": any_available,
        "servers": servers,
        "hint": (
            "LSP servers found! Use --deep flag for enhanced analysis."
            if any_available
            else "No LSP servers found. Install one for deep analysis (see install_hint)."
        ),
    }


register_command(
    "lsp-status",
    "Check which LSP servers are available for deep analysis",
    add_args,
    execute,
)
