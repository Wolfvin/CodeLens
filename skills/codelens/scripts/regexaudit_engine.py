"""
Regex Audit Engine for CodeLens — v3
Detects ReDoS-vulnerable regex, incorrect patterns, overly broad matches,
unsafe constructors, and performance issues in regex patterns across the codebase.

Categories:
1. redos_vulnerable    — Regex susceptible to Regular Expression Denial of Service
2. overly_broad        — Regex that matches too much (.* overuse, unbounded quantifiers)
3. incorrect_escaping  — Common escaping mistakes (unescaped dots, double-escaped chars)
4. unsafe_constructor  — new RegExp() / re.compile() with dynamic input
5. performance         — Slow regex patterns (catastrophic backtracking, greedy issues)

For each finding: {category, file, line, pattern, issue, severity, fix_suggestion}
"""

import os
import re
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Configuration ─────────────────────────────────────────────

SOURCE_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".py", ".rs", ".go", ".rb", ".vue", ".svelte",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hxx",
}

MAX_FILES_PER_RUN = 3000
MAX_RESULTS_PER_CATEGORY = 100

# ReDoS-indicating patterns (nested quantifiers, overlapping alternatives)
REDOS_PATTERNS = [
    # Nested quantifiers: (a+)+, (a*)*, (a+)*, (a*)+
    (r'\(([^)]*[\+\*][^)]*)\)[\+\*]', "nested_quantifier",
     "Nested quantifiers like (X+)+ can cause exponential backtracking"),
    # Quantified group containing quantified alternation
    (r'\((?:[^)]*\|[^)]*[\+\*])\)[\+\*]', "overlapping_alternation_quantified",
     "Quantified group with overlapping alternatives causes backtracking"),
    # Specific dangerous patterns
    (r'\(\\w\+?\)\+', "word_nested_plus",
     r"(\w+)+ pattern is a classic ReDoS vector"),
    (r'\(\\w\*?\)\*', "word_nested_star",
     r"(\w*)* pattern is a classic ReDoS vector"),
    (r'\(\.\*\)\*', "dot_star_nested",
     r"(.*)* pattern causes catastrophic backtracking"),
    (r'\(\.\+\)\*', "dot_plus_nested",
     r"(.+)* pattern causes catastrophic backtracking"),
    (r'\(\.\*\)\+', "dot_star_plus_nested",
     r"(.*)+ pattern causes catastrophic backtracking"),
    (r'\(\.\+\)\+', "dot_plus_plus_nested",
     r"(.+)+ pattern causes catastrophic backtracking"),
    (r'\([\s\S]\*?\)\*?', "any_char_nested",
     r"([\s\S]*)* pattern causes catastrophic backtracking"),
    # Overlapping alternatives: (a|a+), (a|a*b)
    (r'\((\w)\\?\|\1\+?\)', "overlapping_alternatives",
     "Overlapping alternatives (a|a+) cause ambiguous matching"),
    # Quantified backreference
    (r'\\(\d)\s*[\+\*]', "quantified_backreference",
     "Quantified backreference can cause exponential matching"),
    # \w+\w+ (consecutive overlapping quantifiers)
    (r'\\w\+\\s\*\\w\+', "consecutive_overlapping_quantifiers",
     r"\w+\s*\w+ with optional separator creates overlapping match paths"),
    # (a+)+b or similar
    (r'\([\w\\]+\+?\)[\+\*]\s*\w', "nested_quantifier_with_suffix",
     "Nested quantifier followed by literal requires backtracking to resolve"),
    # Repeated groups with overlap
    (r'\([^)]+\)[\+\*]\s*\([^)]+\)[\+\*]', "repeated_quantified_groups",
     "Multiple consecutive quantified groups create backtracking pressure"),
]

# Patterns that detect regex definitions in various languages
REGEX_DEFINITION_PATTERNS = {
    ".js": [
        (r'(?:const|let|var)\s+\w+\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
        (r'/([^/\n]+)/[gimsuy]*', "regex_literal_inline"),
    ],
    ".mjs": [
        (r'(?:const|let|var)\s+\w+\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
    ],
    ".cjs": [
        (r'(?:const|let|var)\s+\w+\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
    ],
    ".ts": [
        (r'(?:const|let|var)\s+\w+\s*(?::\s*\w+(?:<[^>]+>)?)?\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
    ],
    ".tsx": [
        (r'(?:const|let|var)\s+\w+\s*(?::\s*\w+(?:<[^>]+>)?)?\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
    ],
    ".jsx": [
        (r'(?:const|let|var)\s+\w+\s*=\s*(/[^/\n]+/[gimsuy]*)', "regex_literal"),
        (r'new\s+RegExp\s*\(\s*("([^"]*)"|\'([^\']*)\')', "regexp_constructor"),
    ],
    ".py": [
        (r're\.compile\s*\(\s*(?:r)?["\']([^"\']+)["\']', "re_compile"),
        (r're\.(?:match|search|findall|sub|split|finditer|fullmatch)\s*\(\s*(?:r)?["\']([^"\']+)["\']', "re_inline"),
        (r'(?:pattern|regex|pat)\s*=\s*(?:r)?["\']([^"\']+)["\']', "regex_variable"),
    ],
    ".rs": [
        (r'Regex::new\s*\(\s*(?:r)?["\']([^"\']+)["\']', "regex_new"),
        (r'regex!\s*\(\s*(?:r)?["\']([^"\']+)["\']', "regex_macro"),
    ],
    ".go": [
        (r'regexp\.Compile\s*\(\s*`([^`]+)`\s*\)', "regexp_compile"),
        (r'regexp\.MustCompile\s*\(\s*`([^`]+)`\s*\)', "regexp_must_compile"),
        (r'regexp\.Compile\s*\(\s*"([^"]+)"\s*\)', "regexp_compile_str"),
        (r'regexp\.MustCompile\s*\(\s*"([^"]+)"\s*\)', "regexp_must_compile_str"),
    ],
}


# ─── Main Entry Point ──────────────────────────────────────────

def audit_regex_patterns(
    workspace: str,
    severity: Optional[str] = None,
    config: Optional[Dict] = None,
    max_files: int = MAX_FILES_PER_RUN,
    max_results_per_category: int = MAX_RESULTS_PER_CATEGORY,
) -> Dict[str, Any]:
    """
    Audit regex patterns across the workspace for security and correctness issues.

    Args:
        workspace: Absolute path to workspace root
        severity: Optional severity filter ("high", "medium", "low")
        config: CodeLens configuration dict

    Returns:
        Dict with status, stats, findings, and recommendations
    """
    workspace = os.path.abspath(workspace)

    valid_severities = {"high", "medium", "low"}

    if severity and severity not in valid_severities:
        return {
            "status": "error",
            "message": f"Invalid severity '{severity}'. Valid: {sorted(valid_severities)}"
        }

    findings: List[Dict] = []
    all_patterns: List[Dict] = []  # All discovered regex patterns
    files_scanned = 0
    truncated = False
    category_counts: Dict[str, int] = defaultdict(int)

    for root, dirs, filenames in os.walk(workspace):
        if files_scanned >= max_files:
            truncated = True
            break

        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in SOURCE_EXTENSIONS:
                continue

            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)

            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except IOError:
                continue

            files_scanned += 1
            if files_scanned >= max_files:
                truncated = True

            lines = content.split('\n')

            # ─── Extract regex patterns from the file ────
            file_patterns = _extract_regex_patterns(content, lines, ext, rel_path)
            all_patterns.extend(file_patterns)

            # ─── Check for unsafe constructors ───────────
            if category_counts["unsafe_constructor"] < max_results_per_category:
                prev = len(findings)
                _check_unsafe_constructors(content, lines, ext, rel_path, findings)
                category_counts["unsafe_constructor"] += len(findings) - prev
                if category_counts["unsafe_constructor"] >= max_results_per_category:
                    truncated = True
            else:
                truncated = True

            # ─── Analyze each pattern ────────────────────
            for pat_info in file_patterns:
                pattern_str = pat_info["pattern"]

                # ReDoS vulnerability
                if category_counts["redos_vulnerable"] < max_results_per_category:
                    prev = len(findings)
                    _check_redos(pattern_str, pat_info, findings)
                    category_counts["redos_vulnerable"] += len(findings) - prev
                    if category_counts["redos_vulnerable"] >= max_results_per_category:
                        truncated = True
                else:
                    truncated = True

                # Overly broad patterns
                if category_counts["overly_broad"] < max_results_per_category:
                    prev = len(findings)
                    _check_overly_broad(pattern_str, pat_info, ext, findings)
                    category_counts["overly_broad"] += len(findings) - prev
                    if category_counts["overly_broad"] >= max_results_per_category:
                        truncated = True
                else:
                    truncated = True

                # Incorrect escaping
                if category_counts["incorrect_escaping"] < max_results_per_category:
                    prev = len(findings)
                    _check_incorrect_escaping(pattern_str, pat_info, ext, findings)
                    category_counts["incorrect_escaping"] += len(findings) - prev
                    if category_counts["incorrect_escaping"] >= max_results_per_category:
                        truncated = True
                else:
                    truncated = True

                # Performance issues
                if category_counts["performance"] < max_results_per_category:
                    prev = len(findings)
                    _check_performance(pattern_str, pat_info, findings)
                    category_counts["performance"] += len(findings) - prev
                    if category_counts["performance"] >= max_results_per_category:
                        truncated = True
                else:
                    truncated = True

    # Apply severity filter
    if severity:
        findings = [f for f in findings if f["severity"] == severity]

    # ─── Aggregate Stats ──────────────────────────────────
    by_category = defaultdict(int)
    by_severity = defaultdict(int)
    for finding in findings:
        by_category[finding["category"]] += 1
        by_severity[finding["severity"]] += 1

    vulnerable_count = by_category.get("redos_vulnerable", 0)

    # ─── Recommendations ──────────────────────────────────
    recommendations = _generate_recommendations(
        len(all_patterns), findings, dict(by_category), dict(by_severity)
    )

    return {
        "status": "ok",
        "workspace": workspace,
        "stats": {
            "total_patterns": len(all_patterns),
            "files_scanned": files_scanned,
            "truncated": truncated,
            "vulnerable": vulnerable_count,
            "by_category": dict(by_category),
            "by_severity": dict(by_severity),
        },
        "findings": findings,
        "recommendations": recommendations,
    }


# ─── Pattern Extraction ────────────────────────────────────────

def _extract_regex_patterns(
    content: str, lines: List[str], ext: str, rel_path: str
) -> List[Dict]:
    """Extract regex pattern strings from a file."""
    patterns = []

    lang_patterns = REGEX_DEFINITION_PATTERNS.get(ext, [])
    for regex_pattern, pattern_type in lang_patterns:
        for m in re.finditer(regex_pattern, content):
            # Extract the actual pattern string from the appropriate group
            pattern_str = None
            for group_idx in range(1, len(m.groups()) + 1):
                if m.group(group_idx):
                    pattern_str = m.group(group_idx)
                    break

            if not pattern_str:
                continue

            # Clean up the pattern (remove delimiters for regex literals)
            if pattern_type == "regex_literal" or pattern_type == "regex_literal_inline":
                # Remove leading / and trailing /flags
                pattern_str = re.sub(r'^/|/[gimsuy]*$', '', pattern_str)

            line_num = content[:m.start()].count('\n') + 1

            patterns.append({
                "pattern": pattern_str,
                "file": rel_path,
                "line": line_num,
                "type": pattern_type,
            })

    return patterns


# ─── ReDoS Detection ───────────────────────────────────────────

def _check_redos(pattern_str: str, pat_info: Dict, findings: List[Dict]) -> None:
    """Check a regex pattern for ReDoS vulnerabilities."""
    for redos_pattern, vuln_type, description in REDOS_PATTERNS:
        if re.search(redos_pattern, pattern_str):
            findings.append({
                "category": "redos_vulnerable",
                "file": pat_info["file"],
                "line": pat_info["line"],
                "pattern": pattern_str,
                "issue": vuln_type,
                "severity": "high",
                "fix_suggestion": _suggest_redos_fix(vuln_type, pattern_str),
            })
            return  # One ReDoS finding per pattern is enough

    # Additional heuristic checks for ReDoS
    # Check for quantified groups with overlapping content
    if _has_nested_quantifier_heuristic(pattern_str):
        findings.append({
            "category": "redos_vulnerable",
            "file": pat_info["file"],
            "line": pat_info["line"],
            "pattern": pattern_str,
            "issue": "potential_nested_quantifier",
            "severity": "medium",
            "fix_suggestion": (
                "Review this pattern for nested quantifiers. "
                "Use possessive quantifiers (++) or atomic groups (?>...) if supported, "
                "or restructure to avoid nested repetition."
            ),
        })


def _has_nested_quantifier_heuristic(pattern: str) -> bool:
    """
    Heuristic check for nested quantifiers that might cause ReDoS.
    Looks for patterns where a quantified group contains elements
    that can match the same strings as elements outside the group.
    """
    # Find all groups with quantifiers
    group_pattern = r'\(([^)]+)\)([+*?{])'
    groups = list(re.finditer(group_pattern, pattern))

    for g in groups:
        group_content = g.group(1)
        quantifier = g.group(2)

        if quantifier in ('+', '*', '{'):
            # Check if group content has quantifiers inside
            if re.search(r'[\+\*{]', group_content):
                return True

            # Check if group content can match empty string
            # (e.g., (a?)+ is dangerous)
            if re.search(r'\w\?', group_content):
                return True

    return False


def _suggest_redos_fix(vuln_type: str, pattern: str) -> str:
    """Suggest a fix for a ReDoS vulnerability."""
    fix_map = {
        "nested_quantifier": (
            "Replace nested quantifiers with a single quantifier on a character class. "
            "E.g., instead of (a+)+, use a+ or (?:a+) without the outer quantifier."
        ),
        "overlapping_alternation_quantified": (
            "Make alternatives non-overlapping or use atomic groups (?>...). "
            "E.g., instead of (a|a+)+, use a+."
        ),
        "word_nested_plus": (
            r"Replace (\w+)+ with \w+ — the inner quantifier already matches "
            r"all word characters, the outer one is redundant."
        ),
        "word_nested_star": (
            r"Replace (\w*)* with \w* — the inner quantifier already matches "
            r"all word characters, the outer one is redundant."
        ),
        "dot_star_nested": (
            r"Replace (.*)* with .* — the inner .* already matches everything, "
            r"the outer quantifier causes backtracking."
        ),
        "dot_plus_nested": (
            r"Replace (.+)* with .* — simplify to avoid backtracking."
        ),
        "dot_star_plus_nested": (
            r"Replace (.*)+ with .* — simplify to avoid backtracking."
        ),
        "dot_plus_plus_nested": (
            r"Replace (.+)+ with .+ — the outer quantifier is redundant."
        ),
        "any_char_nested": (
            "Replace [\\s\\S]* nested quantifiers with a simpler pattern. "
            "Use [^\\n]* for single-line matching or re.DOTALL flag."
        ),
        "overlapping_alternatives": (
            "Make alternatives non-overlapping. E.g., instead of (a|a+), "
            "just use a+ which covers both cases."
        ),
        "quantified_backreference": (
            "Avoid quantifying backreferences. Use a non-quantified backreference "
            "or restructure the pattern."
        ),
        "consecutive_overlapping_quantifiers": (
            "Consecutive overlapping quantifiers create ambiguous match paths. "
            "Use a character class or more specific pattern."
        ),
        "nested_quantifier_with_suffix": (
            "Pattern like (X+)+Y requires backtracking when Y doesn't match. "
            "Use possessive quantifiers or atomic groups if supported."
        ),
        "repeated_quantified_groups": (
            "Multiple consecutive quantified groups create exponential backtracking. "
            "Restructure to use more specific matching."
        ),
        "potential_nested_quantifier": (
            "Review this pattern for nested quantifiers. "
            "Use possessive quantifiers or atomic groups where possible."
        ),
    }
    return fix_map.get(vuln_type, "Review and simplify this regex pattern to avoid ReDoS.")


# ─── Overly Broad Detection ────────────────────────────────────

def _check_overly_broad(
    pattern_str: str, pat_info: Dict, ext: str, findings: List[Dict]
) -> None:
    """Check for regex patterns that match too broadly."""
    issues = []

    # .* at start or end without anchors
    if re.search(r'^\.\*', pattern_str) and not pattern_str.startswith('^'):
        issues.append({
            "issue": "unanchored_dot_star_start",
            "description": ".* at start without ^ anchor matches too much",
        })

    if re.search(r'\.\*$', pattern_str) and not pattern_str.endswith('$'):
        issues.append({
            "issue": "unanchored_dot_star_end",
            "description": ".* at end without $ anchor matches too much",
        })

    # .* in the middle (could often be replaced with more specific pattern)
    dot_star_count = len(re.findall(r'\.\*', pattern_str))
    if dot_star_count > 2:
        issues.append({
            "issue": "excessive_dot_star",
            "description": f"Pattern has {dot_star_count} .* segments — likely too broad",
        })

    # [\s\S]* instead of specific patterns
    if re.search(r'\[\\s\\S\]', pattern_str):
        issues.append({
            "issue": "match_any_char_class",
            "description": "[\\s\\S]* matches any character including newlines — "
                          "use re.DOTALL flag with . instead, or be more specific",
        })

    # Unbounded quantifiers without context
    unbounded = re.findall(r'[^+*?]\+[^+]|[^+*?]\*[^*]', pattern_str)
    if len(unbounded) > 3:
        issues.append({
            "issue": "many_unbounded_quantifiers",
            "description": f"Pattern has {len(unbounded)} unbounded quantifiers — "
                          f"consider adding upper bounds",
        })

    # .+ when a specific character class would be better
    if re.search(r'\.\+(?![*?])', pattern_str):
        # Check if it's in a simple pattern where [^\n]+ would be safer
        if not re.search(r'[\^$]', pattern_str):
            issues.append({
                "issue": "dot_plus_unanchored",
                "description": ".+ could be replaced with a more specific character class "
                              "like [^\\n]+ or [\\w]+",
            })

    for issue in issues:
        findings.append({
            "category": "overly_broad",
            "file": pat_info["file"],
            "line": pat_info["line"],
            "pattern": pattern_str,
            "issue": issue["issue"],
            "severity": "medium",
            "fix_suggestion": issue["description"],
        })


# ─── Incorrect Escaping Detection ──────────────────────────────

def _check_incorrect_escaping(
    pattern_str: str, pat_info: Dict, ext: str, findings: List[Dict]
) -> None:
    """Check for common escaping mistakes in regex patterns."""
    issues = []

    # v5.9: Skip URL-like strings that are NOT regex patterns.
    # Common false positive: strings like "gitlab.com", "example.org", "www.w3.org"
    # in CSP allowlists, test fixtures, or SVG namespaces — these are plain strings,
    # not regex patterns. We detect this by checking if the pattern lacks regex
    # metacharacters (quantifiers, anchors, groups, character classes).
    _has_regex_meta = bool(re.search(r'[+*?^$|\\[\]{}()]', pattern_str))
    if not _has_regex_meta:
        # No regex metacharacters at all — this is a plain string, not a regex.
        # Don't flag unescaped dots in plain strings.
        return

    # Unescaped dots that should match literal dots
    # Common in IP address patterns, version numbers, file extensions
    if re.search(r'\d\\\.\d', pattern_str):
        # This is actually correctly escaped — skip
        pass
    elif re.search(r'\d\.\d', pattern_str):
        # Numeric pattern with unescaped dot — likely should be \.
        issues.append({
            "issue": "unescaped_dot_in_numeric",
            "description": "Unescaped '.' in numeric context (e.g., version or IP) — "
                          "use \\. to match a literal dot",
        })

    # File extension patterns with unescaped dot
    if re.search(r'\.\w{2,4}$', pattern_str) or re.search(r'\.\w{2,4}(?:\\b|$)', pattern_str):
        # Could be matching file extensions without escaping the dot
        if not re.search(r'\\\.\w{2,4}', pattern_str):
            issues.append({
                "issue": "unescaped_dot_extension",
                "description": "Pattern matching file extension has unescaped '.' — "
                              "'.' matches any character, use '\\.' for literal dot",
            })

    # Double-escaped characters: \\d instead of \d
    if re.search(r'\\\\d', pattern_str):
        issues.append({
            "issue": "double_escaped_digit",
            "description": "Double-escaped \\d — matches literal backslash + 'd' "
                          "instead of digit character class. Use \\d for digits.",
        })

    if re.search(r'\\\\w', pattern_str):
        issues.append({
            "issue": "double_escaped_word",
            "description": "Double-escaped \\w — matches literal backslash + 'w' "
                          "instead of word character class. Use \\w for word chars.",
        })

    if re.search(r'\\\\s', pattern_str):
        issues.append({
            "issue": "double_escaped_space",
            "description": "Double-escaped \\s — matches literal backslash + 's' "
                          "instead of whitespace class. Use \\s for whitespace.",
        })

    # Unescaped special chars in character classes
    # Inside [], only ] \ ^ - need escaping
    char_classes = re.findall(r'\[([^\]]+)\]', pattern_str)
    for cc in char_classes:
        # Check for unescaped ] inside (would terminate the class early)
        if ']' in cc and not cc.endswith(']'):
            issues.append({
                "issue": "unescaped_bracket_in_class",
                "description": f"Unescaped ']' in character class [{cc}] — "
                              f"may terminate the class prematurely",
            })
            break

        # Check for unescaped - that's not at start/end
        if re.search(r'\w-\w', cc):
            # This is a range like a-z, which is fine
            pass
        elif '-' in cc and not cc.startswith('-') and not cc.endswith('-'):
            issues.append({
                "issue": "ambiguous_hyphen_in_class",
                "description": f"Ambiguous '-' in character class [{cc}] — "
                              f"place at start/end or escape it",
            })
            break

    # Unescaped ^ in the middle of a pattern (not at start, not in [])
    if re.search(r'[^\\\[]\^', pattern_str) and not pattern_str.startswith('^'):
        issues.append({
            "issue": "unescaped_caret",
            "description": "Unescaped '^' not at pattern start — "
                          "use \\^ for literal caret, or confirm it's an anchor",
        })

    # Mixing escape conventions
    if ext == ".py":
        # In raw strings, \d is correct. In non-raw strings, \\d is needed.
        if pat_info.get("type") == "re_compile" and '\\\\d' in pattern_str:
            issues.append({
                "issue": "over_escaped_in_raw_string",
                "description": "Pattern may have over-escaped \\d in a raw string — "
                              "in r\"...\", use \\d not \\\\d",
            })

    for issue in issues:
        findings.append({
            "category": "incorrect_escaping",
            "file": pat_info["file"],
            "line": pat_info["line"],
            "pattern": pattern_str,
            "issue": issue["issue"],
            "severity": "medium",
            "fix_suggestion": issue["description"],
        })


# ─── Unsafe Constructor Detection ──────────────────────────────

def _check_unsafe_constructors(
    content: str, lines: List[str], ext: str, rel_path: str, findings: List[Dict]
) -> None:
    """Detect regex construction with dynamic/user input."""
    patterns = []

    if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
        # new RegExp(variable)
        patterns.extend([
            (r'new\s+RegExp\s*\(\s*(\w+)\s*\)', "regexp_with_variable", "high"),
            (r'new\s+RegExp\s*\(\s*\w+\s*\+\s*', "regexp_concatenation", "high"),
            (r'new\s+RegExp\s*\(\s*`[^`]*\$\{', "regexp_template_literal", "high"),
            (r'new\s+RegExp\s*\(\s*[^\'"]', "regexp_non_literal", "medium"),
        ])

    elif ext == ".py":
        # re.compile with f-string or .format()
        patterns.extend([
            (r're\.compile\s*\(\s*f["\']', "re_compile_fstring", "high"),
            (r're\.compile\s*\([^)]*\.format\s*\(', "re_compile_format", "high"),
            (r're\.compile\s*\(\s*\w+\s*\)', "re_compile_variable", "medium"),
            (r're\.\w+\s*\(\s*\w+\s*,', "re_inline_variable", "medium"),
        ])

    elif ext == ".rs":
        patterns.extend([
            (r'Regex::new\s*\(\s*\w+', "regex_new_variable", "medium"),
            (r'format!\s*\([^)]*Regex', "regex_format_string", "high"),
        ])

    elif ext == ".go":
        patterns.extend([
            (r'regexp\.Compile\s*\(\s*\w+', "regexp_compile_variable", "medium"),
            (r'fmt\.Sprintf\s*\([^)]*regexp', "regexp_sprintf", "high"),
        ])

    for pattern, issue_type, severity in patterns:
        for m in re.finditer(pattern, content):
            line_num = content[:m.start()].count('\n') + 1

            fix_suggestion = (
                "Avoid constructing regex from dynamic input. If necessary, "
                "sanitize input by escaping special regex characters first: "
            )
            if ext in {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}:
                fix_suggestion += "use input.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') before passing to RegExp."
            elif ext == ".py":
                fix_suggestion += "use re.escape(input) before passing to re.compile()."
            elif ext == ".rs":
                fix_suggestion += "use regex::escape(input) before passing to Regex::new()."
            elif ext == ".go":
                fix_suggestion += "use regexp.QuoteMeta(input) before passing to Compile()."

            findings.append({
                "category": "unsafe_constructor",
                "file": rel_path,
                "line": line_num,
                "pattern": m.group(0)[:80],
                "issue": issue_type,
                "severity": severity,
                "fix_suggestion": fix_suggestion,
            })


# ─── Performance Detection ─────────────────────────────────────

def _check_performance(pattern_str: str, pat_info: Dict, findings: List[Dict]) -> None:
    """Check for regex performance issues."""
    issues = []

    # Unnecessary capturing groups (should be non-capturing (?:...))
    capturing_groups = re.findall(r'(?<!\\)\((?!\?)', pattern_str)
    non_capturing_groups = re.findall(r'\(\?:', pattern_str)
    if len(capturing_groups) > 3 and len(non_capturing_groups) == 0:
        issues.append({
            "issue": "unnecessary_capturing_groups",
            "description": (
                f"Pattern has {len(capturing_groups)} capturing groups but no non-capturing "
                f"groups (?:...). Use non-capturing groups when you don't need the captured "
                f"value — they're faster and clearer in intent."
            ),
        })

    # Greedy quantifiers that might cause issues with backtracking
    # Check for .* followed by specific patterns (common backtracking pattern)
    if re.search(r'\.\*[^+*?].+\.\*', pattern_str):
        issues.append({
            "issue": "greedy_dot_star_sequence",
            "description": (
                "Multiple .* segments with content between them cause backtracking. "
                "Consider using lazy quantifiers .*? or more specific character classes."
            ),
        })

    # Alternation with common prefix
    alternatives = re.findall(r'\(([^)]+)\)', pattern_str)
    for alt_block in alternatives:
        if '|' in alt_block:
            parts = alt_block.split('|')
            if len(parts) >= 3:
                # Check if alternatives share a common prefix
                common_prefix = os.path.commonprefix(parts)
                if len(common_prefix) >= 2:
                    issues.append({
                        "issue": "alternation_common_prefix",
                        "description": (
                            f"Alternatives in ({alt_block}) share common prefix "
                            f"'{common_prefix}' — extract it: {common_prefix}({'|'.join(p[len(common_prefix):] for p in parts)})"
                        ),
                    })
                    break

    # Extremely long patterns (hard to debug and maintain)
    if len(pattern_str) > 200:
        issues.append({
            "issue": "pattern_too_long",
            "description": (
                f"Pattern is {len(pattern_str)} characters long — consider breaking "
                f"into multiple smaller patterns or using verbose mode (re.VERBOSE)."
            ),
        })

    # Alternation with many options
    pipe_count = pattern_str.count('|')
    if pipe_count > 10:
        issues.append({
            "issue": "too_many_alternatives",
            "description": (
                f"Pattern has {pipe_count} alternatives — each must be tried during "
                f"matching. Consider restructuring or using a trie-based approach."
            ),
        })

    for issue in issues:
        findings.append({
            "category": "performance",
            "file": pat_info["file"],
            "line": pat_info["line"],
            "pattern": pattern_str[:100] + "..." if len(pattern_str) > 100 else pattern_str,
            "issue": issue["issue"],
            "severity": "low",
            "fix_suggestion": issue["description"],
        })


# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    total_patterns: int,
    findings: List[Dict],
    by_category: Dict[str, int],
    by_severity: Dict[str, int]
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    redos_count = by_category.get("redos_vulnerable", 0)
    if redos_count > 0:
        recs.append(
            f"CRITICAL: {redos_count} ReDoS-vulnerable patterns found. "
            f"These can cause denial-of-service with crafted input. Fix immediately by "
            f"removing nested quantifiers or using atomic groups."
        )

    unsafe_count = by_category.get("unsafe_constructor", 0)
    if unsafe_count > 0:
        recs.append(
            f"SECURITY: {unsafe_count} unsafe regex constructors found (dynamic input). "
            f"These are potential injection vectors. Always sanitize/escape user input "
            f"before using it in regex patterns."
        )

    broad_count = by_category.get("overly_broad", 0)
    if broad_count > 3:
        recs.append(
            f"Found {broad_count} overly broad regex patterns. Use more specific "
            f"character classes and anchors to improve both correctness and performance."
        )

    escaping_count = by_category.get("incorrect_escaping", 0)
    if escaping_count > 0:
        recs.append(
            f"Found {escaping_count} escaping issues. Incorrect escaping leads to "
            f"subtle bugs where patterns match more or less than intended. "
            f"Always test regex patterns with edge cases."
        )

    perf_count = by_category.get("performance", 0)
    if perf_count > 0:
        recs.append(
            f"Found {perf_count} performance-related regex issues. "
            f"Consider using non-capturing groups, lazy quantifiers, and "
            f"anchored patterns for better performance."
        )

    if total_patterns > 0 and not findings:
        recs.append(
            f"All {total_patterns} regex patterns look clean — no vulnerabilities "
            f"or issues detected."
        )

    if not recs:
        recs.append("No regex patterns found in the workspace.")

    # General best practice recommendations
    if total_patterns > 20:
        recs.append(
            f"Codebase has {total_patterns} regex patterns. Consider centralizing "
            f"commonly-used patterns in a shared constants file for consistency."
        )

    return recs
