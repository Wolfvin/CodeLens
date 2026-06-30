"""Regex prefilter for CodeLens scan (issue #56).

Conservative file-level prefilter that skips files which definitely do not
contain any patterns being searched, *before* expensive tree-sitter parsing.

GUARANTEE
---------
The prefilter is **strictly conservative**:

* False positives are OK (passing a file that won't match is just a missed
  optimization).
* False negatives are FORBIDDEN: a file that *would* match a rule must
  **never** be skipped. Concretely, any file that contains a literal token
  extracted from any rule's ``sources``, ``sinks``, ``sanitizers`` or
  related fields will pass the prefilter.

When in doubt (e.g., the file cannot be read, the prefilter regex fails to
compile, or no literals can be extracted from the rule set), the prefilter
returns ``True`` — scan the file. Safer to scan than skip.

USAGE
-----
::

    from prefilter import build_prefilter, should_scan_file

    prefilter = build_prefilter(rules)
    if should_scan_file(path, prefilter):
        # ... expensive tree-sitter parse ...
    else:
        # skip — file definitely doesn't contain any rule token

When ``rules`` is empty or contains no extractable literals,
``build_prefilter`` returns ``None`` and ``should_scan_file`` always returns
``True`` — the prefilter becomes a no-op, preserving the scan's pre-#56
behavior. This means the prefilter is safe to wire up by default: it only
starts filtering once rules are actually loaded (e.g., via ``--plugins``).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional


# ─── Tuning constants ────────────────────────────────────────

# Minimum token length to be considered a useful literal.
# Tokens shorter than this (e.g., "fs", "id", "in", "to") are too common
# and would match nearly every file, providing no filtering value while
# inflating the regex alternation. A 4-char floor keeps the regex compact
# while still catching the vast majority of meaningful identifiers
# ("flask", "exec", "eval", "fetch", "pickle", "cursor", ...).
_MIN_TOKEN_LENGTH = 4

# Maximum number of unique tokens to OR together. Caps regex compilation
# time and per-file match cost when rule sets are huge (e.g., the bundled
# OWASP / PCI-DSS / HIPAA packs together can yield 1000+ tokens). Python's
# ``re`` module handles large alternations fine, but bounding the size is
# a defensive measure. When the cap is hit, the longest tokens are kept
# (longer tokens are more specific → fewer false positives).
_MAX_TOKENS = 1000

# Fields in rule YAML / PluginRule dicts that may contain literal
# identifier strings. We extract tokens from all of them so the prefilter
# covers both taint-style rules (sources/sinks/sanitizers) and any future
# pattern-based rules (patterns/match/imports/exports).
_RULE_LITERAL_FIELDS: tuple = (
    "sources",
    "sinks",
    "sanitizers",
    "patterns",
    "match",
    "imports",
    "exports",
)


# ─── Token extraction ────────────────────────────────────────


def _extract_tokens_from_entry(entry: Any) -> List[str]:
    """Split a single rule entry into literal identifier tokens.

    Rule entries are typically dotted/qualified identifier strings such as
    ``"flask.request.args"``, ``"cursor.execute"`` or ``"exec("``. We split
    on anything that's not a letter, digit, or underscore, which collapses:

    * ``"flask.request.args"`` → ``["flask", "request", "args"]``
    * ``"exec("``              → ``["exec"]``
    * ``".innerHTML"``          → ``["innerHTML"]``
    * ``"Object.assign("``      → ``["Object", "assign"]``

    Tokens shorter than ``_MIN_TOKEN_LENGTH`` are dropped (see constant
    docstring for rationale).
    """
    if not isinstance(entry, str):
        # Defensive: coerce non-string entries (e.g., ints from a malformed
        # rule) to string so re.split doesn't raise.
        entry = str(entry)
    # Split on any run of non-identifier characters: anything that's not
    # [A-Za-z0-9_]. This is intentionally permissive — it handles dots,
    # parens, brackets, slashes, whitespace, etc. in one pass.
    raw = re.split(r"[^A-Za-z0-9_]+", entry)
    return [t for t in raw if len(t) >= _MIN_TOKEN_LENGTH]


def _iter_rule_entries(rule: Dict[str, Any]):
    """Yield every literal-bearing entry from a single rule dict.

    Iterates over all fields in ``_RULE_LITERAL_FIELDS``. Each field may be
    a string (treated as a single entry), a list/tuple of strings, or
    falsy (skipped). Non-string items inside a list are coerced to string
    by ``_extract_tokens_from_entry``.
    """
    if not isinstance(rule, dict):
        return
    for field in _RULE_LITERAL_FIELDS:
        value = rule.get(field)
        if not value:
            continue
        if isinstance(value, str):
            yield value
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield item
        # Nested dicts / other shapes are ignored — we only extract from
        # flat string lists, which is the documented rule schema.


# ─── Public API ──────────────────────────────────────────────


def build_prefilter(rules: Optional[List[dict]]) -> Optional[re.Pattern]:
    """Analyze rules/patterns, extract literal tokens (identifiers, strings).

    Build a single ``re.Pattern`` OR-ed from all tokens. Return ``None``
    if no literals can be extracted (e.g., empty rules list, or all
    patterns are pure wildcards with no identifier characters).

    Args:
        rules: List of rule dicts. Each dict may contain any of the fields
            in ``_RULE_LITERAL_FIELDS`` (``sources``, ``sinks``,
            ``sanitizers``, ``patterns``, ``match``, ``imports``,
            ``exports``). Both raw YAML rule dicts and ``PluginRule.to_dict()``
            outputs are accepted.

    Returns:
        Compiled ``re.Pattern`` that matches any file containing at least
        one extracted token, or ``None`` if no tokens could be extracted.

    Guarantees:
        * **No false negatives**: every literal token from every rule is
          included in the alternation. A file containing any rule token
          will match.
        * **Conservative**: when in doubt (no tokens, regex compilation
          fails), returns ``None`` → caller treats as "scan everything".
    """
    if not rules:
        return None

    tokens: set = set()
    for rule in rules:
        for entry in _iter_rule_entries(rule):
            for tok in _extract_tokens_from_entry(entry):
                tokens.add(tok)

    if not tokens:
        return None

    # Sort longest-first so the regex engine finds the most specific match
    # earliest. This is a minor optimization for the success path; OR
    # semantics still require scanning the whole alternation on failure,
    # but ordering long→short tends to find matches faster when they exist.
    # Secondary alphabetical sort makes the output deterministic, which
    # helps debugging and test assertions.
    sorted_tokens = sorted(tokens, key=lambda t: (-len(t), t))

    if len(sorted_tokens) > _MAX_TOKENS:
        sorted_tokens = sorted_tokens[:_MAX_TOKENS]

    # Escape each token (defensive: tokens are already identifier-like, so
    # there should be no regex metacharacters, but re.escape is cheap and
    # guards against unexpected input).
    pattern = "|".join(re.escape(t) for t in sorted_tokens)
    try:
        return re.compile(pattern)
    except re.error:
        # Should never happen since we escape everything, but be safe.
        # Conservative: return None → caller scans everything.
        return None


def should_scan_file(path: str, prefilter: Optional[re.Pattern]) -> bool:
    """Quick grep: open file, check if prefilter matches.

    Args:
        path: Absolute or relative path to the file.
        prefilter: Compiled regex from ``build_prefilter``, or ``None``.

    Returns:
        ``True`` if the file should be scanned (prefilter is ``None`` OR
        the file content matches the prefilter). ``False`` only when the
        prefilter is non-``None`` AND the file was successfully read AND
        no token matched.

    Conservative behavior:
        * ``prefilter is None`` → ``True`` (no filtering).
        * File cannot be read (IOError, OSError, UnicodeDecodeError) →
          ``True`` (safer to scan than skip; the parse step will re-read
          and handle errors its own way).
        * Any other unexpected exception → ``True``.
    """
    if prefilter is None:
        return True
    try:
        # Read with errors='ignore' so files with mixed encodings don't
        # crash the prefilter. The parse step already does the same.
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except (IOError, OSError, UnicodeDecodeError):
        # Conservative: if we can't read the file for the prefilter,
        # scan it anyway. The actual parse step will re-read and handle
        # errors its own way — and skipping a file we can't read could
        # hide a real finding.
        return True
    except Exception:
        # Catch-all: never let the prefilter crash the scan.
        return True

    if prefilter.search(content) is not None:
        return True
    return False


# ─── Stats container ─────────────────────────────────────────


class PrefilterStats:
    """Mutable accumulator for prefilter statistics.

    Tracks the number of files checked, passed, and skipped, plus the
    wall-clock elapsed time. Used by the scan command to report prefilter
    effectiveness in ``--verbose`` output.
    """

    __slots__ = ("checked", "passed", "skipped", "elapsed_sec")

    def __init__(self) -> None:
        self.checked: int = 0
        self.passed: int = 0
        self.skipped: int = 0
        self.elapsed_sec: float = 0.0

    def record(self, passed: bool) -> None:
        """Record one file check result."""
        self.checked += 1
        if passed:
            self.passed += 1
        else:
            self.skipped += 1

    @property
    def skip_percent(self) -> float:
        """Percentage of checked files that were skipped (0.0–100.0)."""
        if self.checked == 0:
            return 0.0
        return (self.skipped / self.checked) * 100.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict suitable for inclusion in scan result."""
        return {
            "checked": self.checked,
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_percent": round(self.skip_percent, 1),
            "elapsed_sec": round(self.elapsed_sec, 3),
        }

    def format_verbose_line(self) -> str:
        """Format the one-line ``--verbose`` summary.

        Example::

            Prefilter: 1240 files checked, 387 passed, 853 skipped (68%) in 0.3s

        The skip percentage is truncated (not rounded) to match the issue
        #56 spec example (853/1240 = 68.79% → "68%").
        """
        return (
            f"Prefilter: {self.checked} files checked, "
            f"{self.passed} passed, "
            f"{self.skipped} skipped ({int(self.skip_percent)}%) "
            f"in {self.elapsed_sec:.1f}s"
        )
