"""CodeLens check command — CI/CD quality gate that exits non-zero on failure."""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from commands import register_command


def add_args(parser):
    parser.add_argument("workspace", nargs="?", default=None,
                        help="Path to workspace root (auto-detected if omitted)")
    parser.add_argument('--severity', choices=['critical', 'high', 'medium', 'low'],
                        default='high',
                        help='Minimum severity to fail the gate (default: high)')
    parser.add_argument('--max-findings', type=int, default=0,
                        help='Maximum allowed findings (0 = no limit, default: 0)')
    parser.add_argument('--health-min', type=int, default=0,
                        help='Minimum health score to pass (0-100, default: 0)')
    parser.add_argument('--sarif', action='store_true', default=False,
                        help='Also embed SARIF in JSON output (prefer --format sarif for CI/CD)')
    parser.add_argument('--commands', nargs='+',
                        default=['secrets', 'dead-code', 'smell', 'complexity', 'debug-leak', 'circular', 'taint'],
                        help='Commands to run for the quality gate (default: core analysis)')
    # Issue #46: Semgrep-compatible YAML rule engine — additive flag.
    # When supplied, the rule engine runs over the workspace and any
    # findings above --severity are added to the gate's finding list.
    parser.add_argument('--rule-file', dest='rule_files',
                        action='append', default=None,
                        metavar='<path.yaml>',
                        help='Path to a Semgrep-compatible YAML rule file '
                             '(issue #46). May be passed multiple times. '
                             'Additive — rule findings are merged into the '
                             'quality-gate result.')

    # ── Issue #57 Phase 1: baseline + diff scan ──────────────────
    parser.add_argument('--baseline-commit', dest='baseline_commit',
                        default=None, metavar='<SHA>',
                        help='Compare findings against a baseline captured at '
                             '<SHA>. Only NEW findings (not in baseline) will '
                             'fail the gate. The baseline is loaded from '
                             '.codelens/baseline_<SHA>.json if it exists. If '
                             'no baseline file exists yet, all findings are '
                             'treated as new (first run). Combine with '
                             '--save-baseline to capture one. (issue #57)')
    parser.add_argument('--save-baseline', action='store_true', default=False,
                        help='After running the gate, persist the current '
                             'findings as the baseline for --baseline-commit. '
                             'Writes .codelens/baseline_<SHA>.json. Useful for '
                             'the "main" branch run that subsequent PR runs '
                             'diff against. (issue #57)')
    parser.add_argument('--diff-scan', action='store_true', default=False,
                        help='Restrict the scan to files with uncommitted '
                             'changes (working tree vs HEAD). Useful for '
                             'pre-commit hooks and local iteration. '
                             '(issue #57)')
    parser.add_argument('--staged', action='store_true', default=False,
                        help='Restrict the scan to staged files '
                             '(git diff --cached). Implies --diff-scan mode. '
                             '(issue #57)')
    parser.add_argument('--diff-vs', dest='diff_vs', default=None,
                        metavar='<ref>',
                        help='Restrict the scan to files changed vs <ref> '
                             '(branch, tag, or SHA). Example: --diff-vs '
                             'origin/main. (issue #57)')

    # ── Issue #57 Phase 2: strict mode + thresholds ──────────────
    # The three flags below are mutually exclusive via dest= — the
    # last one passed wins. In practice the CLI parser accepts any
    # combination and exit_policy.evaluate_exit_policy() applies the
    # documented priority (severity_threshold > strict > error).
    parser.add_argument('--strict', action='store_true', default=False,
                        help='Exit non-zero on ANY finding (severity >= low). '
                             'Equivalent to --severity-threshold low. '
                             '(issue #57)')
    parser.add_argument('--error', action='store_true', default=False,
                        help='Exit non-zero if any finding has severity >= '
                             'high. Equivalent to --severity-threshold high. '
                             'Overrides the legacy --severity flag for the '
                             'exit-code decision (the finding filter still '
                             'uses --severity). (issue #57)')
    parser.add_argument('--severity-threshold', dest='severity_threshold',
                        default=None,
                        choices=['critical', 'high', 'medium', 'low', 'info'],
                        help='Exit non-zero if any finding has severity >= '
                             '<level>. Explicit form of --strict/--error. '
                             '(issue #57)')


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

    # Issue #46: merge Semgrep-compat rule-engine findings into the gate.
    # Rule severities (CRITICAL/HIGH/MEDIUM/LOW/INFO/ERROR/WARNING/HINT)
    # are normalized to the gate's severity vocabulary before filtering.
    rule_findings_count = 0
    rule_files = getattr(args, 'rule_files', None)
    if rule_files:
        try:
            from rule_engine import run_rules_against_file
            import os
            sev_map = {
                'CRITICAL': 'critical', 'HIGH': 'high',
                'MEDIUM': 'medium', 'LOW': 'low', 'INFO': 'info',
                'ERROR': 'critical', 'WARNING': 'high',
                'HINT': 'low',
            }
            py_exts = {".py", ".pyw", ".pyi"}
            for dirpath, _dirs, files in os.walk(workspace):
                for name in files:
                    if os.path.splitext(name)[1].lower() not in py_exts:
                        continue
                    file_path = os.path.join(dirpath, name)
                    rr = run_rules_against_file(file_path, rule_files)
                    if rr.error:
                        errors.append(f"rule-engine: {rr.error}")
                        continue
                    for m in rr.matches:
                        gate_sev = sev_map.get(m.severity.upper(), 'medium')
                        if severity_order.get(gate_sev, 2) <= min_sev:
                            relevant_findings.append({
                                'severity': gate_sev,
                                'rule_id': m.rule_id,
                                'message': m.message,
                                'file': file_path,
                                'line': m.range.start_point[0] + 1,
                                'column': m.range.start_point[1] + 1,
                                'category': 'rule-engine',
                                'metavariables': m.metavariables,
                            })
                            rule_findings_count += 1
        except ImportError as exc:
            errors.append(f"rule-engine unavailable: {exc}")

    # Count by severity
    by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
    for f in relevant_findings:
        sev = f.get('severity', 'medium')
        by_severity[sev] = by_severity.get(sev, 0) + 1

    # ── Issue #57 Phase 1: diff-scan filtering ───────────────────
    # If the user asked for --staged / --diff-scan / --diff-vs, narrow
    # the finding list to files git knows changed. This is a separate
    # step from the severity filter above so the reported
    # ``total_findings`` still reflects the full scan, while
    # ``relevant_findings`` reflects the diff-filtered set used for the
    # gate decision.
    diff_info = None
    diff_active = (
        getattr(args, 'staged', False)
        or getattr(args, 'diff_scan', False)
        or bool(getattr(args, 'diff_vs', None))
    )
    if diff_active:
        try:
            from git_integration import (
                list_staged_files,
                list_working_tree_changes,
                list_diff_vs,
            )
        except ImportError:
            list_staged_files = list_working_tree_changes = list_diff_vs = None  # type: ignore

        changed_files = []
        diff_mode = None
        if list_staged_files is not None:
            if getattr(args, 'staged', False):
                changed_files = list_staged_files(workspace)
                diff_mode = 'staged'
            elif getattr(args, 'diff_vs', None):
                changed_files = list_diff_vs(workspace, args.diff_vs)
                diff_mode = f'diff-vs:{args.diff_vs}'
            elif getattr(args, 'diff_scan', False):
                changed_files = list_working_tree_changes(workspace)
                diff_mode = 'working-tree'

        try:
            from baseline_diff import filter_to_changed_files
            diff_filtered = filter_to_changed_files(
                relevant_findings, changed_files, workspace,
            )
        except ImportError:
            diff_filtered = relevant_findings

        diff_info = {
            'mode': diff_mode,
            'changed_files_count': len(changed_files),
            'findings_before_filter': len(relevant_findings),
            'findings_after_filter': len(diff_filtered),
        }
        # Replace the gate's relevant set with the diff-filtered set.
        relevant_findings = diff_filtered
        # Recount by_severity for the filtered set.
        by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
        for f in relevant_findings:
            sev = f.get('severity', 'medium')
            by_severity[sev] = by_severity.get(sev, 0) + 1

    # ── Issue #57 Phase 1: baseline diff ────────────────────────
    # If --baseline-commit is set, load the baseline and split findings
    # into new vs preexisting. The gate decision is then based on NEW
    # findings only (preexisting ones are surfaced in the output but
    # don't fail the gate).
    baseline_info = None
    baseline_commit_arg = getattr(args, 'baseline_commit', None)
    if baseline_commit_arg:
        try:
            from git_integration import resolve_baseline_sha
            from baseline_diff import (
                load_baseline,
                save_baseline,
                diff_findings,
            )
        except ImportError as exc:
            errors.append(f"baseline_diff unavailable: {exc}")
            resolved_sha = None
            load_baseline = save_baseline = diff_findings = None  # type: ignore
        else:
            resolved_sha = resolve_baseline_sha(workspace, baseline_commit_arg)

        if resolved_sha and load_baseline is not None:
            baseline_data = load_baseline(workspace, resolved_sha)
            baseline_findings = (
                baseline_data.get('findings', []) if baseline_data else []
            )
            if diff_findings is not None:
                delta = diff_findings(relevant_findings, baseline_findings)
                baseline_info = {
                    'baseline_sha': resolved_sha,
                    'baseline_loaded': baseline_data is not None,
                    'baseline_total': len(baseline_findings),
                    'new_findings_count': len(delta['new_findings']),
                    'preexisting_findings_count': len(delta['preexisting_findings']),
                    'resolved_findings_count': len(delta['resolved_findings']),
                    'delta_per_severity': delta['delta_per_severity'],
                    'summary': delta['summary'],
                }
                # The gate now operates on NEW findings only.
                relevant_findings = delta['new_findings']
                # Recount by_severity for the new-findings-only set.
                by_severity = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
                for f in relevant_findings:
                    sev = f.get('severity', 'medium')
                    by_severity[sev] = by_severity.get(sev, 0) + 1
        else:
            baseline_info = {
                'baseline_sha': resolved_sha,
                'baseline_loaded': False,
                'note': 'baseline SHA could not be resolved or baseline_diff module unavailable',
            }

    # ── Issue #57 Phase 2: exit policy ──────────────────────────
    # If any of the Phase 2 strict-mode flags were passed, delegate
    # the gate decision to exit_policy.evaluate_exit_policy(). This is
    # additive — when none of the new flags are set, the legacy
    # --severity / --max-findings / --health-min logic below runs
    # unchanged (backward-compat for existing CI configs).
    phase2_active = (
        getattr(args, 'strict', False)
        or getattr(args, 'error', False)
        or bool(getattr(args, 'severity_threshold', None))
    )

    gate_passed = True
    fail_reasons = []
    exit_decision = None

    if phase2_active:
        try:
            from exit_policy import evaluate_exit_policy
        except ImportError as exc:
            errors.append(f"exit_policy unavailable: {exc}")
            evaluate_exit_policy = None  # type: ignore

        if evaluate_exit_policy is not None:
            exit_decision = evaluate_exit_policy(
                relevant_findings,
                strict=getattr(args, 'strict', False),
                error=getattr(args, 'error', False),
                severity_threshold=getattr(args, 'severity_threshold', None),
                max_findings=getattr(args, 'max_findings', 0),
            )
            gate_passed = not exit_decision.should_fail
            fail_reasons = list(exit_decision.reasons)

    if not phase2_active:
        # Legacy gate logic — preserved verbatim for backward compat.
        if by_severity.get('critical', 0) > 0:
            gate_passed = False
            fail_reasons.append(f"{by_severity['critical']} critical issues found")
        if min_sev <= 1 and by_severity.get('high', 0) > 0:
            gate_passed = False
            fail_reasons.append(f"{by_severity['high']} high-severity issues found")
        if min_sev <= 2 and by_severity.get('medium', 0) > 0 and args.severity == 'medium':
            gate_passed = False
            fail_reasons.append(f"{by_severity['medium']} medium-severity issues found")

        # Check max-findings (legacy path — exit_policy handles it
        # when phase2_active is True)
        if args.max_findings > 0 and len(relevant_findings) > args.max_findings:
            gate_passed = False
            fail_reasons.append(f"{len(relevant_findings)} findings exceed limit of {args.max_findings}")

    # Check health-score minimum (applies in both modes — orthogonal
    # to finding-count gates).
    if args.health_min > 0 and health_score < args.health_min:
        gate_passed = False
        fail_reasons.append(f"Health score {health_score} below minimum {args.health_min}")

    # ── Issue #57 Phase 1: --save-baseline ──────────────────────
    # Persist the current findings (AFTER severity filter but BEFORE
    # baseline diffing — we want the baseline to contain ALL findings
    # so a future run's "new" set is meaningful).
    save_baseline_info = None
    if getattr(args, 'save_baseline', False):
        try:
            from git_integration import resolve_baseline_sha as _resolve
            from baseline_diff import save_baseline as _save
        except ImportError:
            _resolve = _save = None  # type: ignore
        if _resolve is not None and _save is not None:
            sha_to_save = _resolve(workspace, baseline_commit_arg)
            if sha_to_save:
                # Strip the _identity / _severity internal fields before
                # saving so the baseline file is clean JSON.
                clean_findings = [
                    {k: v for k, v in f.items() if not k.startswith('_')}
                    for f in relevant_findings
                ]
                path = _save(workspace, sha_to_save, clean_findings)
                save_baseline_info = {
                    'saved': True,
                    'baseline_sha': sha_to_save,
                    'path': path,
                    'finding_count': len(clean_findings),
                }
            else:
                save_baseline_info = {
                    'saved': False,
                    'reason': 'could not resolve a baseline SHA (pass --baseline-commit or set $CODELENS_BASELINE_SHA)',
                }

    # Generate SARIF if requested
    sarif_output = None
    if args.sarif:
        from formatters.sarif import to_sarif
        sarif_data = to_sarif(
            {"findings": relevant_findings},
            command="check",
            workspace=workspace,
            automation_guid=getattr(args, 'baseline_commit', None),
        )
        sarif_output = sarif_data

    result = {
        "status": "ok",
        "gate": "passed" if gate_passed else "failed",
        "exit_code": 0 if gate_passed else 1,
        "health_score": health_score,
        "total_findings": len(all_findings),
        "relevant_findings": len(relevant_findings),
        "rule_findings": rule_findings_count,
        "findings": relevant_findings,
        "by_severity": by_severity,
        "commands_run": command_results,
        "fail_reasons": fail_reasons,
        "errors": errors[:5],
    }

    if diff_info is not None:
        result["diff"] = diff_info
    if baseline_info is not None:
        result["baseline"] = baseline_info
    if exit_decision is not None:
        result["exit_policy"] = {
            "severity_threshold": exit_decision.severity_threshold,
            "max_findings": exit_decision.max_findings,
            "relevant_count": exit_decision.relevant_count,
        }
    if save_baseline_info is not None:
        result["save_baseline"] = save_baseline_info
    if sarif_output is not None:
        result["sarif"] = sarif_output

    return result


register_command(
    'check',
    'CI/CD quality gate — exits non-zero on failure (use with --severity, '
    '--strict/--error, --baseline-commit, --diff-scan)',
    add_args,
    execute,
)
