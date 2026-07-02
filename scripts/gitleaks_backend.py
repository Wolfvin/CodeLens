# @WHO:   scripts/gitleaks_backend.py
# @WHAT:  Gitleaks subprocess backend for `codelens secrets` (issue #159)
# @PART:  secrets
# @ENTRY: scan_with_gitleaks()
"""
Gitleaks Backend — optional high-accuracy secrets scanner (issue #159).

When gitleaks (https://github.com/gitleaks/gitleaks) is installed on the
system, ``codelens secrets`` uses it as the primary backend for its 600+
maintained rules, entropy scoring, and structured JSON output. When
gitleaks is not available, the existing regex-based scanner in
``secrets_engine.py`` runs unchanged — gitleaks is an opt-in upgrade,
never a hard dependency.

This module is intentionally self-contained:
- Detection (``_gitleaks_available``)
- Invocation (``_run_gitleaks``)
- Result normalization (``_normalize_gitleaks_findings``)
- Public entry point (``scan_with_gitleaks``)

The normalizer maps gitleaks JSON fields to the existing CodeLens
findings schema so downstream formatters (JSON, SARIF, compact) work
without changes.

@FLOW:    GITLEAKS_SCAN
@CALLS:   subprocess.run(['gitleaks', 'detect', ...]) -> JSON file
@MUTATES: none (writes only to a temp file, cleaned up after)
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Any, Dict, List, Optional

from utils import logger


# ─── Public entry point ──────────────────────────────────────


def scan_with_gitleaks(
    workspace: str,
    severity: Optional[str] = None,
    timeout: int = 120,
) -> Optional[Dict[str, Any]]:
    """Run gitleaks on ``workspace`` and return a CodeLens-shaped result.

    This is the primary entry point called by ``commands/secrets.py`` when
    gitleaks is detected. Returns ``None`` if gitleaks is not available
    (caller falls back to the regex scanner). Returns a result dict on
    success. Raises ``GitleaksError`` on invocation/parse failure — caller
    catches and falls back to regex.

    The returned dict matches the shape produced by
    ``secrets_engine.detect_secrets()`` so formatters work unchanged:
    ``{status, workspace, severity_filter, stats, risk, findings, ...}``
    plus a ``backend`` field set to ``"gitleaks"``.

    Args:
        workspace: Absolute path to the workspace root.
        severity: Optional severity filter (critical/high/medium/low).
            Gitleaks doesn't natively filter by severity, so we filter
            post-normalization.
        timeout: Subprocess timeout in seconds (default 120).

    Returns:
        Result dict, or ``None`` if gitleaks is not installed.

    Raises:
        GitleaksError: If gitleaks invocation fails or output is unparseable.
    """
    if not _gitleaks_available():
        return None

    workspace = os.path.abspath(workspace)
    if not os.path.isdir(workspace):
        raise GitleaksError(f"Workspace does not exist: {workspace}")

    raw_findings = _run_gitleaks(workspace, timeout=timeout)
    findings = _normalize_gitleaks_findings(raw_findings, workspace)

    # Post-filter by severity (gitleaks doesn't filter natively)
    if severity:
        findings = [f for f in findings if f.get("severity") == severity]

    stats = _compute_stats(findings)
    risk = _compute_risk(findings)

    return {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "backend": "gitleaks",
        "stats": stats,
        "risk": risk,
        "findings": findings[:200],  # Same cap as regex backend
        "env_exposed": [],  # gitleaks doesn't check .env/.gitignore
        "recommendations": _generate_recommendations(findings, stats),
        "files_scanned": stats["files_with_findings"],
        "files_skipped_oversized": 0,
        "files_skipped_regex_timeout": 0,
        "gitleaks_version": _gitleaks_version(),
    }


# ─── Detection ───────────────────────────────────────────────


def _gitleaks_available() -> bool:
    """Return True if the ``gitleaks`` binary is on PATH and callable.

    Uses ``gitleaks version`` (the lightest possible invocation) to
    confirm the binary exists and is executable. Never raises — returns
    False on any failure (binary not found, timeout, non-zero exit).
    """
    try:
        result = subprocess.run(
            ["gitleaks", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[gitleaks] version check timed out — treating as unavailable")
        return False
    except Exception as exc:
        logger.warning(f"[gitleaks] version check failed: {exc}")
        return False


def _gitleaks_version() -> Optional[str]:
    """Return the gitleaks version string, or None if unavailable."""
    try:
        result = subprocess.run(
            ["gitleaks", "version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return (result.stdout or result.stderr).strip()
    except Exception:
        pass
    return None


# ─── Invocation ──────────────────────────────────────────────


def _run_gitleaks(workspace: str, timeout: int = 120) -> List[Dict[str, Any]]:
    """Invoke ``gitleaks detect`` and return the parsed JSON findings list.

    Gitleaks writes JSON to a file (not stdout) when ``--report-format json``
    is used. We use a temp file and read it back. The ``--no-git`` flag
    scans the working tree only (no git history scan) to match the regex
    backend's behavior — git history scanning can be added later via a
    ``--git-history`` flag if needed.

    Gitleaks exits with code 1 when findings are discovered (by default).
    We pass ``--exit-code 0`` so the subprocess doesn't fail on findings —
    we handle the findings ourselves. Non-zero exit for any other reason
    (config error, invalid path) raises ``GitleaksError``.

    Args:
        workspace: Absolute path to scan.
        timeout: Subprocess timeout in seconds.

    Returns:
        List of gitleaks finding dicts (raw schema).

    Raises:
        GitleaksError: If gitleaks exits non-zero for a non-finding reason,
            times out, or produces unparseable output.
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="codelens_gitleaks_"
    ) as tmp:
        report_path = tmp.name

    try:
        cmd = [
            "gitleaks", "detect",
            "--source", workspace,
            "--report-format", "json",
            "--report-path", report_path,
            "--no-git",
            "--exit-code", "0",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitleaksError(
                f"gitleaks timed out after {timeout}s scanning {workspace}"
            ) from exc

        # exit code 0 = no findings OR findings (we forced --exit-code 0)
        # exit code > 0 = real error (config, invalid args, etc.)
        # Note: gitleaks may still write a valid JSON file (empty array) on
        # exit 0, so we parse the file regardless of exit code as long as
        # the file exists.
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise GitleaksError(
                f"gitleaks exited with code {result.returncode}: {stderr}"
            )

        if not os.path.exists(report_path):
            # No findings — gitleaks may skip writing the file
            return []

        try:
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if not content:
                return []
            data = json.loads(content)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "Results" in data:
                # Older gitleaks versions wrap results in a dict
                return data["Results"]
            return []
        except (json.JSONDecodeError, OSError) as exc:
            raise GitleaksError(f"Failed to parse gitleaks output: {exc}") from exc
    finally:
        try:
            os.unlink(report_path)
        except OSError:
            pass


# ─── Normalization ───────────────────────────────────────────


# Gitleaks severity isn't a native field — it's encoded in the RuleID or
# tags. We infer severity from the rule ID and tags heuristically.
def _infer_severity(rule_id: str, tags: List[str]) -> str:
    """Infer a CodeLens severity (critical/high/medium/low) from gitleaks metadata.

    Gitleaks rules don't have a structured severity field. We infer from:
    1. Tags containing severity keywords (e.g., "critical", "high")
    2. Rule ID containing severity keywords
    3. Rule ID containing high-value targets (aws-secret, private-key,
       github-pat) → critical
    4. Default → high (gitleaks rules are generally high-confidence)
    """
    rule_lower = (rule_id or "").lower()
    tags_lower = [str(t).lower() for t in (tags or [])]
    combined = " ".join([rule_lower] + tags_lower)

    if "critical" in combined:
        return "critical"
    # High-value secret types → critical. These are credentials that grant
    # real access (cloud accounts, source control, payments) — finding one
    # in source code is always critical regardless of the rule's tags.
    high_value_markers = (
        "aws-access", "aws-secret", "private-key", "github-pat", "gitlab-pat",
        "stripe-secret", "stripe-live", "slack-token", "slack-webhook",
        "jwt-secret", "service-account", "gcp-service-account",
    )
    if any(m in combined for m in high_value_markers):
        return "critical"
    if "high" in combined:
        return "high"
    if "medium" in combined:
        return "medium"
    if "low" in combined:
        return "low"
    # Default: gitleaks rules are curated, so default to high
    return "high"


def _mask_secret(secret: str) -> str:
    """Mask a secret value for safe display: first 4 chars + ***.

    Matches the masking convention used by the regex backend
    (``secrets_engine._mask_value``). Never returns the raw secret.
    """
    if not secret:
        return "***"
    if len(secret) <= 4:
        return "***"
    return secret[:4] + "***"


def _normalize_gitleaks_findings(
    raw_findings: List[Dict[str, Any]],
    workspace: str,
) -> List[Dict[str, Any]]:
    """Convert gitleaks JSON findings to CodeLens finding schema.

    Each gitleaks finding has this shape (v8+):
    ```
    {
        "Description": "AWS Access Key Variable",
        "StartLine": 42,
        "EndLine": 42,
        "StartColumn": 12,
        "EndColumn": 51,
        "Match": "AKIA...",
        "Secret": "AKIAIOSFODNN7EXAMPLE",
        "File": "src/config.py",
        "Repo": "myrepo",
        "RuleID": "aws-access-key",
        "Tags": ["aws", "key"],
        "Fingerprint": "abc123..."
    }
    ```

    Maps to CodeLens schema:
    ```
    {
        "type": "aws-access-key",          # RuleID
        "file": "src/config.py",            # File (relative)
        "line": 42,                         # StartLine
        "match": "AKIA***",                 # masked Secret
        "value": "AKIA***",                 # masked Secret (alias)
        "line_content": "",                 # gitleaks doesn't provide this
        "severity": "critical",             # inferred
        "category": "gitleaks",             # fixed
        "rule_id": "aws-access-key",        # RuleID (alias)
        "tags": ["aws", "key"],             # Tags
        "fingerprint": "abc123...",         # Fingerprint
        "backend": "gitleaks",              # provenance
    }
    ```
    """
    normalized: List[Dict[str, Any]] = []
    for raw in raw_findings:
        if not isinstance(raw, dict):
            continue
        rule_id = raw.get("RuleID", "unknown")
        tags = raw.get("Tags") or []
        if isinstance(tags, str):
            tags = [tags]
        secret = raw.get("Secret", "") or raw.get("Match", "")
        file_path = raw.get("File", "")
        # Gitleaks returns absolute paths in some versions — normalize to
        # relative if the file is under workspace.
        if file_path and os.path.isabs(file_path):
            try:
                file_path = os.path.relpath(file_path, workspace)
            except ValueError:
                # Windows cross-drive — keep as-is
                pass

        finding = {
            "type": rule_id,
            "file": file_path,
            "line": raw.get("StartLine", 0),
            "match": _mask_secret(secret),
            "value": _mask_secret(secret),
            "line_content": "",  # gitleaks doesn't provide line content
            "severity": _infer_severity(rule_id, tags),
            "category": "gitleaks",
            "rule_id": rule_id,
            "tags": tags,
            "fingerprint": raw.get("Fingerprint", ""),
            "backend": "gitleaks",
            "description": raw.get("Description", ""),
        }
        normalized.append(finding)
    return normalized


# ─── Stats / Risk / Recommendations ──────────────────────────
# These mirror the helpers in secrets_engine.py so the output shape is
# consistent. Duplicated rather than imported to avoid coupling — if
# secrets_engine changes its stats shape, the regex backend changes
# independently of the gitleaks backend.


def _compute_stats(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute stats dict matching the regex backend's shape."""
    by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    files_with_findings = set()
    for f in findings:
        sev = f.get("severity", "medium")
        if sev in by_severity:
            by_severity[sev] += 1
        if f.get("file"):
            files_with_findings.add(f["file"])

    return {
        "total": len(findings),
        "by_severity": by_severity,
        "files_with_findings": len(files_with_findings),
    }


def _compute_risk(findings: List[Dict[str, Any]]) -> str:
    """Compute risk level (critical/high/medium/low) from findings."""
    if not findings:
        return "low"
    by_severity = _compute_stats(findings)["by_severity"]
    if by_severity["critical"] > 0:
        return "critical"
    if by_severity["high"] > 0:
        return "high"
    if by_severity["medium"] > 0:
        return "medium"
    return "low"


def _generate_recommendations(
    findings: List[Dict[str, Any]],
    stats: Dict[str, Any],
) -> List[str]:
    """Generate actionable recommendations matching the regex backend's style."""
    recs: List[str] = []
    if not findings:
        recs.append("No secrets found. Continue to use environment variables for sensitive values.")
        return recs

    by_sev = stats.get("by_severity", {})
    if by_sev.get("critical", 0) > 0:
        recs.append(
            f"CRITICAL: {by_sev['critical']} critical-severity secret(s) found. "
            "Rotate these credentials immediately — they may already be compromised."
        )
    if by_sev.get("high", 0) > 0:
        recs.append(
            f"{by_sev['high']} high-severity secret(s) found. "
            "Move to environment variables or a secrets manager."
        )
    if by_sev.get("medium", 0) > 0:
        recs.append(
            f"{by_sev['medium']} medium-severity finding(s) — review for false positives."
        )
    recs.append("Add secrets to .env (and ensure .env is in .gitignore).")
    return recs


# ─── Exception ───────────────────────────────────────────────


class GitleaksError(Exception):
    """Raised when gitleaks invocation or output parsing fails.

    The caller (``commands/secrets.py``) catches this and falls back to
    the regex backend with a warning — gitleaks failure should never
    crash ``codelens secrets``.
    """
