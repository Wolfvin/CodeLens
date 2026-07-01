"""Unified Finding dataclass + extraction helper for CodeLens formatters (issue #52, Phase 1).

Why this module exists
----------------------
CodeLens commands return heterogeneous dicts — each engine uses
slightly different keys for the same logical concept:

* ``secrets`` returns ``findings`` with ``file``, ``line``, ``severity``,
  ``category``, ``message``, ``match``
* ``dead-code`` returns ``by_category`` dict of lists, with
  ``defined_in`` instead of ``file``, ``line_number`` instead of
  ``line``
* ``smell`` returns ``by_category`` with ``severity``, ``message``
* ``taint`` returns ``chains`` with ``source``, ``sink``, ``taint_path``
* ``complexity`` returns ``functions`` with ``cyclomatic`` score

Before Phase 1, every formatter (sarif, compact, ai normalizer) had
its own ad-hoc extraction logic — duplicated, slightly inconsistent,
and a maintenance trap.

This module introduces a single :class:`Finding` dataclass and a
single :func:`extract_findings` entry point. Formatters consume
``Finding`` objects; the extraction logic lives here, in one place.

Backward compatibility
----------------------
This is **additive only**. Existing formatters (json, markdown, ai,
sarif, compact) keep their original behavior — they do NOT use
``Finding`` objects internally. New Phase 2 formatters (text,
junit_xml, emacs, vim, gitlab_sast) consume ``Finding`` objects.

The path forward (future Phase) is to refactor existing formatters
to also consume ``Finding`` objects, but that's a behavior-risky
change and out of scope for this PR.

License note
------------
Issue #52 explicitly notes: "Semgrep formatters are LGPL-2.1 —
reference only, reimplement from spec." This module is a clean-room
reimplementation from the CodeLens output schemas observed in the
existing engines; no Semgrep code or schema was copied.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

__all__ = [
    "Finding",
    "Severity",
    "extract_findings",
    "findings_to_dicts",
]


# ─── Severity enum (string-based for JSON compat) ──────────────

class Severity:
    """String constants for finding severity levels.

    CodeLens engines use a mix of severity vocabularies — some use
    ``critical/high/medium/low/info``, others use ``error/warning/info``.
    The :class:`Severity` constants are the canonical set; the
    extraction layer normalizes engine-specific values to these.

    Using a class-with-string-constants (not ``enum.Enum``) because:

    * JSON serialization "just works" (no ``.value`` accessor needed).
    * Formatters can compare ``finding.severity == "critical"``
      without importing the class.
    * Backward-compatible with existing string-typed severity fields
      in engine output.
    """
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"
    ERROR = "error"      # alias for critical/high in some tools
    WARNING = "warning"  # alias for medium
    UNKNOWN = "info"     # default when engine didn't set severity


# ─── Finding dataclass ─────────────────────────────────────────


@dataclass
class Finding:
    """A single analyzer finding, normalized across all CodeLens engines.

    Every formatter in Phase 2+ consumes this dataclass. The
    extraction layer (:func:`extract_findings`) populates it from
    the heterogeneous engine outputs.

    Fields are designed to be **superset** of what any single
    formatter needs — ``junit_xml`` uses ``message`` + ``severity``,
    ``emacs``/``vim`` use ``file`` + ``line`` + ``column`` + ``message``,
    ``gitlab_sast`` uses ``cwe`` + ``severity`` + ``location``. A
    formatter just reads the fields it needs and ignores the rest.

    Severity values: see :class:`Severity`. Always lowercase string.
    """
    # ─── Required (every finding has these) ───
    message: str
    severity: str = Severity.UNKNOWN

    # ─── Location ───
    file: str = ""
    line: int = 0
    column: int = 0
    end_line: int = 0
    end_column: int = 0

    # ─── Classification ───
    rule_id: str = ""        # e.g. "codelens/secrets/api-key"
    category: str = ""       # e.g. "api_key", "unreachable", "long_fn"
    command: str = ""        # which CodeLens command produced this
    confidence: str = ""     # "high" / "medium" / "low" if available

    # ─── Optional context ───
    cwe: str = ""            # e.g. "CWE-79" for XSS
    snippet: str = ""        # source code snippet (already masked if secret)
    taint_path: str = ""     # "source → ... → sink" for taint findings
    source: str = ""         # taint source identifier
    sink: str = ""           # taint sink identifier

    # ─── Suppression ───
    suppressed: bool = False
    suppressed_reason: str = ""

    # ─── Free-form extras (preserved for round-trip JSON) ───
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a plain dict (for JSON serialization).

        Omits empty/zero values to keep output compact — this is the
        format ``--format json`` will eventually use directly once
        existing formatters are refactored to consume ``Finding``.
        For now, it's used by ``findings_to_dicts`` for testing.
        """
        d = asdict(self)
        # Remove empty/zero fields (but keep ``severity`` even if "info",
        # and keep ``message`` even if empty — those are required).
        out: Dict[str, Any] = {}
        for k, v in d.items():
            if k == "extras":
                if v:
                    out.update(v)
                continue
            if v in ("", 0, False, None):
                # Keep severity and message even if "empty" defaults.
                if k in ("severity", "message"):
                    out[k] = v
                continue
            out[k] = v
        return out


# ─── Extraction logic ──────────────────────────────────────────

# Keys where engines stash their findings lists. Order matters —
# the first key that yields a non-empty list wins. This mirrors the
# priority order in ``formatters/__init__.py::_normalize_to_ai`` so
# Phase 1 extraction is consistent with existing AI normalizer.
_FINDING_LIST_KEYS: Tuple[str, ...] = (
    "findings", "leaks", "hints", "issues", "violations",
    "matches", "chains", "results",
)

# Keys where engines stash category-keyed dicts of finding lists
# (e.g. ``dead-code`` returns ``{"by_category": {"unreachable": [...]}}``).
_FINDING_DICT_KEYS: Tuple[str, ...] = (
    "by_category", "by_severity", "results",
)


def _coerce_int(value: Any, default: int = 0) -> int:
    """Best-effort int coercion — engines sometimes emit strings."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _normalize_severity(raw: Any) -> str:
    """Normalize engine-specific severity strings to canonical Severity.

    Engines use various vocabularies — this collapses them to the
    canonical set so formatters don't need to handle every variant.
    """
    if not raw:
        return Severity.UNKNOWN
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip().lower()
    # Direct canonical match
    if s in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
             Severity.LOW, Severity.INFO):
        return s
    # Aliases
    if s in (Severity.ERROR, "fatal", "blocker"):
        return Severity.CRITICAL
    if s in (Severity.WARNING, "warn", "moderate"):
        return Severity.MEDIUM
    if s in ("informational", "note", "hint", "trivial"):
        return Severity.LOW
    return Severity.UNKNOWN


def _normalize_finding_dict(
    raw: Dict[str, Any],
    command: str,
    category_hint: str = "",
) -> Finding:
    """Normalize a single engine finding dict into a :class:`Finding`.

    ``category_hint`` is set when the finding came from a
    category-keyed dict (e.g. ``by_category["unreachable"]``) — the
    engine often doesn't repeat the category inside each finding, so
    we use the hint as a fallback.
    """
    if not isinstance(raw, dict):
        # Defensive: engines shouldn't return non-dict findings, but
        # if they do, wrap the value in a message.
        return Finding(message=str(raw), command=command, category=category_hint)

    # ─── Location ───
    file_path = (
        raw.get("file")
        or raw.get("defined_in")
        or raw.get("path")
        or raw.get("filename")
        or ""
    )
    line = _coerce_int(
        raw.get("line") or raw.get("line_number") or raw.get("start_line") or 0
    )
    column = _coerce_int(
        raw.get("column") or raw.get("col") or raw.get("start_column") or 0
    )
    end_line = _coerce_int(
        raw.get("end_line") or raw.get("endLine") or 0
    )
    end_column = _coerce_int(
        raw.get("end_column") or raw.get("endColumn") or 0
    )

    # ─── Classification ───
    category = (
        raw.get("category")
        or raw.get("type")
        or category_hint
        or ""
    )
    severity = _normalize_severity(
        raw.get("severity") or raw.get("risk") or raw.get("level")
    )
    confidence = (
        raw.get("confidence")
        or raw.get("certainty")
        or ""
    )
    if isinstance(confidence, str):
        confidence = confidence.lower()

    # ─── Message ───
    # Engines use various keys for the human-readable message.
    message = (
        raw.get("message")
        or raw.get("name")
        or raw.get("description")
        or raw.get("match")
        or raw.get("rule")
        or ""
    )
    if not message:
        # Last-resort: synthesize a message from category + file.
        # Better than empty string — formatters need *something* to show.
        basename = file_path.rsplit("/", 1)[-1] if file_path else "<unknown>"
        message = f"{command} finding in {basename}"
        if category:
            message = f"{category} in {basename}"

    # ─── Rule ID ───
    rule_id = (
        raw.get("rule_id")
        or raw.get("ruleId")
        or raw.get("rule")
        or ""
    )
    if not rule_id and command:
        # Synthesize a stable rule_id: "codelens/<command>/<category>"
        # Lowercase, hyphenated. This matches the convention used by
        # the existing SARIF formatter (``sarif._get_rule_id``).
        safe_cat = (category or "general").lower().replace("_", "-").replace(" ", "-")
        rule_id = f"codelens/{command}/{safe_cat}"

    # ─── CWE ───
    cwe = raw.get("cwe") or raw.get("CWE") or ""
    if isinstance(cwe, str):
        cwe = cwe.strip()

    # ─── Snippet ───
    snippet = (
        raw.get("snippet")
        or raw.get("code")
        or raw.get("line_content")
        or raw.get("match")
        or ""
    )

    # ─── Taint-specific ───
    taint_path = (
        raw.get("taint_path")
        or raw.get("dataflow_path")
        or raw.get("flow")
        or ""
    )
    source = raw.get("source") or ""
    sink = raw.get("sink") or ""

    # ─── Suppression ───
    suppressed = bool(raw.get("suppressed") or raw.get("ignored") or False)
    suppressed_reason = raw.get("suppressed_reason") or raw.get("ignore_reason") or ""

    # ─── Extras: capture remaining non-canonical keys ───
    # This preserves round-trip fidelity — if an engine emits a
    # field that doesn't map to a Finding attribute, it goes into
    # ``extras`` and survives ``to_dict()``.
    known_keys = {
        "file", "defined_in", "path", "filename",
        "line", "line_number", "start_line", "start_column",
        "column", "col", "end_line", "endLine", "end_column", "endColumn",
        "category", "type", "severity", "risk", "level", "confidence", "certainty",
        "message", "name", "description", "match", "rule",
        "rule_id", "ruleId", "cwe", "CWE",
        "snippet", "code", "line_content",
        "taint_path", "dataflow_path", "flow", "source", "sink",
        "suppressed", "ignored", "suppressed_reason", "ignore_reason",
    }
    extras = {k: v for k, v in raw.items() if k not in known_keys}

    return Finding(
        message=message,
        severity=severity,
        file=file_path,
        line=line,
        column=column,
        end_line=end_line,
        end_column=end_column,
        rule_id=rule_id,
        category=category,
        command=command,
        confidence=confidence,
        cwe=cwe,
        snippet=snippet,
        taint_path=taint_path,
        source=source,
        sink=sink,
        suppressed=suppressed,
        suppressed_reason=suppressed_reason,
        extras=extras,
    )


def extract_findings(data: Any, command: str = "") -> List[Finding]:
    """Extract a list of :class:`Finding` from any CodeLens command output.

    This is the single entry point formatters should call. It handles:

    * Plain finding lists (``data["findings"] = [...]``)
    * Category-keyed dicts (``data["by_category"] = {"unreachable": [...]}``)
    * Severity-keyed dicts (``data["by_severity"] = {"critical": [...]}``)
    * Empty / non-dict / error output → returns ``[]``

    The extraction is conservative — when in doubt, return fewer
    findings rather than risk duplicating or misattributing. An
    empty list is always safe for formatters to render as "no
    findings".

    Args:
        data: CodeLens command output (usually a dict).
        command: Command name (e.g. ``"secrets"``). Used to populate
            :attr:`Finding.command` and synthesize :attr:`Finding.rule_id`
            when the engine didn't provide one.

    Returns:
        List of :class:`Finding` objects, possibly empty. Never None.
    """
    if not isinstance(data, dict):
        return []
    if data.get("status") == "error":
        # Error responses have no findings — don't try to extract.
        return []

    findings: List[Finding] = []
    seen_ids: set = set()  # dedupe by (file, line, category, message)

    def _add(raw_finding: Any, category_hint: str = "") -> None:
        if not isinstance(raw_finding, dict):
            return
        f = _normalize_finding_dict(raw_finding, command, category_hint)
        # Dedupe — engines occasionally return the same finding twice
        # (e.g. once in ``findings`` and once in ``by_category``).
        key = (f.file, f.line, f.category, f.message)
        if key in seen_ids:
            return
        seen_ids.add(key)
        findings.append(f)

    # ─── Phase 1: plain finding lists ───
    for key in _FINDING_LIST_KEYS:
        val = data.get(key)
        if isinstance(val, list):
            for item in val:
                _add(item)
        elif isinstance(val, dict):
            # Some engines use ``findings = {"category_name": [list]}``
            # instead of a plain list. Treat it like by_category.
            for cat, items in val.items():
                if isinstance(items, list):
                    for item in items:
                        _add(item, category_hint=cat)

    # ─── Phase 2: category/severity-keyed dicts ───
    for key in _FINDING_DICT_KEYS:
        val = data.get(key)
        if isinstance(val, dict):
            for cat, items in val.items():
                if isinstance(items, list):
                    for item in items:
                        _add(item, category_hint=cat)

    return findings


def findings_to_dicts(findings: List[Finding]) -> List[Dict[str, Any]]:
    """Convert a list of Finding back to plain dicts.

    Mainly used for testing — verifies round-trip fidelity.
    """
    return [f.to_dict() for f in findings]
