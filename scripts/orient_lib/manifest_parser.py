# @WHO:   scripts/orient_lib/manifest_parser.py
# @WHAT:  Run/build/test command extraction from manifest files
# @PART:  orient
# @ENTRY: extract_commands()

"""
Manifest parser for the ``codelens orient`` command.

Extracts run/build/test/dev commands from the project's manifest files
(``package.json`` scripts, ``Makefile``, ``pyproject.toml``,
``Cargo.toml``, ``go.mod``, ``pom.xml`` / ``build.gradle``). Each
extracted command is classified into a semantic ``kind``::

    dev    — start dev server / watch mode
    build  — compile / bundle the project
    test   — run the test suite
    lint   — run linter
    deploy — deploy / publish
    run    — run the app (production)
    other  — anything else

No subprocess is used — purely filesystem reads + regex parsing.

Reference: issue #160.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

__all__ = ["extract_commands"]

_logger = logging.getLogger("codelens.orient.manifest_parser")


# ─── Classification rules ──────────────────────────────────────
#
# A script name maps to a ``kind`` based on the first matching keyword.
# Order matters — more specific kinds first (e.g. "test:e2e" → test
# before "e2e" → other).

_KIND_RULES: List[tuple] = [
    ("dev", ("dev", "start", "serve", "watch", "nodemon")),
    ("build", ("build", "compile", "bundle", "dist", "webpack", "vite")),
    ("test", ("test", "spec", "coverage", "pytest", "jest", "vitest")),
    ("lint", ("lint", "eslint", "ruff", "flake8", "mypy", "pylint", "check")),
    ("deploy", ("deploy", "publish", "release", "ship")),
    ("run", ("run", "exec", "start:prod", "prod")),
]


def _classify_script(name: str) -> str:
    """Classify a script name into a semantic kind."""
    lower = name.lower()
    for kind, keywords in _KIND_RULES:
        for kw in keywords:
            if kw in lower:
                return kind
    return "other"


def _read_text(path: str, max_bytes: int = 256 * 1024) -> Optional[str]:
    """Read a file as UTF-8 text, return None on any I/O error."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_bytes)
    except OSError:
        return None


# ─── Per-manifest parsers ──────────────────────────────────────


def _parse_package_json_scripts(workspace: str) -> List[Dict[str, Any]]:
    """Extract commands from package.json ``scripts`` block."""
    path = os.path.join(workspace, "package.json")
    text = _read_text(path)
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        _logger.warning("[orient/manifest_parser] invalid package.json at %s", path)
        return []
    scripts = data.get("scripts", {}) or {}
    commands: List[Dict[str, Any]] = []
    for name, cmd in scripts.items():
        if not isinstance(cmd, str) or not cmd.strip():
            continue
        kind = _classify_script(name)
        commands.append({
            "kind": kind,
            "command": f"npm run {name}",
            "description": f"package.json script: {name}",
            "raw": cmd,
        })
    return commands


def _parse_makefile(workspace: str) -> List[Dict[str, Any]]:
    """Extract targets from Makefile (or makefile, GNUmakefile)."""
    commands: List[Dict[str, Any]] = []
    for fname in ("Makefile", "makefile", "GNUmakefile"):
        path = os.path.join(workspace, fname)
        text = _read_text(path)
        if not text:
            continue
        seen: set = set()
        for line in text.splitlines():
            # Target line: ``name: deps`` — skip if it's a recipe line
            # (starts with tab) or a variable assignment (``VAR =``).
            if line.startswith("\t") or line.startswith(" "):
                continue
            m = re.match(r"^([A-Za-z0-9_.\-]+)\s*:\s*", line)
            if not m:
                continue
            target = m.group(1)
            if target in seen or target.startswith("."):
                # Skip phony/automatic targets like .PHONY, .DEFAULT.
                continue
            seen.add(target)
            kind = _classify_script(target)
            commands.append({
                "kind": kind,
                "command": f"make {target}",
                "description": f"Makefile target: {target}",
                "raw": "",
            })
        break  # Only parse the first Makefile found.
    return commands


def _parse_pyproject_scripts(workspace: str) -> List[Dict[str, Any]]:
    """Extract ``[project.scripts]`` console entry points from pyproject.toml."""
    path = os.path.join(workspace, "pyproject.toml")
    text = _read_text(path)
    if not text:
        return []
    commands: List[Dict[str, Any]] = []
    # [project.scripts] block — name = "module:func"
    block = re.search(
        r"^\s*\[project\.scripts\]\s*$(.*?)(?=^\s*\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if block:
        for line in block.group(1).splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_.\-]+)\s*=\s*"([^"]+)"', line)
            if m:
                name, target = m.group(1), m.group(2)
                commands.append({
                    "kind": "run",
                    "command": name,
                    "description": f"console script -> {target}",
                    "raw": target,
                })
    # Look for common dev/test commands in optional-dependencies or
    # tool config — best-effort: if pytest is a dep, suggest pytest.
    if "pytest" in text.lower():
        commands.append({
            "kind": "test",
            "command": "pytest",
            "description": "pytest test runner (detected in pyproject.toml)",
            "raw": "",
        })
    if "ruff" in text.lower():
        commands.append({
            "kind": "lint",
            "command": "ruff check .",
            "description": "ruff linter (detected in pyproject.toml)",
            "raw": "",
        })
    return commands


def _parse_cargo_alias(workspace: str) -> List[Dict[str, Any]]:
    """Extract ``[alias]`` entries from Cargo.toml ``[cargo-aliases]``."""
    path = os.path.join(workspace, "Cargo.toml")
    text = _read_text(path)
    if not text:
        return []
    commands: List[Dict[str, Any]] = []
    block = re.search(
        r"^\s*\[alias\]\s*$(.*?)(?=^\s*\[|\Z)",
        text, re.MULTILINE | re.DOTALL,
    )
    if block:
        for line in block.group(1).splitlines():
            m = re.match(r'^\s*([A-Za-z0-9_\-]+)\s*=\s*"([^"]+)"', line)
            if m:
                name = m.group(1)
                kind = _classify_script(name)
                commands.append({
                    "kind": kind,
                    "command": f"cargo {name}",
                    "description": f"cargo alias: {name}",
                    "raw": m.group(2),
                })
    # Standard cargo commands are always available — suggest the common ones.
    commands.append({
        "kind": "build", "command": "cargo build",
        "description": "Compile the project", "raw": "",
    })
    commands.append({
        "kind": "test", "command": "cargo test",
        "description": "Run tests", "raw": "",
    })
    return commands


def _parse_go_directives(workspace: str) -> List[Dict[str, Any]]:
    """Suggest standard ``go`` commands when a go.mod is present."""
    if not os.path.isfile(os.path.join(workspace, "go.mod")):
        return []
    return [
        {"kind": "build", "command": "go build ./...",
         "description": "Compile all packages", "raw": ""},
        {"kind": "test", "command": "go test ./...",
         "description": "Run all tests", "raw": ""},
        {"kind": "run", "command": "go run .",
         "description": "Run the main package", "raw": ""},
    ]


def _parse_maven_gradle(workspace: str) -> List[Dict[str, Any]]:
    """Suggest Maven/Gradle build commands when a pom.xml/build.gradle exists."""
    commands: List[Dict[str, Any]] = []
    if os.path.isfile(os.path.join(workspace, "pom.xml")):
        commands.extend([
            {"kind": "build", "command": "mvn package",
             "description": "Maven build + package", "raw": ""},
            {"kind": "test", "command": "mvn test",
             "description": "Maven test", "raw": ""},
        ])
    for gname in ("build.gradle", "build.gradle.kts"):
        if os.path.isfile(os.path.join(workspace, gname)):
            commands.extend([
                {"kind": "build", "command": "./gradlew build",
                 "description": "Gradle build", "raw": ""},
                {"kind": "test", "command": "./gradlew test",
                 "description": "Gradle test", "raw": ""},
            ])
            break
    return commands


# ─── Public entry ──────────────────────────────────────────────


# @FLOW:    ORIENT_COMMANDS
# @CALLS:   _parse_package_json_scripts() -> npm run <name>
#           _parse_makefile() -> make <target>
#           _parse_pyproject_scripts() -> console scripts + pytest/ruff
#           _parse_cargo_alias() -> cargo <alias> + cargo build/test
#           _parse_go_directives() -> go build/test/run
#           _parse_maven_gradle() -> mvn/gradlew build/test
# @MUTATES: (none — pure read)


def extract_commands(workspace: str) -> List[Dict[str, Any]]:
    """Extract run/build/test commands from all manifest files.

    Args:
        workspace: Absolute path to the project root.

    Returns:
        List of command dicts, each::

            {
                "kind": "dev" | "build" | "test" | "lint" | "deploy" | "run" | "other",
                "command": "npm run dev",
                "description": "package.json script: dev",
                "raw": "next dev"
            }

        The ``raw`` field holds the underlying script string when
        available (empty for inferred commands). Commands are
        de-duplicated by ``(kind, command)``.
    """
    workspace = os.path.abspath(workspace)
    all_commands: List[Dict[str, Any]] = []
    all_commands.extend(_parse_package_json_scripts(workspace))
    all_commands.extend(_parse_makefile(workspace))
    all_commands.extend(_parse_pyproject_scripts(workspace))
    all_commands.extend(_parse_cargo_alias(workspace))
    all_commands.extend(_parse_go_directives(workspace))
    all_commands.extend(_parse_maven_gradle(workspace))

    # De-duplicate by (kind, command) — keep the first occurrence.
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for cmd in all_commands:
        key = (cmd["kind"], cmd["command"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cmd)
    return deduped
