"""
Tests for path-segment-aware ignore matching.

These tests verify that the should_ignore function (in scan command)
and should_ignore_dir utility (in utils) correctly match ignore patterns
as complete path segments, avoiding false positives from substring matches.

Bug: Previously, "target/" would match "/home/user/test-target/src/"
     because "target/" appeared as a substring in the absolute path.
Fix: Now, patterns only match when they correspond to a complete path
     segment boundary.
"""

import os
import sys
import json
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from commands.scan import should_ignore, discover_files
from utils import should_ignore_dir
from registry import save_config


class TestShouldIgnoreSegmentAware:
    """Test that should_ignore uses path-segment-aware matching."""

    def test_exact_match(self):
        """Exact directory name should be ignored."""
        assert should_ignore("node_modules", {"ignore": ["node_modules/"]}) is True

    def test_prefix_segment(self):
        """Pattern at start of path should match."""
        assert should_ignore("node_modules/react", {"ignore": ["node_modules/"]}) is True

    def test_middle_segment(self):
        """Pattern as a middle path segment should match."""
        assert should_ignore("src/node_modules/react", {"ignore": ["node_modules/"]}) is True

    def test_suffix_segment(self):
        """Pattern as last path segment should match."""
        assert should_ignore("src/target", {"ignore": ["target/"]}) is True

    def test_no_false_positive_substring(self):
        """Pattern should NOT match as a substring within a path segment.

        This is the core bug fix: 'test-target' should not match 'target/'.
        """
        assert should_ignore("test-target/src", {"ignore": ["target/"]}) is False

    def test_no_false_positive_embedded(self):
        """'dist-app' should not match 'dist/'."""
        assert should_ignore("dist-app/components", {"ignore": ["dist/"]}) is False

    def test_no_false_positive_prefix(self):
        """'build-tools' should not match 'build/'."""
        assert should_ignore("build-tools/config", {"ignore": ["build/"]}) is False

    def test_actual_target_dir_should_match(self):
        """'src/target/debug' SHOULD match 'target/'."""
        assert should_ignore("src/target/debug", {"ignore": ["target/"]}) is True

    def test_git_hidden_dir(self):
        """'.git' should be matched."""
        assert should_ignore(".git/objects", {"ignore": [".git/"]}) is True

    def test_no_match_unrelated(self):
        """Completely unrelated path should not match."""
        assert should_ignore("src/components/App.tsx", {"ignore": ["node_modules/", "target/"]}) is False

    def test_windows_backslash_normalized(self):
        """Backslash paths should be normalized for matching."""
        assert should_ignore("src\\node_modules\\react", {"ignore": ["node_modules/"]}) is True

    def test_workspace_named_test_target(self):
        """Full workspace path containing 'test-target' should not match 'target/'.

        This was the original bug: workspace at /home/user/test-target
        caused ALL subdirectories to be ignored because 'target/' was found
        as a substring in the absolute path.
        """
        # This tests the relative path case (which is what we now use)
        assert should_ignore("src/main.tsx", {"ignore": ["target/"]}) is False


class TestShouldIgnoreDir:
    """Test the shared should_ignore_dir utility."""

    def test_exact_match(self):
        assert should_ignore_dir("node_modules") is True

    def test_nested_match(self):
        assert should_ignore_dir("src/node_modules/pkg") is True

    def test_no_false_positive(self):
        assert should_ignore_dir("test-target/src") is False

    def test_no_false_positive_embedded(self):
        assert should_ignore_dir("dist-app/components") is False

    def test_git_directory(self):
        assert should_ignore_dir(".git") is True

    def test_nested_git(self):
        assert should_ignore_dir("project/.git/objects") is True

    def test_codelens_directory(self):
        assert should_ignore_dir(".codelens") is True

    def test_normal_path(self):
        assert should_ignore_dir("src/components") is False


class TestDiscoverFilesWithSubstringWorkspace:
    """Test that discover_files works when workspace name contains an ignore pattern."""

    def test_workspace_named_test_target_finds_files(self):
        """When workspace is named 'test-target', files should still be discovered.

        Previously, ALL files were ignored because 'target/' matched as
        a substring of the workspace name in the absolute path.
        """
        # Create workspace with 'test-target' in the path
        parent = tempfile.mkdtemp()
        ws = os.path.join(parent, "test-target")
        os.makedirs(ws)

        # Create source files
        src_dir = os.path.join(ws, "src")
        os.makedirs(src_dir)

        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)

        with open(os.path.join(src_dir, "App.tsx"), 'w') as f:
            f.write('export function App() { return <div className="app">Hello</div>; }')

        with open(os.path.join(src_dir, "index.html"), 'w') as f:
            f.write('<!DOCTYPE html><html><body><div id="root"></div></body></html>')

        with open(os.path.join(src_dir, "styles.css"), 'w') as f:
            f.write('.app { color: red; }')

        try:
            # Init and scan
            from commands.init import cmd_init
            cmd_init(ws)

            config = {
                "frontend_paths": ["src/"],
                "backend_paths": [],
                "watch": True,
                "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
                "frameworks": ["react"],
                "jsx_mode": True,
                "vue_mode": False,
                "svelte_mode": False,
                "tailwind_mode": False,
            }
            save_config(ws, config)

            files = discover_files(ws, config)

            # Should find the TSX and HTML and CSS files
            assert len(files["tsx"]) > 0, f"Expected TSX files but got: {files}"
            assert len(files["html"]) > 0, f"Expected HTML files but got: {files}"
            assert len(files["css"]) > 0, f"Expected CSS files but got: {files}"
        finally:
            shutil.rmtree(parent, ignore_errors=True)

    def test_workspace_named_dist_app_finds_files(self):
        """When workspace is named 'dist-app', files should still be discovered."""
        parent = tempfile.mkdtemp()
        ws = os.path.join(parent, "dist-app")
        os.makedirs(ws)

        src_dir = os.path.join(ws, "src")
        os.makedirs(src_dir)

        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)

        with open(os.path.join(src_dir, "App.tsx"), 'w') as f:
            f.write('export function App() { return <div>Hello</div>; }')

        try:
            from commands.init import cmd_init
            cmd_init(ws)

            config = {
                "frontend_paths": ["src/"],
                "backend_paths": [],
                "watch": True,
                "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
                "frameworks": ["react"],
                "jsx_mode": True,
                "vue_mode": False,
                "svelte_mode": False,
                "tailwind_mode": False,
            }
            save_config(ws, config)

            files = discover_files(ws, config)

            # Should find the TSX files even though workspace is named "dist-app"
            assert len(files["tsx"]) > 0, f"Expected TSX files but got: {files}"
        finally:
            shutil.rmtree(parent, ignore_errors=True)

    def test_actual_target_dir_is_ignored(self):
        """When there IS an actual 'target' directory, it should be ignored."""
        parent = tempfile.mkdtemp()
        ws = os.path.join(parent, "my-project")
        os.makedirs(ws)

        src_dir = os.path.join(ws, "src")
        os.makedirs(src_dir)
        target_dir = os.path.join(ws, "target")
        os.makedirs(target_dir)

        with open(os.path.join(ws, "package.json"), 'w') as f:
            json.dump({"dependencies": {"react": "^18.0.0"}}, f)

        with open(os.path.join(src_dir, "App.tsx"), 'w') as f:
            f.write('export function App() { return <div>Hello</div>; }')

        # This file should be IGNORED because it's in the target/ directory
        with open(os.path.join(target_dir, "output.tsx"), 'w') as f:
            f.write('export function Output() { return <div>Build output</div>; }')

        try:
            from commands.init import cmd_init
            cmd_init(ws)

            config = {
                "frontend_paths": ["src/"],
                "backend_paths": [],
                "watch": True,
                "ignore": ["node_modules/", "dist/", ".git/", "build/", "target/", "__pycache__/"],
                "frameworks": ["react"],
                "jsx_mode": True,
                "vue_mode": False,
                "svelte_mode": False,
                "tailwind_mode": False,
            }
            save_config(ws, config)

            files = discover_files(ws, config)

            # Should find src/App.tsx but NOT target/output.tsx
            assert len(files["tsx"]) == 1, f"Expected 1 TSX file (only src/), got: {files['tsx']}"
            assert any("App.tsx" in f for f in files["tsx"])
            assert not any("target" in f and "output.tsx" in f for f in files["tsx"])
        finally:
            shutil.rmtree(parent, ignore_errors=True)
