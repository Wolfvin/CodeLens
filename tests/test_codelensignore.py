"""Tests for 3-tier .codelensignore support (issue #55).

Verifies:
1. Three-tier loading: workspace > user > builtin (priority order).
2. ``!``-negation works across tiers (workspace can re-include user/builtin ignores).
3. Backward compat with ``DEFAULT_IGNORE_DIRS`` — builtin patterns cover the
   historical hardcoded set, including segment-aware matching that avoids
   false positives like ``test-target`` matching ``target/``.
4. Integration with ``discover_files`` (scan command).
5. ``--suggest-ignore`` flag returns top-N largest non-ignored directories.
6. ``pathspec`` optional dependency: graceful degradation to fnmatch fallback.
"""

import os
import sys
import shutil
import tempfile
import json

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

import codelensignore as ci
from utils import DEFAULT_IGNORE_DIRS


# ─── Helpers ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the module-level matcher cache before every test."""
    ci._CACHE.clear()
    yield
    ci._CACHE.clear()


@pytest.fixture
def user_ignore_file(tmp_path, monkeypatch):
    """Create an isolated user-level ~/.codelensignore in a temp HOME.

    Returns the path to the user ignore file. Tests can write patterns
    to it directly.
    """
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Also patch expanduser for systems where HOME is overridden
    monkeypatch.setattr(os.path, "expanduser", lambda p: (
        str(fake_home) if p == "~" else
        str(fake_home) + p[1:] if p.startswith("~/") else
        p
    ))
    ignore_file = fake_home / ".codelensignore"
    return str(ignore_file)


def _write(path, content):
    """Write *content* to *path*, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ─── 1. Three-tier loading ────────────────────────────────────────


class TestThreeTierLoading:
    """Verify builtin, user, and workspace tiers are all loaded."""

    def test_builtin_patterns_loaded(self):
        """Builtin patterns file should exist and contain expected entries."""
        patterns = ci.builtin_patterns()
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        # Must include the explicitly-required entries from the issue.
        for required in ("node_modules/", ".git/", "__pycache__/",
                         "*.pyc", ".venv/", "venv/", "dist/",
                         "build/", ".codelens/"):
            assert required in patterns, f"Builtin missing required pattern: {required}"

    def test_workspace_patterns_loaded(self, tmp_path):
        """Workspace .codelensignore should be loaded when present."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".codelensignore").write_text("custom_dir/\n*.special\n")

        patterns = ci.workspace_patterns(str(ws))
        assert "custom_dir/" in patterns
        assert "*.special" in patterns

    def test_user_patterns_loaded(self, user_ignore_file):
        """User ~/.codelensignore should be loaded when present."""
        _write(user_ignore_file, "*.user_pattern\n")

        patterns = ci.user_patterns()
        assert "*.user_pattern" in patterns

    def test_load_patterns_merges_all_tiers(self, tmp_path, user_ignore_file):
        """load_patterns should merge builtin + user + workspace patterns."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".codelensignore").write_text("workspace_pattern/\n")
        _write(user_ignore_file, "user_pattern/\n")

        merged = ci.load_patterns(str(ws))
        # All three tiers should be represented
        assert "node_modules/" in merged  # builtin
        assert "user_pattern/" in merged   # user
        assert "workspace_pattern/" in merged  # workspace

    def test_workspace_overrides_user(self, tmp_path, user_ignore_file):
        """Workspace patterns can RE-include paths ignored by user tier.

        ``!``-negation in the workspace file should override a positive
        pattern in the user file.
        """
        ws = tmp_path / "ws"
        ws.mkdir()
        # User tier: ignore all *.test.py files
        _write(user_ignore_file, "*.test.py\n")
        # Workspace tier: re-include important.test.py
        (ws / ".codelensignore").write_text("!important.test.py\n")

        # regular test file ignored by user pattern
        assert ci.is_ignored("app.test.py", str(ws)) is True
        # workspace negation re-includes important.test.py
        assert ci.is_ignored("important.test.py", str(ws)) is False

    def test_workspace_overrides_builtin(self, tmp_path):
        """Workspace ``!``-negation can re-include builtin-ignored paths."""
        ws = tmp_path / "ws"
        ws.mkdir()
        # Builtin has node_modules/ — workspace re-includes a specific path
        (ws / ".codelensignore").write_text("!node_modules/keep_me/\n")

        assert ci.is_ignored("node_modules/skip/file.js", str(ws)) is True
        assert ci.is_ignored("node_modules/keep_me/file.js", str(ws)) is False

    def test_user_overrides_builtin(self, user_ignore_file, tmp_path):
        """User tier takes priority over builtin."""
        ws = tmp_path / "ws"
        ws.mkdir()
        # Builtin has *.pyc — user re-includes important.pyc
        _write(user_ignore_file, "!important.pyc\n")

        assert ci.is_ignored("app.pyc", str(ws)) is True  # builtin
        assert ci.is_ignored("important.pyc", str(ws)) is False  # user negation


# ─── 2. Negation ──────────────────────────────────────────────────


class TestNegation:
    """Verify ``!``-prefix negation semantics across single and multiple tiers."""

    def test_negation_within_single_file(self, tmp_path):
        """``!``-negation within a single workspace file overrides earlier patterns."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".codelensignore").write_text(
            "*.log\n!important.log\n"
        )
        assert ci.is_ignored("debug.log", str(ws)) is True
        assert ci.is_ignored("important.log", str(ws)) is False

    def test_negation_resurrects_subdir(self, tmp_path):
        """A negated subdirectory of an ignored directory is re-included."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".codelensignore").write_text(
            "build/\n!build/keep/\n"
        )
        assert ci.is_ignored("build/output.exe", str(ws)) is True
        assert ci.is_ignored("build/keep/important.txt", str(ws)) is False

    def test_negation_does_not_affect_unrelated_paths(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".codelensignore").write_text(
            "*.log\n!important.log\n"
        )
        assert ci.is_ignored("src/app.py", str(ws)) is False
        assert ci.is_ignored("README.md", str(ws)) is False

    def test_negation_in_workspace_overrides_user_positive(self, tmp_path, user_ignore_file):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write(user_ignore_file, "secrets/\n")
        (ws / ".codelensignore").write_text("!secrets/public/\n")

        assert ci.is_ignored("secrets/private.key", str(ws)) is True
        assert ci.is_ignored("secrets/public/notice.txt", str(ws)) is False


# ─── 3. Backward compat with DEFAULT_IGNORE_DIRS ──────────────────


class TestBackwardCompat:
    """Builtin patterns must cover the historical DEFAULT_IGNORE_DIRS set,
    and segment-aware matching must avoid false positives (issue #55 constraint).
    """

    @pytest.mark.parametrize("dirname", sorted(DEFAULT_IGNORE_DIRS))
    def test_builtin_covers_default_ignore_dirs(self, dirname):
        """Every entry in DEFAULT_IGNORE_DIRS should be ignored by builtin."""
        patterns = ci.builtin_patterns()
        # Either dir/ or just dir is in the patterns.
        assert f"{dirname}/" in patterns or dirname in patterns, (
            f"DEFAULT_IGNORE_DIRS entry {dirname!r} not covered by builtin patterns"
        )

    @pytest.mark.parametrize("dirname", sorted(DEFAULT_IGNORE_DIRS))
    def test_default_dir_is_ignored(self, dirname, tmp_path):
        """Sanity: each default-ignored dir name actually gets ignored."""
        # Skip 'bin' here — pathspec's gitignore doesn't recognize bare
        # 'bin/' as a top-level dir unless anchored, but builtin patterns
        # still match it as a path segment. We verify with a sub-path.
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored(f"{dirname}/file.txt", str(ws)) is True, (
            f"Expected {dirname}/file.txt to be ignored by builtin patterns"
        )

    def test_segment_aware_no_false_positive_test_target(self, tmp_path):
        """``target/`` should NOT match ``test-target/`` (path-segment-aware)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored("test-target/src/app.py", str(ws)) is False
        assert ci.is_ignored("test-target", str(ws)) is False

    def test_segment_aware_no_false_positive_dist_app(self, tmp_path):
        """``dist/`` should NOT match ``dist-app/``."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored("dist-app/components/Button.tsx", str(ws)) is False

    def test_segment_aware_no_false_positive_build_tools(self, tmp_path):
        """``build/`` should NOT match ``build-tools/``."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored("build-tools/config/webpack.js", str(ws)) is False

    def test_actual_target_dir_is_ignored(self, tmp_path):
        """An actual ``target/`` directory SHOULD be ignored."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored("target/debug/binary.o", str(ws)) is True
        assert ci.is_ignored("src/target/debug/binary.o", str(ws)) is True

    def test_pyc_files_ignored(self, tmp_path):
        """``*.pyc`` builtin pattern should match .pyc files anywhere."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored("app.pyc", str(ws)) is True
        assert ci.is_ignored("src/__pycache__/app.cpython-310.pyc", str(ws)) is True

    def test_codelens_dir_ignored(self, tmp_path):
        """``.codelens/`` should be ignored (it's CodeLens's own output dir)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ci.is_ignored(".codelens/codelens.db", str(ws)) is True
        assert ci.is_ignored(".codelens", str(ws)) is True


# ─── 4. Integration with discover_files ───────────────────────────


class TestDiscoverFilesIntegration:
    """Verify that discover_files() respects the 3-tier .codelensignore system."""

    def _make_workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        # Source files
        src = ws / "src"
        src.mkdir()
        (src / "app.py").write_text("print('hi')\n")
        # node_modules — ignored by builtin
        nm = ws / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = 1;\n")
        # custom_ignore — to be ignored by workspace .codelensignore
        ci_dir = ws / "custom_ignore"
        ci_dir.mkdir()
        (ci_dir / "data.py").write_text("x = 1\n")
        return ws

    def _save_config(self, ws):
        from registry import save_config
        config = {
            "frontend_paths": [], "backend_paths": [], "watch": False,
            "ignore": ["node_modules/", "dist/", ".git/", "build/",
                       "target/", "__pycache__/"],
            "frameworks": [], "jsx_mode": False, "vue_mode": False,
            "svelte_mode": False, "tailwind_mode": False,
        }
        save_config(str(ws), config)
        return config

    def test_workspace_codelensignore_filters_dir(self, tmp_path):
        """discover_files should skip a dir listed in .codelensignore."""
        from commands.scan import discover_files

        ws = self._make_workspace(tmp_path)
        (ws / ".codelensignore").write_text("custom_ignore/\n")
        config = self._save_config(ws)

        files = discover_files(str(ws), config)
        python_files = [os.path.basename(f) for f in files["python"]]
        assert "app.py" in python_files
        assert "data.py" not in python_files

    def test_builtin_patterns_filter_node_modules(self, tmp_path):
        """discover_files should skip node_modules via builtin patterns."""
        from commands.scan import discover_files

        ws = self._make_workspace(tmp_path)
        config = self._save_config(ws)

        files = discover_files(str(ws), config)
        # node_modules index.js should NOT appear in js_backend
        js_files = [os.path.basename(f) for f in files["js_backend"]]
        assert "index.js" not in js_files

    def test_negation_reincludes_in_discover(self, tmp_path):
        """A ``!``-negation in .codelensignore should let a previously-ignored
        file be discovered."""
        from commands.scan import discover_files

        ws = tmp_path / "ws"
        ws.mkdir()
        # Create a .pyc file — ignored by builtin *.pyc
        (ws / "app.pyc").write_text("garbage")
        # Workspace: re-include app.pyc (overriding builtin *.pyc)
        (ws / ".codelensignore").write_text("!app.pyc\n")
        config = self._save_config(ws)

        # Note: discover_files only categorizes known source extensions,
        # so .pyc won't show up in any list. Instead, verify via is_ignored.
        assert ci.is_ignored("app.pyc", str(ws)) is False

    def test_default_behavior_preserved_without_codelensignore(self, tmp_path):
        """Without any workspace .codelensignore, builtin patterns still apply."""
        from commands.scan import discover_files

        ws = self._make_workspace(tmp_path)
        config = self._save_config(ws)

        files = discover_files(str(ws), config)
        # node_modules should still be filtered out by builtin
        js_files = [os.path.basename(f) for f in files["js_backend"]]
        assert "index.js" not in js_files
        # custom_ignore has no .codelensignore to filter it — its data.py
        # SHOULD be discovered (since the test config doesn't include it).
        python_files = [os.path.basename(f) for f in files["python"]]
        assert "data.py" in python_files


# ─── 5. --suggest-ignore flag ─────────────────────────────────────


class TestSuggestIgnore:
    """Verify ``scan --suggest-ignore`` returns top-N largest non-ignored dirs."""

    def _make_workspace(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        # Small dir
        (ws / "small_dir").mkdir()
        (ws / "small_dir" / "file.txt").write_text("x" * 100)
        # Large dir
        (ws / "large_dir").mkdir()
        (ws / "large_dir" / "big.bin").write_text("y" * 10000)
        # node_modules — ignored by builtin, should NOT appear
        (ws / "node_modules" / "pkg").mkdir(parents=True)
        (ws / "node_modules" / "pkg" / "index.js").write_text("z" * 50000)
        return ws

    def test_suggest_returns_top_dirs_by_size(self, tmp_path):
        ws = self._make_workspace(tmp_path)
        result = ci.suggest_ignore_directories(str(ws), top_n=10)
        assert result[0]["path"] == "large_dir"
        assert result[0]["size_bytes"] == 10000
        assert "size_human" in result[0]
        assert "file_count" in result[0]

    def test_suggest_excludes_ignored_dirs(self, tmp_path):
        """Directories matched by builtin patterns should NOT appear."""
        ws = self._make_workspace(tmp_path)
        result = ci.suggest_ignore_directories(str(ws), top_n=10)
        paths = [r["path"] for r in result]
        assert "node_modules" not in paths
        assert "node_modules/pkg" not in paths

    def test_suggest_excludes_workspace_ignored(self, tmp_path):
        """Workspace .codelensignore entries should also be excluded."""
        ws = self._make_workspace(tmp_path)
        (ws / ".codelensignore").write_text("large_dir/\n")
        result = ci.suggest_ignore_directories(str(ws), top_n=10)
        paths = [r["path"] for r in result]
        assert "large_dir" not in paths

    def test_suggest_respects_top_n(self, tmp_path):
        ws = self._make_workspace(tmp_path)
        result = ci.suggest_ignore_directories(str(ws), top_n=1)
        assert len(result) <= 1
        assert result[0]["path"] == "large_dir"

    def test_scan_command_execute_suggest_ignore(self, tmp_path):
        """The scan command's execute() should short-circuit for --suggest-ignore."""
        from commands.scan import execute

        ws = self._make_workspace(tmp_path)

        class Args:
            suggest_ignore = True
            incremental = False
            plugins = None
            max_files = None

        result = execute(Args(), str(ws))
        assert result["status"] == "ok"
        assert result["command"] == "scan --suggest-ignore"
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)


# ─── 6. pathspec fallback ─────────────────────────────────────────


class TestPathspecFallback:
    """Verify graceful degradation when pathspec is not installed.

    We monkeypatch HAS_PATHSPEC to False and force the fnmatch-based matcher.
    """

    def test_fnmatch_fallback_basic_ignore(self, tmp_path, monkeypatch):
        """fnmatch matcher should respect positive patterns."""
        monkeypatch.setattr(ci, "_HAS_PATHSPEC", False)
        ci._CACHE.clear()
        try:
            ws = tmp_path / "ws"
            ws.mkdir()
            (ws / ".codelensignore").write_text("custom_dir/\n*.log\n")

            assert ci.is_ignored("custom_dir/file.txt", str(ws)) is True
            assert ci.is_ignored("debug.log", str(ws)) is True
            assert ci.is_ignored("src/app.py", str(ws)) is False
        finally:
            # Restore real pathspec state
            monkeypatch.undo()
            ci._CACHE.clear()

    def test_fnmatch_fallback_negation(self, tmp_path, monkeypatch):
        """fnmatch matcher should respect ``!``-negation (last match wins)."""
        monkeypatch.setattr(ci, "_HAS_PATHSPEC", False)
        ci._CACHE.clear()
        try:
            ws = tmp_path / "ws"
            ws.mkdir()
            (ws / ".codelensignore").write_text("*.log\n!important.log\n")

            assert ci.is_ignored("debug.log", str(ws)) is True
            assert ci.is_ignored("important.log", str(ws)) is False
        finally:
            monkeypatch.undo()
            ci._CACHE.clear()

    def test_fnmatch_fallback_builtin_patterns(self, tmp_path, monkeypatch):
        """fnmatch matcher should respect builtin patterns."""
        monkeypatch.setattr(ci, "_HAS_PATHSPEC", False)
        ci._CACHE.clear()
        try:
            ws = tmp_path / "ws"
            ws.mkdir()
            # Builtin patterns: node_modules/, *.pyc, etc.
            assert ci.is_ignored("node_modules/pkg/index.js", str(ws)) is True
            assert ci.is_ignored("app.pyc", str(ws)) is True
            assert ci.is_ignored("src/app.py", str(ws)) is False
        finally:
            monkeypatch.undo()
            ci._CACHE.clear()
