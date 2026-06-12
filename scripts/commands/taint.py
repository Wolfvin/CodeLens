"""Taint command — Run semantic taint analysis for vulnerability detection."""

from semantic_engine import run_semantic_analysis
from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument("--language", choices=["python", "javascript", "typescript"], default=None,
                        help="Filter analysis to a specific language")
    parser.add_argument("--max-files", type=int, default=5000,
                        help="Maximum number of files to scan (default: 5000)")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Time budget in seconds (default: 120)")
    parser.add_argument("--with-secrets", action="store_true", default=False,
                        help="Include secrets engine findings as taint sources")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"], default=None,
                        help="Filter by severity (includes higher)")


def execute(args, workspace):
    secrets_findings = None
    if getattr(args, 'with_secrets', False):
        try:
            from secrets_engine import scan_secrets
            sr = scan_secrets(workspace)
            if sr.get("status") == "ok":
                secrets_findings = sr.get("findings", [])
        except Exception:
            pass
    result = run_semantic_analysis(workspace, secrets_findings=secrets_findings,
                                  max_files=args.max_files, timeout_sec=float(args.timeout),
                                  language_filter=args.language)
    if args.severity and result.get("status") == "ok":
        so = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ms = so.get(args.severity, 3)
        result["findings"] = [f for f in result.get("findings", []) if so.get(f.get("severity", "low"), 3) <= ms]
        result["total_findings"] = len(result["findings"])
    if result.get("status") == "ok":
        crit = [f for f in result.get("findings", []) if f.get("severity") == "critical"]
        high = [f for f in result.get("findings", []) if f.get("severity") == "high"]
        result["actionable_items"] = []
        for f in crit[:5]:
            result["actionable_items"].append({"action": "FIX_IMMEDIATELY", "rule": f.get("rule", ""),
                "file": f.get("file", ""), "line": f.get("line", 0), "message": f.get("message", "")})
        for f in high[:5]:
            result["actionable_items"].append({"action": "REVIEW_AND_FIX", "rule": f.get("rule", ""),
                "file": f.get("file", ""), "line": f.get("line", 0), "message": f.get("message", "")})
    return result


register_command("taint", "Run semantic taint analysis for vulnerability detection", add_args, execute)
