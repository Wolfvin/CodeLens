"""
OSV.dev API Client for CodeLens v5
Real-time vulnerability database integration via https://api.osv.dev

Provides live CVE/OSV data with SQLite caching, batch queries,
rate limiting, and graceful offline fallback.

Architecture:
- Phase 0 (new): OSV.dev API — query real-time vulnerability data
  - Batch queries (up to 100 packages per request)
  - SQLite cache with configurable TTL (default 24 hours)
  - Graceful fallback: API → Cache → built-in VULN_DB

Supported ecosystems: PyPI, npm, Go, Maven, Cargo, NuGet, RubyGems, Pub, Hex

Answers: "Are there any known vulnerabilities in my dependencies RIGHT NOW?"
Answers: "What does the OSV database say about my packages?"
"""

import os
import re
import json
import time
import sqlite3
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
from pathlib import Path

try:
    import urllib.request
    import urllib.error
    import urllib.parse
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False

try:
    from utils import logger
except ImportError:
    logger = logging.getLogger("osv_client")

# ─── Constants ─────────────────────────────────────────────────

OSV_API_BASE = "https://api.osv.dev"
OSV_QUERY_ENDPOINT = "/v1/query"           # Single package query (returns full vuln data)
OSV_BATCH_ENDPOINT = "/v1/querybatch"      # Batch query (returns vuln IDs only)
OSV_VULN_ENDPOINT = "/v1/vulns"            # Get full vuln details by ID
DEFAULT_TTL = 86400  # 24 hours in seconds
DEFAULT_TIMEOUT = 30  # seconds
MAX_REQUESTS_PER_SECOND = 10
MAX_BATCH_SIZE = 100  # OSV supports up to 1000 but 100 is safer
CACHE_DIR_NAME = ".codelens"
CACHE_DB_NAME = "osv_cache.db"
CACHE_MAX_SIZE_MB = 100  # Vacuum if cache exceeds this

# Ecosystem name mapping: CodeLens ecosystem → OSV ecosystem name
ECOSYSTEM_MAP = {
    "npm": "npm",
    "pip": "PyPI",
    "rust": "crates.io",
    "go": "Go",
    "maven": "Maven",
    "nuget": "NuGet",
    "rubygems": "RubyGems",
    "pub": "Pub",
    "hex": "Hex",
    "nimble": None,  # Not supported by OSV
}

# Reverse mapping: OSV ecosystem → CodeLens ecosystem
OSV_ECOSYSTEM_REVERSE = {v: k for k, v in ECOSYSTEM_MAP.items() if v is not None}
# Add common aliases
OSV_ECOSYSTEM_REVERSE["npm"] = "npm"
OSV_ECOSYSTEM_REVERSE["PyPI"] = "pip"
OSV_ECOSYSTEM_REVERSE["crates.io"] = "rust"
OSV_ECOSYSTEM_REVERSE["Go"] = "go"


# ─── Data Classes ──────────────────────────────────────────────

@dataclass
class OSVPackage:
    """Represents a package to query against OSV."""
    name: str
    version: str
    ecosystem: str  # OSV ecosystem name (e.g., "PyPI", "npm", "Go")

    def to_query(self) -> Dict[str, Any]:
        """Convert to OSV query format."""
        return {
            "package": {
                "name": self.name,
                "ecosystem": self.ecosystem,
            },
            "version": self.version,
        }

    def cache_key(self) -> str:
        """Generate a cache key for this package query."""
        return f"{self.ecosystem}|{self.name}|{self.version}"


@dataclass
class OSVVulnerability:
    """Represents a vulnerability from OSV.dev."""
    id: str                          # e.g., "GHSA-xxxx-xxxx-xxxx" or "CVE-2023-xxxxx"
    summary: str                     # Short description
    severity: str                    # CodeLens severity: critical/high/medium/low
    cvss_score: Optional[float]      # CVSS v2/v3 base score (None if not available)
    cvss_version: Optional[str]      # "2.0" or "3.1" etc.
    affected_versions: str           # e.g., "<4.17.21"
    fixed_version: str               # e.g., "4.17.21"
    references: List[str]            # URLs for advisories
    cwe: str                         # CWE identifier (e.g., "CWE-79")
    ecosystem: str                   # OSV ecosystem
    package: str                     # Package name
    installed_version: str           # Version that was queried
    source: str = "osv_dev"          # Data source identifier

    def to_finding(self) -> Dict[str, Any]:
        """Convert to vulnscan_engine finding format."""
        return {
            "type": "vulnerability",
            "ecosystem": OSV_ECOSYSTEM_REVERSE.get(self.ecosystem, self.ecosystem.lower()),
            "package": self.package,
            "installed_version": self.installed_version,
            "vulnerable_range": self.affected_versions,
            "severity": self.severity,
            "cve": self.id,
            "title": self.summary[:120] if self.summary else f"Vulnerability {self.id}",
            "fix_version": self.fixed_version,
            "file": "",
            "source": self.source,
            "cvss_score": self.cvss_score,
            "cvss_version": self.cvss_version,
            "cwe": self.cwe,
            "references": self.references[:5],  # Cap at 5 URLs
        }


# ─── SQLite Cache ──────────────────────────────────────────────

class OSVCache:
    """SQLite-based cache for OSV API responses.

    Schema: cache(package_ecosystem_version, response_json, timestamp, ttl)
    - package_ecosystem_version: composite key like "npm|lodash|4.17.15"
    - response_json: JSON-serialized OSV response
    - timestamp: Unix timestamp when cached
    - ttl: Time-to-live in seconds
    """

    def __init__(self, workspace: str, ttl: int = DEFAULT_TTL):
        self.ttl = ttl
        self._lock = threading.Lock()

        # Create cache directory
        cache_dir = os.path.join(workspace, CACHE_DIR_NAME)
        os.makedirs(cache_dir, exist_ok=True)

        self.db_path = os.path.join(cache_dir, CACHE_DB_NAME)
        self._init_db()
        self._maybe_vacuum()

    def _init_db(self):
        """Initialize the SQLite database and create table if not exists."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        package_ecosystem_version TEXT PRIMARY KEY,
                        response_json TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        ttl INTEGER NOT NULL DEFAULT 86400
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_timestamp
                    ON cache(timestamp)
                """)
                conn.commit()
            finally:
                conn.close()

    def _maybe_vacuum(self):
        """Vacuum the database if it exceeds the size limit."""
        try:
            db_size = os.path.getsize(self.db_path)
            if db_size > CACHE_MAX_SIZE_MB * 1024 * 1024:
                logger.info("OSV cache exceeds %dMB, vacuuming...", CACHE_MAX_SIZE_MB)
                self.cleanup()
                with self._lock:
                    conn = sqlite3.connect(self.db_path)
                    try:
                        conn.execute("VACUUM")
                        conn.commit()
                    finally:
                        conn.close()
                new_size = os.path.getsize(self.db_path)
                logger.info("OSV cache vacuumed: %.1fMB → %.1fMB",
                            db_size / (1024 * 1024), new_size / (1024 * 1024))
        except (OSError, sqlite3.Error) as exc:
            logger.debug("OSV cache vacuum failed: %s", exc)

    def get(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Retrieve cached OSV response if not expired.

        Args:
            key: Cache key (e.g., "npm|lodash|4.17.15")

        Returns:
            Parsed OSV response (list of vuln objects) or None if not found/expired
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT response_json, timestamp, ttl FROM cache WHERE package_ecosystem_version = ?",
                    (key,)
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                response_json, timestamp, ttl = row
                if time.time() - timestamp > ttl:
                    # Expired — delete and return None
                    conn.execute(
                        "DELETE FROM cache WHERE package_ecosystem_version = ?",
                        (key,)
                    )
                    conn.commit()
                    return None

                try:
                    return json.loads(response_json)
                except json.JSONDecodeError:
                    # Corrupt cache entry — delete
                    conn.execute(
                        "DELETE FROM cache WHERE package_ecosystem_version = ?",
                        (key,)
                    )
                    conn.commit()
                    return None
            finally:
                conn.close()

    def peek(self, key: str) -> Optional[Tuple[List[Dict[str, Any]], float, int]]:
        """Retrieve a cache entry WITHOUT TTL check or deletion.

        Unlike :meth:`get`, this method does not apply the stored TTL when
        deciding whether to return the entry. Callers receive the raw
        ``(response, timestamp, ttl)`` tuple and decide staleness themselves
        — for example using a ``--max-age`` override (issue #30).

        Corrupt entries (invalid JSON) are deleted and treated as missing.

        Args:
            key: Cache key (e.g., ``"npm|lodash|4.17.15"``)

        Returns:
            Tuple of ``(response, timestamp, ttl)`` or ``None`` if the key is
            not present or corrupt. ``timestamp`` is a Unix epoch float;
            ``ttl`` is the stored TTL in seconds.
        """
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT response_json, timestamp, ttl FROM cache "
                    "WHERE package_ecosystem_version = ?",
                    (key,)
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                response_json, timestamp, ttl = row
                try:
                    response = json.loads(response_json)
                except json.JSONDecodeError:
                    # Corrupt cache entry — delete and treat as missing
                    conn.execute(
                        "DELETE FROM cache WHERE package_ecosystem_version = ?",
                        (key,)
                    )
                    conn.commit()
                    return None
                return (response, timestamp, ttl)
            finally:
                conn.close()

    def set(self, key: str, response: List[Dict[str, Any]], ttl: Optional[int] = None):
        """Cache an OSV API response.

        Args:
            key: Cache key (e.g., "npm|lodash|4.17.15")
            response: Parsed OSV response (list of vuln objects)
            ttl: Time-to-live in seconds (defaults to instance TTL)
        """
        if ttl is None:
            ttl = self.ttl

        response_json = json.dumps(response, ensure_ascii=False)
        timestamp = time.time()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO cache (package_ecosystem_version, response_json, timestamp, ttl)
                       VALUES (?, ?, ?, ?)""",
                    (key, response_json, timestamp, ttl)
                )
                conn.commit()
            finally:
                conn.close()

    def batch_set(self, entries: List[Tuple[str, List[Dict[str, Any]]]], ttl: Optional[int] = None):
        """Cache multiple OSV API responses in a single transaction.

        Args:
            entries: List of (key, response) tuples
            ttl: Time-to-live in seconds (defaults to instance TTL)
        """
        if not entries:
            return
        if ttl is None:
            ttl = self.ttl

        timestamp = time.time()

        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executemany(
                    """INSERT OR REPLACE INTO cache (package_ecosystem_version, response_json, timestamp, ttl)
                       VALUES (?, ?, ?, ?)""",
                    [(key, json.dumps(resp, ensure_ascii=False), timestamp, ttl) for key, resp in entries]
                )
                conn.commit()
            finally:
                conn.close()

    def cleanup(self):
        """Remove all expired entries from the cache."""
        now = time.time()
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "DELETE FROM cache WHERE ? - timestamp > ttl",
                    (now,)
                )
                deleted = cursor.rowcount
                conn.commit()
                if deleted > 0:
                    logger.debug("OSV cache: removed %d expired entries", deleted)
            finally:
                conn.close()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM cache")
                total = cursor.fetchone()[0]

                now = time.time()
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM cache WHERE ? - timestamp <= ttl",
                    (now,)
                )
                valid = cursor.fetchone()[0]

                try:
                    db_size = os.path.getsize(self.db_path)
                except OSError:
                    db_size = 0

                return {
                    "total_entries": total,
                    "valid_entries": valid,
                    "expired_entries": total - valid,
                    "db_size_bytes": db_size,
                    "db_size_mb": round(db_size / (1024 * 1024), 2),
                }
            finally:
                conn.close()


# ─── Rate Limiter ──────────────────────────────────────────────

class _RateLimiter:
    """Simple rate limiter: max N requests per second."""

    def __init__(self, max_per_second: int = MAX_REQUESTS_PER_SECOND):
        self.max_per_second = max_per_second
        self._lock = threading.Lock()
        self._timestamps: List[float] = []

    def acquire(self):
        """Block until a request slot is available."""
        with self._lock:
            now = time.time()
            # Remove timestamps older than 1 second
            self._timestamps = [t for t in self._timestamps if now - t < 1.0]

            if len(self._timestamps) >= self.max_per_second:
                # Wait until the oldest request exits the window
                sleep_time = 1.0 - (now - self._timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)

            self._timestamps.append(time.time())


# ─── OSV Client ────────────────────────────────────────────────

class OSVClient:
    """Main OSV.dev API client for real-time vulnerability data.

    Features:
    - Batch queries for efficiency (up to 100 packages per request)
    - SQLite cache with configurable TTL
    - Rate limiting (max 10 requests/second)
    - Exponential backoff on 429 responses
    - Graceful fallback when offline → cache → built-in VULN_DB
    - Support for 9 ecosystems: PyPI, npm, Go, Maven, Cargo, NuGet, RubyGems, Pub, Hex

    Usage:
        client = OSVClient(workspace="/path/to/project")
        packages = [OSVPackage("lodash", "4.17.15", "npm")]
        vulns = client.query_packages(packages)
        for vuln in vulns:
            print(f"{vuln.id}: {vuln.severity} - {vuln.summary}")
    """

    def __init__(
        self,
        workspace: str,
        ttl: int = DEFAULT_TTL,
        timeout: int = DEFAULT_TIMEOUT,
        offline: bool = False,
    ):
        """Initialize OSV client.

        Args:
            workspace: Path to workspace root (for cache location)
            ttl: Cache TTL in seconds (default 24 hours)
            timeout: HTTP request timeout in seconds
            offline: If True, skip API queries and use cache only
        """
        self.workspace = os.path.abspath(workspace)
        self.timeout = timeout
        self.offline = offline
        self.cache = OSVCache(workspace, ttl=ttl)
        self._rate_limiter = _RateLimiter(MAX_REQUESTS_PER_SECOND)
        self._request_count = 0
        self._cache_hit_count = 0
        self._api_error_count = 0

    def query_single(
        self,
        name: str,
        version: str,
        ecosystem: str,
    ) -> List[OSVVulnerability]:
        """Query a single package against OSV.dev.

        Args:
            name: Package name (e.g., "lodash")
            version: Package version (e.g., "4.17.15")
            ecosystem: OSV ecosystem name (e.g., "npm", "PyPI", "Go")

        Returns:
            List of OSVVulnerability objects
        """
        # Map CodeLens ecosystem to OSV ecosystem
        osv_ecosystem = ECOSYSTEM_MAP.get(ecosystem, ecosystem)
        if osv_ecosystem is None:
            # Not supported by OSV (e.g., nimble)
            return []

        pkg = OSVPackage(name=name, version=version, ecosystem=osv_ecosystem)
        results = self.query_packages([pkg])
        return results

    def query_packages(
        self,
        packages: List[OSVPackage],
        force_refresh: bool = False,
        max_age: Optional[int] = None,
    ) -> List[OSVVulnerability]:
        """Query multiple packages against OSV.dev.

        Uses batch queries for efficiency. Checks cache first,
        then queries API for uncached packages.

        Args:
            packages: List of OSVPackage objects to query
            force_refresh: If True, bypass the OSV cache and force fresh
                API calls for every package (issue #30 ``--refresh`` flag).
                Silently ignored when ``self.offline`` is True (no network
                available). Cached entries are still updated with new results.
            max_age: Optional per-run TTL override in seconds. When set,
                cached entries older than ``max_age`` are treated as stale
                and re-fetched from the API for this run only (issue #30
                ``--max-age`` flag). The stored TTL is unchanged. Use
                ``max_age=0`` to force-refresh all entries without the
                ``force_refresh`` flag.

        Returns:
            List of OSVVulnerability objects (deduplicated)
        """
        if not packages:
            return []

        all_vulns: List[OSVVulnerability] = []
        uncached_packages: List[OSVPackage] = []
        uncached_keys: List[str] = []

        # --refresh is meaningless in offline mode (no network to refresh
        # from). Fall back to normal cache behaviour so users still get
        # whatever cached data exists.
        effective_force_refresh = force_refresh and not self.offline

        for pkg in packages:
            if pkg.ecosystem is None:
                continue  # Not supported by OSV

            cache_key = pkg.cache_key()

            if effective_force_refresh:
                # Issue #30 --refresh: bypass cache, force fresh API call.
                uncached_packages.append(pkg)
                uncached_keys.append(cache_key)
                continue

            if max_age is not None:
                # Issue #30 --max-age: apply a per-run TTL threshold using
                # peek() so the stored entry (and its stored TTL) is left
                # intact for future runs.
                entry = self.cache.peek(cache_key)
                if entry is None:
                    uncached_packages.append(pkg)
                    uncached_keys.append(cache_key)
                    continue
                response, timestamp, _stored_ttl = entry
                if (time.time() - timestamp) > max_age:
                    # Stale per --max-age — re-fetch
                    uncached_packages.append(pkg)
                    uncached_keys.append(cache_key)
                    continue
                # Fresh per --max-age — use cached response
                self._cache_hit_count += 1
                all_vulns.extend(self._parse_cached_response(response, pkg))
                continue

            # Normal mode — TTL-based cache.get()
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._cache_hit_count += 1
                all_vulns.extend(self._parse_cached_response(cached, pkg))
            else:
                uncached_packages.append(pkg)
                uncached_keys.append(cache_key)

        # Query API for uncached packages
        if uncached_packages and not self.offline:
            api_vulns = self._batch_query_api(uncached_packages)
            all_vulns.extend(api_vulns)

        return all_vulns

    def _parse_cached_response(
        self,
        cached: List[Any],
        package: OSVPackage,
    ) -> List[OSVVulnerability]:
        """Parse a cached OSV response for a single package.

        The OSV cache stores two response shapes (both as JSON lists):

        1. A list of vulnerability IDs (strings) — produced by the
           ``/v1/querybatch`` endpoint. Each ID must be resolved to its
           full detail via :meth:`_fetch_vuln_detail` (which itself uses
           the cache).
        2. A list of full vulnerability dicts — produced by the
           ``/v1/query`` fallback path. Parsed directly via
           :meth:`_parse_osv_response`.

        Args:
            cached: The cached JSON list (may be empty).
            package: The OSVPackage this cache entry belongs to.

        Returns:
            List of OSVVulnerability objects (possibly empty).
        """
        if not cached:
            return []

        if isinstance(cached[0], str):
            # List of vuln IDs → fetch details from cache/API
            results: List[OSVVulnerability] = []
            for vuln_id in cached:
                vuln_detail = self._fetch_vuln_detail(vuln_id)
                if vuln_detail is not None:
                    parsed = self._parse_single_vuln(vuln_detail, package)
                    if parsed is not None:
                        results.append(parsed)
            return results

        # List of full vuln dicts → parse directly
        return self._parse_osv_response(cached, package)

    def batch_query(
        self,
        packages: List[OSVPackage],
        batch_size: int = MAX_BATCH_SIZE,
    ) -> List[OSVVulnerability]:
        """Query packages in batches for efficiency.

        Args:
            packages: List of OSVPackage objects
            batch_size: Number of packages per API request (max 100)

        Returns:
            List of OSVVulnerability objects
        """
        return self.query_packages(packages)

    def _batch_query_api(
        self,
        packages: List[OSVPackage],
    ) -> List[OSVVulnerability]:
        """Send batch queries to OSV.dev API.

        Strategy:
        1. Use /v1/querybatch to get vulnerability IDs for all packages (efficient, 1 req per 100 pkgs)
        2. For each unique vuln ID, check the cache for full details
        3. For uncached vuln IDs, fetch full details from /v1/vulns/{id}
        4. Parse full details and cache them

        Falls back to individual /v1/query requests on batch failure.

        Args:
            packages: List of uncached OSVPackage objects

        Returns:
            List of OSVVulnerability objects from API responses
        """
        all_vulns: List[OSVVulnerability] = []

        # Process in batches via /v1/querybatch
        for i in range(0, len(packages), MAX_BATCH_SIZE):
            batch = packages[i:i + MAX_BATCH_SIZE]

            try:
                response_data = self._make_batch_api_request(batch)
                self._request_count += 1

                if response_data is not None:
                    results_list = response_data.get("results", [])

                    # Collect all vuln IDs and their associated packages
                    vuln_pkg_map: Dict[str, List[OSVPackage]] = defaultdict(list)
                    for idx, result in enumerate(results_list):
                        if idx < len(batch) and isinstance(result, dict):
                            pkg = batch[idx]
                            vuln_ids = []
                            for vuln_summary in result.get("vulns", []):
                                vuln_id = vuln_summary.get("id", "") if isinstance(vuln_summary, dict) else ""
                                if vuln_id:
                                    vuln_pkg_map[vuln_id].append(pkg)
                                    vuln_ids.append(vuln_id)
                            # Cache the list of vuln IDs for this package query
                            # This enables offline lookup: pkg query → vuln IDs → cached vuln details
                            self.cache.set(pkg.cache_key(), vuln_ids)

                    # Fetch full details for each unique vuln ID
                    for vuln_id, associated_pkgs in vuln_pkg_map.items():
                        vuln_detail = self._fetch_vuln_detail(vuln_id)
                        if vuln_detail is not None:
                            # Create a finding for each package this vuln affects
                            for pkg in associated_pkgs:
                                parsed = self._parse_single_vuln(vuln_detail, pkg)
                                if parsed is not None:
                                    all_vulns.append(parsed)

            except Exception as exc:
                self._api_error_count += 1
                logger.warning("OSV API batch query failed (batch %d): %s", i // MAX_BATCH_SIZE, exc)

                # Fallback: individual /v1/query requests (returns full data)
                for pkg in batch:
                    try:
                        single_response = self._make_single_api_request(pkg)
                        self._request_count += 1
                        if single_response is not None:
                            raw_vulns = single_response.get("vulns", [])
                            # Cache each vuln's full data
                            for v in raw_vulns:
                                vid = v.get("id", "")
                                if vid:
                                    self.cache.set(f"vuln:{vid}", v)
                            # Also cache the package-level response
                            self.cache.set(pkg.cache_key(), raw_vulns)
                            vulns = self._parse_osv_response(raw_vulns, pkg)
                            all_vulns.extend(vulns)
                    except Exception as single_exc:
                        self._api_error_count += 1
                        logger.debug("OSV API single query failed for %s@%s: %s",
                                     pkg.name, pkg.version, single_exc)

        return all_vulns

    def _make_batch_api_request(
        self,
        packages: List[OSVPackage],
        max_retries: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Make a batch query request to the OSV.dev /v1/querybatch endpoint.

        Args:
            packages: List of OSVPackage objects (up to MAX_BATCH_SIZE)
            max_retries: Maximum number of retries with exponential backoff

        Returns:
            Parsed JSON response with "results" array, or None on failure
        """
        if not _HAS_URLLIB:
            logger.debug("urllib not available, skipping OSV API request")
            return None

        # Build the request body for /v1/querybatch
        queries = [pkg.to_query() for pkg in packages]
        body = json.dumps({"queries": queries}, ensure_ascii=False).encode("utf-8")

        url = OSV_API_BASE + OSV_BATCH_ENDPOINT
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CodeLens-OSVClient/1.0",
        }

        backoff = 1
        for attempt in range(max_retries + 1):
            self._rate_limiter.acquire()

            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        return data
                    else:
                        logger.debug("OSV API returned status %d", resp.status)
                        return None

            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    # Rate limited — exponential backoff
                    if attempt < max_retries:
                        wait = backoff * 2
                        logger.info("OSV API rate limited, retrying in %ds (attempt %d/%d)",
                                    wait, attempt + 1, max_retries)
                        time.sleep(wait)
                        backoff = min(backoff * 2, 60)  # Cap at 60s
                        continue
                    else:
                        logger.warning("OSV API rate limited, max retries exceeded")
                        return None
                elif exc.code >= 500:
                    # Server error — retry with backoff
                    if attempt < max_retries:
                        time.sleep(backoff)
                        backoff = min(backoff * 2, 60)
                        continue
                    return None
                else:
                    logger.debug("OSV API HTTP error %d: %s", exc.code, exc.reason)
                    return None

            except urllib.error.URLError as exc:
                logger.debug("OSV API network error: %s", exc)
                return None

            except (TimeoutError, OSError) as exc:
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
                    continue
                logger.debug("OSV API timeout/connection error: %s", exc)
                return None

        return None

    def _make_single_api_request(
        self,
        package: OSVPackage,
        max_retries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Make a single package query to the OSV.dev API.

        Args:
            package: Single OSVPackage object
            max_retries: Maximum retries

        Returns:
            Parsed JSON response or None on failure
        """
        body_dict = {
            "package": {
                "name": package.name,
                "ecosystem": package.ecosystem,
            },
            "version": package.version,
        }
        body = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

        url = OSV_API_BASE + OSV_QUERY_ENDPOINT
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "CodeLens-OSVClient/1.0",
        }

        backoff = 1
        for attempt in range(max_retries + 1):
            self._rate_limiter.acquire()

            try:
                req = urllib.request.Request(url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        return json.loads(resp.read().decode("utf-8"))
                    return None

            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                return None

            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                return None

        return None

    def _fetch_vuln_detail(
        self,
        vuln_id: str,
        max_retries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Fetch full vulnerability details from OSV.dev /v1/vulns/{id}.

        Checks cache first, then fetches from API.

        Args:
            vuln_id: OSV vulnerability ID (e.g., "GHSA-xxxx-xxxx-xxxx")
            max_retries: Maximum retries

        Returns:
            Full vulnerability dict or None on failure
        """
        # Check cache for vuln detail
        cache_key = f"vuln:{vuln_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            self._cache_hit_count += 1
            return cached[0] if isinstance(cached, list) and cached else cached

        if not _HAS_URLLIB:
            return None

        url = OSV_API_BASE + OSV_VULN_ENDPOINT + "/" + urllib.parse.quote(vuln_id, safe="")
        headers = {
            "Accept": "application/json",
            "User-Agent": "CodeLens-OSVClient/1.0",
        }

        backoff = 1
        for attempt in range(max_retries + 1):
            self._rate_limiter.acquire()

            try:
                req = urllib.request.Request(url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        # Cache the full detail
                        self.cache.set(cache_key, data)
                        return data
                    return None

            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                logger.debug("OSV vuln detail fetch failed for %s: HTTP %d", vuln_id, exc.code)
                return None

            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
                    continue
                return None

        return None

    # ─── Response Parsing ────────────────────────────────────────

    def _parse_osv_response(
        self,
        vulns_data: List[Dict[str, Any]],
        package: OSVPackage,
    ) -> List[OSVVulnerability]:
        """Parse OSV API response into OSVVulnerability objects.

        Args:
            vulns_data: List of vulnerability dicts from OSV API
            package: The OSVPackage that was queried

        Returns:
            List of OSVVulnerability objects
        """
        results: List[OSVVulnerability] = []

        if not isinstance(vulns_data, list):
            return results

        for vuln in vulns_data:
            try:
                parsed = self._parse_single_vuln(vuln, package)
                if parsed is not None:
                    results.append(parsed)
            except Exception as exc:
                logger.debug("Failed to parse OSV vulnerability: %s", exc)
                continue

        return results

    def _parse_single_vuln(
        self,
        vuln: Dict[str, Any],
        package: OSVPackage,
    ) -> Optional[OSVVulnerability]:
        """Parse a single OSV vulnerability entry.

        Args:
            vuln: Single vulnerability dict from OSV API
            package: The OSVPackage that was queried

        Returns:
            OSVVulnerability or None if not relevant
        """
        vuln_id = vuln.get("id", "UNKNOWN")
        summary = vuln.get("summary", "")

        # Parse severity from CVSS scores
        cvss_score, cvss_version, severity = self._parse_severity(vuln)

        # Parse affected versions and fixed version
        affected_versions, fixed_version = self._parse_affected(vuln, package)

        # Parse references
        references = []
        for ref in vuln.get("references", []):
            url = ref.get("url", "")
            if url:
                references.append(url)

        # Parse CWE
        cwe = ""
        # Try database_specific for CWE first (most reliable)
        db_specific = vuln.get("database_specific", {})
        if isinstance(db_specific, dict):
            cwe_ids = db_specific.get("cwe_ids", [])
            if cwe_ids and isinstance(cwe_ids, list):
                cwe = cwe_ids[0]  # e.g., "CWE-79"
            elif not cwe_ids:
                cwe_list = db_specific.get("cwes", [])
                if cwe_list:
                    cwe = cwe_list[0] if isinstance(cwe_list[0], str) else ""

        # Fallback: try to extract CWE from CVSS vector string
        if not cwe:
            for sev in vuln.get("severity", []):
                if sev.get("type") in ("CVSS_V3", "CVSS_V2"):
                    score_str = sev.get("score", "")
                    cwe_match = re.search(r'CWE-(\d+)', score_str)
                    if cwe_match:
                        cwe = f"CWE-{cwe_match.group(1)}"
                        break

        return OSVVulnerability(
            id=vuln_id,
            summary=summary or f"Vulnerability {vuln_id}",
            severity=severity,
            cvss_score=cvss_score,
            cvss_version=cvss_version,
            affected_versions=affected_versions,
            fixed_version=fixed_version,
            references=references[:10],
            cwe=cwe,
            ecosystem=package.ecosystem,
            package=package.name,
            installed_version=package.version,
            source="osv_dev",
        )

    def _parse_severity(
        self,
        vuln: Dict[str, Any],
    ) -> Tuple[Optional[float], Optional[str], str]:
        """Parse CVSS severity from OSV vulnerability entry.

        Returns:
            (cvss_score, cvss_version, severity_level)
        """
        cvss_score = None
        cvss_version = None
        severity = "medium"  # Default

        severity_entries = vuln.get("severity", [])
        if not isinstance(severity_entries, list):
            severity_entries = []

        for sev in severity_entries:
            if not isinstance(sev, dict):
                continue

            sev_type = sev.get("type", "")
            score_str = sev.get("score", "")

            if sev_type == "CVSS_V3":
                cvss_version = "3.x"
                # CVSS v3 score can be a number or a vector string
                try:
                    # Try parsing as float first (some APIs return just the score)
                    cvss_score = float(score_str)
                except (ValueError, TypeError):
                    # Try extracting from vector string: "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"
                    # The base score is typically in database_specific
                    cvss_score = self._extract_cvss_score_from_vector(score_str)
                break  # Prefer CVSS v3

            elif sev_type == "CVSS_V2":
                if cvss_score is None:  # Don't override v3
                    cvss_version = "2.0"
                    try:
                        cvss_score = float(score_str)
                    except (ValueError, TypeError):
                        cvss_score = self._extract_cvss_score_from_vector(score_str)

        # If no CVSS score found, try database_specific
        if cvss_score is None:
            db_specific = vuln.get("database_specific", {})
            if isinstance(db_specific, dict):
                severity_str = db_specific.get("severity", "")
                if isinstance(severity_str, str):
                    # GitHub Advisory severity: "CRITICAL", "HIGH", "MODERATE", "LOW"
                    severity = self._map_ghsa_severity(severity_str)

        # Map CVSS score to severity level
        if cvss_score is not None:
            severity = self._cvss_to_severity(cvss_score)

        return cvss_score, cvss_version, severity

    def _extract_cvss_score_from_vector(self, vector: str) -> Optional[float]:
        """Try to extract a CVSS base score from a vector string.

        This is a best-effort heuristic. The actual score depends on the
        full vector calculation, but we can estimate from the exploitability
        and impact metrics.
        """
        # Check if it starts with CVSS:3.x
        if not vector.startswith("CVSS:"):
            return None

        # Parse the vector to estimate severity
        # For CVSS v3: AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H → Critical
        # Simple heuristic: count high-impact metrics
        parts = vector.split("/")
        high_impact = sum(1 for p in parts if p.endswith(":H"))
        if high_impact >= 3:
            return 9.0
        elif high_impact >= 2:
            return 7.5
        elif high_impact >= 1:
            return 5.5
        return 3.0

    def _cvss_to_severity(self, score: float) -> str:
        """Map CVSS score to CodeLens severity level.

        CVSS v3.1 scale:
        - 9.0-10.0: Critical
        - 7.0-8.9:  High
        - 4.0-6.9:  Medium
        - 0.1-3.9:  Low

        CVSS v2 scale:
        - 7.0-10.0: High
        - 4.0-6.9:  Medium
        - 0.1-3.9:  Low
        """
        if score >= 9.0:
            return "critical"
        elif score >= 7.0:
            return "high"
        elif score >= 4.0:
            return "medium"
        else:
            return "low"

    def _map_ghsa_severity(self, severity: str) -> str:
        """Map GitHub Advisory severity to CodeLens severity."""
        mapping = {
            "critical": "critical",
            "high": "high",
            "moderate": "medium",
            "medium": "medium",
            "low": "low",
        }
        return mapping.get(severity.lower(), "medium")

    def _parse_affected(
        self,
        vuln: Dict[str, Any],
        package: OSVPackage,
    ) -> Tuple[str, str]:
        """Parse affected version ranges and fixed versions from OSV vulnerability.

        Args:
            vuln: OSV vulnerability dict
            package: The queried package

        Returns:
            (affected_versions_str, fixed_version_str)
            e.g., ("<4.17.21", "4.17.21")
        """
        affected_entries = vuln.get("affected", [])
        if not isinstance(affected_entries, list):
            return ("unknown", "")

        fixed_versions: List[str] = []
        affected_descriptions: List[str] = []

        for affected in affected_entries:
            if not isinstance(affected, dict):
                continue

            # Check if this affected entry matches our package
            affected_pkg = affected.get("package", {})
            if isinstance(affected_pkg, dict):
                pkg_name = affected_pkg.get("name", "")
                pkg_eco = affected_pkg.get("ecosystem", "")
                if pkg_name and pkg_name.lower() != package.name.lower():
                    continue
                if pkg_eco and pkg_eco != package.ecosystem:
                    continue

            # Parse ranges
            ranges = affected.get("ranges", [])
            if not isinstance(ranges, list):
                ranges = []

            for range_entry in ranges:
                if not isinstance(range_entry, dict):
                    continue

                range_type = range_entry.get("type", "")
                events = range_entry.get("events", [])
                if not isinstance(events, list):
                    continue

                introduced = "0"  # Default: all versions
                fixed = ""

                for event in events:
                    if not isinstance(event, dict):
                        continue

                    if "introduced" in event:
                        introduced = event["introduced"]
                    elif "fixed" in event:
                        fixed = event["fixed"]
                        fixed_versions.append(fixed)
                    elif "last_affected" in event:
                        # last_affected means versions up to and including this are affected
                        pass

                if fixed:
                    affected_descriptions.append(f"<{fixed}")
                elif introduced != "0":
                    affected_descriptions.append(f">={introduced}")

            # Also check version field (explicit list of affected versions)
            versions = affected.get("versions", [])
            if isinstance(versions, list) and versions and not affected_descriptions:
                affected_descriptions.append(f"affected: {', '.join(str(v) for v in versions[:5])}")

        # Compile the results
        affected_str = affected_descriptions[0] if affected_descriptions else "unknown"
        fixed_str = fixed_versions[0] if fixed_versions else ""  # Earliest fix

        return (affected_str, fixed_str)

    def get_cache_info(
        self,
        packages: List[OSVPackage],
    ) -> Dict[str, Any]:
        """Compute OSV cache freshness info for the queried packages.

        Implements the ``cache_info`` block requested in issue #30 so that
        agents consuming ``vuln-scan`` output can decide whether to trust
        the cached CVE data or trigger a refresh.

        The staleness assessment covers only the packages that were
        actually queried in this run — other cache entries (from previous
        scans of different packages) are ignored. A package counts as
        stale if its cache entry is missing OR past the cache's stored
        TTL.

        Args:
            packages: List of OSVPackage objects that were queried in
                this run (typically the result of
                ``OSVQueryBuilder.build_from_workspace``).

        Returns:
            Dict with the following keys:

            - ``last_refresh``: ISO 8601 UTC timestamp (``YYYY-MM-DDTHH:MM:SSZ``)
              of the most recently written cache entry among the queried
              packages, or ``None`` if no entries exist.
            - ``age_hours``: Age in hours of that most-recent entry
              (i.e., how long ago the cache was last refreshed for any
              of the queried packages), or ``None`` if no entries exist.
            - ``ttl_hours``: The cache TTL in hours (from
              ``self.cache.ttl``), rounded to 2 decimals.
            - ``is_stale``: ``True`` if any queried package's cache entry
              is past TTL or missing.
            - ``stale_packages``: List of ``"name@version"`` strings for
              stale or missing packages (sorted for deterministic output).
        """
        now = time.time()
        ttl_seconds = self.cache.ttl
        ttl_hours = round(ttl_seconds / 3600.0, 2)

        latest_timestamp: Optional[float] = None
        stale_packages: List[str] = []

        for pkg in packages:
            if pkg.ecosystem is None:
                continue  # Not supported by OSV — skip staleness check

            cache_key = pkg.cache_key()
            entry = self.cache.peek(cache_key)
            if entry is None:
                # Missing cache entry → treat as stale (needs fetch).
                stale_packages.append(f"{pkg.name}@{pkg.version}")
                continue

            _response, timestamp, _stored_ttl = entry
            if latest_timestamp is None or timestamp > latest_timestamp:
                latest_timestamp = timestamp

            if (now - timestamp) > ttl_seconds:
                stale_packages.append(f"{pkg.name}@{pkg.version}")

        # Deterministic ordering for stable test/output assertions.
        stale_packages.sort()

        if latest_timestamp is not None:
            last_refresh = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(latest_timestamp)
            )
            age_hours = round((now - latest_timestamp) / 3600.0, 2)
        else:
            last_refresh = None
            age_hours = None

        is_stale = bool(stale_packages)

        return {
            "last_refresh": last_refresh,
            "age_hours": age_hours,
            "ttl_hours": ttl_hours,
            "is_stale": is_stale,
            "stale_packages": stale_packages,
        }

    # ─── Statistics ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics including cache stats."""
        cache_stats = self.cache.get_stats()
        return {
            "api_requests": self._request_count,
            "cache_hits": self._cache_hit_count,
            "api_errors": self._api_error_count,
            "offline_mode": self.offline,
            "cache": cache_stats,
        }


# ─── Query Builder ─────────────────────────────────────────────

class OSVQueryBuilder:
    """Build OSV queries from package dependency files.

    Supports:
    - package.json → npm
    - requirements.txt → PyPI
    - Cargo.toml → crates.io
    - go.mod → Go
    - Maven pom.xml → Maven
    - Gemfile → RubyGems
    - pubspec.yaml → Pub
    - mix.exs → Hex
    - .csproj / packages.config → NuGet
    """

    # Reuse the ecosystem mapping from vulnscan_engine
    FILE_TO_ECOSYSTEM = {
        "package.json": "npm",
        "requirements.txt": "pip",
        "Pipfile": "pip",
        "pyproject.toml": "pip",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "pom.xml": "maven",
        "Gemfile": "rubygems",
        "pubspec.yaml": "pub",
        "mix.exs": "hex",
        ".csproj": "nuget",
        "packages.config": "nuget",
    }

    @staticmethod
    def build_from_workspace(workspace: str) -> List[OSVPackage]:
        """Scan workspace for dependency files and build OSV package list.

        Args:
            workspace: Path to workspace root

        Returns:
            List of OSVPackage objects (deduplicated)
        """
        from vulnscan_engine import (
            _discover_dependency_files,
            _parse_package_json,
            _parse_requirements_txt,
            _parse_cargo_toml,
            _parse_go_mod,
            _parse_pipfile,
            _parse_pyproject_toml,
        )

        packages: List[OSVPackage] = []
        seen: Set[Tuple[str, str, str]] = set()

        dep_files = _discover_dependency_files(workspace)

        for ecosystem, files in dep_files.items():
            # Map CodeLens ecosystem to OSV ecosystem
            osv_eco = ECOSYSTEM_MAP.get(ecosystem)
            if osv_eco is None:
                continue  # Not supported by OSV

            # Process manifest files
            for manifest in files.get("manifest", []):
                manifest_path = os.path.join(workspace, manifest)
                if not os.path.exists(manifest_path):
                    continue

                try:
                    with open(manifest_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except IOError:
                    continue

                parsed = OSVQueryBuilder._parse_manifest(content, manifest, ecosystem)
                for name, version in parsed:
                    key = (osv_eco, name.lower(), version)
                    if key not in seen and version and version != "0.0.0" and version != "unknown":
                        seen.add(key)
                        packages.append(OSVPackage(
                            name=name,
                            version=version,
                            ecosystem=osv_eco,
                        ))

            # Process lockfiles
            for lockfile in files.get("lockfile", []):
                lock_path = os.path.join(workspace, lockfile)
                if not os.path.exists(lock_path):
                    continue

                try:
                    with open(lock_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except IOError:
                    continue

                parsed = OSVQueryBuilder._parse_lockfile(content, lockfile, ecosystem)
                for name, version in parsed:
                    key = (osv_eco, name.lower(), version)
                    if key not in seen and version and version != "0.0.0" and version != "unknown":
                        seen.add(key)
                        packages.append(OSVPackage(
                            name=name,
                            version=version,
                            ecosystem=osv_eco,
                        ))

        return packages

    @staticmethod
    def build_from_file(file_path: str) -> List[OSVPackage]:
        """Build OSV package list from a specific dependency file.

        Args:
            file_path: Path to the dependency file

        Returns:
            List of OSVPackage objects
        """
        filename = os.path.basename(file_path)
        ecosystem = OSVQueryBuilder.FILE_TO_ECOSYSTEM.get(filename)
        if ecosystem is None:
            # Try by extension
            if filename.endswith(".csproj"):
                ecosystem = "nuget"
            else:
                return []

        osv_eco = ECOSYSTEM_MAP.get(ecosystem)
        if osv_eco is None:
            return []

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except IOError:
            return []

        parsed = OSVQueryBuilder._parse_manifest(content, filename, ecosystem)
        packages: List[OSVPackage] = []
        seen: Set[Tuple[str, str, str]] = set()

        for name, version in parsed:
            key = (osv_eco, name.lower(), version)
            if key not in seen and version and version != "0.0.0" and version != "unknown":
                seen.add(key)
                packages.append(OSVPackage(
                    name=name,
                    version=version,
                    ecosystem=osv_eco,
                ))

        return packages

    @staticmethod
    def _parse_manifest(
        content: str,
        filename: str,
        ecosystem: str,
    ) -> List[Tuple[str, str]]:
        """Parse a manifest file for package names and versions.

        Delegates to vulnscan_engine parsers where available.
        """
        # Import parsers from vulnscan_engine
        try:
            from vulnscan_engine import (
                _parse_package_json,
                _parse_requirements_txt,
                _parse_cargo_toml,
                _parse_go_mod,
                _parse_pipfile,
                _parse_pyproject_toml,
            )
        except ImportError:
            return []

        if filename == "package.json":
            return _parse_package_json(content)
        elif filename == "requirements.txt":
            return _parse_requirements_txt(content)
        elif filename == "Cargo.toml":
            return _parse_cargo_toml(content)
        elif filename == "go.mod":
            return _parse_go_mod(content)
        elif filename == "Pipfile":
            return _parse_pipfile(content)
        elif filename == "pyproject.toml":
            return _parse_pyproject_toml(content)
        elif filename == "pom.xml":
            return OSVQueryBuilder._parse_pom_xml(content)
        elif filename == "Gemfile":
            return OSVQueryBuilder._parse_gemfile(content)
        elif filename == "pubspec.yaml":
            return OSVQueryBuilder._parse_pubspec(content)
        elif filename == "mix.exs":
            return OSVQueryBuilder._parse_mix_exs(content)
        elif filename.endswith(".csproj") or filename == "packages.config":
            return OSVQueryBuilder._parse_nuget(content, filename)

        return []

    @staticmethod
    def _parse_lockfile(
        content: str,
        filename: str,
        ecosystem: str,
    ) -> List[Tuple[str, str]]:
        """Parse a lockfile for package names and versions."""
        try:
            from vulnscan_engine import (
                _parse_npm_lock,
                _parse_cargo_lock,
                _parse_cargo_lock_toml,
                _parse_poetry_lock,
                _parse_pipfile_lock,
                _parse_go_sum,
                _parse_yarn_lock,
                _parse_bun_lock,
            )
        except ImportError:
            return []

        if ecosystem == "npm":
            if filename.endswith("bun.lock"):
                return _parse_bun_lock(content)
            elif filename.endswith("yarn.lock"):
                return _parse_yarn_lock(content)
            else:
                return _parse_npm_lock(content)
        elif ecosystem == "rust":
            try:
                return _parse_cargo_lock(content)
            except Exception:
                return _parse_cargo_lock_toml(content)
        elif ecosystem == "pip":
            if filename.endswith("poetry.lock"):
                return _parse_poetry_lock(content)
            elif filename.endswith("Pipfile.lock"):
                return _parse_pipfile_lock(content)
        elif ecosystem == "go":
            return _parse_go_sum(content)

        return []

    # ─── Additional Parsers ──────────────────────────────────────

    @staticmethod
    def _parse_pom_xml(content: str) -> List[Tuple[str, str]]:
        """Parse Maven pom.xml for dependency names and versions."""
        packages = []

        # Simple regex-based parsing (not full XML parsing)
        # Match: <groupId>xxx</groupId> <artifactId>yyy</artifactId> <version>zzz</version>
        dep_pattern = re.compile(
            r'<dependency>.*?'
            r'<groupId>([^<]+)</groupId>.*?'
            r'<artifactId>([^<]+)</artifactId>.*?'
            r'<version>([^<]+)</version>.*?'
            r'</dependency>',
            re.DOTALL
        )

        for m in dep_pattern.finditer(content):
            group_id = m.group(1).strip()
            artifact_id = m.group(2).strip()
            version = m.group(3).strip()

            # Skip variable references like ${project.version}
            if version.startswith("$"):
                version = "0.0.0"

            # Maven uses groupId:artifactId as package name
            name = f"{group_id}:{artifact_id}"
            packages.append((name, version))

        return packages

    @staticmethod
    def _parse_gemfile(content: str) -> List[Tuple[str, str]]:
        """Parse Ruby Gemfile for gem names and versions."""
        packages = []

        for line in content.splitlines():
            stripped = line.strip()
            # gem "name", "~> 1.2.3"
            # gem "name", ">= 1.2.3"
            # gem "name", "1.2.3"
            m = re.match(r"gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", stripped)
            if m:
                name = m.group(1)
                version_spec = m.group(2) or ""
                version = re.sub(r'^[~^>=<!]+', '', version_spec).strip()
                if not version:
                    version = "0.0.0"
                packages.append((name, version))

        return packages

    @staticmethod
    def _parse_pubspec(content: str) -> List[Tuple[str, str]]:
        """Parse Dart pubspec.yaml for package names and versions."""
        packages = []
        in_deps = False

        for line in content.splitlines():
            stripped = line.strip()

            if stripped == "dependencies:" or stripped == "dev_dependencies:":
                in_deps = True
                continue
            elif stripped and not stripped.startswith("#") and not stripped.startswith("-") and ":" in stripped and not stripped[0].isspace():
                in_deps = False
                continue

            if not in_deps:
                continue

            # name: ^1.2.3
            m = re.match(r'\s+([A-Za-z0-9_]+):\s*["\']?([^\s"\']+)["\']?', stripped)
            if m:
                name = m.group(1)
                version = re.sub(r'^[~^>=<!]+', '', m.group(2)).strip()
                if not version or version.startswith("git:") or version.startswith("path:"):
                    version = "0.0.0"
                packages.append((name, version))

        return packages

    @staticmethod
    def _parse_mix_exs(content: str) -> List[Tuple[str, str]]:
        """Parse Elixir mix.exs for package names and versions."""
        packages = []

        # Simple regex parsing for deps block
        # {:name, "~> 1.2.3"}
        for m in re.finditer(r':([a-z_][\w]*)\s*,\s*["\']~?>?\s*([0-9][0-9.]*)["\']', content):
            name = m.group(1)
            version = m.group(2)
            packages.append((name, version))

        return packages

    @staticmethod
    def _parse_nuget(content: str, filename: str) -> List[Tuple[str, str]]:
        """Parse .csproj or packages.config for NuGet package names and versions."""
        packages = []

        if filename == "packages.config":
            # <package id="Newtonsoft.Json" version="12.0.3" />
            for m in re.finditer(r'<package\s+id="([^"]+)"\s+version="([^"]+)"', content):
                packages.append((m.group(1), m.group(2)))
        else:
            # .csproj: <PackageReference Include="Newtonsoft.Json" Version="12.0.3" />
            for m in re.finditer(
                r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"',
                content
            ):
                packages.append((m.group(1), m.group(2)))

        return packages


# ─── Convenience Functions ─────────────────────────────────────

def scan_with_osv(
    workspace: str,
    offline: bool = False,
    ttl: int = DEFAULT_TTL,
    severity: Optional[str] = None,
) -> Dict[str, Any]:
    """High-level function to scan workspace for vulnerabilities using OSV.dev.

    This is the main entry point for OSV integration with vulnscan_engine.

    Args:
        workspace: Path to workspace root
        offline: If True, use cache only (no API calls)
        ttl: Cache TTL in seconds
        severity: Optional severity filter

    Returns:
        Dict with findings, stats, and OSV metadata
    """
    workspace = os.path.abspath(workspace)
    client = OSVClient(workspace=workspace, ttl=ttl, offline=offline)

    # Clean up expired cache entries
    client.cache.cleanup()

    # Build package list from workspace
    packages = OSVQueryBuilder.build_from_workspace(workspace)

    if not packages:
        return {
            "status": "ok",
            "osv_findings": [],
            "stats": {
                "packages_queried": 0,
                "vulnerabilities_found": 0,
            },
            "osv_client_stats": client.get_stats(),
        }

    # Query OSV
    vulns = client.query_packages(packages)

    # Convert to finding format
    findings = [v.to_finding() for v in vulns]

    # Apply severity filter
    if severity:
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        threshold = severity_order.get(severity, 99)
        findings = [
            f for f in findings
            if severity_order.get(f.get("severity", "low"), 3) <= threshold
        ]

    # Compute stats
    by_severity: Dict[str, int] = defaultdict(int)
    by_ecosystem: Dict[str, int] = defaultdict(int)
    for f in findings:
        by_severity[f.get("severity", "unknown")] += 1
        by_ecosystem[f.get("ecosystem", "unknown")] += 1

    return {
        "status": "ok",
        "osv_findings": findings,
        "stats": {
            "packages_queried": len(packages),
            "vulnerabilities_found": len(findings),
            "by_severity": dict(by_severity),
            "by_ecosystem": dict(by_ecosystem),
        },
        "osv_client_stats": client.get_stats(),
    }


# ─── CLI Entry Point ───────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python osv_client.py <workspace> [--offline] [--ttl SECONDS]")
        sys.exit(1)

    workspace = sys.argv[1]
    offline = "--offline" in sys.argv
    ttl = DEFAULT_TTL

    for i, arg in enumerate(sys.argv):
        if arg == "--ttl" and i + 1 < len(sys.argv):
            try:
                ttl = int(sys.argv[i + 1])
            except ValueError:
                pass

    print(f"Scanning {workspace} with OSV.dev (offline={offline}, ttl={ttl}s)...")

    result = scan_with_osv(workspace, offline=offline, ttl=ttl)

    print(f"\nPackages queried: {result['stats']['packages_queried']}")
    print(f"Vulnerabilities found: {result['stats']['vulnerabilities_found']}")

    if result['stats'].get('by_severity'):
        print(f"  By severity: {result['stats']['by_severity']}")
    if result['stats'].get('by_ecosystem'):
        print(f"  By ecosystem: {result['stats']['by_ecosystem']}")

    client_stats = result.get('osv_client_stats', {})
    print(f"\nClient stats:")
    print(f"  API requests: {client_stats.get('api_requests', 0)}")
    print(f"  Cache hits: {client_stats.get('cache_hits', 0)}")
    print(f"  API errors: {client_stats.get('api_errors', 0)}")
    cache_stats = client_stats.get('cache', {})
    print(f"  Cache entries: {cache_stats.get('valid_entries', 0)} valid, "
          f"{cache_stats.get('expired_entries', 0)} expired "
          f"({cache_stats.get('db_size_mb', 0)}MB)")

    if result['osv_findings']:
        print(f"\nTop vulnerabilities:")
        for finding in result['osv_findings'][:20]:
            print(f"  [{finding['severity'].upper()}] {finding['package']}@{finding['installed_version']}: "
                  f"{finding['cve']} - {finding['title'][:80]}")
            if finding.get('fix_version'):
                print(f"    Fix: upgrade to {finding['fix_version']}")
