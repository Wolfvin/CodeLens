"""CodeLens fix command — Auto-fix issues with confidence scoring."""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from commands import register_command


def add_args(parser):
    parser.add_argument('--categories', nargs='+',
                        choices=['secrets_mask', 'dead_code', 'debug_leak', 'import_cleanup', 'todo_fixme'],
                        default=None,
                        help='Fix categories to apply (default: all)')
    parser.add_argument('--dry-run', action='store_true', default=True,
                        help='Show what would be changed without modifying files (default)')
    parser.add_argument('--apply', dest='dry_run', action='store_false',
                        help='Actually apply the fixes')
    parser.add_argument('--min-confidence', type=float, default=0.5,
                        help='Minimum confidence threshold (0-1, default: 0.5)')
    parser.add_argument('--max-risk', choices=['safe', 'moderate', 'risky', 'dangerous'],
                        default='risky',
                        help='Maximum risk level to apply (default: risky)')
    parser.add_argument('--max-fixes', type=int, default=50,
                        help='Maximum number of fixes to apply (default: 50)')


def execute(args, workspace):
    from autofix_engine import run_autofix, RISK_SAFE, RISK_MODERATE, RISK_RISKY, RISK_DANGEROUS

    risk_map = {
        'safe': RISK_SAFE,
        'moderate': RISK_MODERATE,
        'risky': RISK_RISKY,
        'dangerous': RISK_DANGEROUS,
    }

    result = run_autofix(
        workspace=workspace,
        categories=args.categories,
        min_confidence=args.min_confidence,
        max_risk=risk_map.get(args.max_risk, RISK_RISKY),
        dry_run=args.dry_run,
        max_fixes=args.max_fixes,
    )

    return result


register_command(
    'fix',
    'Auto-fix issues with confidence scoring (dry-run by default)',
    add_args,
    execute,
)
