"""Serena-style markdown memory manager for CodeLens (issue #60).

Provides cross-session memory for AI agents using CodeLens. Memory files are
plain markdown so they can be read, edited, and version-controlled by humans
or tools without specialised software.

Storage layout
--------------
- **Project memory:** ``<workspace>/.codelens/memories/<topic>.md``
  Scoped to a single workspace; read/write via CLI.
- **Global memory:** ``~/.codelens/memories/global/<topic>.md``
  Scoped to the current user; **read-only via CLI**. Edit manually on the
  filesystem to update.

File format
-----------
Every memory file MUST start with a header line::

    # Memory: <topic>

The body is free-form markdown. A ``mem:NAME`` token anywhere in the body is
treated as a reference to another memory file named ``NAME``. References are
validated (non-blocking — see :func:`validate_references`) on write so authors
get a heads-up if they typo a topic name, but a missing reference never blocks
a write.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ─── Public constants ──────────────────────────────────────────────────────

# Memory file header prefix. Every memory file must start with this.
HEADER_PREFIX = "# Memory:"

# Canonical header regex. Allows leading whitespace, requires '# Memory:',
# then captures the topic name (rest of line, trimmed).
_HEADER_RE = re.compile(r"^\s*#\s+Memory:\s*(.+?)\s*$", re.MULTILINE)

# `mem:NAME` reference pattern. Names start with a letter and may contain
# letters, digits, underscores, dots, or hyphens — same charset enforced by
# :func:`_validate_name`. The leading word boundary prevents matching inside
# longer tokens like ``notmem:foo``.
_MEM_REF_RE = re.compile(r"(?<![\w:])mem:([A-Za-z][A-Za-z0-9_.-]*)\b")

# Valid memory name charset (must match the capture group in _MEM_REF_RE).
_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")


# ─── Path helpers ──────────────────────────────────────────────────────────


def project_memory_dir(workspace: str) -> str:
    """Return the project memory directory for a workspace."""
    return os.path.join(workspace, ".codelens", "memories")


def global_memory_dir() -> str:
    """Return the global memory directory (under the user's home)."""
    return os.path.join(os.path.expanduser("~"), ".codelens", "memories", "global")


def project_memory_path(workspace: str, name: str) -> str:
    """Return the absolute path to a project memory file."""
    _validate_name(name)
    return os.path.join(project_memory_dir(workspace), f"{name}.md")


def global_memory_path(name: str) -> str:
    """Return the absolute path to a global memory file."""
    _validate_name(name)
    return os.path.join(global_memory_dir(), f"{name}.md")


# ─── Name validation ───────────────────────────────────────────────────────


def _validate_name(name: str) -> None:
    """Raise ``ValueError`` if ``name`` is not a valid memory topic name.

    Names must start with a letter and contain only letters, digits,
    underscores, dots, or hyphens. This is the same charset that
    :data:`_MEM_REF_RE` accepts inside ``mem:NAME`` references, so a writer
    can always reference any validly-named memory.
    """
    if not name:
        raise ValueError("Memory name cannot be empty")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid memory name: {name!r}. "
            "Names must start with a letter and contain only letters, digits, "
            "underscores, dots, or hyphens."
        )


# ─── File content helpers ──────────────────────────────────────────────────


def build_file_content(name: str, content: str) -> str:
    """Return canonical file content with the required header.

    If ``content`` already starts with a valid ``# Memory:`` header (with any
    topic name), the existing header is replaced with the canonical one for
    ``name``. Otherwise the header is prepended.

    The result is always terminated by a single newline so files are
    diff-friendly and idempotent across writes.
    """
    header = format_header(name)
    stripped = content.lstrip()
    # Detect and replace a pre-existing header (any topic).
    if stripped.startswith(HEADER_PREFIX):
        # Remove the first header line (and any blank line right after it).
        without_header = _HEADER_RE.sub("", content, count=1).lstrip("\n")
        body = without_header.rstrip()
    else:
        body = content.rstrip()

    if body:
        return f"{header}\n\n{body}\n"
    return f"{header}\n"


def format_header(name: str) -> str:
    """Return the canonical header line for a memory named ``name``."""
    return f"{HEADER_PREFIX} {name}"


def parse_header_topic(first_line: str) -> Optional[str]:
    """Extract the topic name from a header line.

    Returns ``None`` if the line is not a valid memory header. Used by
    :func:`list_memories` to surface whether each file has a valid header.
    """
    if not first_line:
        return None
    m = _HEADER_RE.match(first_line)
    return m.group(1) if m else None


def has_valid_header(content: str) -> bool:
    """Return True if ``content`` starts with a valid memory header line."""
    if not content:
        return False
    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    return parse_header_topic(first_line) is not None


# ─── Reference handling ────────────────────────────────────────────────────


def extract_references(content: str) -> List[str]:
    """Return the unique ``mem:NAME`` references found in ``content``.

    Order is preserved (first occurrence wins). Self-references (``mem:NAME``
    inside the memory file named ``NAME``) are included — callers decide
    whether to ignore them via the ``exclude`` parameter of
    :func:`validate_references`.
    """
    refs = _MEM_REF_RE.findall(content)
    seen: set[str] = set()
    unique: List[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def memory_exists(workspace: str, name: str) -> bool:
    """Return True if a memory named ``name`` exists in project or global scope."""
    _validate_name(name)
    return (
        os.path.isfile(project_memory_path(workspace, name))
        or os.path.isfile(global_memory_path(name))
    )


def validate_references(
    workspace: str,
    content: str,
    exclude: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate ``mem:NAME`` references in ``content`` (non-blocking).

    Returns a dict with:

    - ``references`` — all unique ``mem:NAME`` references found.
    - ``missing``    — references whose target memory does not exist in
      project or global scope.
    - ``warnings``   — human-readable warning strings, one per missing
      reference. Suitable for surfacing to the CLI user / AI agent.

    This function never raises on a missing reference — the contract is
    "warn, don't block" (see issue #60). Invalid reference *syntax* is
    silently ignored (the regex simply won't match).
    """
    references = extract_references(content)
    missing: List[str] = []
    for ref in references:
        if exclude is not None and ref == exclude:
            # Self-reference: the memory being written will exist after the
            # write succeeds, so don't flag it.
            continue
        try:
            if not memory_exists(workspace, ref):
                missing.append(ref)
        except ValueError:
            # Shouldn't happen because the regex already validated the name,
            # but be defensive — never block on validation.
            continue

    warnings = [
        f"Reference 'mem:{ref}' does not exist (project or global)"
        for ref in missing
    ]
    return {
        "references": references,
        "missing": missing,
        "warnings": warnings,
    }


# ─── CRUD operations ───────────────────────────────────────────────────────


def write_memory(workspace: str, name: str, content: str) -> Dict[str, Any]:
    """Create or update a project memory file.

    The file is written to ``<workspace>/.codelens/memories/<name>.md`` with a
    canonical ``# Memory: <name>`` header. ``mem:NAME`` references in
    ``content`` are validated and any missing references are reported in the
    result's ``warnings`` field — but the write always succeeds (issue #60:
    warn, don't block).

    Global memories are not writable via this function — they are read-only
    through the CLI by design.
    """
    workspace = os.path.abspath(workspace)
    _validate_name(name)

    file_content = build_file_content(name, content)
    validation = validate_references(workspace, file_content, exclude=name)

    path = project_memory_path(workspace, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(file_content)

    result: Dict[str, Any] = {
        "status": "ok",
        "action": "written",
        "scope": "project",
        "name": name,
        "path": path,
        "references": validation["references"],
        "size_bytes": len(file_content.encode("utf-8")),
    }
    if validation["missing"]:
        result["missing_references"] = validation["missing"]
        result["warnings"] = validation["warnings"]
    return result


def read_memory(workspace: str, name: str) -> Dict[str, Any]:
    """Read a memory file. Looks in project first, then global.

    Returns a ``not_found`` result (not an error) when the memory doesn't
    exist in either scope, so callers can distinguish "missing" from "broken".
    """
    workspace = os.path.abspath(workspace)
    _validate_name(name)

    proj_path = project_memory_path(workspace, name)
    if os.path.isfile(proj_path):
        return _read_file(proj_path, name, "project")

    glob_path = global_memory_path(name)
    if os.path.isfile(glob_path):
        return _read_file(glob_path, name, "global")

    return {
        "status": "not_found",
        "name": name,
        "message": (
            f"Memory '{name}' not found in project or global scope. "
            "Run 'codelens memory list' to see available memories."
        ),
    }


def _read_file(path: str, name: str, scope: str) -> Dict[str, Any]:
    """Read a memory file from disk and return a structured result."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return {
            "status": "error",
            "error": f"Failed to read memory file: {e}",
            "path": path,
            "name": name,
            "scope": scope,
        }

    references = extract_references(content)
    first_line = content.splitlines()[0] if content.strip() else ""
    header_topic = parse_header_topic(first_line)

    return {
        "status": "ok",
        "scope": scope,
        "name": name,
        "path": path,
        "content": content,
        "references": references,
        "header_topic": header_topic,
        "has_valid_header": header_topic is not None,
        "size_bytes": len(content.encode("utf-8")),
    }


def list_memories(workspace: str) -> Dict[str, Any]:
    """List all memories in project and global scope.

    Returns a dict with ``project`` and ``global`` lists plus a combined
    ``memories`` list (deduplicated by name; project wins on collision).
    """
    workspace = os.path.abspath(workspace)

    project = _list_dir(project_memory_dir(workspace), "project")
    glob = _list_dir(global_memory_dir(), "global")

    # Deduplicate by name (project takes precedence — it shadows a global
    # memory of the same name when reading via :func:`read_memory`).
    seen: set[str] = set()
    combined: List[Dict[str, Any]] = []
    for entry in project + glob:
        if entry["name"] in seen:
            continue
        seen.add(entry["name"])
        combined.append(entry)

    return {
        "status": "ok",
        "total": len(combined),
        "project_count": len(project),
        "global_count": len(glob),
        "project": project,
        "global": glob,
        "memories": combined,
    }


def _list_dir(directory: str, scope: str) -> List[Dict[str, Any]]:
    """List memory files in ``directory``. Returns ``[]`` if dir is missing."""
    if not os.path.isdir(directory):
        return []

    results: List[Dict[str, Any]] = []
    for fname in sorted(os.listdir(directory)):
        if not fname.endswith(".md"):
            continue
        name = fname[:-3]
        # Skip names that don't match our validation rules (e.g. manually
        # created files with weird names). They still exist on disk but we
        # don't surface them through the CLI.
        if not _NAME_RE.fullmatch(name):
            continue
        path = os.path.join(directory, fname)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
            with open(path, "r", encoding="utf-8") as f:
                first_line = f.readline().rstrip("\n")
        except OSError:
            continue
        header_topic = parse_header_topic(first_line)
        results.append({
            "name": name,
            "scope": scope,
            "path": path,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "header_topic": header_topic,
            "has_valid_header": header_topic is not None,
        })
    return results


def delete_memory(workspace: str, name: str) -> Dict[str, Any]:
    """Delete a project memory file.

    Global memories are **read-only via CLI** and cannot be deleted here —
    they must be removed manually from the filesystem. Returns ``not_found``
    when the project memory doesn't exist (rather than an error) so callers
    can distinguish "missing" from "broken".
    """
    workspace = os.path.abspath(workspace)
    _validate_name(name)

    path = project_memory_path(workspace, name)
    if not os.path.isfile(path):
        return {
            "status": "not_found",
            "scope": "project",
            "name": name,
            "message": (
                f"Project memory '{name}' not found. "
                "Global memories are read-only via CLI and cannot be deleted; "
                "remove them manually from "
                f"{global_memory_dir()!r}."
            ),
        }

    try:
        os.remove(path)
    except OSError as e:
        return {
            "status": "error",
            "error": f"Failed to delete memory file: {e}",
            "path": path,
            "name": name,
            "scope": "project",
        }

    return {
        "status": "ok",
        "action": "deleted",
        "scope": "project",
        "name": name,
        "path": path,
    }


# ─── Module entry point for ad-hoc CLI inspection ──────────────────────────


def _main(argv: Optional[List[str]] = None) -> int:
    """Tiny REPL-style entry point for manual debugging via ``python -m``.

    Not part of the public API — the real CLI lives in
    ``scripts/commands/memory.py``. This exists so a developer can run
    ``python3 -m memories.memory_manager`` to sanity-check imports.
    """
    print("memory_manager module loaded successfully.")
    print(f"  Global memory dir: {global_memory_dir()}")
    print("  Use 'codelens memory <write|read|list|delete>' for real access.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main())
