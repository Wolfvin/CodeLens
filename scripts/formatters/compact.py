"""Compact output formatter for CodeLens — token-efficient JSON for MCP tools (issue #17).

Goal: shrink MCP tool output 40-70% by:
  1. Omitting null/empty fields (agents pay tokens for every byte).
  2. Abbreviating edge and node types to single characters.
  3. Using short single-character keys for common fields.
  4. Stripping the workspace prefix from absolute paths.

Output is still valid JSON so MCP clients can parse it directly. The
abbreviations are stable and documented below so an agent that reads
``format: 'compact'`` once can decode the payload without a lookup table.

Key abbreviations:
    Node types:  function->fn  class->cls  file->f  module->m
                 route->r  type->t  interface->i
                 (anything else -> first 2 chars of the type, lowercased)
    Edge types:  CALLS->C  IMPORTS->I  DEFINES->D  INHERITS->H
                 IMPLEMENTS->M  USES_TYPE->U  (anything else -> first char)
    Field keys:  name->n  file->f  line->l  type->t  status->s
                 confidence->c  depth->d  resolved->r  domain->d
                 direction->dir  symbol->sym  max_depth->md
                 total->tot  count->cnt  offset->off  limit->lim
                 has_more->more  truncated->trunc  matches->m
                 results->r  chains->ch  stats->st  items->i
                 callers_found->up  callees_found->dn
                 workspace->ws  pattern->pat  query->q

The formatter is intentionally additive: ``--format json/ai/markdown/sarif``
keep their existing behavior, and ``--format compact`` is the new 5th choice.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple


# ─── Abbreviation Maps ────────────────────────────────────────

#: Map full node type strings to single-char abbreviations.
NODE_TYPE_ABBR: Dict[str, str] = {
    "function": "fn",
    "class": "cls",
    "file": "f",
    "module": "m",
    "route": "r",
    "type": "t",
    "interface": "i",
}

#: Map full edge type strings to single-char abbreviations.
EDGE_TYPE_ABBR: Dict[str, str] = {
    "CALLS": "C",
    "IMPORTS": "I",
    "DEFINES": "D",
    "INHERITS": "H",
    "IMPLEMENTS": "M",
    "USES_TYPE": "U",
}

#: Map verbose field names to short keys. Applied recursively to dicts.
FIELD_KEY_ABBR: Dict[str, str] = {
    "name": "n",
    "file": "f",
    "line": "l",
    "type": "t",
    "status": "s",
    "confidence": "c",
    "depth": "d",
    "resolved": "r",
    "domain": "dom",
    "direction": "dir",
    "symbol": "sym",
    "max_depth": "md",
    "total": "tot",
    "count": "cnt",
    "offset": "off",
    "limit": "lim",
    "has_more": "more",
    "truncated": "trunc",
    "matches": "m",
    "results": "r",
    "chains": "ch",
    "stats": "st",
    "items": "i",
    "callers_found": "up",
    "callees_found": "dn",
    "workspace": "ws",
    "pattern": "pat",
    "query": "q",
    "node_id": "id",
    "node_type": "nt",
    "edge_type": "et",
    "source_id": "src",
    "target_id": "tgt",
    "affected_files": "af",
    "affected_file_list": "afl",
    "files_searched": "fs",
    "files_matched": "fm",
    "total_matches": "tm",
    "by_type": "bt",
    "by_status": "bs",
    "summary": "sum",
    "ref_count": "rc",
    "defined_in": "di",
    "locations": "loc",
    "location": "loc",
    "async": "as",
    "impl_for": "if",
    "component": "cmp",
    "superclasses": "sc",
    "filter": "flt",
    "fuzzy": "fz",
    "health_score": "hs",
    "total_findings": "tf",
    "recommendations": "rec",
    "command": "cmd",
    "error": "err",
    "error_type": "et",
    "suggestion": "sug",
    "truncation_note": "tn",
    "node": "nd",
    "tree": "tr",
    "errors": "errs",
    "files_outlined": "fo",
    "total_lines": "tl",
    "outlines": "ols",
    "edges": "e",
    "nodes": "n",
    "node_types": "nts",
    "edge_types": "ets",
    "indexes": "ix",
}


# ─── Helpers ──────────────────────────────────────────────────


def _is_empty(value: Any) -> bool:
    """Return True for None, empty list, empty dict, empty string."""
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def _abbreviate_value(key: str, value: Any) -> Any:
    """Abbreviate edge/node type strings in-place based on the field key."""
    if not isinstance(value, str):
        return value
    if key in ("edge_type", "et", "type") and value in EDGE_TYPE_ABBR:
        # Note: 'type' is ambiguous — it can be a node_type or a generic
        # type. We only abbreviate when the value matches a known edge
        # type (which is uppercase by convention). Node types are lowercase.
        return EDGE_TYPE_ABBR[value]
    if key in ("node_type", "nt") and value in NODE_TYPE_ABBR:
        return NODE_TYPE_ABBR[value]
    if key == "type" and value in NODE_TYPE_ABBR:
        # Lowercase node types like 'function', 'class', etc.
        return NODE_TYPE_ABBR[value]
    return value


def _strip_workspace_prefix(path: str, workspace: str) -> str:
    """Strip the workspace prefix from an absolute path.

    ``/home/user/proj/src/app.py`` with workspace ``/home/user/proj``
    becomes ``src/app.py``. Relative paths and non-matching absolute
    paths are returned unchanged. Empty values pass through.
    """
    if not path or not workspace:
        return path
    # Only strip when path is absolute and starts with the workspace.
    if not os.path.isabs(path):
        return path
    workspace_abs = os.path.abspath(workspace)
    # Try with trailing separator to avoid partial matches (e.g.
    # workspace=/foo/bar matching path=/foo/barbaz).
    prefix = workspace_abs
    if not prefix.endswith(os.sep):
        prefix += os.sep
    if path.startswith(prefix):
        return path[len(prefix):]
    if path == workspace_abs:
        return ""
    return path


def _compact_value(value: Any, workspace: str, depth: int = 0) -> Any:
    """Recursively compact a single value (dict, list, or scalar).

    - Drops null/empty fields from dicts.
    - Abbreviates keys, node types, and edge types.
    - Strips the workspace prefix from string values that look like paths.
    """
    if depth > 20:
        # Guard against pathological self-referential structures.
        return value
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            compacted_v = _compact_value(v, workspace, depth + 1)
            if _is_empty(compacted_v):
                continue
            short_k = FIELD_KEY_ABBR.get(k, k)
            compacted_v = _abbreviate_value(k, compacted_v)
            out[short_k] = compacted_v
        return out
    if isinstance(value, list):
        return [_compact_value(item, workspace, depth + 1) for item in value]
    if isinstance(value, str):
        # Heuristic: only strip workspace prefix from strings that look like
        # absolute paths under the workspace. Other strings (names, statuses)
        # are left alone.
        if value.startswith(workspace) or (
            os.path.isabs(value) and workspace and value.startswith(
                os.path.abspath(workspace)
            )
        ):
            return _strip_workspace_prefix(value, workspace)
        return value
    return value


# ─── Public API ───────────────────────────────────────────────


def format_compact(result: Any, command: str = "", workspace: str = "") -> str:
    """Format a CodeLens command result as a token-efficient compact JSON string.

    Args:
        result: The dict (or list/scalar) returned by a CodeLens command.
        command: The command name (e.g. ``trace``). Currently informational
                 — the same abbreviation rules apply to all commands.
        workspace: Absolute path to the workspace. Used to strip the
                   workspace prefix from absolute paths in the output.

    Returns:
        A JSON string with single-char keys, abbreviated types, and no
        null/empty fields. Always parseable by standard JSON parsers.
    """
    compacted = _compact_value(result, workspace)
    # Use compact JSON separators (no whitespace) for maximum token savings.
    # ensure_ascii=False keeps non-ASCII source identifiers readable.
    return json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))


def compact_dict(result: Any, workspace: str = "") -> Any:
    """Return the compacted Python value (not a JSON string).

    Useful for MCP server responses where the transport layer does its own
    JSON serialization, and for tests that want to assert on the structure
    rather than the string.
    """
    return _compact_value(result, workspace)
