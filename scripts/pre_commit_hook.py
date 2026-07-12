#!/usr/bin/env python3
"""
CodeLens pre-commit hook — Runs quality gate before allowing a commit.

Install:
  1. Copy this file to .git/hooks/pre-commit (or add to your pre-commit config)
  2. chmod +x .git/hooks/pre-commit

Configuration (.codelens/pre-commit.yaml):
  severity: high          # Minimum severity to block commit (critical, high, medium, low)
  max_findings: 10        # Maximum allowed findings before blocking
  commands:               # Commands to run
    - secrets
    - dead-code
    - debug-leak
  auto_fix: false         # Auto-fix safe issues before committing
"""

import sys
import os
import subprocess
import json

# subprocess.run(..., text=True) below also passes encoding='utf-8',
# errors='replace' — without it, Windows decodes with cp1252 (platform
# default) and crashes on git/codelens output containing non-cp1252 bytes
# (accented file/author names, non-ASCII findings text). Same class of bug
# fixed in ownership_engine.py (PR #216).

# Add scripts directory to path
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'scripts')
CODELENS = os.path.join(SCRIPT_DIR, 'codelens.py')


def main():
    workspace = os.getcwd()

    # Get list of staged files
    try:
        result = subprocess.run(
            ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=workspace
        )
        staged_files = [f.strip() for f in result.stdout.strip().split('\n') if f.strip()]
    except Exception:
        staged_files = []

    if not staged_files:
        print("[CodeLens] No staged files to check.")
        return 0

    # Filter to source files only
    source_exts = {'.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.go', '.vue', '.svelte',
                   '.css', '.scss', '.html', '.php', '.java', '.rb'}
    source_files = [f for f in staged_files if os.path.splitext(f)[1].lower() in source_exts]

    if not source_files:
        print("[CodeLens] No source files in staged changes — skipping check.")
        return 0

    print(f"[CodeLens] Checking {len(source_files)} staged source files...")

    # Load config
    config = _load_config(workspace)
    severity = config.get('severity', 'high')
    max_findings = config.get('max_findings', 10)
    commands = config.get('commands', ['secrets', 'dead-code', 'debug-leak'])

    # Run CodeLens check
    try:
        cmd = [sys.executable, CODELENS, 'check', workspace,
               '--severity', severity,
               '--max-findings', str(max_findings),
               '--commands'] + commands

        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
            cwd=workspace, timeout=120
        )

        if result.returncode != 0:
            # Gate failed
            try:
                output = json.loads(result.stdout)
                gate = output.get('gate', 'unknown')
                findings = output.get('relevant_findings', 0)
                by_severity = output.get('by_severity', {})

                print(f"\n[CodeLens] ❌ Quality gate FAILED!")
                print(f"  Gate: {gate}")
                print(f"  Findings: {findings}")
                for sev, count in by_severity.items():
                    if count > 0:
                        print(f"    {sev}: {count}")
                print(f"\n  To fix and retry:")
                print(f"    python3 scripts/codelens.py fix . --dry-run")
                print(f"    python3 scripts/codelens.py fix . --apply --max-risk safe")
                print(f"\n  To bypass (not recommended):")
                print(f"    git commit --no-verify")

            except json.JSONDecodeError:
                print(f"\n[CodeLens] ❌ Quality gate FAILED!")
                print(result.stdout[:500] if result.stdout else result.stderr[:500])

            return 1
        else:
            try:
                output = json.loads(result.stdout)
                findings = output.get('relevant_findings', 0)
                health = output.get('health_score', 100)
                print(f"[CodeLens] ✅ Quality gate passed! (findings: {findings}, health: {health})")
            except json.JSONDecodeError:
                print("[CodeLens] ✅ Quality gate passed!")

            return 0

    except subprocess.TimeoutExpired:
        print("[CodeLens] ⚠️ Quality gate timed out — allowing commit (check manually)")
        return 0
    except Exception as e:
        print(f"[CodeLens] ⚠️ Quality gate error: {e} — allowing commit")
        return 0


def _load_config(workspace):
    """Load pre-commit configuration from .codelens/pre-commit.yaml."""
    config_path = os.path.join(workspace, '.codelens', 'pre-commit.yaml')
    if os.path.exists(config_path):
        try:
            import yaml
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass
    return {}


if __name__ == '__main__':
    sys.exit(main())
