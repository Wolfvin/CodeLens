"""
Parser for ``yarn.lock`` (Yarn v1 Classic, v2/v3 Berry, PnP).

Format reference (public, reimplemented from spec):
- v1 (Classic): text-based. Blocks start with one or more quoted or
  unquoted specifiers followed by ``:``. Inside the block, ``version
  "x.y.z"`` declares the resolved version. Multiple specifiers can
  resolve to the same version.
- v2+ (Berry): same textual shape, with an optional ``__metadata``
  block at the top containing ``cacheKey`` and ``version``. Berry may
  also include resolution fields like ``resolution: "..."``.
- PnP (.pnp.cjs/.pnp.js): not handled here — those are not lockfiles
  in the same sense; this parser only handles yarn.lock text files.
"""

from __future__ import annotations

import logging
import re
from typing import List, Set, Tuple

from . import Dependency

logger = logging.getLogger("codelens.sca.yarn")


_SPEC_RE = re.compile(r'^"?([^@].*?)@([^@/]+)"?$')
# Match a yarn v2+ resolution line that ends with the npm spec
_NPM_RESOLUTION_RE = re.compile(r'^resolution:\s+"?npm:([^@]+)@([^@/]+)"?$')


def _split_specifier(spec: str) -> Tuple[str, str]:
    """Split ``name@version`` (or ``@scope/name@version``) into (name, version)."""
    spec = spec.strip().strip('"')
    if not spec:
        return ("", "")
    at_idx = spec.rfind("@")
    if at_idx <= 0:
        return (spec, "")
    return (spec[:at_idx], spec[at_idx + 1:])


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("yarn_lock: cannot read %s: %s", path, exc)
        return []

    deps: List[Dependency] = []
    seen: Set[Tuple[str, str]] = set()

    current_names: List[str] = []
    current_version: str = ""
    in_block = False

    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # New block: line ends with ":" and is at column 0
        if stripped.endswith(":") and not raw_line.startswith((" ", "\t")):
            # Flush previous
            if in_block and current_names and current_version:
                for n in current_names:
                    if (n, current_version) not in seen:
                        seen.add((n, current_version))
                        deps.append(
                            Dependency(
                                name=n,
                                version=current_version,
                                ecosystem="npm",
                                source_file=path,
                                transitivity="transitive",
                            )
                        )
            # Begin new block
            spec_part = stripped[:-1]
            current_names = []
            current_version = ""
            for piece in spec_part.split(", "):
                name, _ver = _split_specifier(piece)
                if name:
                    current_names.append(name)
            in_block = bool(current_names)
            continue

        if not in_block:
            continue

        # Version line: `version "x.y.z"` (yarn v1 / Berry)
        m = re.match(r'^version\s+"([^"]+)"', stripped)
        if m:
            current_version = m.group(1)
            continue

        # Berry npm: resolution line carries the canonical name+version
        m = _NPM_RESOLUTION_RE.match(stripped)
        if m and current_names:
            # Override version with the resolved one
            current_version = m.group(2)

    # Flush last block
    if in_block and current_names and current_version:
        for n in current_names:
            if (n, current_version) not in seen:
                seen.add((n, current_version))
                deps.append(
                    Dependency(
                        name=n,
                        version=current_version,
                        ecosystem="npm",
                        source_file=path,
                        transitivity="transitive",
                    )
                )

    return deps


__all__ = ["parse"]
