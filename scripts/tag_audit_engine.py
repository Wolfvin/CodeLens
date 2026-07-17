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

        for lineno, line in enumerate(content.splitlines(), start=1):
            m = _TAG_RE.search(line)
            if not m:
                continue
            tag, value = m.group(1), m.group(2)
            if tag in HEADER_TAGS:
                header_present.add(tag)
            elif tag == "FLOW":
                name = _flow_name(value)
                if name:
                    self._flows.setdefault(name, []).append(f"{rel}:{lineno}")

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
        flows = [
            {"name": name, "count": len(locs), "locations": sorted(locs)}
            for name, locs in sorted(self._flows.items())
        ]
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
