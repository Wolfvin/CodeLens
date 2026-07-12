# @WHO:   tests/test_rust_command_taint.py
# @WHAT:  Tests for Rust #[tauri::command] parameter-to-sink taint MVP (issue #240)
# @PART:  tests
"""Tests for rust_command_taint.scan_workspace() (issue #240 MVP).

Verifies the regex-based detector flags a Tauri command parameter that
reaches a dangerous sink, does NOT flag Command::new() sinks that live in
separate helper functions (not the command body), and does NOT flag
commands whose parameters never reach a sink.
"""

import os
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from rust_command_taint import scan_workspace  # noqa: E402


def _write_ws(files: dict) -> str:
    ws = tempfile.mkdtemp(prefix="codelens_rust_taint_")
    for rel, content in files.items():
        path = os.path.join(ws, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    return ws


class TestRustCommandTaint:
    def test_param_reaching_command_new_flagged(self):
        ws = _write_ws({
            "src/cmd.rs": (
                "#[tauri::command]\n"
                "pub fn run_it(user_arg: String) -> Result<(), String> {\n"
                "    let out = Command::new(&user_arg).output();\n"
                "    Ok(())\n"
                "}\n"
            )
        })
        try:
            findings = scan_workspace(ws)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

        assert len(findings) == 1
        f = findings[0]
        assert f["rule_id"] == "rust-command-injection"
        assert f["tainted_variable"] == "user_arg"
        assert f["sink"] == "Command::new"

    def test_param_reaching_fs_flagged(self):
        ws = _write_ws({
            "src/cmd.rs": (
                "#[tauri::command(rename_all = \"camelCase\")]\n"
                "pub async fn save(path: String) -> Result<(), String> {\n"
                "    std::fs::write(&path, b\"data\").unwrap();\n"
                "    Ok(())\n"
                "}\n"
            )
        })
        try:
            findings = scan_workspace(ws)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

        assert len(findings) == 1
        assert findings[0]["rule_id"] == "rust-path-traversal"
        assert findings[0]["tainted_variable"] == "path"

    def test_command_new_in_helper_not_command_body_not_flagged(self):
        """Command::new() in a separate helper function (not inside the
        #[tauri::command] body, and not fed by a command parameter) must
        not be flagged — the brace-matched body boundary is what scopes
        the analysis. Regression guard for a real pattern seen on a live
        workspace (health/mod.rs)."""
        ws = _write_ws({
            "src/mod.rs": (
                "fn helper() {\n"
                "    let c = Command::new(\"tesseract\").output();\n"
                "}\n"
                "\n"
                "#[tauri::command]\n"
                "pub fn health_snapshot(refresh: Option<bool>) -> String {\n"
                "    String::from(\"ok\")\n"
                "}\n"
            )
        })
        try:
            findings = scan_workspace(ws)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

        assert findings == []

    def test_param_not_reaching_sink_not_flagged(self):
        ws = _write_ws({
            "src/cmd.rs": (
                "#[tauri::command]\n"
                "pub fn add(a: i32, b: i32) -> i32 {\n"
                "    a + b\n"
                "}\n"
            )
        })
        try:
            findings = scan_workspace(ws)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

        assert findings == []

    def test_non_command_fn_with_param_and_sink_not_flagged(self):
        """A plain fn (no #[tauri::command]) whose param reaches a sink is
        out of scope for this MVP — the command attribute is the taint
        source marker. Only #[tauri::command] fns are analyzed."""
        ws = _write_ws({
            "src/cmd.rs": (
                "pub fn internal(arg: String) {\n"
                "    Command::new(&arg).output();\n"
                "}\n"
            )
        })
        try:
            findings = scan_workspace(ws)
        finally:
            import shutil
            shutil.rmtree(ws, ignore_errors=True)

        assert findings == []
