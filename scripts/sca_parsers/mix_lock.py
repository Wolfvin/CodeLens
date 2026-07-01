"""
Parser for ``mix.lock`` (Elixir / Hex).

Format reference (public, reimplemented from spec):
- Elixir source file with ``%{`` map literal at top level.
- Each entry is ``"package_name": {:hex, :package_name, "1.2.3",
  "url", "hash", [:mix], deps...}`` or
  ``"name": {:git, "url", "sha", branch/ref}``.
- We only handle ``:hex`` entries (Hex packages) for OSV matching —
  ``:git`` entries are also extracted but marked with ecosystem ``hex``
  and version ``git:<short-sha>`` so downstream can decide.

Implementation: we don't evaluate the Elixir code; we regex-scan for
the ``"name": {:hex, :name, "version",`` pattern.
"""

from __future__ import annotations

import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.mix_lock")


_HEX_RE = re.compile(
    r'"([^"]+)":\s*\{:hex,\s*:([A-Za-z0-9_.-]+),\s*"([^"]+)"'
)
_GIT_RE = re.compile(
    r'"([^"]+)":\s*\{:git,\s*"[^"]+",\s*"([0-9a-f]+)"'
)


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("mix_lock: cannot read %s: %s", path, exc)
        return []

    deps: List[Dependency] = []
    seen = set()

    for key, name, version in _HEX_RE.findall(content):
        # The map key and the :name atom usually match — use the atom name
        # (canonical) but fall back to the key if they differ.
        pkg_name = name or key
        if not pkg_name or not version:
            continue
        unique = (pkg_name.lower(), version)
        if unique in seen:
            continue
        seen.add(unique)
        deps.append(
            Dependency(
                name=pkg_name,
                version=version,
                ecosystem="hex",
                source_file=path,
                transitivity="transitive",  # mix.lock is the full resolution
            )
        )

    for key, sha in _GIT_RE.findall(content):
        if not key or not sha:
            continue
        unique = (key.lower(), f"git:{sha[:12]}")
        if unique in seen:
            continue
        seen.add(unique)
        deps.append(
            Dependency(
                name=key,
                version=f"git:{sha[:12]}",
                ecosystem="hex",
                source_file=path,
                transitivity="transitive",
            )
        )

    return deps


__all__ = ["parse"]
