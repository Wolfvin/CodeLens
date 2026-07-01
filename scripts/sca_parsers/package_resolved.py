"""
Parser for ``Package.resolved`` (Swift Package Manager).

Format reference (public, reimplemented from spec):
- JSON file with a top-level ``object`` and ``version`` field.
- v1: ``object.pins`` is an array of ``{ "package": "Name",
  "repositoryURL": "...", "state": { "version": "1.2.3" } }``.
- v2: ``object.pins`` entries have ``identity`` (lowercase package id)
  instead of ``package``, and ``location`` instead of ``repositoryURL``.
  ``state`` may carry ``revision`` (a git sha) and/or ``version``.
- v3: same shape as v2 with an extra ``version`` field at the top level.

If ``state.version`` is missing (branch / revision-only pins), we fall
back to ``state.revision`` (short sha) so the dep is still recorded.
"""

from __future__ import annotations

import json
import logging
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.package_resolved")


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("package_resolved: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    obj = data.get("object", {}) or {}
    if not isinstance(obj, dict):
        return []
    pins = obj.get("pins", []) or []
    if not isinstance(pins, list):
        return []

    deps: List[Dependency] = []
    seen = set()

    for pin in pins:
        if not isinstance(pin, dict):
            continue
        # v1: "package" (display name) ; v2/v3: "identity" (lowercase id)
        name = pin.get("package") or pin.get("identity") or ""
        if not isinstance(name, str) or not name:
            continue
        state = pin.get("state", {}) or {}
        if not isinstance(state, dict):
            continue
        version = state.get("version") or ""
        if not version:
            # Branch/revision-only pin: fall back to short sha.
            revision = state.get("revision") or ""
            if revision:
                version = revision[:12]
        if not version:
            continue
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        deps.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="swiftpm",
                source_file=path,
                # Package.resolved doesn't distinguish direct vs transitive
                # (both kinds end up in the same pins list). Default direct.
                transitivity="direct",
            )
        )

    return deps


__all__ = ["parse"]
