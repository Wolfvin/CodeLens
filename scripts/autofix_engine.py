"""
Auto-Fix Engine for CodeLens — Intelligent code remediation with confidence scoring.

Design Goals:
- Provide automated fixes for common issues (secrets masking, dead-code removal,
  debug-leak cleanup, import optimization)
- Every fix has a confidence score (0-1) and a risk assessment
- Supports dry-run mode (show what would be changed without modifying files)
- Generates unified diff output for review
- Tracks fix history for audit trail

Fix Categories:
1. secrets_mask   — Replace hardcoded secrets with env variable references
2. dead_code      — Remove or comment out unreachable/unused code
3. debug_leak     — Remove console.log, print(), debugger statements
4. import_cleanup — Remove unused imports
5. todo_fixme     — Convert TODO/FIXME to structured issue references

Confidence Levels:
- 0.95+ : Mechanical fix (e.g., removing a console.log line)
- 0.80+ : High-confidence structural fix (e.g., removing unreachable code after return)
- 0.60+ : Moderate confidence (e.g., masking a potential secret)
- 0.40+ : Low confidence, requires human review (e.g., removing unused variable)

Risk Assessment:
- safe:       No side effects, change is reversible
- moderate:   Change affects logic but is well-understood
- risky:      Change could affect runtime behavior
- dangerous:  Change requires manual verification
"""

import os
import re
import difflib
import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple, Set
from utils import logger, safe_read_file


# ─── Confidence & Risk Constants ─────────────────────────────

RISK_SAFE = "safe"
RISK_MODERATE = "moderate"
RISK_RISKY = "risky"
RISK_DANGEROUS = "dangerous"

# Category → default confidence/risk mapping
CATEGORY_DEFAULTS = {
    "secrets_mask":   {"confidence": 0.70, "risk": RISK_MODERATE},
    "dead_code":      {"confidence": 0.85, "risk": RISK_SAFE},
    "debug_leak":     {"confidence": 0.95, "risk": RISK_SAFE},
    "import_cleanup": {"confidence": 0.80, "risk": RISK_MODERATE},
    "todo_fixme":     {"confidence": 0.60, "risk": RISK_RISKY},
}


# ─── Individual Fix Handlers ────────────────────────────────

class FixHandler:
    """Base class for fix handlers."""

    category: str = ""

    def can_fix(self, finding: Dict) -> bool:
        """Check if this handler can fix the given finding."""
        return True

    def generate_fix(self, finding: Dict, file_content: str, file_lines: List[str]) -> Optional[Dict]:
        """Generate a fix for the given finding.

        Returns:
            Dict with: replacement_lines, confidence, risk, description
            or None if no fix can be generated.
        """
        raise NotImplementedError

    def apply_fix(self, finding: Dict, file_lines: List[str], fix: Dict) -> List[str]:
        """Apply the fix to the file lines and return the modified lines."""
        line_idx = finding.get("line", 0) - 1
        if line_idx < 0 or line_idx >= len(file_lines):
            return file_lines

        replacement = fix.get("replacement_lines")
        if replacement is None:
            # Delete the line
            file_lines[line_idx] = ""
            # Also remove the trailing newline if it was the only content
            if file_lines[line_idx] == "" and line_idx > 0:
                # Mark for removal
                file_lines[line_idx] = None
        else:
            file_lines[line_idx] = replacement

        return file_lines


class SecretsMaskHandler(FixHandler):
    """Mask hardcoded secrets by replacing them with environment variable references."""

    category = "secrets_mask"

    def can_fix(self, finding: Dict) -> bool:
        return finding.get("category", "") in ("api_key", "token", "secret_key",
                                                  "password", "private_key",
                                                  "connection_string", "webhook")

    def generate_fix(self, finding: Dict, file_content: str, file_lines: List[str]) -> Optional[Dict]:
        line_idx = finding.get("line", 0) - 1
        if line_idx < 0 or line_idx >= len(file_lines):
            return None

        line = file_lines[line_idx]
        match_str = finding.get("match", "")
        if not match_str:
            return None

        # Extract the variable name and secret pattern
        # Pattern: VAR_NAME = "sk_live_..." or const API_KEY = "ghp_..."
        assign_match = re.match(
            r'^(\s*)(\w[\w.-]*)\s*[=:]\s*["\'](.+?)["\']',
            line
        )
        if not assign_match:
            # Try object property: key: "value"
            assign_match = re.match(
                r'^(\s*)(\w[\w.-]*)\s*:\s*["\'](.+?)["\']',
                line
            )

        if assign_match:
            indent = assign_match.group(1)
            var_name = assign_match.group(2)
            secret_val = assign_match.group(3)

            # Determine the env var name (UPPER_SNAKE_CASE)
            env_name = re.sub(r'[^a-zA-Z0-9]', '_', var_name).upper()
            if not env_name.endswith('_KEY') and not env_name.endswith('_SECRET') and \
               not env_name.endswith('_TOKEN') and not env_name.endswith('_URL'):
                env_name += '_SECRET'

            # Detect the language/assignment style
            if ': ' in line and '=' not in line:
                # JS/TS object property or Python keyword arg
                if line.strip().startswith(('const ', 'let ', 'var ')):
                    replacement = f'{indent}{var_name} = process.env.{env_name};'
                else:
                    replacement = f'{indent}{var_name}: process.env.{env_name},'
            else:
                # Python or JS assignment
                ext = finding.get("file", "").rsplit('.', 1)[-1] if '.' in finding.get("file", "") else "py"
                if ext in ('py',):
                    replacement = f'{indent}{var_name} = os.environ.get("{env_name}", "")'
                elif ext in ('js', 'ts', 'mjs', 'cjs', 'jsx', 'tsx'):
                    replacement = f'{indent}{var_name} = process.env.{env_name};'
                elif ext in ('rs',):
                    replacement = f'{indent}{var_name} = std::env::var("{env_name}").unwrap_or_default();'
                elif ext in ('go',):
                    replacement = f'{indent}{var_name} = os.Getenv("{env_name}")'
                else:
                    replacement = f'{indent}{var_name} = os.environ.get("{env_name}", "")'

            return {
                "replacement_lines": replacement,
                "confidence": 0.75,
                "risk": RISK_MODERATE,
                "description": f"Replace hardcoded {finding.get('category', 'secret')} with env var {env_name}",
                "env_var": env_name,
            }

        return None


class DebugLeakHandler(FixHandler):
    """Remove debug statements (console.log, print, debugger, etc.)."""

    category = "debug_leak"

    def can_fix(self, finding: Dict) -> bool:
        return finding.get("category", "") in (
            "console_log", "print_statement", "debugger",
            "pdb", "breakpoint"
        )

    def generate_fix(self, finding: Dict, file_content: str, file_lines: List[str]) -> Optional[Dict]:
        line_idx = finding.get("line", 0) - 1
        if line_idx < 0 or line_idx >= len(file_lines):
            return None

        line = file_lines[line_idx]
        stripped = line.strip()

        # Only auto-fix simple single-line debug statements
        categories = finding.get("category", "")
        if categories == "console_log":
            # Check it's a simple console.log (not in a catch block)
            if "catch" in file_lines[max(0, line_idx - 3):line_idx]:
                return None  # Don't remove console.error in catch blocks
            return {"replacement_lines": None, "confidence": 0.95, "risk": RISK_SAFE, "description": f"Remove debug statement: {stripped[:60]}"}
        elif categories == "print_statement":
            # Don't remove print in __main__ blocks
            if '__main__' in ''.join(file_lines[max(0, line_idx - 10):line_idx]):
                return None
            return {"replacement_lines": None, "confidence": 0.90, "risk": RISK_SAFE, "description": f"Remove print statement: {stripped[:60]}"}
        elif categories in ("debugger", "pdb", "breakpoint"):
            return {"replacement_lines": None, "confidence": 0.98, "risk": RISK_SAFE, "description": f"Remove debugger statement: {stripped[:60]}"}

        return None


class DeadCodeHandler(FixHandler):
    """Remove or comment out dead/unreachable code."""

    category = "dead_code"

    def can_fix(self, finding: Dict) -> bool:
        return finding.get("category", "") in (
            "unreachable", "unused_variable", "unused_import", "zombie_css"
        )

    def generate_fix(self, finding: Dict, file_content: str, file_lines: List[str]) -> Optional[Dict]:
        line_idx = finding.get("line", 0) - 1
        if line_idx < 0 or line_idx >= len(file_lines):
            return None

        cat = finding.get("category", "")

        if cat == "unreachable":
            # Code after return/throw/break — safe to remove
            # Find the extent of unreachable code (until next dedent or end of block)
            indent = len(file_lines[line_idx]) - len(file_lines[line_idx].lstrip())
            end_idx = line_idx + 1
            while end_idx < len(file_lines):
                next_line = file_lines[end_idx]
                if next_line.strip() == "":
                    end_idx += 1
                    continue
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent <= indent and next_line.strip():
                    break
                end_idx += 1

            return {
                "replacement_lines": None,  # Delete lines
                "line_range": (line_idx, end_idx),
                "confidence": 0.90,
                "risk": RISK_SAFE,
                "description": f"Remove unreachable code (lines {line_idx + 1}-{end_idx})",
            }

        elif cat == "unused_variable":
            # Comment out unused variable rather than deleting
            line = file_lines[line_idx]
            indent = len(line) - len(line.lstrip())
            comment_prefix = "// " if finding.get("file", "").endswith(('.js', '.ts', '.tsx', '.jsx', '.rs', '.go')) else "# "
            replacement = " " * indent + comment_prefix + line.strip() + "  # UNUSED"
            return {
                "replacement_lines": replacement,
                "confidence": 0.80,
                "risk": RISK_MODERATE,
                "description": f"Comment out unused variable: {line.strip()[:50]}",
            }

        elif cat == "unused_import":
            # Remove unused import line
            return {
                "replacement_lines": None,
                "confidence": 0.85,
                "risk": RISK_MODERATE,
                "description": f"Remove unused import: {file_lines[line_idx].strip()[:60]}",
            }

        return None


class ImportCleanupHandler(FixHandler):
    """Remove unused imports."""

    category = "import_cleanup"

    def can_fix(self, finding: Dict) -> bool:
        return finding.get("category", "") in ("unused_import",)

    def generate_fix(self, finding: Dict, file_content: str, file_lines: List[str]) -> Optional[Dict]:
        line_idx = finding.get("line", 0) - 1
        if line_idx < 0 or line_idx >= len(file_lines):
            return None

        return {"replacement_lines": None, "confidence": 0.85, "risk": RISK_MODERATE, "description": f"Remove unused import on line {line_idx + 1}"}


# ─── Auto-Fix Engine ────────────────────────────────────────

class AutoFixEngine:
    """Main auto-fix engine that orchestrates finding analysis and fix generation.

    Usage:
        engine = AutoFixEngine(workspace)
        plan = engine.create_fix_plan(findings, categories=["secrets_mask", "debug_leak"])
        engine.execute_plan(plan, dry_run=True)  # Show what would change
        engine.execute_plan(plan, dry_run=False)  # Apply changes
    """

    HANDLERS = {
        "secrets_mask": SecretsMaskHandler(),
        "debug_leak": DebugLeakHandler(),
        "dead_code": DeadCodeHandler(),
        "import_cleanup": ImportCleanupHandler(),
    }

    def __init__(self, workspace: str, min_confidence: float = 0.5,
                 max_risk: str = RISK_RISKY):
        self.workspace = os.path.abspath(workspace)
        self.min_confidence = min_confidence
        self.max_risk = max_risk
        self.fix_history: List[Dict] = []
        self._risk_order = {RISK_SAFE: 0, RISK_MODERATE: 1, RISK_RISKY: 2, RISK_DANGEROUS: 3}

    def create_fix_plan(self, findings: List[Dict],
                        categories: Optional[List[str]] = None,
                        max_fixes: int = 50) -> Dict[str, Any]:
        """Create a fix plan from a list of findings.

        Args:
            findings: List of finding dicts from CodeLens engines
            categories: Filter to specific fix categories (None = all)
            max_fixes: Maximum number of fixes to plan

        Returns:
            Fix plan dict with file_groups, stats, and individual fix entries
        """
        if categories is None:
            categories = list(self.HANDLERS.keys())

        fixes = []
        skipped = []
        file_contents: Dict[str, Tuple[str, List[str]]] = {}

        for finding in findings:
            # Determine which handler applies
            handler = None
            fix_category = None

            for cat in categories:
                h = self.HANDLERS.get(cat)
                if h and h.can_fix(finding):
                    handler = h
                    fix_category = cat
                    break

            if not handler:
                skipped.append({
                    "finding": finding,
                    "reason": "no_handler",
                })
                continue

            # Load file content if needed
            file_path = finding.get("file", "")
            if not file_path:
                skipped.append({
                    "finding": finding,
                    "reason": "no_file",
                })
                continue

            abs_path = os.path.join(self.workspace, file_path) if not os.path.isabs(file_path) else file_path
            if abs_path not in file_contents:
                content = safe_read_file(abs_path)
                if content is None:
                    skipped.append({
                        "finding": finding,
                        "reason": "file_not_readable",
                    })
                    continue
                file_contents[abs_path] = (content, content.split('\n'))

            content, lines = file_contents[abs_path]

            # Generate the fix
            try:
                fix = handler.generate_fix(finding, content, lines)
            except Exception as e:
                logger.warning(f"Fix generation failed for {finding}: {e}")
                skipped.append({
                    "finding": finding,
                    "reason": f"generation_error: {e}",
                })
                continue

            if fix is None:
                skipped.append({
                    "finding": finding,
                    "reason": "no_fix_possible",
                })
                continue

            # Check confidence threshold
            confidence = fix.get("confidence", 0)
            if confidence < self.min_confidence:
                skipped.append({
                    "finding": finding,
                    "reason": f"low_confidence: {confidence:.2f} < {self.min_confidence}",
                })
                continue

            # Check risk threshold
            risk = fix.get("risk", RISK_DANGEROUS)
            if self._risk_order.get(risk, 3) > self._risk_order.get(self.max_risk, 3):
                skipped.append({
                    "finding": finding,
                    "reason": f"high_risk: {risk} > {self.max_risk}",
                })
                continue

            fixes.append({
                "category": fix_category,
                "file": abs_path,
                "rel_path": file_path,
                "line": finding.get("line", 0),
                "confidence": confidence,
                "risk": risk,
                "description": fix.get("description", ""),
                "replacement_lines": fix.get("replacement_lines"),
                "line_range": fix.get("line_range"),
                "original_line": lines[finding.get("line", 0) - 1].rstrip() if finding.get("line", 0) > 0 else "",
                "finding": finding,
                "_fix_data": fix,
            })

        # Sort by confidence (highest first) and risk (lowest first)
        fixes.sort(key=lambda f: (-f["confidence"], self._risk_order.get(f["risk"], 3)))

        # Cap at max_fixes
        if len(fixes) > max_fixes:
            skipped.extend([{"finding": f["finding"], "reason": "max_fixes_reached"} for f in fixes[max_fixes:]])
            fixes = fixes[:max_fixes]

        # Group by file
        file_groups: Dict[str, List[Dict]] = {}
        for fix in fixes:
            fp = fix["file"]
            if fp not in file_groups:
                file_groups[fp] = []
            file_groups[fp].append(fix)

        # Compute stats
        by_category = {}
        by_risk = {}
        confidence_sum = 0
        for fix in fixes:
            by_category[fix["category"]] = by_category.get(fix["category"], 0) + 1
            by_risk[fix["risk"]] = by_risk.get(fix["risk"], 0) + 1
            confidence_sum += fix["confidence"]

        return {
            "status": "ok",
            "total_fixes": len(fixes),
            "total_skipped": len(skipped),
            "files_affected": len(file_groups),
            "avg_confidence": round(confidence_sum / len(fixes), 3) if fixes else 0,
            "by_category": by_category,
            "by_risk": by_risk,
            "file_groups": {fp: len(fxs) for fp, fxs in file_groups.items()},
            "fixes": fixes,
            "skipped": skipped[:20],  # Cap skipped list
        }

    def execute_plan(self, plan: Dict, dry_run: bool = True) -> Dict[str, Any]:
        """Execute a fix plan.

        Args:
            plan: Fix plan from create_fix_plan()
            dry_run: If True, only show what would change (no file modifications)

        Returns:
            Execution result with diffs, files modified, and audit trail
        """
        if plan.get("status") != "ok":
            return plan

        fixes = plan.get("fixes", [])
        results = []
        files_modified = set()
        total_lines_changed = 0

        # Group fixes by file for efficient processing
        file_fixes: Dict[str, List[Dict]] = {}
        for fix in fixes:
            fp = fix["file"]
            if fp not in file_fixes:
                file_fixes[fp] = []
            file_fixes[fp].append(fix)

        for file_path, file_fix_list in file_fixes.items():
            # Read original content
            original_content = safe_read_file(file_path)
            if original_content is None:
                for fix in file_fix_list:
                    results.append({
                        "file": file_path,
                        "line": fix["line"],
                        "status": "error",
                        "error": "file_not_readable",
                    })
                continue

            original_lines = original_content.split('\n')
            modified_lines = list(original_lines)

            # Sort fixes by line number (descending) so we modify from bottom up
            # This prevents line number shifts from affecting other fixes
            file_fix_list.sort(key=lambda f: f.get("line_range", (f["line"], f["line"]))[0]
                               if f.get("line_range") else f["line"], reverse=True)

            lines_changed_in_file = 0

            for fix in file_fix_list:
                line_range = fix.get("line_range")
                replacement = fix.get("replacement_lines")

                if line_range:
                    # Multi-line fix (e.g., unreachable code block)
                    start, end = line_range
                    if replacement is None:
                        # Delete lines (replace with empty)
                        for i in range(start, end):
                            modified_lines[i] = None  # Mark for removal
                        lines_changed_in_file += end - start
                    else:
                        modified_lines[start] = replacement
                        for i in range(start + 1, end):
                            modified_lines[i] = None
                        lines_changed_in_file += end - start
                else:
                    # Single-line fix
                    line_idx = fix["line"] - 1
                    if 0 <= line_idx < len(modified_lines):
                        if replacement is None:
                            modified_lines[line_idx] = None  # Mark for removal
                        else:
                            modified_lines[line_idx] = replacement
                        lines_changed_in_file += 1

                results.append({
                    "file": file_path,
                    "rel_path": fix.get("rel_path", ""),
                    "line": fix["line"],
                    "category": fix["category"],
                    "confidence": fix["confidence"],
                    "risk": fix["risk"],
                    "description": fix["description"],
                    "original": fix.get("original_line", ""),
                    "status": "dry_run" if dry_run else "applied",
                })

            # Remove None lines (deleted lines)
            final_lines = [line for line in modified_lines if line is not None]
            final_content = '\n'.join(final_lines)

            # Generate unified diff
            diff = list(difflib.unified_diff(
                original_lines,
                final_lines,
                fromfile=f"a/{os.path.relpath(file_path, self.workspace)}",
                tofile=f"b/{os.path.relpath(file_path, self.workspace)}",
                lineterm='',
            ))

            total_lines_changed += lines_changed_in_file

            if not dry_run:
                # Write the modified file
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(final_content)
                    files_modified.add(file_path)
                except (IOError, OSError) as e:
                    logger.warning(f"Failed to write {file_path}: {e}")
                    for r in results:
                        if r["file"] == file_path:
                            r["status"] = "error"
                            r["error"] = str(e)

            # Record in fix history
            self.fix_history.append({
                "timestamp": time.time(),
                "file": file_path,
                "lines_changed": lines_changed_in_file,
                "dry_run": dry_run,
                "fixes": [f["description"] for f in file_fix_list],
                "diff": diff[:100],  # Cap diff size
            })

        return {
            "status": "ok",
            "dry_run": dry_run,
            "files_modified": len(files_modified) if not dry_run else 0,
            "files_would_modify": len(file_fixes),
            "total_lines_changed": total_lines_changed,
            "results": results,
            "fixes_applied": sum(1 for r in results if r["status"] == ("dry_run" if dry_run else "applied")),
            "fixes_failed": sum(1 for r in results if r["status"] == "error"),
        }

    def generate_diff_summary(self, plan: Dict) -> str:
        """Generate a human-readable diff summary for a fix plan."""
        lines = []
        lines.append(f"Auto-Fix Plan: {plan['total_fixes']} fixes across {plan['files_affected']} files")
        lines.append(f"Average confidence: {plan['avg_confidence']:.1%}")
        lines.append("")

        for cat, count in plan.get("by_category", {}).items():
            lines.append(f"  {cat}: {count} fixes")

        lines.append("")
        for risk, count in plan.get("by_risk", {}).items():
            lines.append(f"  Risk [{risk}]: {count} fixes")

        lines.append("")
        lines.append("Proposed changes:")
        for fix in plan.get("fixes", [])[:30]:
            lines.append(f"  [{fix['category']}] {fix['rel_path']}:{fix['line']} "
                         f"(confidence: {fix['confidence']:.0%}, risk: {fix['risk']})")
            lines.append(f"    {fix['description']}")

        return '\n'.join(lines)


def run_autofix(workspace: str, categories: Optional[List[str]] = None,
                min_confidence: float = 0.5, max_risk: str = RISK_RISKY,
                dry_run: bool = True, max_fixes: int = 50,
                findings: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Convenience function to run the auto-fix engine.

    If findings are not provided, the engine will run the relevant CodeLens
    commands to gather findings automatically.
    """
    engine = AutoFixEngine(workspace, min_confidence=min_confidence, max_risk=max_risk)

    if findings is None:
        # Auto-gather findings from relevant engines
        findings = _gather_findings(workspace, categories)

    plan = engine.create_fix_plan(findings, categories=categories, max_fixes=max_fixes)

    if plan["total_fixes"] == 0:
        return {
            "status": "ok",
            "message": "No fixable issues found",
            "total_findings_scanned": len(findings),
            "total_fixes": 0,
        }

    execution = engine.execute_plan(plan, dry_run=dry_run)

    return {
        "status": "ok",
        "dry_run": dry_run,
        "total_findings_scanned": len(findings),
        "plan": {
            "total_fixes": plan["total_fixes"],
            "files_affected": plan["files_affected"],
            "avg_confidence": plan["avg_confidence"],
            "by_category": plan["by_category"],
            "by_risk": plan["by_risk"],
        },
        "execution": execution,
        "diff_summary": engine.generate_diff_summary(plan),
    }


def _gather_findings(workspace: str, categories: Optional[List[str]] = None) -> List[Dict]:
    """Gather findings from CodeLens engines for auto-fix."""
    findings = []

    if categories is None:
        categories = list(AutoFixEngine.HANDLERS.keys())

    # Import engine modules
    for cat in categories:
        try:
            if cat in ("secrets_mask",):
                from secrets_engine import detect_secrets
                result = detect_secrets(workspace)
                for f in result.get("findings", []):
                    f["_fix_category"] = cat
                    findings.append(f)

            elif cat in ("debug_leak",):
                from debugleak_engine import detect_debug_leaks
                result = detect_debug_leaks(workspace)
                # Flatten by_category
                by_cat = result.get("by_category", {})
                for category_name, items in by_cat.items():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                item["category"] = category_name
                                item["_fix_category"] = cat
                                findings.append(item)

            elif cat in ("dead_code", "import_cleanup"):
                from deadcode_engine import detect_dead_code
                result = detect_dead_code(workspace)
                by_cat = result.get("by_category", {})
                for category_name, items in by_cat.items():
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                item["category"] = category_name
                                item["_fix_category"] = cat if category_name != "unused_import" else "import_cleanup"
                                findings.append(item)

        except Exception as e:
            logger.warning(f"Failed to gather findings for {cat}: {e}")

    return findings
