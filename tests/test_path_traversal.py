"""Tests for path traversal protection (issue #58, Phase 1).

Covers:

* :class:`scripts.security.path_traversal.PathRefusalError`
* :func:`scripts.security.path_traversal.is_path_within_project`
* :func:`scripts.security.path_traversal.resolve_path_within_project`
* :func:`scripts.security.path_traversal.safe_resolve_path`
* :func:`utils.safe_read_file_within_project` integration

Test strategy:

* Real filesystem fixtures (``tmp_path``) — no mocking of ``os.path``
  or ``os.symlink``, because the whole point of Phase 1 is that
  ``realpath`` correctly defeats symlink-based escapes.
* Both Linux-style and Windows-style path separators where the
  behavior is platform-sensitive (skipped on non-relevant platforms).
* Boundary cases: path == project_root, path immediately under root,
  path with trailing slash, path with ``..`` that resolves back
  inside the project.
* Negative cases: absolute escape, relative traversal escape, symlink
  escape, sibling-directory prefix collision (``/home/proj-evil`` vs
  ``/home/proj``).
"""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap

import pytest

# Add scripts dir to sys.path so we can import the security package.
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from security.path_traversal import (  # noqa: E402
    PathRefusalError,
    is_path_within_project,
    resolve_path_within_project,
    safe_resolve_path,
)
from utils import safe_read_file_within_project  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def project_tree(tmp_path):
    """Build a small project tree with a few files and one inside-symlink.

    Layout::

        <tmp>/proj/
            src/
                app.py
                utils.py
            inside_link -> src/app.py      (symlink, stays in project)
            outside_link -> /etc/hostname  (symlink, escapes project)
    """
    proj = tmp_path / "proj"
    src = proj / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (src / "utils.py").write_text("def x(): pass\n", encoding="utf-8")

    # Symlink creation requires SeCreateSymbolicLinkPrivilege on Windows
    # (Administrator or Developer Mode enabled) — it raises OSError
    # WinError 1314 otherwise. Without this guard, every one of the ~26
    # tests in this file errors out at fixture setup (even tests that
    # don't test symlink behavior at all), since they all depend on this
    # shared fixture. Fall back to a plain file so non-symlink-specific
    # tests still run; symlink-specific tests check `symlinks_supported`
    # and skip themselves individually.
    symlinks_supported = True

    # Inside symlink: points to a file inside the project.
    inside = proj / "inside_link"
    try:
        inside.symlink_to(src / "app.py")
    except OSError:
        symlinks_supported = False
        inside.write_text("print('hi')\n", encoding="utf-8")

    # Outside symlink: points to a system file outside the project.
    # /etc/hostname exists on virtually every POSIX system; if not,
    # we point to /tmp which definitely exists.
    target = "/etc/hostname"
    if not os.path.exists(target):
        target = tempfile.gettempdir()
    outside = proj / "outside_link"
    try:
        outside.symlink_to(target)
    except OSError:
        symlinks_supported = False
        outside.write_text("placeholder\n", encoding="utf-8")

    return {
        "root": str(proj),
        "src_app": str(src / "app.py"),
        "inside_link": str(inside),
        "outside_link": str(outside),
        "symlinks_supported": symlinks_supported,
    }


# ─── is_path_within_project ────────────────────────────────────


class TestIsPathWithinProject:
    """Boolean pre-flight check."""

    def test_path_inside_project(self, project_tree):
        assert is_path_within_project(project_tree["root"], project_tree["src_app"]) is True

    def test_path_is_project_root_itself(self, project_tree):
        assert is_path_within_project(project_tree["root"], project_tree["root"]) is True

    def test_relative_path_inside(self, project_tree):
        # cwd-independent check: pass an absolute project_root and a
        # relative path that, when resolved against cwd, does NOT
        # land inside. We can't easily control cwd here, so instead
        # test the absolute variant.
        assert is_path_within_project(
            project_tree["root"],
            os.path.join(project_tree["root"], "src", "app.py"),
        ) is True

    def test_dotdot_that_stays_inside(self, project_tree):
        # src/../src/app.py lexically resolves to src/app.py — still inside.
        candidate = os.path.join(project_tree["root"], "src", "..", "src", "app.py")
        assert is_path_within_project(project_tree["root"], candidate) is True

    def test_dotdot_escape(self, project_tree, tmp_path):
        # proj/../other should resolve to <tmp>/other — outside proj.
        candidate = os.path.join(project_tree["root"], "..", "other")
        assert is_path_within_project(project_tree["root"], candidate) is False

    def test_absolute_path_outside(self, project_tree, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        assert is_path_within_project(project_tree["root"], str(other)) is False

    def test_sibling_prefix_collision(self, tmp_path):
        """``/tmp/proj-evil`` must NOT match ``/tmp/proj`` as a prefix.

        This is the core reason ``_normalize_project_root`` appends
        ``os.sep`` — naive ``startswith`` would let ``proj-evil``
        slip through.
        """
        proj = tmp_path / "proj"
        proj.mkdir()
        (tmp_path / "proj-evil").mkdir()
        candidate = str(tmp_path / "proj-evil" / "secret.txt")
        assert is_path_within_project(str(proj), candidate) is False

    def test_symlink_inside_project(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        # The realpath of inside_link is src/app.py, which IS inside.
        assert is_path_within_project(project_tree["root"], project_tree["inside_link"]) is True

    def test_symlink_escape(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        # The realpath of outside_link is /etc/hostname (or /tmp), which
        # is NOT inside the project.
        assert is_path_within_project(project_tree["root"], project_tree["outside_link"]) is False

    def test_empty_path_returns_false(self, project_tree):
        assert is_path_within_project(project_tree["root"], "") is False

    def test_empty_project_root_returns_false(self, project_tree):
        assert is_path_within_project("", project_tree["src_app"]) is False

    def test_non_existent_path_inside(self, project_tree):
        # A path that doesn't exist but lexically resolves inside the
        # project is fine — we're checking the resolved location, not
        # existence. This matters for pre-flight "should I even try?"
        # checks.
        candidate = os.path.join(project_tree["root"], "src", "does_not_exist.py")
        assert is_path_within_project(project_tree["root"], candidate) is True

    def test_non_existent_path_outside(self, project_tree):
        candidate = os.path.join(project_tree["root"], "..", "does_not_exist.py")
        assert is_path_within_project(project_tree["root"], candidate) is False


# ─── resolve_path_within_project ───────────────────────────────


class TestResolvePathWithinProject:
    """Throwing variant — returns realpath on success, raises on escape."""

    def test_returns_realpath_for_inside_path(self, project_tree):
        result = resolve_path_within_project(project_tree["root"], project_tree["src_app"])
        # realpath should equal the canonical absolute path of src/app.py
        assert result == os.path.realpath(project_tree["src_app"])
        assert os.path.isfile(result)

    def test_returns_realpath_for_symlink_inside(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        result = resolve_path_within_project(project_tree["root"], project_tree["inside_link"])
        # The symlink is resolved to its target — which is inside the project.
        assert result == os.path.realpath(project_tree["src_app"])

    def test_raises_for_symlink_escape(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        with pytest.raises(PathRefusalError) as exc_info:
            resolve_path_within_project(project_tree["root"], project_tree["outside_link"])
        err = exc_info.value
        # The error message must be actionable — include the requested
        # path, the resolved target, and the project root.
        assert project_tree["outside_link"] in str(err)
        assert project_tree["root"] in str(err)
        # The resolved_path attribute should point at the escape target.
        assert err.resolved_path is not None
        assert err.resolved_path == os.path.realpath(project_tree["outside_link"])

    def test_raises_for_dotdot_escape(self, project_tree, tmp_path):
        candidate = os.path.join(project_tree["root"], "..", "other")
        with pytest.raises(PathRefusalError):
            resolve_path_within_project(project_tree["root"], candidate)

    def test_raises_for_absolute_outside(self, project_tree, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        with pytest.raises(PathRefusalError):
            resolve_path_within_project(project_tree["root"], str(other))

    def test_raises_for_empty_path(self, project_tree):
        with pytest.raises(PathRefusalError):
            resolve_path_within_project(project_tree["root"], "")

    def test_raises_value_error_for_empty_project_root(self, project_tree):
        with pytest.raises(ValueError):
            resolve_path_within_project("", project_tree["src_app"])

    def test_project_root_itself_returns_root(self, project_tree):
        result = resolve_path_within_project(project_tree["root"], project_tree["root"])
        assert result == os.path.realpath(project_tree["root"])

    def test_pathrefusalerror_is_permission_error_subclass(self, project_tree):
        """``PathRefusalError`` must be catchable as ``PermissionError``
        and ``OSError`` so existing error handlers in callers continue
        to work without modification.
        """
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        try:
            resolve_path_within_project(project_tree["root"], project_tree["outside_link"])
        except PathRefusalError as exc:
            assert isinstance(exc, PermissionError)
            assert isinstance(exc, OSError)
        else:
            pytest.fail("PathRefusalError was not raised")


# ─── safe_resolve_path ─────────────────────────────────────────


class TestSafeResolvePath:
    """Non-throwing variant — returns Optional[str]."""

    def test_returns_realpath_on_success(self, project_tree):
        result = safe_resolve_path(project_tree["root"], project_tree["src_app"])
        assert result == os.path.realpath(project_tree["src_app"])

    def test_returns_none_on_refusal(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        result = safe_resolve_path(project_tree["root"], project_tree["outside_link"])
        assert result is None

    def test_returns_none_on_empty_path(self, project_tree):
        assert safe_resolve_path(project_tree["root"], "") is None


# ─── utils.safe_read_file_within_project integration ───────────


class TestSafeReadFileWithinProject:
    """End-to-end: refusing paths return None instead of file content."""

    def test_reads_file_inside_project(self, project_tree):
        content = safe_read_file_within_project(project_tree["src_app"], project_tree["root"])
        assert content is not None
        assert "print('hi')" in content

    def test_returns_none_for_symlink_escape(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        # The symlink target is /etc/hostname (or /tmp) — readable by
        # the OS, but our security boundary must refuse it regardless
        # of OS permissions.
        content = safe_read_file_within_project(project_tree["outside_link"], project_tree["root"])
        assert content is None

    def test_returns_none_for_dotdot_escape(self, project_tree, tmp_path):
        # Build a real file outside the project that would be readable
        # if not for the path check.
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("SECRET", encoding="utf-8")
        candidate = os.path.join(project_tree["root"], "..", "outside.txt")
        content = safe_read_file_within_project(candidate, project_tree["root"])
        assert content is None

    def test_reads_file_via_inside_symlink(self, project_tree):
        # Symlink that stays inside the project should be followed
        # transparently — the realpath is src/app.py, which is inside.
        content = safe_read_file_within_project(project_tree["inside_link"], project_tree["root"])
        assert content is not None
        assert "print('hi')" in content

    def test_returns_none_for_nonexistent_inside_path(self, project_tree):
        # Path that doesn't exist but stays inside the project —
        # refusal layer passes, then safe_read_file returns None
        # because the file doesn't exist. No exception.
        candidate = os.path.join(project_tree["root"], "src", "nope.py")
        content = safe_read_file_within_project(candidate, project_tree["root"])
        assert content is None


# ─── MCP-side path validation integration ──────────────────────


class TestMcpPathValidation:
    """Verify the MCP server's ``_validate_path_args`` helper.

    This is the agent-facing enforcement point — any MCP tool call
    that includes a ``file`` / ``path`` / ``file_path`` argument is
    checked before the underlying command is dispatched.
    """

    def _make_server(self):
        # Import lazily so test collection doesn't fail if MCP
        # dependencies change shape.
        from mcp_server import MCPServer
        return MCPServer()

    def test_safe_file_arg_passes(self, project_tree):
        srv = self._make_server()
        args = {"file": os.path.join(project_tree["root"], "src", "app.py")}
        assert srv._validate_path_args(args, project_tree["root"]) is None

    def test_relative_file_arg_resolved_against_workspace(self, project_tree):
        srv = self._make_server()
        # A relative path is resolved against the workspace before
        # checking — this is the desired behavior (commands do the
        # same). So "src/app.py" relative to workspace should pass.
        args = {"file": "src/app.py"}
        assert srv._validate_path_args(args, project_tree["root"]) is None

    def test_dotdot_escape_returns_structured_error(self, project_tree):
        srv = self._make_server()
        args = {"file": "../../../etc/passwd"}
        result = srv._validate_path_args(args, project_tree["root"])
        assert result is not None
        assert result["status"] == "error"
        assert result["error"] == "path_refusal"
        assert result["argument"] == "file"
        assert "suggestion" in result

    def test_symlink_escape_returns_structured_error(self, project_tree):
        if not project_tree["symlinks_supported"]:
            pytest.skip("symlink creation requires elevated privilege on this platform")
        srv = self._make_server()
        args = {"file": project_tree["outside_link"]}
        result = srv._validate_path_args(args, project_tree["root"])
        assert result is not None
        assert result["status"] == "error"
        assert result["error"] == "path_refusal"

    def test_absolute_outside_path_refused(self, project_tree, tmp_path):
        srv = self._make_server()
        other = tmp_path / "other"
        other.mkdir()
        args = {"file": str(other / "x.py")}
        result = srv._validate_path_args(args, project_tree["root"])
        assert result is not None
        assert result["error"] == "path_refusal"

    def test_path_arg_also_validated(self, project_tree):
        srv = self._make_server()
        args = {"path": "../../../etc/passwd"}
        result = srv._validate_path_args(args, project_tree["root"])
        assert result is not None
        assert result["argument"] == "path"

    def test_file_path_arg_also_validated(self, project_tree):
        srv = self._make_server()
        args = {"file_path": "../../../etc/passwd"}
        result = srv._validate_path_args(args, project_tree["root"])
        assert result is not None
        assert result["argument"] == "file_path"

    def test_no_path_args_returns_none(self, project_tree):
        srv = self._make_server()
        # A query call with no file/path arg should not be blocked.
        args = {"name": "my_func"}
        assert srv._validate_path_args(args, project_tree["root"]) is None

    def test_empty_workspace_returns_none(self, project_tree):
        srv = self._make_server()
        # If the MCP server couldn't resolve a workspace, we don't
        # block — commands will produce their own "workspace not
        # found" error. Path validation is a security layer, not a
        # workspace-resolution layer.
        args = {"file": "/etc/passwd"}
        assert srv._validate_path_args(args, "") is None

    def test_non_string_arg_ignored(self, project_tree):
        srv = self._make_server()
        # Defensive: a malformed MCP call with a non-string file arg
        # should be ignored by the validator (the command will
        # produce its own type error downstream).
        args = {"file": 12345}
        assert srv._validate_path_args(args, project_tree["root"]) is None

    def test_empty_string_arg_ignored(self, project_tree):
        srv = self._make_server()
        args = {"file": ""}
        assert srv._validate_path_args(args, project_tree["root"]) is None
