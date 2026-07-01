"""
Parser for ``Pipfile`` (declared deps, non-lock).

Format reference (public Pipenv docs, reimplemented — no code copied):
- TOML file with ``[packages]`` and ``[dev-packages]`` sections.
- Each entry is ``name = "version_spec"`` or
  ``name = {version = "version_spec", extras = [...], ...}``.
- Version specifiers follow pip semantics (``==1.2.3``, ``>=1.2``,
  ``*`` for unpinned).
- We strip the leading operator and extras to get a bare version
  number. Unpinned deps (``*`` or empty) get version ``"0.0.0"``.
"""

from __future__ import annotations

import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.pipfile")


_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*=\s*(.*)$")
_VERSION_TABLE_RE = re.compile(r'version\s*=\s*"([^"]*)"')


def _normalise_version(spec: str) -> str:
    if not spec:
        return "0.0.0"
    spec = spec.strip()
    if spec in ("*", ""):
        return "0.0.0"
    cleaned = re.sub(r"^[><=!~]+", "", spec)
    cleaned = cleaned.split(",")[0].strip()
    if not cleaned or cleaned == "*":
        return "0.0.0"
    if re.match(r"^\d", cleaned):
        return cleaned
    return "0.0.0"


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("pipfile: cannot read %s: %s", path, exc)
        return []

    deps: List[Dependency] = []
    seen = set()

    in_section = False  # True when inside [packages] or [dev-packages]

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped in ("[packages]", "[dev-packages]")
            continue
        if not in_section:
            continue
        m = _NAME_RE.match(stripped)
        if not m:
            continue
        name = m.group(1)
        rest = m.group(2).strip()
        if rest.startswith("{"):
            tm = _VERSION_TABLE_RE.search(rest)
            version = _normalise_version(tm.group(1)) if tm else "0.0.0"
        elif rest.startswith('"'):
            vm = re.match(r'^"([^"]*)"', rest)
            version = _normalise_version(vm.group(1)) if vm else "0.0.0"
        elif rest.startswith("'"):
            vm = re.match(r"^'([^']*)'", rest)
            version = _normalise_version(vm.group(1)) if vm else "0.0.0"
        elif rest == "*":
            version = "0.0.0"
        else:
            version = "0.0.0"
        if not name:
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
