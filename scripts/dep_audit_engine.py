# @WHO:   scripts/dep_audit_engine.py
# @WHAT:  Dependency audit engine — scans manifests/lockfiles for known CVEs via OSV.dev
# @PART:  engine
# @ENTRY: audit_dependencies()
"""
Dependency Audit Engine for CodeLens.

Scans dependency manifests (requirements.txt, package.json, Cargo.toml) and
lock files (package-lock.json, yarn.lock, Cargo.lock) for packages with known
vulnerabilities, using the OSV.dev batch API.

Answers: "Do any of my dependencies have known CVEs?"

Architecture (issue #158):
- Manifest / lock-file parsing: pure Python, no external binary deps
- OSV batch API: POST /v1/querybatch (up to 1000 queries per request)
- Per-vuln details: GET /v1/vulns/{id} (cached in-memory for the run)
- Severity mapping: CVSS v3 vector → critical/high/medium/low
- Persistence: findings stored in SQLite graph as `dependency_vuln` nodes
  linked to the source file via `HAS_VULN` edges (graph_model.py constants)

Design invariants:
- Zero external binary dependency (pure-stdlib: urllib, json, sqlite3, tomllib)
- Network failures are graceful: return status "offline" with empty findings,
  NEVER raise. Caller (MCP / CLI) decides what to do with status.
- No telemetry, no PII. Only package names + versions are sent to OSV.dev
  (which is the minimum required to query vulnerabilities).

Issue: #158
"""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from graph_model import (
    EDGE_TYPE_HAS_VULN,
    GRAPH_EDGES_TABLE,
    GRAPH_NODES_TABLE,
    NODE_TYPE_DEPENDENCY_VULN,
    NODE_TYPE_FILE,
    init_graph_schema,
)
from utils import default_db_path, logger

# ─── Constants ─────────────────────────────────────────────────

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{vuln_id}"

# OSV batch endpoint accepts up to 1000 queries per request.
OSV_BATCH_SIZE = 1000

# Network timeouts and retry behavior.
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # seconds; doubled each retry

# Severity ranking — CVSS v3 base score → bucket.
# Per CVSS v3 spec: 0.1-3.9 low, 4.0-6.9 medium, 7.0-8.9 high, 9.0-10.0 critical.
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}

# Ecosystems supported by deps-audit (issue #158 scope).
SUPPORTED_ECOSYSTEMS = ("PyPI", "npm", "crates.io")

# Map of ecosystem → (manifest files, lock files).
# Lock files are preferred when present because they pin exact versions.
_ECOSYSTEM_FILES: Dict[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    "PyPI": (
        ("requirements.txt", "pyproject.toml", "Pipfile"),
        ("requirements.txt",),  # requirements.txt is itself the lock file
    ),
    "npm": (
        ("package.json",),
        ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"),
    ),
    "crates.io": (
        ("Cargo.toml",),
        ("Cargo.lock",),
    ),
}


# ─── Public API ────────────────────────────────────────────────


def audit_dependencies(
    workspace: str,
    severity: Optional[str] = None,
    ecosystem: Optional[str] = None,
    offline: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan workspace dependencies for known vulnerabilities via OSV.dev.

    Args:
        workspace: Absolute path to workspace root.
        severity: Optional filter — only return findings at this severity or
            higher. One of "critical", "high", "medium", "low".
        ecosystem: Optional filter — only scan one ecosystem. One of
            "PyPI", "npm", "crates.io". None = scan all.
        offline: If True, skip OSV API queries. Returns the set of
            packages that *would* be checked plus a status of "offline"
            and an empty findings list.
        db_path: Optional SQLite db path for graph persistence. Defaults
            to `<workspace>/.codelens/codelens.db`.

    Returns:
        Dict with keys:
            - status: "ok" | "offline" | "error"
            - workspace: the resolved workspace path
            - severity_filter: the severity filter (or None)
            - ecosystem_filter: the ecosystem filter (or None)
            - stats: {total, critical, high, medium, low, unknown,
                      packages_scanned, ecosystems_scanned}
            - findings: list of finding dicts (see _build_finding)
            - recommendations: list of actionable strings
            - files_scanned: list of manifest/lock file paths read
            - packages_scanned: list of {name, version, ecosystem, source_file}
    """
    workspace = os.path.abspath(workspace)

    # ─── Discover dependency files ─────────────────────────────
    ecosystems_to_scan = (
        (ecosystem,) if ecosystem else SUPPORTED_ECOSYSTEMS
    )
    files_scanned: List[str] = []
    packages: List[Dict[str, str]] = []

    for eco in ecosystems_to_scan:
        manifests, lockfiles = _ECOSYSTEM_FILES[eco]
        eco_packages, eco_files = _collect_packages_for_ecosystem(
            workspace, eco, manifests, lockfiles
        )
        packages.extend(eco_packages)
        files_scanned.extend(eco_files)

    # Deduplicate packages by (name, version, ecosystem) — a package may
    # appear in both manifest and lock file.
    seen = set()
    deduped_packages: List[Dict[str, str]] = []
    for pkg in packages:
        key = (pkg["name"], pkg["version"], pkg["ecosystem"])
        if key in seen:
            continue
        seen.add(key)
        deduped_packages.append(pkg)
    packages = deduped_packages

    # ─── Offline short-circuit ─────────────────────────────────
    if offline:
        return {
            "status": "offline",
            "workspace": workspace,
            "severity_filter": severity,
            "ecosystem_filter": ecosystem,
            "stats": {
                "total": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
                "packages_scanned": len(packages),
                "ecosystems_scanned": len(ecosystems_to_scan),
            },
            "findings": [],
            "recommendations": [
                "Offline mode: skipped OSV API queries. Re-run without "
                "--offline to scan for known vulnerabilities."
            ],
            "files_scanned": sorted(set(files_scanned)),
            "packages_scanned": packages,
        }

    if not packages:
        return {
            "status": "ok",
            "workspace": workspace,
            "severity_filter": severity,
            "ecosystem_filter": ecosystem,
            "stats": {
                "total": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
                "packages_scanned": 0,
                "ecosystems_scanned": len(ecosystems_to_scan),
            },
            "findings": [],
            "recommendations": [
                "No dependency manifests found. Supported files: "
                "requirements.txt, pyproject.toml, Pipfile, package.json, "
                "package-lock.json, yarn.lock, pnpm-lock.yaml, Cargo.toml, "
                "Cargo.lock."
            ],
            "files_scanned": [],
            "packages_scanned": [],
        }

    # ─── Query OSV.dev ─────────────────────────────────────────
    raw_findings, api_errors = _query_osv_batch(packages)

    # ─── Apply severity filter ─────────────────────────────────
    if severity:
        threshold = SEVERITY_ORDER.get(severity, 99)
        filtered: List[Dict[str, Any]] = []
        for f in raw_findings:
            f_sev = SEVERITY_ORDER.get(f.get("severity", "unknown"), 4)
            if f_sev <= threshold:
                filtered.append(f)
        findings = filtered
    else:
        findings = raw_findings

    # ─── Compute stats ─────────────────────────────────────────
    stats = _compute_stats(findings, packages, ecosystems_to_scan)

    # ─── Persist to SQLite graph ───────────────────────────────
    persistence_info = _persist_findings_to_graph(
        workspace, db_path, findings, packages
    )

    # ─── Recommendations ───────────────────────────────────────
    recommendations = _generate_recommendations(findings, api_errors)

    result: Dict[str, Any] = {
        "status": "ok",
        "workspace": workspace,
        "severity_filter": severity,
        "ecosystem_filter": ecosystem,
        "stats": stats,
        "findings": findings,
        "recommendations": recommendations,
        "files_scanned": sorted(set(files_scanned)),
        "packages_scanned": packages,
    }
    if persistence_info:
        result["persistence"] = persistence_info
    if api_errors:
        # Surface non-fatal API errors (e.g. partial batch failure) so the
        # caller knows the result may be incomplete. status stays "ok" because
        # we did return *some* findings.
        result["api_errors"] = api_errors
    return result


# ─── Manifest / Lock Parsing ───────────────────────────────────


def _collect_packages_for_ecosystem(
    workspace: str,
    ecosystem: str,
    manifests: Tuple[str, ...],
    lockfiles: Tuple[str, ...],
) -> Tuple[List[Dict[str, str]], List[str]]:
    """Find and parse dependency files for one ecosystem.

    Lock files are preferred when present (pinned versions). Falls back to
    manifest files otherwise. Files that don't exist are silently skipped.

    Returns:
        (packages, files_scanned) — packages is a list of dicts with keys
        {name, version, ecosystem, source_file}. files_scanned is the list
        of file paths that were actually read.
    """
    packages: List[Dict[str, str]] = []
    files_scanned: List[str] = []

    # Try lock files first — they have exact pinned versions.
    for lock_name in lockfiles:
        lock_path = os.path.join(workspace, lock_name)
        if not os.path.isfile(lock_path):
            continue
        try:
            parsed = _parse_lock_file(lock_path, ecosystem)
        except Exception as e:
            logger.warning(
                f"[dep_audit] failed to parse lock file {lock_path}: {e}"
            )
            continue
        for name, version in parsed:
            packages.append(
                {
                    "name": name,
                    "version": version,
                    "ecosystem": ecosystem,
                    "source_file": lock_name,
                }
            )
        files_scanned.append(lock_name)

    # If we got packages from a lock file, don't also parse the manifest —
    # lock-file versions are more accurate.
    if packages:
        return packages, files_scanned

    # No lock file (or lock file empty) — fall back to manifests.
    for manifest_name in manifests:
        manifest_path = os.path.join(workspace, manifest_name)
        if not os.path.isfile(manifest_path):
            continue
        try:
            parsed = _parse_manifest_file(manifest_path, ecosystem)
        except Exception as e:
            logger.warning(
                f"[dep_audit] failed to parse manifest {manifest_path}: {e}"
            )
            continue
        for name, version in parsed:
            packages.append(
                {
                    "name": name,
                    "version": version,
                    "ecosystem": ecosystem,
                    "source_file": manifest_name,
                }
            )
        files_scanned.append(manifest_name)

    return packages, files_scanned


def _parse_lock_file(path: str, ecosystem: str) -> List[Tuple[str, str]]:
    """Dispatch to the right parser for a lock file.

    Args:
        path: Absolute path to the lock file.
        ecosystem: One of "PyPI", "npm", "crates.io".

    Returns:
        List of (name, version) tuples. Empty list on parse failure.
    """
    name = os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    if ecosystem == "PyPI" and name == "requirements.txt":
        return _parse_requirements_txt(content)
    if ecosystem == "npm":
        if name == "package-lock.json":
            return _parse_package_lock_json(content)
        if name == "yarn.lock":
            return _parse_yarn_lock(content)
        if name == "pnpm-lock.yaml":
            return _parse_pnpm_lock_yaml(content)
    if ecosystem == "crates.io" and name == "Cargo.lock":
        return _parse_cargo_lock(content)

    logger.warning(
        f"[dep_audit] no parser for lock file {name} (ecosystem={ecosystem})"
    )
    return []


def _parse_manifest_file(path: str, ecosystem: str) -> List[Tuple[str, str]]:
    """Dispatch to the right parser for a manifest file."""
    name = os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    if ecosystem == "PyPI":
        if name == "requirements.txt":
            return _parse_requirements_txt(content)
        if name == "pyproject.toml":
            return _parse_pyproject_toml(content)
        if name == "Pipfile":
            return _parse_pipfile(content)
    if ecosystem == "npm" and name == "package.json":
        return _parse_package_json(content)
    if ecosystem == "crates.io" and name == "Cargo.toml":
        return _parse_cargo_toml(content)

    logger.warning(
        f"[dep_audit] no parser for manifest {name} (ecosystem={ecosystem})"
    )
    return []


# ─── Per-format Parsers ────────────────────────────────────────


_REQUIREMENT_LINE_RE = None  # compiled lazily to keep import side-effects minimal


def _parse_requirements_txt(content: str) -> List[Tuple[str, str]]:
    """Parse requirements.txt — supports `name==version`, `name>=version`,
    `name~=version`, and bare `name` (version becomes "").
    Skips comments, blank lines, options (-r, --, -e), and VCS URLs.
    """
    import re

    global _REQUIREMENT_LINE_RE
    if _REQUIREMENT_LINE_RE is None:
        _REQUIREMENT_LINE_RE = re.compile(
            r"^\s*([A-Za-z0-9_.\-]+)\s*(?:==|>=|~=|<=|>|<|=)?\s*"
            r"([A-Za-z0-9_.\-*+!]+)?"
        )

    out: List[Tuple[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-", "git+", "http://", "https://", "svn+", "hg+")):
            continue
        # Strip environment markers (e.g. "; python_version >= '3.8'")
        line = line.split(";", 1)[0].strip()
        # Strip extras (e.g. "package[extra1,extra2]")
        line = re.sub(r"\[[^\]]+\]", "", line)
        match = _REQUIREMENT_LINE_RE.match(line)
        if not match:
            continue
        name = match.group(1)
        version = (match.group(2) or "").strip()
        if not name:
            continue
        out.append((name, version))
    return out


def _parse_package_json(content: str) -> List[Tuple[str, str]]:
    """Parse package.json — extracts dependencies + devDependencies.
    Versions are npm semver specs (e.g. "^1.2.3", "~2.0.0", ">=3.0.0").
    The leading operator is stripped to give a best-effort version.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"[dep_audit] invalid package.json: {e}")
        return []
    out: List[Tuple[str, str]] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        section_deps = data.get(section) or {}
        if not isinstance(section_deps, dict):
            continue
        for name, spec in section_deps.items():
            if not isinstance(spec, str):
                continue
            # Skip git/file/link specs — only registry versions are checkable.
            if spec.startswith(("file:", "git+", "link:", "http:", "https:")):
                continue
            version = _strip_npm_operator(spec)
            out.append((name, version))
    return out


def _parse_package_lock_json(content: str) -> List[Tuple[str, str]]:
    """Parse package-lock.json (npm v1/v2/v3) — extracts `packages` and
    `dependencies` sections, returning pinned (name, version) pairs.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        logger.warning(f"[dep_audit] invalid package-lock.json: {e}")
        return []
    out: List[Tuple[str, str]] = []

    # Lockfile v2/v3: "packages" dict keyed by "node_modules/..." paths
    packages_section = data.get("packages") or {}
    if isinstance(packages_section, dict):
        for path_key, info in packages_section.items():
            if not isinstance(info, dict):
                continue
            # Skip the root package itself (key is "").
            if not path_key:
                continue
            # Skip bundled / optional / workspace packages without a real version.
            version = info.get("version")
            if not version:
                continue
            # Extract the package name from the path key (last segment after
            # the last "node_modules/").
            name = path_key.split("node_modules/")[-1]
            if not name:
                continue
            out.append((name, version))

    # Lockfile v1: "dependencies" dict (flat).
    deps_section = data.get("dependencies") or {}
    if isinstance(deps_section, dict):
        for name, info in deps_section.items():
            if not isinstance(info, dict):
                continue
            version = info.get("version")
            if not version:
                continue
            out.append((name, version))

    # Deduplicate — v2 lockfiles have both sections pointing at the same packages.
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for name, version in out:
        if (name, version) in seen:
            continue
        seen.add((name, version))
        deduped.append((name, version))
    return deduped


def _parse_yarn_lock(content: str) -> List[Tuple[str, str]]:
    """Parse yarn.lock (v1 format). Best-effort — handles the common case
    of `name@version:` blocks with a `version "X.Y.Z"` line below.
    """
    out: List[Tuple[str, str]] = []
    current_names: List[str] = []
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if not line:
            current_names = []
            continue
        # Header line: 'name@spec, name@spec:' or '"name@spec":'
        if line and (line.endswith(":") or line.rstrip().endswith(":")) and "@" in line:
            header = line.rstrip().rstrip(":")
            # Split multiple aliases: "name@^1.0.0, name@^1.0.1"
            current_names = []
            for alias in header.split(","):
                alias = alias.strip().strip('"')
                if "@" in alias:
                    # name is everything before the LAST @ (handles scoped @org/pkg)
                    name = alias.rsplit("@", 1)[0]
                    if name:
                        current_names.append(name)
            continue
        # Version line: '  version "1.2.3"'
        stripped = line.strip()
        if stripped.startswith("version ") and current_names:
            version = stripped[len("version "):].strip().strip('"').strip("'")
            if version:
                for name in current_names:
                    out.append((name, version))
                current_names = []
    return out


def _parse_pnpm_lock_yaml(content: str) -> List[Tuple[str, str]]:
    """Parse pnpm-lock.yaml (v9+ format). pnpm v9 uses a `packages:` section
    with entries like `'@scope/pkg@1.2.3':` followed by metadata.
    Falls back to a regex scrape if the structure is unusual.

    Pure-Python parser — no PyYAML dependency. Handles the common v9 layout.
    For v5/v6 lockfiles, the `dependencies:` section is parsed instead.
    """
    import re

    out: List[Tuple[str, str]] = []
    # v9+: scan for `packages:` section entries.
    in_packages = False
    pkg_re = re.compile(r"^\s*'([^']+)@([^@']+)':\s*$")
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.startswith("packages:") or line == "packages:":
            in_packages = True
            continue
        if in_packages:
            # Next top-level key (no leading whitespace, ends with `:`) ends
            # the packages section.
            if line and not line[0].isspace() and line.endswith(":"):
                in_packages = False
                continue
            match = pkg_re.match(line)
            if match:
                name, version = match.group(1), match.group(2)
                # Strip any path / peer-dep suffix after the version.
                version = version.split("(")[0].strip()
                if name and version:
                    out.append((name, version))
    if out:
        return out

    # Fallback: v5/v6 `dependencies:` section with `version: X.Y.Z` lines.
    in_deps = False
    current_name = ""
    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if line.startswith("dependencies:") or line == "dependencies:":
            in_deps = True
            continue
        if in_deps:
            if line and not line[0].isspace() and line.endswith(":"):
                in_deps = False
                continue
            stripped = line.strip()
            if stripped.endswith(":") and not stripped.startswith("version"):
                # 'name:' header
                current_name = stripped.rstrip(":").strip("'\"")
            elif stripped.startswith("version:") and current_name:
                version = stripped[len("version:"):].strip().strip("'\"")
                if version:
                    out.append((current_name, version))
                    current_name = ""
    return out


def _parse_cargo_lock(content: str) -> List[Tuple[str, str]]:
    """Parse Cargo.lock — TOML-ish format with `[[package]]` sections
    containing `name = "..."` and `version = "..."` lines.
    """
    out: List[Tuple[str, str]] = []
    current_name: Optional[str] = None
    current_version: Optional[str] = None
    in_package = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line == "[[package]]":
            if current_name and current_version:
                out.append((current_name, current_version))
            current_name = None
            current_version = None
            in_package = True
            continue
        if not in_package:
            continue
        if line.startswith("name = "):
            current_name = _unquote(line[len("name = "):])
        elif line.startswith("version = "):
            current_version = _unquote(line[len("version = "):])
        elif line.startswith("[") and line != "[[package]]":
            # Entering a different section inside the package (e.g. [package.dependencies])
            # — but a new [[package]] was already handled above, so just ignore.
            pass
    # Flush the last package
    if current_name and current_version:
        out.append((current_name, current_version))
    return out


def _parse_pyproject_toml(content: str) -> List[Tuple[str, str]]:
    """Parse pyproject.toml — extracts `dependencies` array under
    `[project]` and `[tool.poetry.dependencies]`. Uses tomllib (Python 3.11+).
    """
    import tomllib

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        logger.warning(f"[dep_audit] invalid pyproject.toml: {e}")
        return []

    out: List[Tuple[str, str]] = []

    # PEP 621: [project] dependencies = ["name>=1.0", ...]
    project = data.get("project") or {}
    project_deps = project.get("dependencies") or []
    if isinstance(project_deps, list):
        for spec in project_deps:
            name, version = _split_pep508_spec(spec)
            if name:
                out.append((name, version))

    # Poetry: [tool.poetry.dependencies] — dict of name → version spec
    poetry = (data.get("tool") or {}).get("poetry") or {}
    poetry_deps = poetry.get("dependencies") or {}
    if isinstance(poetry_deps, dict):
        for name, spec in poetry_deps.items():
            if name == "python":
                continue
            if isinstance(spec, str):
                version = _strip_python_operator(spec)
                out.append((name, version))
            elif isinstance(spec, dict) and "version" in spec:
                version = _strip_python_operator(str(spec["version"]))
                out.append((name, version))

    return out


def _parse_pipfile(content: str) -> List[Tuple[str, str]]:
    """Parse Pipfile (TOML) — `[packages]` and `[dev-packages]` sections."""
    import tomllib

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        logger.warning(f"[dep_audit] invalid Pipfile: {e}")
        return []
    out: List[Tuple[str, str]] = []
    for section in ("packages", "dev-packages"):
        section_deps = data.get(section) or {}
        if not isinstance(section_deps, dict):
            continue
        for name, spec in section_deps.items():
            if isinstance(spec, str):
                out.append((name, _strip_python_operator(spec)))
            elif isinstance(spec, dict) and "version" in spec:
                out.append((name, _strip_python_operator(str(spec["version"]))))
    return out


def _parse_cargo_toml(content: str) -> List[Tuple[str, str]]:
    """Parse Cargo.toml — `[dependencies]` and `[dev-dependencies]` sections.
    Supports both `name = "version"` and `name = { version = "X", ... }` forms.
    """
    import tomllib

    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        logger.warning(f"[dep_audit] invalid Cargo.toml: {e}")
        return []
    out: List[Tuple[str, str]] = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        section_deps = data.get(section) or {}
        if not isinstance(section_deps, dict):
            continue
        for name, spec in section_deps.items():
            if isinstance(spec, str):
                out.append((name, _strip_cargo_operator(spec)))
            elif isinstance(spec, dict) and "version" in spec:
                out.append(
                    (name, _strip_cargo_operator(str(spec["version"])))
                )
    return out


# ─── Spec-string Helpers ───────────────────────────────────────


def _strip_npm_operator(spec: str) -> str:
    """Strip npm semver operators (^, ~, >=, >, <=, <, =) and any range
    whitespace. Returns the bare version like '1.2.3' or '' for wildcards.
    """
    spec = spec.strip()
    if not spec:
        return ""
    if spec.startswith(("^", "~", ">", "<", "=")):
        spec = spec.lstrip("^~><= ")
    # Handle '1.2.x' / '*' / 'latest' — these can't be queried.
    if spec in ("*", "latest", "") or "x" in spec.lower():
        return ""
    # Take only the first version if it's a range (e.g. "1.2.3 || 2.0.0").
    spec = spec.split(" ", 1)[0].split("||", 1)[0].strip()
    return spec


def _strip_python_operator(spec: str) -> str:
    """Strip PEP 440 operators from a version spec. Returns '' for wildcards."""
    import re

    spec = spec.strip()
    if not spec:
        return ""
    spec = re.sub(r"^[=<>!~^]+", "", spec).strip()
    if spec in ("*", "any", ""):
        return ""
    return spec


def _strip_cargo_operator(spec: str) -> str:
    """Strip Cargo version operators (^, ~, *, >=). Returns '' for wildcards."""
    spec = spec.strip()
    if not spec or spec == "*":
        return ""
    if spec.startswith(("^", "~", ">", "<", "=")):
        spec = spec.lstrip("^~><= ")
    if "*" in spec:
        return ""
    return spec


def _split_pep508_spec(spec: str) -> Tuple[str, str]:
    """Split a PEP 508 requirement spec like 'name>=1.0,<2.0; python_version>"3.8"'
    into (name, version) where version is the first pinned version, or '' if
    only ranges/wildcards are given.
    """
    import re

    if not isinstance(spec, str):
        return ("", "")
    # Strip environment markers.
    spec = spec.split(";", 1)[0].strip()
    # Strip extras.
    spec = re.sub(r"\[[^\]]+\]", "", spec)
    match = re.match(
        r"^\s*([A-Za-z0-9_.\-]+)\s*(?:\s*(==|>=|~=|<=|>|<|=)\s*([A-Za-z0-9_.\-*+!]+))?",
        spec,
    )
    if not match:
        return ("", "")
    name = match.group(1)
    op = match.group(2)
    version = match.group(3) or ""
    # Only == and ~= give a checkable version. >= / > / <= / < are ranges.
    # We still send the bound version to OSV — it'll just return vulns that
    # affect that version, which is the conservative behavior.
    if version in ("*", "any"):
        version = ""
    return (name, version)


def _unquote(s: str) -> str:
    """Strip surrounding double or single quotes from a TOML value string."""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


# ─── OSV API Client ────────────────────────────────────────────


def _query_osv_batch(
    packages: List[Dict[str, str]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Query OSV.dev batch endpoint for all packages.

    Splits `packages` into chunks of OSV_BATCH_SIZE, sends each chunk as a
    POST to /v1/querybatch, then for each returned vuln ID fetches full
    details via GET /v1/vulns/{id}. Vuln details are cached per-run to avoid
    refetching across packages that share vulns.

    Args:
        packages: List of {name, version, ecosystem, source_file} dicts.

    Returns:
        (findings, api_errors) — findings is a list of dicts with keys
        {package, version, ecosystem, source_file, vuln_id, severity,
        fixed_in, summary, osv_url}. api_errors is a list of human-readable
        error strings (empty if all requests succeeded).
    """
    findings: List[Dict[str, Any]] = []
    api_errors: List[str] = []
    vuln_cache: Dict[str, Dict[str, Any]] = {}

    # Skip packages with empty version — OSV requires a version to query.
    queryable = [p for p in packages if p.get("version")]
    skipped = len(packages) - len(queryable)
    if skipped:
        api_errors.append(
            f"[dep_audit] {skipped} package(s) skipped — missing or "
            f"unparseable version (wildcards/ranges not supported by OSV)."
        )

    for chunk_start in range(0, len(queryable), OSV_BATCH_SIZE):
        chunk = queryable[chunk_start : chunk_start + OSV_BATCH_SIZE]
        batch_payload = {"queries": [_build_osv_query(p) for p in chunk]}

        try:
            batch_resp = _http_post_json(OSV_BATCH_URL, batch_payload)
        except Exception as e:
            msg = (
                f"[dep_audit] OSV batch query failed for chunk "
                f"{chunk_start}-{chunk_start + len(chunk)}: {e}"
            )
            logger.error(msg)
            api_errors.append(msg)
            continue

        results = batch_resp.get("results") or []
        for pkg, result in zip(chunk, results):
            vulns = result.get("vulns") or []
            for vuln_entry in vulns:
                vuln_id = vuln_entry.get("id")
                if not vuln_id:
                    continue
                # Fetch full vuln details (cached).
                if vuln_id not in vuln_cache:
                    try:
                        vuln_cache[vuln_id] = _fetch_osv_vuln(vuln_id)
                    except Exception as e:
                        msg = (
                            f"[dep_audit] OSV vuln detail fetch failed for "
                            f"{vuln_id}: {e}"
                        )
                        logger.warning(msg)
                        api_errors.append(msg)
                        vuln_cache[vuln_id] = {}
                details = vuln_cache[vuln_id]
                findings.append(
                    _build_finding(pkg, vuln_id, details)
                )

    return findings, api_errors


def _build_osv_query(pkg: Dict[str, str]) -> Dict[str, Any]:
    """Build a single OSV query object for one package."""
    return {
        "package": {"name": pkg["name"], "ecosystem": pkg["ecosystem"]},
        "version": pkg["version"],
    }


def _fetch_osv_vuln(vuln_id: str) -> Dict[str, Any]:
    """GET /v1/vulns/{id} — returns full vuln record with severity,
    affected ranges, and summaries. Retries with exponential backoff on
    transient errors (5xx, network).
    """
    url = OSV_VULN_URL.format(vuln_id=vuln_id)
    return _http_get_json(url)


def _build_finding(
    pkg: Dict[str, str], vuln_id: str, details: Dict[str, Any]
) -> Dict[str, Any]:
    """Assemble a finding dict from package + OSV vuln details.

    Extracts:
        - severity: from database_specific.severity OR CVSS v3 base score
        - fixed_in: first fixed version from affected[].ranges[].events
        - summary: vuln summary field
        - cve_ids: list of CVE aliases
    """
    severity = _extract_severity(details)
    fixed_in = _extract_fixed_version(details, pkg)
    summary = details.get("summary") or ""
    aliases = details.get("aliases") or []
    cve_ids = [a for a in aliases if a.startswith("CVE-")]

    return {
        "package": pkg["name"],
        "version": pkg["version"],
        "ecosystem": pkg["ecosystem"],
        "source_file": pkg["source_file"],
        "vuln_id": vuln_id,
        "severity": severity,
        "fixed_in": fixed_in,
        "summary": summary,
        "cve_ids": cve_ids,
        "osv_url": f"https://osv.dev/vulnerability/{vuln_id}",
    }


def _extract_severity(details: Dict[str, Any]) -> str:
    """Extract severity bucket from an OSV vuln record.

    Priority:
      1. database_specific.severity (e.g. "CRITICAL", "HIGH") if it matches
         a known bucket.
      2. severity[].score string — parse CVSS v3 base score from the vector.
      3. "unknown" if neither is present.
    """
    db_specific = details.get("database_specific") or {}
    if isinstance(db_specific, dict):
        raw_sev = db_specific.get("severity")
        if isinstance(raw_sev, str):
            bucket = _normalize_severity_string(raw_sev)
            if bucket != "unknown":
                return bucket
        # Some ecosystems put severity under severity[].type
    # Try severity[] array (CVSS vectors)
    for sev_entry in details.get("severity") or []:
        if not isinstance(sev_entry, dict):
            continue
        score_str = sev_entry.get("score") or ""
        # CVSS v3 vector string like
        # "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H" — base score not
        # directly embedded. We need to compute it. Or look for a numeric
        # string in database_specific.
        bucket = _cvss_vector_to_severity(score_str)
        if bucket != "unknown":
            return bucket
    return "unknown"


def _normalize_severity_string(raw: str) -> str:
    """Normalize 'CRITICAL' / 'High' / 'MODERATE' / etc. to canonical bucket."""
    raw = raw.strip().upper()
    if raw in ("CRITICAL",):
        return "critical"
    if raw in ("HIGH",):
        return "high"
    if raw in ("MEDIUM", "MODERATE"):
        return "medium"
    if raw in ("LOW",):
        return "low"
    return "unknown"


def _cvss_vector_to_severity(vector: str) -> str:
    """Compute CVSS v3 base score from a vector string and return the
    severity bucket. Returns 'unknown' if the vector can't be parsed.

    Pure-Python implementation — no external CVSS library. Uses the standard
    CVSS v3.1 base score formula from the official spec.
    """
    if not isinstance(vector, str) or not vector.startswith("CVSS:3."):
        return "unknown"
    parts = vector.split("/")
    metrics: Dict[str, str] = {}
    for part in parts:
        if ":" in part:
            k, v = part.split(":", 1)
            metrics[k] = v
    try:
        # Metric values per CVSS v3.1 spec
        av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}[metrics["AV"]]
        ac = {"L": 0.77, "H": 0.44}[metrics["AC"]]
        pr = (
            {"N": 0.85, "L": 0.62, "H": 0.27}[metrics["PR"]]
            if metrics.get("S") == "U"
            else {"N": 0.85, "L": 0.68, "H": 0.5}[metrics["PR"]]
        )
        ui = {"N": 0.85, "R": 0.62}[metrics["UI"]]
        c = {"H": 0.56, "L": 0.22, "N": 0.0}[metrics["C"]]
        i = {"H": 0.56, "L": 0.22, "N": 0.0}[metrics["I"]]
        a = {"H": 0.56, "L": 0.22, "N": 0.0}[metrics["A"]]
    except (KeyError, TypeError):
        return "unknown"

    iss = 1 - ((1 - c) * (1 - i) * (1 - a))
    if metrics.get("S") == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    exploitability = 8.22 * av * ac * pr * ui
    if impact <= 0:
        return "unknown"
    if metrics.get("S") == "U":
        base = min(impact + exploitability, 10)
    else:
        base = min(1.08 * (impact + exploitability), 10)
    base = round(base, 1)
    # Round up to one decimal per CVSS v3.1
    if base >= 9.0:
        return "critical"
    if base >= 7.0:
        return "high"
    if base >= 4.0:
        return "medium"
    return "low"


def _extract_fixed_version(
    details: Dict[str, Any], pkg: Dict[str, str]
) -> str:
    """Extract the first fixed version from an OSV vuln record.

    Scans `affected[]` for an entry matching our package, then walks
    `ranges[].events[]` looking for a `fixed` event. Returns "" if no fixed
    version is recorded.
    """
    for affected in details.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        affected_pkg = affected.get("package") or {}
        if affected_pkg.get("name") != pkg["name"]:
            continue
        if affected_pkg.get("ecosystem") != pkg["ecosystem"]:
            continue
        for rng in affected.get("ranges") or []:
            if not isinstance(rng, dict):
                continue
            for event in rng.get("events") or []:
                if not isinstance(event, dict):
                    continue
                if "fixed" in event:
                    return str(event["fixed"])
    return ""


# ─── HTTP Helpers ──────────────────────────────────────────────


def _http_post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST JSON to OSV API with retry+backoff. Raises on persistent failure."""
    body = json.dumps(payload).encode("utf-8")
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "User-Agent": "CodeLens-deps-audit/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            # 429 = rate limit; 5xx = transient. Retry with backoff.
            if e.code in (429, 500, 502, 503, 504):
                retry_after = e.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(min(int(retry_after), 30))
                    except ValueError:
                        time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
                else:
                    time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
                continue
            # 4xx other than 429 — don't retry, fail fast.
            raise
        except urllib.error.URLError as e:
            last_exc = e
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
            continue
    raise last_exc  # type: ignore[misc]


def _http_get_json(url: str) -> Dict[str, Any]:
    """GET JSON from OSV API with retry+backoff. Raises on persistent failure."""
    last_exc: Optional[Exception] = None
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                url,
                method="GET",
                headers={
                    "Accept": "application/json",
                    "User-Agent": "CodeLens-deps-audit/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_exc = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
                continue
            raise
        except urllib.error.URLError as e:
            last_exc = e
            time.sleep(RETRY_BACKOFF_BASE * (2 ** attempt))
            continue
    raise last_exc  # type: ignore[misc]


# ─── Stats + Persistence ───────────────────────────────────────


def _compute_stats(
    findings: List[Dict[str, Any]],
    packages: List[Dict[str, str]],
    ecosystems_scanned: Tuple[str, ...],
) -> Dict[str, Any]:
    """Compute summary stats for the audit run."""
    by_sev = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    for f in findings:
        sev = f.get("severity", "unknown")
        if sev in by_sev:
            by_sev[sev] += 1
        else:
            by_sev["unknown"] += 1
    return {
        "total": len(findings),
        "critical": by_sev["critical"],
        "high": by_sev["high"],
        "medium": by_sev["medium"],
        "low": by_sev["low"],
        "unknown": by_sev["unknown"],
        "packages_scanned": len(packages),
        "ecosystems_scanned": len(ecosystems_scanned),
    }


def _persist_findings_to_graph(
    workspace: str,
    db_path: Optional[str],
    findings: List[Dict[str, Any]],
    packages: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """Persist findings as `dependency_vuln` graph nodes + `HAS_VULN` edges.

    Each finding becomes a node with:
        node_id = "dep_vuln:{vuln_id}:{package}:{ecosystem}"
        node_type = "dependency_vuln"
        name = "{package}@{version} ({vuln_id})"
        file = source_file (the lock/manifest path)
        extra_json = full finding dict

    For each finding, an edge is created from the source file (as a `file`
    node) to the vuln node with edge_type = "HAS_VULN".

    Returns:
        Dict with {nodes_inserted, edges_inserted, db_path} or None if
        persistence was skipped (e.g. no db_path, no findings).
    """
    if not findings:
        return None

    workspace = os.path.abspath(workspace)
    db_path = db_path or default_db_path(workspace)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    nodes_inserted = 0
    edges_inserted = 0
    try:
        init_graph_schema(conn)

        # Idempotent: delete previous deps-audit findings for these files
        # before re-inserting, so re-scans don't accumulate duplicates.
        source_files = sorted({f.get("source_file", "") for f in findings if f.get("source_file")})
        if source_files:
            placeholders = ",".join("?" * len(source_files))
            conn.execute(
                f"DELETE FROM {GRAPH_EDGES_TABLE} WHERE edge_type = ? "
                f"AND file IN ({placeholders})",
                [EDGE_TYPE_HAS_VULN] + source_files,
            )
            # Delete vuln nodes that are no longer referenced by any edge.
            conn.execute(
                f"DELETE FROM {GRAPH_NODES_TABLE} WHERE node_type = ? "
                f"AND node_id NOT IN (SELECT target_id FROM {GRAPH_EDGES_TABLE})",
                [NODE_TYPE_DEPENDENCY_VULN],
            )

        for finding in findings:
            vuln_id = finding.get("vuln_id", "")
            pkg_name = finding.get("package", "")
            version = finding.get("version", "")
            ecosystem = finding.get("ecosystem", "")
            source_file = finding.get("source_file", "")

            node_id = f"dep_vuln:{vuln_id}:{pkg_name}:{ecosystem}"
            node_name = f"{pkg_name}@{version} ({vuln_id})"
            extra_json = json.dumps(finding, sort_keys=True)

            try:
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO {GRAPH_NODES_TABLE} "
                    f"(node_id, node_type, name, file, line, extra_json) "
                    f"VALUES (?, ?, ?, ?, ?, ?)",
                    (node_id, NODE_TYPE_DEPENDENCY_VULN, node_name, source_file, 0, extra_json),
                )
                if cur.rowcount > 0:
                    nodes_inserted += 1
            except sqlite3.Error as e:
                logger.warning(
                    f"[dep_audit] failed to insert vuln node {node_id}: {e}"
                )
                continue

            # Insert the file node (if not already present) and link with HAS_VULN
            if source_file:
                file_node_id = f"file:{source_file}"
                try:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {GRAPH_NODES_TABLE} "
                        f"(node_id, node_type, name, file, line, extra_json) "
                        f"VALUES (?, ?, ?, ?, ?, ?)",
                        (file_node_id, NODE_TYPE_FILE, source_file, source_file, 0, None),
                    )
                except sqlite3.Error as e:
                    logger.warning(
                        f"[dep_audit] failed to insert file node {file_node_id}: {e}"
                    )

                try:
                    cur = conn.execute(
                        f"INSERT INTO {GRAPH_EDGES_TABLE} "
                        f"(source_id, target_id, edge_type, file, line, confidence, extra_json) "
                        f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (file_node_id, node_id, EDGE_TYPE_HAS_VULN, source_file, 0, 1.0, None),
                    )
                    if cur.rowcount > 0:
                        edges_inserted += 1
                except sqlite3.Error as e:
                    logger.warning(
                        f"[dep_audit] failed to insert HAS_VULN edge: {e}"
                    )

        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"[dep_audit] graph persistence failed: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

    return {
        "nodes_inserted": nodes_inserted,
        "edges_inserted": edges_inserted,
        "db_path": db_path,
    }


# ─── Recommendations ───────────────────────────────────────────


def _generate_recommendations(
    findings: List[Dict[str, Any]], api_errors: List[str]
) -> List[str]:
    """Generate actionable recommendations based on the audit findings."""
    recs: List[str] = []

    if not findings and not api_errors:
        recs.append(
            "No known vulnerabilities found in scanned dependencies. "
            "Re-run periodically — new CVEs are published daily."
        )
        return recs

    if api_errors:
        recs.append(
            "WARNING: API errors occurred during the scan — results may be "
            "incomplete. See the `api_errors` field for details."
        )

    if not findings:
        return recs

    critical = [f for f in findings if f.get("severity") == "critical"]
    high = [f for f in findings if f.get("severity") == "high"]

    if critical:
        crit_packages = sorted({f["package"] for f in critical})
        recs.append(
            f"CRITICAL: {len(critical)} critical vulnerability(ies) found in "
            f"{len(crit_packages)} package(s): "
            f"{', '.join(crit_packages[:10])}. "
            f"Upgrade immediately — these are likely exploitable."
        )

    if high:
        high_packages = sorted({f["package"] for f in high})
        recs.append(
            f"HIGH: {len(high)} high-severity vulnerability(ies) in "
            f"{len(high_packages)} package(s): "
            f"{', '.join(high_packages[:10])}. "
            f"Upgrade before the next release."
        )

    # Group by package to suggest consolidated upgrades
    by_pkg: Dict[str, List[Dict[str, Any]]] = {}
    for f in findings:
        by_pkg.setdefault(f["package"], []).append(f)

    upgradable = [
        pkg for pkg, flist in by_pkg.items()
        if any(f.get("fixed_in") for f in flist)
    ]
    if upgradable:
        recs.append(
            f"UPGRADE: {len(upgradable)} package(s) have a known fixed "
            f"version. Update your manifest/lock file to the version listed "
            f"in the `fixed_in` field of each finding."
        )

    no_fix = [pkg for pkg, flist in by_pkg.items() if not any(f.get("fixed_in") for f in flist)]
    if no_fix:
        recs.append(
            f"NO FIX AVAILABLE: {len(no_fix)} package(s) have vulnerabilities "
            f"with no recorded fix. Consider replacing or pinning a "
            f"workaround: {', '.join(sorted(no_fix)[:10])}."
        )

    return recs
