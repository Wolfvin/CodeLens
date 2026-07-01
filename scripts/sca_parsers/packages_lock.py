"""
Parser for ``packages.lock.json`` (NuGet).

Format reference (public, reimplemented from spec):
- Top-level JSON object with ``version`` (an int, usually 1 or 2),
  ``dependencies`` and (v2) ``frameworks``.
- v1: ``dependencies`` maps ``"PackageName"`` -> ``{ "resolved": "1.2.3",
  "type": "Direct|Transitive|Project", ... }``.
- v2: ``frameworks`` maps ``".NETCoreApp,Version=v6.0"`` -> ``{ "dependencies":
  {...} }``. We flatten across all frameworks (dedup by name+version).

The ``type`` field is the authoritative source for direct vs transitive;
we fall back to "transitive" when missing.
"""

from __future__ import annotations

import json
import logging
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.packages_lock")


def _extract_from_deps_dict(
    deps: dict, path: str, seen: set
) -> List[Dependency]:
    out: List[Dependency] = []
    if not isinstance(deps, dict):
        return out
    for name, info in deps.items():
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(info, dict):
            continue
        version = info.get("resolved") or info.get("version") or ""
        if not isinstance(version, str) or not version:
            continue
        dep_type = info.get("type", "")
        transitivity = "direct" if dep_type == "Direct" else "transitive"
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="nuget",
                source_file=path,
                transitivity=transitivity,
            )
        )
    return out


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("packages_lock: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    seen: set = set()
    deps: List[Dependency] = []

    # v1: top-level "dependencies"
    if isinstance(data.get("dependencies"), dict):
        deps.extend(_extract_from_deps_dict(data["dependencies"], path, seen))

    # v2: per-framework "dependencies"
    frameworks = data.get("frameworks", {}) or {}
    if isinstance(frameworks, dict):
        for _tfm, tfm_data in frameworks.items():
            if not isinstance(tfm_data, dict):
                continue
            inner = tfm_data.get("dependencies", {}) or {}
            deps.extend(_extract_from_deps_dict(inner, path, seen))

    return deps


__all__ = ["parse"]
