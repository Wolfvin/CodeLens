"""
Parser for ``requirements.txt`` (pinned + unpinned).

Format reference (public PEP 508 / pip docs, reimplemented — no code copied):
- One requirement per line.
- Comments start with ``#`` and may appear inline.
- ``-r other.txt``, ``-e .``, ``-c constraints.txt`` and similar pip
  options start with ``-`` — skipped.
- Forms handled:
  * ``package==1.2.3``
  * ``package>=1.2.3,<2.0.0``
  * ``package~=1.2.3``
  * ``package[extra]==1.2.3``
  * ``package (extras)`` — wait, that's setup.cfg; we ignore.
  * ``package``                       (unpinned → version "0.0.0")
  * ``package @ https://.../pkg.tar.gz`` (URL — name recorded, version "0.0.0")
  * ``git+https://github.com/x/y@v1.0#egg=y`` (egg name extracted)
- Environment markers (``; python_version<'3.10'``) are stripped.
"""

from __future__ import annotations

import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.requirements_txt")


_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?")
_VERSION_OP_RE = re.compile(r"^(==|!=|<=|>=|~=|>|<|===)\s*([A-Za-z0-9_.*+!-]+)")


def _extract_version(spec: str) -> str:
    """Extract a concrete version number from a pip version specifier.

    Returns ``"0.0.0"`` if no version is pinned.
    """
    spec = spec.strip()
    if not spec:
        return "0.0.0"
    m = _VERSION_OP_RE.match(spec)
    if not m:
        # Bare version with no operator? Take leading version-like token.
        first = spec.split(",")[0].split()[0]
        if re.match(r"^[0-9]", first):
            return first
        return "0.0.0"
    op = m.group(1)
    ver = m.group(2)
    # Strip trailing extras like `,<2.0`
    ver = ver.split(",")[0]
    if op in ("==", "==="):
        # Exact pin — strip any ``.*`` wildcard suffix.
        return ver.rstrip(".*") if ".*" in ver else ver
    # Other operators — take the bare version as the lower bound estimate.
    return ver


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("requirements_txt: cannot read %s: %s", path, exc)
        return []

    deps: List[Dependency] = []
    seen = set()

    for raw_line in content.splitlines():
        # Strip inline comments
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        # Skip pip options
        if line.startswith("-"):
            continue
        # Strip environment markers: `pkg==1.0 ; python_version<'3.10'`
        line = line.split(";", 1)[0].strip()
        # Handle `name @ url` syntax
        if " @ " in line:
            name_part = line.split(" @ ", 1)[0].strip()
            m = _NAME_RE.match(name_part)
            if not m:
                continue
            name = m.group(1)
            version = "0.0.0"
        else:
            m = _NAME_RE.match(line)
            if not m:
                continue
            name = m.group(1)
            rest = line[m.end():].strip()
            # Strip leading whitespace and operators
            version = _extract_version(rest)
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
                # requirements.txt is a manifest; all entries are direct.
                transitivity="direct",
            )
        )

    return deps


__all__ = ["parse"]
