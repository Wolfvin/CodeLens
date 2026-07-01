"""
Parser for ``composer.lock`` (PHP / Composer).

Format reference (public, reimplemented from spec):
- Top-level JSON object with ``packages`` and ``packages-dev`` arrays.
- Each entry has at minimum ``name`` (``vendor/package``) and ``version``
  (e.g. ``"1.2.3"`` or ``"v1.2.3"`` or ``"dev-master"``).
- The ``require`` and ``require-dev`` sub-fields inside each package
  are NOT what we want — those are the deps of that sub-package. We
  only take the top-level ``packages`` and ``packages-dev`` arrays.
- Direct vs transitive: composer.lock does not natively distinguish,
  but ``packages-dev`` are dev deps (treated as direct) and ``packages``
  are runtime deps (also direct from the lockfile perspective).
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.composer_lock")


def _normalise_version(version: str) -> str:
    """Strip the leading ``v`` and any ``dev-`` prefix from a Composer version."""
    if not isinstance(version, str) or not version:
        return ""
    v = version.strip()
    # Composer uses "v1.2.3" pretty-print form; strip leading v.
    if v.startswith("v") and len(v) > 1 and v[1].isdigit():
        v = v[1:]
    return v


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("composer_lock: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    deps: List[Dependency] = []
    seen = set()

    for section, dev_flag in (("packages", False), ("packages-dev", True)):
        arr = data.get(section, []) or []
        if not isinstance(arr, list):
            continue
        for entry in arr:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            version = _normalise_version(entry.get("version", ""))
            if not name or not version:
                continue
            key = (name.lower(), version)
            if key in seen:
                continue
            seen.add(key)
            deps.append(
                Dependency(
                    name=name,
                    version=version,
                    ecosystem="composer",
                    source_file=path,
                    # Composer treats both sections as resolved runtime/dev deps.
                    transitivity="direct",
                )
            )

    return deps


__all__ = ["parse"]
