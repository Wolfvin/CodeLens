# @WHO:   scripts/commands/source.py
# @WHAT:  `context --check source` — return a function's source by name
# @PART:  command (sub-check of `context`)
# @ENTRY: execute()
"""`context --check source --name X` — a function's source, by name.

The most direct replacement for "Read the whole file to see one function":
resolve X to its file and start line, bound it by the next declaration, and
return just those lines. Read-only. Boundaries are heuristic — the next
declaration in the file, or EOF — which is exact for the common case and
never guesses beyond a file's own structure.
"""

import os
from typing import Any, Dict, List

from outline_engine import get_file_outline


def add_args(parser):
    """Register CLI arguments (workspace/name/file carried by the umbrella)."""
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )


def _symbol_lines(outline: Dict) -> List[int]:
    """Every declaration line in a file, sorted — the boundary candidates."""
    lines = []
    for section in ("functions", "classes"):
        for entry in outline.get(section, []):
            if isinstance(entry.get("line"), int):
                lines.append(entry["line"])
    return sorted(set(lines))


def _extract(abs_file: str, rel_file: str, workspace: str,
             start: int, name: str) -> Dict[str, Any]:
    """Slice one function's source from its start line to the next declaration."""
    res = get_file_outline(abs_file, workspace, "normal")
    outline = res.get("outline") or {}
    line_count = outline.get("line_count", 0)

    decl_lines = _symbol_lines(outline)
    end = line_count
    for ln in decl_lines:
        if ln > start:
            end = ln - 1
            break

    try:
        with open(abs_file, "r", encoding="utf-8", errors="replace") as f:
            file_lines = f.read().splitlines()
    except OSError as e:
        return {"symbol": name, "file": rel_file, "error": str(e)}

    body = file_lines[start - 1:end]
    # Drop blank lines between this function and the next declaration.
    while body and not body[-1].strip():
        body.pop()
        end -= 1
    return {
        "symbol": name,
        "file": rel_file,
        "start_line": start,
        "end_line": end,
        "source": "\n".join(body),
    }


def execute(args, workspace) -> Dict[str, Any]:
    """Return the source of function(s) named ``--name``.

    @FLOW:    SOURCE_VIEW
    @CALLS:   graph_model.find_nodes_by_name(), outline_engine.get_file_outline()
    @MUTATES: nothing (read-only)
    """
    name = getattr(args, "name", None)
    if not name:
        return {
            "status": "error",
            "error": "source needs --name X (the function to show)",
            "error_type": "missing_argument",
        }

    workspace = os.path.abspath(workspace) if workspace else os.getcwd()
    only_file = getattr(args, "file", None)

    # Resolve where X is defined: an explicit --file needs no graph; otherwise
    # ask the call-graph (populated by a prior scan).
    locations = []  # (abs_file, rel_file, start_line)
    if only_file:
        abs_file = only_file if os.path.isabs(only_file) else os.path.join(workspace, only_file)
        res = get_file_outline(abs_file, workspace, "normal")
        outline = res.get("outline") or {}
        for fn in outline.get("functions", []):
            if fn.get("name") == name and isinstance(fn.get("line"), int):
                locations.append((abs_file, os.path.relpath(abs_file, workspace), fn["line"]))
    else:
        try:
            from utils import default_db_path
            import graph_model as gm
        except Exception:
            return {"status": "error",
                    "error": "graph unavailable; pass --file to locate the function",
                    "error_type": "no_graph"}
        db = getattr(args, "db_path", None) or default_db_path(workspace)
        if not db or not os.path.exists(db):
            return {"status": "error",
                    "error": "no graph DB — scan the workspace first, or pass --file",
                    "error_type": "no_graph"}
        for node in gm.find_nodes_by_name(name, db):
            rel = node.get("file", "")
            if not rel:
                continue
            abs_file = rel if os.path.isabs(rel) else os.path.join(workspace, rel)
            line = node.get("line")
            if isinstance(line, int) and line > 0 and os.path.exists(abs_file):
                locations.append((abs_file, rel.replace("\\", "/"), line))

    if not locations:
        where = f" in {only_file}" if only_file else ""
        return {"status": "ok", "symbol": name, "found": False,
                "message": f"No function named '{name}' found{where}. "
                           "If the workspace was never scanned, run scan first or pass --file."}

    matches = [_extract(a, r, workspace, ln, name) for a, r, ln in locations]
    return {
        "status": "ok",
        "symbol": name,
        "found": True,
        "count": len(matches),
        "matches": matches,
    }
