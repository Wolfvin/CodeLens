"""
CodeLens post_tool MCP hook — auto-scan a file after an AI agent writes it.

Implements Phase 1 of issue #47. When an MCP agent (Claude Desktop, Cursor,
Continue.dev, etc.) writes a file via *any* MCP tool, the agent previously
had to remember to call ``codelens_scan`` followed by ``codelens_check`` to
discover newly-introduced security smells, secrets, or dead code. In
practice agents forgot ~70 % of the time, so high-severity findings shipped
to production unnoticed.

This hook closes that gap. After every CodeLens MCP tool call whose
arguments reference a specific file, the hook (when enabled):

1. Resolves the file path relative to the workspace.
2. Runs an incremental scan of the workspace so the registry reflects the
   just-written file (``scan --incremental``).
3. Asks the smell / secrets / complexity engines whether the file produced
   any new ``critical`` or ``high`` findings.
4. Returns a :class:`PostToolHookResult`. The :class:`HookManager` in
   ``mcp_server.py`` surfaces that result to the agent either as a
   JSON-RPC notification (``notifications/message``) or as a ``_hooks``
   field on the next ``tools/call`` response.

Performance target: <500 ms added latency to the original tool call. The
hook itself runs entirely in a ThreadPoolExecutor so the tool response is
returned to the agent immediately; the only synchronous cost is the
argument inspection that decides whether to fire the hook at all (<<1 ms).

Configuration (``.codelens/hooks.json``):

.. code-block:: json

    {
      "hooks": {
        "post_tool": {
          "enabled": false,
          "severity_threshold": "high"
        }
      }
    }

All hooks default to ``enabled: false`` — users must opt in explicitly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# ─── Module-level constants ───────────────────────────────────────────

#: Severity ordering — lower index = more severe. Used both for the
#: ``severity_threshold`` comparison and to bucket findings.
SEVERITY_ORDER: Dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

#: Default config block written into ``.codelens/hooks.json`` when the
#: file does not exist yet. Every hook defaults to *disabled* — opt-in.
DEFAULT_CONFIG: Dict[str, Any] = {
    "hooks": {
        "post_tool": {
            "enabled": False,
            "severity_threshold": "high",
        }
    }
}

#: Engine commands the hook consults to surface new findings. Each entry
#: is (command_name, result_key, severity_for_match). The hook invokes the
#: command's ``execute`` function directly (in-process, no subprocess) to
#: stay well under the 500 ms latency budget.
_FINDING_SOURCES: List[Tuple[str, str, str]] = [
    # (engine, key_in_result, default_severity)
    ("smell", "by_category", "high"),
    ("secrets", "findings", "critical"),
    ("complexity", "high_complexity", "high"),
    ("dead-code", "by_category", "medium"),
    ("debug-leak", "by_category", "low"),
]


@dataclass
class PostToolHookResult:
    """Structured result returned by :func:`run_post_tool_hook`.

    Attributes
    ----------
    triggered:
        ``True`` if the hook actually ran (file resolved, scan executed).
        ``False`` for early-exit cases (hook disabled, no file in args).
    file_path:
        Absolute path of the file that was inspected, or ``None``.
    workspace:
        Workspace root the scan was run against.
    severity_threshold:
        Severity level used to filter findings.
    findings:
        List of finding dicts (one per matching finding) for debugging.
    critical_count / high_count:
        Bucketed counts of the two severities the hook surfaces to the
        agent. Lower severities are intentionally ignored.
    message:
        Human-readable message intended for the agent. Empty when nothing
        was found or the hook did not run.
    error:
        ``None`` on success, otherwise a short description of why the hook
        could not complete (file missing, scan failed, …). Errors never
        raise — the hook is non-blocking and must not crash the MCP
        server.
    elapsed_ms:
        Wall-clock time spent inside the hook, measured in milliseconds.
    """

    triggered: bool = False
    file_path: Optional[str] = None
    workspace: Optional[str] = None
    severity_threshold: str = "high"
    findings: List[Dict[str, Any]] = field(default_factory=list)
    critical_count: int = 0
    high_count: int = 0
    message: str = ""
    error: Optional[str] = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (dataclasses.asdict wrapper)."""
        return asdict(self)


# ─── Argument inspection ─────────────────────────────────────────────


def extract_file_path(arguments: Dict[str, Any], workspace: str) -> Optional[str]:
    """Best-effort extraction of a file path from MCP tool call arguments.

    The hook is generic over every CodeLens MCP tool, so we inspect the
    common argument names that carry a file path: ``file``, ``path``,
    ``file_path``. Both absolute and workspace-relative paths are
    accepted; relative paths are resolved against ``workspace``.

    Returns ``None`` when no file argument is present or the resolved
    path does not exist on disk. Returning ``None`` is the signal to the
    HookManager that the hook should not fire for this tool call.
    """
    if not isinstance(arguments, dict):
        return None
    for key in ("file", "path", "file_path", "filename"):
        value = arguments.get(key)
        if not value or not isinstance(value, str):
            continue
        candidate = value
        if not os.path.isabs(candidate) and workspace:
            candidate = os.path.join(workspace, candidate)
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            return candidate
        # Some commands accept a file substring filter rather than a real
        # path. Try to resolve it inside the workspace.
        if workspace:
            alt = os.path.join(workspace, value)
            if os.path.isfile(alt):
                return os.path.normpath(alt)
    return None


# ─── Finding collection ──────────────────────────────────────────────


def _matches_file(finding: Any, file_path: str, workspace: str) -> bool:
    """Return ``True`` if a finding struct references ``file_path``."""
    if not isinstance(finding, dict):
        return False
    haystack_keys = ("file", "path", "file_path", "filename", "source", "location")
    rel_path = ""
    try:
        rel_path = os.path.relpath(file_path, workspace).replace(os.sep, "/")
    except ValueError:
        pass
    norm_path = file_path.replace(os.sep, "/")
    base_name = os.path.basename(file_path)
    for key in haystack_keys:
        val = finding.get(key)
        if not isinstance(val, str):
            continue
        val_norm = val.replace(os.sep, "/")
        if val_norm == norm_path or val_norm == rel_path or val_norm.endswith("/" + base_name):
            return True
        # Substring match — many engines store relative paths.
        if rel_path and rel_path in val_norm:
            return True
        if base_name and base_name == os.path.basename(val_norm):
            return True
    return False


def _severity_of(finding: Dict[str, Any], default: str) -> str:
    """Resolve a finding's severity, falling back to ``default``."""
    sev = finding.get("severity") or finding.get("level") or default
    if isinstance(sev, str):
        sev = sev.lower().strip()
        if sev in SEVERITY_ORDER:
            return sev
    return default


def collect_findings_for_file(
    workspace: str,
    file_path: str,
    severity_threshold: str = "high",
) -> List[Dict[str, Any]]:
    """Run the lightweight analysis engines and return matching findings.

    Only findings whose severity is at or above ``severity_threshold`` AND
    whose ``file`` field references ``file_path`` are returned. The
    engines are imported lazily so importing :mod:`mcp_hooks.post_tool`
    has no cost when hooks are disabled.
    """
    threshold_idx = SEVERITY_ORDER.get(
        str(severity_threshold).lower(), SEVERITY_ORDER["high"]
    )
    matched: List[Dict[str, Any]] = []

    # Lazy import — keeps the module import-cheap for disabled-hook case.
    from commands import get_all_commands  # type: ignore

    try:
        registry = get_all_commands()
    except Exception:
        return matched

    # Reuse the _ArgsNamespace shim from the MCP server so we can invoke
    # each command's execute() with the right shape.
    from mcp_server import _ArgsNamespace  # type: ignore

    args_ns = _ArgsNamespace({"file": file_path}, workspace)
    # Some engines look at args.file; others scan the whole workspace and
    # let us filter findings by file afterwards. We do both.

    for cmd_name, result_key, default_sev in _FINDING_SOURCES:
        cmd_info = registry.get(cmd_name)
        if not cmd_info or "execute" not in cmd_info:
            continue
        try:
            result = cmd_info["execute"](args_ns, workspace)
        except Exception:
            # Engine failures must never break the hook.
            continue
        if not isinstance(result, dict):
            continue
        bucket = result.get(result_key)
        items: List[Any] = []
        if isinstance(bucket, list):
            items = bucket
        elif isinstance(bucket, dict):
            for sub in bucket.values():
                if isinstance(sub, list):
                    items.extend(sub)
        elif result_key == "by_category" and isinstance(bucket, dict):
            items = [i for sub in bucket.values() if isinstance(sub, list) for i in sub]
        for item in items:
            if not isinstance(item, dict):
                continue
            sev = _severity_of(item, default_sev)
            if SEVERITY_ORDER.get(sev, 99) > threshold_idx:
                continue
            if _matches_file(item, file_path, workspace):
                item_copy = dict(item)
                item_copy.setdefault("severity", sev)
                item_copy.setdefault("source_engine", cmd_name)
                matched.append(item_copy)

    return matched


# ─── Public entry point ──────────────────────────────────────────────


def run_post_tool_hook(
    arguments: Dict[str, Any],
    workspace: str,
    severity_threshold: str = "high",
) -> PostToolHookResult:
    """Run the post_tool hook for a single MCP tool call.

    This function is *the* contract between :class:`HookManager` and the
    hook. It is intentionally synchronous — the HookManager wraps the
    call in a ThreadPoolExecutor so callers never block.

    Parameters
    ----------
    arguments:
        The MCP tool call arguments dict (``params.arguments``).
    workspace:
        Absolute path to the workspace root. Used to resolve relative
        file paths and as the scan target.
    severity_threshold:
        Findings below this severity are ignored. Defaults to ``high``.

    Returns
    -------
    PostToolHookResult
        Always returns — never raises. Any internal error is captured in
        ``PostToolHookResult.error``.
    """
    import time

    start = time.monotonic()
    result = PostToolHookResult(
        workspace=workspace,
        severity_threshold=str(severity_threshold).lower(),
    )

    if not workspace or not os.path.isdir(workspace):
        result.error = "workspace not found"
        result.elapsed_ms = (time.monotonic() - start) * 1000.0
        return result

    file_path = extract_file_path(arguments, workspace)
    if not file_path:
        # No file in args → nothing to do. Not an error.
        result.elapsed_ms = (time.monotonic() - start) * 1000.0
        return result

    result.file_path = file_path
    result.triggered = True

    try:
        # 1. Incremental scan so the registry reflects the just-written file.
        #    The scan command does not accept a ``--file`` flag, so we run an
        #    incremental workspace scan (cheap when only one file changed).
        from commands.scan import cmd_scan  # type: ignore

        cmd_scan(workspace, incremental=True)

        # 2. Collect findings for the target file from the lightweight engines.
        findings = collect_findings_for_file(
            workspace, file_path, result.severity_threshold
        )
        result.findings = findings
        for f in findings:
            sev = _severity_of(f, "medium")
            if sev == "critical":
                result.critical_count += 1
            elif sev == "high":
                result.high_count += 1

        # 3. Build the agent-facing message. Only critical/high counts are
        #    surfaced to keep the message short (issue #47 spec).
        if result.critical_count or result.high_count:
            short = os.path.basename(file_path)
            parts = []
            if result.critical_count:
                parts.append(f"{result.critical_count} critical")
            if result.high_count:
                parts.append(f"{result.high_count} high")
            result.message = (
                f"⚠️ post_tool hook: {' and '.join(parts)} "
                f"finding(s) in {short}"
            )
    except Exception as exc:  # pragma: no cover — defensive guard
        # Hook failures must never propagate to the MCP server.
        result.error = f"{type(exc).__name__}: {exc}"
        try:
            print(f"[CodeLens MCP] post_tool hook error: {exc}", file=sys.stderr)
        except Exception:
            pass

    result.elapsed_ms = (time.monotonic() - start) * 1000.0
    return result


__all__ = [
    "PostToolHookResult",
    "run_post_tool_hook",
    "extract_file_path",
    "collect_findings_for_file",
    "DEFAULT_CONFIG",
    "SEVERITY_ORDER",
]
