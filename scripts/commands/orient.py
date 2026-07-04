# @WHO:   scripts/commands/orient.py
# @WHAT:  orient command — 10-second codebase orientation brief
# @PART:  commands
# @ENTRY: cmd_orient()

"""
orient command — Produce a 10-second codebase orientation brief.

Answers the first four questions a developer asks when entering an
unfamiliar repo:

1. What framework/stack is this?       (framework_db.detect_frameworks_brief)
2. How do I run, build, and test it?   (manifest_parser.extract_commands)
3. Where do I start reading?           (file_ranker.rank_start_here_files)
4. What CI/Docker infrastructure exists? (inline detection in this module)

The command is pure-filesystem: no subprocess, no network, no LSP. It
reads manifest files, walks the source tree once, and emits a single
structured brief. ``--format compact`` produces a single-line brief
suitable for LLM context generation (target: <=300 tokens).

Reference: issue #160. Ported from codeglance (TypeScript, MIT) —
rewritten in Python idioms, no code copied.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

from commands import register_command
from orient_lib import (
    detect_frameworks_brief,
    extract_commands,
    rank_start_here_files,
)

__all__ = ["cmd_orient", "add_args", "execute"]


# ─── Entry point detection ─────────────────────────────────────
#
# Per-ecosystem candidate file lists + manifest "main"/"bin" lookup.
# Returns up to 8 files with a semantic ``type`` label.

_ENTRY_POINT_CANDIDATES: Dict[str, List[tuple]] = {
    "Node.js": [
        ("src/index.ts", "entry"), ("src/index.js", "entry"),
        ("src/main.ts", "entry"), ("src/main.js", "entry"),
        ("src/app.ts", "entry"), ("src/app.js", "entry"),
        ("server.ts", "server"), ("server.js", "server"),
        ("app.ts", "entry"), ("app.js", "entry"),
        ("next.config.js", "config"), ("next.config.mjs", "config"),
        ("next.config.ts", "config"),
    ],
    "Python": [
        ("main.py", "entry"), ("app.py", "entry"),
        ("run.py", "entry"), ("manage.py", "entry"),
        ("wsgi.py", "server"), ("asgi.py", "server"),
        ("__main__.py", "entry"), ("cli.py", "cli"),
    ],
    "Go": [
        ("main.go", "entry"), ("cmd/main.go", "entry"),
        ("cmd/main/main.go", "entry"),
        ("server.go", "server"), ("app.go", "entry"),
    ],
    "Rust": [
        ("src/main.rs", "entry"), ("src/lib.rs", "library"),
        ("main.rs", "entry"), ("src/bin/main.rs", "entry"),
    ],
    "Java": [
        ("src/main/java/Main.java", "entry"),
        ("src/main/java/Application.java", "entry"),
        ("src/main/java/App.java", "entry"),
    ],
}


def _detect_entry_points(workspace: str, ecosystem: str) -> List[Dict[str, str]]:
    """Detect entry point files for the given ecosystem."""
    candidates = _ENTRY_POINT_CANDIDATES.get(ecosystem, [])
    found: List[Dict[str, str]] = []
    seen_paths: set = set()
    for rel_path, entry_type in candidates:
        abs_path = os.path.join(workspace, rel_path)
        if os.path.isfile(abs_path) and rel_path not in seen_paths:
            found.append({"path": rel_path, "type": entry_type})
            seen_paths.add(rel_path)
        if len(found) >= 8:
            break

    # Augment with package.json "main"/"bin" fields for Node.js.
    if ecosystem == "Node.js" and len(found) < 8:
        pkg_main = _read_package_json_main(workspace)
        for entry_path, entry_type in pkg_main:
            if entry_path not in seen_paths:
                found.append({"path": entry_path, "type": entry_type})
                seen_paths.add(entry_path)
            if len(found) >= 8:
                break

    return found


def _read_package_json_main(workspace: str) -> List[tuple]:
    """Extract ``main`` and ``bin`` entry points from package.json."""
    import json
    path = os.path.join(workspace, "package.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    entries: List[tuple] = []
    main_field = data.get("main")
    if isinstance(main_field, str) and main_field:
        entries.append((main_field, "entry"))
    bin_field = data.get("bin")
    if isinstance(bin_field, str) and bin_field:
        entries.append((bin_field, "cli"))
    elif isinstance(bin_field, dict):
        for bin_name, bin_path in bin_field.items():
            if isinstance(bin_path, str):
                entries.append((bin_path, "cli"))
    return entries


# ─── CI / Docker / Env detection ───────────────────────────────


_CI_DIRS = (".github/workflows", ".gitlab-ci", ".circleci")
_CI_FILES = (".travis.yml", "azure-pipelines.yml", "Jenkinsfile",
             "bitbucket-pipelines.yml", ".drone.yml")


def _detect_ci(workspace: str) -> Dict[str, Any]:
    """Detect CI configuration files (filesystem only, no subprocess)."""
    ci_count = 0
    for ci_dir in _CI_DIRS:
        full = os.path.join(workspace, ci_dir)
        if os.path.isdir(full):
            try:
                ci_count += sum(
                    1 for f in os.listdir(full)
                    if f.endswith((".yml", ".yaml")) and not f.startswith(".")
                )
            except OSError:
                pass
    for ci_file in _CI_FILES:
        if os.path.isfile(os.path.join(workspace, ci_file)):
            ci_count += 1
    return {"ci": ci_count > 0, "ci_count": ci_count}


def _detect_docker(workspace: str) -> bool:
    """Detect Dockerfile / docker-compose presence."""
    for name in ("Dockerfile", "Dockerfile.dev", "Dockerfile.prod",
                 "docker-compose.yml", "docker-compose.yaml",
                 "compose.yml", "compose.yaml"):
        if os.path.isfile(os.path.join(workspace, name)):
            return True
    return False


def _detect_env_file(workspace: str) -> bool:
    """Detect ``.env`` or ``.env.example`` presence."""
    for name in (".env", ".env.example", ".env.local", ".env.template"):
        if os.path.isfile(os.path.join(workspace, name)):
            return True
    return False


def _detect_test_framework_and_linter(workspace: str, ecosystem: str) -> Dict[str, Optional[str]]:
    """Detect test framework + linter from config files (heuristic)."""
    result: Dict[str, Optional[str]] = {"test_framework": None, "linter": None}
    files_present: Dict[str, bool] = {}
    try:
        files_present = {
            f: True for f in os.listdir(workspace)
            if os.path.isfile(os.path.join(workspace, f))
        }
    except OSError:
        pass

    if ecosystem == "Node.js":
        if "jest.config.js" in files_present or "jest.config.ts" in files_present:
            result["test_framework"] = "jest"
        elif "vitest.config.ts" in files_present or "vitest.config.js" in files_present:
            result["test_framework"] = "vitest"
        elif os.path.isfile(os.path.join(workspace, "playwright.config.ts")):
            result["test_framework"] = "playwright"
        if ".eslintrc.js" in files_present or ".eslintrc.json" in files_present \
                or ".eslintrc.cjs" in files_present or "eslint.config.js" in files_present:
            result["linter"] = "eslint"
        elif "biome.json" in files_present:
            result["linter"] = "biome"
    elif ecosystem == "Python":
        if any(f.startswith("pytest") for f in files_present) or \
                os.path.isfile(os.path.join(workspace, "pytest.ini")) or \
                os.path.isfile(os.path.join(workspace, "tox.ini")):
            result["test_framework"] = "pytest"
        if os.path.isfile(os.path.join(workspace, ".flake8")) or \
                os.path.isfile(os.path.join(workspace, "setup.cfg")):
            result["linter"] = "flake8"
        elif os.path.isfile(os.path.join(workspace, "ruff.toml")) or \
                os.path.isfile(os.path.join(workspace, ".ruff.toml")):
            result["linter"] = "ruff"
    elif ecosystem == "Go":
        # Go has built-in testing; no config file needed.
        result["test_framework"] = "go test"
    elif ecosystem == "Rust":
        # Cargo has built-in testing.
        result["test_framework"] = "cargo test"
    elif ecosystem == "Java":
        if os.path.isfile(os.path.join(workspace, "pom.xml")):
            result["test_framework"] = "junit (maven)"
        elif os.path.isfile(os.path.join(workspace, "build.gradle")) or \
                os.path.isfile(os.path.join(workspace, "build.gradle.kts")):
            result["test_framework"] = "junit (gradle)"
    return result


# ─── Output rendering ──────────────────────────────────────────


def _render_compact(brief: Dict[str, Any]) -> str:
    """Render the brief as a single-line summary (target <=300 tokens)."""
    fw = brief.get("framework", {})
    eco = fw.get("ecosystem", "Unknown")
    primary = fw.get("primary") or "no primary framework"
    secondary = fw.get("secondary") or []
    sec_str = f" + {', '.join(secondary[:3])}" if secondary else ""
    commands = brief.get("commands", [])
    cmd_str = "; ".join(
        f"{c['command']}({c['kind']})" for c in commands[:5]
    ) if commands else "no commands detected"
    infra = brief.get("infra", {})
    ci = "CI" if infra.get("ci") else "no-CI"
    docker = "Docker" if infra.get("docker") else "no-Docker"
    env = ".env" if infra.get("env_file") else "no-.env"
    start_here = brief.get("start_here", [])
    start_str = ", ".join(f["path"] for f in start_here[:3]) if start_here else "none"
    return (
        f"{eco}/{primary}{sec_str} | {cmd_str} | {ci}/{docker}/{env} | "
        f"start: {start_str}"
    )


# ─── Command entry ─────────────────────────────────────────────


def add_args(parser):
    """Register orient-specific arguments.

    ``workspace`` is an optional positional — if omitted, the CLI
    dispatcher auto-detects from cwd (same pattern as ``scan``,
    ``query``, etc.). ``--format`` overrides the global format flag
    with orient-specific choices (text/json/compact).
    """
    parser.add_argument(
        "workspace", nargs="?", default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text", "compact"],
        default="json",
        help="Output format (default: json). 'compact' = single-line brief "
             "for LLM context (<=300 tokens). 'text' = human-readable.",
    )
    parser.add_argument(
        "--top", type=int, default=8,
        help="Maximum number of Start Here files to return (default: 8)",
    )


# @FLOW:    ORIENT
# @CALLS:   detect_frameworks_brief() -> {ecosystem, primary, secondary, summary}
#           extract_commands() -> [{kind, command, description, raw}]
#           _detect_entry_points() -> [{path, type}]
#           rank_start_here_files() -> [{path, score, reason}]
#           _detect_ci()/_detect_docker()/_detect_env_file() -> infra block
# @MUTATES: (none — pure read; emits structured brief to stdout)


def cmd_orient(workspace: str, top: int = 8) -> Dict[str, Any]:
    """Produce a structured codebase orientation brief.

    Args:
        workspace: Absolute path to the project root.
        top: Maximum number of Start Here files to return.

    Returns:
        Dict matching the orient output schema::

            {
                "status": "ok",
                "workspace": "/path/to/repo",
                "framework": {...},
                "commands": [...],
                "entry_points": [...],
                "start_here": [...],
                "infra": {...}
            }
    """
    workspace = os.path.abspath(workspace)

    framework = detect_frameworks_brief(workspace)
    ecosystem = framework.get("ecosystem", "Unknown")
    commands = extract_commands(workspace)
    entry_points = _detect_entry_points(workspace, ecosystem)
    start_here = rank_start_here_files(workspace, top_n=top)

    infra: Dict[str, Any] = {}
    infra.update(_detect_ci(workspace))
    infra["docker"] = _detect_docker(workspace)
    infra["env_file"] = _detect_env_file(workspace)
    infra.update(_detect_test_framework_and_linter(workspace, ecosystem))

    return {
        "status": "ok",
        "workspace": workspace,
        "framework": framework,
        "commands": commands,
        "entry_points": entry_points,
        "start_here": start_here,
        "infra": infra,
    }


def execute(args, workspace):
    """Run the orient command and handle output format."""
    top = getattr(args, "top", 8) or 8
    brief = cmd_orient(workspace, top=top)

    fmt = getattr(args, "format", None)
    if fmt not in ("json", "text", "compact"):
        fmt = "json"

    if fmt == "compact":
        print(_render_compact(brief))
        brief["_orient_printed_text"] = True
    elif fmt == "text":
        _render_text(brief)
        brief["_orient_printed_text"] = True
    # If json: return the dict and let the global formatter handle it.
    return brief


def _render_text(brief: Dict[str, Any]) -> None:
    """Print a human-readable multi-line orientation brief."""
    fw = brief.get("framework", {})
    print(f"== Codebase Orientation: {brief.get('workspace', '?')} ==")
    print()
    print(f"Framework: {fw.get('ecosystem', 'Unknown')} / {fw.get('primary', 'none')}")
    if fw.get("secondary"):
        print(f"  Secondary: {', '.join(fw['secondary'])}")
    print(f"  Summary: {fw.get('summary', '')}")
    print()

    commands = brief.get("commands", [])
    if commands:
        print("Commands:")
        for c in commands[:10]:
            print(f"  [{c['kind']}] {c['command']} — {c.get('description', '')}")
        print()

    entries = brief.get("entry_points", [])
    if entries:
        print("Entry points:")
        for e in entries:
            print(f"  {e['path']} ({e['type']})")
        print()

    start = brief.get("start_here", [])
    if start:
        print("Start here (top files to read first):")
        for s in start:
            print(f"  [{s['score']:>3}] {s['path']} — {s['reason']}")
        print()

    infra = brief.get("infra", {})
    print("Infrastructure:")
    print(f"  CI: {infra.get('ci', False)} ({infra.get('ci_count', 0)} file(s))")
    print(f"  Docker: {infra.get('docker', False)}")
    print(f"  .env file: {infra.get('env_file', False)}")
    print(f"  Test framework: {infra.get('test_framework', 'none')}")
    print(f"  Linter: {infra.get('linter', 'none')}")

# Issue #199: deprecated "orient" alias registration removed; this module is now an implementation module imported by the "context" umbrella command.
