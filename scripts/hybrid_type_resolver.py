"""Hybrid Type Resolution — import-aware call edge refinement (issue #13).

This module is a post-scan pass that enriches CALLS edges in ``graph_edges``
with receiver type information. The existing ``typeinfer_engine`` does
lightweight per-file type inference but does not track import chains, so
calls like ``user.profile.update()`` get recorded as a call to ``update``
with no target type. The call graph has holes wherever methods are called
on imported objects.

Hybrid type resolution fills those holes by:

1. Building a per-file import registry (``from X import Y``, ``import X.Y``,
   ``import {Y} from 'X'``, ``import * as X from 'Y'``).
2. Resolving the receiver type at each call site via the import registry
   (simple receivers) plus local-variable type inference
   (``user = User(...)``) and class attribute type traversal
   (``user.profile`` -> the ``Profile`` type declared on ``User``).
3. Refining CALLS edges in place: setting ``target_id`` to the resolved
   method node and stamping ``resolved_type`` / ``resolution_method`` into
   ``extra_json`` for auditability.

Everything here is best-effort. Unresolvable cases return ``None`` and the
caller moves on — type resolution MUST NOT crash the scan pipeline.

Priority languages (per issue #13): Python (dotted imports, attribute
annotations) and TypeScript/JavaScript (ES module imports). Other languages
are skipped silently.
"""

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from utils import DEFAULT_IGNORE_DIRS, logger


# ─── Schema Constants ────────────────────────────────────────

IMPORT_REGISTRY_TABLE = "import_registry"

_CREATE_IMPORT_REGISTRY = """
CREATE TABLE IF NOT EXISTS {table} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file        TEXT NOT NULL,
    local_name  TEXT NOT NULL,
    module_path TEXT,
    symbol_name TEXT,
    line        INTEGER
)
""".format(table=IMPORT_REGISTRY_TABLE)

_CREATE_IMPORT_REGISTRY_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_import_registry_file "
    "ON {t}(file)".format(t=IMPORT_REGISTRY_TABLE),
    "CREATE INDEX IF NOT EXISTS idx_import_registry_file_local "
    "ON {t}(file, local_name)".format(t=IMPORT_REGISTRY_TABLE),
]


# ─── Source File Extensions ─────────────────────────────────

_PY_EXTENSIONS = {".py"}
_TS_EXTENSIONS = {".ts", ".tsx", ".jsx", ".js", ".mjs", ".cjs"}


# ─── Import Statement Patterns ──────────────────────────────

# Python: from X import Y [as Z], A as B, *  (single line, no parens)
_PY_FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+([\w.]+)\s+import\s+(.+?)\s*(?:#.*)?$"
)
# Python: import X[.Y] [as Z]
_PY_IMPORT_RE = re.compile(
    r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*(?:#.*)?$"
)
# Python: import X, Y  (multiple imports on one line)
_PY_MULTI_IMPORT_RE = re.compile(
    r"^\s*import\s+(.+?)\s*(?:#.*)?$"
)
_PY_NAME_CLAUSE_RE = re.compile(r"^(\w+)(?:\s+as\s+(\w+))?$")

# TS/JS: import {A [as B], C} from 'X'
_TS_NAMED_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]\s*;?\s*$"""
)
# TS/JS: import * as X from 'Y'
_TS_NAMESPACE_IMPORT_RE = re.compile(
    r"""^\s*import\s+\*\s+as\s+(\w+)\s+from\s+['"]([^'"]+)['"]\s*;?\s*$"""
)
# TS/JS: import X from 'Y'   (default import — must come after namespace/named)
_TS_DEFAULT_IMPORT_RE = re.compile(
    r"""^\s*import\s+(\w+)\s+from\s+['"]([^'"]+)['"]\s*;?\s*$"""
)
# TS/JS: import X, {A, B} from 'Y'   (mixed default + named)
_TS_MIXED_IMPORT_RE = re.compile(
    r"""^\s*import\s+(\w+)\s*,\s*\{([^}]+)\}\s+from\s+['"]([^'"]+)['"]\s*;?\s*$"""
)


# ─── Local Variable Type Inference Patterns ─────────────────

# Python: var = Constructor(...)
_PY_LOCAL_VAR_RE = re.compile(
    r"^\s*(\w+)\s*=\s*([A-Za-z_]\w*)\s*\("
)
# TS/JS: const/let/var var = [new] Constructor(...)
_TS_LOCAL_VAR_RE = re.compile(
    r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:new\s+)?([A-Za-z_$][\w$]*)\s*[\(]"
)


# ─── Class Attribute Type Patterns ──────────────────────────

# Python: self.attr: Type = ...    (annotated attribute — PEP 526)
_PY_ANNOTATED_ATTR_RE = re.compile(
    r"self\.(\w+)\s*:\s*([A-Za-z_][\w.]*)"
)
# Python: self.attr = Constructor(...)    (inferred from RHS)
_PY_INFERRED_ATTR_RE = re.compile(
    r"self\.(\w+)\s*=\s*(?:new\s+)?([A-Za-z_]\w*)\s*\("
)


# ─── Call Site Receiver Extraction ──────────────────────────

# Matches `<receiver>.<method>(...)` where receiver may be dotted.
# Used to extract the receiver expression from a call site.
_CALL_RECEIVER_RE_TEMPLATE = r"([A-Za-z_][\w.]*)\s*\.\s*{method}\s*\("


# ─── Schema Initialization ──────────────────────────────────


def _ensure_import_registry_schema(conn: sqlite3.Connection) -> None:
    """Create the import_registry table + indexes if missing (idempotent).

    Safe to call repeatedly. Called by ``build_import_registry`` before
    populating rows.

    Args:
        conn: Open sqlite3.Connection. Caller owns commit/close.
    """
    try:
        conn.execute(_CREATE_IMPORT_REGISTRY)
        for sql in _CREATE_IMPORT_REGISTRY_INDEXES:
            conn.execute(sql)
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("import_registry schema init error: %s", exc)


# ─── Import Statement Parsing ───────────────────────────────


def _strip_inline_comment_py(line: str) -> str:
    """Strip an inline ``# ...`` comment from a Python line.

    Naive — does not track string literals. Sufficient for import lines
    where ``#`` outside a string is overwhelmingly the comment case.
    """
    # Find the first # that is not inside a string. Cheap heuristic: count
    # quotes before the # position. If odd, # is inside a string.
    for i, ch in enumerate(line):
        if ch != "#":
            continue
        before = line[:i]
        if before.count('"') % 2 == 0 and before.count("'") % 2 == 0:
            return line[:i]
    return line


def _parse_py_imports(content: str) -> List[Tuple[str, Optional[str], str, int]]:
    """Extract import bindings from Python source.

    Handles:
      * ``from X import Y``
      * ``from X import Y as Z``
      * ``from X import A, B as C``
      * ``from X import (A, B)``  (parenthesized multi-line)
      * ``import X``
      * ``import X.Y``
      * ``import X.Y as Z``
      * ``import X, Y``  (multiple imports on one line)
      * ``from X import *``  (wildcard — recorded as ``local_name="*"``)

    Returns:
        List of ``(local_name, module_path, symbol_name, line)`` tuples.
        ``module_path`` is the dotted module path (e.g. ``src.utils``).
        For ``import X.Y``, ``symbol_name`` is the last segment (``Y``)
        and ``local_name`` is ``X`` unless aliased.
    """
    results: List[Tuple[str, Optional[str], str, int]] = []
    lines = content.split("\n")

    i = 0
    while i < len(lines):
        line_num = i + 1
        line = lines[i]
        stripped = _strip_inline_comment_py(line).rstrip()
        if not stripped.strip():
            i += 1
            continue

        # from X import ...
        m = _PY_FROM_IMPORT_RE.match(stripped)
        if m:
            module_path = m.group(1)
            names_part = m.group(2).strip()
            # Handle parenthesized multi-line: from X import (\n A, B \n)
            if names_part.startswith("(") and ")" not in names_part:
                # Collect continuation lines until the closing paren
                collected = names_part
                j = i + 1
                while j < len(lines) and ")" not in lines[j]:
                    collected += " " + _strip_inline_comment_py(lines[j]).strip()
                    j += 1
                if j < len(lines):
                    collected += " " + _strip_inline_comment_py(lines[j]).strip()
                    i = j
                names_part = collected.strip().strip("()").strip()
            elif names_part.startswith("("):
                names_part = names_part.strip("()").strip()
            elif names_part.endswith("\\"):
                # Continuation: from X import A, \
                #               B, C
                names_part = names_part.rstrip("\\").strip()
                j = i + 1
                while j < len(lines) and (lines[j].rstrip().endswith("\\") or
                                          _strip_inline_comment_py(lines[j]).strip()):
                    cont = _strip_inline_comment_py(lines[j]).rstrip()
                    if cont.endswith("\\"):
                        names_part += " " + cont[:-1].strip()
                    else:
                        names_part += " " + cont.strip()
                        i = j
                        break
                    j += 1
            for name_clause in names_part.split(","):
                name_clause = name_clause.strip()
                if not name_clause:
                    continue
                if name_clause == "*":
                    results.append(("*", module_path, "*", line_num))
                    continue
                m2 = _PY_NAME_CLAUSE_RE.match(name_clause)
                if m2:
                    symbol_name = m2.group(1)
                    local_name = m2.group(2) or symbol_name
                    results.append((local_name, module_path, symbol_name, line_num))
            i += 1
            continue

        # import X.Y [as Z]  (single import)
        m = _PY_IMPORT_RE.match(stripped)
        if m:
            full_path = m.group(1)
            local_name = m.group(2) or full_path.split(".")[0]
            results.append(
                (local_name, full_path, full_path.split(".")[-1], line_num)
            )
            i += 1
            continue

        # import X, Y, Z  (multiple imports on one line, no `as`)
        m = _PY_MULTI_IMPORT_RE.match(stripped)
        if m and "," in m.group(1):
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            for part in parts:
                m3 = re.match(r"^([\w.]+)(?:\s+as\s+(\w+))?$", part)
                if m3:
                    full_path = m3.group(1)
                    local_name = m3.group(2) or full_path.split(".")[0]
                    results.append(
                        (local_name, full_path, full_path.split(".")[-1], line_num)
                    )
            i += 1
            continue

        i += 1

    return results


def _collapse_ts_continuations(content: str) -> str:
    """Collapse multi-line TS/JS import statements into single lines.

    ES module imports frequently span multiple lines::

        import {
          Foo,
          Bar,
        } from './mymodule';

    This function joins such continuations so the single-line regexes
    above can match them. Only collapses inside import statements;
    other multi-line constructs are left intact.
    """
    out_lines: List[str] = []
    buf: List[str] = []
    in_import = False
    brace_depth = 0

    for line in content.split("\n"):
        stripped = line.strip()
        if not in_import:
            if stripped.startswith("import ") and "{" in stripped and "}" not in stripped:
                # Begin multi-line named import
                in_import = True
                brace_depth = stripped.count("{") - stripped.count("}")
                buf.append(line)
                continue
            out_lines.append(line)
        else:
            buf.append(line)
            brace_depth += stripped.count("{") - stripped.count("}")
            if brace_depth <= 0 and "from" in stripped:
                # Closing brace + from clause on this line — flush
                out_lines.append(" ".join(b.strip() for b in buf))
                buf = []
                in_import = False
            elif brace_depth <= 0 and "from" not in stripped:
                # Closing brace but no `from` yet — keep accumulating
                # (rare). The next non-empty line should have `from`.
                pass
    if buf:
        # Unterminated import — flush what we have
        out_lines.append(" ".join(b.strip() for b in buf))
    return "\n".join(out_lines)


def _parse_ts_imports(content: str) -> List[Tuple[str, Optional[str], str, int]]:
    """Extract import bindings from TypeScript/JavaScript source.

    Handles:
      * ``import {A, B as C} from 'X'``
      * ``import * as X from 'Y'``
      * ``import X from 'Y'``  (default import)
      * ``import X, {A, B} from 'Y'``  (mixed default + named)
      * Multi-line variants of all of the above.

    Returns:
        List of ``(local_name, module_path, symbol_name, line)`` tuples.
        For namespace imports (``import * as X``), ``local_name`` is ``X``
        and ``symbol_name`` is ``"*"`` (the whole module namespace).
        For default imports, ``symbol_name`` is ``"default"``.
    """
    results: List[Tuple[str, Optional[str], str, int]] = []
    collapsed = _collapse_ts_continuations(content)

    for line_num, line in enumerate(collapsed.split("\n"), 1):
        stripped = line.strip()
        if not stripped.startswith("import"):
            continue

        # import * as X from 'Y'
        m = _TS_NAMESPACE_IMPORT_RE.match(line)
        if m:
            local_name = m.group(1)
            module_path = m.group(2)
            results.append((local_name, module_path, "*", line_num))
            continue

        # import X, {A, B} from 'Y'  (mixed default + named)
        m = _TS_MIXED_IMPORT_RE.match(line)
        if m:
            default_local = m.group(1)
            named_part = m.group(2)
            module_path = m.group(3)
            results.append((default_local, module_path, "default", line_num))
            for name_clause in named_part.split(","):
                name_clause = name_clause.strip()
                if not name_clause:
                    continue
                m2 = re.match(r"^(\w+)(?:\s+as\s+(\w+))?$", name_clause)
                if m2:
                    symbol_name = m2.group(1)
                    local_name = m2.group(2) or symbol_name
                    results.append((local_name, module_path, symbol_name, line_num))
            continue

        # import {A, B as C} from 'X'
        m = _TS_NAMED_IMPORT_RE.match(line)
        if m:
            named_part = m.group(1)
            module_path = m.group(2)
            for name_clause in named_part.split(","):
                name_clause = name_clause.strip()
                if not name_clause:
                    continue
                # Skip TypeScript `type` modifier: import { type Foo }
                if name_clause.startswith("type "):
                    name_clause = name_clause[5:].strip()
                m2 = re.match(r"^(\w+)(?:\s+as\s+(\w+))?$", name_clause)
                if m2:
                    symbol_name = m2.group(1)
                    local_name = m2.group(2) or symbol_name
                    results.append((local_name, module_path, symbol_name, line_num))
            continue

        # import X from 'Y'  (default import)
        m = _TS_DEFAULT_IMPORT_RE.match(line)
        if m:
            local_name = m.group(1)
            module_path = m.group(2)
            results.append((local_name, module_path, "default", line_num))
            continue

    return results


# ─── Module Path → File Path Resolution ─────────────────────


def _resolve_py_module_to_file(module_path: str, workspace: str) -> Optional[str]:
    """Resolve a Python dotted module path to a workspace-relative file path.

    Tries, in order:
      1. ``<module_path with / replaced>.py``
      2. ``<module_path with / replaced>/__init__.py``

    Returns the relative path if a matching file exists on disk, else
    ``None``. External modules (e.g. ``os``, ``typing``) return ``None``.
    """
    rel = module_path.replace(".", os.sep)
    candidates = [rel + ".py", os.path.join(rel, "__init__.py")]
    for cand in candidates:
        if os.path.isfile(os.path.join(workspace, cand)):
            return cand
    return None


def _resolve_ts_module_to_file(
    module_path: str, importing_file_rel: str, workspace: str
) -> Optional[str]:
    """Resolve a TS/JS module specifier to a workspace-relative file path.

    Handles:
      * Relative specifiers: ``./foo``, ``../foo``, ``./foo/bar``
      * Bare specifiers: ``react``, ``lodash`` — returns ``None`` (external)

    Tries extensions in order: ``.ts``, ``.tsx``, ``.js``, ``.jsx``,
    ``.mjs``, ``.cjs``, plus ``/index.<ext>`` for each.

    Args:
        module_path: The string inside the quotes in the import statement.
        importing_file_rel: Workspace-relative path of the importing file
            (used to resolve relative specifiers).
        workspace: Absolute workspace root.
    """
    if not module_path.startswith("."):
        # Bare specifier — external package, skip.
        return None
    importer_dir = os.path.dirname(importing_file_rel)
    base = os.path.normpath(os.path.join(importer_dir, module_path))
    exts = [".ts", ".tsx", ".jsx", ".js", ".mjs", ".cjs"]
    for ext in exts:
        cand = base + ext
        if os.path.isfile(os.path.join(workspace, cand)):
            return cand
    for ext in exts:
        cand = os.path.join(base, "index" + ext)
        if os.path.isfile(os.path.join(workspace, cand)):
            return cand
    return None


# ─── File Walking ───────────────────────────────────────────


def _walk_source_files(workspace: str) -> List[Tuple[str, str, str]]:
    """Walk the workspace and return Python + TS/JS source files.

    Args:
        workspace: Absolute workspace root.

    Returns:
        List of ``(abs_path, rel_path, ext)`` tuples. ``ext`` includes the
        leading dot (lowercased). Hidden dirs and ``DEFAULT_IGNORE_DIRS``
        are skipped.
    """
    results: List[Tuple[str, str, str]] = []
    for root, dirs, files in os.walk(workspace):
        # Prune ignored directories in-place so os.walk doesn't descend.
        dirs[:] = [
            d for d in dirs
            if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")
        ]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext in _PY_EXTENSIONS or ext in _TS_EXTENSIONS:
                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, workspace)
                results.append((abs_path, rel_path, ext))
    return results


def _read_file(path: str) -> str:
    """Read a text file, returning '' on any I/O or decode error."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


# ─── Import Registry Build ──────────────────────────────────


def _file_node_id(rel_path: str) -> str:
    """Return the synthetic graph node_id for a file-level IMPORTS edge source.

    IMPORTS edges represent file-level dependencies. Since the graph model
    does not have native file nodes (only function/class/etc.), we use a
    synthetic source_id of the form ``<rel_path>:0:file``. This id does
    NOT have a corresponding ``graph_nodes`` row — it's a dangling
    reference that CALLS-traversal code naturally skips (no node matches
    it). Future ``query_graph`` work (#9, Phase 3) can handle dangling
    source_ids gracefully or promote file nodes to first-class entries.

    The format ``<rel_path>:0:file`` cannot collide with function/class
    node ids (which are ``<rel_path>:<line>`` or
    ``<rel_path>:<line>:<name>``) because the ``:file`` suffix is unique.
    """
    return "{}:0:file".format(rel_path)


def _find_symbol_node(
    conn: sqlite3.Connection, name: str, file_rel: str
) -> Optional[str]:
    """Find a graph_nodes.node_id matching a symbol name in a file.

    Used to resolve the target of an IMPORTS edge. Looks for a node with
    the given ``name`` whose ``file`` column matches ``file_rel``. If
    multiple matches, returns the first (lowest line).

    Args:
        conn: Open sqlite3.Connection.
        name: Symbol name (function, class, etc.).
        file_rel: Workspace-relative file path to match.

    Returns:
        The node_id, or ``None`` if no match.
    """
    try:
        row = conn.execute(
            "SELECT node_id FROM graph_nodes "
            "WHERE name = ? AND file = ? "
            "ORDER BY line ASC LIMIT 1",
            (name, file_rel),
        ).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def build_import_registry(
    workspace: str, db_path: Optional[str] = None
) -> Dict[str, Dict[str, str]]:
    """Build a per-file import registry and write it to SQLite.

    Scans all Python and TS/JS files in the workspace, extracts import
    bindings, and stores them in the new ``import_registry`` SQLite table
    with schema ``(file, local_name, module_path, symbol_name, line)``.
    Also writes IMPORTS edges to ``graph_edges``: source is the importing
    file's synthetic file node, target is the imported symbol's
    graph_nodes entry when resolvable.

    Existing ``import_registry`` rows for the workspace are cleared
    first so re-runs don't accumulate duplicates. Existing IMPORTS edges
    (``edge_type='IMPORTS'``) are also cleared before re-writing.

    Args:
        workspace: Absolute path to the workspace root.
        db_path: Optional SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict mapping ``file_path`` -> ``{local_name: qualified_name}``
        where ``qualified_name`` is ``"<module_path>.<symbol_name>"``
        (or just ``"<module_path>"`` for namespace / wildcard imports).
        Files with no imports are omitted from the dict.
    """
    workspace = os.path.abspath(workspace)
    if db_path is None:
        db_path = os.path.join(workspace, ".codelens", "codelens.db")
    if not os.path.exists(db_path):
        # Nothing to attach to — return empty registry.
        return {}

    conn = sqlite3.connect(db_path)
    try:
        _ensure_import_registry_schema(conn)
        # Ensure graph tables exist too (for IMPORTS edge writes).
        try:
            from graph_model import init_graph_schema
            init_graph_schema(conn)
        except Exception:  # noqa: BLE001 — fail-soft
            logger.debug("graph schema init skipped", exc_info=True)
        # Clear stale rows.
        conn.execute("DELETE FROM {}".format(IMPORT_REGISTRY_TABLE))
        conn.execute(
            "DELETE FROM graph_edges WHERE edge_type = 'IMPORTS'"
        )
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("build_import_registry: clear error: %s", exc)
        conn.close()
        return {}

    registry: Dict[str, Dict[str, str]] = {}

    for abs_path, rel_path, ext in _walk_source_files(workspace):
        content = _read_file(abs_path)
        if not content:
            continue

        if ext in _PY_EXTENSIONS:
            bindings = _parse_py_imports(content)
            module_resolver = lambda mod: _resolve_py_module_to_file(mod, workspace)
        else:
            bindings = _parse_ts_imports(content)
            module_resolver = lambda mod: _resolve_ts_module_to_file(
                mod, rel_path, workspace
            )

        if not bindings:
            continue

        # Use the synthetic file node_id as the IMPORTS edge source.
        # See _file_node_id docstring for why no graph_node row is created.
        file_node_id = _file_node_id(rel_path)
        file_map: Dict[str, str] = {}

        for local_name, module_path, symbol_name, line_num in bindings:
            # Persist to import_registry table.
            try:
                conn.execute(
                    "INSERT INTO {} "
                    "(file, local_name, module_path, symbol_name, line) "
                    "VALUES (?, ?, ?, ?, ?)".format(IMPORT_REGISTRY_TABLE),
                    (rel_path, local_name, module_path, symbol_name, line_num),
                )
            except sqlite3.Error as exc:
                logger.debug("import_registry insert error: %s", exc)
                continue

            qualified = (
                module_path if symbol_name in ("*", "default")
                else "{}.{}".format(module_path, symbol_name)
            )
            if local_name not in ("*",):
                file_map[local_name] = qualified

            # Write an IMPORTS edge. Target is the imported symbol's node
            # if resolvable, else NULL.
            target_id: Optional[str] = None
            if symbol_name not in ("*", "default"):
                target_file = module_resolver(module_path) if module_path else None
                if target_file:
                    target_id = _find_symbol_node(conn, symbol_name, target_file)
            extra = {
                "module_path": module_path,
                "symbol_name": symbol_name,
            }
            try:
                conn.execute(
                    "INSERT INTO graph_edges "
                    "(source_id, target_id, edge_type, file, line, confidence, extra_json) "
                    "VALUES (?, ?, 'IMPORTS', ?, ?, 1.0, ?)",
                    (file_node_id, target_id, rel_path, line_num,
                     json.dumps(extra, default=str)),
                )
            except sqlite3.Error as exc:
                logger.debug("IMPORTS edge insert error: %s", exc)

        if file_map:
            registry[rel_path] = file_map

    try:
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("build_import_registry: commit error: %s", exc)
    finally:
        conn.close()

    return registry


# ─── Local Variable Type Inference ──────────────────────────


def _build_local_var_types(
    content: str, ext: str, import_registry_for_file: Dict[str, str]
) -> Dict[str, str]:
    """Infer local variable types from ``var = Constructor(...)`` patterns.

    Only tracks variables whose constructor name resolves via the file's
    import registry. Returns a mapping ``var_name -> qualified_type``.

    Args:
        content: Source file content.
        ext: File extension (lowercased, with leading dot).
        import_registry_for_file: The file's entry in the import registry
            (``local_name -> qualified_name``).

    Returns:
        Dict mapping local variable names to their resolved qualified
        types. Empty if no patterns match.
    """
    types: Dict[str, str] = {}
    if ext in _PY_EXTENSIONS:
        regex = _PY_LOCAL_VAR_RE
    elif ext in _TS_EXTENSIONS:
        regex = _TS_LOCAL_VAR_RE
    else:
        return types

    for line in content.split("\n"):
        m = regex.match(line)
        if not m:
            continue
        var_name = m.group(1)
        ctor_name = m.group(2)
        # Resolve constructor via import registry.
        qualified = import_registry_for_file.get(ctor_name)
        if qualified:
            types[var_name] = qualified
    return types


# ─── Class Attribute Type Resolution ────────────────────────


def _load_class_body(
    class_name: str, workspace: str, db_path: str
) -> Optional[Tuple[str, str]]:
    """Find and return the source body of a class definition.

    Looks up the class node in ``graph_nodes`` (``node_type='class'``,
    ``name=class_name``), reads the class's source file, and returns the
    text from the ``class`` line to the end of the class body (best-effort
    indent-based extraction).

    Args:
        class_name: The class name to find.
        workspace: Absolute workspace root.
        db_path: SQLite db path.

    Returns:
        Tuple ``(class_body, file_rel)`` where ``class_body`` is the
        source text of the class body (including the ``class`` line), or
        ``None`` if the class isn't found.
    """
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT file, line FROM graph_nodes "
            "WHERE name = ? AND node_type = 'class' "
            "ORDER BY line ASC LIMIT 1",
            (class_name,),
        ).fetchone()
        conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None

    file_rel = row["file"]
    line = row["line"] or 1
    abs_path = os.path.join(workspace, file_rel)
    content = _read_file(abs_path)
    if not content:
        return None

    lines = content.split("\n")
    if line < 1 or line > len(lines):
        return None

    # The class definition starts at `line`. Extract its body by indent:
    # the body is everything indented more than the `class` line until
    # the next non-blank line at the same or lower indent.
    start_idx = line - 1
    cls_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    body_lines = [lines[start_idx]]
    for idx in range(start_idx + 1, len(lines)):
        ln = lines[idx]
        if ln.strip() == "":
            body_lines.append(ln)
            continue
        cur_indent = len(ln) - len(ln.lstrip())
        if cur_indent <= cls_indent:
            break
        body_lines.append(ln)
    return ("\n".join(body_lines), file_rel)


def _resolve_class_attribute(
    class_name: str,
    attribute_name: str,
    workspace: str,
    db_path: str,
    class_file_imports: Dict[str, str],
) -> Optional[str]:
    """Resolve the declared type of a class attribute.

    Scans the class body for two patterns (Python priority):
      1. ``self.attribute: Type = ...``  (PEP 526 annotation — preferred)
      2. ``self.attribute = Constructor(...)``  (inferred from RHS)

    For TS/JS class bodies, looks for ``attribute: Type = ...`` field
    declarations and ``attribute = new Constructor(...)`` initializers.

    Resolves the declared type name via the class file's import registry.
    When the type is not imported (i.e., defined in the same file as the
    class), qualifies it using the file's module path so callers get a
    consistent ``<module>.<ClassName>`` form.

    Args:
        class_name: The class to inspect.
        attribute_name: The attribute whose type we want.
        workspace: Absolute workspace root.
        db_path: SQLite db path.
        class_file_imports: The class's file entry in the import registry.

    Returns:
        The resolved qualified type (e.g. ``"models.Profile"``), or
        ``None`` if not found.
    """
    loaded = _load_class_body(class_name, workspace, db_path)
    if not loaded:
        return None
    body, file_rel = loaded

    def _qualify(type_name: str) -> str:
        """Qualify a type name with the class file's module path when not imported."""
        qualified = class_file_imports.get(type_name)
        if qualified:
            return qualified
        # Same-file type: derive module path from file_rel.
        # "src/utils.py" -> "src.utils"
        if file_rel.endswith(".py"):
            module_path = file_rel[:-3].replace(os.sep, ".")
        else:
            base, _ = os.path.splitext(file_rel)
            module_path = base.replace(os.sep, ".")
        return "{}.{}".format(module_path, type_name)

    # Try annotated attribute first (Python): self.attr: Type
    for line in body.split("\n"):
        m = _PY_ANNOTATED_ATTR_RE.search(line)
        if m and m.group(1) == attribute_name:
            type_name = m.group(2).split(".")[-1]  # last segment
            return _qualify(type_name)

    # Then inferred attribute (Python): self.attr = Constructor(...)
    for line in body.split("\n"):
        m = _PY_INFERRED_ATTR_RE.search(line)
        if m and m.group(1) == attribute_name:
            ctor_name = m.group(2)
            return _qualify(ctor_name)

    return None


# ─── Receiver Type Resolution ───────────────────────────────


def _get_file_imports(
    import_registry: Dict[str, Dict[str, str]], file_rel: str
) -> Dict[str, str]:
    """Return the import-registry entry for ``file_rel`` (empty dict if absent)."""
    return import_registry.get(file_rel, {})


def resolve_receiver_type(
    file_path: str,
    receiver_expr: str,
    import_registry: Dict[str, Dict[str, str]],
    workspace: Optional[str] = None,
    db_path: Optional[str] = None,
    local_var_types: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Resolve the type of a call-site receiver expression.

    Handles three receiver shapes:

    1. Simple imported name — ``User``: looked up directly in the file's
       import registry entry. Returns the qualified name
       (e.g. ``"models.User"``).
    2. Local variable — ``user``: looked up in ``local_var_types`` (which
       is built from ``var = Constructor(...)`` patterns). Returns the
       constructor's qualified type.
    3. Dotted attribute access — ``user.profile``: resolves the first
       segment per the above, then traverses class attributes by reading
       the class body (requires ``workspace`` and ``db_path``).

    Best-effort — returns ``None`` whenever resolution can't continue.
    Never raises.

    Args:
        file_path: Workspace-relative path of the file containing the call.
        receiver_expr: The receiver expression (e.g. ``"user.profile"``
            or ``"User"``).
        import_registry: Output of ``build_import_registry``.
        workspace: Absolute workspace root (required for dotted
            resolution).
        db_path: SQLite db path (required for dotted resolution).
        local_var_types: Optional pre-built local var type map for the
            file. If omitted, dotted resolution is skipped.

    Returns:
        The resolved qualified type, or ``None``.
    """
    if not receiver_expr:
        return None

    file_imports = _get_file_imports(import_registry, file_path)

    parts = receiver_expr.split(".")
    head = parts[0]

    # Resolve the head: import registry first, then local var types.
    qualified = file_imports.get(head)
    if not qualified and local_var_types:
        qualified = local_var_types.get(head)
    if not qualified:
        return None

    if len(parts) == 1:
        return qualified

    # Dotted: traverse attributes. The first segment's qualified name
    # is "<module>.<ClassName>"; the class name is the last segment.
    if not workspace or not db_path:
        return None

    current_type = qualified
    for attr in parts[1:]:
        class_name = current_type.split(".")[-1]
        # Look up the class file's imports so we can resolve attribute
        # type names that are imported.
        # Find the class file via graph_nodes.
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT file FROM graph_nodes "
                "WHERE name = ? AND node_type = 'class' "
                "ORDER BY line ASC LIMIT 1",
                (class_name,),
            ).fetchone()
            conn.close()
        except sqlite3.Error:
            return None
        if not row:
            return None
        class_file = row["file"]
        class_imports = _get_file_imports(import_registry, class_file)
        next_type = _resolve_class_attribute(
            class_name, attr, workspace, db_path, class_imports
        )
        if not next_type:
            return None
        current_type = next_type

    return current_type


# ─── Call Edge Refinement ───────────────────────────────────


def _find_function_body(
    content: str, def_line: int
) -> str:
    """Extract the source body of a Python/JS function starting at def_line.

    Uses indentation to find the end of the function (Python) or brace
    matching (JS/TS). Falls back to a generous slice when the language
    can't be determined.

    Args:
        content: The full source file content.
        def_line: 1-indexed line number where the function definition
            starts.

    Returns:
        The function body source (best-effort). Empty string on failure.
    """
    lines = content.split("\n")
    if def_line < 1 or def_line > len(lines):
        return ""
    start_idx = def_line - 1
    # Detect language by file extension would require passing the path;
    # instead, use a hybrid: try brace matching if the def line has `{`,
    # otherwise use indent-based extraction (Python).
    first_line = lines[start_idx]
    if "{" in first_line:
        # Brace-matching (JS-family).
        depth = 0
        started = False
        body_lines: List[str] = []
        for idx in range(start_idx, len(lines)):
            ln = lines[idx]
            body_lines.append(ln)
            depth += ln.count("{") - ln.count("}")
            if "{" in ln:
                started = True
            if started and depth <= 0:
                break
        return "\n".join(body_lines)
    # Indent-based (Python).
    base_indent = len(first_line) - len(first_line.lstrip())
    body_lines = []
    for idx in range(start_idx, len(lines)):
        ln = lines[idx]
        if ln.strip() == "":
            body_lines.append(ln)
            continue
        cur_indent = len(ln) - len(ln.lstrip())
        if idx > start_idx and cur_indent <= base_indent and ln.strip():
            break
        body_lines.append(ln)
    return "\n".join(body_lines)


def _find_call_receivers(
    body: str, method_name: str
) -> List[str]:
    """Find all receiver expressions for ``<receiver>.method_name(...)`` calls.

    Scans ``body`` for occurrences of ``<expr>.method_name(`` where
    ``<expr>`` is a dotted identifier chain (``a``, ``a.b``, ``a.b.c``).
    Skips ``self.method_name(`` (caller is the source function's own
    class — handled separately by the edge resolver).

    Args:
        body: The function body source.
        method_name: The bare method name (``to_fn``) to match.

    Returns:
        List of receiver expressions (strings like ``"user.profile"``).
        Empty if no matches.
    """
    if not method_name:
        return []
    # Escape the method name for regex safety.
    pattern = _CALL_RECEIVER_RE_TEMPLATE.format(method=re.escape(method_name))
    receivers: List[str] = []
    for m in re.finditer(pattern, body):
        receiver = m.group(1)
        if receiver == "self":
            continue
        receivers.append(receiver)
    return receivers


def _find_method_node_in_class_file(
    db_path: str, method_name: str, class_file_rel: str
) -> Optional[str]:
    """Find a function node by name in a specific file.

    Used to refine a CALLS edge's target_id to the specific method
    node inside a class's file. Returns the node_id of the first match
    (lowest line).
    """
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT node_id FROM graph_nodes "
            "WHERE name = ? AND file = ? "
            "ORDER BY line ASC LIMIT 1",
            (method_name, class_file_rel),
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _find_class_file_for_type(
    db_path: str, qualified_type: str
) -> Optional[str]:
    """Find the file where a class is defined, given its qualified type.

    ``qualified_type`` may be ``"models.User"`` or just ``"User"``. The
    last segment is treated as the class name. Returns the file path of
    the first matching class node, or ``None``.
    """
    class_name = qualified_type.split(".")[-1]
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT file FROM graph_nodes "
            "WHERE name = ? AND node_type = 'class' "
            "ORDER BY line ASC LIMIT 1",
            (class_name,),
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def refine_call_edges(
    workspace: str, db_path: Optional[str] = None
) -> Dict[str, int]:
    """Refine CALLS edges in ``graph_edges`` with receiver type info.

    Main entry point for hybrid type resolution. Runs as a post-scan
    pass:

    1. Builds the import registry (writes rows to ``import_registry``
       table + IMPORTS edges to ``graph_edges``).
    2. For each CALLS edge whose ``target_id`` is NULL or whose
       ``extra_json`` lacks ``resolved_type``:
       a. Read the source function's body.
       b. Find call sites matching the edge's ``to_fn``.
       c. Extract the receiver expression.
       d. Resolve the receiver type via the import registry + local
          var types + class attribute traversal.
       e. If resolved: look up the method node in the resolved type's
          class file. Update ``target_id`` if it differs from the
          current value. Stamp ``resolved_type`` + ``resolution_method``
          into ``extra_json``.
       f. If unresolved: stamp ``resolution_attempted=true`` +
          ``failure_reason`` into ``extra_json`` (only for edges whose
          ``target_id`` is NULL — already-resolved edges are left alone).

    Args:
        workspace: Absolute workspace root.
        db_path: Optional SQLite db path. Defaults to
            ``<workspace>/.codelens/codelens.db``.

    Returns:
        Dict with keys:
          * ``edges_total`` — total CALLS edges examined.
          * ``edges_refined`` — edges whose target_id was updated or
            whose ``resolved_type`` was stamped.
          * ``edges_unresolved`` — edges whose target_id is still NULL
            after the pass (resolution attempted but failed).
    """
    workspace = os.path.abspath(workspace)
    if db_path is None:
        db_path = os.path.join(workspace, ".codelens", "codelens.db")
    if not os.path.exists(db_path):
        return {"edges_total": 0, "edges_refined": 0, "edges_unresolved": 0}

    # 1. Build the import registry (also writes IMPORTS edges).
    import_registry = build_import_registry(workspace, db_path)

    # 2. Load all CALLS edges with their source node info.
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        edges = conn.execute(
            "SELECT id, source_id, target_id, file, line, extra_json "
            "FROM graph_edges WHERE edge_type = 'CALLS'"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("refine_call_edges: load error: %s", exc)
        if "conn" in dir():
            conn.close()
        return {"edges_total": 0, "edges_refined": 0, "edges_unresolved": 0}

    stats = {"edges_total": len(edges), "edges_refined": 0, "edges_unresolved": 0}

    # Cache: file_rel -> (content, ext, local_var_types) so we don't
    # re-read the same file for each of its edges.
    file_cache: Dict[str, Tuple[str, str, Dict[str, str]]] = {}

    def _get_file_info(file_rel: str) -> Tuple[str, str, Dict[str, str]]:
        """Return (content, ext, local_var_types) for a file, cached."""
        if file_rel in file_cache:
            return file_cache[file_rel]
        abs_path = os.path.join(workspace, file_rel)
        content = _read_file(abs_path)
        ext = os.path.splitext(file_rel)[1].lower()
        file_imports = _get_file_imports(import_registry, file_rel)
        local_types = _build_local_var_types(content, ext, file_imports)
        file_cache[file_rel] = (content, ext, local_types)
        return file_cache[file_rel]

    # Cache: file_rel -> def_line -> body, to avoid recomputing bodies.
    body_cache: Dict[Tuple[str, int], str] = {}

    for edge in edges:
        edge_id = edge["id"]
        source_id = edge["source_id"] or ""
        target_id = edge["target_id"]
        extra_json_str = edge["extra_json"] or "{}"

        try:
            extra = json.loads(extra_json_str)
        except (json.JSONDecodeError, TypeError):
            extra = {}

        to_fn = extra.get("to_fn", "")
        if not to_fn and target_id:
            # edge_resolver drops ``to_fn`` from resolved edges — recover
            # it by looking up the target node's name. This lets us refine
            # already-resolved edges (the common case when the method name
            # is unambiguous) without requiring parser changes.
            try:
                row = conn.execute(
                    "SELECT name FROM graph_nodes WHERE node_id = ?",
                    (target_id,),
                ).fetchone()
                if row:
                    to_fn = row[0] or ""
            except sqlite3.Error:
                pass
        if not to_fn:
            # No method name to refine — skip.
            if target_id is None:
                stats["edges_unresolved"] += 1
            continue

        # Parse source_id to get the calling function's file + def line.
        # Format: <file>:<line>[:<name>]
        parts = source_id.split(":")
        if len(parts) < 2:
            if target_id is None:
                stats["edges_unresolved"] += 1
            continue
        try:
            def_line = int(parts[1])
        except (ValueError, TypeError):
            if target_id is None:
                stats["edges_unresolved"] += 1
            continue
        src_file = parts[0]
        # Some node ids have more colons (e.g. class:line:name) — rejoin
        # anything between the first colon and the line number as the
        # file path. Our parsers use simple "file:line" so this is
        # usually a single segment, but be defensive.
        if len(parts) >= 3:
            # Could be file:line OR file:line:name. Heuristic: if parts[1]
            # is an int, file is parts[0]; else file is everything before
            # the first int.
            try:
                int(parts[1])
                src_file = parts[0]
            except ValueError:
                # Find the first int part — that's the line.
                file_segs = []
                for seg in parts:
                    try:
                        def_line = int(seg)
                        break
                    except ValueError:
                        file_segs.append(seg)
                src_file = ":".join(file_segs)

        content, ext, local_types = _get_file_info(src_file)

        # Find the function body.
        body_key = (src_file, def_line)
        if body_key not in body_cache:
            body_cache[body_key] = _find_function_body(content, def_line)
        body = body_cache[body_key]

        # Find call sites matching to_fn and extract receivers.
        receivers = _find_call_receivers(body, to_fn)
        if not receivers:
            # No receiver expression found (could be a direct call like
            # `update(...)` or `self.update(...)`). Nothing to refine.
            if target_id is None:
                stats["edges_unresolved"] += 1
                _stamp_extra(
                    conn, edge_id, extra,
                    {"resolution_attempted": True,
                     "failure_reason": "no_receiver_found"},
                )
            continue

        # Try each receiver until one resolves.
        resolved_type: Optional[str] = None
        for receiver in receivers:
            try:
                resolved_type = resolve_receiver_type(
                    src_file, receiver, import_registry,
                    workspace=workspace, db_path=db_path,
                    local_var_types=local_types,
                )
            except Exception:  # noqa: BLE001 — best-effort
                resolved_type = None
            if resolved_type:
                break

        if not resolved_type:
            if target_id is None:
                stats["edges_unresolved"] += 1
                _stamp_extra(
                    conn, edge_id, extra,
                    {"resolution_attempted": True,
                     "failure_reason": "receiver_not_imported"},
                )
            continue

        # Find the method node in the resolved type's class file.
        class_file = _find_class_file_for_type(db_path, resolved_type)
        new_target_id: Optional[str] = None
        if class_file:
            new_target_id = _find_method_node_in_class_file(
                db_path, to_fn, class_file
            )

        if new_target_id and new_target_id != target_id:
            # Update the edge's target_id.
            try:
                conn.execute(
                    "UPDATE graph_edges SET target_id = ? WHERE id = ?",
                    (new_target_id, edge_id),
                )
            except sqlite3.Error as exc:
                logger.debug("refine_call_edges: target update error: %s", exc)

        # Stamp the resolved_type + method into extra_json.
        _stamp_extra(
            conn, edge_id, extra,
            {"resolved_type": resolved_type,
             "resolution_method": "import_registry"},
        )
        stats["edges_refined"] += 1

    try:
        conn.commit()
    except sqlite3.Error as exc:
        logger.warning("refine_call_edges: commit error: %s", exc)
    finally:
        conn.close()

    return stats


def _stamp_extra(
    conn: sqlite3.Connection,
    edge_id: int,
    existing_extra: Dict[str, Any],
    new_fields: Dict[str, Any],
) -> None:
    """Merge ``new_fields`` into ``existing_extra`` and persist as extra_json.

    Does NOT commit — caller is responsible for committing the batch.

    Args:
        conn: Open sqlite3.Connection.
        edge_id: graph_edges.id.
        existing_extra: The current extra dict (will be mutated + merged).
        new_fields: Fields to add/overwrite.
    """
    existing_extra.update(new_fields)
    try:
        conn.execute(
            "UPDATE graph_edges SET extra_json = ? WHERE id = ?",
            (json.dumps(existing_extra, default=str), edge_id),
        )
    except sqlite3.Error as exc:
        logger.debug("_stamp_extra: update error: %s", exc)


# ─── Introspection ──────────────────────────────────────────


def import_registry_size(db_path: str) -> int:
    """Return the number of rows in the ``import_registry`` table.

    Returns 0 if the db or table doesn't exist.
    """
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT COUNT(*) FROM {}".format(IMPORT_REGISTRY_TABLE)
        ).fetchone()
        conn.close()
        return row[0] if row else 0
    except sqlite3.Error:
        return 0
