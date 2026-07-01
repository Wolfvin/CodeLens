"""
Parser for ``pnpm-lock.yaml`` (pnpm v6 and v9).

Format reference (public, reimplemented from spec — no code copied):
- v6: top-level ``importers`` maps workspace path -> ``dependencies`` /
  ``devDependencies`` / ``optionalDependencies`` dicts of
  ``name: specifier`` strings. The ``packages`` dict maps a
  ``/name@version`` key to a metadata object.
- v9: same shape, but the lockfileVersion is 9.0 and ``packages`` keys
  may include peer-resolution suffixes like ``/name@version(peer)``.
- ``snapshots`` (v9) holds resolved tree state — we ignore it because
  ``packages`` already gives us every installed package exactly once.

We extract direct deps from ``importers`` and mark everything else
as transitive.
"""

from __future__ import annotations

import logging
import re
from typing import List, Set

try:
    import yaml  # PyYAML
except ImportError:  # pragma: no cover - PyYAML is a hard dep of codelens
    yaml = None

from . import Dependency

logger = logging.getLogger("codelens.sca.pnpm")


def parse(path: str) -> List[Dependency]:
    if yaml is None:
        logger.warning("pnpm_lock: PyYAML not available, skipping %s", path)
        return []

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = yaml.safe_load(f)
    except Exception as exc:
        logger.warning("pnpm_lock: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    lock_version = data.get("lockfileVersion", 6)

    # ── Collect direct deps from importers ──
    direct_names: Set[str] = set()
    importers = data.get("importers", {}) or {}
    if isinstance(importers, dict):
        for _ws, ws_data in importers.items():
            if not isinstance(ws_data, dict):
                continue
            for dep_field in (
                "dependencies",
                "devDependencies",
                "optionalDependencies",
                "peerDependencies",
            ):
                section = ws_data.get(dep_field, {}) or {}
                if not isinstance(section, dict):
                    continue
                for name in section.keys():
                    direct_names.add(name)

    # ── Collect all resolved packages ──
    deps: List[Dependency] = []
    seen: Set[str] = set()
    packages = data.get("packages", {}) or {}
    if isinstance(packages, dict):
        for key, _info in packages.items():
            if not isinstance(key, str) or not key:
                continue
            # Key format: "/name@version" or "/name@version(peer@v)"
            # Strip a leading "/"
            stripped = key[1:] if key.startswith("/") else key
            # Strip peer suffix in parentheses
            stripped = stripped.split("(", 1)[0]
            # Split on the LAST @ (scoped packages: @scope/name@version)
            at_idx = stripped.rfind("@")
            if at_idx <= 0:
                continue
            name = stripped[:at_idx]
            version = stripped[at_idx + 1:]
            if not name or not version:
                continue
            unique = (name, version)
            if unique in seen:
                continue
            seen.add(unique)
            transitivity = "direct" if name in direct_names else "transitive"
            deps.append(
                Dependency(
                    name=name,
                    version=version,
                    ecosystem="npm",
                    source_file=path,
                    transitivity=transitivity,
                )
            )

    # v6 fallback: if there are no ``packages`` we may still have
    # ``dependencies`` at top level (older experimental format).
    if not deps:
        top_deps = data.get("dependencies", {}) or {}
        if isinstance(top_deps, dict):
            for name, info in top_deps.items():
                if isinstance(info, dict):
                    version = info.get("version", "")
                elif isinstance(info, str):
                    version = info
                else:
                    continue
                if name and version:
                    deps.append(
                        Dependency(
                            name=name,
                            version=str(version),
                            ecosystem="npm",
                            source_file=path,
                            transitivity="direct" if name in direct_names else "transitive",
                        )
                    )

    _ = lock_version  # parsed for future use, currently format-agnostic
    return deps


__all__ = ["parse"]
