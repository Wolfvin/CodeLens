"""Tests for scripts/diff_scope.py — issue #157.

Tests the DiffScope class and its factory from_ref(), including:
- Construction with explicit file lists
- Path normalization (absolute ↔ relative, OS separators)
- filter_findings with various file key names
- from_ref against real temporary git repos
- Error cases: invalid ref, empty ref, non-git directory, missing workspace
- Empty diff detection
- Summary dict structure
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from diff_scope import DiffScope, DiffScopeError


# ─── 1. Direct construction ──────────────────────────────────


class TestConstruction(unittest.TestCase):
    """DiffScope constructed directly with a file list (no git)."""

    def test_basic_construction(self):
        scope = DiffScope("/tmp/work", ["src/a.py", "src/b.py"])
        self.assertEqual(scope.workspace, "/tmp/work")
        self.assertEqual(scope.changed_count, 2)
        self.assertFalse(scope.is_empty)

    def test_absolute_paths_normalized_to_relative(self):
        scope = DiffScope("/tmp/work", ["/tmp/work/src/a.py"])
        # Stored as relative with forward slashes
        self.assertIn("src/a.py", scope.changed_files)

    def test_empty_file_list_is_empty_scope(self):
        scope = DiffScope("/tmp/work", [])
        self.assertTrue(scope.is_empty)
        self.assertEqual(scope.changed_count, 0)

    def test_empty_strings_in_list_are_skipped(self):
        scope = DiffScope("/tmp/work", ["", "src/a.py", ""])
        self.assertEqual(scope.changed_count, 1)

    def test_paths_normalized_to_forward_slash(self):
        """Backslash separators (Windows) normalized to forward slash."""
        scope = DiffScope("/tmp/work", ["src\\nested\\a.py"])
        self.assertIn("src/nested/a.py", scope.changed_files)

    def test_changed_files_is_frozenset(self):
        scope = DiffScope("/tmp/work", ["src/a.py"])
        self.assertIsInstance(scope.changed_files, frozenset)

    def test_workspace_is_absolute(self):
        scope = DiffScope("relative/path", ["a.py"])
        self.assertTrue(os.path.isabs(scope.workspace))


# ─── 2. allows() ─────────────────────────────────────────────


class TestAllows(unittest.TestCase):
    """DiffScope.allows() path-matching logic."""

    def setUp(self):
        self.scope = DiffScope("/tmp/work", ["src/a.py", "src/b.py"])

    def test_relative_path_in_set(self):
        self.assertTrue(self.scope.allows("src/a.py"))

    def test_absolute_path_in_set(self):
        self.assertTrue(self.scope.allows("/tmp/work/src/a.py"))

    def test_relative_path_not_in_set(self):
        self.assertFalse(self.scope.allows("src/c.py"))

    def test_empty_path(self):
        self.assertFalse(self.scope.allows(""))

    def test_none_path(self):
        self.assertFalse(self.scope.allows(None))  # type: ignore[arg-type]

    def test_backslash_path_matches(self):
        """Windows-style backslash path should match forward-slash entry."""
        scope = DiffScope("/tmp/work", ["src/a.py"])
        self.assertTrue(scope.allows("src\\a.py"))


# ─── 3. filter_findings() ────────────────────────────────────


class TestFilterFindings(unittest.TestCase):
    """DiffScope.filter_findings() drops findings from unchanged files."""

    def setUp(self):
        self.scope = DiffScope("/tmp/work", ["src/a.py", "src/b.py"])

    def test_filters_by_file_key(self):
        findings = [
            {"file": "src/a.py", "msg": "keep"},
            {"file": "src/unchanged.py", "msg": "drop"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["msg"], "keep")

    def test_filters_by_path_key(self):
        findings = [
            {"path": "src/a.py", "msg": "keep"},
            {"path": "src/unchanged.py", "msg": "drop"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 1)

    def test_filters_by_defined_in_key(self):
        findings = [
            {"defined_in": "src/a.py", "msg": "keep"},
            {"defined_in": "src/unchanged.py", "msg": "drop"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 1)

    def test_filters_by_file_path_key(self):
        findings = [
            {"file_path": "src/a.py", "msg": "keep"},
            {"file_path": "src/unchanged.py", "msg": "drop"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 1)

    def test_absolute_file_path_matches_relative_entry(self):
        findings = [
            {"file": "/tmp/work/src/a.py", "msg": "keep"},
            {"file": "/tmp/work/src/unchanged.py", "msg": "drop"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 1)

    def test_findings_without_file_key_are_kept(self):
        """Workspace-level findings (no file key) should be kept."""
        findings = [
            {"msg": "no .gitignore found", "severity": "low"},
            {"file": "src/a.py", "msg": "keep"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 2)

    def test_empty_file_value_treated_as_no_file(self):
        """A finding with file="" should be kept (treated as no file key)."""
        findings = [
            {"file": "", "msg": "keep"},
            {"file": "src/a.py", "msg": "keep"},
        ]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 2)

    def test_empty_findings_list(self):
        kept = self.scope.filter_findings([])
        self.assertEqual(kept, [])

    def test_non_dict_findings_kept(self):
        """Non-dict entries (strings, None) are kept — caller's responsibility."""
        findings = ["raw string", None, {"file": "src/a.py", "msg": "keep"}]
        kept = self.scope.filter_findings(findings)
        self.assertEqual(len(kept), 3)

    def test_custom_file_keys_override_defaults(self):
        """When custom file_keys are specified, only those keys are checked.

        A finding with a ``file`` key (default key) but no ``custom_key``
        should be KEPT (treated as no-file because the custom key isn't
        present).
        """
        findings = [
            {"custom_key": "src/a.py", "msg": "keep"},
            {"custom_key": "src/unchanged.py", "msg": "drop"},
            {"file": "src/a.py", "msg": "keep (no custom_key → treated as no-file)"},
        ]
        kept = self.scope.filter_findings(findings, file_keys=["custom_key"])
        self.assertEqual(len(kept), 2)
        msgs = {f["msg"] for f in kept}
        self.assertIn("keep", msgs)
        self.assertIn("keep (no custom_key → treated as no-file)", msgs)

    def test_does_not_mutate_input(self):
        findings = [{"file": "src/a.py"}, {"file": "src/unchanged.py"}]
        original = [dict(f) for f in findings]
        self.scope.filter_findings(findings)
        self.assertEqual(findings, original)


# ─── 4. summary() ────────────────────────────────────────────


class TestSummary(unittest.TestCase):
    """DiffScope.summary() returns a dict suitable for embedding in output."""

    def test_summary_structure(self):
        scope = DiffScope("/tmp/work", ["src/a.py", "src/b.py"])
        s = scope.summary()
        self.assertIn("base_ref", s)
        self.assertIn("changed_files", s)
        self.assertIn("changed_count", s)
        self.assertIn("workspace", s)

    def test_summary_changed_files_sorted(self):
        scope = DiffScope("/tmp/work", ["src/b.py", "src/a.py"])
        s = scope.summary()
        self.assertEqual(s["changed_files"], ["src/a.py", "src/b.py"])

    def test_summary_base_ref_none_when_not_from_ref(self):
        scope = DiffScope("/tmp/work", ["src/a.py"])
        self.assertIsNone(scope.summary()["base_ref"])


# ─── 5. from_ref() against real git repos ───────────────────


class TestFromRefRealGit(unittest.TestCase):
    """DiffScope.from_ref() against real temporary git repositories."""

    def setUp(self):
        """Create a temp git repo with a couple of commits."""
        self.tmpdir = tempfile.mkdtemp(prefix="codelens_diffscope_test_")
        self._run("git", "init", cwd=self.tmpdir)
        self._run("git", "config", "user.email", "test@test.com", cwd=self.tmpdir)
        self._run("git", "config", "user.name", "test", cwd=self.tmpdir)
        # Initial commit
        self._write("file1.py", "print('hello')\n")
        self._write("file2.py", "print('world')\n")
        self._run("git", "add", ".", cwd=self.tmpdir)
        self._run("git", "commit", "-m", "initial", cwd=self.tmpdir)
        self.first_sha = self._run("git", "rev-parse", "HEAD", cwd=self.tmpdir).strip()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, *cmd, cwd=None):
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=True
        ).stdout

    def _write(self, name, content):
        with open(os.path.join(self.tmpdir, name), "w") as f:
            f.write(content)

    def test_from_ref_with_no_changes(self):
        """HEAD vs HEAD (no uncommitted changes) → empty diff."""
        scope = DiffScope.from_ref(self.tmpdir, "HEAD")
        self.assertTrue(scope.is_empty)
        self.assertEqual(scope.changed_count, 0)

    def test_from_ref_with_uncommitted_change(self):
        """HEAD vs working tree (uncommitted edit) → 1 changed file."""
        self._write("file1.py", "print('changed')\n")
        scope = DiffScope.from_ref(self.tmpdir, "HEAD")
        self.assertFalse(scope.is_empty)
        self.assertEqual(scope.changed_count, 1)
        self.assertIn("file1.py", scope.changed_files)

    def test_from_ref_with_new_untracked_file(self):
        """Untracked files should be included by default."""
        self._write("file3.py", "print('new')\n")
        scope = DiffScope.from_ref(self.tmpdir, "HEAD")
        self.assertIn("file3.py", scope.changed_files)

    def test_from_ref_exclude_untracked(self):
        """include_untracked=False excludes untracked files."""
        self._write("file3.py", "print('new')\n")
        scope = DiffScope.from_ref(self.tmpdir, "HEAD", include_untracked=False)
        self.assertNotIn("file3.py", scope.changed_files)
        self.assertTrue(scope.is_empty)

    def test_from_ref_against_first_commit(self):
        """Diffing HEAD against the first commit should show all post-initial changes."""
        # Make a second commit
        self._write("file3.py", "print('third')\n")
        self._run("git", "add", ".", cwd=self.tmpdir)
        self._run("git", "commit", "-m", "second", cwd=self.tmpdir)
        scope = DiffScope.from_ref(self.tmpdir, self.first_sha)
        self.assertIn("file3.py", scope.changed_files)

    def test_from_ref_sets_base_ref_in_summary(self):
        scope = DiffScope.from_ref(self.tmpdir, "HEAD")
        self.assertEqual(scope.summary()["base_ref"], "HEAD")

    def test_from_ref_head_tilde_1(self):
        """HEAD~1 syntax works."""
        # Make a second commit
        self._write("file3.py", "print('third')\n")
        self._run("git", "add", ".", cwd=self.tmpdir)
        self._run("git", "commit", "-m", "second", cwd=self.tmpdir)
        scope = DiffScope.from_ref(self.tmpdir, "HEAD~1")
        self.assertIn("file3.py", scope.changed_files)
        self.assertEqual(scope.summary()["base_ref"], "HEAD~1")

    def test_from_ref_branch_name(self):
        """Branch name as ref works (detects default branch — main or master)."""
        # Detect the default branch created by `git init`
        branch_out = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=self.tmpdir, capture_output=True, text=True, check=True,
        )
        default_branch = branch_out.stdout.strip()
        self.assertTrue(default_branch, "git should have a current branch")
        scope = DiffScope.from_ref(self.tmpdir, default_branch)
        # current_branch vs HEAD (no uncommitted changes) → empty
        self.assertTrue(scope.is_empty)
        self.assertEqual(scope.summary()["base_ref"], default_branch)


# ─── 6. from_ref() error cases ──────────────────────────────


class TestFromRefErrors(unittest.TestCase):
    """DiffScope.from_ref() raises DiffScopeError on bad input."""

    def test_invalid_ref_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmpdir, capture_output=True, check=True)
            with open(os.path.join(tmpdir, "f.py"), "w") as f:
                f.write("x = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True, check=True)
            with self.assertRaises(DiffScopeError) as ctx:
                DiffScope.from_ref(tmpdir, "nonexistent-ref-xyz")
            self.assertIn("nonexistent-ref-xyz", str(ctx.exception))

    def test_empty_ref_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(DiffScopeError) as ctx:
                DiffScope.from_ref(tmpdir, "")
            self.assertIn("non-empty", str(ctx.exception))

    def test_nonexistent_workspace_raises(self):
        with self.assertRaises(DiffScopeError) as ctx:
            DiffScope.from_ref("/nonexistent/path/xyz", "HEAD")
        self.assertIn("does not exist", str(ctx.exception))

    def test_non_git_directory_raises(self):
        """A directory that exists but is not a git repo should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(DiffScopeError):
                DiffScope.from_ref(tmpdir, "HEAD")


# ─── 7. CLI integration (subprocess) ────────────────────────


class TestCliIntegration(unittest.TestCase):
    """End-to-end CLI tests via subprocess — --diff-base flag works."""

    @classmethod
    def setUpClass(cls):
        """Use the CodeLens repo itself as the test workspace."""
        cls.codelens_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.cli = os.path.join(cls.codelens_repo, "scripts", "codelens.py")

    def _run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env.pop("CODELENS_AI_MODE", None)  # ensure json default
        proc = subprocess.run(
            [sys.executable, self.cli] + list(args),
            capture_output=True, text=True, env=env, timeout=60,
            cwd=self.codelens_repo,
        )
        return proc

    def test_diff_base_flag_in_help(self):
        proc = self._run_cli("--help")
        self.assertIn("--diff-base", proc.stdout)

    def test_invalid_ref_exits_nonzero(self):
        proc = self._run_cli("secrets", "tests/fixtures", "--diff-base", "nonexistent-ref-xyz")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("diff_scope_error", proc.stderr + proc.stdout)

    def test_valid_ref_produces_diff_scope_in_output(self):
        """--diff-base HEAD~1 should add a diff_scope key to the JSON output."""
        proc = self._run_cli("secrets", "tests/fixtures", "--diff-base", "HEAD~1")
        # Find JSON in output (skip stderr hint lines)
        import json
        out = proc.stdout
        json_start = out.find("{")
        self.assertGreater(json_start, -1, "No JSON in output")
        data = json.loads(out[json_start:])
        self.assertIn("diff_scope", data)
        self.assertIn("changed_count", data["diff_scope"])
        self.assertIn("findings_before_filter", data["diff_scope"])
        self.assertIn("findings_after_filter", data["diff_scope"])

    def test_empty_diff_early_exit(self):
        """--diff-base HEAD in a clean repo → early exit with 'No changed files' message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmpdir, capture_output=True, check=True)
            with open(os.path.join(tmpdir, "f.py"), "w") as f:
                f.write("x = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, capture_output=True, check=True)

            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            env.pop("CODELENS_AI_MODE", None)
            proc = subprocess.run(
                [sys.executable, self.cli, "secrets", tmpdir, "--diff-base", "HEAD"],
                capture_output=True, text=True, env=env, timeout=60,
                cwd=self.codelens_repo,
            )
            self.assertEqual(proc.returncode, 0)
            import json
            out = proc.stdout
            json_start = out.find("{")
            self.assertGreater(json_start, -1)
            data = json.loads(out[json_start:])
            self.assertEqual(data["status"], "ok")
            self.assertIn("No changed files", data.get("message", ""))
            self.assertEqual(data["diff_scope"]["changed_count"], 0)

    def test_diff_base_before_subcommand(self):
        """--diff-base works both before and after the subcommand."""
        proc = self._run_cli("--diff-base", "HEAD~1", "secrets", "tests/fixtures")
        import json
        out = proc.stdout
        json_start = out.find("{")
        self.assertGreater(json_start, -1)
        data = json.loads(out[json_start:])
        self.assertIn("diff_scope", data)


if __name__ == "__main__":
    unittest.main()
