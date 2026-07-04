"""Tests for the Architecture Decision Records (ADR) system (issue #16).

Covers:
- ``adr_engine`` SQLite-backed CRUD: create / list / get / update / deprecate / delete
- Status validation (proposed/accepted/deprecated/rejected)
- Supersession linking (deprecate with --superseded-by)
- Referential integrity (self-supersession forbidden, missing replacement rejected)
- Soft-fail on missing ids (``not_found`` results, not exceptions)
- The CLI ``adr`` command auto-registers and dispatches subcommands
- The MCP ``manage-adr`` tool is statically defined in ``_TOOL_DEFINITIONS``
- File header (@WHO/@WHAT/@PART/@ENTRY) is present
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

# Make scripts/ importable.
SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from adr_engine import (  # noqa: E402
    manage_adr,
    create_adr,
    list_adrs,
    get_adr,
    update_adr,
    deprecate_adr,
    delete_adr,
    adr_db_path,
    _VALID_STATUSES,
)
from commands import COMMAND_REGISTRY  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def workspace():
    """Yield a temporary workspace directory."""
    d = tempfile.mkdtemp(prefix="codelens_adr_test_")
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ─── Path / constants ──────────────────────────────────────────────────────


class TestPathAndConstants:
    """Sanity-checks for path helpers and module constants."""

    def test_adr_db_path_under_codelens_dir(self, workspace):
        p = adr_db_path(workspace)
        assert p.endswith(os.path.join(".codelens", "adrs.db"))
        assert os.path.isabs(p)

    def test_valid_statuses_set(self):
        assert _VALID_STATUSES == {"proposed", "accepted", "deprecated", "rejected"}


# ─── create_adr ────────────────────────────────────────────────────────────


class TestCreateAdr:
    """``create_adr`` inserts a record and returns it with an assigned id."""

    def test_create_returns_record_with_id(self, workspace):
        r = create_adr(workspace, title="Use SQLite over PostgreSQL")
        assert r["status"] == "ok"
        assert r["action"] == "created"
        adr = r["adr"]
        assert adr["id"] >= 1
        assert adr["title"] == "Use SQLite over PostgreSQL"
        assert adr["context"] == ""
        assert adr["decision"] == ""
        assert adr["status"] == "proposed"  # default
        assert adr["superseded_by"] is None
        assert adr["created_at"] == adr["updated_at"]

    def test_create_with_all_fields(self, workspace):
        r = create_adr(
            workspace,
            title="Use WAL mode",
            context="Single-node deployment",
            decision="Enable WAL for concurrent reads",
            status="accepted",
        )
        adr = r["adr"]
        assert adr["context"] == "Single-node deployment"
        assert adr["decision"] == "Enable WAL for concurrent reads"
        assert adr["status"] == "accepted"

    def test_create_strips_title_whitespace(self, workspace):
        r = create_adr(workspace, title="  Padded title  ")
        assert r["adr"]["title"] == "Padded title"

    def test_create_rejects_empty_title(self, workspace):
        with pytest.raises(ValueError, match="title cannot be empty"):
            create_adr(workspace, title="")
        with pytest.raises(ValueError, match="title cannot be empty"):
            create_adr(workspace, title="   ")

    def test_create_rejects_invalid_status(self, workspace):
        with pytest.raises(ValueError, match="Invalid ADR status"):
            create_adr(workspace, title="x", status="bogus")

    def test_create_assigns_sequential_ids(self, workspace):
        r1 = create_adr(workspace, title="First")
        r2 = create_adr(workspace, title="Second")
        r3 = create_adr(workspace, title="Third")
        assert r2["adr"]["id"] == r1["adr"]["id"] + 1
        assert r3["adr"]["id"] == r2["adr"]["id"] + 1

    def test_create_persists_to_sqlite_file(self, workspace):
        create_adr(workspace, title="Persisted")
        assert os.path.isfile(adr_db_path(workspace))


# ─── list_adrs ─────────────────────────────────────────────────────────────


class TestListAdrs:
    """``list_adrs`` returns all ADRs, optionally filtered by status."""

    def test_list_empty_workspace(self, workspace):
        r = list_adrs(workspace)
        assert r["status"] == "ok"
        assert r["total"] == 0
        assert r["filtered"] == 0
        assert r["adrs"] == []
        assert r["filter"] is None

    def test_list_returns_all_sorted_by_id(self, workspace):
        create_adr(workspace, title="C")
        create_adr(workspace, title="A")
        create_adr(workspace, title="B")
        r = list_adrs(workspace)
        assert r["total"] == 3
        assert r["filtered"] == 3
        titles = [a["title"] for a in r["adrs"]]
        # Sorted by id (insertion order), not alphabetical
        assert titles == ["C", "A", "B"]

    def test_list_filter_by_status(self, workspace):
        create_adr(workspace, title="P1", status="proposed")
        create_adr(workspace, title="A1", status="accepted")
        create_adr(workspace, title="P2", status="proposed")
        create_adr(workspace, title="D1", status="deprecated")

        r = list_adrs(workspace, status_filter="accepted")
        assert r["filter"] == "accepted"
        assert r["total"] == 4  # total still counts all
        assert r["filtered"] == 1
        assert r["adrs"][0]["title"] == "A1"

    def test_list_filter_rejects_invalid_status(self, workspace):
        with pytest.raises(ValueError, match="Invalid ADR status"):
            list_adrs(workspace, status_filter="bogus")


# ─── get_adr ───────────────────────────────────────────────────────────────


class TestGetAdr:
    """``get_adr`` returns a single record or ``not_found``."""

    def test_get_existing(self, workspace):
        created = create_adr(workspace, title="Find me")
        rid = created["adr"]["id"]
        r = get_adr(workspace, rid)
        assert r["status"] == "ok"
        assert r["action"] == "get"
        assert r["adr"]["id"] == rid
        assert r["adr"]["title"] == "Find me"

    def test_get_missing_returns_not_found(self, workspace):
        r = get_adr(workspace, 9999)
        assert r["status"] == "not_found"
        assert r["id"] == 9999
        assert "not found" in r["message"].lower()

    def test_get_rejects_non_integer_id(self, workspace):
        with pytest.raises(ValueError, match="must be an integer"):
            get_adr(workspace, "not-an-int")

    def test_get_rejects_non_positive_id(self, workspace):
        with pytest.raises(ValueError, match="must be >= 1"):
            get_adr(workspace, 0)
        with pytest.raises(ValueError, match="must be >= 1"):
            get_adr(workspace, -5)


# ─── update_adr ────────────────────────────────────────────────────────────


class TestUpdateAdr:
    """``update_adr`` patches fields and refreshes ``updated_at``."""

    def test_update_single_field(self, workspace):
        created = create_adr(workspace, title="Original")
        rid = created["adr"]["id"]
        original_updated = created["adr"]["updated_at"]

        r = update_adr(workspace, rid, decision="New decision")
        assert r["status"] == "ok"
        assert r["action"] == "updated"
        assert r["adr"]["decision"] == "New decision"
        assert r["adr"]["title"] == "Original"  # unchanged
        # updated_at must have moved forward (or stayed equal if same ms)
        assert r["adr"]["updated_at"] >= original_updated

    def test_update_multiple_fields(self, workspace):
        created = create_adr(workspace, title="Orig", status="proposed")
        rid = created["adr"]["id"]
        r = update_adr(
            workspace, rid,
            title="New title",
            context="New context",
            decision="New decision",
            status="accepted",
        )
        adr = r["adr"]
        assert adr["title"] == "New title"
        assert adr["context"] == "New context"
        assert adr["decision"] == "New decision"
        assert adr["status"] == "accepted"

    def test_update_with_no_fields_returns_current_record(self, workspace):
        created = create_adr(workspace, title="Untouched")
        rid = created["adr"]["id"]
        r = update_adr(workspace, rid)
        # Falls through to get_adr
        assert r["status"] == "ok"
        assert r["adr"]["title"] == "Untouched"

    def test_update_missing_returns_not_found(self, workspace):
        r = update_adr(workspace, 9999, title="x")
        assert r["status"] == "not_found"

    def test_update_rejects_empty_title(self, workspace):
        created = create_adr(workspace, title="Valid")
        rid = created["adr"]["id"]
        with pytest.raises(ValueError, match="title cannot be empty"):
            update_adr(workspace, rid, title="")

    def test_update_rejects_invalid_status(self, workspace):
        created = create_adr(workspace, title="Valid")
        rid = created["adr"]["id"]
        with pytest.raises(ValueError, match="Invalid ADR status"):
            update_adr(workspace, rid, status="bogus")


# ─── deprecate_adr ─────────────────────────────────────────────────────────


class TestDeprecateAdr:
    """``deprecate_adr`` sets status=deprecated and links superseded_by."""

    def test_deprecate_without_replacement(self, workspace):
        created = create_adr(workspace, title="Old", status="accepted")
        rid = created["adr"]["id"]
        r = deprecate_adr(workspace, rid)
        assert r["status"] == "ok"
        assert r["action"] == "deprecated"
        assert r["adr"]["status"] == "deprecated"
        assert r["adr"]["superseded_by"] is None

    def test_deprecate_with_replacement_links_ids(self, workspace):
        old = create_adr(workspace, title="Old", status="accepted")
        new = create_adr(workspace, title="New", status="accepted")
        r = deprecate_adr(workspace, old["adr"]["id"], superseded_by=new["adr"]["id"])
        assert r["adr"]["status"] == "deprecated"
        assert r["adr"]["superseded_by"] == new["adr"]["id"]

    def test_deprecate_rejects_self_supersession(self, workspace):
        created = create_adr(workspace, title="Self")
        rid = created["adr"]["id"]
        with pytest.raises(ValueError, match="cannot supersede itself"):
            deprecate_adr(workspace, rid, superseded_by=rid)

    def test_deprecate_rejects_missing_replacement(self, workspace):
        created = create_adr(workspace, title="Old")
        rid = created["adr"]["id"]
        r = deprecate_adr(workspace, rid, superseded_by=9999)
        assert r["status"] == "error"
        assert r["error"] == "superseded_by_not_found"
        assert r["superseded_by"] == 9999

    def test_deprecate_missing_adr_returns_not_found(self, workspace):
        r = deprecate_adr(workspace, 9999)
        assert r["status"] == "not_found"


# ─── delete_adr ────────────────────────────────────────────────────────────


class TestDeleteAdr:
    """``delete_adr`` removes a record and clears dangling references."""

    def test_delete_existing(self, workspace):
        created = create_adr(workspace, title="ToDelete")
        rid = created["adr"]["id"]
        r = delete_adr(workspace, rid)
        assert r["status"] == "ok"
        assert r["action"] == "deleted"
        assert r["id"] == rid
        # Verify it's really gone
        assert get_adr(workspace, rid)["status"] == "not_found"

    def test_delete_missing_returns_not_found(self, workspace):
        r = delete_adr(workspace, 9999)
        assert r["status"] == "not_found"

    def test_delete_clears_dangling_superseded_by(self, workspace):
        old = create_adr(workspace, title="Old", status="accepted")
        new = create_adr(workspace, title="New", status="accepted")
        deprecate_adr(workspace, old["adr"]["id"], superseded_by=new["adr"]["id"])

        # Delete the replacement — old.superseded_by should become NULL
        delete_adr(workspace, new["adr"]["id"])
        r = get_adr(workspace, old["adr"]["id"])
        assert r["adr"]["superseded_by"] is None


# ─── manage_adr dispatcher ─────────────────────────────────────────────────


class TestManageAdrDispatcher:
    """``manage_adr`` is the single entry point used by CLI + MCP."""

    def test_dispatch_create(self, workspace):
        r = manage_adr(workspace, "create", title="Via dispatch")
        assert r["status"] == "ok"
        assert r["action"] == "created"

    def test_dispatch_list(self, workspace):
        manage_adr(workspace, "create", title="A")
        r = manage_adr(workspace, "list")
        assert r["filtered"] == 1

    def test_dispatch_get(self, workspace):
        created = manage_adr(workspace, "create", title="X")
        rid = created["adr"]["id"]
        r = manage_adr(workspace, "get", id=rid)
        assert r["status"] == "ok"

    def test_dispatch_update(self, workspace):
        created = manage_adr(workspace, "create", title="X")
        rid = created["adr"]["id"]
        r = manage_adr(workspace, "update", id=rid, title="Y")
        assert r["adr"]["title"] == "Y"

    def test_dispatch_deprecate(self, workspace):
        created = manage_adr(workspace, "create", title="X")
        rid = created["adr"]["id"]
        r = manage_adr(workspace, "deprecate", id=rid)
        assert r["adr"]["status"] == "deprecated"

    def test_dispatch_delete(self, workspace):
        created = manage_adr(workspace, "create", title="X")
        rid = created["adr"]["id"]
        r = manage_adr(workspace, "delete", id=rid)
        assert r["status"] == "ok"

    def test_dispatch_unknown_action_returns_error(self, workspace):
        r = manage_adr(workspace, "bogus")
        assert r["status"] == "error"
        assert r["error"] == "unknown_action"
        assert "create" in r["available_actions"]

    def test_dispatch_create_without_title_returns_structured_error(self, workspace):
        r = manage_adr(workspace, "create")
        assert r["status"] == "error"
        assert r["error"] == "missing_required_field"
        assert r["field"] == "title"

    def test_dispatch_get_without_id_returns_structured_error(self, workspace):
        r = manage_adr(workspace, "get")
        assert r["status"] == "error"
        assert r["error"] == "missing_required_field"
        assert r["field"] == "id"


# ─── CLI command registration ──────────────────────────────────────────────


@pytest.mark.skip(reason="adr command dropped in issue #195 consolidation (adr.py deleted; adr_engine still tested above)")
class TestCliCommandRegistration:
    """The ``adr`` command must auto-register from commands/adr.py."""

    def test_adr_command_registered(self):
        assert "adr" in COMMAND_REGISTRY
        info = COMMAND_REGISTRY["adr"]
        assert "help" in info
        assert "add_args" in info
        assert "execute" in info
        assert callable(info["add_args"])
        assert callable(info["execute"])

    def test_adr_command_help_text_mentions_actions(self):
        help_text = COMMAND_REGISTRY["adr"]["help"]
        for action in ("create", "list", "get", "update", "deprecate", "delete"):
            assert action in help_text

    def test_execute_with_no_action_returns_usage_error(self, workspace):
        from argparse import Namespace
        info = COMMAND_REGISTRY["adr"]
        # Simulate `codelens adr` with no subcommand
        args = Namespace(adr_action=None)
        r = info["execute"](args, workspace)
        assert r["status"] == "error"
        assert r["error"] == "no_action"
        assert "usage" in r
        assert "examples" in r


# ─── MCP tool registration ─────────────────────────────────────────────────


@pytest.mark.skip(reason="adr command + manage-adr MCP tool dropped in issue #195 consolidation")
class TestMcpToolRegistration:
    """The ``manage-adr`` MCP tool must be statically defined."""

    def test_manage_adr_in_tool_definitions(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        assert "manage-adr" in _TOOL_DEFINITIONS

    def test_manage_adr_schema_has_required_fields(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        schema = _TOOL_DEFINITIONS["manage-adr"]
        assert "description" in schema
        assert "parameters" in schema
        params = schema["parameters"]
        assert params["type"] == "object"
        assert "workspace" in params["properties"]
        assert "action" in params["properties"]
        assert "workspace" in params["required"]
        assert "action" in params["required"]

    def test_manage_adr_action_enum_matches_engine(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        action_prop = _TOOL_DEFINITIONS["manage-adr"]["parameters"]["properties"]["action"]
        assert set(action_prop["enum"]) == {
            "create", "list", "get", "update", "deprecate", "delete"
        }

    def test_manage_adr_status_enum_matches_engine(self):
        try:
            from mcp_server import _TOOL_DEFINITIONS
        except ImportError as exc:
            pytest.skip(f"mcp_server not importable: {exc}")
        props = _TOOL_DEFINITIONS["manage-adr"]["parameters"]["properties"]
        assert set(props["status"]["enum"]) == _VALID_STATUSES
        assert set(props["status_filter"]["enum"]) == _VALID_STATUSES


# ─── File header convention ────────────────────────────────────────────────


class TestFileHeaders:
    """CONTRIBUTING.md mandates @WHO/@WHAT/@PART/@ENTRY headers on new files."""

    def test_adr_engine_has_file_header(self):
        path = os.path.join(SCRIPT_DIR, "adr_engine.py")
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(500)
        assert "# @WHO:" in head
        assert "# @WHAT:" in head
        assert "# @PART:" in head
        assert "# @ENTRY:" in head

    def test_adr_command_has_file_header(self):
        pytest.skip("adr.py deleted in issue #195 consolidation")
        path = os.path.join(SCRIPT_DIR, "commands", "adr.py")
        with open(path, "r", encoding="utf-8") as f:
            head = f.read(500)
        assert "# @WHO:" in head
        assert "# @WHAT:" in head
        assert "# @PART:" in head
        assert "# @ENTRY:" in head


# ─── Cross-action workflow integration ─────────────────────────────────────


class TestEndToEndWorkflow:
    """Simulate a real ADR lifecycle: create → accept → supersede → deprecate."""

    def test_full_lifecycle(self, workspace):
        # 1. Propose an ADR
        r1 = manage_adr(
            workspace, "create",
            title="Use SQLite over PostgreSQL",
            context="Deployment simplicity for single-node",
            decision="TBD",
            status="proposed",
        )
        id1 = r1["adr"]["id"]
        assert r1["adr"]["status"] == "proposed"

        # 2. Accept it after deliberation
        r2 = manage_adr(
            workspace, "update",
            id=id1,
            decision="SQLite with WAL mode, weekly VACUUM",
            status="accepted",
        )
        assert r2["adr"]["status"] == "accepted"
        assert r2["adr"]["decision"] == "SQLite with WAL mode, weekly VACUUM"

        # 3. Time passes — a new ADR supersedes it
        r3 = manage_adr(
            workspace, "create",
            title="Use PostgreSQL for multi-node",
            context="Outgrew single-node SQLite",
            decision="PostgreSQL 16 with streaming replication",
            status="accepted",
        )
        id3 = r3["adr"]["id"]

        # 4. Deprecate the old one, link to the new
        r4 = manage_adr(workspace, "deprecate", id=id1, superseded_by=id3)
        assert r4["adr"]["status"] == "deprecated"
        assert r4["adr"]["superseded_by"] == id3

        # 5. List — total 2, accepted 1, deprecated 1
        all_adrs = manage_adr(workspace, "list")
        assert all_adrs["total"] == 2

        accepted = manage_adr(workspace, "list", status_filter="accepted")
        assert accepted["filtered"] == 1
        assert accepted["adrs"][0]["id"] == id3

        deprecated = manage_adr(workspace, "list", status_filter="deprecated")
        assert deprecated["filtered"] == 1
        assert deprecated["adrs"][0]["id"] == id1
