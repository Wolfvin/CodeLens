"""
Inline Suppression Detection and Application for CodeLens.

Supports cross-language inline suppression annotations:
  - ``# codelens-ignore`` (Python, Ruby, PHP, shell)
  - ``// codelens-ignore`` (JS, TS, Rust, Go, Java, C, C++)
  - ``/* codelens-ignore */`` (CSS, multi-line C-family)
  - ``<!-- codelens-ignore -->`` (HTML)

Three keyword aliases:
  - ``codelens-ignore`` (default, brandable)
  - ``nolens`` (short alias)
  - ``nosemgrep`` (Semgrep ecosystem compat)

Syntax variants:
  - ``<code>  // codelens-ignore: rule-id-1, rule-id-2 -- reason``
  - ``<code>  // codelens-ignore`` (suppress all rules on line)
  - ``/* codelens-ignore-next: rule-id */`` (suppress next line)

Suppressed findings remain in output with ``status: "suppressed"`` for auditability.
SARIF ``suppressions`` field is populated per spec.
"""

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


# ─── Default keyword pattern ────────────────────────────────────────────────

DEFAULT_KEYWORD_PATTERN = r"codelens-ignore|nolens|nosemgrep"

# All supported keywords (for documentation / validation)
SUPPORTED_KEYWORDS = ("codelens-ignore", "nolens", "nosemgrep")


# ─── SuppressionInfo Dataclass ──────────────────────────────────────────────

@dataclass
class SuppressionInfo:
    """Parsed suppression annotation information.

    Attributes:
        rule_ids: List of specific rule IDs to suppress. Empty list = suppress all.
        reason: Human-readable reason for suppression (empty string if not provided).
        is_next_line: True if this is a ``-next`` annotation that applies to the
            following line rather than the current line.
        keyword: The actual keyword used (e.g., "codelens-ignore", "nolens").
    """

    rule_ids: List[str] = field(default_factory=list)
    reason: str = ""
    is_next_line: bool = False
    keyword: str = "codelens-ignore"


# ─── Detection ──────────────────────────────────────────────────────────────

# Pre-compiled regex for performance.
# Matches: keyword[: rule1, rule2 -- reason] or keyword-next[: rule1, rule2 -- reason]
# Examples:
#   codelens-ignore
#   codelens-ignore: rule-1, rule-2 -- some reason
#   codelens-ignore-next: rule-1
#   nolens
#   nosemgrep: rule-1 -- false positive
# Step 1: Match the keyword (with optional -next suffix)
_KEYWORD_RE = re.compile(
    r"(?P<keyword>codelens-ignore|nolens|nosemgrep)(?P<next>-next)?",
    re.IGNORECASE,
)


def detect_suppression(
    comment_text: str,
    default_keyword: str = "codelens-ignore",
    keyword_pattern: str = DEFAULT_KEYWORD_PATTERN,
) -> Optional[SuppressionInfo]:
    """Detect a suppression annotation in a comment string.

    Args:
        comment_text: The raw comment text (may include comment delimiters like ``#``, ``//``).
        default_keyword: The default keyword to use in SuppressionInfo.
        keyword_pattern: Regex pattern string for custom keywords.

    Returns:
        SuppressionInfo if a suppression annotation is found, None otherwise.
    """
    if not comment_text:
        return None

    # Strip comment delimiters to get the inner text
    text = comment_text.strip()
    # Remove common comment prefixes
    text = re.sub(r"^(#+|//+|/\*+|<!--|--|;)", "", text).strip()
    # Remove trailing comment suffixes
    text = re.sub(r"(\*/|-->)\s*$", "", text).strip()

    # Check if any keyword is present using the keyword pattern
    keyword_re = re.compile(keyword_pattern, re.IGNORECASE)
    kw_match = keyword_re.search(text)
    if not kw_match:
        return None

    # Get the matched keyword
    keyword = kw_match.group(0).lower()

    # Check for -next suffix right after the keyword
    after_kw_match = text[kw_match.end():]
    is_next = after_kw_match.startswith("-next")
    if is_next:
        after_keyword = after_kw_match[5:].strip()  # Skip "-next"
    else:
        after_keyword = after_kw_match.strip()

    rule_ids: List[str] = []
    reason: str = ""

    if after_keyword:
        # Check for ":" to separate rules
        if after_keyword.startswith(":"):
            after_colon = after_keyword[1:].strip()
            # Check for "--" to separate reason
            if " -- " in after_colon:
                parts = after_colon.split(" -- ", 1)
                rules_str = parts[0].strip()
                reason = parts[1].strip()
            else:
                rules_str = after_colon
                reason = ""

            # Parse comma-separated rule IDs
            rule_ids = [r.strip() for r in rules_str.split(",") if r.strip()]
        elif after_keyword.startswith("--"):
            # Only reason, no rules
            reason = after_keyword[2:].strip()

    return SuppressionInfo(
        rule_ids=rule_ids,
        reason=reason,
        is_next_line=is_next,
        keyword=keyword,
    )


# ─── Comment Detection Per Language ─────────────────────────────────────────

# Language → comment prefixes (for fallback regex parsers)
COMMENT_PREFIXES: Dict[str, List[str]] = {
    "python": ["#"],
    "ruby": ["#"],
    "php": ["#", "//", "/*"],
    "shell": ["#"],
    "yaml": ["#"],
    "toml": ["#"],
    "javascript": ["//", "/*"],
    "typescript": ["//", "/*"],
    "rust": ["//", "/*"],
    "go": ["//", "/*"],
    "java": ["//", "/*"],
    "c": ["//", "/*"],
    "cpp": ["//", "/*"],
    "csharp": ["//", "/*"],
    "kotlin": ["//", "/*"],
    "swift": ["//", "/*"],
    "css": ["/*"],
    "html": ["<!--"],
    "xml": ["<!--"],
    "sql": ["--"],
}


def _detect_language_from_extension(file_path: str) -> str:
    """Detect language from file extension.

    Args:
        file_path: Path to the source file.

    Returns:
        Language name (lowercase) or "unknown".
    """
    ext_map = {
        ".py": "python", ".rb": "ruby", ".php": "php", ".sh": "shell",
        ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
        ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
        ".rs": "rust", ".go": "go", ".java": "java",
        ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
        ".cs": "csharp", ".kt": "kotlin", ".swift": "swift",
        ".css": "css", ".html": "html", ".htm": "html", ".xml": "xml",
        ".sql": "sql", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    }
    for ext, lang in ext_map.items():
        if file_path.endswith(ext):
            return lang
    return "unknown"


def _extract_comments_from_line(line: str, language: str) -> List[str]:
    """Extract comment text from a source line for the given language.

    Handles inline comments (code + comment on same line) and full-line comments.

    Args:
        line: A single line of source code.
        language: Language name (lowercase).

    Returns:
        List of comment strings found in the line.
    """
    prefixes = COMMENT_PREFIXES.get(language, [])
    comments = []

    for prefix in prefixes:
        # Find the prefix in the line (not inside a string — simplified)
        idx = _find_comment_start(line, prefix)
        if idx >= 0:
            comment = line[idx:]
            comments.append(comment)

    # Deduplicate (/* might match both // and /*)
    seen = set()
    unique = []
    for c in comments:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _find_comment_start(line: str, prefix: str) -> int:
    """Find the start index of a comment prefix in a line, ignoring strings.

    This is a simplified string-aware search. It handles basic cases:
    - Double-quoted strings: "hello // world" — the // inside is not a comment
    - Single-quoted strings: 'hello // world' — same
    - Backtick strings (JS/TS): `hello // world` — same

    Args:
        line: Source code line.
        prefix: Comment prefix to find (e.g., "//", "#", "/*").

    Returns:
        Index of the comment start, or -1 if not found.
    """
    in_string = None  # None, '"', "'", or '`'
    i = 0
    while i < len(line):
        ch = line[i]

        if in_string:
            if ch == in_string:
                in_string = None
            elif ch == "\\" and i + 1 < len(line):
                i += 1  # Skip escaped character
        else:
            if ch in ('"', "'", "`"):
                in_string = ch
            elif line[i:i + len(prefix)] == prefix:
                return i
        i += 1
    return -1


# ─── Apply Suppressions ────────────────────────────────────────────────────

def apply_suppressions(
    findings: List[Dict],
    source_files: Dict[str, str],
    keyword: str = "codelens-ignore",
    keyword_pattern: str = DEFAULT_KEYWORD_PATTERN,
) -> List[Dict]:
    """Apply inline suppressions to findings.

    Findings are mutated in-place: ``suppressed``, ``suppressed_rules``,
    and ``suppressed_reason`` fields are set.

    Suppression logic:
    1. For each finding, look at the finding's line in the source file.
    2. Check for inline suppression on that line.
    3. If not found and the finding is on line N, check line N-1 for a
       ``-next`` annotation.
    4. If a suppression is found:
       - If rule_ids is empty → suppress all rules (suppressed = True).
       - If rule_ids is non-empty → suppress only if the finding's rule_id
         or category matches one of the listed rule_ids.

    Args:
        findings: List of finding dicts. Each should have ``file``, ``line``
            (or ``line_number``), and optionally ``rule_id`` or ``category``.
        source_files: Dict mapping file path → file content string.
        keyword: Default keyword name (for SuppressionInfo.keyword).
        keyword_pattern: Regex pattern for keyword matching.

    Returns:
        The same findings list (mutated in-place).
    """
    # Pre-parse suppression annotations per file
    # Structure: {file_path: {line_num: [SuppressionInfo, ...]}}
    file_suppressions: Dict[str, Dict[int, List[SuppressionInfo]]] = {}
    # Also track next-line suppressions: {file_path: {line_num: [SuppressionInfo, ...]}}
    # where line_num is the line ON WHICH the -next annotation appears (applies to line+1)
    file_next_suppressions: Dict[str, Dict[int, List[SuppressionInfo]]] = {}

    for file_path, content in source_files.items():
        language = _detect_language_from_extension(file_path)
        lines = content.split("\n")

        file_suppressions[file_path] = {}
        file_next_suppressions[file_path] = {}

        for i, line in enumerate(lines):
            line_num = i + 1  # 1-indexed
            comments = _extract_comments_from_line(line, language)

            for comment in comments:
                info = detect_suppression(comment, keyword, keyword_pattern)
                if info:
                    if info.is_next_line:
                        # This suppression applies to the NEXT line
                        if line_num not in file_next_suppressions[file_path]:
                            file_next_suppressions[file_path][line_num] = []
                        file_next_suppressions[file_path][line_num].append(info)
                    else:
                        # This suppression applies to the CURRENT line
                        if line_num not in file_suppressions[file_path]:
                            file_suppressions[file_path][line_num] = []
                        file_suppressions[file_path][line_num].append(info)

    # Apply suppressions to findings
    for finding in findings:
        file_path = finding.get("file") or finding.get("defined_in") or ""
        line_num = finding.get("line") or finding.get("line_number") or 0
        if isinstance(line_num, str):
            try:
                line_num = int(line_num)
            except ValueError:
                continue

        if not file_path or not line_num:
            continue

        # Initialize suppression fields
        finding.setdefault("suppressed", False)
        finding.setdefault("suppressed_rules", [])
        finding.setdefault("suppressed_reason", "")

        # Get the finding's rule ID
        finding_rule_id = (
            finding.get("rule_id")
            or finding.get("ruleId")
            or finding.get("category")
            or finding.get("type")
            or ""
        )

        # Check same-line suppressions
        same_line_infos = file_suppressions.get(file_path, {}).get(line_num, [])
        for info in same_line_infos:
            if _matches_suppression(info, finding_rule_id):
                finding["suppressed"] = True
                if info.rule_ids:
                    finding["suppressed_rules"] = info.rule_ids
                finding["suppressed_reason"] = info.reason
                break

        if finding["suppressed"]:
            continue

        # Check next-line suppressions (line_num - 1 has the -next annotation)
        prev_line = line_num - 1
        next_line_infos = file_next_suppressions.get(file_path, {}).get(prev_line, [])
        for info in next_line_infos:
            if _matches_suppression(info, finding_rule_id):
                finding["suppressed"] = True
                if info.rule_ids:
                    finding["suppressed_rules"] = info.rule_ids
                finding["suppressed_reason"] = info.reason
                break

    return findings


def _matches_suppression(info: SuppressionInfo, finding_rule_id: str) -> bool:
    """Check if a suppression info matches a finding's rule ID.

    Args:
        info: Parsed suppression info.
        finding_rule_id: The finding's rule ID or category.

    Returns:
        True if the suppression applies to this finding.
    """
    # If no specific rule_ids → suppress everything
    if not info.rule_ids:
        return True

    # If specific rule_ids → check if finding's rule matches
    finding_rule_lower = finding_rule_id.lower().strip()
    for rid in info.rule_ids:
        rid_lower = rid.lower().strip()
        # Exact match or suffix match (e.g., "long-function" matches "codelens/smell/long-function")
        if finding_rule_lower == rid_lower or finding_rule_lower.endswith(rid_lower):
            return True
    return False


# ─── Count Pipeline Helpers ─────────────────────────────────────────────────

def update_stats_with_suppressions(result: Dict) -> Dict:
    """Update stats in a result dict to include suppression counts.

    This ensures suppressed findings are counted separately from active ones,
    preventing the UBS bug #51 pattern where suppressed findings are silently
    missed in count pipelines.

    Affected stat fields (per engine):
    - smell.stats.total_findings → stays as total (includes suppressed)
    - smell.stats.suppressed_count → NEW field
    - secrets.stats.findings_count → stays as total
    - secrets.stats.suppressed_count → NEW field
    - taint.stats.violations → stays as total
    - taint.stats.suppressed_count → NEW field
    - Any engine with stats.*_count → add stats.suppressed_count

    Args:
        result: The engine result dict.

    Returns:
        The same result dict (mutated in-place).
    """
    if not isinstance(result, dict):
        return result

    # Collect all findings from the result
    all_findings = _collect_findings(result)
    if not all_findings:
        return result

    suppressed_count = sum(1 for f in all_findings if f.get("suppressed", False))

    # Update stats
    stats = result.get("stats", {})
    if isinstance(stats, dict):
        stats["suppressed_count"] = suppressed_count
        # Also add to top-level for convenience
        result["suppressed_count"] = suppressed_count

    return result


def _collect_findings(result: Dict) -> List[Dict]:
    """Collect all finding-like dicts from a result.

    Looks in: findings, leaks, hints, issues, violations, matches, chains,
    and by_category (dict of lists).
    """
    findings = []
    finding_keys = ("findings", "leaks", "hints", "issues", "violations", "matches", "chains")

    for key in finding_keys:
        val = result.get(key)
        if isinstance(val, list):
            findings.extend(val)
        elif isinstance(val, dict):
            for sub_val in val.values():
                if isinstance(sub_val, list):
                    findings.extend(sub_val)

    # Also check by_category
    by_cat = result.get("by_category")
    if isinstance(by_cat, dict):
        for sub_val in by_cat.values():
            if isinstance(sub_val, list):
                findings.extend(sub_val)

    return findings
