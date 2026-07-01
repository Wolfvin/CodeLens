"""
Parser for ``Pipfile.lock`` (Pipenv).

Format reference (public, reimplemented from spec):
- Top-level JSON object with ``default`` and ``develop`` sections.
- Each section maps ``name`` -> ``{"version": "==1.2.3", "hashes": [...], ...}``
  or (rare legacy) ``name`` -> ``"==1.2.3"``.
- The ``version`` field includes the leading ``==`` operator which we
  strip to obtain the bare version.

Direct vs transitive: Pipfile.lock does not distinguish declared vs
sub-deps — every entry in ``default``/``develop`` is a resolved dep. We
mark all as ``direct`` because Pipfile (the manifest) declares the
top-level ones and Pipfile.lock is just the resolution.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.pipfile_lock")


def _strip_specifier(version: str) -> str:
    """Strip leading version operators: ``==1.2.3`` -> ``1.2.3``."""
    if not isinstance(version, str):
        return ""
    cleaned = re.sub(r"^[><=!~]+", "", version.strip())
    return cleaned or ""


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
    except Exception as exc:
        logger.warning("pipfile_lock: cannot read %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    deps: List[Dependency] = []
    seen = set()

    for section in ("default", "develop"):
        section_data = data.get(section, {}) or {}
        if not isinstance(section_data, dict):
            continue
        for name, info in section_data.items():
            if isinstance(info, dict):
                version = info.get("version", "")
            elif isinstance(info, str):
                version = info
            else:
                continue
            version = _strip_specifier(version)
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
                    ecosystem="pypi",
                    source_file=path,
                    transitivity="direct",
                )
            )

    return deps


__all__ = ["parse"]
