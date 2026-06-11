"""Config-drift command — Detect dependency drift (package.json vs code)."""

from configdrift_engine import detect_config_drift
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")


def execute(args, workspace):
    return detect_config_drift(workspace)


register_command("config-drift", "Detect dependency drift (package.json vs code)", add_args, execute)
