"""
Parser for Gradle lockfiles (``gradle.lockfile``) and ``build.gradle``
(declared deps).

Format reference (public, reimplemented from spec):

``gradle.lockfile`` (Gradle 6+ dependency locking):
- Plain-text, line-per-dependency, format:
  ``<group>:<artifact>:<version>:<configuration>=<unused>``
  e.g. ``com.google.code.gson:gson:2.8.9:compileClasspath=2.8.9``
- Empty lines and lines starting with ``#`` are comments. There is a
  header block starting with ``# This is a Gradle dependency locking
  file`` that we ignore.
- We split on the LAST ``=`` to separate the config key from the
  unused marker, then split the key on ``:``.

``build.gradle`` (Groovy DSL, declared deps):
- ``dependencies { ... }`` block with lines like
  ``implementation 'group:artifact:version'`` or
  ``testImplementation "group:artifact:version"``.
- We extract (group, artifact, version) and emit ``group:artifact`` as
  the package name.
"""

from __future__ import annotations

import logging
import os
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.gradle_lock")


# Match: <group>:<artifact>:<version>[:<configuration>]=<unused>
_LOCKFILE_LINE_RE = re.compile(
    r"^([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.+-]+)(?::[^=]+)?=.*$"
)

# Match Groovy dep declarations: configuration 'group:artifact:version'
# (single or double quotes, optional map-style attributes)
_GRADLE_DEP_RE = re.compile(
    r"""^\s*(?:[A-Za-z][A-Za-z0-9_]*(?:\s*\([^)]*\))?\s+)     # configuration name
        ['"]([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([A-Za-z0-9_.+-]+)['"]
    """,
    re.VERBOSE,
)


def _parse_gradle_lockfile(content: str, path: str) -> List[Dependency]:
    deps: List[Dependency] = []
    seen = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _LOCKFILE_LINE_RE.match(line)
        if not m:
            continue
        group, artifact, version = m.group(1), m.group(2), m.group(3)
        name = f"{group}:{artifact}"
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        deps.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="gradle",
                source_file=path,
                # gradle.lockfile contains both direct and transitive;
                # without context we mark transitive.
                transitivity="transitive",
            )
        )
    return deps


def _parse_build_gradle(content: str, path: str) -> List[Dependency]:
    deps: List[Dependency] = []
    seen = set()
    in_deps = False
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        # Enter dependencies block
        if re.match(r"^dependencies\s*\{?\s*$", stripped) or re.match(
            r"^dependencies\s*\{", stripped
        ):
            in_deps = True
            continue
        if in_deps and stripped == "}":
            in_deps = False
            continue
        if not in_deps:
            continue
        m = _GRADLE_DEP_RE.match(raw_line)
        if not m:
            continue
        group, artifact, version = m.group(1), m.group(2), m.group(3)
        name = f"{group}:{artifact}"
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)
        deps.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="gradle",
                source_file=path,
                transitivity="direct",
            )
        )
    return deps


def parse(path: str) -> List[Dependency]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as exc:
        logger.warning("gradle_lock: cannot read %s: %s", path, exc)
        return []

    basename = os.path.basename(path)
    if basename == "gradle.lockfile":
        return _parse_gradle_lockfile(content, path)
    if basename in ("build.gradle", "build.gradle.kts"):
        return _parse_build_gradle(content, path)
    # Unknown but routed here — try lockfile shape first (more reliable),
    # then build.gradle shape as a fallback.
    if "=" in content and ":" in content:
        return _parse_gradle_lockfile(content, path)
    return _parse_build_gradle(content, path)


__all__ = ["parse"]
