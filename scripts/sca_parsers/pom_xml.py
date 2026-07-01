"""
Parser for ``pom.xml`` (Maven declared dependencies).

Format reference (public Maven POM spec, reimplemented — no code copied):
- XML file with ``<project>`` root, ``<dependencies>`` under either
  ``<project>`` directly or under ``<dependencyManagement>`` /
  ``<profiles>``.
- Each ``<dependency>`` has ``<groupId>``, ``<artifactId>``, ``<version>``
  and optional ``<scope>``. We use ``group:artifact`` as the package name
  to match OSV.dev's Maven ecosystem convention.
- Maven properties (``${project.version}``, ``${spring.version}``,
  ``${revision}`` etc.) are NOT resolved — we emit the literal string
  and downstream tooling can decide to skip properties.
- We avoid using external XML parser dependencies other than the stdlib
  ``xml.etree.ElementTree`` which is MIT-licensed and compatible.
"""

from __future__ import annotations

import logging
import re
from typing import List
from xml.etree import ElementTree as ET

from . import Dependency

logger = logging.getLogger("codelens.sca.pom_xml")


def _strip_namespace(root: ET.Element) -> ET.Element:
    """Recursively strip the XML namespace from every element's tag.

    Maven pom.xml uses a default namespace (``xmlns="..."``) which makes
    every tag like ``{http://maven.apache.org/POM/4.0.0}dependency``
    instead of bare ``dependency``. Stripping makes ``find()`` and
    ``iter()`` work with the unprefixed names from the spec.
    """
    for elem in root.iter():
        if isinstance(elem.tag, str) and "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _text(parent: ET.Element, tag: str) -> str:
    """Return stripped text of the first direct child ``tag`` of ``parent``."""
    if parent is None:
        return ""
    child = parent.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _collect_dependencies(root: ET.Element) -> List[ET.Element]:
    """Find all <dependency> elements anywhere under ``root``."""
    return list(root.iter("dependency"))


def parse(path: str) -> List[Dependency]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        logger.warning("pom_xml: cannot parse %s: %s", path, exc)
        return []
    except Exception as exc:
        logger.warning("pom_xml: cannot read %s: %s", path, exc)
        return []

    root = _strip_namespace(tree.getroot())
    deps: List[Dependency] = []
    seen = set()

    for dep in _collect_dependencies(root):
        group_id = _text(dep, "groupId")
        artifact_id = _text(dep, "artifactId")
        version = _text(dep, "version")
        scope = _text(dep, "scope")

        if not group_id or not artifact_id:
            continue
        # Skip Maven-injected test/provided/runtime-only deps from
        # dependencyManagement — we still want them recorded but marked
        # transitive is misleading; instead we keep them as direct
        # declared deps (the user explicitly listed them).
        if not version:
            # Inherited from dependencyManagement without explicit version.
            version = "0.0.0"

        # Maven version strings may reference properties: ${foo}. Keep
        # them as-is; downstream consumers can choose to skip these.
        name = f"{group_id}:{artifact_id}"
        key = (name.lower(), version)
        if key in seen:
            continue
        seen.add(key)

        transitivity = "direct"
        if scope in ("test", "provided", "runtime"):
            # Still declared by the user, but non-runtime scope.
            # We keep "direct" because they are explicitly listed.
            transitivity = "direct"

        deps.append(
            Dependency(
                name=name,
                version=version,
                ecosystem="maven",
                source_file=path,
                transitivity=transitivity,
            )
        )

    return deps


__all__ = ["parse"]
