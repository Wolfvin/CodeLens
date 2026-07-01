"""
Parser for ``pyproject.toml`` (PEP 621 + Poetry).

Format reference (public PEP 621 + Poetry docs, reimplemented — no code
copied):
- TOML file. We use the stdlib ``tomllib`` (Python 3.11+) and fall back
  to ``tomli`` if available.
- Deps are declared in:
  * ``[project.dependencies]`` — PEP 621 list of strings.
  * ``[project.optional-dependencies.<extra>]`` — PEP 621 lists.
  * ``[tool.poetry.dependencies]`` — Poetry table ``name = "spec"``.
  * ``[tool.poetry.group.<g>.dependencies]`` — Poetry per-group deps.
- Version specifiers follow PEP 440. We strip the leading operator and
  take the first version-like token. Unpinned (``*``) → ``"0.0.0"``.

This module also re-exports ``parse_poetry_lock`` for ``poetry.lock``
so the registry can route that filename here.
"""

from __future__ import annotations

import logging
import re
from typing import List

from . import Dependency

logger = logging.getLogger("codelens.sca.pyproject_toml")


try:
    import tomllib as _toml  # py311+
except ImportError:  # pragma: no cover
    try:
        import tomli as _toml  # type: ignore
    except ImportError:
        _toml = None  # type: ignore


_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
# Match leading PEP 440 operators plus Poetry's `^`/`~` and npm-style `*`.
_VERSION_OP_RE = re.compile(r"^(==|!=|<=|>=|~=|>|<|===|\^|~)\s*([A-Za-z0-9_.*+!-]+)")


def _normalise_spec(spec: str) -> str:
    """Strip leading version operators and return a bare version string.

    Handles PEP 440 (==, !=, <=, >=, ~=, >, <, ===), Poetry caret/tilde
    (``^1.2``, ``~1.2.3``), and bare versions (``1.2.3``). Returns
    ``"0.0.0"`` for unpinned (``*`` or empty).
    """
    if not spec:
        return "0.0.0"
    spec = spec.strip()
    if spec in ("*", ""):
        return "0.0.0"
    m = _VERSION_OP_RE.match(spec)
    if m:
        return m.group(2).split(",")[0]
    first = spec.split(",")[0].split()[0]
    if re.match(r"^\d", first):
        return first
    return "0.0.0"


def _emit(name: str, version_spec, path: str, deps: list, seen: set) -> None:
    """Append a Dependency to ``deps`` (deduplicated by lower(name)+version)."""
    if not isinstance(name, str) or not name:
        return
    if isinstance(version_spec, str):
        version = _normalise_spec(version_spec)
    elif isinstance(version_spec, dict):
        v = version_spec.get("version", "")
        version = _normalise_spec(v) if isinstance(v, str) else "0.0.0"
    else:
        version = "0.0.0"
    key = (name.lower(), version)
    if key in seen:
        return
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


def parse(path: str) -> List[Dependency]:
    if _toml is None:
        logger.warning("pyproject_toml: tomllib/tomli not available, skipping %s", path)
        return []
    try:
        with open(path, "rb") as f:
            data = _toml.load(f)
    except Exception as exc:
        logger.warning("pyproject_toml: cannot parse %s: %s", path, exc)
        return []

    if not isinstance(data, dict):
        return []

    deps: List[Dependency] = []
    seen: set = set()

    # ── PEP 621 [project.dependencies] ──
    project = data.get("project", {}) or {}
    if isinstance(project, dict):
        for entry in project.get("dependencies", []) or []:
            if isinstance(entry, str):
                m = _NAME_RE.match(entry)
                if not m:
                    continue
                name = m.group(1)
                rest = entry[m.end():].strip()
                # Strip extras `[foo]` and markers `; python_version<'3.10'`
                rest = rest.split(";", 1)[0].strip()
                version = _normalise_spec(rest)
                _emit(name, version if version else "0.0.0", path, deps, seen)
        # Optional extras
        opt = project.get("optional-dependencies", {}) or {}
        if isinstance(opt, dict):
            for _group, entries in opt.items():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, str):
                        continue
                    m = _NAME_RE.match(entry)
                    if not m:
                        continue
                    name = m.group(1)
                    rest = entry[m.end():].strip().split(";", 1)[0].strip()
                    version = _normalise_spec(rest)
                    _emit(name, version if version else "0.0.0", path, deps, seen)

    # ── Poetry [tool.poetry.dependencies] ──
    tool = data.get("tool", {}) or {}
    if isinstance(tool, dict):
        poetry = tool.get("poetry", {}) or {}
        if isinstance(poetry, dict):
            _poetry_section_deps(poetry.get("dependencies", {}), path, deps, seen)
            groups = poetry.get("group", {}) or {}
            if isinstance(groups, dict):
                for _gname, gdata in groups.items():
                    if not isinstance(gdata, dict):
                        continue
                    _poetry_section_deps(gdata.get("dependencies", {}), path, deps, seen)

    return deps


def _poetry_section_deps(section: dict, path: str, deps: list, seen: set) -> None:
    if not isinstance(section, dict):
        return
    for name, spec in section.items():
        # Skip Python version constraint entry: `python = ">=3.8"`
        if name.lower() == "python":
            continue
        _emit(name, spec, path, deps, seen)


# ── poetry.lock support ────────────────────────────────────────


def parse_poetry_lock(path: str) -> List[Dependency]:
    """Parse ``poetry.lock`` (TOML form, Poetry 1.2+).

    Falls back gracefully if tomllib is unavailable.
    """
    if _toml is None:
        logger.warning("pyproject_toml: tomllib not available, cannot parse poetry.lock %s", path)
        return []
    try:
        with open(path, "rb") as f:
            data = _toml.load(f)
    except Exception as exc:
        logger.warning("pyproject_toml: cannot parse poetry.lock %s: %s", path, exc)
        return []
    if not isinstance(data, dict):
        return []
    packages = data.get("package", []) or []
    if not isinstance(packages, list):
        return []
    deps: List[Dependency] = []
    seen = set()
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        if not name or not version:
            continue
        # poetry.lock carries a `category = "main|dev"` field; both are
        # resolved deps, mark as direct (Poetry treats them as such).
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


__all__ = ["parse", "parse_poetry_lock"]
