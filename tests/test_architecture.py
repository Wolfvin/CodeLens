"""
Tests for the `architecture` command + engine (issue #19).

Verifies:
1. `architecture` command returns status ok on the clean_app fixture.
2. Full payload has all required fields (languages, frameworks,
   entry_points, packages, routes, hotspots, total_symbols, adrs).
3. `--lite` mode omits routes / packages / hotspots.
4. Hotspots are sorted by dependent count descending and use the graph model.
5. Cache is created on first call and reused on second call (cached flag set).
6. Cache is invalidated after a re-scan (db mtime newer than cache mtime).
7. MCP tool `codelens_architecture` appears in tools/list and returns full
   architecture data via the stats field (preserved by _normalize_to_ai).
8. `--lite` payload stays under ~1k tokens (~4000 bytes JSON).
"""

import json
import os
import shutil
import sys
import tempfile
import time

import pytest

# Add scripts directory to path (matches other test files)
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "benchmarks", "fixtures", "clean_app",
)


# ─── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def scanned_clean_app():
    """Copy clean_app fixture to a temp workspace and run a full scan.

    Yields the workspace path. The scan populates .codelens/codelens.db
    (including graph_nodes + graph_edges), summary.json, and backend.json.
    Cleanup removes the temp workspace on teardown.
    """
    if not os.path.isdir(FIXTURE_DIR):
        pytest.skip("clean_app fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_arch_test_")
    for entry in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    from commands.scan import cmd_scan
    cmd_scan(workspace, incremental=False)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def fresh_clean_app():
    """Copy clean_app fixture to a temp workspace WITHOUT scanning.

    Used to verify the architecture command auto-scans when no .codelens/
    directory exists yet. Yields the workspace path.
    """
    if not os.path.isdir(FIXTURE_DIR):
        pytest.skip("clean_app fixture not available")
    workspace = tempfile.mkdtemp(prefix="codelens_arch_fresh_")
    for entry in os.listdir(FIXTURE_DIR):
        src = os.path.join(FIXTURE_DIR, entry)
        dst = os.path.join(workspace, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)

    yield workspace

    shutil.rmtree(workspace, ignore_errors=True)


# ─── 1. Command returns status ok ────────────────────────────


class TestArchitectureBasic:
    """Verify the architecture command runs and returns a valid payload."""

    def test_returns_ok_status(self, scanned_clean_app):
        """architecture must return status=ok on a scanned clean_app."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        assert isinstance(result, dict)
        assert result.get("status") == "ok", (
            f"expected status ok, got: {result.get('status')!r}"
        )
        assert result.get("workspace") == os.path.abspath(scanned_clean_app)

    def test_auto_scans_on_fresh_workspace(self, fresh_clean_app):
        """architecture on a workspace with no .codelens/ must auto-scan."""
        from architecture_engine import get_architecture

        # Sanity: no .codelens/ before the call
        assert not os.path.isdir(os.path.join(fresh_clean_app, ".codelens"))

        result = get_architecture(fresh_clean_app, lite=True)
        assert result.get("status") == "ok"
        # Auto-scan must have populated the db + graph tables
        db_path = os.path.join(fresh_clean_app, ".codelens", "codelens.db")
        assert os.path.isfile(db_path)
        stats = result.get("stats", {})
        assert stats.get("total_symbols", 0) > 0, (
            "auto-scan should populate graph nodes so total_symbols > 0"
        )


# ─── 2. Required fields ──────────────────────────────────────


class TestArchitectureFields:
    """Verify the full payload has all required fields from issue #19."""

    REQUIRED_FIELDS = (
        "languages", "frameworks", "entry_points",
        "packages", "routes", "hotspots",
        "total_symbols", "adrs",
    )

    def test_payload_has_all_required_fields(self, scanned_clean_app):
        """Full payload must contain every field listed in issue #19 inside stats."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        stats = result["stats"]
        for field in self.REQUIRED_FIELDS:
            assert field in stats, (
                f"missing required field {field!r} in stats"
            )

    def test_languages_is_dict_of_counts(self, scanned_clean_app):
        """languages must be a dict mapping language name to file count."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        languages = result["stats"]["languages"]
        assert isinstance(languages, dict)
        # clean_app fixture has .py files, so python must be present
        assert "python" in languages, (
            f"expected 'python' in languages, got: {list(languages.keys())}"
        )
        assert languages["python"] > 0
        # All values must be positive ints
        for lang, count in languages.items():
            assert isinstance(count, int)
            assert count > 0

    def test_frameworks_is_list(self, scanned_clean_app):
        """frameworks must be a list (possibly empty)."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        frameworks = result["stats"]["frameworks"]
        assert isinstance(frameworks, list)

    def test_entry_points_is_list_of_paths(self, scanned_clean_app):
        """entry_points must be a list of file path strings."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        entry_points = result["stats"]["entry_points"]
        assert isinstance(entry_points, list)
        # clean_app has main.py with `if __name__ == "__main__": main()`
        assert len(entry_points) > 0, "expected at least one entry point"
        for ep in entry_points:
            assert isinstance(ep, str)
            assert ep, "entry point path must not be empty"

    def test_packages_is_list(self, scanned_clean_app):
        """packages must be a list of relative dir paths."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        packages = result["stats"]["packages"]
        assert isinstance(packages, list)
        # clean_app has src/ + config/ as top-level dirs with source code.
        # The src/ dir's direct children are files (db_queries.py, etc), not
        # subdirs, so config/ should be detected as a package.
        for pkg in packages:
            assert isinstance(pkg, str)

    def test_routes_is_list_of_dicts(self, scanned_clean_app):
        """routes must be a list of {method, path, handler} dicts."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        routes = result["stats"]["routes"]
        assert isinstance(routes, list)
        for route in routes:
            assert isinstance(route, dict)
            assert "method" in route
            assert "path" in route
            assert "handler" in route

    def test_hotspots_is_list_of_strings(self, scanned_clean_app):
        """hotspots must be a list of human-readable strings."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        hotspots = result["stats"]["hotspots"]
        assert isinstance(hotspots, list)
        for hs in hotspots:
            assert isinstance(hs, str)
            # Each hotspot string should include a dependent count
            assert "dependents" in hs, (
                f"hotspot string should mention 'dependents': {hs!r}"
            )

    def test_total_symbols_is_int(self, scanned_clean_app):
        """total_symbols must be a non-negative int from graph_stats().nodes."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        total = result["stats"]["total_symbols"]
        assert isinstance(total, int)
        # clean_app fixture has ~31 backend nodes (verified in test_graph_model)
        assert total > 0, f"expected total_symbols > 0, got {total}"

    def test_adrs_is_empty_list_placeholder(self, scanned_clean_app):
        """adrs must be an empty list (ADR feature is issue #16, Phase 3)."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        assert result["stats"]["adrs"] == []


# ─── 3. Lite mode ────────────────────────────────────────────


class TestArchitectureLiteMode:
    """Verify --lite mode omits routes/packages/hotspots."""

    def test_lite_omits_routes_packages_hotspots(self, scanned_clean_app):
        """--lite payload must NOT contain routes, packages, or hotspots."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=True)
        assert result.get("lite") is True
        stats = result["stats"]
        for omitted in ("routes", "packages", "hotspots"):
            assert omitted not in stats, (
                f"--lite must omit {omitted!r}, but it's present in stats"
            )

    def test_lite_keeps_core_fields(self, scanned_clean_app):
        """--lite payload must keep languages, frameworks, entry_points, total_symbols."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=True)
        stats = result["stats"]
        for kept in ("languages", "frameworks", "entry_points", "total_symbols"):
            assert kept in stats, (
                f"--lite must keep {kept!r}, but it's missing from stats"
            )


# ─── 4. Hotspots use the graph model and are sorted ─────────


class TestArchitectureHotspots:
    """Verify hotspots come from the graph model and are sorted desc."""

    def test_hotspots_sorted_by_dependents_desc(self, scanned_clean_app):
        """Hotspots must be sorted by dependent count, descending."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        hotspots = result["stats"]["hotspots"]
        if len(hotspots) < 2:
            pytest.skip("need >=2 hotspots to verify sort order")

        # Extract the dependent count from each "file (N dependents)" string.
        counts = []
        for hs in hotspots:
            # Parse "src/foo.py (47 dependents)" -> 47
            try:
                n_str = hs.split("(")[-1].split(" ")[0]
                counts.append(int(n_str))
            except (IndexError, ValueError):
                pytest.fail(f"could not parse dependent count from: {hs!r}")

        assert counts == sorted(counts, reverse=True), (
            f"hotspots not sorted desc: {counts}"
        )

    def test_hotspots_match_graph_query(self, scanned_clean_app):
        """Hotspots must match a direct SQL query against graph_edges."""
        import sqlite3
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        hotspots = result["stats"]["hotspots"]

        db_path = os.path.join(scanned_clean_app, ".codelens", "codelens.db")
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT gn.file, COUNT(*) AS cnt "
                "FROM graph_edges AS ge "
                "INNER JOIN graph_nodes AS gn ON gn.node_id = ge.target_id "
                "WHERE ge.target_id IS NOT NULL AND ge.target_id != '' "
                "  AND gn.file IS NOT NULL AND gn.file != '' "
                "GROUP BY gn.file "
                "ORDER BY cnt DESC "
                "LIMIT 5",
            ).fetchall()
        finally:
            conn.close()

        # The hotspot strings should reference the same files as the SQL query
        sql_files = [r[0] for r in rows if r[0]]
        hotspot_files = [hs.rsplit(" (", 1)[0] for hs in hotspots]
        # The set of files in hotspots should match the set from the SQL
        # query (order may differ if counts are tied, but the sets must match)
        assert set(hotspot_files) == set(sql_files), (
            f"hotspot files {set(hotspot_files)} != sql files {set(sql_files)}"
        )

    def test_hotspots_are_distinct_files(self, scanned_clean_app):
        """Each hotspot must be a distinct file (no duplicates)."""
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=False)
        hotspots = result["stats"]["hotspots"]
        if not hotspots:
            pytest.skip("no hotspots to verify")
        files = [hs.rsplit(" (", 1)[0] for hs in hotspots]
        assert len(files) == len(set(files)), (
            f"hotspot files must be distinct, got duplicates: {files}"
        )


# ─── 5. Caching ─────────────────────────────────────────────


class TestArchitectureCaching:
    """Verify the architecture cache is created, reused, and invalidated."""

    def test_cache_file_created_on_first_call(self, scanned_clean_app):
        """First call must write .codelens/architecture_cache.json."""
        from architecture_engine import get_architecture

        cache_path = os.path.join(
            scanned_clean_app, ".codelens", "architecture_cache.json"
        )
        assert not os.path.isfile(cache_path), "cache should not exist yet"

        get_architecture(scanned_clean_app, lite=False)
        assert os.path.isfile(cache_path), "cache file must be created"

    def test_cache_reused_on_second_call(self, scanned_clean_app):
        """Second call must return the cached payload (cached=True)."""
        from architecture_engine import get_architecture

        # First call builds and caches
        first = get_architecture(scanned_clean_app, lite=False)
        assert first.get("cached") is False

        # Touch the cache file to set a known mtime, then verify second call
        # returns the cached version
        cache_path = os.path.join(
            scanned_clean_app, ".codelens", "architecture_cache.json"
        )
        first_cache_mtime = os.path.getmtime(cache_path)

        second = get_architecture(scanned_clean_app, lite=False)
        assert second.get("cached") is True, (
            "second call must return cached payload"
        )
        # The cache file must not have been rewritten
        second_cache_mtime = os.path.getmtime(cache_path)
        assert second_cache_mtime == first_cache_mtime, (
            "cache file must not be rewritten when reusing"
        )

    def test_cache_invalidated_after_rescan(self, scanned_clean_app):
        """Re-running scan must invalidate the cache (cached=False on next call)."""
        from architecture_engine import get_architecture
        from commands.scan import cmd_scan

        # First call builds and caches
        first = get_architecture(scanned_clean_app, lite=False)
        assert first.get("cached") is False

        # Wait briefly so the re-scan db mtime is strictly newer than the
        # cache file mtime (mtime resolution can be 1s on some filesystems).
        time.sleep(1.1)

        # Re-scan — this touches codelens.db (newer mtime than cache)
        cmd_scan(scanned_clean_app, incremental=False)

        # Next architecture call must rebuild (cached=False)
        rebuilt = get_architecture(scanned_clean_app, lite=False)
        assert rebuilt.get("cached") is False, (
            "cache must be invalidated after re-scan"
        )

    def test_lite_and_full_caches_not_shared(self, scanned_clean_app):
        """Requesting --lite after --full (or vice versa) must rebuild.

        Lite and full payloads have different shapes — the cache must not
        serve the wrong shape even if the db mtime is unchanged.
        """
        from architecture_engine import get_architecture

        full = get_architecture(scanned_clean_app, lite=False)
        assert full.get("cached") is False
        assert "routes" in full["stats"]

        lite = get_architecture(scanned_clean_app, lite=True)
        # Even though the db hasn't changed, the cached payload is the wrong
        # shape (full vs lite), so the engine must rebuild.
        assert lite.get("cached") is False, (
            "lite must not be served from a full-mode cache"
        )
        assert "routes" not in lite["stats"]


# ─── 6. MCP tool appears in tools/list ───────────────────────


class TestArchitectureMCPTool:
    """Verify codelens_architecture is registered as an MCP tool."""

    def test_mcp_tool_listed(self):
        """tools/list must include codelens_architecture."""
        # Import the MCP server module to access _TOOL_DEFINITIONS
        import mcp_server

        assert "architecture" in mcp_server._TOOL_DEFINITIONS, (
            "architecture must be in _TOOL_DEFINITIONS"
        )

        tool_def = mcp_server._TOOL_DEFINITIONS["architecture"]
        assert "description" in tool_def
        assert "parameters" in tool_def

        params = tool_def["parameters"]
        assert params.get("type") == "object"
        assert "workspace" in params.get("properties", {})
        assert "workspace" in params.get("required", [])
        # lite flag must be exposed
        assert "lite" in params.get("properties", {})

    def test_mcp_tool_returns_full_architecture_via_stats(self, scanned_clean_app):
        """codelens_architecture tool call must return stats with architecture data.

        The MCP normalizer (_normalize_to_ai) preserves the `stats` dict
        as-is, so the architecture data nested inside `stats` must survive
        the normalization and reach the agent.
        """
        from mcp_server import MCPServer

        srv = MCPServer()
        call_result = srv._handle_tools_call({
            "name": "codelens_architecture",
            "arguments": {"workspace": scanned_clean_app, "lite": False},
        })
        assert call_result.get("isError") is False
        text = call_result["content"][0]["text"]
        data = json.loads(text)
        assert data.get("status") == "ok"
        assert data.get("command") == "architecture"

        # The stats dict must contain the architecture-specific fields.
        stats = data.get("stats", {})
        for field in ("languages", "frameworks", "entry_points",
                      "packages", "routes", "hotspots",
                      "total_symbols", "adrs"):
            assert field in stats, (
                f"MCP tool must return {field!r} inside stats; got: "
                f"{list(stats.keys())}"
            )

        # Sanity: total_symbols must be > 0 (graph is populated)
        assert stats.get("total_symbols", 0) > 0


# ─── 7. Lite payload stays under ~1k tokens ─────────────────


class TestArchitectureTokenBudget:
    """Verify --lite output stays under the ~1k token target (~4000 bytes)."""

    def test_lite_payload_under_4000_bytes(self, scanned_clean_app):
        """--lite JSON byte length must stay under 4000 (~1k tokens).

        1 token ~= 4 bytes for English text + JSON syntax, so 4000 bytes is
        a generous upper bound for the 1k-token target.
        """
        from architecture_engine import get_architecture

        result = get_architecture(scanned_clean_app, lite=True)
        payload_json = json.dumps(result, ensure_ascii=False, default=str)
        byte_len = len(payload_json.encode("utf-8"))
        assert byte_len < 4000, (
            f"--lite payload is {byte_len} bytes, exceeds 4000-byte budget "
            f"(~1k tokens). Payload: {payload_json[:300]}..."
        )

    def test_lite_mcp_response_under_4000_bytes(self, scanned_clean_app):
        """--lite MCP tool response must stay under 4000 bytes after normalization."""
        from mcp_server import MCPServer

        srv = MCPServer()
        call_result = srv._handle_tools_call({
            "name": "codelens_architecture",
            "arguments": {"workspace": scanned_clean_app, "lite": True},
        })
        text = call_result["content"][0]["text"]
        byte_len = len(text.encode("utf-8"))
        assert byte_len < 4000, (
            f"--lite MCP response is {byte_len} bytes, exceeds 4000-byte "
            f"budget (~1k tokens). Response: {text[:300]}..."
        )
