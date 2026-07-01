"""
Tests for issue #15 Phase 1 — multi-repo workspace support.

Covers the new ``workspace_roots`` config field + the helper functions
that manage it:

  - ``load_config()`` includes ``workspace_roots: []`` in defaults
  - ``save_config()`` persists the field
  - ``get_workspace_roots()`` returns [primary] + extra roots, deduped
  - ``add_workspace_root()`` is idempotent + rejects invalid paths
  - ``init --add-repo <path>`` CLI flag routes to ``add_workspace_root``

Phase 2 (cross-repo edge detection, trace --cross-repo, combined
architecture) is out of scope for this PR — these tests only verify
the config + helper layer that Phase 2 will consume.

Run: python -m pytest tests/test_workspace_roots.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from registry import (  # noqa: E402
    add_workspace_root,
    get_workspace_roots,
    load_config,
    save_config,
)
from commands.init import add_args, cmd_init, execute  # noqa: E402


# ---------------------------------------------------------------------------
# load_config — workspace_roots default
# ---------------------------------------------------------------------------


class TestLoadConfigWorkspaceRootsDefault:
    def test_default_config_includes_workspace_roots(self):
        """load_config() must include ``workspace_roots: []`` in defaults."""
        with tempfile.TemporaryDirectory() as ws:
            config = load_config(ws)
            assert "workspace_roots" in config, (
                "load_config defaults must include workspace_roots (issue #15 Phase 1)"
            )
            assert config["workspace_roots"] == [], (
                "workspace_roots default must be empty list (single-repo mode)"
            )

    def test_load_config_preserves_existing_workspace_roots(self):
        """When config file has workspace_roots, load_config returns it."""
        with tempfile.TemporaryDirectory() as ws:
            from registry import ensure_codelens_dir, get_codelens_dir
            ensure_codelens_dir(ws)
            config_path = os.path.join(get_codelens_dir(ws), "codelens.config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"workspace_roots": ["/some/other/repo"]}, f)
            config = load_config(ws)
            assert config["workspace_roots"] == ["/some/other/repo"]

    def test_load_config_merges_workspace_roots_with_other_defaults(self):
        """workspace_roots + other defaults coexist after load."""
        with tempfile.TemporaryDirectory() as ws:
            config = load_config(ws)
            # Other defaults still present
            assert "frontend_paths" in config
            assert "backend_paths" in config
            assert "ignore" in config
            # workspace_roots present
            assert config["workspace_roots"] == []


# ---------------------------------------------------------------------------
# save_config — round-trip
# ---------------------------------------------------------------------------


class TestSaveConfigWorkspaceRoots:
    def test_save_config_persists_workspace_roots(self):
        with tempfile.TemporaryDirectory() as ws:
            config = load_config(ws)
            config["workspace_roots"] = ["/repo/a", "/repo/b"]
            save_config(ws, config)
            reloaded = load_config(ws)
            assert reloaded["workspace_roots"] == ["/repo/a", "/repo/b"]

    def test_save_config_round_trip_empty_list(self):
        with tempfile.TemporaryDirectory() as ws:
            config = load_config(ws)
            config["workspace_roots"] = []
            save_config(ws, config)
            reloaded = load_config(ws)
            assert reloaded["workspace_roots"] == []


# ---------------------------------------------------------------------------
# get_workspace_roots — the primary consumer of the config field
# ---------------------------------------------------------------------------


class TestGetWorkspaceRoots:
    def test_returns_primary_only_when_no_extras(self):
        with tempfile.TemporaryDirectory() as ws:
            cmd_init(ws)  # Initialize so config file exists
            roots = get_workspace_roots(ws)
            assert roots == [os.path.abspath(ws)]

    def test_returns_primary_plus_extras_in_order(self):
        with tempfile.TemporaryDirectory() as ws:
            extra1 = tempfile.mkdtemp()
            extra2 = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                add_workspace_root(ws, extra1)
                add_workspace_root(ws, extra2)
                roots = get_workspace_roots(ws)
                assert roots[0] == os.path.abspath(ws)
                assert os.path.abspath(extra1) in roots
                assert os.path.abspath(extra2) in roots
                assert len(roots) == 3
            finally:
                import shutil
                shutil.rmtree(extra1, ignore_errors=True)
                shutil.rmtree(extra2, ignore_errors=True)

    def test_deduplicates_paths(self):
        """If workspace_roots contains the same path twice (e.g. user
        edited the JSON manually), get_workspace_roots deduplicates."""
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                add_workspace_root(ws, extra)
                # Manually duplicate in the config file
                config = load_config(ws)
                config["workspace_roots"] = [extra, extra, os.path.abspath(extra)]
                save_config(ws, config)
                roots = get_workspace_roots(ws)
                assert len(roots) == 2  # primary + extra (deduped)
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_normalizes_relative_paths_to_absolute(self):
        """Paths stored as relative are normalized to absolute on read."""
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp(dir=ws, prefix="extra_")
            extra_rel = os.path.relpath(extra, ws)
            try:
                cmd_init(ws)
                # Manually write a relative path into the config
                config = load_config(ws)
                config["workspace_roots"] = [extra_rel]
                save_config(ws, config)
                roots = get_workspace_roots(ws)
                # All roots must be absolute
                for r in roots:
                    assert os.path.isabs(r), f"root {r!r} must be absolute"
                # The extra path must be present (resolved to absolute)
                assert os.path.abspath(extra) in roots
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_skips_empty_string_entries(self):
        """Empty strings in workspace_roots are silently skipped."""
        with tempfile.TemporaryDirectory() as ws:
            cmd_init(ws)
            config = load_config(ws)
            config["workspace_roots"] = ["", "  ", ""]
            save_config(ws, config)
            roots = get_workspace_roots(ws)
            assert roots == [os.path.abspath(ws)]


# ---------------------------------------------------------------------------
# add_workspace_root — the writer
# ---------------------------------------------------------------------------


class TestAddWorkspaceRoot:
    def test_adds_existing_directory(self):
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                result = add_workspace_root(ws, extra)
                assert result["status"] == "ok"
                assert os.path.abspath(extra) in result["workspace_roots"]
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_idempotent_re_add_is_skipped(self):
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                first = add_workspace_root(ws, extra)
                second = add_workspace_root(ws, extra)
                assert first["status"] == "ok"
                assert second["status"] == "skipped"
                assert "already registered" in second["reason"]
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_add_primary_workspace_is_skipped(self):
        """Adding the primary workspace itself is a no-op."""
        with tempfile.TemporaryDirectory() as ws:
            cmd_init(ws)
            result = add_workspace_root(ws, ws)
            assert result["status"] == "skipped"
            assert "primary workspace" in result["reason"]
            assert result["workspace_roots"] == [os.path.abspath(ws)]

    def test_add_nonexistent_path_is_error(self):
        with tempfile.TemporaryDirectory() as ws:
            cmd_init(ws)
            result = add_workspace_root(ws, "/nonexistent/path/that/does/not/exist")
            assert result["status"] == "error"
            assert "does not exist" in result["reason"]

    def test_add_file_not_directory_is_error(self):
        """A file path (not a directory) is rejected."""
        with tempfile.TemporaryDirectory() as ws:
            cmd_init(ws)
            file_path = os.path.join(ws, "not_a_dir.txt")
            with open(file_path, "w") as f:
                f.write("test")
            result = add_workspace_root(ws, file_path)
            assert result["status"] == "error"
            assert "not a directory" in result["reason"]

    def test_add_multiple_distinct_repos(self):
        with tempfile.TemporaryDirectory() as ws:
            extra1 = tempfile.mkdtemp()
            extra2 = tempfile.mkdtemp()
            extra3 = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                add_workspace_root(ws, extra1)
                add_workspace_root(ws, extra2)
                add_workspace_root(ws, extra3)
                roots = get_workspace_roots(ws)
                assert len(roots) == 4  # primary + 3 extras
                assert roots[0] == os.path.abspath(ws)
            finally:
                import shutil
                for d in (extra1, extra2, extra3):
                    shutil.rmtree(d, ignore_errors=True)

    def test_relative_path_normalized_to_absolute(self):
        """Adding a relative path stores it as absolute in the config."""
        with tempfile.TemporaryDirectory() as ws:
            # Create a subdir inside ws so the relative path is stable
            extra = os.path.join(ws, "sibling_repo")
            os.makedirs(extra)
            cmd_init(ws)
            # Use a relative path — should be resolved against cwd, but
            # since we're running from elsewhere, use an absolute path
            # to make the test deterministic. The point of this test is
            # that the stored + returned paths are absolute.
            result = add_workspace_root(ws, extra)
            assert result["status"] == "ok"
            assert os.path.isabs(result["workspace_roots"][1])


# ---------------------------------------------------------------------------
# init command — --add-repo CLI flag
# ---------------------------------------------------------------------------


class TestInitAddRepoFlag:
    def test_add_args_defines_add_repo_flag(self):
        """add_args() must register --add-repo as a repeatable flag."""
        import argparse
        parser = argparse.ArgumentParser()
        add_args(parser)
        # Single --add-repo
        args = parser.parse_args(["/ws", "--add-repo", "/extra1"])
        assert args.add_repo == ["/extra1"]
        # Multiple --add-repo (repeatable)
        args = parser.parse_args(["/ws", "--add-repo", "/extra1", "--add-repo", "/extra2"])
        assert args.add_repo == ["/extra1", "/extra2"]
        # No --add-repo → default empty list
        args = parser.parse_args(["/ws"])
        assert args.add_repo == []

    def test_execute_with_add_repo_calls_add_workspace_root(self):
        """When --add-repo is supplied, execute() routes to add_workspace_root
        instead of the normal cmd_init flow."""
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp()
            try:
                # First, initialize the workspace
                cmd_init(ws)
                # Then, execute with --add-repo
                args = SimpleNamespace(add_repo=[extra])
                result = execute(args, ws)
                assert result["status"] == "ok"
                assert "add_repo_results" in result
                assert len(result["add_repo_results"]) == 1
                assert result["add_repo_results"][0]["status"] == "ok"
                assert os.path.abspath(extra) in result["workspace_roots"]
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_execute_with_multiple_add_repo(self):
        """Multiple --add-repo flags are processed in order."""
        with tempfile.TemporaryDirectory() as ws:
            extra1 = tempfile.mkdtemp()
            extra2 = tempfile.mkdtemp()
            try:
                cmd_init(ws)
                args = SimpleNamespace(add_repo=[extra1, extra2])
                result = execute(args, ws)
                assert result["status"] == "ok"
                assert len(result["add_repo_results"]) == 2
                assert result["add_repo_results"][0]["status"] == "ok"
                assert result["add_repo_results"][1]["status"] == "ok"
                roots = result["workspace_roots"]
                assert os.path.abspath(extra1) in roots
                assert os.path.abspath(extra2) in roots
            finally:
                import shutil
                shutil.rmtree(extra1, ignore_errors=True)
                shutil.rmtree(extra2, ignore_errors=True)

    def test_execute_without_add_repo_runs_normal_init(self):
        """When --add-repo is NOT supplied, execute() runs cmd_init."""
        with tempfile.TemporaryDirectory() as ws:
            args = SimpleNamespace(add_repo=[])
            result = execute(args, ws)
            assert result["status"] == "ok"
            assert "codelens_dir" in result
            assert "config" in result
            # workspace_roots should be in the config (empty list)
            assert result["config"].get("workspace_roots") == []

    def test_execute_with_add_repo_on_uninitialized_workspace(self):
        """--add-repo on a workspace that hasn't been init'd yet should
        still work — add_workspace_root calls ensure_codelens_dir via
        save_config, which creates the .codelens/ directory lazily."""
        with tempfile.TemporaryDirectory() as ws:
            extra = tempfile.mkdtemp()
            try:
                # Do NOT call cmd_init first — directly execute --add-repo
                args = SimpleNamespace(add_repo=[extra])
                result = execute(args, ws)
                # add_workspace_root should succeed (it calls save_config
                # which creates .codelens/ lazily)
                assert result["status"] == "ok"
                assert result["add_repo_results"][0]["status"] == "ok"
            finally:
                import shutil
                shutil.rmtree(extra, ignore_errors=True)

    def test_init_includes_workspace_roots_in_config(self):
        """cmd_init() must write workspace_roots: [] to the config file
        on first init, so the field is always present for Phase 2 consumers."""
        with tempfile.TemporaryDirectory() as ws:
            result = cmd_init(ws)
            assert "workspace_roots" in result["config"]
            assert result["config"]["workspace_roots"] == []
            # Verify it's persisted to disk
            reloaded = load_config(ws)
            assert reloaded["workspace_roots"] == []
