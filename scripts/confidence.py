# @WHO:   scripts/confidence.py
# @WHAT:  Confidence scoring for findings + schema versioning (issue #5)
# @PART:  engine
# @ENTRY: score_finding(), SCHEMA_VERSION, stamp_schema_version()
"""Confidence scoring and schema versioning for CodeLens findings (issue #5).

Two agent-UX features live here:

1. **Confidence scores** — each finding gets a ``confidence`` field in [0.0, 1.0]
   so agents can filter actionable findings vs. ones that need human review
   without discarding everything. High-confidence findings (>= 0.9) are safe
   to auto-triage; low-confidence ones (< 0.5) should be surfaced for review.

2. **Schema versioning** — every JSON output gets a ``schema_version`` field
   so consumers can handle breaking changes gracefully. The version follows
   the CodeLens release version (e.g. ``"8.2"``). Bumped on any breaking
   change to the AI-normalized output schema.

Confidence model
----------------
Confidence is *category-driven* with *modifier adjustments*. The base score
reflects how reliable a detection category is in general; modifiers nudge
the score up or down based on per-finding signals (e.g. test-file context
reduces confidence, dynamic-access patterns reduce it further).

Examples::

    score_finding("dead_code", "unreachable", {"after": "return"})
    # -> 0.95  (code after return is almost certainly dead)

    score_finding("dead_code", "unused_exports", {"source": "library_api"})
    # -> 0.40  (library exports are often public API; low confidence)

    score_finding("secrets", "pattern_match", {"in_test_file": True})
    # -> 0.55  (test-file match is often a fixture, not a real secret)

The scores below are starting heuristics — they should be tuned over time
as we collect false-positive / false-negative data. Agents should treat
them as *ranking signals*, not ground truth.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional


# ─── Schema version ────────────────────────────────────────────────────────

# Bumped on any breaking change to the AI-normalized output schema
# (formatters/_normalize_to_ai). Agents can read this to decide whether
# their parser still understands the output.
#
# History:
#   8.2 — initial schema_version field (issue #5)
SCHEMA_VERSION = "8.2"


def stamp_schema_version(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Add ``schema_version`` to a payload dict (in place + returned).

    Used by :func:`formatters._normalize_to_ai` so every MCP/JSON output
    carries the version. Idempotent — if the field is already present it
    is preserved (callers may override for testing).
    """
    if isinstance(payload, dict) and "schema_version" not in payload:
        payload["schema_version"] = SCHEMA_VERSION
    return payload


# ─── Confidence base scores per category ───────────────────────────────────
#
# These reflect *general reliability* of each detection category. Categories
# that rely on simple syntactic patterns score high; categories that depend
# on cross-file resolution or heuristics score lower.
#
# Tuning guidelines:
#   0.95+  — almost never wrong (e.g. code after return)
#   0.80   — usually right, occasional false positive (e.g. unreachable after throw)
#   0.65   — mixed; needs review (e.g. unused variables — could be intentional)
#   0.50   — often wrong; flag for review (e.g. zombie CSS — class may be dynamic)
#   0.35   — low confidence; almost certainly needs review (e.g. library exports)

_DEAD_CODE_BASE: Dict[str, float] = {
    "unreachable":      0.95,  # code after return/throw/break — syntactic certainty
    "unused_vars":      0.70,  # could be intentional (debugging, future use)
    "dead_listeners":   0.60,  # element may be dynamically created
    "zombie_css":       0.50,  # classes often referenced dynamically
    "unused_exports":   0.45,  # public API — could be consumed externally
    "registry_dead":    0.75,  # ref_count==0 from scan — usually right but
                                # misses dynamic calls
}

_SECRETS_BASE: Dict[str, float] = {
    "pattern_match":    0.90,  # matched a known secret pattern (e.g. AWS key format)
    "env_exposed":      0.85,  # secret reads from env in source — high signal
    "entropy":          0.65,  # high-entropy string — could be a hash, UUID, etc.
}


# ─── Modifier rules ────────────────────────────────────────────────────────
#
# Each modifier is ``(predicate, delta)``. Predicates inspect the finding dict
# and return ``True`` when the modifier applies. Deltas are summed onto the
# base score, then clamped to [0.0, 1.0].
#
# Negative deltas = *reduce* confidence (more likely false positive).
# Positive deltas = *increase* confidence (more likely true positive).

def _is_test_file(finding: Dict[str, Any]) -> bool:
    return bool(finding.get("in_test_file") or finding.get("source") == "test")


def _is_config_file(finding: Dict[str, Any]) -> bool:
    return finding.get("source") == "config"


def _is_library_api(finding: Dict[str, Any]) -> bool:
    return finding.get("source") == "library_api"


def _is_downgraded(finding: Dict[str, Any]) -> bool:
    return bool(finding.get("downgraded"))


def _has_after_return(finding: Dict[str, Any]) -> bool:
    return finding.get("after") == "return"


def _has_after_throw(finding: Dict[str, Any]) -> bool:
    return finding.get("after") == "throw"


_DEAD_CODE_MODIFIERS = [
    # Test/config files: detections here are less reliable — they're often
    # fixtures, examples, or intentionally dead for testing purposes.
    (_is_test_file,   -0.15),
    (_is_config_file, -0.10),
    # Library API exports: almost always false positives — public API.
    (_is_library_api, -0.20),
    # Already-downgraded findings: confidence already reflects doubt.
    (_is_downgraded,  -0.05),
    # `after: return` is more certain than `after: throw` (throw can be
    # caught by an outer try/catch in some languages).
    (_has_after_return, +0.03),
    (_has_after_throw,  -0.03),
]

_SECRETS_MODIFIERS = [
    # Test files: secrets here are almost always fixtures, not real.
    (_is_test_file, -0.30),
    # Already-downgraded severity: lower confidence.
    (_is_downgraded, -0.10),
]


# ─── Public API ────────────────────────────────────────────────────────────


def score_finding(
    engine: str,
    category: str,
    finding: Dict[str, Any],
) -> float:
    """Return a confidence score in [0.0, 1.0] for a finding.

    Args:
        engine:    ``"dead_code"`` or ``"secrets"`` (the engine that produced
                   the finding).
        category:  The finding's category within the engine (e.g.
                   ``"unreachable"``, ``"pattern_match"``).
        finding:   The finding dict. Modifiers inspect fields like
                   ``in_test_file``, ``source``, ``after``, ``downgraded``.

    Returns:
        Float in [0.0, 1.0]. Higher = more confident the finding is real.

    Unknown engines/categories default to ``0.50`` (neutral) so a missing
    score never breaks the pipeline — agents can still rank findings,
    they just won't get the benefit of category-specific tuning.
    """
    if engine == "dead_code":
        base = _DEAD_CODE_BASE.get(category, 0.50)
        modifiers = _DEAD_CODE_MODIFIERS
    elif engine == "secrets":
        base = _SECRETS_BASE.get(category, 0.50)
        modifiers = _SECRETS_MODIFIERS
    else:
        return 0.50

    score = base
    for predicate, delta in modifiers:
        try:
            if predicate(finding):
                score += delta
        except Exception:
            # Never let a modifier crash the scoring — fail safe.
            continue

    return max(0.0, min(1.0, round(score, 2)))


def enrich_finding(
    engine: str,
    finding: Dict[str, Any],
    *,
    category_field: str = "category",
    type_field: str = "type",
) -> Dict[str, Any]:
    """Add a ``confidence`` field to a finding dict (in place + returned).

    Resolves the scoring category from the finding. For secrets, the
    *detection method* lives in ``type`` (pattern_match / entropy /
    env_exposed) and is the right key for confidence lookup; ``category``
    holds the specific secret kind (aws_key, etc.) which is too granular.
    For dead-code, callers normally pass the category explicitly via
    :func:`enrich_findings`; this single-finding helper falls back to
    ``type`` then ``category``.

    Idempotent: if ``confidence`` is already present, it is preserved.
    """
    if not isinstance(finding, dict):
        return finding
    if "confidence" in finding:
        return finding

    # For secrets, prefer `type` (detection method) over `category` (secret kind).
    # For dead-code, prefer `category` (set by callers) over `type` (subkind).
    if engine == "secrets":
        category = (
            finding.get(type_field)
            or finding.get(category_field)
            or "unknown"
        )
    else:
        category = (
            finding.get(category_field)
            or finding.get(type_field)
            or "unknown"
        )

    finding["confidence"] = score_finding(engine, category, finding)
    return finding


def enrich_findings(
    engine: str,
    findings: Dict[str, Any],
    *,
    results_key: str = "results",
    findings_key: str = "findings",
) -> Dict[str, Any]:
    """Enrich all findings in a result payload with confidence scores.

    Works for both dead-code (category-keyed dict under ``results``) and
    secrets (flat list under ``findings``). Mutates ``findings`` in place
    and returns it.

    Args:
        engine:       ``"dead_code"`` or ``"secrets"``.
        findings:     The full result payload from the engine.
        results_key:  Key for category-keyed dict (dead-code style).
        findings_key: Key for flat list (secrets style).

    Returns:
        The same ``findings`` dict, with ``confidence`` added to each
        finding. If the payload shape doesn't match either style, the
        payload is returned unchanged (fail-safe).
    """
    if not isinstance(findings, dict):
        return findings

    # Dead-code style: results = {category: [finding, ...], ...}
    if results_key in findings and isinstance(findings[results_key], dict):
        for category, items in findings[results_key].items():
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and "confidence" not in item:
                    # For dead-code, the category is the dict key.
                    item["confidence"] = score_finding(engine, category, item)

    # Secrets style: findings = [finding, ...]
    # For secrets, the *detection method* lives in ``type`` (pattern_match,
    # entropy, env_exposed) while ``category`` holds the specific secret kind
    # (aws_key, github_token, etc.). Confidence is keyed off the detection
    # method, so we prefer ``type`` over ``category`` here.
    if findings_key in findings and isinstance(findings[findings_key], list):
        for item in findings[findings_key]:
            if isinstance(item, dict) and "confidence" not in item:
                category = item.get("type") or item.get("category") or "unknown"
                item["confidence"] = score_finding(engine, category, item)

    return findings


# ─── Convenience: confidence distribution ──────────────────────────────────


def confidence_distribution(findings: list) -> Dict[str, int]:
    """Bucket a list of (already-scored) findings by confidence range.

    Returns a dict with keys ``high`` (>= 0.85), ``medium`` (0.5..0.85),
    ``low`` (< 0.5), and ``unscored`` (findings without a ``confidence``
    field). Useful for surfacing a quick reliability summary to agents.
    """
    buckets = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    for item in findings:
        if not isinstance(item, dict):
            continue
        c = item.get("confidence")
        if c is None:
            buckets["unscored"] += 1
        elif c >= 0.85:
            buckets["high"] += 1
        elif c >= 0.5:
            buckets["medium"] += 1
        else:
            buckets["low"] += 1
    return buckets
