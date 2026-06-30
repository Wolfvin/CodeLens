"""Tests for the Serena-style markdown memory system (issue #60).

Covers:
- CRUD operations on project memory files (write/read/list/delete)
- Global memory fallback on read
- Global memory is read-only via CLI (write/delete reject it)
- File header is always present and canonical
- ``mem:NAME`` reference extraction + non-blocking validation (warn, not block)
- Name validation rejects invalid topic names
- The CLI ``memory`` command auto-registers and dispatches subcommands
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Make scripts/ importable.
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from memories import memory_manager as mm  # noqa: E402
from commands import COMMAND_REGISTRY  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace():
    """Yield a temporary workspace directory."""
    d = tempfile.mkdtemp(prefix="codelens_memory_test_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fake_home(monkeypatch, tmp_path):
    """Redirect ``~`` to a temp dir so global memories don't touch the real home.

    Returns the path to the fake home directory. Tests that need a global
    memory file should write to ``fake_home / ".codelens" / "memories" / "global"``.
    """
    home = tmp_path / "fake_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # os.path.expanduser caches nothing, but be explicit so any code reading
    # HOME directly also gets the override.
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home) if p == "~" else os.path.expanduser.__wrapped__(p) if hasattr(os.path.expanduser, "__wrapped__") else _expanduser(p, home))
    return home


def _expanduser(path: str, home: Path) -> str:
    """Helper for monkeypatching os.path.expanduser without infinite recursion."""
    if path == "~":
        return str(home)
    if path.startswith("~/"):
        return str(home / path[2:])
    return path


# ─── Name validation ───────────────────────────────────────────────────────


class TestNameValidation:
    """Names must match [A-Za-z][A-Za-z0-9_.-]* — same charset as mem:NAME."""

    @pytest.mark.parametrize(
        "name",
        ["auth", "auth-flow", "auth_flow", "auth.flow", "auth2", "A", "a.b-c_d"],
    )
    def test_valid_names_accepted(self, name):
        mm._validate_name(name)  # should not raise
        # Path helpers should also accept these.
        assert mm.project_memory_path("/ws", name).endswith(f"{name}.md")
        assert mm.global_memory_path(name).endswith(f"{name}.md")

    @pytest.mark.parametrize(
        "name",
        [
            "",            # empty
            "1auth",       # starts with digit
            "-auth",       # starts with hyphen
            ".auth",       # starts with dot
            "_auth",       # starts with underscore
            "auth flow",   # contains space
            "auth/flow",   # contains slash
            "auth:flow",   # contains colon
            "auth$flow",   # contains special char
        ],
    )
    def test_invalid_names_rejected(self, name):
        with pytest.raises(ValueError):
            mm._validate_name(name)

    def test_write_memory_rejects_invalid_name(self, workspace):
        with pytest.raises(ValueError):
            mm.write_memory(workspace, "1invalid", "content")

    def test_read_memory_rejects_invalid_name(self, workspace):
        with pytest.raises(ValueError):
            mm.read_memory(workspace, "1invalid")

    def test_delete_memory_rejects_invalid_name(self, workspace):
        with pytest.raises(ValueError):
            mm.delete_memory(workspace, "1invalid")


# ─── Header handling ───────────────────────────────────────────────────────


class TestHeaderHandling:
    """Every memory file must start with '# Memory: <name>'."""

    def test_write_adds_header_when_missing(self, workspace):
        result = mm.write_memory(workspace, "topic", "Just body text.")
        assert result["status"] == "ok"
        with open(result["path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("# Memory: topic\n")
        assert "Just body text." in content

    def test_write_replaces_existing_header_with_canonical(self, workspace):
        # Even if the user passes content with a different topic in the
        # header, we overwrite with the canonical name.
        result = mm.write_memory(
            workspace, "real-name", "# Memory: wrong-name\n\nbody"
        )
        with open(result["path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("# Memory: real-name\n")
        assert "wrong-name" not in content
        assert "body" in content

    def test_write_preserves_body_when_only_header_given(self, workspace):
        result = mm.write_memory(workspace, "t", "# Memory: t\n\nbody line 1\nbody line 2")
        with open(result["path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert "body line 1" in content
        assert "body line 2" in content

    def test_write_idempotent(self, workspace):
        """Writing the same content twice produces the same file."""
        mm.write_memory(workspace, "t", "body")
        r1 = mm.read_memory(workspace, "t")
        mm.write_memory(workspace, "t", "body")
        r2 = mm.read_memory(workspace, "t")
        assert r1["content"] == r2["content"]
        assert r1["size_bytes"] == r2["size_bytes"]

    def test_has_valid_header(self):
        assert mm.has_valid_header("# Memory: foo\n\nbody")
        assert mm.has_valid_header("  # Memory: foo\nbody")
        assert not mm.has_valid_header("No header here")
        assert not mm.has_valid_header("")
        assert not mm.has_valid_header("# Memory:\n")  # missing topic

    def test_parse_header_topic(self):
        assert mm.parse_header_topic("# Memory: auth-flow") == "auth-flow"
        assert mm.parse_header_topic("  # Memory:   spaced  ") == "spaced"
        assert mm.parse_header_topic("not a header") is None
        assert mm.parse_header_topic("") is None


# ─── Write / Read / List / Delete ─────────────────────────────────────────


class TestWriteReadListDelete:
    """Core CRUD lifecycle on project memory files."""

    def test_write_creates_file_in_project_scope(self, workspace):
        result = mm.write_memory(workspace, "auth", "Uses JWT.")
        assert result["status"] == "ok"
        assert result["action"] == "written"
        assert result["scope"] == "project"
        assert result["name"] == "auth"
        assert result["path"] == os.path.join(
            workspace, ".codelens", "memories", "auth.md"
        )
        assert os.path.isfile(result["path"])
        assert result["size_bytes"] > 0

    def test_write_creates_memories_dir(self, workspace):
        memories_dir = os.path.join(workspace, ".codelens", "memories")
        assert not os.path.exists(memories_dir)
        mm.write_memory(workspace, "first", "content")
        assert os.path.isdir(memories_dir)

    def test_write_updates_existing_file(self, workspace):
        mm.write_memory(workspace, "topic", "v1")
        r1 = mm.read_memory(workspace, "topic")
        mm.write_memory(workspace, "topic", "v2 different content")
        r2 = mm.read_memory(workspace, "topic")
        assert r1["content"] != r2["content"]
        assert "v2" in r2["content"]

    def test_read_returns_project_memory(self, workspace):
        mm.write_memory(workspace, "topic", "Hello world")
        result = mm.read_memory(workspace, "topic")
        assert result["status"] == "ok"
        assert result["scope"] == "project"
        assert result["name"] == "topic"
        assert "Hello world" in result["content"]
        assert result["has_valid_header"] is True
        assert result["header_topic"] == "topic"

    def test_read_returns_not_found_when_missing(self, workspace, fake_home):
        result = mm.read_memory(workspace, "nonexistent")
        assert result["status"] == "not_found"
        assert "nonexistent" in result["message"]

    def test_read_falls_back_to_global(self, workspace, fake_home):
        # Drop a global memory file directly (the only way to create one —
        # write_memory only writes to project scope).
        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "global-topic.md").write_text(
            "# Memory: global-topic\n\nGlobal content.\n", encoding="utf-8"
        )

        result = mm.read_memory(workspace, "global-topic")
        assert result["status"] == "ok"
        assert result["scope"] == "global"
        assert "Global content." in result["content"]

    def test_read_prefers_project_over_global(self, workspace, fake_home):
        # Both scopes have a memory with the same name.
        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "shared.md").write_text(
            "# Memory: shared\n\nGlobal version.\n", encoding="utf-8"
        )
        mm.write_memory(workspace, "shared", "Project version.")

        result = mm.read_memory(workspace, "shared")
        assert result["status"] == "ok"
        assert result["scope"] == "project"
        assert "Project version." in result["content"]

    def test_list_empty_when_no_memories(self, workspace, fake_home):
        result = mm.list_memories(workspace)
        assert result["status"] == "ok"
        assert result["total"] == 0
        assert result["project_count"] == 0
        assert result["global_count"] == 0
        assert result["memories"] == []

    def test_list_returns_project_and_global(self, workspace, fake_home):
        mm.write_memory(workspace, "p1", "project 1")
        mm.write_memory(workspace, "p2", "project 2")

        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "g1.md").write_text("# Memory: g1\n\nglobal 1\n", encoding="utf-8")

        result = mm.list_memories(workspace)
        assert result["status"] == "ok"
        assert result["project_count"] == 2
        assert result["global_count"] == 1
        assert result["total"] == 3

        names = {m["name"] for m in result["memories"]}
        assert names == {"p1", "p2", "g1"}

        # Each entry has the expected metadata.
        for m in result["memories"]:
            assert m["scope"] in ("project", "global")
            assert m["path"]
            assert m["size_bytes"] > 0
            assert m["modified_at"]
            assert m["has_valid_header"] is True
            assert m["header_topic"] == m["name"]

    def test_list_dedupes_with_project_taking_precedence(self, workspace, fake_home):
        """A project memory shadows a global memory of the same name."""
        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "shared.md").write_text(
            "# Memory: shared\n\nglobal\n", encoding="utf-8"
        )
        mm.write_memory(workspace, "shared", "project")

        result = mm.list_memories(workspace)
        assert result["total"] == 1
        assert len(result["memories"]) == 1
        assert result["memories"][0]["scope"] == "project"
        # The global list still shows the global entry.
        assert result["global_count"] == 1
        assert result["project_count"] == 1

    def test_delete_removes_project_memory(self, workspace):
        mm.write_memory(workspace, "topic", "content")
        path = os.path.join(workspace, ".codelens", "memories", "topic.md")
        assert os.path.isfile(path)

        result = mm.delete_memory(workspace, "topic")
        assert result["status"] == "ok"
        assert result["action"] == "deleted"
        assert result["scope"] == "project"
        assert not os.path.exists(path)

    def test_delete_returns_not_found_for_missing_project(self, workspace):
        result = mm.delete_memory(workspace, "never-existed")
        assert result["status"] == "not_found"
        assert "Global memories are read-only" in result["message"]

    def test_delete_cannot_delete_global(self, workspace, fake_home):
        """Global memories are read-only via CLI — delete must refuse."""
        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        global_path = global_dir / "global-only.md"
        global_path.write_text("# Memory: global-only\n\nbody\n", encoding="utf-8")

        # No project memory of the same name → not_found, file untouched.
        result = mm.delete_memory(workspace, "global-only")
        assert result["status"] == "not_found"
        assert global_path.exists()  # global file is untouched


# ─── Reference validation (warn, don't block) ─────────────────────────────


class TestReferenceValidation:
    """``mem:NAME`` references are validated on write; missing refs warn."""

    def test_extract_references_finds_all(self):
        content = "See mem:auth and mem:tokens. Also mem:auth again."
        refs = mm.extract_references(content)
        # Deduplicated, order preserved.
        assert refs == ["auth", "tokens"]

    def test_extract_references_ignores_non_matches(self):
        # 'notmem:foo' should not match (leading word char before 'mem:').
        # 'mem:' alone has no name. 'mem:1foo' starts with digit, not allowed.
        content = "notmem:foo mem: mem:1foo mem:valid"
        refs = mm.extract_references(content)
        assert refs == ["valid"]

    def test_extract_references_handles_special_chars_in_name(self):
        content = "See mem:auth-flow, mem:tokens_v2, and mem:cache.hit"
        refs = mm.extract_references(content)
        assert "auth-flow" in refs
        assert "tokens_v2" in refs
        assert "cache.hit" in refs

    def test_extract_references_empty_content(self):
        assert mm.extract_references("") == []
        assert mm.extract_references("no refs here") == []

    def test_validate_references_no_missing(self, workspace):
        mm.write_memory(workspace, "target", "target body")
        result = mm.validate_references(workspace, "see mem:target")
        assert result["references"] == ["target"]
        assert result["missing"] == []
        assert result["warnings"] == []

    def test_validate_references_reports_missing(self, workspace):
        result = mm.validate_references(workspace, "see mem:nonexistent")
        assert result["missing"] == ["nonexistent"]
        assert "Reference 'mem:nonexistent' does not exist" in result["warnings"][0]

    def test_validate_references_exclude_self(self, workspace):
        """When writing memory 'foo', a mem:foo self-reference is not flagged."""
        result = mm.validate_references(
            workspace, "self-ref mem:foo and missing mem:bar", exclude="foo"
        )
        assert "foo" in result["references"]
        assert result["missing"] == ["bar"]  # foo excluded

    def test_write_with_missing_reference_succeeds_with_warning(self, workspace):
        """Issue #60: warn, don't block. The write must succeed."""
        result = mm.write_memory(
            workspace, "login", "Login uses mem:auth-flow and mem:missing-topic."
        )
        assert result["status"] == "ok"
        assert result["action"] == "written"
        # auth-flow doesn't exist either → both missing
        assert "auth-flow" in result["missing_references"]
        assert "missing-topic" in result["missing_references"]
        assert any("auth-flow" in w for w in result["warnings"])
        assert any("missing-topic" in w for w in result["warnings"])
        # File was still written.
        assert os.path.isfile(result["path"])

    def test_write_with_existing_reference_no_warning(self, workspace):
        """When all references exist, no warnings are emitted."""
        mm.write_memory(workspace, "auth", "auth body")
        mm.write_memory(workspace, "tokens", "tokens body")
        result = mm.write_memory(
            workspace, "login", "Login uses mem:auth and mem:tokens."
        )
        assert result["status"] == "ok"
        assert "missing_references" not in result
        assert "warnings" not in result
        assert set(result["references"]) == {"auth", "tokens"}

    def test_write_with_self_reference_no_warning(self, workspace):
        """A memory that references itself doesn't warn."""
        result = mm.write_memory(
            workspace, "recursive", "see mem:recursive for details"
        )
        assert result["status"] == "ok"
        assert "recursive" in result["references"]
        assert "missing_references" not in result

    def test_read_includes_references(self, workspace):
        mm.write_memory(workspace, "topic", "see mem:other")
        result = mm.read_memory(workspace, "topic")
        assert result["references"] == ["other"]

    def test_validate_references_falls_back_to_global(self, workspace, fake_home):
        """A reference to a global memory should not be flagged missing."""
        global_dir = fake_home / ".codelens" / "memories" / "global"
        global_dir.mkdir(parents=True)
        (global_dir / "global-topic.md").write_text(
            "# Memory: global-topic\n\nbody\n", encoding="utf-8"
        )
        result = mm.validate_references(workspace, "see mem:global-topic")
        assert result["missing"] == []
        assert result["warnings"] == []


# ─── Path helpers ─────────────────────────────────────────────────────────


class TestPathHelpers:
    """Path helpers return deterministic, validated paths."""

    def test_project_memory_dir(self, workspace):
        assert mm.project_memory_dir(workspace) == os.path.join(
            workspace, ".codelens", "memories"
        )

    def test_global_memory_dir_uses_home(self, fake_home):
        assert mm.global_memory_dir() == str(
            fake_home / ".codelens" / "memories" / "global"
        )

    def test_project_memory_path_validates_name(self):
        with pytest.raises(ValueError):
            mm.project_memory_path("/ws", "1invalid")

    def test_global_memory_path_validates_name(self):
        with pytest.raises(ValueError):
            mm.global_memory_path("1invalid")


# ─── CLI command registration & dispatch ──────────────────────────────────


class TestCommandRegistration:
    """The ``memory`` command must auto-register via register_command()."""

    def test_memory_command_registered(self):
        assert "memory" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["memory"]
        assert "Serena-style" in info["help"]
        assert callable(info["add_args"])
        assert callable(info["execute"])

    def test_command_registered_with_canonical_name(self):
        """The execute function must belong to commands.memory module.

        This guards against the test_every_command_module_registers test in
        test_command_registry.py — each commands/*.py must register at least
        one command, and the registration must come from that module.
        """
        info = COMMAND_REGISTRY["memory"]
        assert info["execute"].__module__ == "commands.memory"


class TestCommandDispatch:
    """End-to-end dispatch through the registered ``execute`` callback."""

    def _parse_and_run(self, subcommand_args, workspace):
        """Build an argparse namespace the way codelens.py does and dispatch."""
        import argparse
        from commands.memory import add_args, execute

        parser = argparse.ArgumentParser(prog="codelens memory")
        add_args(parser)
        # The framework adds --format etc. to subparsers; we don't need them
        # for these tests since execute() doesn't read them.
        args = parser.parse_args(subcommand_args)
        return execute(args, workspace)

    def test_no_action_returns_error(self, workspace):
        result = self._parse_and_run([], workspace)
        assert result["status"] == "error"
        assert "No memory action" in result["error"]

    def test_write_via_dispatch(self, workspace):
        result = self._parse_and_run(
            ["write", "topic", "body content"], workspace
        )
        assert result["status"] == "ok"
        assert result["scope"] == "project"

    def test_read_via_dispatch(self, workspace):
        self._parse_and_run(["write", "topic", "body content"], workspace)
        result = self._parse_and_run(["read", "topic"], workspace)
        assert result["status"] == "ok"
        assert "body content" in result["content"]

    def test_list_via_dispatch(self, workspace):
        self._parse_and_run(["write", "a", "alpha"], workspace)
        self._parse_and_run(["write", "b", "beta"], workspace)
        result = self._parse_and_run(["list"], workspace)
        assert result["status"] == "ok"
        assert result["total"] == 2

    def test_delete_via_dispatch(self, workspace):
        self._parse_and_run(["write", "topic", "body"], workspace)
        result = self._parse_and_run(["delete", "topic"], workspace)
        assert result["status"] == "ok"
        assert result["action"] == "deleted"

    def test_unknown_action_returns_error(self, workspace):
        # Argparse will reject unknown subcommands before execute() is called,
        # but if memory_action is somehow None or unknown we should still
        # return a structured error rather than crashing.
        result = self._parse_and_run([], workspace)
        assert result["status"] == "error"


# ─── CLI subprocess smoke test ────────────────────────────────────────────


class TestCLISubprocess:
    """Smoke-test the memory command end-to-end through codelens.py."""

    def test_memory_command_runs_via_cli(self, workspace):
        """`codelens memory write ...` end-to-end through codelens.py."""
        import subprocess
        import json

        # Drop a project marker so the auto-detector finds this temp dir
        # rather than walking up to the real CodeLens checkout. We also
        # redirect HOME so the last-workspace cache (~/.codelens/...) doesn't
        # leak across tests / pollute the developer's real home dir.
        (Path(workspace) / "pyproject.toml").write_text(
            "[project]\nname = 'test-ws'\nversion = '0'\n", encoding="utf-8"
        )
        fake_home = Path(workspace) / "fake_home"
        fake_home.mkdir()

        env = {
            **os.environ,
            "PYTHONPATH": SCRIPT_DIR,
            "PYTHONUTF8": "1",
            "HOME": str(fake_home),
        }
        codelens = os.path.join(SCRIPT_DIR, "codelens.py")

        # write
        r = subprocess.run(
            [sys.executable, codelens, "memory", "write", "topic", "body text"],
            capture_output=True, text=True, env=env, cwd=workspace, timeout=30,
        )
        assert r.returncode == 0, f"write failed: {r.stderr[:300]}"

        # The output should be JSON (after any [CodeLens] stderr lines).
        stdout_lines = [
            line for line in r.stdout.splitlines()
            if not line.startswith("[CodeLens]")
        ]
        data = json.loads("\n".join(stdout_lines))
        assert data["status"] == "ok"
        # File must have landed inside the temp workspace, not somewhere else.
        assert data["path"].startswith(workspace), (
            f"memory file written outside temp workspace: {data['path']}"
        )
        assert os.path.isfile(data["path"])

    def test_memory_no_action_via_cli(self):
        """`codelens memory` with no action returns a structured error."""
        import subprocess
        import json

        env = {
            **os.environ,
            "PYTHONPATH": SCRIPT_DIR,
            "PYTHONUTF8": "1",
        }
        codelens = os.path.join(SCRIPT_DIR, "codelens.py")
        r = subprocess.run(
            [sys.executable, codelens, "memory"],
            capture_output=True, text=True, env=env, timeout=30,
        )
        assert r.returncode == 0
        stdout_lines = [
            line for line in r.stdout.splitlines()
            if not line.startswith("[CodeLens]")
        ]
        data = json.loads("\n".join(stdout_lines))
        assert data["status"] == "error"
        assert "No memory action" in data["error"]
