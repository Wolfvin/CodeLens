"""
CodeLens baseline diff engine (issue #57, Phase 1).

Computes the delta between the current scan's findings and a previously
captured baseline, so CI can fail ONLY on newly introduced findings
instead of failing on every pre-existing issue.

Finding identity (per issue #57 spec):
    hash of (rule_id, file, line, severity)

This deliberately excludes:
- ``message`` text (wording may change between CodeLens versions
  without changing the underlying issue)
- ``column`` (small column drift from parser updates should NOT
  re-flag the same issue as "new")
- ``fix_version``, ``cve`` (these are enrichment fields, not identity)

A finding with the same (rule_id, file, line, severity) in both the
baseline and the current scan is considered ``preexisting``. Anything
in the current scan without a baseline match is ``new``. Anything in
the baseline but not the current scan is ``resolved``.

Persistence:
    Baselines are written to ``.codelens/baseline_<sha>.json`` so the
    same baseline can be reused across CI runs (e.g. on every PR push
    against the same base SHA). The file format is intentionally
    human-readable JSON so it can be committed to a repo or attached
    as a CI artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from utils import logger


# ─── Finding identity ──────────────────────────────────────────


def finding_identity(finding: Dict[str, Any]) -> str:
    """Compute a stable identity hash for a finding.

    Identity = SHA1 of ``|``-joined string of:
    - rule_id  (or "" if absent)
    - file     (relative path, or "" if absent)
    - line     (int, 0 if absent)
    - severity (lowercased, or "" if absent)

    Returns a 16-char hex string (truncated SHA1 — collisions at this
    cardinality are vanishingly rare for finding-sized datasets and
    the hash is only used as a set-membership key, never as a
    security primitive).
    """
    rule_id = str(finding.get("rule_id") or finding.get("rule") or "")
    # ``file`` may be absolute or relative. Normalise to forward slashes
    # so the same finding on Windows + Linux produces the same identity.
    file_path = str(finding.get("file") or finding.get("path") or "")
    file_path = file_path.replace("\\", "/")
    line = int(finding.get("line") or 0)
    severity = str(finding.get("severity") or "").lower()
    raw = f"{rule_id}|{file_path}|{line}|{severity}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalise_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of ``finding`` with ``_identity`` and ``_severity``
    fields attached (used by diff + exit-policy)."""
    out = dict(finding)
    out["_identity"] = finding_identity(finding)
    return out


# ─── Baseline persistence ──────────────────────────────────────


def baseline_path(workspace: str, sha: str) -> str:
    """Return the canonical path for a baseline file.

    Baselines live under ``<workspace>/.codelens/baseline_<sha>.json``.
    The ``.codelens`` directory is created lazily — callers should call
    :func:`save_baseline` which handles directory creation.
    """
    codelens_dir = os.path.join(workspace, ".codelens")
    return os.path.join(codelens_dir, f"baseline_{sha}.json")


def save_baseline(
    workspace: str, sha: str, findings: List[Dict[str, Any]]
) -> str:
    """Write ``findings`` to the baseline file for ``sha``.

    Returns the absolute path to the written file. The directory
    ``.codelens`` is created if it does not exist. Findings are stored
    in their original form (NOT normalised) plus a small metadata
    block for traceability.
    """
    path = baseline_path(workspace, sha)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "version": 1,
        "sha": sha,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "finding_count": len(findings),
        "findings": findings,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def load_baseline(
    workspace: str, sha: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Load the baseline for ``sha`` (or return None if missing).

    Returns the parsed JSON dict (with ``findings``, ``sha``,
    ``created_at``, etc.) or ``None`` if the baseline file does not
    exist, ``sha`` is falsy, or the file is corrupt.
    """
    if not sha:
        return None
    path = baseline_path(workspace, sha)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("baseline_diff: cannot load %s: %s", path, exc)
        return None


# ─── Diff computation ──────────────────────────────────────────


def diff_findings(
    current: List[Dict[str, Any]],
    baseline: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Compute the delta between current and baseline findings.

    Args:
        current: Findings from the current scan.
        baseline: Findings from a prior scan (may be None or empty →
                  everything is "new").

    Returns:
        Dict with:
        - ``new_findings``         : list of findings present in current
                                      but not in baseline
        - ``preexisting_findings`` : list of findings present in both
        - ``resolved_findings``    : list of findings present in
                                      baseline but not current
                                      (informational; CI gates usually
                                      ignore these)
        - ``total_findings``       : len(current)
        - ``delta_per_severity``   : {severity: Δ} where Δ is the change
                                      in count vs baseline (new − resolved
                                      for that severity). Positive means
                                      more findings than baseline.
        - ``summary``              : short human-readable string
    """
    baseline = baseline or []
    baseline_ids = {finding_identity(f) for f in baseline}
    current_ids = {finding_identity(f) for f in current}

    new_findings = [
        _normalise_finding(f) for f in current
        if finding_identity(f) not in baseline_ids
    ]
    preexisting_findings = [
        _normalise_finding(f) for f in current
        if finding_identity(f) in baseline_ids
    ]
    resolved_findings = [
        _normalise_finding(f) for f in baseline
        if finding_identity(f) not in current_ids
    ]

    # Per-severity delta
    sev_current: Dict[str, int] = {}
    for f in current:
        sev = str(f.get("severity") or "unknown").lower()
        sev_current[sev] = sev_current.get(sev, 0) + 1
    sev_baseline: Dict[str, int] = {}
    for f in baseline:
        sev = str(f.get("severity") or "unknown").lower()
        sev_baseline[sev] = sev_baseline.get(sev, 0) + 1

    all_sevs = sorted(set(sev_current) | set(sev_baseline))
    delta_per_severity: Dict[str, int] = {}
    for sev in all_sevs:
        delta_per_severity[sev] = (
            sev_current.get(sev, 0) - sev_baseline.get(sev, 0)
        )

    summary = (
        f"{len(new_findings)} new, {len(preexisting_findings)} preexisting, "
        f"{len(resolved_findings)} resolved "
        f"(baseline: {len(baseline)}, current: {len(current)})"
    )

    return {
        "new_findings": new_findings,
        "preexisting_findings": preexisting_findings,
        "resolved_findings": resolved_findings,
        "total_findings": len(current),
        "baseline_total": len(baseline),
        "delta_per_severity": delta_per_severity,
        "summary": summary,
    }


def filter_to_changed_files(
    findings: List[Dict[str, Any]],
    changed_files: List[str],
    workspace: str = "",
) -> List[Dict[str, Any]]:
    """Keep only findings whose file is in ``changed_files``.

    Used by ``--diff-scan`` / ``--staged`` / ``--diff-vs`` modes to
    narrow the scan result to only files git knows changed.

    Args:
        findings: Full list of findings from the current scan.
        changed_files: List of relative file paths from git diff.
        workspace: Optional workspace root used to normalise absolute
                   paths in ``findings`` to the same form git emits.

    Returns:
        Filtered list of findings. Findings without a ``file`` field
        are dropped (no way to map them to a changed file).
    """
    if not changed_files:
        return []
    # Normalise changed_files to forward-slash relative paths.
    changed_set = {p.replace("\\", "/") for p in changed_files}
    out: List[Dict[str, Any]] = []
    for f in findings:
        file_path = str(f.get("file") or f.get("path") or "")
        if not file_path:
            continue
        file_path = file_path.replace("\\", "/")
        # Strip workspace prefix if present so absolute paths match
        # the relative paths git emits.
        if workspace:
            ws_norm = workspace.replace("\\", "/").rstrip("/") + "/"
            if file_path.startswith(ws_norm):
                file_path = file_path[len(ws_norm):]
        if file_path in changed_set:
            out.append(f)
    return out


__all__ = [
    "finding_identity",
    "baseline_path",
    "save_baseline",
    "load_baseline",
    "diff_findings",
    "filter_to_changed_files",
]
