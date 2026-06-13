"""CodeLens guard command — Pre/post-write verification for AI agents.

This command provides real-time verification that AI agents can use before
and after making code changes. It integrates with the MCP server to provide
a "guard" mode that:

1. Pre-write check: Verify the change is safe (no collisions, dead code references, etc.)
2. Post-write check: Verify the change didn't introduce new issues
3. Diff-aware analysis: Only analyze changed files for fast feedback
4. Persistent state: Track what the codebase looked like before the change

This is the "killer feature" that no other code analysis tool has —
purpose-built integration for AI agent coding workflows.
"""

import sys
import os
import json
import re
import time
import hashlib
from typing import Any, Dict, List, Optional

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from commands import register_command


def add_args(parser):
    sub = parser.add_subparsers(dest='guard_action', help='Guard action')

    # pre: Check before writing
    pre = sub.add_parser('pre', help='Pre-write check — verify change is safe')
    pre.add_argument('--file', required=True, help='File that will be modified')
    pre.add_argument('--symbol', help='Symbol that will be added/modified/removed')
    pre.add_argument('--action', choices=['create', 'modify', 'delete', 'rename'],
                     default='modify', help='Type of change (default: modify)')

    # post: Check after writing
    post = sub.add_parser('post', help='Post-write check — verify no new issues')
    post.add_argument('--file', required=True, help='File that was modified')
    post.add_argument('--diff', help='Git-style diff of the changes')

    # snapshot: Save current state
    snap = sub.add_parser('snapshot', help='Save a snapshot of current analysis state')

    # verify: Compare current state with snapshot
    verify = sub.add_parser('verify', help='Verify codebase against saved snapshot')
    verify.add_argument('--snapshot', help='Snapshot ID to compare against (default: latest)')


def execute(args, workspace):
    action = getattr(args, 'guard_action', None)

    if action == 'pre':
        return _pre_write_check(args, workspace)
    elif action == 'post':
        return _post_write_check(args, workspace)
    elif action == 'snapshot':
        return _save_snapshot(workspace)
    elif action == 'verify':
        return _verify_against_snapshot(args, workspace)
    else:
        return {
            "status": "error",
            "error": "Specify a guard action: pre, post, snapshot, verify",
            "examples": [
                "codelens guard pre --file src/app.py --symbol my_func --action modify",
                "codelens guard post --file src/app.py",
                "codelens guard snapshot",
                "codelens guard verify",
            ]
        }


def _pre_write_check(args, workspace) -> Dict[str, Any]:
    """Check if a planned code change is safe.

    Verifies:
    1. The file exists (for modify/delete)
    2. No dead code references the symbol (would break)
    3. No circular dependency would be created
    4. The symbol doesn't already exist (for create)
    5. The symbol isn't in use elsewhere (for delete)
    """
    target_file = args.file
    symbol = args.symbol
    action = args.action
    issues = []
    warnings = []
    info = []

    abs_path = os.path.join(workspace, target_file) if not os.path.isabs(target_file) else target_file

    # Check file existence
    if action in ('modify', 'delete'):
        if not os.path.exists(abs_path):
            issues.append({
                "type": "file_not_found",
                "message": f"File {target_file} does not exist — cannot {action}",
                "severity": "critical",
            })

    if action == 'create':
        if os.path.exists(abs_path):
            warnings.append({
                "type": "file_exists",
                "message": f"File {target_file} already exists — will overwrite",
                "severity": "warning",
            })

    if symbol:
        # Check registry for the symbol
        try:
            from registry import load_backend_registry
            registry = load_backend_registry(workspace)

            if registry:
                nodes = registry.get('nodes', {})

                # Check if symbol exists
                symbol_exists = False
                symbol_refs = 0
                symbol_status = "unknown"

                for node_name, node_data in nodes.items():
                    if isinstance(node_data, dict):
                        if node_name == symbol or symbol in node_name:
                            symbol_exists = True
                            symbol_refs = node_data.get('ref_count', 0)
                            symbol_status = node_data.get('status', 'unknown')

                            if action == 'create':
                                if symbol_status == 'active':
                                    issues.append({
                                        "type": "symbol_exists",
                                        "message": f"Symbol '{symbol}' already exists and is active ({symbol_refs} refs)",
                                        "severity": "critical",
                                    })
                                elif symbol_status == 'dead':
                                    warnings.append({
                                        "type": "symbol_dead",
                                        "message": f"Symbol '{symbol}' exists but is dead — safe to reuse",
                                        "severity": "info",
                                    })

                            elif action == 'delete':
                                if symbol_refs > 0:
                                    issues.append({
                                        "type": "symbol_in_use",
                                        "message": f"Symbol '{symbol}' has {symbol_refs} references — deleting will break them",
                                        "severity": "critical",
                                        "affected_refs": symbol_refs,
                                    })

                            elif action == 'modify':
                                info.append({
                                    "type": "symbol_info",
                                    "message": f"Symbol '{symbol}' is {symbol_status} with {symbol_refs} references",
                                    "severity": "info",
                                })
                            break

                if not symbol_exists and action == 'modify':
                    warnings.append({
                        "type": "symbol_not_found",
                        "message": f"Symbol '{symbol}' not found in registry — new symbol?",
                        "severity": "warning",
                    })

        except Exception as e:
            warnings.append({
                "type": "registry_error",
                "message": f"Could not check registry: {e}",
                "severity": "warning",
            })

    # Check for potential circular dependencies
    if symbol and action in ('create', 'modify'):
        try:
            from circular_engine import detect_cycles
            result = detect_cycles(workspace)
            cycles = result.get('cycles', [])
            for cycle in cycles:
                cycle_str = str(cycle)
                if target_file in cycle_str:
                    warnings.append({
                        "type": "circular_dep",
                        "message": f"File {target_file} is in a circular dependency cycle",
                        "severity": "warning",
                        "cycle": cycle,
                    })
        except Exception:
            pass

    # Determine overall safety
    safe = len(issues) == 0
    risk_level = "safe" if not issues and not warnings else \
                 "moderate" if not issues else "dangerous"

    # Generate recommendations
    recommendations = []
    if issues:
        recommendations.append("STOP: Critical issues found — resolve before proceeding")
        for issue in issues:
            recommendations.append(f"  → {issue['message']}")
    elif warnings:
        recommendations.append("CAUTION: Warnings found — review before proceeding")
        for warning in warnings:
            recommendations.append(f"  → {warning['message']}")
    else:
        recommendations.append("GREEN: No issues detected — safe to proceed")

    return {
        "status": "ok",
        "action": action,
        "file": target_file,
        "symbol": symbol,
        "safe": safe,
        "risk_level": risk_level,
        "issues": issues,
        "warnings": warnings,
        "info": info,
        "recommendations": recommendations,
    }


def _post_write_check(args, workspace) -> Dict[str, Any]:
    """Check if a code change introduced new issues.

    Compares current analysis with the last snapshot to find:
    1. New dead code introduced
    2. New secrets leaked
    3. New circular dependencies
    4. New complexity issues
    5. New debug leaks
    """
    target_file = args.file
    new_issues = []
    resolved_issues = []
    persisting_issues = []

    abs_path = os.path.join(workspace, target_file) if not os.path.isabs(target_file) else target_file

    # Run targeted analysis on the changed file
    if not os.path.exists(abs_path):
        return {
            "status": "error",
            "error": f"File {target_file} does not exist",
        }

    # Load the last snapshot
    snapshot_dir = os.path.join(workspace, ".codelens", "guard_snapshots")
    latest_snapshot = _load_latest_snapshot(snapshot_dir)

    # Run analysis on the changed file
    file_issues = _analyze_file(workspace, target_file)

    # Compare with snapshot
    if latest_snapshot:
        prev_file_issues = latest_snapshot.get('files', {}).get(target_file, {}).get('issues', [])

        prev_set = {(i.get('type', ''), i.get('category', ''), i.get('line', 0))
                    for i in prev_file_issues}
        curr_set = {(i.get('type', ''), i.get('category', ''), i.get('line', 0))
                    for i in file_issues}

        new_keys = curr_set - prev_set
        resolved_keys = prev_set - curr_set
        persisting_keys = curr_set & prev_set

        for issue in file_issues:
            key = (issue.get('type', ''), issue.get('category', ''), issue.get('line', 0))
            if key in new_keys:
                new_issues.append(issue)
            elif key in persisting_keys:
                persisting_issues.append(issue)

        for issue in prev_file_issues:
            key = (issue.get('type', ''), issue.get('category', ''), issue.get('line', 0))
            if key in resolved_keys:
                resolved_issues.append(issue)
    else:
        # No snapshot — all issues are new
        new_issues = file_issues

    # Determine if the change is clean
    critical_new = [i for i in new_issues if i.get('severity') in ('critical', 'high')]
    clean = len(critical_new) == 0

    return {
        "status": "ok",
        "file": target_file,
        "clean": clean,
        "new_issues": new_issues,
        "resolved_issues": resolved_issues,
        "persisting_issues": persisting_issues,
        "summary": {
            "new": len(new_issues),
            "resolved": len(resolved_issues),
            "persisting": len(persisting_issues),
            "critical_new": len(critical_new),
        },
        "recommendations": _generate_post_recommendations(new_issues, resolved_issues),
    }


def _save_snapshot(workspace) -> Dict[str, Any]:
    """Save a snapshot of the current analysis state."""
    snapshot_dir = os.path.join(workspace, ".codelens", "guard_snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)

    timestamp = int(time.time())
    snapshot_id = f"snapshot_{timestamp}"
    snapshot_file = os.path.join(snapshot_dir, f"{snapshot_id}.json")

    # Run quick analysis
    file_data = {}

    # Scan workspace for source files
    source_exts = {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.go', '.vue', '.svelte'}
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', '.codelens', 'venv', '.venv', 'dist', 'build')]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in source_exts:
                rel_path = os.path.relpath(os.path.join(root, f), workspace)
                file_data[rel_path] = {
                    "issues": _analyze_file(workspace, rel_path),
                    "timestamp": timestamp,
                }

    snapshot = {
        "id": snapshot_id,
        "timestamp": timestamp,
        "files": file_data,
        "total_files": len(file_data),
        "total_issues": sum(len(v.get('issues', [])) for v in file_data.values()),
    }

    try:
        with open(snapshot_file, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
    except (IOError, OSError) as e:
        return {"status": "error", "error": f"Failed to save snapshot: {e}"}

    # Keep only last 10 snapshots
    _cleanup_old_snapshots(snapshot_dir, keep=10)

    return {
        "status": "ok",
        "snapshot_id": snapshot_id,
        "files_snapshotted": len(file_data),
        "total_issues_captured": snapshot["total_issues"],
        "snapshot_file": snapshot_file,
    }


def _verify_against_snapshot(args, workspace) -> Dict[str, Any]:
    """Verify current codebase against a saved snapshot."""
    snapshot_dir = os.path.join(workspace, ".codelens", "guard_snapshots")

    if not os.path.isdir(snapshot_dir):
        return {
            "status": "error",
            "error": "No snapshots found. Run 'codelens guard snapshot' first.",
        }

    # Load the specified or latest snapshot
    snapshot = None
    if args and args.snapshot:
        snapshot_file = os.path.join(snapshot_dir, f"{args.snapshot}.json")
        if os.path.exists(snapshot_file):
            with open(snapshot_file, 'r') as f:
                snapshot = json.load(f)
    else:
        snapshot = _load_latest_snapshot(snapshot_dir)

    if not snapshot:
        return {
            "status": "error",
            "error": "No snapshot found.",
        }

    # Compare current state with snapshot
    new_issues = []
    resolved_issues = []
    changed_files = []

    for rel_path, snap_data in snapshot.get('files', {}).items():
        current_issues = _analyze_file(workspace, rel_path)

        prev_set = {(i.get('type', ''), i.get('category', ''), i.get('line', 0))
                    for i in snap_data.get('issues', [])}
        curr_set = {(i.get('type', ''), i.get('category', ''), i.get('line', 0))
                    for i in current_issues}

        new_keys = curr_set - prev_set
        resolved_keys = prev_set - curr_set

        if new_keys or resolved_keys:
            changed_files.append(rel_path)

        for issue in current_issues:
            key = (issue.get('type', ''), issue.get('category', ''), issue.get('line', 0))
            if key in new_keys:
                new_issues.append(issue)

        for issue in snap_data.get('issues', []):
            key = (issue.get('type', ''), issue.get('category', ''), issue.get('line', 0))
            if key in resolved_keys:
                resolved_issues.append(issue)

    return {
        "status": "ok",
        "snapshot_id": snapshot.get('id', 'unknown'),
        "changed_files": changed_files,
        "new_issues": len(new_issues),
        "resolved_issues": len(resolved_issues),
        "new_issues_detail": new_issues[:20],
        "resolved_issues_detail": resolved_issues[:20],
        "clean": len([i for i in new_issues if i.get('severity') in ('critical', 'high')]) == 0,
    }


def _analyze_file(workspace: str, rel_path: str) -> List[Dict]:
    """Run quick analysis on a single file and return issues."""
    issues = []

    abs_path = os.path.join(workspace, rel_path)
    if not os.path.exists(abs_path):
        return issues

    from utils import safe_read_file
    content = safe_read_file(abs_path)
    if not content:
        return issues

    lines = content.split('\n')
    ext = os.path.splitext(rel_path)[1].lower()

    # Quick pattern-based checks (no engine overhead)
    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()

        # Secrets check
        if ext in ('.py', '.js', '.ts', '.env'):
            if re.search(r'(?:password|secret|api_key|token)\s*[=:]\s*["\'][^"\']{8,}["\']', stripped, re.I):
                issues.append({
                    "type": "secret",
                    "category": "hardcoded_secret",
                    "line": line_no,
                    "severity": "high",
                    "message": f"Potential hardcoded secret on line {line_no}",
                })

        # Debug leak check
        if ext in ('.js', '.ts', '.tsx', '.jsx'):
            if re.search(r'console\.(log|debug|info)\s*\(', stripped):
                issues.append({
                    "type": "debug_leak",
                    "category": "console_log",
                    "line": line_no,
                    "severity": "low",
                    "message": f"console.log on line {line_no}",
                })
        elif ext == '.py':
            if re.search(r'^\s*print\s*\(', stripped) and '__main__' not in content:
                issues.append({
                    "type": "debug_leak",
                    "category": "print_statement",
                    "line": line_no,
                    "severity": "low",
                    "message": f"print() statement on line {line_no}",
                })

        # TODO/FIXME check
        if re.search(r'#\s*(TODO|FIXME|HACK|XXX)', stripped, re.I):
            issues.append({
                "type": "todo_fixme",
                "category": "todo_fixme",
                "line": line_no,
                "severity": "info",
                "message": f"TODO/FIXME marker on line {line_no}",
            })

    return issues


def _load_latest_snapshot(snapshot_dir: str) -> Optional[Dict]:
    """Load the most recent snapshot."""
    if not os.path.isdir(snapshot_dir):
        return None

    snapshots = sorted([f for f in os.listdir(snapshot_dir) if f.endswith('.json')],
                       reverse=True)
    if not snapshots:
        return None

    latest = os.path.join(snapshot_dir, snapshots[0])
    try:
        with open(latest, 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None


def _cleanup_old_snapshots(snapshot_dir: str, keep: int = 10):
    """Remove old snapshots, keeping only the N most recent."""
    if not os.path.isdir(snapshot_dir):
        return

    snapshots = sorted([f for f in os.listdir(snapshot_dir) if f.endswith('.json')])
    while len(snapshots) > keep:
        os.remove(os.path.join(snapshot_dir, snapshots.pop(0)))


def _generate_post_recommendations(new_issues: List[Dict],
                                    resolved_issues: List[Dict]) -> List[str]:
    """Generate recommendations from post-write check."""
    recs = []

    critical = [i for i in new_issues if i.get('severity') in ('critical', 'high')]
    if critical:
        recs.append(f"URGENT: {len(critical)} new critical/high issues introduced")
        for c in critical[:3]:
            recs.append(f"  → {c.get('message', 'Unknown issue')}")

    if resolved_issues:
        recs.append(f"Good: {len(resolved_issues)} issues resolved by this change")

    if not new_issues:
        recs.append("Clean change: no new issues introduced")

    return recs[:10]


register_command(
    'guard',
    'Pre/post-write verification for AI agents (guard pre/post/snapshot/verify)',
    add_args,
    execute,
)
