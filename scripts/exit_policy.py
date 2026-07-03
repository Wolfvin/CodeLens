# @WHO:   scripts/exit_policy.py
# @WHAT:  Exit-code policy evaluator — strict-mode / severity-threshold gate for CI
# @PART:  ci
# @ENTRY: evaluate_exit_policy()
"""
CodeLens exit-code policy evaluator (issue #57, Phase 2).

Encapsulates the "should this CI run fail?" decision so it can be
reused by ``codelens check``, ``codelens scan``, and the future
``codelens ci`` command (Phase 3) without duplicating logic.

Strict-mode semantics (issue #57 worker consensus, Semgrep CL-012):

- ``--strict``        : exit non-zero on ANY finding (warning or above).
                        Equivalent to ``--severity-threshold low``.
- ``--error``         : exit non-zero if any finding has severity
                        >= high. Equivalent to ``--severity-threshold high``.
- ``--severity-threshold <level>`` : exit non-zero if any finding has
                        severity >= ``<level>``. Explicit, no shortcut.
- ``--max-findings N``: exit non-zero if the count of relevant findings
                        exceeds N. N=0 disables the cap (default).

Evaluation order (when multiple flags are combined):
    1. severity threshold (``--strict`` or ``--error`` or
       ``--severity-threshold`` — last wins if multiple given, but in
       practice the CLI ``add_args`` makes them mutually exclusive via
       ``dest='severity_threshold'``).
    2. ``--max-findings`` cap.

The evaluator returns an :class:`ExitDecision` with ``should_fail``,
``exit_code``, ``reasons`` (human-readable list), and the resolved
threshold level so callers can include it in their JSON output.

Phase 2 scope (this module) does NOT make the actual ``sys.exit`` call
— that is the caller's job (codelens.py main dispatcher). Keeping the
decision pure makes it trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Severity ordering — lower index = more severe.
# ``info`` is treated as "informational, never fails the gate on its own".
SEVERITY_ORDER = ["critical", "high", "medium", "low", "info", "unknown"]
SEVERITY_RANK: Dict[str, int] = {s: i for i, s in enumerate(SEVERITY_ORDER)}


def severity_rank(sev: Optional[str]) -> int:
    """Return 0..5 for a severity string (lower = more severe).

    Unknown / missing severities are treated as ``"unknown"`` which
    ranks just below ``"info"`` — they will NOT trigger the gate on
    their own, but ``--strict`` (threshold=low) still catches them.
    """
    if not sev:
        return SEVERITY_RANK["unknown"]
    return SEVERITY_RANK.get(str(sev).lower(), SEVERITY_RANK["unknown"])


@dataclass
class ExitDecision:
    """Outcome of evaluating the exit policy against a set of findings."""

    should_fail: bool = False
    exit_code: int = 0
    reasons: List[str] = field(default_factory=list)
    severity_threshold: Optional[str] = None
    max_findings: Optional[int] = None
    relevant_count: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)


def evaluate_exit_policy(
    findings: List[Dict[str, Any]],
    *,
    strict: bool = False,
    error: bool = False,
    severity_threshold: Optional[str] = None,
    max_findings: int = 0,
) -> ExitDecision:
    """Decide whether a CI run should fail based on the findings.

    Args:
        findings: List of finding dicts. Each may carry ``severity``
                  (one of critical/high/medium/low/info). Missing
                  severity is treated as ``"unknown"``.
        strict: True if ``--strict`` was passed (threshold = low).
        error: True if ``--error`` was passed (threshold = high).
        severity_threshold: Explicit ``--severity-threshold <level>``.
                            Overrides strict/error when set.
        max_findings: ``--max-findings N``. 0 means no cap.

    Returns:
        ExitDecision with the verdict.

    Resolution of the effective severity threshold:
        1. ``severity_threshold`` (explicit, wins)
        2. ``strict`` → ``"low"``
        3. ``error``  → ``"high"``
        4. None → no severity gate (only ``--max-findings`` applies)
    """
    # Resolve the effective threshold. The CLI parser should make
    # these mutually exclusive via dest=, but we handle the priority
    # explicitly here in case a caller constructs args directly.
    effective_threshold: Optional[str] = None
    if severity_threshold:
        effective_threshold = severity_threshold.lower()
    elif strict:
        effective_threshold = "low"
    elif error:
        effective_threshold = "high"

    # Count by severity
    by_severity: Dict[str, int] = {}
    relevant_count = 0
    threshold_rank = (
        SEVERITY_RANK[effective_threshold] if effective_threshold else None
    )
    for f in findings:
        sev = str(f.get("severity") or "unknown").lower()
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if threshold_rank is not None:
            # A finding is "relevant" if its severity is at or above
            # the threshold. Lower rank number = more severe, so
            # finding_rank <= threshold_rank means it triggers.
            if severity_rank(sev) <= threshold_rank:
                relevant_count += 1
        else:
            # No severity gate — every finding counts toward max-findings.
            relevant_count += 1

    decision = ExitDecision(
        should_fail=False,
        exit_code=0,
        severity_threshold=effective_threshold,
        max_findings=max_findings if max_findings > 0 else None,
        relevant_count=relevant_count,
        by_severity=by_severity,
    )

    # ── Severity gate ──
    if effective_threshold:
        # Walk severities at or above the threshold and report any
        # non-zero counts as failure reasons.
        for sev in SEVERITY_ORDER:
            if SEVERITY_RANK[sev] > threshold_rank:
                break
            count = by_severity.get(sev, 0)
            if count > 0:
                decision.should_fail = True
                decision.reasons.append(
                    f"{count} {sev}-severity finding(s) at or above "
                    f"threshold '{effective_threshold}'"
                )

    # ── Max-findings cap ──
    if max_findings > 0 and relevant_count > max_findings:
        decision.should_fail = True
        decision.reasons.append(
            f"{relevant_count} relevant findings exceed --max-findings "
            f"cap of {max_findings}"
        )

    if decision.should_fail:
        decision.exit_code = 1

    return decision


__all__ = [
    "SEVERITY_ORDER",
    "SEVERITY_RANK",
    "severity_rank",
    "ExitDecision",
    "evaluate_exit_policy",
]
