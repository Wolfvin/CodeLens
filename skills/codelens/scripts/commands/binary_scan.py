"""Binary artifact scan command for CodeLens."""

from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Workspace path (auto-detected if omitted)")


def execute(args, workspace):
    """Scan workspace for binary/compiled artifacts."""
    from utils import scan_binary_artifacts
    return scan_binary_artifacts(workspace)


register_command(
    "binary-scan",
    "Scan for binary/compiled artifacts (executables, libraries, build outputs)",
    add_args,
    execute
)
