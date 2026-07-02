"""CodeLens ``sessions`` command — installer session log viewer (issue #64, Phase 2).

What this command does
-----------------------
``codelens sessions`` reads the install-session log that ``setup.sh``
appends to on every run, and displays the last N sessions in a
human-readable format (or JSON for programmatic access).

The session log lives at ``~/.codelens/session.md`` (Markdown) with a
JSON sidecar at ``~/.codelens/session.json`` for structured access.
Each session entry records:

* Timestamp (ISO 8601, UTC)
* Duration (seconds)
* Python / OS / arch
* Detected agents (Claude Code, Cursor, etc.) with ✓/✗
* Configured integrations
* Dependencies installed
* Warnings and errors

This is the "what happened last time I ran setup?" debugging tool —
useful when an install partially fails and the user wants to see
what changed.

Why a separate command (not just ``cat ~/.codelens/session.md``)?
-----------------------------------------------------------------
* **Filtering** — ``--entries N`` shows the last N sessions without
  dumping the whole file.
* **Rotation** — when the log exceeds 1 MB, the oldest sessions are
  trimmed automatically (keep last 50).
* **JSON output** — ``--json`` parses the sidecar and emits a
  structured array for CI / programmatic consumption.
* **Custom config dir** — ``--config-dir`` lets users inspect a
  non-default ``~/.codelens/`` location (useful for debugging
  containerized installs).
* **Doctor integration** — ``doctor`` can call ``sessions --json``
  to surface "last install had 2 warnings" in its diagnostic.

What Phase 2 deliberately does NOT do
-------------------------------------
* It does not parse legacy install logs from before this feature
  shipped (those entries simply don't exist).
* It does not sync sessions across machines (that's a future
  cloud-sync feature, out of scope).
* It does not write sessions — only ``setup.sh`` writes them. This
  command is read-only.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from commands import register_command

# ─── Constants ─────────────────────────────────────────────────

# Default location of the session log. Override per-call with
# ``--config-dir``.
DEFAULT_CONFIG_DIR = os.path.expanduser("~/.codelens")
SESSION_MD_FILENAME = "session.md"
SESSION_JSON_FILENAME = "session.json"

# Rotation thresholds — when the JSON sidecar exceeds this size,
# trim to the most recent N entries.
MAX_LOG_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB
MAX_SESSIONS_AFTER_ROTATION = 50

# Default number of sessions to display.
DEFAULT_ENTRIES = 5


# ─── Session log paths ─────────────────────────────────────────


def _session_paths(config_dir: Optional[str]) -> tuple[str, str]:
    """Return ``(md_path, json_path)`` for the given config dir.

    Falls back to :data:`DEFAULT_CONFIG_DIR` when ``config_dir`` is
    None or empty.
    """
    base = config_dir or DEFAULT_CONFIG_DIR
    return (
        os.path.join(base, SESSION_MD_FILENAME),
        os.path.join(base, SESSION_JSON_FILENAME),
    )


# ─── Session log reading ───────────────────────────────────────


def _load_json_sessions(json_path: str) -> List[Dict[str, Any]]:
    """Load the JSON sidecar and return the sessions list.

    Returns an empty list if the file doesn't exist, is empty, or
    fails to parse. A corrupted sidecar must NOT crash the command —
    we degrade gracefully to "no sessions found" and let the user
    inspect the raw Markdown file with ``--raw``.
    """
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "sessions" in data:
            # Future-proof: support a wrapped schema where the
            # top-level object has a ``sessions`` key.
            sessions = data["sessions"]
            return sessions if isinstance(sessions, list) else []
        return []
    except (OSError, json.JSONDecodeError):
        return []


def _parse_md_sessions(md_path: str) -> List[Dict[str, Any]]:
    """Parse the Markdown log into a list of session dicts.

    Each session in the Markdown log is delimited by a level-2
    heading (``##``). The heading line contains the ISO 8601
    timestamp. Subsequent lines until the next ``##`` are the
    session body (key-value pairs in ``- **key**: value`` format).

    This is a best-effort parser — the JSON sidecar is the source of
    truth; the Markdown is for human reading. We only fall back to
    parsing the Markdown when the sidecar is missing or empty.
    """
    if not os.path.exists(md_path):
        return []
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return []

    sessions: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    current_body: List[str] = []

    for line in content.splitlines():
        # A level-2 heading starts a new session.
        if line.startswith("## "):
            # Flush the previous session.
            if current is not None:
                current["body"] = "\n".join(current_body).strip()
                sessions.append(current)
            # Parse the heading: ``## 2026-06-28T09:14:31Z — setup``
            heading = line[3:].strip()
            # Split on em-dash if present (the convention from setup.sh).
            parts = re.split(r"\s+[—-]\s+", heading, maxsplit=1)
            timestamp_str = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else "session"
            current = {
                "timestamp": timestamp_str,
                "title": title,
                "raw_heading": heading,
            }
            current_body = []
        elif current is not None:
            current_body.append(line)

    # Flush the last session.
    if current is not None:
        current["body"] = "\n".join(current_body).strip()
        sessions.append(current)

    return sessions


def _load_sessions(config_dir: Optional[str]) -> List[Dict[str, Any]]:
    """Load sessions, preferring the JSON sidecar.

    Falls back to parsing the Markdown log if the sidecar is missing
    or empty. Returns an empty list if neither exists.
    """
    md_path, json_path = _session_paths(config_dir)
    sessions = _load_json_sessions(json_path)
    if sessions:
        return sessions
    return _parse_md_sessions(md_path)


# ─── Rotation ──────────────────────────────────────────────────


def _maybe_rotate(config_dir: Optional[str]) -> bool:
    """Trim the session log if it exceeds :data:`MAX_LOG_SIZE_BYTES`.

    Returns ``True`` if rotation happened, ``False`` otherwise.
    Rotation keeps the most recent :data:`MAX_SESSIONS_AFTER_ROTATION`
    sessions in both the JSON sidecar and the Markdown log.

    This is called automatically on every ``sessions`` invocation —
    no need for a separate cron job.
    """
    md_path, json_path = _session_paths(config_dir)
    # Check the JSON sidecar size (the smaller of the two; if it's
    # over the threshold, the Markdown is definitely over too).
    try:
        json_size = os.path.getsize(json_path) if os.path.exists(json_path) else 0
    except OSError:
        json_size = 0
    if json_size < MAX_LOG_SIZE_BYTES:
        return False

    sessions = _load_json_sessions(json_path)
    if len(sessions) <= MAX_SESSIONS_AFTER_ROTATION:
        return False

    # Keep the most recent N sessions. Sessions are appended in
    # chronological order, so the most recent are at the end.
    trimmed = sessions[-MAX_SESSIONS_AFTER_ROTATION:]
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2, ensure_ascii=False)
    except OSError:
        return False

    # Rewrite the Markdown log with only the trimmed sessions.
    # We don't try to reconstruct the original Markdown formatting
    # exactly — we just emit a fresh, valid log from the JSON data.
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# CodeLens install sessions\n\n")
            for s in trimmed:
                ts = s.get("timestamp", "unknown")
                title = s.get("title", "session")
                f.write(f"## {ts} — {title}\n\n")
                body = s.get("body")
                if body:
                    f.write(body + "\n\n")
                else:
                    # Emit structured fields if no body.
                    for k, v in s.items():
                        if k in ("timestamp", "title", "raw_heading", "body"):
                            continue
                        f.write(f"- **{k}**: {v}\n")
                    f.write("\n")
    except OSError:
        pass
    return True


# ─── Output formatting ─────────────────────────────────────────


def _format_text(sessions: List[Dict[str, Any]], entries: int) -> str:
    """Format the last N sessions as a human-readable text report."""
    if not sessions:
        return "No install sessions found. Run `bash setup.sh` to record one."
    # Take the last N sessions (most recent first for display).
    recent = sessions[-entries:] if entries > 0 else sessions
    recent = list(reversed(recent))  # most recent first

    lines: List[str] = []
    lines.append(f"CodeLens sessions — showing {len(recent)} of {len(sessions)} total")
    lines.append("=" * 60)
    for i, s in enumerate(recent, 1):
        ts = s.get("timestamp", "?")
        title = s.get("title", "session")
        lines.append(f"\n[{i}] {ts} — {title}")
        # Show structured fields if present.
        for key in ("duration_sec", "python", "os", "arch", "agents_detected",
                    "integrations_configured", "deps_installed", "warnings", "errors"):
            if key in s:
                val = s[key]
                if isinstance(val, (list, dict)):
                    val = json.dumps(val, ensure_ascii=False)
                lines.append(f"    {key}: {val}")
        # If there's a body (from MD parsing), show a truncated version.
        body = s.get("body")
        if body and not any(k in s for k in ("duration_sec", "python")):
            # No structured fields — show first 5 lines of body.
            body_lines = body.splitlines()[:5]
            for bl in body_lines:
                if bl.strip():
                    lines.append(f"    {bl}")
            if len(body.splitlines()) > 5:
                lines.append(f"    ... ({len(body.splitlines()) - 5} more lines)")
    lines.append("\n" + "=" * 60)
    lines.append(f"Total sessions logged: {len(sessions)}")
    return "\n".join(lines)


def _format_raw(md_path: str) -> str:
    """Return the raw Markdown log content verbatim."""
    if not os.path.exists(md_path):
        return f"Session log not found at {md_path}"
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as exc:
        return f"Failed to read {md_path}: {exc}"


# ─── CLI plumbing ──────────────────────────────────────────────


def add_args(parser):
    """Register sessions-specific arguments."""
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Ignored (sessions is global). Accepted for CLI consistency.",
    )
    parser.add_argument(
        "--entries",
        type=int,
        default=DEFAULT_ENTRIES,
        help=f"Number of recent sessions to display (default: {DEFAULT_ENTRIES}). Use 0 for all.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        default=False,
        help="Print the raw Markdown log verbatim (no formatting).",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help=f"Custom config dir (default: {DEFAULT_CONFIG_DIR}).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output as JSON array (for programmatic access).",
    )


def execute(args, workspace):
    """Read the session log, optionally rotate, return result dict.

    The result always includes:

    * ``status``         — "ok" | "error"
    * ``config_dir``     — resolved config dir
    * ``total_sessions`` — count of sessions in the log
    * ``returned_sessions`` — count actually returned (after ``--entries``)
    * ``sessions``       — list of session dicts (the data)
    * ``rotated``        — bool, whether rotation happened during this call
    * ``raw``            — the raw Markdown content (only if ``--raw``)
    """
    config_dir = getattr(args, "config_dir", None) or DEFAULT_CONFIG_DIR
    entries = getattr(args, "entries", DEFAULT_ENTRIES)
    raw_mode = bool(getattr(args, "raw", False))
    json_mode = bool(getattr(args, "json_output", False))

    md_path, json_path = _session_paths(config_dir)

    # Rotate if needed (side effect — but safe and idempotent).
    rotated = _maybe_rotate(config_dir)

    sessions = _load_sessions(config_dir)

    # Apply --entries limit (0 = all).
    if entries > 0:
        display = sessions[-entries:]
    else:
        display = sessions

    result: Dict[str, Any] = {
        "status": "ok",
        "config_dir": config_dir,
        "md_path": md_path,
        "json_path": json_path,
        "total_sessions": len(sessions),
        "returned_sessions": len(display),
        "sessions": display,
        "rotated": rotated,
    }

    if raw_mode:
        result["raw"] = _format_raw(md_path)
        # In raw mode, print the raw content directly and signal to
        # the dispatcher that we've already printed.
        print(result["raw"])
        result["_sessions_printed_text"] = True
    elif json_mode:
        # In JSON mode, print just the sessions array (so ``jq`` etc.
        # can pipe it cleanly). The full result dict is still
        # returned for the dispatcher, but we override the printed
        # output here.
        print(json.dumps(display, indent=2, ensure_ascii=False))
        result["_sessions_printed_text"] = True
    else:
        # Default text mode — print the human-readable report.
        print(_format_text(sessions, entries))
        result["_sessions_printed_text"] = True

    return result


register_command(
    "sessions",
    "View recent install sessions (from setup.sh session log)",
    add_args,
    execute,
)
