# @WHO:   scripts/tag_audit_engine.py
# @WHAT:  Audit the @WHO/@WHAT/@PART/@ENTRY + @FLOW/@CALLS/@MUTATES doc-tag
#         convention: inventory named flows, measure header coverage, list
#         untagged and partially-tagged files (issue #305)
# @PART:  engine
# @ENTRY: TagAuditEngine, audit_tags()
"""Tag-convention audit for CodeLens.

The codebase documents intent with a header block per file
(``@WHO``/``@WHAT``/``@PART``/``@ENTRY``) and per-function tags in docstrings
(``@FLOW``/``@CALLS``/``@MUTATES``). The convention spans languages — the tags
appear in ``#`` comments (Python) and ``//`` comments (TS/JS) alike — but until
now nothing read them back, so the data rotted silently (e.g. flows naming
code that a command consolidation later dropped).

This engine answers three questions from the tags *already in the code*,
inventing nothing:

1. **Inventory** — every distinct ``@FLOW`` name and where it is declared.
2. **Coverage** — which files carry a full header, a partial one, or none.
3. **Partial headers** — files missing some (not all) of the four header tags,
   which usually means a tag was forgotten.

Pure and deterministic: regex only, no LLM, no network, every collection
sorted so two runs on the same tree are byte-identical.

@FLOW:    TAG_AUDIT
@CALLS:   TagAuditEngine.run() -> dict  (walks workspace via BaseEngine)
@MUTATES: none (read-only scan; never writes tags back to source)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from base_engine import BaseEngine

# The four file-header tags, in canonical order.
HEADER_TAGS = ("WHO", "WHAT", "PART", "ENTRY")
# Per-function tags.
FUNCTION_TAGS = ("FLOW", "CALLS", "MUTATES")

# Match `@TAG: value` only when it OPENS a comment/docstring line — optional
# comment marker (`#`, `//`, `*`, `--`) then whitespace then the tag. Anchoring
# to line start is what separates a real declaration from a prose mention like
# `... the `@FLOW: PURE` example ...`, which would otherwise pollute the
# inventory (any file *documenting* the convention, this engine included, would
# register phantom flows). The value runs to end of line.
_TAG_RE = re.compile(
    r"^[ \t]*(?:#|//|\*|--|/\*)?[ \t]*"
    r"@(" + "|".join(HEADER_TAGS + FUNCTION_TAGS) + r"):[ \t]*(.*)"
)

# Source extensions that carry the convention. Language-agnostic: the tags are
# the same across all of them; only the comment marker differs.
_SOURCE_EXTENSIONS: Set[str] = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".php", ".rb", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".kt", ".swift", ".css", ".scss", ".html", ".vue", ".svelte",
}

# Cap on enumerated file lists; counts stay exact.
_LIST_CAP = 200

# Broad, language-agnostic declaration pattern — captures the symbol name from
# a keyword-style definition (py/rust/go/ts/java/php/c...) or a JS-style
# `const foo =` / `foo(...) {`. Used only to attribute a @FLOW tag to the
# nearest enclosing symbol; a miss falls back to the file, so it never has to
# be exhaustive.
_DEF_RE = re.compile(
    r"^[ \t]*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+|"
    r"final\s+|pub\s+)*"
    r"(?:def|fn|func|function|class|struct|interface|type|impl|trait)\s+(\w+)"
)
_JS_DEF_RE = re.compile(
    r"^[ \t]*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=|"
    r"^[ \t]*(\w+)\s*\([^)]*\)\s*(?:\{|=>|:)"
)


def _symbol_at(line: str) -> str:
    """Return the symbol declared on ``line``, or '' if it declares none."""
    m = _DEF_RE.match(line)
    if m:
        return m.group(1)
    m = _JS_DEF_RE.match(line)
    if m:
        return m.group(1) or m.group(2) or ""
    return ""


# How many lines below a tag to scan for a `comment-above-def` declaration.
_LOOKAHEAD = 3


def _lookahead_symbol(lines, idx: int) -> str:
    """Symbol declared just below line ``idx`` (a comment-above-def), or ''.

    Only contiguous comment lines may sit between the tag and the declaration.
    A blank line ends the run: it separates a file-header tag (blank, then an
    unrelated first declaration) from a genuine comment-above-def, and a
    docstring tag (whose following lines are code) never reaches a def.
    """
    for j in range(idx + 1, min(idx + 1 + _LOOKAHEAD, len(lines))):
        stripped = lines[j].strip()
        sym = _symbol_at(lines[j])
        if sym:
            return sym
        if not stripped or not stripped.startswith(("//", "#", "*", "/*", '"""', "'''")):
            break  # blank line or real code before a def — not comment-above-def
    return ""


def _flow_name(raw: str) -> str:
    """The flow name is the first whitespace-delimited token of an @FLOW value.

    `@FLOW: PURE (declarations only)` -> `PURE`; `@FLOW: AUDIT_DISPATCH` ->
    `AUDIT_DISPATCH`. The remainder is human prose, not part of the identity.
    """
    return raw.strip().split(None, 1)[0] if raw.strip() else ""


class TagAuditEngine(BaseEngine):
    """Scan source files for the doc-tag convention and report on it."""

    FILE_EXTENSIONS = _SOURCE_EXTENSIONS

    def _pre_scan(self, workspace: str, **kwargs) -> None:
        # flow name -> sorted set of "rel_path:line" declaration sites
        self._flows: Dict[str, List[str]] = {}
        self._full_header: List[str] = []
        self._partial_header: List[Dict[str, Any]] = []
        self._untagged: List[str] = []

    def _analyze_file(self, rel_path, content, ext, abs_path) -> List[Dict[str, Any]]:
        header_present: Set[str] = set()
        # Normalise separators so keys match across OSes (Windows scan, Linux CI).
        rel = rel_path.replace("\\", "/")
        source_lines = content.splitlines()
        last_symbol = ""  # nearest declaration seen while scanning down the file

        for idx, line in enumerate(source_lines):
            lineno = idx + 1
            symbol = _symbol_at(line)
            if symbol:
                last_symbol = symbol

            m = _TAG_RE.search(line)
            if not m:
                continue
            tag, value = m.group(1), m.group(2)
            if tag in HEADER_TAGS:
                header_present.add(tag)
            elif tag == "FLOW":
                name = _flow_name(value)
                if name:
                    # Attribute the flow to a function. A comment-above-def
                    # (`// @FLOW` then the declaration) is the most specific, so
                    # look a few lines down first; otherwise fall back to the
                    # enclosing def seen above (docstring case); a tag with
                    # neither (file header) attributes to the file itself.
                    self._flows.setdefault(name, []).append({
                        "symbol": _lookahead_symbol(source_lines, idx) or last_symbol,
                        "file": rel,
                        "line": lineno,
                    })

        if not header_present:
            self._untagged.append(rel)
        elif header_present.issuperset(HEADER_TAGS):
            self._full_header.append(rel)
        else:
            self._partial_header.append({
                "file": rel,
                "present": sorted(header_present),
                "missing": [t for t in HEADER_TAGS if t not in header_present],
            })

        # This engine aggregates in instance state, not per-file findings.
        return []

    def _build_result(self, workspace: str) -> Dict[str, Any]:
        flows = []
        for name, members in sorted(self._flows.items()):
            ordered = sorted(members, key=lambda m: (m["file"], m["line"]))
            flows.append({
                "name": name,
                "count": len(ordered),
                # Members carry the enclosing symbol; locations stays for
                # backward compat (tag-audit consumers + ai item extraction).
                "members": ordered,
                "locations": [f"{m['file']}:{m['line']}" for m in ordered],
            })
        partial = sorted(self._partial_header, key=lambda d: d["file"])
        untagged = sorted(self._untagged)
        scanned = self._files_scanned

        tagged = len(self._full_header) + len(partial)
        return {
            "status": "ok",
            "workspace": workspace,
            "check": "tags",
            "summary": {
                "files_scanned": scanned,
                "with_full_header": len(self._full_header),
                "with_partial_header": len(partial),
                "without_header": len(untagged),
                "header_coverage_pct": round(100 * tagged / scanned, 1) if scanned else 0.0,
                "distinct_flows": len(flows),
                "total_flow_declarations": sum(f["count"] for f in flows),
            },
            "flows": flows,
            "partial_headers": partial[:_LIST_CAP],
            "partial_headers_truncated": len(partial) > _LIST_CAP,
            "untagged_files": untagged[:_LIST_CAP],
            "untagged_files_truncated": len(untagged) > _LIST_CAP,
        }


def audit_tags(workspace: str) -> Dict[str, Any]:
    """Run the tag audit against ``workspace`` and return the report dict."""
    return TagAuditEngine().run(workspace)
