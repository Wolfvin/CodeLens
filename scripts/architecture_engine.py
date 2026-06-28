"""
Architecture Engine — single-call codebase overview for AI agents (issue #19).

When an agent lands on an unfamiliar codebase it normally has to chain 4-6
commands (scan -> list -> detect -> entrypoints -> api-map -> read entry files)
just to figure out what it is looking at. That orientation phase burns 10-20k
tokens before any real work starts.

This engine orchestrates the existing engines (framework_detect, entrypoints,
apimap, graph_model) plus a lightweight top-level package scan into a single
compact summary so the agent can orient in one call:

    {
        "languages":     {"python": 342, "typescript": 89},
        "frameworks":    ["fastapi", "react"],
        "entry_points":  ["src/main.py", "src/server.ts"],
        "packages":      ["src/api", "src/models", "src/services"],
        "routes":        [{"method": "GET", "path": "/users", "handler": "get_users"}],
        "hotspots":      ["src/models/user.py (47 dependents)"],
        "total_symbols": 1842,
        "adrs":          []
    }

The `--lite` flag omits routes / packages / hotspots to keep the payload under
~1k tokens for the cheapest possible orientation call.

Caching: the first call writes `.codelens/architecture_cache.json` with a
timestamp. Subsequent calls return the cached payload as long as
`.codelens/codelens.db` hasn't been touched since (i.e. scan hasn't been
re-run). This makes repeated orientation calls instant.
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Constants ────────────────────────────────────────────────

# Source-file extensions used to decide whether a top-level directory counts
# as a "package" (contains real source code, not just assets/docs).
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".rs", ".go", ".java", ".kt", ".rb", ".php",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hxx",
    ".vue", ".svelte", ".swift", ".scala", ".dart",
    ".ex", ".exs", ".lua", ".cs", ".zig",
}

# Directories whose direct children represent logical packages / modules.
_PACKAGE_ROOT_DIRS = ("src", "app", "lib", "packages", "server", "internal")

# Limits to keep the JSON payload small (issue target: <1k tokens in --lite).
_MAX_ENTRY_POINTS = 10
_MAX_PACKAGES = 20
_MAX_ROUTES = 20
_MAX_HOTSPOTS = 5

# Map scan result `files_scanned` keys to canonical language names used in
# the architecture payload. Multiple scan buckets may collapse into one
# language (e.g. js_backend + js_frontend + mjs/cjs all become "javascript").
_SCAN_BUCKET_TO_LANGUAGE: Dict[str, str] = {
    "python": "python",
    "js_frontend": "javascript",
    "js_backend": "javascript",
    "tsx": "typescript",
    "rust": "rust",
    "vue": "vue",
    "svelte": "svelte",
    "java": "java",
    "kotlin": "kotlin",
    "c_cpp": "c_cpp",
    "go": "go",
    "lua": "lua",
    "csharp": "csharp",
    "php": "php",
    "blade": "blade",
    "ruby": "ruby",
    "elixir": "elixir",
    "dart": "dart",
    "swift": "swift",
    "scala": "scala",
    "shell": "shell",
    "gdscript": "gdscript",
    "objc": "objective_c",
    "html": "html",
    "css": "css",
}

# Map file extension to canonical language name for the cheap stat-only
# fallback walk (used when neither scan_result nor summary.json is available).
_EXT_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin", ".kts": "kotlin",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".hpp": "cpp", ".hxx": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".vue": "vue",
    ".svelte": "svelte",
    ".swift": "swift",
    ".scala": "scala", ".sc": "scala",
    ".dart": "dart",
    ".ex": "elixir", ".exs": "elixir",
    ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".less": "css", ".sass": "css",
    ".zig": "zig",
}


# ─── Public API ───────────────────────────────────────────────

def get_architecture(workspace: str, lite: bool = False) -> Dict[str, Any]:
    """Build (or return cached) single-call codebase overview.

    Orchestrates framework_detect, entrypoints_engine, apimap_engine, and the
    graph_model hotspots query into one compact payload. The first call writes
    `.codelens/architecture_cache.json`; subsequent calls return the cache as
    long as `.codelens/codelens.db` hasn't been modified (i.e. the scan hasn't
    been re-run).

    The architecture-specific fields (languages, frameworks, entry_points,
    packages, routes, hotspots, total_symbols, adrs) are nested inside a
    `stats` dict. This is intentional: the MCP `_normalize_to_ai` formatter
    preserves `stats` as-is, so the `codelens_architecture` MCP tool returns
    the full architecture data to agents. CLI consumers get the same shape.

    Args:
        workspace: Path to the workspace root. Auto-init + auto-scan runs if
            `.codelens/codelens.db` doesn't exist yet so the first call works
            on a totally unfamiliar codebase.
        lite: When True, omit routes / packages / hotspots to keep the output
            under ~1k tokens for cheap orientation.

    Returns:
        Dict with keys: status, workspace, lite, cached, generated_at, stats.
        The `stats` sub-dict holds: languages, frameworks, entry_points,
        total_symbols, adrs (always); packages, routes, hotspots (only when
        lite=False).
    """
    workspace = os.path.abspath(workspace)
    codelens_dir = os.path.join(workspace, ".codelens")
    db_path = os.path.join(codelens_dir, "codelens.db")
    cache_path = os.path.join(codelens_dir, "architecture_cache.json")

    # Auto-scan if the graph database doesn't exist or is empty. This makes
    # `architecture` self-sufficient on a fresh codebase (issue #19 spec:
    # "single-call codebase overview").
    scan_result: Optional[Dict[str, Any]] = None
    if not _graph_is_populated(db_path):
        try:
            from commands.scan import cmd_scan
            scan_result = cmd_scan(workspace, incremental=False)
        except Exception:
            logger.warning("architecture: auto-scan failed", exc_info=True)

    # Cache lookup — return immediately if scan hasn't been re-run since the
    # last architecture build.
    cached = _load_cache_if_fresh(cache_path, db_path, lite)
    if cached is not None:
        return cached

    payload = _build_architecture(workspace, db_path, lite, scan_result)
    _save_cache(cache_path, payload)
    return payload


# ─── Build Pipeline ───────────────────────────────────────────

def _build_architecture(
    workspace: str,
    db_path: str,
    lite: bool,
    scan_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run every sub-engine and assemble the architecture payload.

    The architecture-specific fields (languages, frameworks, entry_points,
    packages, routes, hotspots, total_symbols, adrs) are nested inside a
    `stats` dict so they survive the MCP normalizer (`_normalize_to_ai`
    preserves `stats` as-is). This way the MCP `codelens_architecture` tool
    returns the full architecture data to agents, not just an empty
    `{stats:{}, items:[]}` shell.

    Args:
        workspace: Absolute workspace path.
        db_path: Absolute path to .codelens/codelens.db (may not exist).
        lite: When True, omit routes / packages / hotspots.
        scan_result: Optional scan result dict (from a fresh auto-scan) used
            to derive language counts without re-walking files. None when the
            scan was done in a prior call.

    Returns:
        The full architecture dict (not yet cached).
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    languages = _compute_languages(workspace, scan_result)
    frameworks = _compute_frameworks(workspace)
    entry_points = _compute_entry_points(workspace)
    total_symbols = _compute_total_symbols(db_path)

    # Stats holds all architecture-specific fields. The MCP normalizer
    # preserves `stats` as-is so agents get the full payload via MCP.
    stats: Dict[str, Any] = {
        "languages": languages,
        "frameworks": frameworks,
        "entry_points": entry_points,
        "total_symbols": total_symbols,
        "adrs": [],  # placeholder — ADR feature is issue #16 (Phase 3)
    }

    if not lite:
        stats["packages"] = _compute_packages(workspace)
        stats["routes"] = _compute_routes(workspace)
        stats["hotspots"] = _compute_hotspots(db_path)

    payload: Dict[str, Any] = {
        "status": "ok",
        "workspace": workspace,
        "lite": lite,
        "cached": False,
        "generated_at": generated_at,
        "stats": stats,
    }

    return payload


def _compute_languages(
    workspace: str,
    scan_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    """Return a {language_name: file_count} dict.

    Three-tier resolution (avoids re-walking files when possible):
      1. If `scan_result` is provided (fresh auto-scan), use its
         `files_scanned` bucket counts — collapsed to canonical language
         names (e.g. js_backend + js_frontend -> javascript).
      2. Else if `.codelens/summary.json` exists (written when scan is invoked
         via the CLI dispatcher), use its `files_by_language` field.
      3. Else, fall back to a cheap stat-only extension-counting walk — no
         file parsing, just `os.walk` + `os.path.splitext`.

    Args:
        workspace: Absolute workspace path.
        scan_result: Optional scan result dict from a fresh auto-scan.

    Returns:
        Dict mapping language name to source file count, sorted by count
        descending then name ascending. Empty dict if no source files found.
    """
    # Tier 1: fresh scan_result captured by caller.
    if scan_result and isinstance(scan_result, dict):
        files_scanned = scan_result.get("files_scanned", {})
        if isinstance(files_scanned, dict) and files_scanned:
            collapsed: Dict[str, int] = {}
            for bucket, count in files_scanned.items():
                if not count:
                    continue
                lang = _SCAN_BUCKET_TO_LANGUAGE.get(str(bucket), str(bucket))
                collapsed[lang] = collapsed.get(lang, 0) + int(count)
            if collapsed:
                return dict(
                    sorted(collapsed.items(), key=lambda kv: (-kv[1], kv[0]))
                )

    # Tier 2: summary.json written by CLI dispatcher.
    summary_path = os.path.join(workspace, ".codelens", "summary.json")
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            files_by_lang = data.get("files_by_language", {})
            if isinstance(files_by_lang, dict) and files_by_lang:
                cleaned = {
                    str(k): int(v) for k, v in files_by_lang.items() if v
                }
                if cleaned:
                    return dict(
                        sorted(cleaned.items(), key=lambda kv: (-kv[1], kv[0]))
                    )
        except (json.JSONDecodeError, OSError):
            pass

    # Tier 3: cheap stat-only extension-counting fallback.
    return _count_files_by_extension(workspace)


def _count_files_by_extension(workspace: str) -> Dict[str, int]:
    """Cheap stat-only walk counting source files per language.

    Used as a last-resort fallback when neither scan_result nor summary.json
    is available. Does NOT parse files — just walks directories and inspects
    file extensions, so it's fast even on large workspaces.

    Args:
        workspace: Absolute workspace path.

    Returns:
        Dict mapping language name to source file count, sorted by count
        descending then name ascending.
    """
    counts: Dict[str, int] = {}
    for root, dirs, files in os.walk(workspace):
        # Prune ignored + dot directories in-place (os.walk lets us mutate
        # dirs to skip them on the next iteration).
        dirs[:] = [
            d for d in dirs
            if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")
        ]
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            lang = _EXT_TO_LANGUAGE.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return {}
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _compute_frameworks(workspace: str) -> List[str]:
    """Return detected framework names from framework_detect.

    Args:
        workspace: Absolute workspace path.

    Returns:
        Sorted list of detected framework name strings (e.g.
        ["fastapi", "react"]). Empty list on failure.
    """
    try:
        from framework_detect import detect_frameworks
        result = detect_frameworks(workspace)
        frameworks = result.get("frameworks", [])
        if isinstance(frameworks, list):
            return sorted({str(fw) for fw in frameworks if fw})
    except Exception:
        logger.debug("architecture: framework_detect failed", exc_info=True)
    return []


def _compute_entry_points(workspace: str) -> List[str]:
    """Return up to _MAX_ENTRY_POINTS unique entry-point file paths.

    Uses `entrypoints_engine.map_entrypoints` and extracts the unique
    `file` field from each entrypoint dict. The most "important" entry
    point types (main, http_handler, cli_command) are prioritised so
    test_entry noise doesn't crowd them out.

    Args:
        workspace: Absolute workspace path.

    Returns:
        List of relative file paths (deduplicated, ordered by importance).
    """
    try:
        from entrypoints_engine import map_entrypoints
        result = map_entrypoints(workspace, exclude_tests=True)
    except Exception:
        logger.debug("architecture: entrypoints engine failed", exc_info=True)
        return []

    entrypoints = result.get("entrypoints", [])
    if not isinstance(entrypoints, list):
        return []

    # Priority order — main/handlers/cli first, then everything else.
    type_priority = {"main": 0, "http_handler": 1, "cli_command": 2,
                     "worker": 3, "cron_job": 4, "event_handler": 5,
                     "module_export": 6, "test_entry": 7}
    ordered = sorted(
        entrypoints,
        key=lambda e: (type_priority.get(e.get("type", ""), 99),
                       str(e.get("file", ""))),
    )

    seen = set()
    paths: List[str] = []
    for ep in ordered:
        f = ep.get("file")
        if not f or f in seen:
            continue
        seen.add(f)
        paths.append(f)
        if len(paths) >= _MAX_ENTRY_POINTS:
            break
    return paths


def _compute_packages(workspace: str) -> List[str]:
    """Return up to _MAX_PACKAGES top-level package directories.

    Scans `src/`, `app/`, `lib/`, `packages/`, `server/`, `internal/` (the
    conventional package roots) and lists immediate subdirectories that
    contain at least one source file. This is a shallow, fast scan — it
    doesn't recurse into nested subdirectories.

    Args:
        workspace: Absolute workspace path.

    Returns:
        Sorted list of relative paths like "src/api", "src/models".
    """
    packages: List[str] = []
    for root_name in _PACKAGE_ROOT_DIRS:
        root_dir = os.path.join(workspace, root_name)
        if not os.path.isdir(root_dir):
            continue
        try:
            children = sorted(os.listdir(root_dir))
        except OSError:
            continue
        for child in children:
            if child in DEFAULT_IGNORE_DIRS or child.startswith("."):
                continue
            child_path = os.path.join(root_dir, child)
            if not os.path.isdir(child_path):
                continue
            if _dir_contains_source(child_path):
                rel = os.path.relpath(child_path, workspace)
                packages.append(rel.replace(os.sep, "/"))
                if len(packages) >= _MAX_PACKAGES:
                    return sorted(packages)
    return sorted(packages)


def _dir_contains_source(dir_path: str) -> bool:
    """Return True if dir_path (or any immediate child file) has source code.

    One level of recursion is allowed so packages organised as
    `pkg/__init__.py` or `pkg/sub/module.py` are still detected. Nested
    directories beyond depth 2 are not inspected to keep this fast.

    Args:
        dir_path: Absolute directory path.

    Returns:
        True if any source file exists at depth 1 or 2 under dir_path.
    """
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return False
    for name in entries:
        if name in DEFAULT_IGNORE_DIRS or name.startswith("."):
            continue
        full = os.path.join(dir_path, name)
        if os.path.isfile(full):
            _, ext = os.path.splitext(name)
            if ext.lower() in _SOURCE_EXTENSIONS:
                return True
        elif os.path.isdir(full):
            # Recurse one level — packages are usually flat two-tier trees.
            try:
                for sub_name in os.listdir(full):
                    if sub_name in DEFAULT_IGNORE_DIRS or sub_name.startswith("."):
                        continue
                    sub_full = os.path.join(full, sub_name)
                    if os.path.isfile(sub_full):
                        _, ext = os.path.splitext(sub_name)
                        if ext.lower() in _SOURCE_EXTENSIONS:
                            return True
            except OSError:
                continue
    return False


def _compute_routes(workspace: str) -> List[Dict[str, str]]:
    """Return up to _MAX_ROUTES routes from the API map engine.

    Each route is normalised to `{method, path, handler}` to keep the JSON
    payload compact. The `handler` field falls back to `handler_name` then
    `""` depending on which extractor produced the route.

    Args:
        workspace: Absolute workspace path.

    Returns:
        List of `{method, path, handler}` dicts. Empty list on failure.
    """
    try:
        from apimap_engine import map_api_routes
        result = map_api_routes(workspace, production_only=True)
    except Exception:
        logger.debug("architecture: apimap engine failed", exc_info=True)
        return []

    routes = result.get("routes", [])
    if not isinstance(routes, list):
        return []

    out: List[Dict[str, str]] = []
    for r in routes[:_MAX_ROUTES]:
        if not isinstance(r, dict):
            continue
        method = str(r.get("method", "") or "")
        path = str(r.get("path", "") or "")
        handler = r.get("handler_name") or r.get("handler") or ""
        out.append({"method": method, "path": path, "handler": str(handler)})
    return out


def _compute_hotspots(db_path: str) -> List[str]:
    """Return up to _MAX_HOTSPOTS files ranked by incoming CALLS edge count.

    Queries `graph_edges` joined to `graph_nodes` and groups by file path so
    each hotspot is a distinct file (not a per-symbol row). Files with the
    most incoming CALLS edges across all their symbols are surfaced first —
    these are the "depended-upon" files where changes have the biggest blast
    radius.

    Args:
        db_path: Absolute path to .codelens/codelens.db.

    Returns:
        List of human-readable strings like "src/models/user.py (47 dependents)".
        Empty list if the db/tables don't exist or are empty.
    """
    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        # Group by file (not target_id) so each hotspot is a distinct file —
        # one file may host many symbols, each with its own incoming edges,
        # and we want the file's total blast radius.
        rows = conn.execute(
            "SELECT gn.file, COUNT(*) AS cnt "
            "FROM graph_edges AS ge "
            "INNER JOIN graph_nodes AS gn ON gn.node_id = ge.target_id "
            "WHERE ge.target_id IS NOT NULL AND ge.target_id != '' "
            "  AND gn.file IS NOT NULL AND gn.file != '' "
            "GROUP BY gn.file "
            "ORDER BY cnt DESC "
            "LIMIT ?",
            (_MAX_HOTSPOTS,),
        ).fetchall()
    except sqlite3.Error as e:
        logger.debug(f"architecture: hotspots query failed: {e}")
        return []
    finally:
        conn.close()

    hotspots: List[str] = []
    for file_path, count in rows:
        if not file_path:
            continue
        hotspots.append(f"{file_path} ({count} dependents)")
    return hotspots


def _compute_total_symbols(db_path: str) -> int:
    """Return total symbol count from graph_stats().nodes.

    Args:
        db_path: Absolute path to .codelens/codelens.db.

    Returns:
        Node count (0 if db/tables don't exist).
    """
    try:
        from graph_model import graph_stats
        return int(graph_stats(db_path).get("nodes", 0))
    except Exception:
        return 0


# ─── Cache Layer ──────────────────────────────────────────────

def _graph_is_populated(db_path: str) -> bool:
    """Return True if the graph database exists and has at least one node.

    Args:
        db_path: Absolute path to .codelens/codelens.db.

    Returns:
        True if the graph is ready to query; False if scan needs to run first.
    """
    if not os.path.isfile(db_path):
        return False
    try:
        from graph_model import graph_tables_populated
        return graph_tables_populated(db_path)
    except Exception:
        return False


def _load_cache_if_fresh(
    cache_path: str, db_path: str, lite: bool,
) -> Optional[Dict[str, Any]]:
    """Load cached architecture if it's fresher than the database.

    The cache is invalidated whenever `.codelens/codelens.db` mtime is newer
    than the cache mtime (i.e. scan has been re-run since the cache was
    written). Also returns None if the cached payload's `lite` flag doesn't
    match the requested mode (lite vs full are different shapes).

    Args:
        cache_path: Path to .codelens/architecture_cache.json.
        db_path: Path to .codelens/codelens.db.
        lite: Whether the caller wants the lite payload.

    Returns:
        Cached architecture dict with `cached: True`, or None if the cache
        is missing/stale/wrong-shape.
    """
    if not os.path.isfile(cache_path):
        return None
    try:
        cache_mtime = os.path.getmtime(cache_path)
    except OSError:
        return None
    # If the db has been touched after the cache was written, the cache is
    # stale (scan re-ran). If the db doesn't exist (very weird state — scan
    # failed mid-build), fall through and rebuild.
    if os.path.isfile(db_path):
        try:
            db_mtime = os.path.getmtime(db_path)
        except OSError:
            return None
        if db_mtime > cache_mtime:
            return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(cached, dict):
        return None
    if cached.get("status") != "ok":
        return None
    if bool(cached.get("lite", False)) != bool(lite):
        # Lite and full payloads have different shapes — don't return the
        # wrong one; rebuild instead.
        return None
    cached["cached"] = True
    return cached


def _save_cache(cache_path: str, payload: Dict[str, Any]) -> None:
    """Write the architecture payload to disk for future fast lookups.

    Best-effort: failures are logged but don't fail the call (the payload is
    still returned to the caller).

    Args:
        cache_path: Path to .codelens/architecture_cache.json.
        payload: Architecture dict to cache (will be marked cached=False on
                 disk so a later load sets cached=True itself).
    """
    cache_dir = os.path.dirname(cache_path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        # The on-disk copy says cached=False; the in-memory caller copy
        # already says cached=False too. When _load_cache_if_fresh reads it
        # back, it flips cached=True so callers can tell which path served
        # the request.
        to_write = dict(payload)
        to_write["cached"] = False
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(to_write, f, ensure_ascii=False, default=str)
    except OSError:
        logger.debug("architecture: failed to write cache", exc_info=True)
