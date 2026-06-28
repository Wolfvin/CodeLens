"""Tests for git-aware incremental re-index (issue #14).

Verifies:
1. get_current_sha / get_current_branch return values in a git repo, None outside.
2. get_changed_files returns expected files after a touch + git add.
3. get_last_indexed_sha / set_last_indexed_sha round-trip via registry_meta.
4. detect_branch_switch returns True after a checkout, False otherwise.
5. git-status command returns status=ok with all expected fields.
6. diff --git-aware returns changed files + symbols + impact on a fixture.

All git operations use a temp directory + `git init` so tests don't
depend on the CodeLens repo's git state. If git isn't installed, every
test is skipped with pytest.skip('git not available') (NOT failed).
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import pytest

# Add scripts directory to path (matches other test files).
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)


# ─── Skip-if-git-missing guard ──────────────────────────────────────


def _git_available() -> bool:
    """Return True if the ``git`` binary is installed and runnable."""
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _git_available(),
    reason="git not available",
)


# ─── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def tmp_git_repo():
    """Yield a fresh git repo in a temp directory with one initial commit.

    The repo has ``user.name`` / ``user.email`` configured locally so
    commits work without relying on the host's global git config. The
    default branch is ``main`` (matches modern git defaults).
    """
    td = tempfile.mkdtemp(prefix="codelens_git_test_")
    env = os.environ.copy()
    try:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=td, check=True)
    except subprocess.CalledProcessError:
        # Older git without -b flag — fall back to default branch then rename.
        subprocess.run(["git", "init", "-q"], cwd=td, check=True)
        subprocess.run(
            ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
            cwd=td, check=True,
        )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=td, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=td, check=True
    )
    # Initial commit so HEAD exists (empty tree commit).
    with open(os.path.join(td, "README.md"), "w") as f:
        f.write("# test\n")
    subprocess.run(["git", "add", "README.md"], cwd=td, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "init", "--allow-empty"],
        cwd=td, check=True,
    )
    yield td
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def tmp_non_git_dir():
    """Yield a temp directory that is NOT a git repo."""
    td = tempfile.mkdtemp(prefix="codelens_nogit_test_")
    yield td
    shutil.rmtree(td, ignore_errors=True)


@pytest.fixture
def db_path(tmp_git_repo):
    """Yield a SQLite db path inside the tmp git repo (.codelens/codelens.db).

    Pre-creates the registry_meta table so set/get_last_indexed_sha can
    be tested without depending on the PersistentRegistry init path.
    """
    codelens_dir = os.path.join(tmp_git_repo, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    path = os.path.join(codelens_dir, "codelens.db")
    conn = sqlite3.connect(path)
    from git_aware import init_registry_meta
    init_registry_meta(conn)
    conn.close()
    return path


# ─── 1. get_current_sha / get_current_branch ────────────────────────


class TestCurrentSha:
    """Verify SHA + branch detection in and out of git repos."""

    def test_returns_sha_in_git_repo(self, tmp_git_repo):
        from git_aware import get_current_sha
        sha = get_current_sha(tmp_git_repo)
        assert sha is not None
        assert len(sha) == 40, f"expected 40-char SHA, got {sha!r}"
        # All hex chars
        int(sha, 16)

    def test_returns_none_outside_git(self, tmp_non_git_dir):
        from git_aware import get_current_sha
        assert get_current_sha(tmp_non_git_dir) is None

    def test_returns_branch_in_git_repo(self, tmp_git_repo):
        from git_aware import get_current_branch
        branch = get_current_branch(tmp_git_repo)
        assert branch == "main"

    def test_returns_none_branch_outside_git(self, tmp_non_git_dir):
        from git_aware import get_current_branch
        assert get_current_branch(tmp_non_git_dir) is None


# ─── 2. get_changed_files / get_untracked_files ─────────────────────


class TestChangedFiles:
    """Verify git diff enumeration of changed + untracked files."""

    def test_no_changes_returns_empty(self, tmp_git_repo):
        from git_aware import get_changed_files
        assert get_changed_files(tmp_git_repo) == []

    def test_modified_file_appears(self, tmp_git_repo):
        from git_aware import get_changed_files
        # Modify the committed README
        with open(os.path.join(tmp_git_repo, "README.md"), "a") as f:
            f.write("\nnew line\n")
        changed = get_changed_files(tmp_git_repo)
        assert "README.md" in changed

    def test_untracked_file_appears(self, tmp_git_repo):
        from git_aware import get_untracked_files
        with open(os.path.join(tmp_git_repo, "new.py"), "w") as f:
            f.write("x = 1\n")
        untracked = get_untracked_files(tmp_git_repo)
        assert "new.py" in untracked

    def test_diff_since_sha_includes_committed_changes(self, tmp_git_repo):
        from git_aware import get_current_sha, get_changed_files
        old_sha = get_current_sha(tmp_git_repo)
        # Commit a new file
        with open(os.path.join(tmp_git_repo, "module.py"), "w") as f:
            f.write("def foo(): pass\n")
        subprocess.run(["git", "add", "module.py"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "add module"],
            cwd=tmp_git_repo, check=True,
        )
        # Diff vs old_sha should include module.py
        changed = get_changed_files(tmp_git_repo, since_sha=old_sha)
        assert "module.py" in changed


# ─── 3. get/set_last_indexed_sha round-trip ─────────────────────────


class TestRegistryMeta:
    """Verify registry_meta key/value round-trip + bookmark helpers."""

    def test_set_then_get_sha(self, tmp_git_repo, db_path):
        from git_aware import (
            set_last_indexed_sha, get_last_indexed_sha,
            get_current_sha, get_current_branch,
        )
        sha = get_current_sha(tmp_git_repo)
        branch = get_current_branch(tmp_git_repo)
        assert sha is not None

        set_last_indexed_sha(tmp_git_repo, db_path, sha)
        assert get_last_indexed_sha(tmp_git_repo, db_path) == sha
        # set_last_indexed_sha also persists the branch.
        from git_aware import get_last_indexed_branch
        assert get_last_indexed_branch(db_path) == branch

    def test_get_returns_none_when_unset(self, tmp_git_repo, db_path):
        from git_aware import get_last_indexed_sha
        assert get_last_indexed_sha(tmp_git_repo, db_path) is None

    def test_get_returns_none_when_db_missing(self, tmp_git_repo):
        from git_aware import get_last_indexed_sha
        missing = os.path.join(tmp_git_repo, "nonexistent.db")
        assert get_last_indexed_sha(tmp_git_repo, missing) is None

    def test_set_none_clears_bookmark(self, tmp_git_repo, db_path):
        from git_aware import (
            set_last_indexed_sha, get_last_indexed_sha,
            get_last_indexed_branch, get_current_sha,
        )
        sha = get_current_sha(tmp_git_repo)
        set_last_indexed_sha(tmp_git_repo, db_path, sha)
        assert get_last_indexed_sha(tmp_git_repo, db_path) == sha
        # Clear it
        set_last_indexed_sha(tmp_git_repo, db_path, None)
        assert get_last_indexed_sha(tmp_git_repo, db_path) is None
        assert get_last_indexed_branch(db_path) is None


# ─── 4. detect_branch_switch ────────────────────────────────────────


class TestBranchSwitch:
    """Verify branch-switch detection across checkouts and same-branch commits."""

    def test_false_when_no_bookmark(self, tmp_git_repo, db_path):
        from git_aware import detect_branch_switch
        assert detect_branch_switch(tmp_git_repo, db_path) is False

    def test_false_on_same_branch_commit(self, tmp_git_repo, db_path):
        """Committing on the same branch must NOT count as a branch switch."""
        from git_aware import (
            set_last_indexed_sha, detect_branch_switch, get_current_sha,
        )
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        # New commit on main
        with open(os.path.join(tmp_git_repo, "x.py"), "w") as f:
            f.write("x = 1\n")
        subprocess.run(["git", "add", "x.py"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "x"], cwd=tmp_git_repo, check=True,
        )
        # SHA moved, branch did not — not a switch.
        assert detect_branch_switch(tmp_git_repo, db_path) is False

    def test_true_after_checkout(self, tmp_git_repo, db_path):
        """Checking out a different branch must count as a switch."""
        from git_aware import (
            set_last_indexed_sha, detect_branch_switch, get_current_sha,
        )
        # Bookmark main
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        # Create + checkout a new branch with a new commit (so SHA moves)
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature/x"],
            cwd=tmp_git_repo, check=True,
        )
        with open(os.path.join(tmp_git_repo, "y.py"), "w") as f:
            f.write("y = 1\n")
        subprocess.run(["git", "add", "y.py"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "y"], cwd=tmp_git_repo, check=True,
        )
        assert detect_branch_switch(tmp_git_repo, db_path) is True

    def test_false_when_back_on_original_branch(self, tmp_git_repo, db_path):
        """Checkout + checkout-back must NOT count as a switch (same branch)."""
        from git_aware import (
            set_last_indexed_sha, detect_branch_switch, get_current_sha,
        )
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        subprocess.run(
            ["git", "checkout", "-q", "-b", "feature/y"],
            cwd=tmp_git_repo, check=True,
        )
        with open(os.path.join(tmp_git_repo, "z.py"), "w") as f:
            f.write("z = 1\n")
        subprocess.run(["git", "add", "z.py"], cwd=tmp_git_repo, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "z"], cwd=tmp_git_repo, check=True,
        )
        # Switch back to main — main still has its original SHA + branch.
        subprocess.run(["git", "checkout", "-q", "main"], cwd=tmp_git_repo, check=True)
        # SHA == bookmarked SHA, branch == bookmarked branch → not a switch.
        assert detect_branch_switch(tmp_git_repo, db_path) is False

    def test_false_outside_git(self, tmp_non_git_dir):
        from git_aware import detect_branch_switch
        db = os.path.join(tmp_non_git_dir, "x.db")
        assert detect_branch_switch(tmp_non_git_dir, db) is False


# ─── 5. rescan_recommended ──────────────────────────────────────────


class TestRescanRecommended:
    """Verify the 'do I need to re-scan?' predicate."""

    def test_true_when_bookmark_unset_and_in_git(self, tmp_git_repo, db_path):
        from git_aware import rescan_recommended
        # No bookmark yet but workspace IS a git repo — recommend first scan.
        assert rescan_recommended(tmp_git_repo, db_path) is True

    def test_false_when_bookmark_matches_head(self, tmp_git_repo, db_path):
        from git_aware import (
            set_last_indexed_sha, rescan_recommended, get_current_sha,
        )
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        assert rescan_recommended(tmp_git_repo, db_path) is False

    def test_true_when_working_tree_dirty(self, tmp_git_repo, db_path):
        from git_aware import (
            set_last_indexed_sha, rescan_recommended, get_current_sha,
        )
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        with open(os.path.join(tmp_git_repo, "README.md"), "a") as f:
            f.write("\nmore\n")
        assert rescan_recommended(tmp_git_repo, db_path) is True


# ─── 6. git-status command ──────────────────────────────────────────


class TestGitStatusCommand:
    """Verify the git-status command returns status=ok with all fields."""

    def test_returns_ok_in_git_repo(self, tmp_git_repo, db_path):
        from commands.git_status import cmd_git_status
        result = cmd_git_status(tmp_git_repo)
        assert result["status"] == "ok"
        assert result["git_available"] is True
        assert result["current_sha"] is not None
        assert result["current_branch"] == "main"
        assert "last_indexed_sha" in result
        assert "last_indexed_branch" in result
        assert "changed_files_count" in result
        assert "branch_switch_detected" in result
        assert "rescan_recommended" in result

    def test_returns_ok_outside_git(self, tmp_non_git_dir):
        from commands.git_status import cmd_git_status
        result = cmd_git_status(tmp_non_git_dir)
        assert result["status"] == "ok"
        assert result["git_available"] is False
        assert result["current_sha"] is None
        assert result["current_branch"] is None
        assert result["rescan_recommended"] is False

    def test_changed_files_count_after_edit(self, tmp_git_repo, db_path):
        from commands.git_status import cmd_git_status
        from git_aware import set_last_indexed_sha, get_current_sha
        # Bookmark current HEAD, then dirty the working tree.
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        with open(os.path.join(tmp_git_repo, "README.md"), "a") as f:
            f.write("\nedit\n")
        result = cmd_git_status(tmp_git_repo)
        assert result["changed_files_count"] >= 1
        assert "README.md" in result["changed_files"]
        assert result["rescan_recommended"] is True


# ─── 7. diff --git-aware ────────────────────────────────────────────


class TestDiffGitAware:
    """Verify diff --git-aware returns changed files + symbols on a fixture."""

    def test_returns_ok_outside_git(self, tmp_non_git_dir):
        from commands.diff import cmd_diff_git_aware
        result = cmd_diff_git_aware(tmp_non_git_dir)
        assert result["status"] == "ok"
        assert result["git_available"] is False
        assert result["changed_files"] == []
        assert result["symbols"] == []
        assert result["impact"] == []

    def test_changed_files_in_git_repo(self, tmp_git_repo, db_path):
        from commands.diff import cmd_diff_git_aware
        with open(os.path.join(tmp_git_repo, "module.py"), "w") as f:
            f.write("def foo(): pass\n")
        result = cmd_diff_git_aware(tmp_git_repo)
        assert result["status"] == "ok"
        assert result["git_available"] is True
        assert "module.py" in result["changed_files"]
        assert result["changed_files_count"] >= 1

    def test_symbols_extracted_from_changed_files(
        self, tmp_git_repo, db_path
    ):
        """Run a scan so backend.json is populated, then verify diff --git-aware
        surfaces symbols defined in changed files."""
        from commands.diff import cmd_diff_git_aware
        from commands.scan import cmd_scan

        # Write a python file and scan so the registry has the symbol.
        with open(os.path.join(tmp_git_repo, "app.py"), "w") as f:
            f.write("def hello():\n    return 'hi'\n")
        # Add a .codelens to gitignore so the scan output isn't flagged as untracked.
        with open(os.path.join(tmp_git_repo, ".gitignore"), "w") as f:
            f.write(".codelens/\n")
        cmd_scan(tmp_git_repo, incremental=False)

        # Now modify app.py — diff --git-aware should report 'hello' as a symbol
        # in the changed file. (Symbols come from backend.json which still has
        # the pre-edit definition — that's the point: it shows what WAS there.)
        with open(os.path.join(tmp_git_repo, "app.py"), "a") as f:
            f.write("\ndef world():\n    return 'bye'\n")

        result = cmd_diff_git_aware(tmp_git_repo)
        assert result["status"] == "ok"
        assert "app.py" in result["changed_files"]
        symbol_names = [s["name"] for s in result["symbols"]]
        assert "hello" in symbol_names, (
            f"expected 'hello' in symbols, got {symbol_names}"
        )

    def test_impact_empty_without_graph(self, tmp_git_repo, db_path):
        """Without a populated graph, impact is empty (issue #25 — known gap)."""
        from commands.diff import cmd_diff_git_aware
        with open(os.path.join(tmp_git_repo, "x.py"), "w") as f:
            f.write("def x(): pass\n")
        result = cmd_diff_git_aware(tmp_git_repo)
        assert result["impact"] == []


# ─── 8. incremental.find_changed_files git path ─────────────────────


class TestIncrementalGitPath:
    """Verify incremental.find_changed_files uses git when bookmark is set."""

    def test_uses_git_when_bookmark_set(self, tmp_git_repo, db_path):
        from incremental import find_changed_files
        from git_aware import set_last_indexed_sha, get_current_sha
        # Bookmark HEAD, then modify a file.
        set_last_indexed_sha(tmp_git_repo, db_path, get_current_sha(tmp_git_repo))
        with open(os.path.join(tmp_git_repo, "README.md"), "a") as f:
            f.write("\nedit\n")
        # all_files can be empty — git path doesn't need it.
        changed, new, deleted = find_changed_files(
            tmp_git_repo, [], db_path=db_path,
        )
        # changed is absolute paths; README.md must be in there.
        rel_changed = {os.path.relpath(c, tmp_git_repo) for c in changed}
        assert "README.md" in rel_changed
        # git path folds new into changed; new is always [].
        assert new == []

    def test_falls_back_to_mtime_when_no_bookmark(
        self, tmp_git_repo, db_path
    ):
        """When no bookmark is set, the mtime path runs (no last_indexed_sha)."""
        from incremental import find_changed_files, save_mtimes
        # Pre-populate mtimes cache so the mtime path can detect the change.
        readme = os.path.join(tmp_git_repo, "README.md")
        save_mtimes(tmp_git_repo, {"README.md": os.path.getmtime(readme)})
        # Modify the file
        with open(readme, "a") as f:
            f.write("\nedit\n")
        # No bookmark in registry_meta → mtime fallback should run.
        changed, new, deleted = find_changed_files(
            tmp_git_repo, [readme], db_path=db_path,
        )
        assert any(os.path.relpath(c, tmp_git_repo) == "README.md" for c in changed)

    def test_falls_back_to_mtime_outside_git(self, tmp_non_git_dir):
        from incremental import find_changed_files, save_mtimes
        # Outside git → always mtime path.
        fpath = os.path.join(tmp_non_git_dir, "x.py")
        with open(fpath, "w") as f:
            f.write("x = 1\n")
        save_mtimes(tmp_non_git_dir, {"x.py": os.path.getmtime(fpath) + 100})
        changed, new, deleted = find_changed_files(
            tmp_non_git_dir, [fpath], db_path=None,
        )
        assert any(os.path.relpath(c, tmp_non_git_dir) == "x.py" for c in changed)


# ─── 9. End-to-end scan stores the bookmark ─────────────────────────


class TestScanStoresBookmark:
    """Verify scan.py persists last_indexed_sha after a successful scan."""

    def test_scan_writes_bookmark_in_git_repo(self, tmp_git_repo, db_path):
        from commands.scan import cmd_scan
        from git_aware import get_last_indexed_sha, get_current_sha
        # .codelens is gitignored so the scan output doesn't appear as untracked.
        with open(os.path.join(tmp_git_repo, ".gitignore"), "w") as f:
            f.write(".codelens/\n")
        result = cmd_scan(tmp_git_repo, incremental=False)
        assert result["status"] == "ok"
        # Bookmark should now be set to current HEAD.
        bookmarked = get_last_indexed_sha(tmp_git_repo, db_path)
        assert bookmarked == get_current_sha(tmp_git_repo)
        # Scan output also surfaces the bookmark.
        assert result["git"]["last_indexed_sha"] == bookmarked

    def test_scan_no_bookmark_outside_git(self, tmp_non_git_dir):
        from commands.scan import cmd_scan
        result = cmd_scan(tmp_non_git_dir, incremental=False)
        assert result["status"] == "ok"
        # No git → no bookmark.
        assert result["git"]["last_indexed_sha"] is None
        assert result["git"]["last_indexed_branch"] is None
