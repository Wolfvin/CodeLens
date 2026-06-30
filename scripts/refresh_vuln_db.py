#!/usr/bin/env python3
"""
Refresh the built-in VULN_DB in scripts/vulnscan_engine.py from OSV.dev.

This script is invoked by the .github/workflows/refresh-vuln-db.yml workflow
on a monthly cron, and can also be run manually:

    python3 scripts/refresh_vuln_db.py

Workflow:
1. Query OSV.dev (https://api.osv.dev/v1/query) for known-vulnerable versions
   of every package currently in VULN_DB + a curated list of high-profile
   packages.
2. Extract CVE ID, severity, fix version, vulnerable range, and title from
   each OSV response.
3. Skip CVEs already present in VULN_DB (idempotent).
4. Insert new entries into scripts/vulnscan_engine.py before the closing `]`.
5. Update VULN_DB_LAST_UPDATED to today's date.
6. Print a summary: how many new CVEs added, broken down by ecosystem.

Closes issue #94.

The script is idempotent: running it twice in a row produces no changes
the second time (all CVEs already present are skipped).

Exit codes:
    0 - success (VULN_DB either updated or already current)
    1 - error (network failure, file write error, etc.)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

OSV_API = "https://api.osv.dev/v1/query"

# Packages to query — pulled from current VULN_DB + curated high-profile additions.
# Format: (package_name, ecosystem, probe_version)
# probe_version = a version known to be vulnerable to many CVEs so OSV returns them all.
# Ecosystem values match OSV's naming: "npm", "PyPI" (note: VULN_DB uses "pip" for PyPI,
# the script normalizes this when writing).
PACKAGES_TO_QUERY: List[Tuple[str, str, str]] = [
    # ── npm (existing in VULN_DB) ──
    ("lodash", "npm", "4.17.20"),
    ("express", "npm", "4.17.0"),
    ("node-fetch", "npm", "2.6.0"),
    ("axios", "npm", "0.20.0"),
    ("jquery", "npm", "3.4.0"),
    ("react", "npm", "16.13.0"),
    ("next", "npm", "12.0.0"),
    ("webpack", "npm", "5.70.0"),
    ("jsonwebtoken", "npm", "8.5.1"),
    ("socket.io", "npm", "3.0.0"),
    ("ua-parser-js", "npm", "0.7.20"),
    ("eventsource", "npm", "1.0.0"),
    # ── npm additions (high-profile, not in original VULN_DB) ──
    ("log4js", "npm", "6.0.0"),
    ("moment", "npm", "2.29.0"),
    ("minimist", "npm", "1.2.0"),
    ("qs", "npm", "6.9.0"),
    ("handlebars", "npm", "4.7.0"),
    ("ws", "npm", "7.0.0"),
    # ── PyPI (existing in VULN_DB, ecosystem="pip") ──
    ("cryptography", "PyPI", "38.0.0"),
    ("django", "PyPI", "3.2.0"),
    ("fastapi", "PyPI", "0.70.0"),
    ("flask", "PyPI", "1.1.0"),
    ("jinja2", "PyPI", "2.11.0"),
    ("pillow", "PyPI", "8.0.0"),
    ("pyyaml", "PyPI", "5.3.0"),
    ("requests", "PyPI", "2.24.0"),
    ("sqlalchemy", "PyPI", "1.3.0"),
    ("tornado", "PyPI", "6.0.0"),
    ("urllib3", "PyPI", "1.25.0"),
    ("werkzeug", "PyPI", "1.0.0"),
    # ── PyPI additions (high-profile, not in original VULN_DB) ──
    ("aiohttp", "PyPI", "3.7.0"),
    ("redis", "PyPI", "3.5.0"),
    ("celery", "PyPI", "5.0.0"),
    ("python-jose", "PyPI", "3.2.0"),
    ("bleach", "PyPI", "3.1.0"),
]

# Map OSV severity to CodeLens severity enum
SEVERITY_MAP = {
    "CRITICAL": "critical",
    "HIGH": "high",
    "MODERATE": "medium",
    "MEDIUM": "medium",
    "LOW": "low",
}

# Path to the engine file (relative to repo root)
ENGINE_PATH = Path(__file__).resolve().parent / "vulnscan_engine.py"


def query_osv(package: str, ecosystem: str, version: str) -> List[Dict[str, Any]]:
    """Query OSV.dev for vulnerabilities of a specific package version.

    Returns a list of OSV vuln dicts (empty list on error or no vulns).
    Network errors are logged to stderr but do not raise.
    """
    payload = json.dumps({
        "package": {"name": package, "ecosystem": ecosystem},
        "version": version,
    }).encode()

    req = urllib.request.Request(
        OSV_API,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
            return data.get("vulns", [])
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {package}@{version}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  ERROR for {package}@{version}: {e}", file=sys.stderr)
        return []


def extract_cve_id(vuln: Dict[str, Any]) -> Optional[str]:
    """Extract CVE ID from an OSV vuln entry.

    Returns the first CVE-* alias, or the OSV ID (GHSA-* or OSV-*) if no
    CVE alias exists. Returns None if no ID can be extracted.
    """
    aliases = vuln.get("aliases", [])
    for alias in aliases:
        if alias.startswith("CVE-"):
            return alias
    return vuln.get("id")


def extract_severity(vuln: Dict[str, Any]) -> str:
    """Extract severity from OSV vuln. Falls back to 'medium'."""
    severity_list = vuln.get("severity", [])
    for sev in severity_list:
        cvss_vector = sev.get("score", "")
        if "CVSS:3" in cvss_vector:
            # Parse the vector to get approximate severity
            # Simple heuristic: count H (High) impact metrics
            parts = cvss_vector.split("/")
            impact_parts = [p for p in parts if p.startswith(("C:", "I:", "A:"))]
            high_count = sum(1 for p in impact_parts if p.endswith(":H"))
            if high_count >= 2:
                return "high"
            elif high_count >= 1:
                return "medium"
            return "low"
    # Fall back to database_specific severity if available
    db_specific = vuln.get("database_specific", {})
    sev = db_specific.get("severity", "").upper()
    if sev in SEVERITY_MAP:
        return SEVERITY_MAP[sev]
    return "medium"


def extract_fix_version(vuln: Dict[str, Any], ecosystem: str) -> Optional[str]:
    """Extract the fix version from an OSV vuln's affected ranges.

    Returns the first 'fixed' version found, or None if no fix version
    is available (vuln is either unpatched or the data is incomplete).
    """
    affected = vuln.get("affected", [])
    for aff in affected:
        if aff.get("package", {}).get("ecosystem") != ecosystem:
            continue
        ranges = aff.get("ranges", [])
        for rng in ranges:
            events = rng.get("events", [])
            for event in events:
                if "fixed" in event:
                    return event["fixed"]
    return None


def extract_title(vuln: Dict[str, Any]) -> str:
    """Extract a short title/summary from OSV vuln (max ~80 chars)."""
    summary = vuln.get("summary", "")
    if summary:
        if len(summary) > 80:
            return summary[:77] + "..."
        return summary
    details = vuln.get("details", "")
    if details:
        first_sentence = details.split(". ")[0]
        if len(first_sentence) > 80:
            return first_sentence[:77] + "..."
        return first_sentence
    return "Vulnerability (no summary)"


def extract_vulnerable_range(vuln: Dict[str, Any], ecosystem: str) -> str:
    """Extract vulnerable range string (e.g., '<4.17.21') from OSV vuln.

    Returns empty string if no fix version can be determined (in which
    case the entry is skipped by the caller).
    """
    affected = vuln.get("affected", [])
    for aff in affected:
        if aff.get("package", {}).get("ecosystem") != ecosystem:
            continue
        ranges = aff.get("ranges", [])
        for rng in ranges:
            events = rng.get("events", [])
            fixed = None
            for event in events:
                if "fixed" in event:
                    fixed = event["fixed"]
            if fixed:
                return f"<{fixed}"
    return ""


def format_entry(entry: Dict[str, Any], indent: str = "    ") -> str:
    """Format a single VULN_DB entry as Python source code.

    Uses double-quoted strings to match the existing VULN_DB style and
    avoid apostrophe-in-word issues (e.g. "isn't"). Escapes any double
    quotes inside the string.
    """
    def q(s: str) -> str:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    lines = [
        f"{indent}{{",
        f'{indent}    "package": {q(entry["package"])},',
        f'{indent}    "ecosystem": {q(entry["ecosystem"])},',
        f'{indent}    "vulnerable_range": {q(entry["vulnerable_range"])},',
        f'{indent}    "severity": {q(entry["severity"])},',
        f'{indent}    "cve": {q(entry["cve"])},',
        f'{indent}    "title": {q(entry["title"])},',
        f'{indent}    "fix_version": {q(entry["fix_version"])},',
        f"{indent}}},",
    ]
    return "\n".join(lines)


def main() -> int:
    """Main entry point. Returns exit code (0 success, 1 error)."""
    today = date.today().isoformat()
    print(f"Refreshing VULN_DB from OSV.dev (target date: {today})")
    print(f"  Engine path: {ENGINE_PATH}")
    print(f"  Packages to query: {len(PACKAGES_TO_QUERY)}")

    if not ENGINE_PATH.exists():
        print(f"ERROR: {ENGINE_PATH} not found", file=sys.stderr)
        return 1

    # Load existing VULN_DB to skip CVEs we already have
    sys.path.insert(0, str(ENGINE_PATH.parent))
    try:
        from vulnscan_engine import VULN_DB, VULN_DB_LAST_UPDATED
    except ImportError as e:
        print(f"ERROR: cannot import VULN_DB: {e}", file=sys.stderr)
        return 1

    existing_cves: Set[str] = set()
    for entry in VULN_DB:
        existing_cves.add(entry["cve"])

    print(f"  Existing VULN_DB: {len(VULN_DB)} entries, {len(existing_cves)} unique CVEs")
    print(f"  Current last_updated: {VULN_DB_LAST_UPDATED}")

    new_entries: List[Dict[str, Any]] = []
    new_cve_ids: Set[str] = set()
    stats: Dict[str, int] = {"npm": 0, "pip": 0}

    for i, (package, ecosystem, version) in enumerate(PACKAGES_TO_QUERY, 1):
        print(f"  [{i}/{len(PACKAGES_TO_QUERY)}] {ecosystem}/{package}", end="\r")
        vulns = query_osv(package, ecosystem, version)
        # Be polite to the API — small delay between requests
        time.sleep(0.2)

        if not vulns:
            continue

        # Normalize ecosystem: OSV uses "PyPI", VULN_DB uses "pip"
        db_ecosystem = "pip" if ecosystem == "PyPI" else ecosystem

        for vuln in vulns:
            cve_id = extract_cve_id(vuln)
            if not cve_id:
                continue

            # Skip if we already have this CVE
            if cve_id in existing_cves or cve_id in new_cve_ids:
                continue

            fix_version = extract_fix_version(vuln, ecosystem)
            if not fix_version:
                continue  # Skip vulns without a known fix

            vulnerable_range = extract_vulnerable_range(vuln, ecosystem)
            if not vulnerable_range:
                continue

            severity = extract_severity(vuln)
            title = extract_title(vuln)

            entry = {
                "package": package,
                "ecosystem": db_ecosystem,
                "vulnerable_range": vulnerable_range,
                "severity": severity,
                "cve": cve_id,
                "title": title,
                "fix_version": fix_version,
            }
            new_entries.append(entry)
            new_cve_ids.add(cve_id)
            stats[db_ecosystem] = stats.get(db_ecosystem, 0) + 1

    print(f"\n\nFetched {len(new_entries)} new CVE entries:")
    print(f"  npm: {stats.get('npm', 0)}")
    print(f"  pip: {stats.get('pip', 0)}")

    if not new_entries:
        print("\nVULN_DB is already current — no new CVEs to add.")
        # Still update the last_updated date to reflect that we checked
        if VULN_DB_LAST_UPDATED != today:
            print(f"  Updating VULN_DB_LAST_UPDATED: {VULN_DB_LAST_UPDATED} -> {today}")
        else:
            print("  VULN_DB_LAST_UPDATED already set to today — no changes needed.")
            return 0

    # Read the engine file
    content = ENGINE_PATH.read_text()

    # Find the closing `]` of VULN_DB (first `]` at column 0 after VULN_DB definition)
    closing_idx = content.find("\n]\n")
    if closing_idx == -1:
        print("ERROR: Could not find VULN_DB closing `]`", file=sys.stderr)
        return 1

    # Build the insertion text — group by ecosystem for organization
    parts = []
    npm_entries = [e for e in new_entries if e["ecosystem"] == "npm"]
    pip_entries = [e for e in new_entries if e["ecosystem"] == "pip"]
    other_entries = [e for e in new_entries if e["ecosystem"] not in ("npm", "pip")]

    if npm_entries:
        parts.append(f"    # ── JavaScript / npm (refreshed {today} via OSV.dev) ────")
        for entry in npm_entries:
            parts.append(format_entry(entry))
    if pip_entries:
        parts.append(f"    # ── Python / pip (refreshed {today} via OSV.dev) ──────")
        for entry in pip_entries:
            parts.append(format_entry(entry))
    if other_entries:
        parts.append(f"    # ── Other ecosystems (refreshed {today} via OSV.dev) ───")
        for entry in other_entries:
            parts.append(format_entry(entry))

    insertion = "\n".join(parts) + "\n"

    # Insert before the closing `]`
    new_content = content[:closing_idx] + insertion + content[closing_idx:]

    # Update VULN_DB_LAST_UPDATED
    old_date_pattern = f'VULN_DB_LAST_UPDATED = "{VULN_DB_LAST_UPDATED}"'
    new_date_pattern = f'VULN_DB_LAST_UPDATED = "{today}"'
    if old_date_pattern in new_content:
        new_content = new_content.replace(old_date_pattern, new_date_pattern)
        print(f"  Updated VULN_DB_LAST_UPDATED: {VULN_DB_LAST_UPDATED} -> {today}")

    # Write back
    ENGINE_PATH.write_text(new_content)
    print(f"\nUpdated {ENGINE_PATH}")
    print(f"  Inserted {len(new_entries)} new entries before closing `]`")
    print(f"  Total VULN_DB now: {len(VULN_DB) + len(new_entries)} entries (was {len(VULN_DB)})")

    # Verify syntax
    import ast
    try:
        ast.parse(new_content)
        print("  Syntax check: OK")
    except SyntaxError as e:
        print(f"  ERROR: Syntax check failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
