"""
CodeLens SCA (Software Composition Analysis) lockfile parsers.

This package implements pluggable parsers for dependency lockfiles and
manifests across many ecosystems. Each parser lives in its own module and
exposes a ``parse(path: str) -> List[Dependency]`` function.

Public API:
    Dependency          — dataclass representing a single resolved dependency
    parse_lockfile      — auto-detect format from filename and dispatch
    PARSER_REGISTRY     — mapping of filename -> parser module

Design rules (Issue #53):
- Reimplemented from public format specs — no code copied from other
  projects (LGPL/GPL incompatibility).
- Graceful failure: a parser that errors must log a warning and return []
  so the rest of the vuln-scan keeps working.
- Pure parsing: no network calls, no subprocess, no VULN_DB lookups here.
  vulnscan_engine.py is responsible for matching against VULN_DB.
"""

from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("codelens.sca")


# ─── Dependency dataclass ──────────────────────────────────────


@dataclass
class Dependency:
    """A single resolved dependency extracted from a lockfile or manifest.

    Attributes:
        name:        Package name (e.g. "lodash", "serde", "rails").
        version:     Resolved version string (e.g. "4.17.21"). For unpinned
                     manifests the bare specifier is preserved; downstream
                     code may treat "0.0.0"/"*" as "unknown".
        ecosystem:   One of: pypi, npm, cargo, maven, gem, nuget, pub,
                     hex, swiftpm, gradle, composer, mix, go.
        source_file: Path of the lockfile/manifest this dep was parsed
                     from (relative to workspace or absolute, as given).
        transitivity: "direct" or "transitive". "direct" means the dep
                     is declared at the top level of the manifest;
                     "transitive" means it was pulled in as a sub-dep
                     and only appears in the lockfile. Defaults to
                     "direct" for manifests; lockfile parsers may set
                     "transitive" when they can tell.
    """

    name: str
    version: str
    ecosystem: str
    source_file: str
    transitivity: str = "direct"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


# ─── Parser registry ───────────────────────────────────────────
#
# Mapping of canonical filename -> parser module name (relative to this
# package). Multiple aliases can point to the same module.
#
# Keys are filenames (case-sensitive on POSIX). Lookup is also done by
# basename so that nested lockfiles (e.g. packages/foo/Gemfile.lock) are
# still recognised.

PARSER_REGISTRY: Dict[str, str] = {
    # JS / Node
    "pnpm-lock.yaml": "pnpm_lock",
    "yarn.lock": "yarn_lock",
    # Python
    "Pipfile.lock": "pipfile_lock",
    "Pipfile": "pipfile",
    "requirements.txt": "requirements_txt",
    "pyproject.toml": "pyproject_toml",
    # Ruby
    "Gemfile.lock": "gemfile_lock",
    # PHP
    "composer.lock": "composer_lock",
    # .NET
    "packages.lock.json": "packages_lock",
    # Dart
    "pubspec.lock": "pubspec_lock",
    # Swift
    "Package.resolved": "package_resolved",
    # Gradle / Maven
    "gradle.lockfile": "gradle_lock",
    "build.gradle": "gradle_lock",
    "pom.xml": "pom_xml",
    # Elixir
    "mix.lock": "mix_lock",
    # NOTE: poetry.lock is intentionally NOT registered here — it stays
    # handled by the existing inline _parse_poetry_lock() in
    # vulnscan_engine.py (it predates Issue #53 and is not in the
    # "14 new parsers" list).
}


# Filename -> ecosystem, used by vulnscan_engine to know which VULN_DB
# ecosystem key to use when matching. Only files handled by this
# package are listed.
ECOSYSTEM_BY_FILE: Dict[str, str] = {
    "pnpm-lock.yaml": "npm",
    "yarn.lock": "npm",
    "Pipfile.lock": "pypi",
    "Pipfile": "pypi",
    "requirements.txt": "pypi",
    "pyproject.toml": "pypi",
    "Gemfile.lock": "gem",
    "composer.lock": "composer",
    "packages.lock.json": "nuget",
    "pubspec.lock": "pub",
    "Package.resolved": "swiftpm",
    "gradle.lockfile": "gradle",
    "build.gradle": "gradle",
    "pom.xml": "maven",
    "mix.lock": "hex",
}


def _load_parser(module_name: str):
    """Import a parser module by name (cached by Python's import system)."""
    full = f"sca_parsers.{module_name}"
    try:
        return importlib.import_module(full)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("sca_parsers: failed to import %s: %s", full, exc)
        return None


def parse_lockfile(path: str) -> Tuple[List[Dependency], Optional[str]]:
    """Auto-detect the format of ``path`` and parse it.

    Returns:
        (deps, ecosystem) where ``deps`` is a list of Dependency objects
        (possibly empty) and ``ecosystem`` is the canonical ecosystem
        string or None if the format is not recognised.

        On parser error returns ([], None) and logs a warning — never
        raises, so callers can keep scanning other files.
    """
    basename = os.path.basename(path)
    module_name = PARSER_REGISTRY.get(basename)
    if module_name is None:
        return [], None

    mod = _load_parser(module_name)
    if mod is None:
        return [], None

    try:
        deps = mod.parse(path)
    except Exception as exc:
        logger.warning("sca_parsers: %s.parse(%s) failed: %s", module_name, path, exc)
        return [], None

    # Defensive: parsers must return a list of Dependency objects.
    if not isinstance(deps, list):
        logger.warning("sca_parsers: %s.parse returned non-list: %r", module_name, type(deps))
        return [], None

    ecosystem = ECOSYSTEM_BY_FILE.get(basename)
    return deps, ecosystem


__all__ = [
    "Dependency",
    "PARSER_REGISTRY",
    "ECOSYSTEM_BY_FILE",
    "parse_lockfile",
]
