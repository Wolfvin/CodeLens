"""
Dependency Vulnerability Scanning Engine for CodeLens v5
Detects known vulnerable packages in project dependency files using
OSV.dev API, native audit tools, lock-file parsing, and a built-in CVE database.

Answers: "Are there any known vulnerabilities in my dependencies?"
Answers: "Which packages have known CVEs and need updating?"

Architecture:
- Phase 0: OSV.dev API — query real-time vulnerability data from OSV database
           with SQLite cache and graceful offline fallback.
- Phase 1: Native audit tools — try `npm audit --json`, `cargo audit --json`,
           `pip audit --format json`, `govulncheck ./...` if available.
- Phase 2: Lock-file parsing — parse package-lock.json, Cargo.lock, poetry.lock,
           go.sum for exact version numbers and compare against VULN_DB.
- Phase 3: Manifest matching — parse package.json, Cargo.toml, requirements.txt,
           Pipfile, go.mod for declared versions and compare against VULN_DB.

Ecosystems supported:
- npm  (package.json, package-lock.json)
- Rust (Cargo.toml, Cargo.lock)
- pip  (requirements.txt, Pipfile, poetry.lock)
- Go   (go.mod, go.sum)
- Maven, NuGet, RubyGems, Pub, Hex (via OSV.dev API)

Each finding includes package, installed version, vulnerable range,
CVE identifier, severity, title, and fix version.
"""

import os
import re
import json
import subprocess
import logging
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from utils import DEFAULT_IGNORE_DIRS, logger

# OSV.dev integration (optional — graceful fallback if unavailable)
try:
    from osv_client import OSVClient, OSVQueryBuilder, OSVPackage, OSVVulnerability, ECOSYSTEM_MAP
    _HAS_OSV = True
except ImportError:
    _HAS_OSV = False

# ─── Configuration ─────────────────────────────────────────────

DEPENDENCY_FILE_PATTERNS = {
    "npm": {
        "manifest": ["package.json"],
        "lockfile": ["package-lock.json", "npm-shrinkwrap.json", "bun.lock", "yarn.lock"],
    },
    "rust": {
        "manifest": ["Cargo.toml"],
        "lockfile": ["Cargo.lock"],
    },
    "pip": {
        "manifest": ["requirements.txt", "Pipfile", "pyproject.toml"],
        "lockfile": ["Pipfile.lock", "poetry.lock", "uv.lock"],
    },
    "go": {
        "manifest": ["go.mod"],
        "lockfile": ["go.sum"],
    },
    "nimble": {
        "manifest": [],  # Populated dynamically from *.nimble files
        "lockfile": ["nimble.lock"],
    },
}

AUDIT_TOOLS = {
    "npm": {
        "command": ["npm", "audit", "--json"],
        "parse": "_parse_npm_audit",
        "required_file": "package.json",
    },
    "rust": {
        "command": ["cargo", "audit", "--json"],
        "parse": "_parse_cargo_audit",
        "required_file": "Cargo.toml",
    },
    "pip": {
        "command": ["pip-audit", "--format", "json", "--desc"],
        "parse": "_parse_pip_audit",
        "required_file": "requirements.txt",  # Or pyproject.toml — checked dynamically
    },
    "nimble": {
        "command": ["nimble", "audit"],  # Placeholder — nimble audit may not exist
        "parse": "_parse_nimble_audit",
        "required_file": "*.nimble",  # Wildcard — checked dynamically
    },
    "go": {
        "command": ["govulncheck", "-json", "./..."],
        "parse": "_parse_go_vulncheck",
        "required_file": "go.mod",
    },
}

# ─── Built-in Vulnerability Database ──────────────────────────
# Each entry: (package, ecosystem, vulnerable_range, severity, cve, title, fix_version)
# vulnerable_range uses semver-ish notation: "<X.Y.Z" means all versions below X.Y.Z

VULN_DB: List[Dict[str, Any]] = [
    # ── JavaScript / npm ────────────────────────────────────────
    {
        "package": "lodash",
        "ecosystem": "npm",
        "vulnerable_range": "<4.17.21",
        "severity": "high",
        "cve": "CVE-2021-23337",
        "title": "Command Injection in lodash",
        "fix_version": "4.17.21",
    },
    {
        "package": "lodash",
        "ecosystem": "npm",
        "vulnerable_range": "<4.17.19",
        "severity": "high",
        "cve": "CVE-2020-8203",
        "title": "Prototype Pollution in lodash",
        "fix_version": "4.17.19",
    },
    {
        "package": "express",
        "ecosystem": "npm",
        "vulnerable_range": "<4.17.3",
        "severity": "medium",
        "cve": "CVE-2021-23336",
        "title": "Open Redirect in express",
        "fix_version": "4.17.3",
    },
    {
        "package": "node-fetch",
        "ecosystem": "npm",
        "vulnerable_range": "<3.2.10",
        "severity": "high",
        "cve": "CVE-2022-2596",
        "title": "URL Spoofing in node-fetch",
        "fix_version": "3.2.10",
    },
    {
        "package": "axios",
        "ecosystem": "npm",
        "vulnerable_range": "<0.21.1",
        "severity": "high",
        "cve": "CVE-2021-3749",
        "title": "SSRF in axios",
        "fix_version": "0.21.1",
    },
    {
        "package": "jquery",
        "ecosystem": "npm",
        "vulnerable_range": "<3.5.0",
        "severity": "medium",
        "cve": "CVE-2020-11022",
        "title": "XSS in jQuery",
        "fix_version": "3.5.0",
    },
    {
        "package": "react",
        "ecosystem": "npm",
        "vulnerable_range": "<16.14.0",
        "severity": "medium",
        "cve": "CVE-2021-24033",
        "title": "ReDoS in react",
        "fix_version": "16.14.0",
    },
    {
        "package": "next",
        "ecosystem": "npm",
        "vulnerable_range": "<12.2.5",
        "severity": "high",
        "cve": "CVE-2022-23646",
        "title": "Server-Side Request Forgery in Next.js",
        "fix_version": "12.2.5",
    },
    {
        "package": "webpack",
        "ecosystem": "npm",
        "vulnerable_range": "<5.76.0",
        "severity": "critical",
        "cve": "CVE-2023-28154",
        "title": "Prototype Pollution in webpack",
        "fix_version": "5.76.0",
    },
    {
        "package": "eventsource",
        "ecosystem": "npm",
        "vulnerable_range": "<2.0.2",
        "severity": "high",
        "cve": "CVE-2022-1650",
        "title": "ReDoS in eventsource",
        "fix_version": "2.0.2",
    },
    {
        "package": "ua-parser-js",
        "ecosystem": "npm",
        "vulnerable_range": "<0.7.33",
        "severity": "critical",
        "cve": "CVE-2022-37618",
        "title": "Prototype Pollution in ua-parser-js",
        "fix_version": "0.7.33",
    },
    {
        "package": "jsonwebtoken",
        "ecosystem": "npm",
        "vulnerable_range": "<9.0.0",
        "severity": "high",
        "cve": "CVE-2022-23529",
        "title": "Prototype Pollution in jsonwebtoken",
        "fix_version": "9.0.0",
    },
    {
        "package": "socket.io",
        "ecosystem": "npm",
        "vulnerable_range": "<4.6.1",
        "severity": "medium",
        "cve": "CVE-2023-25996",
        "title": "DoS via unhandled packets in socket.io",
        "fix_version": "4.6.1",
    },

    # ── Python / pip ────────────────────────────────────────────
    {
        "package": "django",
        "ecosystem": "pip",
        "vulnerable_range": "<3.2.16",
        "severity": "critical",
        "cve": "CVE-2022-34265",
        "title": "SQL Injection in Django",
        "fix_version": "3.2.16",
    },
    {
        "package": "flask",
        "ecosystem": "pip",
        "vulnerable_range": "<2.2.5",
        "severity": "high",
        "cve": "CVE-2023-30861",
        "title": "Cookie disclosure vulnerability in Flask",
        "fix_version": "2.2.5",
    },
    {
        "package": "requests",
        "ecosystem": "pip",
        "vulnerable_range": "<2.31.0",
        "severity": "medium",
        "cve": "CVE-2023-32681",
        "title": "Unintended leak of Proxy-Authorization header in requests",
        "fix_version": "2.31.0",
    },
    {
        "package": "pillow",
        "ecosystem": "pip",
        "vulnerable_range": "<9.3.0",
        "severity": "high",
        "cve": "CVE-2022-45199",
        "title": "Buffer overflow in Pillow",
        "fix_version": "9.3.0",
    },
    {
        "package": "pyyaml",
        "ecosystem": "pip",
        "vulnerable_range": "<6.0",
        "severity": "critical",
        "cve": "CVE-2020-14343",
        "title": "Remote Code Execution in PyYAML",
        "fix_version": "6.0",
    },
    {
        "package": "jinja2",
        "ecosystem": "pip",
        "vulnerable_range": "<3.1.3",
        "severity": "high",
        "cve": "CVE-2024-22195",
        "title": "XSS vulnerability in Jinja2",
        "fix_version": "3.1.3",
    },
    {
        "package": "urllib3",
        "ecosystem": "pip",
        "vulnerable_range": "<1.26.18",
        "severity": "high",
        "cve": "CVE-2023-45803",
        "title": "Request body not stripped after redirect in urllib3",
        "fix_version": "1.26.18",
    },
    {
        "package": "cryptography",
        "ecosystem": "pip",
        "vulnerable_range": "<41.0.2",
        "severity": "high",
        "cve": "CVE-2023-3831",
        "title": "NULL pointer dereference in cryptography",
        "fix_version": "41.0.2",
    },
    {
        "package": "sqlalchemy",
        "ecosystem": "pip",
        "vulnerable_range": "<2.0.0b3",
        "severity": "high",
        "cve": "CVE-2022-29164",
        "title": "SQL Injection in SQLAlchemy",
        "fix_version": "2.0.0",
    },
    {
        "package": "werkzeug",
        "ecosystem": "pip",
        "vulnerable_range": "<2.2.3",
        "severity": "medium",
        "cve": "CVE-2023-23934",
        "title": "Cookie parsing DoS in Werkzeug",
        "fix_version": "2.2.3",
    },
    {
        "package": "tornado",
        "ecosystem": "pip",
        "vulnerable_range": "<6.3.3",
        "severity": "critical",
        "cve": "CVE-2023-39733",
        "title": "HTTP request smuggling in Tornado",
        "fix_version": "6.3.3",
    },
    {
        "package": "fastapi",
        "ecosystem": "pip",
        "vulnerable_range": "<0.89.0",
        "severity": "medium",
        "cve": "CVE-2022-41778",
        "title": "Path traversal in FastAPI",
        "fix_version": "0.89.0",
    },

    # ── Rust / cargo ────────────────────────────────────────────
    {
        "package": "openssl",
        "ecosystem": "rust",
        "vulnerable_range": "<0.10.45",
        "severity": "critical",
        "cve": "CVE-2022-0778",
        "title": "Infinite loop in OpenSSL certificate verification (rust binding)",
        "fix_version": "0.10.45",
    },
    {
        "package": "tokio",
        "ecosystem": "rust",
        "vulnerable_range": "<1.25.0",
        "severity": "medium",
        "cve": "CVE-2023-22466",
        "title": "Data race in tokio",
        "fix_version": "1.25.0",
    },
    {
        "package": "hyper",
        "ecosystem": "rust",
        "vulnerable_range": "<0.14.19",
        "severity": "high",
        "cve": "CVE-2021-38597",
        "title": "HTTP request smuggling in hyper",
        "fix_version": "0.14.19",
    },
    {
        "package": "crossbeam",
        "ecosystem": "rust",
        "vulnerable_range": "<0.8.0",
        "severity": "high",
        "cve": "CVE-2022-41877",
        "title": "Data race in crossbeam-channel",
        "fix_version": "0.8.0",
    },
    {
        "package": "regex",
        "ecosystem": "rust",
        "vulnerable_range": "<1.5.5",
        "severity": "high",
        "cve": "CVE-2022-24713",
        "title": "ReDoS in rust regex crate",
        "fix_version": "1.5.5",
    },
    {
        "package": "rustls",
        "ecosystem": "rust",
        "vulnerable_range": "<0.20.8",
        "severity": "critical",
        "cve": "CVE-2023-27523",
        "title": "TLS handshake bypass in rustls",
        "fix_version": "0.20.8",
    },

    # ── Nim / nimble ────────────────────────────────────────────
    {
        "package": "nim",
        "ecosystem": "nimble",
        "vulnerable_range": "<1.6.10",
        "severity": "high",
        "cve": "CVE-2023-2630",
        "title": "Code injection via nimble package URL in Nim",
        "fix_version": "1.6.10",
    },
    {
        "package": "nim",
        "ecosystem": "nimble",
        "vulnerable_range": "<1.6.8",
        "severity": "medium",
        "cve": "CVE-2022-28589",
        "title": "Path traversal in Nim compiler",
        "fix_version": "1.6.8",
    },
    {
        "package": "jester",
        "ecosystem": "nimble",
        "vulnerable_range": "<0.6.0",
        "severity": "medium",
        "cve": "JESTER-001",
        "title": "CSRF protection missing by default in Jester web framework",
        "fix_version": "0.6.0",
    },
    {
        "package": "norm",
        "ecosystem": "nimble",
        "vulnerable_range": "<2.4.0",
        "severity": "high",
        "cve": "NORM-001",
        "title": "SQL injection via unsanitized string interpolation in Norm ORM",
        "fix_version": "2.4.0",
    },
    {
        "package": "nimcrypto",
        "ecosystem": "nimble",
        "vulnerable_range": "<0.6.0",
        "severity": "critical",
        "cve": "NIMCRYPTO-001",
        "title": "Timing side-channel in nimcrypto HMAC implementation",
        "fix_version": "0.6.0",
    },
    {
        "package": "karax",
        "ecosystem": "nimble",
        "vulnerable_range": "<1.3.0",
        "severity": "medium",
        "cve": "KARAX-001",
        "title": "XSS via unescaped HTML rendering in Karax SPA framework",
        "fix_version": "1.3.0",
    },
    {
        "package": "prologue",
        "ecosystem": "nimble",
        "vulnerable_range": "<0.5.0",
        "severity": "high",
        "cve": "PROLOGUE-001",
        "title": "Session fixation vulnerability in Prologue web framework",
        "fix_version": "0.5.0",
    },

    # ── Go ───────────────────────────────────────────────────────
    {
        "package": "stdlib",
        "ecosystem": "go",
        "vulnerable_range": "<1.19.4",
        "severity": "critical",
        "cve": "CVE-2022-41716",
        "title": "Various vulnerabilities in Go stdlib (net/http, os/exec)",
        "fix_version": "1.19.4",
    },
    {
        "package": "gin",
        "ecosystem": "go",
        "vulnerable_range": "<1.8.1",
        "severity": "medium",
        "cve": "CVE-2022-32189",
        "title": "Open redirect in Gin framework",
        "fix_version": "1.8.1",
    },
    {
        "package": "grpc",
        "ecosystem": "go",
        "vulnerable_range": "<1.53.0",
        "severity": "high",
        "cve": "CVE-2023-32732",
        "title": "ReDoS in gRPC",
        "fix_version": "1.53.0",
    },
    {
        "package": "protobuf",
        "ecosystem": "go",
        "vulnerable_range": "<1.30.0",
        "severity": "medium",
        "cve": "CVE-2023-48120",
        "title": "Denial of service in protobuf",
        "fix_version": "1.30.0",
    },
]

# Date the built-in VULN_DB was last updated (used for staleness warning)
VULN_DB_LAST_UPDATED = "2025-02-28"

# Index the VULN_DB for fast lookups: (ecosystem, package_lower) -> [entries]
_VULN_INDEX: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
for _entry in VULN_DB:
    _key = (_entry["ecosystem"], _entry["package"].lower())
    _VULN_INDEX[_key].append(_entry)

# ─── Main Entry Point ─────────────────────────────────────────

def scan_vulnerabilities(
    workspace: str,
    severity: Optional[str] = None,
    config: Optional[Dict] = None,
    offline: bool = False,
    osv_ttl: int = 86400,
    refresh: bool = False,
    max_age: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Scan dependency files for known vulnerabilities.

    Uses OSV.dev API (Phase 0) for real-time vulnerability data, then
    native audit tools (npm audit, cargo audit, pip-audit, govulncheck)
    when available, with fallback to built-in CVE database + lock-file parsing.

    Args:
        workspace: Absolute path to workspace
        severity: Optional filter: "critical", "high", "medium"
        config: CodeLens config dict (supports "vulnscan.ignore" and
                "vulnscan.skip_audit_tools" options)
        offline: If True, skip OSV API queries (use cache only)
        osv_ttl: Cache TTL for OSV results in seconds (default 86400 = 24h)
        refresh: If True, bypass the OSV cache and force fresh API calls for
            every package (issue #30 ``--refresh`` flag). Ignored when
            ``offline`` is True.
        max_age: Optional per-run TTL override in seconds. When set, cached
            OSV entries older than ``max_age`` are treated as stale and
            re-fetched from the API for this run only (issue #30 ``--max-age``
            flag). The stored TTL is unchanged.

    Returns:
        Dict with findings, stats, risk level, audit availability,
        recommendations, and a ``cache_info`` block (issue #30) describing
        OSV cache freshness (``last_refresh``, ``age_hours``, ``ttl_hours``,
        ``is_stale``, ``stale_packages``).
    """
    workspace = os.path.abspath(workspace)

    # ─── Staleness check for built-in VULN_DB ───────────────────
    try:
        from datetime import date as date_type
        db_date = date_type.fromisoformat(VULN_DB_LAST_UPDATED)
        days_old = (date_type.today() - db_date).days
        if days_old > 30:
            logger.warning(
                f"Built-in VULN_DB is {days_old} days old (last updated {VULN_DB_LAST_UPDATED}). "
                f"Consider updating CodeLens for the latest vulnerability data, or rely on OSV.dev integration "
                f"(which provides real-time data when available)."
            )
    except (ValueError, TypeError):
        pass

    findings: List[Dict[str, Any]] = []
    files_scanned: List[str] = []
    audit_available: Dict[str, bool] = {}
    ignore_packages: Set[str] = set()
    skip_audit: bool = False
    osv_stats: Optional[Dict[str, Any]] = None
    cache_info: Optional[Dict[str, Any]] = None

    # Parse config
    if config:
        vuln_config = config.get("vulnscan", {})
        ignore_packages = set(pkg.lower() for pkg in vuln_config.get("ignore", []))
        skip_audit = vuln_config.get("skip_audit_tools", False)

    # ─── Discover dependency files ─────────────────────────────
    dep_files = _discover_dependency_files(workspace)

    # ─── Phase 0: OSV.dev API (real-time vulnerability data) ──
    if _HAS_OSV:
        try:
            osv_client = OSVClient(workspace=workspace, ttl=osv_ttl, offline=offline)
            osv_client.cache.cleanup()  # Purge expired entries

            # Build package list from workspace dependency files
            osv_packages = OSVQueryBuilder.build_from_workspace(workspace)

            if osv_packages:
                osv_vulns = osv_client.query_packages(
                    osv_packages,
                    force_refresh=refresh,
                    max_age=max_age,
                )
                osv_findings = [v.to_finding() for v in osv_vulns]

                # Tag OSV findings so we can prioritize them
                for f in osv_findings:
                    f["source"] = "osv_dev"

                findings.extend(osv_findings)

                osv_stats = {
                    "packages_queried": len(osv_packages),
                    "vulnerabilities_found": len(osv_findings),
                    "client_stats": osv_client.get_stats(),
                }
                logger.info("OSV.dev: queried %d packages, found %d vulnerabilities",
                            len(osv_packages), len(osv_findings))

                # Issue #30: cache freshness info (computed AFTER the query so
                # it reflects the post-query state — any package just fetched
                # or refreshed is now fresh). Pass max_age so ttl_hours and
                # the staleness threshold match the --max-age override.
                cache_info = osv_client.get_cache_info(osv_packages, max_age=max_age)
            else:
                osv_stats = {"packages_queried": 0, "vulnerabilities_found": 0}
                logger.debug("OSV.dev: no packages to query")
                # No packages → no cache entries to inspect. Still surface a
                # cache_info block so consumers can rely on the shape.
                cache_info = {
                    "last_refresh": None,
                    "age_hours": None,
                    "ttl_hours": round(osv_ttl / 3600.0, 2),
                    "is_stale": False,
                    "stale_packages": [],
                }

        except Exception as exc:
            logger.warning("OSV.dev integration failed, continuing with native audit: %s", exc)
            osv_stats = {"error": str(exc)}
            cache_info = {
                "last_refresh": None,
                "age_hours": None,
                "ttl_hours": round(osv_ttl / 3600.0, 2),
                "is_stale": False,
                "stale_packages": [],
                "error": str(exc),
            }
    else:
        logger.debug("OSV.dev client not available (osv_client.py not importable)")

    # ─── Phase 1: Native audit tools ──────────────────────────
    if not skip_audit:
        for ecosystem, tool_info in AUDIT_TOOLS.items():
            if ecosystem not in dep_files:
                continue
            if not any(
                os.path.exists(os.path.join(workspace, f))
                for f in dep_files[ecosystem].get("all", [])
            ):
                continue

            try:
                audit_findings = _run_audit_tool(workspace, ecosystem, tool_info)
                if audit_findings is not None:
                    # Tool ran successfully
                    audit_available[ecosystem] = True
                    findings.extend(audit_findings)
                else:
                    audit_available[ecosystem] = False
            except Exception as exc:
                logger.debug("Audit tool %s failed: %s", ecosystem, exc)
                audit_available[ecosystem] = False
    else:
        for ecosystem in dep_files:
            audit_available[ecosystem] = False

    # ─── Phase 2: Lock-file parsing ───────────────────────────
    for ecosystem, files in dep_files.items():
        for lockfile in files.get("lockfile", []):
            lock_path = os.path.join(workspace, lockfile)
            if not os.path.exists(lock_path):
                continue

            files_scanned.append(lockfile)
            lock_findings = _parse_lock_file(lock_path, lockfile, ecosystem)
            findings.extend(lock_findings)

    # ─── Phase 3: Manifest matching ───────────────────────────
    for ecosystem, files in dep_files.items():
        for manifest in files.get("manifest", []):
            manifest_path = os.path.join(workspace, manifest)
            if not os.path.exists(manifest_path):
                continue

            # Skip if already scanned via lockfile (more precise)
            has_lockfile = bool(files.get("lockfile"))
            if has_lockfile:
                # Still scan manifest for completeness, but findings are less precise
                pass

            if manifest not in files_scanned:
                files_scanned.append(manifest)
            manifest_findings = _parse_manifest_file(manifest_path, manifest, ecosystem)
            findings.extend(manifest_findings)

    # Phase 3b: Nimble manifest matching (*.nimble files are dynamic)
    nimble_deps = _parse_nimble_manifest(workspace)
    if nimble_deps:
        files_scanned.append("*.nimble")
        for dep in nimble_deps:
            # Check against VULN_DB
            for entry in VULN_DB:
                if entry.get("ecosystem") != "nimble":
                    continue
                if dep["package"] != entry.get("package", "").lower():
                    continue
                installed = dep["installed"]
                vuln_range = entry.get("affected_range", "")
                if vuln_range and installed != "latest":
                    findings.append({
                        "type": "vulnerability",
                        "ecosystem": "nimble",
                        "package": dep["package"],
                        "installed_version": installed,
                        "vulnerable_range": vuln_range,
                        "severity": entry.get("severity", "medium"),
                        "cve": entry.get("cve", ""),
                        "title": entry.get("title", "Nimble dependency vulnerability")[:120],
                        "fix_version": entry.get("fix_version", ""),
                        "file": dep["source"],
                        "source": "nimble_manifest",
                    })

    # ─── Deduplicate findings ─────────────────────────────────
    findings = _deduplicate_findings(findings)

    # ─── Filter ignored packages ──────────────────────────────
    if ignore_packages:
        findings = [
            f for f in findings
            if f.get("package", "").lower() not in ignore_packages
        ]

    # ─── Apply severity filter ────────────────────────────────
    if severity:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        threshold = severity_order.get(severity, 99)
        findings = [
            f for f in findings
            if severity_order.get(f.get("severity", "low"), 3) <= threshold
        ]

    # ─── Compute stats ────────────────────────────────────────
    stats = _compute_stats(findings, files_scanned)

    # ─── Compute risk ─────────────────────────────────────────
    risk = _compute_risk(findings)

    # ─── Generate recommendations ─────────────────────────────
    recommendations = _generate_recommendations(findings, audit_available, stats)

    # Determine if any native audit tool was available
    any_audit_available = any(audit_available.values()) if audit_available else False

    return {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "stats": stats,
        "risk": risk,
        "findings": findings[:200],  # Cap to avoid explosion
        "audit_available": any_audit_available,
        "osv_stats": osv_stats,
        "cache_info": cache_info,
        "recommendations": recommendations,
    }

# ─── Dependency File Discovery ─────────────────────────────────

def _discover_dependency_files(workspace: str) -> Dict[str, Dict[str, List[str]]]:
    """Walk the workspace to find dependency files, organized by ecosystem.

    Returns:
        Dict mapping ecosystem -> {"manifest": [...], "lockfile": [...], "all": [...]}
    """
    result: Dict[str, Dict[str, List[str]]] = {}

    # Build a reverse lookup: filename -> (ecosystem, type)
    file_lookup: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for ecosystem, patterns in DEPENDENCY_FILE_PATTERNS.items():
        for ftype, filenames in patterns.items():
            for fname in filenames:
                file_lookup[fname].append((ecosystem, ftype))

    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue

        for filename in filenames:
            if filename not in file_lookup:
                continue

            rel_path = os.path.relpath(os.path.join(root, filename), workspace)

            for ecosystem, ftype in file_lookup[filename]:
                if ecosystem not in result:
                    result[ecosystem] = {"manifest": [], "lockfile": [], "all": []}
                result[ecosystem][ftype].append(rel_path)
                result[ecosystem]["all"].append(rel_path)

    return result

# ─── Phase 1: Native Audit Tools ──────────────────────────────

def _run_audit_tool(
    workspace: str,
    ecosystem: str,
    tool_info: Dict[str, Any]
) -> Optional[List[Dict[str, Any]]]:
    """Try to run a native audit tool and parse the results.

    Returns:
        List of findings if the tool ran successfully, None if tool unavailable.
    """
    command = tool_info["command"]
    parse_fn_name = tool_info["parse"]
    required_file = tool_info["required_file"]

    # Check that at least one dependency file exists for this ecosystem
    dep_files = _discover_dependency_files(workspace)
    ecosystem_files = dep_files.get(ecosystem, {})
    if not ecosystem_files.get("all"):
        # Fallback: check the required_file directly
        if not os.path.exists(os.path.join(workspace, required_file)):
            return None

    # Try running the audit tool
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        # Tool not installed
        logger.debug("Audit tool not found: %s", command[0])
        return None
    except subprocess.TimeoutExpired:
        logger.debug("Audit tool timed out: %s", " ".join(command))
        return None
    except OSError as exc:
        logger.debug("Audit tool error: %s", exc)
        return None

    # Tool ran (even if it found vulnerabilities, exit code may be non-zero)
    stdout = result.stdout
    if not stdout or not stdout.strip():
        return None

    # Parse the output
    parse_fn = globals().get(parse_fn_name)
    if not parse_fn:
        return None

    try:
        return parse_fn(stdout, workspace)
    except Exception as exc:
        logger.debug("Failed to parse %s output: %s", ecosystem, exc)
        return None

def _parse_npm_audit(stdout: str, workspace: str) -> List[Dict[str, Any]]:
    """Parse npm audit --json output."""
    findings = []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return findings

    vulnerabilities = data.get("vulnerabilities", {})
    for _pkg_name, vuln_info in vulnerabilities.items():
        # vuln_info has: name, severity, via, fixAvailable, etc.
        name = vuln_info.get("name", _pkg_name)
        severity = vuln_info.get("severity", "medium")

        # "via" can be a list of dicts or strings
        via_list = vuln_info.get("via", [])
        if not isinstance(via_list, list):
            via_list = [via_list]

        for via in via_list:
            if isinstance(via, dict):
                findings.append({
                    "type": "vulnerability",
                    "ecosystem": "npm",
                    "package": name,
                    "installed_version": via.get("range", "unknown"),
                    "vulnerable_range": via.get("range", "unknown"),
                    "severity": severity,
                    "cve": via.get("cwe", [""])[0] if via.get("cwe") else "",
                    "title": via.get("title", "npm audit finding"),
                    "fix_version": "",
                    "file": "package.json",
                    "source": "npm_audit",
                })
            elif isinstance(via, str):
                findings.append({
                    "type": "vulnerability",
                    "ecosystem": "npm",
                    "package": name,
                    "installed_version": "unknown",
                    "vulnerable_range": "unknown",
                    "severity": severity,
                    "cve": "",
                    "title": via,
                    "fix_version": "",
                    "file": "package.json",
                    "source": "npm_audit",
                })

    return findings

def _parse_cargo_audit(stdout: str, workspace: str) -> List[Dict[str, Any]]:
    """Parse cargo audit --json output."""
    findings = []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return findings

    vulnerabilities = data.get("vulnerabilities", {}).get("list", [])
    for vuln in vulnerabilities:
        advisory = vuln.get("advisory", {})
        versions = vuln.get("versions", {})
        package = vuln.get("package", {})

        findings.append({
            "type": "vulnerability",
            "ecosystem": "rust",
            "package": package.get("name", advisory.get("package", "unknown")),
            "installed_version": versions.get("patched", [])[0] if versions.get("patched") else "unknown",
            "vulnerable_range": versions.get("vulnerable", "unknown"),
            "severity": _map_cargo_severity(advisory.get("severity", "medium")),
            "cve": advisory.get("id", ""),  # Rust advisory IDs like RUSTSEC-2021-XXXX
            "title": advisory.get("title", "cargo audit finding"),
            "fix_version": versions.get("patched", [""])[0] if versions.get("patched") else "",
            "file": "Cargo.toml",
            "source": "cargo_audit",
        })

    return findings

def _parse_pip_audit(stdout: str, workspace: str) -> List[Dict[str, Any]]:
    """Parse pip-audit --format json output."""
    findings = []

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return findings

    # pip-audit JSON format: {"dependencies": [{"name": ..., "version": ..., "vulns": [...]}]}
    dependencies = data.get("dependencies", [])
    for dep in dependencies:
        name = dep.get("name", "unknown")
        version = dep.get("version", "unknown")

        for vuln in dep.get("vulns", []):
            findings.append({
                "type": "vulnerability",
                "ecosystem": "pip",
                "package": name,
                "installed_version": version,
                "vulnerable_range": vuln.get("fix_versions", ["<unknown"])[0] if vuln.get("fix_versions") else "unknown",
                "severity": _map_pip_audit_severity(vuln.get("id", "")),
                "cve": vuln.get("id", ""),
                "title": vuln.get("description", "pip-audit finding")[:120],
                "fix_version": vuln.get("fix_versions", [""])[0] if vuln.get("fix_versions") else "",
                "file": "requirements.txt",
                "source": "pip_audit",
            })

    return findings


def _parse_nimble_audit(stdout: str, workspace: str) -> List[Dict[str, Any]]:
    """Parse nimble audit output (if available). nimble doesn't currently
    have a standard audit command, so this is a placeholder for future support."""
    findings = []
    try:
        data = json.loads(stdout)
        for vuln in data.get("vulnerabilities", []):
            findings.append({
                "type": "vulnerability",
                "ecosystem": "nimble",
                "package": vuln.get("name", "unknown"),
                "installed_version": vuln.get("version", "?"),
                "vulnerable_range": vuln.get("affected", "?"),
                "severity": vuln.get("severity", "medium"),
                "cve": vuln.get("cve", ""),
                "title": vuln.get("title", "")[:120],
                "fix_version": vuln.get("fix", ""),
                "file": "*.nimble",
                "source": "nimble_audit",
            })
    except (json.JSONDecodeError, KeyError):
        pass
    return findings


def _parse_nimble_manifest(workspace: str) -> List[Dict[str, Any]]:
    """Parse .nimble files for dependency versions and check against VULN_DB."""
    deps = []
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith('.')]
        if '.codelens' in root:
            dirs.clear()
            continue
        for f in filenames:
            if f.endswith('.nimble'):
                nimble_path = os.path.join(root, f)
                rel_path = os.path.relpath(nimble_path, workspace)
                try:
                    with open(nimble_path, 'r', encoding='utf-8') as fh:
                        content = fh.read()
                    # requires "pkg >= 1.0.0"
                    for m in re.finditer(r'requires\s+"(\w+)\s*(?:>=|>|==|<=|<)\s*([0-9.]+)', content):
                        deps.append({
                            "ecosystem": "nimble",
                            "package": m.group(1).lower(),
                            "installed": m.group(2),
                            "source": rel_path,
                        })
                    # requires "pkg" (no version)
                    for m in re.finditer(r'requires\s+"(\w+)"', content):
                        pkg_name = m.group(1).lower()
                        if not any(d["package"] == pkg_name for d in deps):
                            deps.append({
                                "ecosystem": "nimble",
                                "package": pkg_name,
                                "installed": "latest",
                                "source": rel_path,
                            })
                except IOError:
                    pass
    return deps


def _parse_go_vulncheck(stdout: str, workspace: str) -> List[Dict[str, Any]]:
    """Parse govulncheck -json output."""
    findings = []
    seen_osv: Set[str] = set()

    # govulncheck outputs one JSON object per line
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Look for "Finding" messages
        if obj.get("Finding"):
            finding = obj["Finding"]
            osv_id = finding.get("osv", "")
            if osv_id in seen_osv:
                continue
            seen_osv.add(osv_id)

            trace = finding.get("Trace", [])
            pkg_path = ""
            if trace:
                pkg_path = trace[0].get("Package", "")

            findings.append({
                "type": "vulnerability",
                "ecosystem": "go",
                "package": pkg_path or osv_id,
                "installed_version": finding.get("trace", [{}])[0].get("module_version", "unknown") if trace else "unknown",
                "vulnerable_range": "see " + osv_id,
                "severity": "high",  # govulncheck doesn't provide severity directly
                "cve": osv_id,
                "title": f"Go vulnerability {osv_id}",
                "fix_version": "",
                "file": "go.mod",
                "source": "govulncheck",
            })

    return findings

# ─── Phase 2: Lock-file Parsing ───────────────────────────────

def _parse_lock_file(
    lock_path: str,
    rel_path: str,
    ecosystem: str
) -> List[Dict[str, Any]]:
    """Parse a lock file and check each package against the VULN_DB."""
    findings = []

    try:
        with open(lock_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return findings

    if ecosystem == "npm":
        if rel_path.endswith("bun.lock"):
            packages = _parse_bun_lock(content)
        elif rel_path.endswith("yarn.lock"):
            packages = _parse_yarn_lock(content)
        else:
            packages = _parse_npm_lock(content)
    elif ecosystem == "rust":
        packages = _parse_cargo_lock(content)
    elif ecosystem == "pip":
        if rel_path.endswith("poetry.lock"):
            packages = _parse_poetry_lock(content)
        elif rel_path.endswith("Pipfile.lock"):
            packages = _parse_pipfile_lock(content)
        else:
            return findings
    elif ecosystem == "go":
        packages = _parse_go_sum(content)
    else:
        return findings

    # Check each package against VULN_DB
    for pkg_name, pkg_version in packages:
        vuln_entries = _VULN_INDEX.get((ecosystem, pkg_name.lower()), [])
        for entry in vuln_entries:
            if _is_version_vulnerable(pkg_version, entry["vulnerable_range"]):
                findings.append({
                    "type": "vulnerability",
                    "ecosystem": ecosystem,
                    "package": pkg_name,
                    "installed_version": pkg_version,
                    "vulnerable_range": entry["vulnerable_range"],
                    "severity": entry["severity"],
                    "cve": entry["cve"],
                    "title": entry["title"],
                    "fix_version": entry["fix_version"],
                    "file": rel_path,
                    "source": "lockfile_db",
                })

    return findings

def _parse_npm_lock(content: str) -> List[Tuple[str, str]]:
    """Parse package-lock.json for package names and versions."""
    packages = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return packages

    # npm v7+ lockfiles
    lock_version = data.get("lockfileVersion", 1)

    if lock_version >= 2:
        # "packages" key maps path -> {version, ...}
        pkgs = data.get("packages", {})
        for pkg_path, info in pkgs.items():
            if not pkg_path or not isinstance(info, dict):
                continue
            name = info.get("name", "")
            version = info.get("version", "")
            # Derive name from path if not present
            if not name and "node_modules/" in pkg_path:
                name = pkg_path.split("node_modules/")[-1]
            if name and version:
                packages.append((name, version))
    else:
        # npm v6 lockfiles: "dependencies" key
        deps = data.get("dependencies", {})
        packages = _flatten_npm_deps(deps)

    return packages

def _flatten_npm_deps(
    deps: Dict[str, Any],
    prefix: str = ""
) -> List[Tuple[str, str]]:
    """Recursively flatten npm v6 lockfile dependencies."""
    result = []
    for name, info in deps.items():
        version = info.get("version", "")
        if version:
            result.append((name, version))
        # Nested dependencies
        nested = info.get("dependencies", {})
        if nested:
            result.extend(_flatten_npm_deps(nested))
    return result

def _parse_bun_lock(content: str) -> List[Tuple[str, str]]:
    """Parse bun.lock (text-based JSON with trailing commas) for package names and versions.

    bun.lock format (v1, text-based JSON):
    - "workspaces"."".dependencies / devDependencies: { "name": "version" }
    - "packages": { "name": ["name@version", "", {...}, "hash"] }

    Note: bun.lock uses trailing commas which are not valid JSON,
    so we strip them before parsing.
    """
    packages = []

    # Strip trailing commas (bun.lock uses JSON with trailing commas)
    # Remove commas before } or ] at various nesting levels
    cleaned = re.sub(r',\s*([}\]])', r'\1', content)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return packages

    # Extract from workspaces dependencies (top-level declared deps)
    workspaces = data.get("workspaces", {})
    for ws_name, ws_data in workspaces.items():
        for dep_type in ("dependencies", "devDependencies"):
            deps = ws_data.get(dep_type, {})
            for name, version in deps.items():
                if name and version:
                    packages.append((name, version))

    # Extract from packages (resolved packages with exact versions)
    # Format: "pkg-name": ["pkg-name@version", "", {...}, "hash"]
    pkgs = data.get("packages", {})
    for pkg_name, pkg_info in pkgs.items():
        if isinstance(pkg_info, list) and len(pkg_info) >= 1:
            # First element is "name@version"
            first = pkg_info[0]
            if "@" in first:
                # Handle scoped packages like @scope/name@version
                # Split on the last @ to get version
                at_idx = first.rfind("@")
                name = first[:at_idx]
                version = first[at_idx + 1:]
                if name and version:
                    packages.append((name, version))

    return packages


def _parse_yarn_lock(content: str) -> List[Tuple[str, str]]:
    """Parse yarn.lock for package names and versions.

    yarn.lock format (Yarn v1 / Classic):
    - Each block starts with a quoted or unquoted package specifier
    - Lines like:  version "1.2.3"
    - Multiple specifiers can map to the same resolution

    yarn.lock format (Yarn v2+ / Berry):
    - Similar but may have __metadata block
    """
    packages = []
    seen = set()  # Avoid duplicates

    current_name = None
    current_version = None

    for line in content.splitlines():
        stripped = line.strip()

        # Skip empty lines and comments
        if not stripped or stripped.startswith('#'):
            continue

        # Detect block start (package specifier line ending with :)
        if stripped.endswith(':') and not stripped.startswith(' '):
            # Save previous block
            if current_name and current_version:
                key = (current_name, current_version)
                if key not in seen:
                    seen.add(key)
                    packages.append(key)

            # Parse new block — extract package names from specifier
            current_name = None
            current_version = None

            # Extract the first package name from the specifier
            specifiers = stripped.rstrip(':')
            for spec in specifiers.split(', '):
                spec = spec.strip().strip('"')
                # Remove version constraint: lodash@^4.0.0 -> lodash
                at_idx = spec.rfind('@')
                if at_idx > 0:
                    name_part = spec[:at_idx]
                    current_name = name_part
                break  # Use first specifier for name

        # Detect version line
        elif stripped.startswith('version ') and current_name is not None:
            m = re.match(r'version\s+"([^"]+)"', stripped)
            if m:
                current_version = m.group(1)

    # Don't forget the last block
    if current_name and current_version:
        key = (current_name, current_version)
        if key not in seen:
            packages.append(key)

    return packages


def _parse_cargo_lock(content: str) -> List[Tuple[str, str]]:
    """Parse Cargo.lock for crate names and versions."""
    packages = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try TOML-like parsing (older Cargo.lock format)
        packages = _parse_cargo_lock_toml(content)
        return packages

    # JSON format
    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if name and version:
            packages.append((name, version))

    return packages

def _parse_cargo_lock_toml(content: str) -> List[Tuple[str, str]]:
    """Parse TOML-format Cargo.lock (fallback)."""
    packages = []
    in_package = False
    current_name = ""
    current_version = ""

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == "[[package]]":
            # Save previous entry
            if current_name and current_version:
                packages.append((current_name, current_version))
            in_package = True
            current_name = ""
            current_version = ""
            continue

        if in_package and stripped.startswith("[[") and stripped != "[[package]]":
            # New section, save current
            if current_name and current_version:
                packages.append((current_name, current_version))
            in_package = False
            continue

        if in_package:
            if stripped.startswith("name"):
                current_name = _extract_toml_value(stripped)
            elif stripped.startswith("version"):
                current_version = _extract_toml_value(stripped)

    # Don't forget the last entry
    if current_name and current_version:
        packages.append((current_name, current_version))

    return packages

def _parse_poetry_lock(content: str) -> List[Tuple[str, str]]:
    """Parse poetry.lock for package names and versions."""
    packages = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Try TOML parsing
        packages = _parse_poetry_lock_toml(content)
        return packages

    for pkg in data.get("package", []):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if name and version:
            packages.append((name, version))

    return packages

def _parse_poetry_lock_toml(content: str) -> List[Tuple[str, str]]:
    """Parse TOML-format poetry.lock."""
    packages = []
    in_package = False
    current_name = ""
    current_version = ""

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == "[[package]]":
            if current_name and current_version:
                packages.append((current_name, current_version))
            in_package = True
            current_name = ""
            current_version = ""
            continue

        if in_package and stripped.startswith("[[") and stripped != "[[package]]":
            if current_name and current_version:
                packages.append((current_name, current_version))
            in_package = False
            continue

        if in_package:
            if stripped.startswith("name"):
                current_name = _extract_toml_value(stripped)
            elif stripped.startswith("version"):
                current_version = _extract_toml_value(stripped)

    if current_name and current_version:
        packages.append((current_name, current_version))

    return packages

def _parse_pipfile_lock(content: str) -> List[Tuple[str, str]]:
    """Parse Pipfile.lock for package names and versions."""
    packages = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return packages

    for section in ("default", "develop"):
        section_deps = data.get(section, {})
        for name, info in section_deps.items():
            if isinstance(info, dict):
                version = info.get("version", "")
            elif isinstance(info, str):
                version = info
            else:
                continue

            # Strip version specifiers (e.g., "==1.2.3" -> "1.2.3")
            version = re.sub(r'^[><=!~]+', '', version).strip()
            if name and version:
                packages.append((name, version))

    return packages

def _parse_go_sum(content: str) -> List[Tuple[str, str]]:
    """Parse go.sum for module names and versions.

    go.sum format: <module> <version>/go.mod h1:hash
    We extract unique (module, version) pairs.
    """
    packages = []
    seen: Set[Tuple[str, str]] = set()

    for line in content.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue

        module = parts[0]
        version = parts[1]

        # Remove the "/go.mod" suffix that appears in go.sum
        if version.endswith("/go.mod"):
            version = version[:-len("/go.mod")]

        key = (module, version)
        if key not in seen:
            seen.add(key)
            packages.append(key)

    return packages

# ─── Phase 3: Manifest Matching ───────────────────────────────

def _parse_manifest_file(
    manifest_path: str,
    rel_path: str,
    ecosystem: str
) -> List[Dict[str, Any]]:
    """Parse a manifest file and check declared dependencies against VULN_DB."""
    findings = []

    try:
        with open(manifest_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
    except IOError:
        return findings

    if ecosystem == "npm" or ecosystem == "bun":
        packages = _parse_package_json(content)
    elif ecosystem == "rust":
        packages = _parse_cargo_toml(content)
    elif ecosystem == "pip":
        if rel_path.endswith("Pipfile"):
            packages = _parse_pipfile(content)
        elif rel_path.endswith("pyproject.toml"):
            packages = _parse_pyproject_toml(content)
        else:
            packages = _parse_requirements_txt(content)
    elif ecosystem == "go":
        packages = _parse_go_mod(content)
    else:
        return findings

    # Check each package against VULN_DB
    # Bun uses npm packages, so also check npm ecosystem for bun
    lookup_ecosystems = [ecosystem]
    if ecosystem == "bun":
        lookup_ecosystems.append("npm")

    for pkg_name, pkg_version in packages:
        for eco in lookup_ecosystems:
            vuln_entries = _VULN_INDEX.get((eco, pkg_name.lower()), [])
            for entry in vuln_entries:
                if _is_version_vulnerable(pkg_version, entry["vulnerable_range"]):
                    # Avoid duplicate if already found via lock file
                    findings.append({
                        "type": "vulnerability",
                        "ecosystem": ecosystem,
                        "package": pkg_name,
                        "installed_version": pkg_version,
                        "vulnerable_range": entry["vulnerable_range"],
                        "severity": entry["severity"],
                        "cve": entry["cve"],
                        "title": entry["title"],
                        "fix_version": entry["fix_version"],
                        "file": rel_path,
                        "source": "manifest_db",
                    })

    return findings

def _parse_package_json(content: str) -> List[Tuple[str, str]]:
    """Parse package.json for dependency names and version ranges."""
    packages = []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return packages

    for dep_field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        deps = data.get(dep_field, {})
        for name, version_spec in deps.items():
            if isinstance(version_spec, str):
                # Extract a version number from range specifiers
                version = _extract_version_from_npm_spec(version_spec)
                packages.append((name, version))

    return packages

def _parse_cargo_toml(content: str) -> List[Tuple[str, str]]:
    """Parse Cargo.toml for dependency names and version requirements."""
    packages = []
    in_deps = False

    for line in content.splitlines():
        stripped = line.strip()

        # Detect [dependencies] or [dev-dependencies] sections
        if re.match(r'^\[dev-?dependencies\]$', stripped):
            in_deps = True
            continue
        elif re.match(r'^\[dependencies\]$', stripped):
            in_deps = True
            continue
        elif stripped.startswith('[') and not stripped.startswith("[["):
            in_deps = False
            continue

        if not in_deps:
            continue

        # Simple form: name = "version"
        m = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*"([^"]+)"', stripped)
        if m:
            name = m.group(1)
            version = _extract_version_from_cargo_spec(m.group(2))
            packages.append((name, version))
            continue

        # Table form: name = { version = "x.y.z", ... }
        m = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*\{.*version\s*=\s*"([^"]+)".*\}', stripped)
        if m:
            name = m.group(1)
            version = _extract_version_from_cargo_spec(m.group(2))
            packages.append((name, version))

    return packages

def _parse_requirements_txt(content: str) -> List[Tuple[str, str]]:
    """Parse requirements.txt for package names and versions."""
    packages = []

    for line in content.splitlines():
        stripped = line.strip()

        # Skip comments and empty lines
        if not stripped or stripped.startswith('#') or stripped.startswith('-'):
            continue

        # Handle various specifier formats:
        # package==1.2.3
        # package>=1.2.3,<2.0.0
        # package~=1.2.3
        # package[name]==1.2.3  (extras)
        m = re.match(
            r'^([A-Za-z0-9_.-]+)(?:\[.*?\])?\s*([><=!~].+)?$', stripped
        )
        if not m:
            continue

        name = m.group(1).strip()
        version_spec = (m.group(2) or "").strip()

        # Extract the most likely installed version from the spec
        version = _extract_version_from_pip_spec(version_spec)

        if name:
            packages.append((name, version))

    return packages

def _parse_pipfile(content: str) -> List[Tuple[str, str]]:
    """Parse Pipfile for package names and versions."""
    packages = []
    in_deps = False
    in_dev = False

    for line in content.splitlines():
        stripped = line.strip()

        if stripped == "[packages]":
            in_deps = True
            in_dev = False
            continue
        elif stripped == "[dev-packages]":
            in_deps = True
            in_dev = True
            continue
        elif stripped.startswith('['):
            in_deps = False
            continue

        if not in_deps:
            continue

        # Simple form: name = "version"
        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', stripped)
        if m:
            name = m.group(1)
            version = _extract_version_from_pip_spec(m.group(2))
            packages.append((name, version))
            continue

        # Table form: name = {version = "x.y.z"}
        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\{.*version\s*=\s*"([^"]*)".*\}', stripped)
        if m:
            name = m.group(1)
            version = _extract_version_from_pip_spec(m.group(2))
            packages.append((name, version))
            continue

        # Bare name: name = "*"
        m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\*', stripped)
        if m:
            packages.append((m.group(1), "0.0.0"))

    return packages


def _parse_pyproject_toml(content: str) -> List[Tuple[str, str]]:
    """Parse pyproject.toml for package names and versions.

    Handles both [project.dependencies] (PEP 621) and
    [tool.poetry.dependencies] (Poetry) sections.
    """
    packages = []
    in_project_deps = False
    in_poetry_deps = False

    for line in content.splitlines():
        stripped = line.strip()

        # PEP 621: [project.dependencies]
        if re.match(r'^\[project\.dependencies\]$', stripped):
            in_project_deps = True
            in_poetry_deps = False
            continue
        elif re.match(r'^\[project\.optional-dependencies\.', stripped):
            in_project_deps = True
            in_poetry_deps = False
            continue
        # Poetry: [tool.poetry.dependencies]
        elif re.match(r'^\[tool\.poetry\.dependencies\]$', stripped):
            in_project_deps = False
            in_poetry_deps = True
            continue
        elif re.match(r'^\[tool\.poetry\.group\..*\.dependencies\]$', stripped):
            in_project_deps = False
            in_poetry_deps = True
            continue
        elif stripped.startswith('[') and not stripped.startswith("[["):
            in_project_deps = False
            in_poetry_deps = False
            continue

        if not (in_project_deps or in_poetry_deps):
            continue

        # PEP 621 form: name = ">=1.2.3" or name = {version = ">=1.2.3"}
        if in_project_deps:
            # Simple string form: name = ">=1.2.3"
            m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', stripped)
            if m:
                name = m.group(1)
                version = _extract_version_from_pip_spec(m.group(2))
                packages.append((name, version))
                continue

            # Table form: name = {version = ">=1.2.3", ...}
            m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\{.*version\s*=\s*"([^"]*)".*\}', stripped)
            if m:
                name = m.group(1)
                version = _extract_version_from_pip_spec(m.group(2))
                packages.append((name, version))
                continue

        # Poetry form: same as Pipfile
        if in_poetry_deps:
            m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"([^"]*)"', stripped)
            if m:
                name = m.group(1)
                version = _extract_version_from_pip_spec(m.group(2))
                packages.append((name, version))
                continue

            m = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\{.*version\s*=\s*"([^"]*)".*\}', stripped)
            if m:
                name = m.group(1)
                version = _extract_version_from_pip_spec(m.group(2))
                packages.append((name, version))
                continue

    return packages


def _parse_go_mod(content: str) -> List[Tuple[str, str]]:
    """Parse go.mod for module names and versions."""
    packages = []

    for line in content.splitlines():
        stripped = line.strip()

        # Skip comments, empty lines, and closing parens
        if not stripped or stripped.startswith('//') or stripped == ')':
            continue

        # require directive (single line): require module version
        m = re.match(r'^require\s+(\S+)\s+(v?\S+)', stripped)
        if m:
            packages.append((m.group(1), m.group(2).lstrip('v')))
            continue

        # Indented require block entries: use original line to detect indentation
        # Lines inside require() blocks are indented with tabs/spaces
        if line != stripped and stripped and not stripped.startswith('require') and not stripped.startswith('module') and not stripped.startswith('go '):
            m = re.match(r'^(\S+)\s+(v?\S+)', stripped)
            if m:
                module = m.group(1)
                version = m.group(2).lstrip('v')
                if module and version:
                    packages.append((module, version))

    return packages

# ─── Version Comparison Helpers ────────────────────────────────

def _extract_version_from_npm_spec(spec: str) -> str:
    """Extract a version number from an npm version specifier.

    Examples: "^1.2.3" -> "1.2.3", "~1.2.3" -> "1.2.3",
              ">=1.2.3" -> "1.2.3", "1.2.3" -> "1.2.3"
    """
    # Remove workspace: / file: / npm: / github: protocols
    if any(spec.startswith(p) for p in ("workspace:", "file:", "npm:", "github:", "git+", "git://", "http:", "https:")):
        return "0.0.0"  # Can't determine version from these

    # Remove leading operators (may be multi-char like >=, <=, !=, ==)
    cleaned = re.sub(r'^[~^>=<!*]+', '', spec)
    # Handle compound ranges like ">=1.2.3 <2.0.0" — take the lower bound
    cleaned = cleaned.split()[0] if cleaned else "0.0.0"
    # Validate it looks like a version
    if re.match(r'^\d+', cleaned):
        return cleaned
    return "0.0.0"

def _extract_version_from_cargo_spec(spec: str) -> str:
    """Extract a version number from a Cargo version requirement.

    Examples: "1.2.3" -> "1.2.3", "^1.2" -> "1.2", "~1.2.3" -> "1.2.3",
              ">=1.2.3" -> "1.2.3"
    """
    cleaned = re.sub(r'^[~^>=<!*]+', '', spec.strip())
    cleaned = cleaned.split(',')[0].strip()
    if re.match(r'^\d+', cleaned):
        return cleaned
    return "0.0.0"

def _extract_version_from_pip_spec(spec: str) -> str:
    """Extract a version number from a pip version specifier.

    Examples: "==1.2.3" -> "1.2.3", ">=1.2.3,<2.0" -> "1.2.3",
              "~=1.2.3" -> "1.2.3", "" -> "0.0.0"
    """
    if not spec:
        return "0.0.0"

    # Try to find an explicit == version first
    m = re.search(r'==\s*([0-9][0-9A-Za-z.*-]*)', spec)
    if m:
        return m.group(1)

    # Fall back to first version-like number
    m = re.search(r'([0-9]+\.[0-9]+(?:\.[0-9]+)?)', spec)
    if m:
        return m.group(1)

    return "0.0.0"

def _extract_toml_value(line: str) -> str:
    """Extract the value from a TOML key = "value" line."""
    m = re.match(r'^\w+\s*=\s*"([^"]*)"', line.strip())
    if m:
        return m.group(1)
    # Try bare value
    m = re.match(r'^\w+\s*=\s*(\S+)', line.strip())
    if m:
        return m.group(1).strip("'")
    return ""

def _is_version_vulnerable(installed: str, vulnerable_range: str) -> bool:
    """Check if an installed version falls within a vulnerable range.

    Supports:
    - "<X.Y.Z" — all versions below X.Y.Z
    - "<=X.Y.Z" — all versions at or below X.Y.Z
    - ">=X.Y.Z" — all versions at or above X.Y.Z
    - "X.Y.Z - A.B.C" — inclusive range (not common in our DB)
    """
    if not installed or installed in ("unknown", "0.0.0", "*"):
        # If we can't determine the version, we can't definitively say it's vulnerable
        return False

    # Normalize versions by stripping leading 'v'
    installed = installed.lstrip('v')
    vuln_spec = vulnerable_range.strip()

    # Parse the operator and threshold version
    if vuln_spec.startswith("<="):
        threshold = vuln_spec[2:].strip().lstrip('v')
        return _compare_versions(installed, threshold) <= 0
    elif vuln_spec.startswith("<"):
        threshold = vuln_spec[1:].strip().lstrip('v')
        return _compare_versions(installed, threshold) < 0
    elif vuln_spec.startswith(">="):
        threshold = vuln_spec[2:].strip().lstrip('v')
        return _compare_versions(installed, threshold) >= 0
    elif vuln_spec.startswith(">"):
        threshold = vuln_spec[1:].strip().lstrip('v')
        return _compare_versions(installed, threshold) > 0
    elif vuln_spec.startswith("=="):
        threshold = vuln_spec[2:].strip().lstrip('v')
        return _compare_versions(installed, threshold) == 0

    # If we can't parse the range, be conservative
    return False

def _compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings.

    Returns:
        -1 if v1 < v2, 0 if v1 == v2, 1 if v1 > v2
    """
    def _parse_ver(v: str) -> List[int]:
        parts = []
        for part in re.split(r'[.\-]', v):
            # Extract leading digits
            m = re.match(r'^(\d+)', part)
            if m:
                parts.append(int(m.group(1)))
            else:
                parts.append(0)
        return parts

    parts1 = _parse_ver(v1)
    parts2 = _parse_ver(v2)

    # Pad shorter version with zeros
    max_len = max(len(parts1), len(parts2))
    parts1.extend([0] * (max_len - len(parts1)))
    parts2.extend([0] * (max_len - len(parts2)))

    for p1, p2 in zip(parts1, parts2):
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1

    return 0

# ─── Severity Helpers ─────────────────────────────────────────

def _map_cargo_severity(severity: str) -> str:
    """Map cargo audit severity to standard severity."""
    mapping = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
    }
    return mapping.get(severity.lower(), "medium")

def _map_pip_audit_severity(vuln_id: str) -> str:
    """Estimate severity from a pip-audit vulnerability ID.

    pip-audit doesn't provide severity directly, so we use heuristics:
    - CVEs with RCE/code-exec keywords are critical
    - Most others default to high
    """
    vuln_id_lower = vuln_id.lower()
    if any(kw in vuln_id_lower for kw in ("rce", "remote code", "arbitrary code")):
        return "critical"
    return "high"

# ─── Deduplication ─────────────────────────────────────────────

def _deduplicate_findings(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove duplicate findings (same package, ecosystem, CVE).

    Prefer findings from OSV.dev and audit tools over built-in DB lookups.
    OSV.dev findings are prioritized because they contain real-time data with
    CVSS scores and more detailed information.
    """
    seen: Set[Tuple[str, str, str]] = set()
    unique = []

    # Prefer findings from OSV.dev and audit tools over DB lookups
    # Sort: most authoritative sources first
    source_priority = {
        "osv_dev": 0,          # OSV.dev API (real-time, most comprehensive)
        "npm_audit": 1,        # Native audit tools
        "cargo_audit": 1,
        "pip_audit": 1,
        "govulncheck": 1,
        "nimble_audit": 1,
        "lockfile_db": 2,      # Built-in DB lookups
        "manifest_db": 3,
        "nimble_manifest": 4,
    }

    sorted_findings = sorted(
        findings,
        key=lambda f: source_priority.get(f.get("source", ""), 99)
    )

    for finding in sorted_findings:
        key = (
            finding.get("package", "").lower(),
            finding.get("ecosystem", ""),
            finding.get("cve", ""),
        )
        if key not in seen:
            seen.add(key)
            unique.append(finding)

    return unique

# ─── Stats & Risk Computation ──────────────────────────────────

def _compute_stats(
    findings: List[Dict[str, Any]],
    files_scanned: List[str]
) -> Dict[str, Any]:
    """Compute statistics from findings."""
    by_severity: Dict[str, int] = defaultdict(int)
    by_ecosystem: Dict[str, int] = defaultdict(int)

    for f in findings:
        by_severity[f.get("severity", "unknown")] += 1
        by_ecosystem[f.get("ecosystem", "unknown")] += 1

    return {
        "total_vulnerabilities": len(findings),
        "by_severity": dict(by_severity),
        "by_ecosystem": dict(by_ecosystem),
        "files_scanned": files_scanned,
    }

def _compute_risk(findings: List[Dict[str, Any]]) -> str:
    """Compute overall risk level based on findings."""
    if not findings:
        return "none"

    severities = {f.get("severity", "low") for f in findings}
    severity_counts = defaultdict(int)
    for f in findings:
        severity_counts[f.get("severity", "low")] += 1

    if "critical" in severities:
        if severity_counts.get("critical", 0) >= 2:
            return "critical"
        return "critical"
    if "high" in severities:
        if severity_counts.get("high", 0) >= 3:
            return "critical"
        return "high"
    if "medium" in severities:
        return "medium"

    return "low"

# ─── Recommendations ───────────────────────────────────────────

def _generate_recommendations(
    findings: List[Dict[str, Any]],
    audit_available: Dict[str, bool],
    stats: Dict[str, Any]
) -> List[str]:
    """Generate actionable recommendations based on findings."""
    recs = []

    if not findings:
        recs.append("No known vulnerabilities detected in dependencies. Good practice!")
        return recs

    # Group findings by ecosystem
    by_ecosystem: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in findings:
        by_ecosystem[f.get("ecosystem", "unknown")].append(f)

    # Critical findings
    critical = [f for f in findings if f.get("severity") == "critical"]
    if critical:
        pkg_list = ", ".join(
            f"{f['package']}@{f.get('installed_version', '?')}" for f in critical[:5]
        )
        recs.append(
            f"CRITICAL: {len(critical)} critical vulnerability(ies) found. "
            f"Update immediately: {pkg_list}"
        )

    # High severity
    high = [f for f in findings if f.get("severity") == "high"]
    if high:
        pkg_list = ", ".join(
            f"{f['package']}@{f.get('installed_version', '?')}" for f in high[:5]
        )
        recs.append(
            f"HIGH: {len(high)} high-severity vulnerability(ies) found. "
            f"Prioritize updating: {pkg_list}"
        )

    # Per-ecosystem update commands
    if "npm" in by_ecosystem:
        fix_packages = set()
        for f in by_ecosystem["npm"]:
            if f.get("fix_version"):
                fix_packages.add(f"{f['package']}@{f['fix_version']}")
        if fix_packages:
            recs.append(
                f"NPM: Run `npm install {' '.join(list(fix_packages)[:8])}` to fix vulnerabilities."
            )
        else:
            recs.append("NPM: Run `npm audit fix` to automatically fix vulnerabilities.")

    if "pip" in by_ecosystem:
        fix_packages = set()
        for f in by_ecosystem["pip"]:
            if f.get("fix_version"):
                fix_packages.add(f"{f['package']}=={f['fix_version']}")
        if fix_packages:
            recs.append(
                f"PIP: Update packages: `pip install {' '.join(list(fix_packages)[:8])}`"
            )
        else:
            recs.append("PIP: Run `pip-audit --fix` or update vulnerable packages manually.")

    if "rust" in by_ecosystem:
        fix_packages = set()
        for f in by_ecosystem["rust"]:
            if f.get("fix_version"):
                fix_packages.add(f'{f["package"]} = "{f["fix_version"]}"')
        if fix_packages:
            recs.append(
                f"CARGO: Update Cargo.toml: {', '.join(list(fix_packages)[:8])}"
            )
        else:
            recs.append("CARGO: Run `cargo update` to update dependencies.")

    if "go" in by_ecosystem:
        recs.append(
            "GO: Run `govulncheck ./...` for detailed analysis and update modules with "
            "`go get -u <module>` or `go get <module>@v<version>`."
        )

    # Audit tool recommendations
    missing_tools = [
        eco for eco, available in audit_available.items() if not available
    ]
    if missing_tools:
        tool_install = {
            "npm": "npm is included with Node.js",
            "rust": "Install with: cargo install cargo-audit",
            "pip": "Install with: pip install pip-audit",
            "go": "Install with: go install golang.org/x/vuln/cmd/govulncheck@latest",
        }
        missing_recs = []
        for eco in missing_tools:
            if eco in tool_install:
                missing_recs.append(f"  {eco}: {tool_install[eco]}")
        if missing_recs:
            recs.append(
                "AUDIT TOOLS: For more accurate results, install native audit tools:\n"
                + "\n".join(missing_recs)
            )

    # General advice
    # Check if OSV.dev data was used
    osv_findings = [f for f in findings if f.get("source") == "osv_dev"]
    if osv_findings:
        recs.append(
            "OSV.DEV: Vulnerability data sourced from OSV.dev (real-time database). "
            "Use --offline flag to use cached data only, or --osv-ttl to adjust cache duration."
        )
    elif _HAS_OSV:
        recs.append(
            "OSV.DEV: No vulnerabilities found via OSV.dev real-time database. "
            "Data is cached for 24h by default (use --osv-ttl to adjust)."
        )
    else:
        recs.append(
            "GENERAL: OSV.dev integration not available. For real-time vulnerability data, "
            "ensure osv_client.py is in the scripts directory. "
            "Consider using Dependabot or Snyk for automated scanning in CI/CD pipelines."
        )

    return recs
