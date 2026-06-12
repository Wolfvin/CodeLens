"""Perf-hint command — Detect performance anti-patterns."""

from perfhint_engine import detect_perf_hints
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity")
    parser.add_argument("--category", default=None,
                        help="Filter by category (n_plus_one, sync_blocking, memory_leak, expensive_renders, large_bundle, inefficient_iteration, unoptimized_images, cache_miss)")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000)")


def execute(args, workspace):
    return detect_perf_hints(workspace, severity=args.severity, category=args.category,
                             max_files=args.max_files)


register_command("perf-hint", "Detect performance anti-patterns", add_args, execute)
