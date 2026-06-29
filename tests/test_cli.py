"""
Tests for the CLI entry point — scan, query, list, init commands.
"""

import os
import sys
import json
import tempfile
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from commands.scan import cmd_scan
from commands.query import cmd_query
from commands.list import cmd_list
from commands.init import cmd_init
from codelens import _apply_top_n, _NO_TOP_KEYS
from commands.migrate import cmd_migrate
from codelens import _registry_exists


def _create_sample_workspace():
    """Create a temporary workspace with sample files for testing."""
    ws = tempfile.mkdtemp()

    # Create HTML file
    with open(os.path.join(ws, "index.html"), 'w') as f:
        f.write('''<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <div id="main-content" class="container main-wrapper">
        <h1 class="header-title">Hello</h1>
        <button id="submit-btn" class="btn btn-primary">Submit</button>
    </div>
</body>
</html>''')

    # Create CSS file
    os.makedirs(os.path.join(ws, "styles"), exist_ok=True)
    with open(os.path.join(ws, "styles", "main.css"), 'w') as f:
        f.write('''
.container { max-width: 1200px; margin: 0 auto; }
.main-wrapper { padding: 20px; }
.header-title { font-size: 2rem; }
.btn { padding: 8px 16px; border: none; cursor: pointer; }
.btn-primary { background: blue; color: white; }
#main-content { background: #fff; }
#submit-btn { font-weight: bold; }
''')

    # Create JS file
    with open(os.path.join(ws, "app.js"), 'w') as f:
        f.write('''
const submitBtn = document.getElementById("submit-btn");
const content = document.querySelector("#main-content");
const buttons = document.querySelectorAll(".btn");

function handleClick() {
    console.log("clicked");
}

function processForm() {
    const data = validateInput();
    return data;
}

function validateInput() {
    return true;
}
''')

    # Create Rust file
    os.makedirs(os.path.join(ws, "src"), exist_ok=True)
    with open(os.path.join(ws, "src", "main.rs"), 'w') as f:
        f.write('''
fn main() {
    let result = verify_token("test");
}

fn verify_token(token: &str) -> bool {
    let hash = hash_token(token);
    hash.len() > 0
}

fn hash_token(token: &str) -> String {
    token.to_string()
}
''')

    return ws


class TestCmdInit:
    """Test the init command."""

    def test_init_creates_codelens_dir(self):
        with tempfile.TemporaryDirectory() as ws:
            result = cmd_init(ws)
            assert result["status"] == "ok"
            assert os.path.isdir(os.path.join(ws, ".codelens"))

    def test_init_creates_config(self):
        with tempfile.TemporaryDirectory() as ws:
            result = cmd_init(ws)
            assert "config" in result
            config_path = os.path.join(ws, ".codelens", "codelens.config.json")
            assert os.path.exists(config_path)


class TestCmdScan:
    """Test the scan command."""

    def test_scan_workspace(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["status"] == "ok"
            assert result["files_scanned"]["html"] >= 1
            assert result["files_scanned"]["css"] >= 1
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_creates_registry(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert os.path.exists(os.path.join(ws, ".codelens", "frontend.json"))
            assert os.path.exists(os.path.join(ws, ".codelens", "backend.json"))
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_finds_classes(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["frontend"]["classes"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_finds_ids(self):
        ws = _create_sample_workspace()
        try:
            result = cmd_scan(ws)
            assert result["frontend"]["ids"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestCmdQuery:
    """Test the query command."""

    def test_query_existing_id(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("submit-btn", ws, domain="frontend")
            assert result["found"] is True
            assert result["type"] == "id"
            assert result["name"] == "submit-btn"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_existing_class(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("btn-primary", ws, domain="frontend")
            assert result["found"] is True
            assert result["type"] == "class"
            assert result["name"] == "btn-primary"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_nonexistent(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("nonexistent-xyz", ws)
            assert result["found"] is False
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_backend_function(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_query("verify_token", ws, domain="backend")
            assert result["found"] is True
            assert result["type"] == "function"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_auto_detect_domain(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            # Frontend name → should find in frontend
            result = cmd_query("btn-primary", ws)
            assert result["found"] is True
            assert result["domain"] == "frontend"

            # Backend name → should find in backend
            result = cmd_query("verify_token", ws)
            assert result["found"] is True
            assert result["domain"] == "backend"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestCmdList:
    """Test the list command."""

    def test_list_all(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="all", filter_type="all")
            assert result["count"] > 0
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_dead(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="all", filter_type="dead")
            # Just verify it runs without error and has correct structure
            assert "count" in result
            assert "results" in result
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_frontend_only(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="frontend", filter_type="all")
            assert result["domain"] == "frontend"
            for entry in result["results"]:
                assert entry["type"] in ("class", "id")
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_list_backend_only(self):
        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)
            result = cmd_list(ws, domain="backend", filter_type="all")
            assert result["domain"] == "backend"
            for entry in result["results"]:
                assert entry["type"] == "function"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


# ─── check command positional workspace arg (issue #78) ─────────────────


class TestCheckCommandArgs:
    """Regression guard for issue #78: ``check`` command must accept an
    optional positional ``workspace`` argument so the CI quality-gate
    workflow command ``codelens check . --severity high --sarif`` works.

    Before the fix, ``check`` only defined optional flags (``--severity``,
    ``--max-findings``, etc.) and no positional, so argparse rejected the
    ``.`` argument with ``error: unrecognized arguments: .``, failing CI
    for every PR.
    """

    def test_check_accepts_positional_workspace(self):
        """``check`` add_args must register a positional ``workspace``."""
        import argparse
        from commands.check import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        # With positional
        args = parser.parse_args(["/tmp/test", "--severity", "high"])
        assert args.workspace == "/tmp/test"
        assert args.severity == "high"

    def test_check_workspace_optional(self):
        """``check`` without positional must still parse (workspace=None)."""
        import argparse
        from commands.check import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        args = parser.parse_args(["--severity", "high"])
        assert args.workspace is None
        assert args.severity == "high"

    def test_check_full_cli_invocation_with_positional(self):
        """End-to-end: ``codelens check <workspace> --severity high`` must not raise."""
        import subprocess
        import sys

        ws = _create_sample_workspace()
        try:
            cmd_scan(ws)  # build registry so check has something to read
            proc = subprocess.run(
                [sys.executable, "scripts/codelens.py",
                 "check", ws, "--severity", "high", "--format", "json"],
                capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONPATH": "scripts"},
            )
            # ``check`` exits 1 when gate fails (which it likely will on the
            # sample workspace) — that's fine, we only care that argparse
            # no longer rejects the positional.
            assert "unrecognized arguments" not in proc.stderr, (
                f"argparse still rejects positional workspace: {proc.stderr}"
            )
            # Output should be valid JSON (gate result), not a usage error
            assert proc.stdout.strip().startswith("{"), (
                f"expected JSON output, got: {proc.stdout[:200]}"
            )
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


# ─── --top N universal truncation (issue #36) ──────────────────


class TestTopNUniversalTruncation:
    """Regression guard for issue #36: --top N must truncate ALL list-valued
    keys in command output, not just those in a hardcoded allowlist.

    Before the fix, ``_apply_top_n`` only truncated keys listed in ``_LIST_KEYS``
    (28 names). A new command returning a list under a non-standard key (e.g.,
    ``entities``, ``my_things``, ``nodes``) would silently ignore ``--top N``,
    violating the documented *"Limit list results to top N items"* contract from
    ``SKILL-QUICK.md`` and risking token overflow for MCP clients.

    The fix replaces the allowlist with runtime auto-discovery: every top-level
    list-valued key is truncated, except those in ``_NO_TOP_KEYS`` (structural/
    metadata keys like ``available_commands``).
    """

    def test_non_standard_key_gets_truncated(self):
        """A hypothetical key name not in any allowlist must still be truncated."""
        result = {"status": "ok", "entities": [{"id": i} for i in range(100)]}
        out = _apply_top_n(result, 5)
        assert len(out["entities"]) == 5, (
            f"Expected 5 items after truncation, got {len(out['entities'])}. "
            "Non-standard key 'entities' was not truncated by --top."
        )
        assert out["entities_truncated"] is True
        assert out["entities_total"] == 100

    def test_multiple_non_standard_keys_truncated(self):
        """Multiple non-standard list keys must all be truncated."""
        result = {
            "status": "ok",
            "widgets": [{"id": i} for i in range(50)],
            "gadgets": [{"id": i} for i in range(30)],
        }
        out = _apply_top_n(result, 10)
        assert len(out["widgets"]) == 10
        assert len(out["gadgets"]) == 10
        assert out["widgets_truncated"] is True
        assert out["gadgets_truncated"] is True

    def test_no_top_keys_exempt(self):
        """Keys in _NO_TOP_KEYS must NOT be truncated even if they're lists."""
        result = {
            "status": "ok",
            "available_commands": [f"cmd_{i}" for i in range(50)],
        }
        out = _apply_top_n(result, 5)
        assert len(out["available_commands"]) == 50, (
            "available_commands should NOT be truncated (it's in _NO_TOP_KEYS)"
        )
        assert "available_commands_truncated" not in out

    def test_standard_keys_still_truncated(self):
        """Existing allowlisted keys (e.g., 'findings') must still be truncated."""
        result = {"findings": [{"name": f"f_{i}"} for i in range(50)]}
        out = _apply_top_n(result, 10)
        assert len(out["findings"]) == 10
        assert out["findings_truncated"] is True
        assert out["findings_total"] == 50

    def test_top_zero_means_no_truncation_for_non_standard_key(self):
        """--top 0 (unlimited) must apply to non-standard keys too."""
        result = {"entities": [{"id": i} for i in range(100)]}
        out = _apply_top_n(result, 0)
        assert len(out["entities"]) == 100

    def test_nested_dict_non_standard_key_truncated(self):
        """Non-standard dict-of-lists key must also be truncated."""
        result = {
            "groups": {
                "alpha": [{"id": i} for i in range(30)],
                "beta": [{"id": i} for i in range(5)],
            }
        }
        out = _apply_top_n(result, 10)
        assert len(out["groups"]["alpha"]) == 10
        assert len(out["groups"]["beta"]) == 5  # under limit, no truncation

    def test_underscore_prefixed_keys_skipped(self):
        """Internal keys starting with '_' should not be processed."""
        result = {
            "_meta": [{"x": i} for i in range(50)],
            "findings": [{"name": f"f_{i}"} for i in range(50)],
        }
        out = _apply_top_n(result, 5)
        assert len(out["_meta"]) == 50, "_-prefixed keys should not be truncated"
        assert len(out["findings"]) == 5

    def test_repro_from_issue(self):
        """Exact repro from issue #36: hypothetical command returning 'entities'."""
        # Simulate what a new command might return
        result = {"status": "ok", "entities": [{"id": i} for i in range(1000)]}
        out = _apply_top_n(result, 5)
        # Before fix: len == 1000 (silent --top bypass)
        # After fix: len == 5 (universal truncation)
        assert len(out["entities"]) == 5, (
            "Issue #36 repro: --top 5 did not truncate 'entities' key. "
            "This means a new command returning non-standard keys would "
            "silently bypass --top, risking token overflow for MCP clients."
        )
# ─── _registry_exists after migrate (issue #35) ─────────────────────

class TestRegistryExistsSqlite:
    """Regression guard for issue #35.

    Before the fix, ``_registry_exists`` only checked for
    ``backend.json`` / ``frontend.json``. A workspace that had been
    migrated to SQLite (``codelens migrate``) and whose JSON files
    were then deleted was always treated as having no registry, so
    every subsequent command silently re-ran ``init + scan`` and threw
    away the migrated data — negating the whole point of ``migrate``.

    The fix adds a second path: a populated ``codelens.db`` also
    counts as a valid registry. "Populated" means the ``symbols``
    table has at least one row, so an empty or corrupt db is NOT
    falsely treated as valid.
    """

    def test_registry_exists_after_migrate_with_json_deleted(self):
        """migrate → delete JSON → ``_registry_exists`` must return True.

        This is the exact repro from issue #35.
        """
        ws = _create_sample_workspace()
        try:
            cmd_init(ws)
            cmd_scan(ws)
            # Sanity: JSON files exist before migrate.
            assert os.path.exists(os.path.join(ws, ".codelens", "backend.json"))
            assert os.path.exists(os.path.join(ws, ".codelens", "frontend.json"))

            # Migrate JSON → SQLite.
            migrate_result = cmd_migrate(ws)
            assert migrate_result["status"] == "ok", migrate_result

            # Delete the JSON files (post-migrate cleanup).
            os.remove(os.path.join(ws, ".codelens", "backend.json"))
            os.remove(os.path.join(ws, ".codelens", "frontend.json"))

            # The fix: the migrated SQLite db must still satisfy
            # _registry_exists so commands don't trigger auto-setup.
            assert _registry_exists(ws) is True, (
                "issue #35 regression: migrated workspace with deleted JSON "
                "files is not recognized as having a valid registry"
            )
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_registry_exists_false_for_empty_db(self):
        """An empty SQLite db (``symbols`` has 0 rows) must NOT be valid.

        Issue #35 constraint: 'db kosong/corrupt tidak salah dianggap
        registry valid'.
        """
        import sqlite3

        with tempfile.TemporaryDirectory() as ws:
            codelens_dir = os.path.join(ws, ".codelens")
            os.makedirs(codelens_dir)
            db_path = os.path.join(codelens_dir, "codelens.db")
            # Create a real SQLite db with the symbols table but no rows.
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE symbols (id INTEGER PRIMARY KEY, name TEXT)"
            )
            conn.commit()
            conn.close()

            # No JSON files, empty db → must be False so auto-setup runs.
            assert _registry_exists(ws) is False, (
                "empty SQLite db should not be treated as a valid registry"
            )

    def test_registry_exists_false_for_corrupt_db(self):
        """A corrupt SQLite db (random bytes) must NOT be valid."""
        with tempfile.TemporaryDirectory() as ws:
            codelens_dir = os.path.join(ws, ".codelens")
            os.makedirs(codelens_dir)
            db_path = os.path.join(codelens_dir, "codelens.db")
            with open(db_path, "wb") as f:
                f.write(b"not a sqlite database file - corrupt bytes")

            # No JSON files, corrupt db → must be False.
            assert _registry_exists(ws) is False, (
                "corrupt SQLite db should not be treated as a valid registry"
            )

    def test_registry_exists_true_for_json_only_workspace(self):
        """Legacy JSON-only workspace (no migrate) must still work.

        Ensures the fix is purely additive — path 1 (JSON check) is
        unchanged and still detects pre-migration workspaces, even
        though ``scan`` may also create an empty ``codelens.db`` shell
        via ``store_scan_result`` (which writes only to
        ``analysis_cache``, not ``symbols``).
        """
        ws = _create_sample_workspace()
        try:
            cmd_init(ws)
            cmd_scan(ws)
            # Pre-migration state: JSON files exist.
            assert os.path.exists(os.path.join(ws, ".codelens", "backend.json"))
            assert os.path.exists(os.path.join(ws, ".codelens", "frontend.json"))

            assert _registry_exists(ws) is True, (
                "JSON-only workspace should still be detected as valid "
                "(pre-existing behavior must not regress)"
            )
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_query_uses_sqlite_fallback_after_json_deleted(self):
        """End-to-end: query must return real data from SQLite after
        ``migrate`` + JSON deletion — not just avoid auto-setup, but
        actually serve the migrated data (issue #35: 'padahal data
        lengkap sudah ada di codelens.db').

        Verifies that ``load_backend_registry`` / ``load_frontend_registry``
        fall back to the SQLite cache populated by ``migrate`` when the
        JSON files are missing.
        """
        ws = _create_sample_workspace()
        try:
            cmd_init(ws)
            cmd_scan(ws)
            # Sanity: the symbol we'll query exists in the JSON registry.
            pre = cmd_query("verify_token", ws, domain="backend")
            assert pre["found"] is True, (
                "verify_token must exist in JSON registry before migrate"
            )

            # Migrate → delete JSON → query must still find the symbol.
            mig = cmd_migrate(ws)
            assert mig["status"] == "ok", mig
            os.remove(os.path.join(ws, ".codelens", "backend.json"))
            os.remove(os.path.join(ws, ".codelens", "frontend.json"))

            post = cmd_query("verify_token", ws, domain="backend")
            assert post["found"] is True, (
                "query must return data from SQLite cache after JSON deletion "
                "(issue #35: migrated data must be usable, not just present)"
            )
            assert post["type"] == "function"
            assert post["node"]["fn"] == "verify_token"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)


class TestAutoSetupFallbackCap:
    """Regression tests for issue #34.

    ``_auto_setup`` in scripts/codelens.py runs scan via subprocess with
    ``--max-files 3000`` as a timeout guard. When the subprocess failed
    (non-zero exit / exception), the fallback called
    ``cmd_scan(workspace, incremental=False)`` with NO cap and NO timeout,
    so huge repos could hang auto-setup indefinitely — while the result
    hint still claimed "Auto-setup capped at 3000 files" (a lie).

    Fix: the fallback must pass ``max_files=_AUTO_SETUP_MAX_FILES`` to
    ``cmd_scan``, and ``result["_auto_setup"]`` must surface ``capped`` and
    ``fallback`` flags so MCP clients can tell which path produced the
    registry.
    """

    def test_fallback_passes_max_files_cap(self, monkeypatch):
        """When the subprocess scan fails, the fallback ``cmd_scan`` call
        must be invoked with ``max_files=3000`` (not uncapped)."""
        import subprocess
        from commands import scan as scan_mod
        import codelens

        ws = _create_sample_workspace()
        try:
            # Force subprocess.run to raise so the fallback path is taken.
            def fake_run(*args, **kwargs):
                raise subprocess.SubprocessError("simulated subprocess failure")
            monkeypatch.setattr(subprocess, "run", fake_run)

            # Spy on cmd_scan to capture the max_files kwarg.
            captured = {}
            real_cmd_scan = scan_mod.cmd_scan

            def spy_cmd_scan(workspace, incremental=False, plugins=None, max_files=None):
                captured["called"] = True
                captured["max_files"] = max_files
                captured["incremental"] = incremental
                # Delegate to the real cmd_scan so the registry actually
                # gets built (otherwise _auto_setup would fail downstream).
                return real_cmd_scan(
                    workspace, incremental=incremental,
                    plugins=plugins, max_files=max_files,
                )
            monkeypatch.setattr(scan_mod, "cmd_scan", spy_cmd_scan)

            result = codelens._auto_setup(ws)

            assert captured.get("called") is True, (
                "Fallback path did not call cmd_scan at all"
            )
            assert captured.get("max_files") == 3000, (
                f"Fallback must pass max_files=3000 to cmd_scan; "
                f"got: {captured.get('max_files')!r}"
            )
            assert result.get("auto_setup") == "ok"
            assert result.get("fallback") is True
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_fallback_sets_capped_and_fallback_flags(self, monkeypatch, capsys):
        """``result['_auto_setup']`` must include ``capped=True`` and
        ``fallback=True`` when the fallback path runs against a workspace
        large enough to actually hit the 3000-file cap.

        Verifies issue #34's Definition of Done item #2: the hint that
        says "capped at 3000 files" must no longer be a lie.

        Drives the full CLI flow (``codelens.main()``) so the assertion
        is on the actual ``result["_auto_setup"]`` dict that gets attached
        to the command's JSON output, not just on ``_auto_setup()``'s
        private return value.
        """
        import subprocess
        import codelens

        # Build a workspace with > 3000 source files so the cap is hit.
        ws = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(ws, "src"), exist_ok=True)
            for i in range(3001):
                with open(os.path.join(ws, "src", f"f{i}.py"), "w") as fh:
                    fh.write(f"def f{i}():\n    pass\n")

            # Force subprocess.run to raise → fallback path is taken.
            # This patches subprocess.run in THIS process, which is the
            # same process codelens.main() runs in, so the inner
            # subprocess call inside _auto_setup will hit the patch.
            def fake_run(*args, **kwargs):
                raise subprocess.SubprocessError("simulated subprocess failure")
            monkeypatch.setattr(subprocess, "run", fake_run)

            # Drive the full CLI flow in-process so we can assert on the
            # actual result["_auto_setup"] attached to the JSON output.
            old_argv = sys.argv
            sys.argv = ["codelens.py", "list", ws, "--format", "json"]
            try:
                codelens.main()
            except SystemExit as e:
                # main() may sys.exit(0) on success or sys.exit(1) on gate
                # failure (for `check`). For `list`, success path returns
                # normally or exits 0.
                assert e.code in (0, None), (
                    f"unexpected exit code from main(): {e.code}"
                )
            finally:
                sys.argv = old_argv

            captured = capsys.readouterr()
            assert captured.out.strip().startswith("{"), (
                f"expected JSON on stdout; got: {captured.out[:300]!r}"
            )
            result = json.loads(captured.out.strip())
            auto = result.get("_auto_setup")
            assert auto is not None, (
                "result['_auto_setup'] missing from CLI output; "
                f"got keys: {list(result.keys())}"
            )
            assert auto.get("fallback") is True, (
                f"expected fallback=True after subprocess failure; "
                f"got _auto_setup={auto!r}"
            )
            assert auto.get("capped") is True, (
                f"expected capped=True when workspace has >3000 files; "
                f"got _auto_setup={auto!r}"
            )
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

    def test_main_path_no_fallback_when_subprocess_succeeds(self, capsys):
        """Sanity guard for Definition of Done item #3: when the subprocess
        path succeeds, ``fallback`` must be False and the auto-setup flags
        must still be present on ``result["_auto_setup"]``.

        Also confirms the issue #34 fix didn't break the main path: with
        ``--max-files`` now a registered scan argument, the subprocess no
        longer exits 2 on argparse rejection, so the main path actually
        runs end-to-end (previously it silently failed every time and the
        fallback was always taken).
        """
        import codelens

        ws = _create_sample_workspace()
        try:
            # Real subprocess (no monkeypatching). With the fix,
            # `--max-files` is now a valid scan arg, so the subprocess
            # should succeed and the fallback should NOT be taken.
            old_argv = sys.argv
            sys.argv = ["codelens.py", "list", ws, "--format", "json"]
            try:
                codelens.main()
            except SystemExit as e:
                assert e.code in (0, None), (
                    f"unexpected exit code from main(): {e.code}"
                )
            finally:
                sys.argv = old_argv

            captured = capsys.readouterr()
            assert captured.out.strip().startswith("{"), (
                f"expected JSON on stdout; got: {captured.out[:300]!r}"
            )
            result = json.loads(captured.out.strip())
            auto = result.get("_auto_setup")
            assert auto is not None, (
                f"result['_auto_setup'] missing; got keys: {list(result.keys())}"
            )
            # Sample workspace has ~4 files (html, css, js, rs) — well below
            # the 3000-file cap, so capped must be False.
            assert auto.get("fallback") is False, (
                f"expected fallback=False on subprocess success; "
                f"got _auto_setup={auto!r}"
            )
            assert auto.get("capped") is False, (
                f"expected capped=False for small workspace; "
                f"got _auto_setup={auto!r}"
            )
            # Flags must always be present (even when False) so MCP clients
            # can rely on the schema.
            assert "capped" in auto, "capped flag missing from _auto_setup"
            assert "fallback" in auto, "fallback flag missing from _auto_setup"
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)
