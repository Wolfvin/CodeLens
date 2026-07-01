"""
Parser for ``pubspec.lock`` (Dart / pub).

Format reference (public, reimplemented from spec):
- YAML file with top-level ``packages`` mapping.
- Each value is a dict with ``dependency``, ``source``, ``version`` and
  (for hosted source) ``description: {name: ..., url: ..., sha256: ...}``.
- ``dependency: "direct main"`` / ``"direct dev"`` / ``"transitive"``.
- ``version`` is a SemVer string, possibly with leading ``^`` (rare in
  lockfiles).
"""

from __future__ import annotations

import logging
import re
from typing import List

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

from . import Dependency

logger = logging.getLogger("codelens.sca.pubspec_lock")


def parse(path: str) -> List[Dependency]:
    if yaml is None:
        logger.warning("pubspec_lock: PyYAML not available, skipping %s", path)
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        logger.warning("pubspec_lock: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    packages = data.get("packages", {}) or {}
    if not isinstance(packages, dict):
        return []

    deps: List[Dependency] = []
    seen = set()

    for name, info in packages.items():
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(info, dict):
            continue
        version = info.get("version", "")
        if not isinstance(version, str) or not version:
            continue
        # Strip leading operator just in case.
        version = re.sub(r"^[~^>=<!*]+", "", version.strip())
        if not version:
            continue

        dep_str = info.get("dependency", "") or ""
        if isinstance(dep_str, str) and dep_str.startswith("direct"):
            transitivity = "direct"
        else:
            transitivity = "transitive"

        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        deps.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="pub",
                source_file=path,
                transitivity=transitivity,
            )
        )

    return deps


__all__ = ["parse"]
