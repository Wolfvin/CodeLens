"""CSS-deep command — Deep CSS analysis (vars, keyframes, specificity)."""

from cssdeep_engine import analyze_css_deep
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["high", "medium", "low"], default=None,
                        help="Filter by severity")
    parser.add_argument("--category", default=None,
                        help="Filter by category (unused_vars, orphan_keyframes, specificity_wars, duplicate_props, unused_media, z_index_abuse)")


def execute(args, workspace):
    return analyze_css_deep(workspace, severity=args.severity, category=args.category)


register_command("css-deep", "Deep CSS analysis (vars, keyframes, specificity)", add_args, execute)
