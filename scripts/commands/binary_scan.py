"""Binary artifact scan command for CodeLens.

v5.9: Enhanced with Tauri reverse engineering capabilities:
- Tauri IPC command/handler mapping from Rust source
- Tauri capabilities/permissions security audit
- Sidecar binary analysis
- Updater configuration analysis
- WebView security audit (CSP, asset protocol)
- Deep-link scheme analysis
- Build configuration security analysis
- Electron app detection
"""

from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Workspace path (auto-detected if omitted)")


def execute(args, workspace):
    """Scan workspace for binary/compiled artifacts with RE analysis."""
    from utils import scan_binary_artifacts
    result = scan_binary_artifacts(workspace)

    # Add Tauri-specific analysis if Tauri is detected
    try:
        from utils import scan_tauri_artifacts
        tauri_result = scan_tauri_artifacts(workspace)
        if tauri_result:
            result["tauri_analysis"] = tauri_result
    except ImportError:
        # scan_tauri_artifacts not available — skip Tauri analysis
        pass

    return result


register_command(
    "binary-scan",
    "Scan for binary/compiled artifacts with Tauri/Electron RE analysis",
    add_args,
    execute
)
