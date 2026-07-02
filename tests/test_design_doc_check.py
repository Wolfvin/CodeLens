"""Tests for scripts/check_design_doc.py — issue #67 Phase 1.

Tests the pure-logic check_pr() function (no GitHub API calls) and the
is_feature_file() classifier. The CLI entry point (main()) is tested via
subprocess to verify env-var and arg parsing.
"""

import os
import subprocess
import sys
import unittest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from check_design_doc import (
    BYPASS_LABEL,
    DESIGN_DOC_DIR,
    check_pr,
    is_feature_file,
)


# ─── 1. is_feature_file classifier ───────────────────────────


class TestIsFeatureFile(unittest.TestCase):
    """Classify file + status pairs as feature or non-feature."""

    def test_new_command_added_is_feature(self):
        self.assertTrue(is_feature_file("scripts/commands/yourfeature.py", "added"))

    def test_new_engine_added_is_feature(self):
        self.assertTrue(is_feature_file("scripts/yourfeature_engine.py", "added"))

    def test_new_formatter_added_is_feature(self):
        self.assertTrue(is_feature_file("scripts/formatters/yourformat.py", "added"))

    def test_new_parser_added_is_feature(self):
        self.assertTrue(is_feature_file("scripts/parsers/yourlang_parser.py", "added"))

    def test_fallback_parser_added_is_not_feature(self):
        """Fallback parsers are regex shadows of existing tree-sitter parsers."""
        self.assertFalse(is_feature_file("scripts/parsers/fallback_yourlang.py", "added"))

    def test_modified_command_is_not_feature(self):
        """Bug fixes / refactors modify existing files — not 'added'."""
        self.assertFalse(is_feature_file("scripts/commands/scan.py", "modified"))

    def test_modified_engine_is_not_feature(self):
        self.assertFalse(is_feature_file("scripts/ast_taint_engine.py", "modified"))

    def test_removed_file_is_not_feature(self):
        self.assertFalse(is_feature_file("scripts/commands/oldfeature.py", "removed"))

    def test_renamed_file_is_not_feature(self):
        """Renaming a file is not a new feature."""
        self.assertFalse(is_feature_file("scripts/commands/renamed.py", "renamed"))

    def test_test_file_is_not_feature(self):
        self.assertFalse(is_feature_file("tests/test_yourfeature.py", "added"))

    def test_doc_file_is_not_feature(self):
        self.assertFalse(is_feature_file("README.md", "added"))
        self.assertFalse(is_feature_file("docs/design/0005-foo.md", "added"))

    def test_engine_in_subdirectory_is_not_feature(self):
        """scripts/parsers/fallback_foo_engine.py should not match _engine.py rule.

        The engine rule requires the file to be directly in scripts/, not in
        a subdirectory. This prevents false positives on files like
        scripts/sca_parsers/pipfile_engine.py (hypothetical).
        """
        # A file in a subdirectory that ends with _engine.py should NOT match
        # the engine rule (it's checked by the subdirectory rules instead).
        self.assertFalse(
            is_feature_file("scripts/sca_parsers/some_engine.py", "added")
        )

    def test_non_python_command_file_still_feature(self):
        """Any new file in scripts/commands/ counts, regardless of extension."""
        self.assertTrue(is_feature_file("scripts/commands/yourfeature.js", "added"))

    def test_empty_filename_is_not_feature(self):
        self.assertFalse(is_feature_file("", "added"))

    def test_empty_status_is_not_feature(self):
        self.assertFalse(is_feature_file("scripts/commands/foo.py", ""))


# ─── 2. check_pr — no feature files ──────────────────────────


class TestCheckPrNoFeatureFiles(unittest.TestCase):
    """PRs without feature files should pass silently."""

    def test_bug_fix_passes(self):
        files = [{"filename": "scripts/commands/scan.py", "status": "modified"}]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])
        self.assertEqual(result["feature_files"], [])
        self.assertFalse(result["bypassed"])

    def test_test_only_pr_passes(self):
        files = [{"filename": "tests/test_foo.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])

    def test_doc_only_pr_passes(self):
        files = [{"filename": "README.md", "status": "modified"}]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])

    def test_empty_pr_passes(self):
        result = check_pr([], [])
        self.assertTrue(result["passed"])

    def test_design_doc_only_pr_passes(self):
        """A PR that only adds a design doc (no feature) passes."""
        files = [{"filename": "docs/design/0005-retroactive.md", "status": "added"}]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])
        self.assertEqual(result["design_docs"], ["docs/design/0005-retroactive.md"])


# ─── 3. check_pr — feature files without design doc ─────────


class TestCheckPrFeatureWithoutDesignDoc(unittest.TestCase):
    """PRs with feature files but no design doc should FAIL."""

    def test_new_command_without_design_doc_fails(self):
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])
        self.assertIn("scripts/commands/newcmd.py", result["feature_files"])
        self.assertEqual(result["design_docs"], [])
        self.assertFalse(result["bypassed"])
        # Reason should mention the design doc requirement
        self.assertIn("design doc", result["reason"].lower())
        self.assertIn("docs/design/", result["reason"])

    def test_new_engine_without_design_doc_fails(self):
        files = [{"filename": "scripts/newfeat_engine.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])

    def test_new_formatter_without_design_doc_fails(self):
        files = [{"filename": "scripts/formatters/newfmt.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])

    def test_new_parser_without_design_doc_fails(self):
        files = [{"filename": "scripts/parsers/newlang_parser.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])

    def test_reason_mentions_bypass_label(self):
        """The failure reason should tell users about the bypass label."""
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertIn(BYPASS_LABEL, result["reason"])

    def test_reason_mentions_template(self):
        """The failure reason should point users to the template."""
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertIn("template", result["reason"].lower())


# ─── 4. check_pr — feature files WITH design doc ────────────


class TestCheckPrFeatureWithDesignDoc(unittest.TestCase):
    """PRs with feature files and a design doc should pass."""

    def test_new_command_with_design_doc_passes(self):
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/design/0005-newcmd.md", "status": "added"},
        ]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])
        self.assertIn("scripts/commands/newcmd.py", result["feature_files"])
        self.assertIn("docs/design/0005-newcmd.md", result["design_docs"])

    def test_modified_design_doc_counts(self):
        """If the PR modifies an existing design doc, that counts."""
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/design/0001-taint-engine.md", "status": "modified"},
        ]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])

    def test_renamed_design_doc_counts(self):
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/design/0005-newcmd.md", "status": "renamed"},
        ]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])

    def test_multiple_feature_files_with_one_design_doc_passes(self):
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "scripts/newfeat_engine.py", "status": "added"},
            {"filename": "scripts/formatters/newfmt.py", "status": "added"},
            {"filename": "docs/design/0005-newfeat.md", "status": "added"},
        ]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["feature_files"]), 3)

    def test_non_md_file_in_design_dir_does_not_count(self):
        """A .txt or .yaml file in docs/design/ is not a design doc."""
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/design/notes.txt", "status": "added"},
        ]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])
        self.assertEqual(result["design_docs"], [])


# ─── 5. check_pr — bypass label ──────────────────────────────


class TestCheckPrBypass(unittest.TestCase):
    """The 'skip-design-doc' label bypasses the check."""

    def test_bypass_label_allows_feature_without_design_doc(self):
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, [BYPASS_LABEL])
        self.assertTrue(result["passed"])
        self.assertTrue(result["bypassed"])
        self.assertIn("bypassed", result["reason"].lower())

    def test_bypass_label_with_design_doc_still_passes(self):
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/design/0005-newcmd.md", "status": "added"},
        ]
        result = check_pr(files, [BYPASS_LABEL])
        self.assertTrue(result["passed"])
        self.assertTrue(result["bypassed"])

    def test_other_labels_do_not_bypass(self):
        """Only the exact 'skip-design-doc' label bypasses."""
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, ["skip-design", "skip-design-docs", "no-design-doc"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["bypassed"])

    def test_bypass_label_case_sensitive(self):
        """Label matching is case-sensitive (GitHub labels are case-insensitive
        but we match exactly — the API returns the label's stored name)."""
        files = [{"filename": "scripts/commands/newcmd.py", "status": "added"}]
        result = check_pr(files, ["Skip-Design-Doc"])
        self.assertFalse(result["passed"])


# ─── 6. Edge cases ───────────────────────────────────────────


class TestEdgeCases(unittest.TestCase):
    """Edge cases: missing keys, weird inputs, mixed PRs."""

    def test_file_without_status_key_treated_as_not_feature(self):
        """If status is missing, is_feature_file returns False (defensive)."""
        files = [{"filename": "scripts/commands/newcmd.py"}]  # no status
        result = check_pr(files, [])
        self.assertTrue(result["passed"])  # no feature detected

    def test_file_without_filename_key_skipped(self):
        files = [{"status": "added"}]  # no filename
        result = check_pr(files, [])
        self.assertTrue(result["passed"])

    def test_mixed_pr_bug_fix_and_new_feature_without_doc_fails(self):
        """A PR with both a bug fix and a new feature still needs a design doc."""
        files = [
            {"filename": "scripts/commands/scan.py", "status": "modified"},  # bug fix
            {"filename": "scripts/commands/newcmd.py", "status": "added"},   # new feature
        ]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])
        self.assertIn("scripts/commands/newcmd.py", result["feature_files"])
        self.assertNotIn("scripts/commands/scan.py", result["feature_files"])

    def test_fallback_parser_does_not_trigger_requirement(self):
        """Adding a fallback parser (regex shadow) does not require a design doc."""
        files = [{"filename": "scripts/parsers/fallback_newlang.py", "status": "added"}]
        result = check_pr(files, [])
        self.assertTrue(result["passed"])
        self.assertEqual(result["feature_files"], [])

    def test_design_doc_in_wrong_directory_does_not_count(self):
        """A design doc in docs/ (not docs/design/) does not satisfy the check."""
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/newcmd-design.md", "status": "added"},
        ]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])
        self.assertEqual(result["design_docs"], [])

    def test_plan_doc_does_not_satisfy_design_doc_requirement(self):
        """A plan in docs/plans/ does not satisfy the design doc requirement.

        Plans are recommended but not enforced — only docs/design/ counts.
        """
        files = [
            {"filename": "scripts/commands/newcmd.py", "status": "added"},
            {"filename": "docs/plans/0005-newcmd.md", "status": "added"},
        ]
        result = check_pr(files, [])
        self.assertFalse(result["passed"])
        self.assertEqual(result["design_docs"], [])


# ─── 7. CLI entry point (subprocess) ─────────────────────────


class TestCliEntryPoint(unittest.TestCase):
    """Test the main() CLI entry point via subprocess."""

    def _run(self, args, env=None):
        """Run check_design_doc.py with the given args, return (returncode, stdout, stderr)."""
        full_env = os.environ.copy()
        if env is not None:
            full_env.update(env)
        # Ensure GITHUB_TOKEN etc. are NOT set (so CI mode doesn't trigger)
        for key in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "PR_NUMBER"):
            full_env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "check_design_doc.py")] + args,
            capture_output=True, text=True, env=full_env, timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_local_mode_bug_fix_passes(self):
        rc, out, _ = self._run(["--files", "scripts/commands/scan.py", "--status", "modified"])
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out)

    def test_local_mode_new_command_without_doc_fails(self):
        rc, out, _ = self._run(["--files", "scripts/commands/newcmd.py", "--status", "added"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)
        self.assertIn("design doc", out.lower())

    def test_local_mode_new_command_with_doc_passes(self):
        rc, out, _ = self._run([
            "--files", "scripts/commands/newcmd.py", "docs/design/0005-newcmd.md",
            "--status", "added", "added",
        ])
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out)

    def test_local_mode_bypass_label_passes(self):
        rc, out, _ = self._run([
            "--files", "scripts/commands/newcmd.py",
            "--status", "added",
            "--labels", BYPASS_LABEL,
        ])
        self.assertEqual(rc, 0)
        self.assertIn("PASS", out)
        self.assertIn("bypassed", out.lower())

    def test_local_mode_default_status_is_added(self):
        """If --status is omitted, all files are assumed 'added'."""
        rc, out, _ = self._run(["--files", "scripts/commands/newcmd.py"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)

    def test_local_mode_mismatched_files_and_status_returns_2(self):
        rc, _, err = self._run([
            "--files", "a.py", "b.py",
            "--status", "added",  # only 1 status for 2 files
        ])
        self.assertEqual(rc, 2)
        self.assertIn("same length", err)

    def test_ci_mode_without_env_vars_returns_2(self):
        """CI mode (no --files) without env vars should return 2 with an error."""
        full_env = os.environ.copy()
        for key in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "PR_NUMBER"):
            full_env.pop(key, None)
        proc = subprocess.run(
            [sys.executable, os.path.join(SCRIPT_DIR, "check_design_doc.py")],
            capture_output=True, text=True, env=full_env, timeout=30,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("CI mode requires", proc.stderr)


if __name__ == "__main__":
    unittest.main()
