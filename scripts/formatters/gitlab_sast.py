"""GitLab SAST JSON formatter for CodeLens (issue #52, Phase 2).

Generates GitLab's native security scan JSON format for direct
ingestion by GitLab CI's security dashboard. Findings appear in
Merge Request widgets, the Security & Compliance dashboard, and
vulnerability management flows — no custom parsing needed.

Format spec: https://docs.gitlab.com/ee/development/integrations/secure.html

Schema overview
---------------
Top-level object with:

* ``version`` — schema version (always "14.0.0" for current GitLab)
* ``vulnerabilities`` — array of vulnerability objects
* ``scan`` — metadata about the analyzer (CodeLens)

Each vulnerability object has:

* ``id`` — stable UUID-like identifier (deterministic from rule+location)
* ``category`` — always "sast" for CodeLens
* ``name``, ``message`` — short + long description
* ``cve`` — fallback ID (GitLab requires this field even for non-CVE)
* ``severity`` — one of ``Info``/``Unknown``/``Low``/``Medium``/``High``/``Critical``
* ``confidence`` — same enum as severity
* ``scanner`` — ``{"id": "codelens", "name": "CodeLens"}``
* ``location`` — ``{"file": "...", "start_line": N}``
* ``identifiers`` — array with rule_id + optional CWE

Severity mapping
----------------
CodeLens severity → GitLab severity:
  critical → Critical
  high     → High
  medium   → Medium
  low      → Low
  info     → Info
  (unknown) → Unknown

Suppressed findings are omitted — GitLab's vulnerability management
flow expects only actionable findings in the report.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List

from formatters.base import Finding, Severity, extract_findings


# Schema version — pinned to the GitLab Secure spec version CodeLens
# targets. Bumping this requires coordination with GitLab release notes.
SCHEMA_VERSION = "14.0.0"

# CodeLens severity → GitLab severity enum (capitalized, per spec).
_GITLAB_SEVERITY = {
    Severity.CRITICAL: "Critical",
    Severity.HIGH: "High",
    Severity.MEDIUM: "Medium",
    Severity.LOW: "Low",
    Severity.INFO: "Info",
    Severity.ERROR: "Critical",
    Severity.WARNING: "Medium",
}

# Default confidence — CodeLens engines don't always set this, but
# GitLab requires the field. Default to the severity-equivalent.
_DEFAULT_CONFIDENCE = "Medium"


def _stable_id(finding: Finding) -> str:
    """Generate a deterministic ID for a finding.

    GitLab expects a stable identifier so the same finding shows up
    as the same vulnerability across scans (not a new one each run).
    We hash rule_id + file + line + category — same inputs = same ID.

    Returns a hex string (GitLab accepts any string; hex is safe).
    """
    parts = [
        finding.rule_id or "",
        finding.file or "",
        str(finding.line or 0),
        finding.category or "",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _cwe_id(finding: Finding) -> str:
    """Extract a clean CWE identifier from finding.cwe.

    Engines sometimes emit ``"CWE-79"``, sometimes ``"79"``,
    sometimes ``"cwe-079"``. Normalize to ``"CWE-79"`` form.
    """
    if not finding.cwe:
        return ""
    cwe = finding.cwe.strip().upper()
    if cwe.startswith("CWE-"):
        # Already in correct form — just normalize the number.
        return cwe
    if cwe.isdigit():
        return f"CWE-{cwe}"
    return cwe


def _build_identifiers(finding: Finding) -> List[Dict[str, str]]:
    """Build the ``identifiers`` array for a GitLab vulnerability.

    Always includes the CodeLens rule_id. If the finding has a CWE,
    adds a CWE identifier too — GitLab uses this to enrich the
    vulnerability with external references.
    """
    identifiers: List[Dict[str, str]] = [{
        "type": "codelens_rule",
        "name": finding.rule_id or "codelens-finding",
        "value": finding.rule_id or finding.category or "codelens-finding",
        "url": "https://github.com/Wolfvin/CodeLens",
    }]
    cwe = _cwe_id(finding)
    if cwe:
        # CWE URL — official MITRE URL pattern.
        cwe_num = cwe.replace("CWE-", "")
        identifiers.append({
            "type": "cwe",
            "name": cwe,
            "value": cwe,
            "url": f"https://cwe.mitre.org/data/definitions/{cwe_num}.html",
        })
    return identifiers


def _build_vulnerability(finding: Finding, workspace: str = "") -> Dict[str, Any]:
    """Convert a single Finding to a GitLab vulnerability dict."""
    severity = _GITLAB_SEVERITY.get(finding.severity, "Unknown")
    # Confidence: use finding.confidence if set, else default.
    confidence = finding.confidence.capitalize() if finding.confidence else _DEFAULT_CONFIDENCE
    # Validate confidence is in GitLab's enum.
    if confidence not in ("Info", "Unknown", "Low", "Medium", "High", "Critical"):
        confidence = _DEFAULT_CONFIDENCE

    # File path — GitLab wants relative paths (relative to repo root).
    file_path = finding.file or ""
    if workspace and file_path.startswith(workspace):
        file_path = os.path.relpath(file_path, workspace)
    file_path = file_path.replace("\\", "/")

    # Build the vulnerability dict per GitLab Secure spec.
    vuln: Dict[str, Any] = {
        "id": _stable_id(finding),
        "category": "sast",
        "name": finding.message or finding.rule_id or "CodeLens finding",
        "message": finding.message or finding.rule_id or "CodeLens finding",
        "cve": _stable_id(finding),  # GitLab requires cve field even for non-CVE
        "severity": severity,
        "confidence": confidence,
        "scanner": {
            "id": "codelens",
            "name": "CodeLens",
        },
        "location": {
            "file": file_path,
            "start_line": max(1, finding.line or 0),
        },
        "identifiers": _build_identifiers(finding),
    }

    # Optional fields — only include if non-empty (GitLab's JSON schema
    # treats absent and null differently; absent is the safe default).
    if finding.end_line and finding.end_line > finding.line:
        vuln["location"]["end_line"] = finding.end_line
    if finding.snippet:
        # GitLab's ``source_code`` field — useful for showing the
        # vulnerable line in the MR widget.
        vuln["raw_source_code_extract"] = finding.snippet[:500]  # cap to avoid huge payloads

    return vuln


def format_gitlab_sast(data: Any, command: str = "", workspace: str = "") -> str:
    """Format CodeLens output as GitLab SAST JSON.

    Args:
        data: CodeLens command output dict.
        command: Command name (recorded in scan metadata).
        workspace: Workspace root (for relative path conversion).

    Returns:
        Valid GitLab Secure-format JSON string. Always a single JSON
        object at the top level — never an array, never JSONL.
    """
    findings = extract_findings(data, command)

    # Omit suppressed findings — GitLab's vulnerability management
    # expects only actionable findings in the report. Suppressed
    # findings should not create new vulnerability records.
    active = [f for f in findings if not f.suppressed]

    vulnerabilities = [_build_vulnerability(f, workspace) for f in active]

    # Scan metadata — GitLab uses this in the dashboard to show which
    # analyzer produced the report and when.
    scan = {
        "scanner": {
            "id": "codelens",
            "name": "CodeLens",
            "version": "8.2.0",  # CodeLens version (single source of truth would be better)
            "vendor": {
                "name": "Wolfvin",
            },
        },
        "type": "sast",
        "start_time": "",  # filled by caller in CI; empty for CLI use
        "end_time": "",
        "status": "success",
    }

    report = {
        "version": SCHEMA_VERSION,
        "vulnerabilities": vulnerabilities,
        "scan": scan,
    }

    return json.dumps(report, indent=2, ensure_ascii=False)
