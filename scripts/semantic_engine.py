"""
Semantic Rules Engine for CodeLens — Taint analysis for vulnerability detection.

.. deprecated:: 8.3 (issue #49 Phase 1)
    This regex-based engine is deprecated. Use ``ast_taint_engine`` (default,
    AST-based with tree-sitter) or ``ast_taint_engine.analyze_workspace(
    cross_file=True)`` for cross-file analysis. The AST engine provides
    strictly better coverage with fewer false positives.

    Deprecation path:
    - v8.3 (now): deprecation warning printed to stderr on every use
    - v8.4: ``taint --no-ast`` will use ``ast_taint_engine`` with regex
      fallback mode (no tree-sitter) instead of this module
    - v9.0: this module will be removed entirely

Design Goals:
- Track data flow from sources (user input) to sinks (dangerous operations)
- Verify if sanitizers exist in the taint path
- Support YAML-defined rules for extensibility
- Inter-procedural analysis within a single file
- Confidence levels based on path certainty

Confidence Levels:
- high: Direct source to sink with no sanitizer (definite finding)
- medium: Indirect source to sink through variable assignment
- low: Possible source to sink but path uncertain
"""

import os
import re
import sys
import warnings
import yaml
from typing import Any, Dict, List, Optional, Set, Tuple

from utils import logger


# Issue #49 Phase 1: emit a one-time deprecation warning when this module
# is used for analysis. We use a module-level flag so the warning prints
# at most once per process, not once per call.
_SEMANTIC_ENGINE_DEPRECATION_WARNED = False


def _emit_deprecation_warning() -> None:
    """Print a deprecation warning to stderr (once per process)."""
    global _SEMANTIC_ENGINE_DEPRECATION_WARNED
    if _SEMANTIC_ENGINE_DEPRECATION_WARNED:
        return
    _SEMANTIC_ENGINE_DEPRECATION_WARNED = True
    msg = (
        "[codelens] WARNING: semantic_engine (regex-based taint analysis) is "
        "deprecated (issue #49 Phase 1). Use ast_taint_engine (default) or "
        "ast_taint_engine.analyze_workspace(cross_file=True) for cross-file "
        "analysis. This module will be removed in v9.0."
    )
    print(msg, file=sys.stderr)
    warnings.warn(
        "semantic_engine is deprecated; use ast_taint_engine instead.",
        DeprecationWarning,
        stacklevel=2,
    )


# ─── Rule Loading ────────────────────────────────────────────

def load_rules(rules_dir: str = None) -> List[Dict[str, Any]]:
    """Load all YAML rule files from the rules directory."""
    if rules_dir is None:
        rules_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")

    rules = []
    if not os.path.isdir(rules_dir):
        return rules

    for fname in sorted(os.listdir(rules_dir)):
        if not fname.endswith(('.yaml', '.yml')):
            continue
        fpath = os.path.join(rules_dir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict) and 'rules' in data:
                for rule in data['rules']:
                    # Normalize: accept both 'rule:' and 'id:' keys
                    if 'rule' in rule and 'id' not in rule:
                        rule['id'] = rule.pop('rule')
                    # Normalize: accept both 'name:' from id if missing
                    if 'name' not in rule:
                        rule['name'] = rule.get('id', 'Unknown').split('/')[-1].replace('_', ' ').replace('-', ' ').title()
                    rule['_source_file'] = fname
                    rules.append(rule)
            elif isinstance(data, list):
                # Legacy format: top-level list of rules with 'rule:' key
                for rule in data:
                    if isinstance(rule, dict):
                        if 'rule' in rule and 'id' not in rule:
                            rule['id'] = rule.pop('rule')
                        if 'name' not in rule:
                            rule['name'] = rule.get('id', 'Unknown').split('/')[-1].replace('_', ' ').replace('-', ' ').title()
                        rule['_source_file'] = fname
                        rules.append(rule)
        except Exception as e:
            logger.warning(f"Failed to load rule file {fname}: {e}")

    return rules


def filter_rules_by_language(rules: List[Dict], language: str) -> List[Dict]:
    """Filter rules that apply to a specific language."""
    return [r for r in rules if r.get('language', '').lower() == language.lower()]


# ─── Taint Analysis Engine ───────────────────────────────────

class TaintAnalyzer:
    """Per-file taint analysis engine.

    .. deprecated:: 8.3 (issue #49 Phase 1)
        Use ``ast_taint_engine.ASTTaintAnalyzer`` instead.

    Builds a simple control flow graph from Python/JS source,
    then tracks tainted data from sources through assignments
    and function calls to sinks.
    """

    def __init__(self, rules: List[Dict], language: str = "python"):
        _emit_deprecation_warning()
        self.rules = filter_rules_by_language(rules, language)
        self.language = language
        self.findings: List[Dict] = []

    def analyze_file(self, file_path: str) -> List[Dict]:
        """Analyze a single source file for taint vulnerabilities."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                source = f.read()
        except (IOError, OSError) as e:
            logger.warning(f"Cannot read {file_path}: {e}")
            return []

        if self.language == "python":
            return self._analyze_python(file_path, source)
        elif self.language in ("javascript", "typescript"):
            return self._analyze_javascript(file_path, source)
        return []

    def _analyze_python(self, file_path: str, source: str) -> List[Dict]:
        """Python-specific taint analysis."""
        findings = []
        lines = source.split('\n')

        # Build variable taint map: variable_name -> taint_source
        tainted_vars: Dict[str, str] = {}
        # Track sanitization: variable_name -> sanitizer_name
        sanitized_vars: Set[str] = set()

        for rule in self.rules:
            sources = rule.get('sources', [])
            sinks = rule.get('sinks', [])
            sanitizers = rule.get('sanitizers', [])

            # Phase 1: Identify tainted variables from sources
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()

                # Skip comments
                if stripped.startswith('#'):
                    continue

                # Detect source assignments: var = request.args.get(...)
                for source in sources:
                    source_parts = source.split('.')
                    source_name = source_parts[-1] if source_parts else source

                    # Direct source usage in assignment
                    assign_match = re.match(
                        r'(\w+)\s*=\s*.*' + re.escape(source) + r'.*',
                        stripped
                    )
                    if assign_match:
                        var_name = assign_match.group(1)
                        tainted_vars[var_name] = source
                        continue

                    # Check if source appears directly
                    if source in stripped or source_name in stripped:
                        # Find the variable being assigned
                        assign_match2 = re.match(r'(\w+)\s*=\s*', stripped)
                        if assign_match2:
                            tainted_vars[assign_match2.group(1)] = source

                # Detect sanitization
                for sanitizer in sanitizers:
                    san_name = sanitizer.split('.')[-1] if '.' in sanitizer else sanitizer
                    if san_name in stripped:
                        # The variable being sanitized
                        assign_match = re.match(r'(\w+)\s*=\s*.*' + re.escape(san_name) + r'.*', stripped)
                        if assign_match:
                            sanitized_vars.add(assign_match.group(1))

            # Phase 2: Check if tainted data reaches sinks
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('#'):
                    continue

                for sink in sinks:
                    sink_name = sink.split('.')[-1] if '.' in sink else sink

                    # Check if sink is called with tainted data
                    if sink in stripped or (sink_name + '(') in stripped:
                        # Check which tainted variables are in this line
                        for var_name, source_name in tainted_vars.items():
                            if var_name in stripped and var_name not in sanitized_vars:
                                # Tainted data reaches sink — NOT sanitized
                                findings.append({
                                    "rule_id": rule.get('id', 'unknown'),
                                    "rule_name": rule.get('name', 'Unknown'),
                                    "severity": rule.get('severity', 'medium'),
                                    "cwe": rule.get('cwe', ''),
                                    "message": rule.get('message', ''),
                                    "file": file_path,
                                    "line": line_no,
                                    "source": source_name,
                                    "sink": sink_name,
                                    "tainted_variable": var_name,
                                    "sanitized": False,
                                    "sanitizers_found": [],
                                    "confidence": "high",
                                    "taint_path": f"{source_name} → {var_name} → {sink_name}",
                                })
                            elif var_name in stripped and var_name in sanitized_vars:
                                # Sanitized but still worth noting
                                findings.append({
                                    "rule_id": rule.get('id', 'unknown'),
                                    "rule_name": rule.get('name', 'Unknown'),
                                    "severity": "info",
                                    "cwe": rule.get('cwe', ''),
                                    "message": f"Tainted data reaches {sink_name} but appears sanitized",
                                    "file": file_path,
                                    "line": line_no,
                                    "source": source_name,
                                    "sink": sink_name,
                                    "tainted_variable": var_name,
                                    "sanitized": True,
                                    "sanitizers_found": [],
                                    "confidence": "low",
                                    "taint_path": f"{source_name} → {var_name} → [sanitized] → {sink_name}",
                                })

        # Deduplicate findings
        seen = set()
        unique_findings = []
        for f in findings:
            key = (f['file'], f['line'], f['rule_id'])
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        return unique_findings

    def _analyze_javascript(self, file_path: str, source: str) -> List[Dict]:
        """JavaScript/TypeScript-specific taint analysis."""
        findings = []
        lines = source.split('\n')

        tainted_vars: Dict[str, str] = {}
        sanitized_vars: Set[str] = set()

        for rule in self.rules:
            sources = rule.get('sources', [])
            sinks = rule.get('sinks', [])
            sanitizers = rule.get('sanitizers', [])

            # Phase 1: Identify tainted variables
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('//') or stripped.startswith('*'):
                    continue

                for source in sources:
                    source_name = source.split('.')[-1] if '.' in source else source
                    if source in stripped or source_name in stripped:
                        # const/let/var assignment
                        assign_match = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*.*' + re.escape(source) + r'.*', stripped)
                        if assign_match:
                            tainted_vars[assign_match.group(1)] = source
                        else:
                            # Object property assignment
                            prop_match = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*.*' + re.escape(source_name) + r'.*', stripped)
                            if prop_match:
                                tainted_vars[prop_match.group(1)] = source

                # Detect sanitization
                for sanitizer in sanitizers:
                    san_name = sanitizer.split('.')[-1] if '.' in sanitizer else sanitizer
                    if san_name in stripped:
                        assign_match = re.match(r'(?:const|let|var)\s+(\w+)\s*=\s*.*' + re.escape(san_name) + r'.*', stripped)
                        if assign_match:
                            sanitized_vars.add(assign_match.group(1))

            # Phase 2: Check sinks
            for line_no, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith('//') or stripped.startswith('*'):
                    continue

                for sink in sinks:
                    sink_name = sink.split('.')[-1] if '.' in sink else sink

                    if sink in stripped or (sink_name + '(') in stripped or (sink_name + ' =') in stripped:
                        for var_name, source_name in tainted_vars.items():
                            if var_name in stripped and var_name not in sanitized_vars:
                                findings.append({
                                    "rule_id": rule.get('id', 'unknown'),
                                    "rule_name": rule.get('name', 'Unknown'),
                                    "severity": rule.get('severity', 'medium'),
                                    "cwe": rule.get('cwe', ''),
                                    "message": rule.get('message', ''),
                                    "file": file_path,
                                    "line": line_no,
                                    "source": source_name,
                                    "sink": sink_name,
                                    "tainted_variable": var_name,
                                    "sanitized": False,
                                    "sanitizers_found": [],
                                    "confidence": "high",
                                    "taint_path": f"{source_name} → {var_name} → {sink_name}",
                                })

        # Deduplicate
        seen = set()
        unique = []
        for f in findings:
            key = (f['file'], f['line'], f['rule_id'])
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return unique


# ─── Workspace-Level Analysis ────────────────────────────────

def analyze_workspace(workspace: str, language: str = None) -> Dict[str, Any]:
    """Run taint analysis across an entire workspace.

    .. deprecated:: 8.3 (issue #49 Phase 1)
        Use ``ast_taint_engine.analyze_workspace()`` instead.
    """
    _emit_deprecation_warning()
    rules = load_rules()
    if not rules:
        return {
            "status": "ok",
            "total_findings": 0,
            "findings": [],
            "stats": {"rules_loaded": 0},
            "hint": "No security rules found in scripts/rules/. Add YAML rule files.",
        }

    # Determine languages to analyze
    languages = [language] if language else _detect_languages(workspace)
    all_findings = []
    files_analyzed = 0

    for lang in languages:
        lang_rules = filter_rules_by_language(rules, lang)
        if not lang_rules:
            continue

        analyzer = TaintAnalyzer(rules, language=lang)
        source_files = _find_source_files(workspace, lang)

        for fpath in source_files:
            findings = analyzer.analyze_file(fpath)
            all_findings.extend(findings)
            files_analyzed += 1

    # Compute stats
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    by_rule = {}
    for f in all_findings:
        sev = f.get("severity", "medium")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        rule_name = f.get("rule_name", "unknown")
        by_rule[rule_name] = by_rule.get(rule_name, 0) + 1

    # Sort by severity
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    all_findings.sort(key=lambda f: severity_order.get(f.get("severity", "medium"), 99))

    risk = "critical" if by_severity.get("critical", 0) > 0 else \
           "high" if by_severity.get("high", 0) > 0 else \
           "medium" if by_severity.get("medium", 0) > 0 else "low"

    return {
        "status": "ok",
        "risk": risk,
        "total_findings": len(all_findings),
        "findings": all_findings,
        "stats": {
            "files_analyzed": files_analyzed,
            "rules_loaded": len(rules),
            "languages_analyzed": languages,
            "by_severity": by_severity,
            "by_rule": by_rule,
        },
        "recommendations": _generate_recommendations(all_findings),
    }


def _detect_languages(workspace: str) -> List[str]:
    """Detect programming languages present in the workspace."""
    lang_markers = {
        "python": {'.py', 'requirements.txt', 'pyproject.toml', 'setup.py'},
        "javascript": {'.js', '.mjs', '.cjs', 'package.json'},
        "typescript": {'.ts', '.tsx', 'tsconfig.json'},
    }
    found = []
    for lang, markers in lang_markers.items():
        for root, dirs, files in os.walk(workspace):
            # Skip hidden dirs
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if any(f.endswith(ext) or f == marker for ext, marker in
                       zip([m if m.startswith('.') else '' for m in markers], markers)):
                    found.append(lang)
                    break
            if lang in found:
                break
    return found if found else ["python"]


def _find_source_files(workspace: str, language: str) -> List[str]:
    """Find all source files of a given language in the workspace."""
    ext_map = {
        "python": {'.py', '.pyi'},
        "javascript": {'.js', '.mjs', '.cjs'},
        "typescript": {'.ts', '.tsx'},
    }
    extensions = ext_map.get(language, {'.py'})
    source_files = []

    for root, dirs, files in os.walk(workspace):
        # Skip hidden dirs, node_modules, __pycache__, .codelens
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in
                   ('node_modules', '__pycache__', '.codelens', 'venv', '.venv', 'env')]
        for f in files:
            if any(f.endswith(ext) for ext in extensions):
                source_files.append(os.path.join(root, f))

    return source_files


def _generate_recommendations(findings: List[Dict]) -> List[str]:
    """Generate actionable recommendations from findings."""
    if not findings:
        return ["No taint vulnerabilities detected."]

    recs = []
    critical = [f for f in findings if f.get("severity") == "critical"]
    if critical:
        recs.append(f"URGENT: {len(critical)} critical vulnerabilities found — fix immediately")
        for c in critical[:3]:
            recs.append(f"  → {c['rule_name']}: {c['taint_path']} in {os.path.basename(c['file'])}:{c['line']}")

    high = [f for f in findings if f.get("severity") == "high"]
    if high:
        recs.append(f"HIGH: {len(high)} high-severity issues — review and fix soon")

    unsanitized = [f for f in findings if not f.get("sanitized")]
    if unsanitized:
        recs.append(f"{len(unsanitized)} unsanitized taint paths — add input validation/sanitization")

    return recs[:10]
