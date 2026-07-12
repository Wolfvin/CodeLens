# @WHO:   scripts/rust_command_taint.py
# @WHAT:  Regex-based taint detection for #[tauri::command] parameters flowing to dangerous sinks
# @PART:  engine
# @ENTRY: scan_workspace()
"""Rust `#[tauri::command]` parameter-to-sink taint detection (issue #240, MVP).

`ast_taint_engine.py` only supports Python/JS/TS/TSX — Rust has zero taint
coverage. Full cross-language taint (tracing a value from a TypeScript
`invoke("cmd", {...})` call across the IPC boundary into the matching Rust
`#[tauri::command]` function) is out of scope for this MVP — see
docs/design/0240-tauri-command-param-taint.md for why.

What this DOES cover: every parameter of a `#[tauri::command]`-annotated
function is untrusted input by construction (that's exactly how Tauri's IPC
dispatch delivers frontend data to Rust) — no cross-language tracing needed
to establish that. From there this is intra-procedural taint: does a
parameter flow into a dangerous sink within the same function body.

This is regex-based, not a full tree-sitter AST walker (consistent with
several other CodeLens engines, e.g. regexaudit_engine.py) — an explicit,
documented trade-off. False negatives are possible on parameters sanitized
in ways the regex can't see; there is no sanitizer allowlist in this MVP.
"""

import os
import re
from typing import Any, Dict, List

from utils import DEFAULT_IGNORE_DIRS, should_ignore_dir, logger


_COMMAND_ATTR_RE = re.compile(
    r"#\[\s*tauri::command\s*(?:\([^)]*\))?\s*\]\s*"
    r"(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*\(([^)]*)\)",
    re.MULTILINE,
)

# Parameter name from a Rust fn signature: `name: Type` or `mut name: Type`.
_PARAM_NAME_RE = re.compile(r"(?:mut\s+)?(\w+)\s*:")

# High-confidence Rust sinks. Each maps to (rule_id, cwe, human message).
_SINKS: List[Dict[str, str]] = [
    {
        "pattern": r"Command::new\s*\(",
        "rule_id": "rust-command-injection",
        "cwe": "CWE-78",
        "sink": "Command::new",
        "message": "Tauri command parameter reaches Command::new() — potential command injection",
    },
    {
        "pattern": r"std::process::Command::new\s*\(",
        "rule_id": "rust-command-injection",
        "cwe": "CWE-78",
        "sink": "std::process::Command::new",
        "message": "Tauri command parameter reaches std::process::Command::new() — potential command injection",
    },
    {
        "pattern": r"std::fs::(read|write|remove_file|remove_dir|remove_dir_all|create_dir|create_dir_all|copy|rename)\s*\(",
        "rule_id": "rust-path-traversal",
        "cwe": "CWE-22",
        "sink": "std::fs",
        "message": "Tauri command parameter reaches a std::fs path operation — potential path traversal",
    },
]


def _find_function_body(source: str, start: int) -> str:
    """Return the brace-matched body of the function starting at ``start``
    (the index of the opening `fn` match). Returns "" if unbalanced."""
    brace_start = source.find("{", start)
    if brace_start == -1:
        return ""
    depth = 0
    for i in range(brace_start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[brace_start:i + 1]
    return source[brace_start:]


def _scan_file(file_path: str, rel_path: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except (IOError, OSError):
        return findings

    for match in _COMMAND_ATTR_RE.finditer(source):
        fn_name = match.group(1)
        params_raw = match.group(2)
        params = [
            m.group(1) for m in _PARAM_NAME_RE.finditer(params_raw)
            if m.group(1) not in ("self",)
        ]
        if not params:
            continue

        body = _find_function_body(source, match.end())
        if not body:
            continue

        body_start_line = source[:match.end()].count("\n") + 1

        for line_offset, line in enumerate(body.split("\n")):
            for sink in _SINKS:
                if not re.search(sink["pattern"], line):
                    continue
                for param in params:
                    # Direct usage of the parameter name as/near an argument
                    # on the same line as the sink call.
                    if re.search(rf"\b{re.escape(param)}\b", line):
                        findings.append({
                            "rule_id": sink["rule_id"],
                            "rule_name": "Tauri command parameter taint",
                            "severity": "high",
                            "cwe": sink["cwe"],
                            "message": (
                                f"{sink['message']} in #[tauri::command] fn "
                                f"'{fn_name}' (parameter '{param}')"
                            ),
                            "file": rel_path,
                            "line": body_start_line + line_offset,
                            "source": f"tauri::command param '{param}'",
                            "sink": sink["sink"],
                            "tainted_variable": param,
                            "sanitized": False,
                            "confidence": "medium",
                            "taint_path": (
                                f"#[tauri::command] fn {fn_name}({param}: ...) "
                                f"→ {sink['sink']}"
                            ),
                            "engine": "rust_command_taint",
                        })
    return findings


def scan_workspace(workspace: str, max_files: int = 3000) -> List[Dict[str, Any]]:
    """Scan all `.rs` files in ``workspace`` for tainted Tauri command
    parameters reaching a dangerous sink.

    Returns a list of finding dicts in the same shape as
    ``ast_taint_engine``'s Python/JS findings (rule_id, severity, cwe,
    message, file, line, source, sink, tainted_variable, sanitized,
    confidence, taint_path) so callers can merge them into one list.
    """
    findings: List[Dict[str, Any]] = []
    workspace = os.path.abspath(workspace)
    files_scanned = 0

    for root, dirs, filenames in os.walk(workspace):
        rel_root = os.path.relpath(root, workspace)
        if should_ignore_dir(rel_root):
            dirs.clear()
            continue
        dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]

        for filename in filenames:
            if not filename.endswith(".rs"):
                continue
            if files_scanned >= max_files:
                return findings
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, workspace)
            try:
                findings.extend(_scan_file(file_path, rel_path))
            except Exception:
                logger.debug(f"rust_command_taint: failed to scan {rel_path}", exc_info=True)
            files_scanned += 1

    return findings
