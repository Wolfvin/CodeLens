"""CodeLens check command — CI/CD quality gate that exits non-zero on failure."""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from commands import register_command


def add_args(parser):
    parser.add_argument('--severity', choices=['critical', 'high', 'medium', 'low'],
                        default='high',
                        help='Minimum severity to fail the gate (default: high)')
    parser.add_argument('--max-findings', type=int, default=0,
                        help='Maximum allowed findings (0 = no limit, default: 0)')
    parser.add_argument('--health-min', type=int, default=0,
                        help='Minimum health score to pass (0-100, default: 0)')
    parser.add_argument('--sarif', action='store_true', default=False,
                        help='Also output SARIF format for GitHub Advanced Security')
    parser.add_argument('--commands', nargs='+',
                        default=['secrets', 'dead-code', 'smell', 'complexity', 'debug-leak', 'circular', 'taint'],
                        help='Commands to run for the quality gate (default: core analysis)')


def execute(args, workspace):
    """Execute quality gate check.

    Returns a dict with the gate result. The CLI wrapper in codelens.py
    will exit with code 1 if the gate fails.
    """
    import json
    from smell_engine import detect_smells
    from complexity_engine import compute_complexity
    from deadcode_engine import detect_dead_code
    from secrets_engine import detect_secrets
    from debugleak_engine import detect_debug_leaks
    from circular_engine import detect_circular

    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
    min_sev = severity_order.get(args.severity, 1)

    all_findings = []
    health_score = 100
    command_results = {}
    errors = []

    for command in args.commands:
        try:
            if command == 'smell':
                result = detect_smells(workspace)
                health_score = result.get('health_score', 100)
                findings = result.get('by_category', {})
                for cat, items in findings.items():
                    if isinstance(items, list):
                        for item in items:
                            item['severity'] = 'medium'
                            all_findings.append(item)

            elif command == 'complexity':
                result = compute_complexity(workspace)
                for fn in result.get('high_complexity', []):
                    fn['severity'] = 'high'
                    all_findings.append(fn)
                for fn in result.get('medium_complexity', []):
                    fn['severity'] = 'medium'
                    all_findings.append(fn)

            elif command == 'dead-code':
                result = detect_dead_code(workspace)
                by_cat = result.get('by_category', {})
                for cat, items in by_cat.items():
                    if isinstance(items, list):
                        for item in items:
                            item['severity'] = 'medium'
                            item['category'] = cat
                            all_findings.append(item)

            elif command == 'secrets':
                result = detect_secrets(workspace)
                for finding in result.get('findings', []):
                    all_findings.append(finding)

            elif command == 'debug-leak':
                result = detect_debug_leaks(workspace)
                by_cat = result.get('by_category', {})
                for cat, items in by_cat.items():
                    if isinstance(items, list):
                        for item in items:
                            item['severity'] = 'low'
                            item['category'] = cat
                            all_findings.append(item)

            elif command == 'circular':
                result = detect_circular(workspace)
                for cycle in result.get('cycles', []):
                    cycle['severity'] = 'medium'
                    all_findings.append(cycle)

            elif command == 'taint':
                try:
                    from crossfile_taint_engine import analyze_cross_file_taint
                    result = analyze_cross_file_taint(workspace)
                    for finding in result.get('findings', []):
                        all_findings.append(finding)
                except Exception as e:
                    import logging
                    logging.getLogger("codelens").warning(f"Taint analysis failed: {e}")

            command_results[command] = "ok"

        except Exception as e:
            command_results[command] = f"error: {e}"
            errors.append(f"{command}: {e}")

    # Filter findings by severity threshold
    relevant_findings = [
        f for f in all_findings
        if severity_order.get(f.get('severity', 'medium'), 2) <= min_sev
    ]

    # Count by severity
    by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
    for f in relevant_findings:
        sev = f.get('severity', 'medium')
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # Determine gate result
    gate_passed = True
    fail_reasons = []

    # Check severity threshold
    if by_severity.get('critical', 0) > 0:
        gate_passed = False
        fail_reasons.append(f"{by_severity['critical']} critical issues found")
    if min_sev <= 1 and by_severity.get('high', 0) > 0:
        gate_passed = False
        fail_reasons.append(f"{by_severity['high']} high-severity issues found")
    if min_sev <= 2 and by_severity.get('medium', 0) > 0 and args.severity == 'medium':
        gate_passed = False
        fail_reasons.append(f"{by_severity['medium']} medium-severity issues found")

    # Check max-findings
    if args.max_findings > 0 and len(relevant_findings) > args.max_findings:
        gate_passed = False
        fail_reasons.append(f"{len(relevant_findings)} findings exceed limit of {args.max_findings}")

    # Check health score
    if args.health_min > 0 and health_score < args.health_min:
        gate_passed = False
        fail_reasons.append(f"Health score {health_score} below minimum {args.health_min}")

    # Generate SARIF if requested
    sarif_output = None
    if args.sarif:
        from formatters.sarif import to_sarif
        sarif_data = to_sarif(
            {"findings": relevant_findings},
            command="check",
            workspace=workspace
        )
        sarif_output = sarif_data

    result = {
        "status": "ok",
        "gate": "passed" if gate_passed else "failed",
        "exit_code": 0 if gate_passed else 1,
        "health_score": health_score,
        "total_findings": len(all_findings),
        "relevant_findings": len(relevant_findings),
        "by_severity": by_severity,
        "commands_run": command_results,
        "fail_reasons": fail_reasons,
        "errors": errors[:5],
    }

    if sarif_output is not None:
        result["sarif"] = sarif_output

    return result


register_command(
    'check',
    'CI/CD quality gate — exits non-zero on failure (use with --severity and --max-findings)',
    add_args,
    execute,
)
