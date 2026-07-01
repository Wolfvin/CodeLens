"""
Tests for the cross-repo intelligence engine (issue #15 MVP).

Verifies that :func:`crossrepo_engine.load_merged_registry` correctly
merges symbol tables from multiple repos and that cross-repo call edges
are resolved and flagged.

Test strategy:
- Create two temp workspaces, each with a ``backend.json`` registry
  containing nodes and raw edges.
- Repo A has a function ``caller_fn`` that calls ``shared_helper``.
- Repo B defines ``shared_helper``.
- After merging, the cross-repo edge from ``caller_fn`` to
  ``shared_helper`` should be resolved (``resolved: True``) and flagged
  with ``cross_repo: True``.
- :func:`query_cross_repo` should find ``shared_helper`` when queried
  from repo A with repo B as an additional path, and the caller list
  should show ``caller_fn`` with ``cross_repo: True``.
"""

import json
import os
import shutil
import sys
import tempfile

import pytest

# Make scripts/ importable
_SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from crossrepo_engine import (
    _parse_additional_paths,
    load_merged_registry,
    query_cross_repo,
)


# ─── Fixtures ─────────────────────────────────────────────────

def _make_backend_json(workspace: str, nodes: list, edges: list) -> None:
    """Write a ``backend.json`` registry into ``workspace/.codelens/``."""
    codelens_dir = os.path.join(workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    data = {
        "last_updated": "2026-07-01T00:00:00Z",
        "workspace": workspace,
        "nodes": nodes,
        "edges": edges,
    }
    with open(os.path.join(codelens_dir, "backend.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _make_node(fn: str, file: str, line: int, repo: str, node_id: str = None) -> dict:
    """Build a minimal backend node dict."""
    if node_id is None:
        node_id = f"{file}:{line}:{fn}"
    return {
        "id": node_id,
        "fn": fn,
        "file": file,
        "line": line,
        "type": "function",
        "status": "active",
        "ref_count": 0,
        "repo": repo,
    }


def _make_raw_edge(from_id: str, to_fn: str) -> dict:
    """Build a minimal raw (unresolved) edge dict."""
    return {
        "from": from_id,
        "to_fn": to_fn,
        "resolved": False,
        "type": "call",
    }


@pytest.fixture
def two_repos():
    """Create two temp workspaces with cross-repo call relationships.

    Repo A (primary):
        - caller_fn in services/api/handler.py calls shared_helper
        - local_fn in services/api/utils.py (no cross-repo calls)

    Repo B (additional):
        - shared_helper in lib/shared/util.py (the cross-repo target)
        - another_helper in lib/shared/util.py (not called from A)
    """
    repo_a = tempfile.mkdtemp(prefix="codelens_xrepo_a_")
    repo_b = tempfile.mkdtemp(prefix="codelens_xrepo_b_")

    # Repo A nodes
    a_nodes = [
        _make_node("caller_fn", "services/api/handler.py", 10, repo_a),
        _make_node("local_fn", "services/api/utils.py", 20, repo_a),
    ]
    # Repo A edges: caller_fn calls shared_helper (cross-repo) + local_fn
    a_edges = [
        _make_raw_edge("services/api/handler.py:10:caller_fn", "shared_helper"),
        _make_raw_edge("services/api/handler.py:10:caller_fn", "local_fn"),
    ]
    _make_backend_json(repo_a, a_nodes, a_edges)

    # Repo B nodes
    b_nodes = [
        _make_node("shared_helper", "lib/shared/util.py", 5, repo_b),
        _make_node("another_helper", "lib/shared/util.py", 15, repo_b),
    ]
    # Repo B edges: shared_helper calls another_helper (intra-repo)
    b_edges = [
        _make_raw_edge("lib/shared/util.py:5:shared_helper", "another_helper"),
    ]
    _make_backend_json(repo_b, b_nodes, b_edges)

    yield repo_a, repo_b

    shutil.rmtree(repo_a, ignore_errors=True)
    shutil.rmtree(repo_b, ignore_errors=True)


@pytest.fixture
def single_repo():
    """A single workspace with a small registry (for non-cross-repo tests)."""
    ws = tempfile.mkdtemp(prefix="codelens_xrepo_single_")
    nodes = [
        _make_node("foo", "main.py", 1, ws),
        _make_node("bar", "main.py", 5, ws),
    ]
    edges = [_make_raw_edge("main.py:1:foo", "bar")]
    _make_backend_json(ws, nodes, edges)
    yield ws
    shutil.rmtree(ws, ignore_errors=True)


# ─── Path parsing tests ───────────────────────────────────────

class TestParseAdditionalPaths:
    """Verify --additional-paths string parsing."""

    def test_none_returns_empty(self):
        assert _parse_additional_paths(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_additional_paths("") == []

    def test_single_path(self):
        result = _parse_additional_paths("/tmp/repo")
        assert result == ["/tmp/repo"]

    def test_multiple_paths_comma_separated(self):
        result = _parse_additional_paths("/tmp/repo1,/tmp/repo2,/tmp/repo3")
        assert result == ["/tmp/repo1", "/tmp/repo2", "/tmp/repo3"]

    def test_whitespace_stripped(self):
        result = _parse_additional_paths("  /tmp/a ,  /tmp/b  ")
        assert result == ["/tmp/a", "/tmp/b"]

    def test_empty_entries_ignored(self):
        result = _parse_additional_paths("/tmp/a,,/tmp/b,")
        assert result == ["/tmp/a", "/tmp/b"]

    def test_relative_paths_made_absolute(self):
        result = _parse_additional_paths("../sibling")
        assert os.path.isabs(result[0])


# ─── Merge tests ──────────────────────────────────────────────

class TestLoadMergedRegistry:
    """Verify multi-repo registry merging."""

    def test_merges_nodes_from_all_repos(self, two_repos):
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        assert merged["stats"]["repos_merged"] == 2
        assert merged["stats"]["total_nodes"] == 4  # 2 from A + 2 from B
        node_fns = {n["fn"] for n in merged["nodes"]}
        assert node_fns == {"caller_fn", "local_fn", "shared_helper", "another_helper"}

    def test_nodes_have_repo_tag(self, two_repos):
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        for node in merged["nodes"]:
            assert "repo" in node
            assert node["repo"] in (repo_a, repo_b)

    def test_cross_repo_edge_resolved(self, two_repos):
        """The edge from caller_fn (repo A) to shared_helper (repo B)
        should be resolved after merging — the resolver finds
        shared_helper in the combined node set."""
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        # Find the cross-repo edge
        cross_edges = [e for e in merged["edges"] if e.get("cross_repo")]
        assert len(cross_edges) == 1, f"Expected 1 cross-repo edge, got {len(cross_edges)}"
        edge = cross_edges[0]
        # The cross_repo flag is only set when BOTH from and to nodes
        # were found in different repos — so its presence proves the
        # edge was resolved. We also check the `to` field points to
        # shared_helper's node_id. (Note: resolve_edges may not carry
        # `resolved` or `to_fn` forward on resolved edges, so we rely
        # on `to` and `cross_repo` instead.)
        assert edge.get("cross_repo") is True
        assert edge.get("target_repo") == repo_b
        assert edge.get("source_repo") == repo_a
        to_id = edge.get("to", "")
        assert "shared_helper" in to_id, (
            f"Expected 'to' to contain 'shared_helper', got: {to_id}"
        )

    def test_intra_repo_edges_not_flagged_cross_repo(self, two_repos):
        """Edges within the same repo should NOT have cross_repo=True."""
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        intra_edges = [e for e in merged["edges"] if not e.get("cross_repo")]
        # caller_fn -> local_fn (intra A) + shared_helper -> another_helper (intra B)
        assert len(intra_edges) >= 2
        for edge in intra_edges:
            assert edge.get("cross_repo") is False

    def test_cross_repo_edge_count(self, two_repos):
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        assert merged["stats"]["cross_repo_edges"] == 1

    def test_no_additional_paths_returns_primary_only(self, single_repo):
        """When additional_paths is empty, merged = primary only."""
        merged = load_merged_registry(single_repo, [])
        assert merged["stats"]["repos_merged"] == 1
        assert merged["stats"]["total_nodes"] == 2
        assert merged["stats"]["cross_repo_edges"] == 0

    def test_missing_primary_returns_empty(self):
        """If the primary workspace has no registry, return empty merge."""
        ws = tempfile.mkdtemp(prefix="codelens_xrepo_empty_")
        try:
            merged = load_merged_registry(ws, [])
            assert merged["stats"]["repos_merged"] == 0
            assert merged["stats"]["total_nodes"] == 0
            assert merged["nodes"] == []
            assert merged["edges"] == []
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_duplicate_primary_in_additional_ignored(self, two_repos):
        """If the primary path is also listed in additional_paths, it
        should not be loaded twice."""
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_a, repo_b])
        # Should still be 2 repos, not 3
        assert merged["stats"]["repos_merged"] == 2
        assert merged["stats"]["total_nodes"] == 4

    def test_unloadable_additional_repo_skipped(self, two_repos):
        """If an additional repo path doesn't exist or has no registry,
        it should be silently skipped."""
        repo_a, repo_b = two_repos
        nonexistent = tempfile.mkdtemp(prefix="codelens_xrepo_nonexist_")
        try:
            merged = load_merged_registry(repo_a, [nonexistent, repo_b])
            # Only repo_a and repo_b contributed nodes
            assert merged["stats"]["repos_merged"] == 2
            assert merged["stats"]["total_nodes"] == 4
        finally:
            shutil.rmtree(nonexistent, ignore_errors=True)

    def test_repos_list_in_result(self, two_repos):
        repo_a, repo_b = two_repos
        merged = load_merged_registry(repo_a, [repo_b])
        assert repo_a in merged["repos"]
        assert repo_b in merged["repos"]


# ─── Query tests ──────────────────────────────────────────────

class TestQueryCrossRepo:
    """Verify multi-repo symbol query."""

    def test_finds_symbol_in_additional_repo(self, two_repos):
        """Querying for shared_helper from repo A (where it's NOT defined)
        should find it in repo B when repo B is an additional path."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("shared_helper", repo_a, [repo_b])
        assert result["status"] == "ok"
        assert result["found"] is True
        assert result["node"]["fn"] == "shared_helper"
        assert result["node"]["repo"] == repo_b

    def test_caller_in_different_repo_flagged(self, two_repos):
        """When querying shared_helper (repo B), the caller caller_fn
        (repo A) should appear in callers with cross_repo=True."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("shared_helper", repo_a, [repo_b])
        assert result["found"] is True
        callers = result.get("callers", [])
        assert len(callers) >= 1
        # Find the cross-repo caller
        cross_callers = [c for c in callers if c.get("cross_repo")]
        assert len(cross_callers) >= 1, (
            f"Expected at least 1 cross-repo caller, got {callers}"
        )
        assert cross_callers[0]["fn"] == "caller_fn"
        assert cross_callers[0]["repo"] == repo_a

    def test_query_local_symbol_still_works(self, two_repos):
        """Querying for a symbol in the primary repo should still work."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("local_fn", repo_a, [repo_b])
        assert result["found"] is True
        assert result["node"]["fn"] == "local_fn"
        assert result["node"]["repo"] == repo_a

    def test_not_found_returns_create_action(self, two_repos):
        """Querying for a non-existent symbol returns CREATE action."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("nonexistent_xyz", repo_a, [repo_b])
        assert result["found"] is False
        assert result["action"] == "CREATE"
        assert result["repos_searched"] == 2

    def test_multi_match_when_same_name_in_both_repos(self, two_repos):
        """If the same function name exists in both repos, return a
        multi_match summary."""
        repo_a, repo_b = two_repos
        # Add a "shared_helper" to repo_a as well
        a_backend = os.path.join(repo_a, ".codelens", "backend.json")
        with open(a_backend) as f:
            data = json.load(f)
        data["nodes"].append(_make_node("shared_helper", "local_copy.py", 1, repo_a))
        with open(a_backend, "w") as f:
            json.dump(data, f)

        result = query_cross_repo("shared_helper", repo_a, [repo_b])
        assert result["found"] is True
        assert result["type"] == "multi_match"
        assert result["match_count"] == 2
        # Each match should have a repo field
        for m in result["matches"]:
            assert "repo" in m

    def test_fuzzy_match_across_repos(self, two_repos):
        """Fuzzy matching should find symbols across repos."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("shared", repo_a, [repo_b], fuzzy=True)
        assert result["found"] is True
        # Should find shared_helper
        if result["type"] == "multi_match":
            fns = [m["fn"] for m in result["matches"]]
            assert "shared_helper" in fns
        else:
            assert result["node"]["fn"] == "shared_helper"

    def test_repos_searched_in_result(self, two_repos):
        repo_a, repo_b = two_repos
        result = query_cross_repo("local_fn", repo_a, [repo_b])
        assert result["repos_searched"] == 2

    def test_cross_repo_search_flag(self, two_repos):
        """cross_repo_search should be True when >1 repos searched."""
        repo_a, repo_b = two_repos
        result = query_cross_repo("local_fn", repo_a, [repo_b])
        assert result["cross_repo_search"] is True

    def test_cross_repo_search_false_for_single_repo(self, single_repo):
        """cross_repo_search should be False when only 1 repo searched."""
        result = query_cross_repo("foo", single_repo, [])
        assert result["cross_repo_search"] is False
        assert result["repos_searched"] == 1


# ─── CLI registration smoke test ──────────────────────────────

class TestCommandIntegration:
    """Verify the --additional-paths flag is wired into the query command."""

    def test_query_command_has_additional_paths_arg(self):
        """The query command should accept --additional-paths."""
        from commands import COMMAND_REGISTRY
        assert "query" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["query"]
        # Build a parser and check the arg is registered
        import argparse
        parser = argparse.ArgumentParser()
        info["add_args"](parser)
        # Parse with --additional-paths
        args = parser.parse_args(["test_fn", "/tmp", "--additional-paths", "/tmp/a,/tmp/b"])
        assert args.additional_paths == "/tmp/a,/tmp/b"

    def test_query_command_without_additional_paths(self):
        """Without --additional-paths, the arg should default to None."""
        from commands import COMMAND_REGISTRY
        info = COMMAND_REGISTRY["query"]
        import argparse
        parser = argparse.ArgumentParser()
        info["add_args"](parser)
        args = parser.parse_args(["test_fn", "/tmp"])
        assert args.additional_paths is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
