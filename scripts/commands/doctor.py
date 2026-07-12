"""CodeLens ``doctor`` command — environment audit + auto-fix (issue #64, Phase 1).

What this command does
-----------------------
``codelens doctor`` audits the local environment for everything CodeLens
needs to run well, and reports a single-pass table of checks. It's the
"why doesn't this work?" debugging tool — for users, for CI, and for
the setup script (``setup.sh`` calls it at the end of install).

Each check produces one of three statuses:

* ``ok``      — the dependency is present and the right version
* ``warning`` — present but old / optional / degraded (exit code 1)
* ``critical``— missing or broken (exit code 2)

``--fix`` runs ``pip install --user`` for any missing Python deps
(safe — pip is the only side effect). ``--verbose`` adds detail like
resolved versions and install paths. ``--format json`` switches the
output to a machine-readable schema for CI pipelines.

Why not just use ``pip check``?
-------------------------------
``pip check`` only verifies dependency coherence — it doesn't know
that CodeLens needs six specific tree-sitter grammars, that
``.codelens/`` must be writable, or that the user's Python is too old.
``doctor`` is purpose-built for CodeLens's actual deployment surface.

What is deliberately NOT checked in Phase 1
-------------------------------------------
* Network reachability of PyPI / OSV.dev (Phase 2+ — slow, flaky in CI)
* MCP server JSON-RPC health (separate concern, lives in MCP tooling)
* Disk space (OS-level concern; doctor is about CodeLens deps)
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from commands import register_command

# ─── Constants ─────────────────────────────────────────────────

# Minimum Python version CodeLens supports (per pyproject.toml).
_MIN_PYTHON = (3, 8)

# The six grammars setup.sh installs. Kept in sync with setup.sh —
# if setup.sh adds a grammar, this list MUST be updated too.
_EXPECTED_GRAMMARS = (
    "tree_sitter_html",
    "tree_sitter_css",
    "tree_sitter_javascript",
    "tree_sitter_typescript",
    "tree_sitter_rust",
    "tree_sitter_python",
)

# Optional Python deps. Missing these is a warning, not critical.
_OPTIONAL_DEPS: Tuple[Tuple[str, str], ...] = (
    # (import_name, pip_install_name)
    ("yaml", "PyYAML"),
    ("watchdog", "watchdog"),
)

# Required Python deps. Missing these is critical.
_REQUIRED_DEPS: Tuple[Tuple[str, str], ...] = (
    ("tree_sitter", "tree-sitter"),
)

# CLI binaries that CodeLens shells out to (optional except git).
_EXPECTED_BINARIES = ("git",)

# Status codes returned by ``execute`` and propagated via the
# ``exit_code`` field. The CLI dispatcher in ``codelens.py`` reads
# ``exit_code`` from the result dict and propagates it to ``sys.exit``.
EXIT_OK = 0
EXIT_WARNING = 1
EXIT_CRITICAL = 2


# ─── Individual checks ─────────────────────────────────────────


def _check_python_version() -> Dict[str, Any]:
    """Verify Python >= 3.8."""
    major, minor = sys.version_info.major, sys.version_info.minor
    current = (major, minor)
    version_str = f"{major}.{minor}.{sys.version_info.micro}"
    if current >= _MIN_PYTHON:
        return {
            "name": "python",
            "status": "ok",
            "found": version_str,
            "required": f">= {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}",
            "detail": sys.version.split()[0],
        }
    return {
        "name": "python",
        "status": "critical",
        "found": version_str,
        "required": f">= {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}",
        "detail": "Python is too old. Install Python 3.8 or newer.",
        "fixable": False,
    }


def _check_import(name: str, pip_name: str, critical: bool) -> Dict[str, Any]:
    """Check that a Python module is importable."""
    try:
        mod = __import__(name)
        version = getattr(mod, "__version__", None) or getattr(mod, "VERSION", None) or "unknown"
        return {
            "name": f"python.module.{name}",
            "status": "ok",
            "found": version,
            "required": "present",
            "detail": f"importable from {getattr(mod, '__file__', '<built-in>')}",
            "pip_name": pip_name,
            "fixable": True,
        }
    except ImportError as exc:
        return {
            "name": f"python.module.{name}",
            "status": "critical" if critical else "warning",
            "found": None,
            "required": "present",
            "detail": f"ImportError: {exc}",
            "pip_name": pip_name,
            "fixable": True,
        }


def _check_grammars() -> Dict[str, Any]:
    """Check that all 6 expected tree-sitter grammars are importable."""
    missing: List[str] = []
    found: Dict[str, str] = {}
    for mod_name in _EXPECTED_GRAMMARS:
        try:
            mod = __import__(mod_name)
            # tree-sitter grammar packages expose a `language()` function
            # or a `LANGUAGE` attribute. Just importing is enough for
            # the doctor check — actual loading is tested by grammar_loader.
            found[mod_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            missing.append(mod_name)

    if not missing:
        return {
            "name": "tree_sitter.grammars",
            "status": "ok",
            "found": f"{len(found)}/{len(_EXPECTED_GRAMMARS)} grammars",
            "required": "all 6 grammars (html, css, js, ts, rust, python)",
            "detail": found,
            "pip_names": [g.replace("_", "-") for g in _EXPECTED_GRAMMARS],
            "fixable": True,
        }
    return {
        "name": "tree_sitter.grammars",
        "status": "critical",
        "found": f"{len(found)}/{len(_EXPECTED_GRAMMARS)} grammars",
        "required": "all 6 grammars (html, css, js, ts, rust, python)",
        "detail": {"missing": missing, "found": found},
        "pip_names": [g.replace("_", "-") for g in missing],
        "fixable": True,
    }


def _check_binary(name: str) -> Dict[str, Any]:
    """Check that a CLI binary is on PATH."""
    path = shutil.which(name)
    if path:
        return {
            "name": f"binary.{name}",
            "status": "ok",
            "found": path,
            "required": "on PATH",
            "detail": f"resolved to {path}",
            "fixable": False,  # We don't auto-install system binaries.
        }
    return {
        "name": f"binary.{name}",
        "status": "warning",
        "found": None,
        "required": "on PATH",
        "detail": f"{name} not found on PATH",
        "fixable": False,
    }


def _check_sqlite() -> Dict[str, Any]:
    """Check that the stdlib sqlite3 module works (compiles + opens :memory:)."""
    try:
        import sqlite3  # noqa: F401 — import side effect is the check
        conn = sqlite3.connect(":memory:")
        ver = sqlite3.sqlite_version
        conn.close()
        return {
            "name": "python.module.sqlite3",
            "status": "ok",
            "found": ver,
            "required": "present (stdlib)",
            "detail": f"sqlite3 module works, SQLite library v{ver}",
            "fixable": False,
        }
    except Exception as exc:
        return {
            "name": "python.module.sqlite3",
            "status": "critical",
            "found": None,
            "required": "present (stdlib)",
            "detail": f"sqlite3 broken: {exc}",
            "fixable": False,
        }


def _check_urllib() -> Dict[str, Any]:
    """Check that urllib can be imported (used by vuln-scan / upgrade)."""
    try:
        import urllib.request  # noqa: F401
        return {
            "name": "python.module.urllib",
            "status": "ok",
            "found": "stdlib",
            "required": "present (stdlib)",
            "detail": "urllib.request importable",
            "fixable": False,
        }
    except Exception as exc:
        return {
            "name": "python.module.urllib",
            "status": "critical",
            "found": None,
            "required": "present (stdlib)",
            "detail": f"urllib broken: {exc}",
            "fixable": False,
        }


def _check_codelens_writable(workspace: str) -> Dict[str, Any]:
    """Check that ``<workspace>/.codelens/`` is writable (or creatable)."""
    if not workspace:
        return {
            "name": "workspace.codelens_writable",
            "status": "warning",
            "found": None,
            "required": "writable .codelens/ dir",
            "detail": "no workspace provided (run from a project root, or pass --workspace)",
            "fixable": False,
        }
    codelens_dir = os.path.join(workspace, ".codelens")
    try:
        os.makedirs(codelens_dir, exist_ok=True)
        # Try a write+delete to confirm we actually have write perms,
        # not just makedirs success (which can succeed on read-only
        # dirs if the dir already exists).
        probe = os.path.join(codelens_dir, ".doctor_write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return {
            "name": "workspace.codelens_writable",
            "status": "ok",
            "found": codelens_dir,
            "required": "writable .codelens/ dir",
            "detail": f"writable: {codelens_dir}",
            "fixable": False,
        }
    except (OSError, PermissionError) as exc:
        return {
            "name": "workspace.codelens_writable",
            "status": "critical",
            "found": codelens_dir,
            "required": "writable .codelens/ dir",
            "detail": f"not writable: {exc}",
            "fixable": False,
        }


def _check_worktree_mismatch(workspace: str) -> Dict[str, Any]:
    """Detect git worktree ↔ CodeLens index mismatch (issue #66 Phase 4).

    A mismatch happens when the user runs CodeLens inside a git
    worktree that does not have its own ``.codelens/`` index, so
    CodeLens silently walks up and loads the main checkout's index —
    which was built from a *different* branch. Every subsequent
    ``query`` / ``trace`` / ``dataflow`` answer is then grounded in
    the wrong file set.

    This check is a ``warning`` (not ``critical``) because the
    workspace is still usable — answers are merely stale, not
    crashes. The user can fix it by running ``codelens init -i`` in
    the worktree.

    Doctor is the natural place to surface this: it's the "why is
    CodeLens behaving weirdly?" debugging command, and "I'm in a
    worktree" is one of the most common answers to that question.
    """
    if not workspace:
        return {
            "name": "workspace.worktree_index_mismatch",
            "status": "ok",
            "found": "no workspace",
            "required": "workspace not in a worktree, or worktree has own .codelens/",
            "detail": "no workspace provided — run from a project root, or pass --workspace",
            "fixable": False,
        }
    try:
        # Import locally so a failure to import the sync subpackage
        # (e.g., due to a packaging regression) doesn't take down the
        # entire doctor run. Doctor must always produce a report.
        from sync.worktree import detect_worktree_index_mismatch, format_worktree_warning

        mismatch = detect_worktree_index_mismatch(workspace)
    except Exception as exc:
        # Detection failure must never break doctor — downgrade to ok
        # with a clear note in the detail field.
        return {
            "name": "workspace.worktree_index_mismatch",
            "status": "ok",
            "found": "detection skipped",
            "required": "workspace not in a worktree, or worktree has own .codelens/",
            "detail": f"worktree detection unavailable: {exc}",
            "fixable": False,
        }

    if not mismatch.get("mismatch"):
        return {
            "name": "workspace.worktree_index_mismatch",
            "status": "ok",
            "found": mismatch.get("reason", "unknown"),
            "required": "workspace not in a worktree, or worktree has own .codelens/",
            "detail": (
                f"worktree_root={mismatch.get('worktree_root')} "
                f"index_root={mismatch.get('index_root')}"
            ),
            "fixable": False,
        }

    # Mismatch detected — surface the full warning so users can see
    # all three paths (worktree / main / index) at a glance.
    return {
        "name": "workspace.worktree_index_mismatch",
        "status": "warning",
        "found": mismatch.get("reason"),
        "required": "worktree should have its own .codelens/ index",
        "detail": format_worktree_warning(mismatch),
        "fixable": False,
    }


def _check_latest_version() -> Dict[str, Any]:
    """Compare installed CodeLens version to the latest GitHub release.

    Network check — failures (offline, rate-limited) are downgraded to
    ``warning`` rather than ``critical`` so CI runs without network
    access don't fail doctor.
    """
    try:
        from utils import CODELENS_VERSION
    except ImportError:
        CODELENS_VERSION = "unknown"

    try:
        import urllib.request
        import json as _json
        # GitHub API requires a User-Agent header or it 403s.
        req = urllib.request.Request(
            "https://api.github.com/repos/Wolfvin/CodeLens/releases/latest",
            headers={"User-Agent": "codelens-doctor", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        latest = (data.get("tag_name") or "").lstrip("v")
        if not latest:
            return {
                "name": "codelens.latest_version",
                "status": "warning",
                "found": CODELENS_VERSION,
                "required": "able to fetch latest release",
                "detail": "GitHub API returned no tag_name field",
                "fixable": False,
            }
        if CODELENS_VERSION == "unknown":
            status = "warning"
        elif _version_tuple(CODELENS_VERSION) >= _version_tuple(latest):
            status = "ok"
        else:
            status = "warning"
        return {
            "name": "codelens.latest_version",
            "status": status,
            "found": CODELENS_VERSION,
            "required": f"latest is {latest}",
            "detail": (
                f"installed={CODELENS_VERSION}, latest={latest}"
                if status == "warning"
                else f"installed={CODELENS_VERSION} (up to date)"
            ),
            "fixable": False,
        }
    except Exception as exc:
        # Network failures are warnings, not critical — doctor must
        # still pass in air-gapped CI.
        return {
            "name": "codelens.latest_version",
            "status": "warning",
            "found": CODELENS_VERSION,
            "required": "able to fetch latest release",
            "detail": f"could not reach GitHub API: {exc}",
            "fixable": False,
        }


def _version_tuple(v: str) -> Tuple[int, ...]:
    """Best-effort parse of a semver-ish string into a comparison tuple."""
    parts: List[int] = []
    for chunk in v.split("."):
        # Strip any pre-release suffix like "1.2.3rc1" → 1.2.3
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        try:
            parts.append(int(num) if num else 0)
        except ValueError:
            parts.append(0)
    return tuple(parts)


# ─── Aggregation ───────────────────────────────────────────────


def _run_all_checks(workspace: str) -> List[Dict[str, Any]]:
    """Run every check in deterministic order, return list of results."""
    checks: List[Dict[str, Any]] = []
    checks.append(_check_python_version())
    checks.append(_check_import("tree_sitter", "tree-sitter", critical=True))
    checks.append(_check_grammars())
    for mod_name, pip_name in _OPTIONAL_DEPS:
        checks.append(_check_import(mod_name, pip_name, critical=False))
    checks.append(_check_sqlite())
    checks.append(_check_urllib())
    for bin_name in _EXPECTED_BINARIES:
        checks.append(_check_binary(bin_name))
    # Worktree mismatch MUST run before _check_codelens_writable — the
    # writable check creates ``.codelens/`` as a side effect of probing
    # write permissions, which would mask the mismatch (the worktree
    # would suddenly appear to have its own index). Running mismatch
    # first gives the user an honest picture of the pre-doctor state.
    checks.append(_check_worktree_mismatch(workspace))
    checks.append(_check_codelens_writable(workspace))
    checks.append(_check_latest_version())
    return checks


def _aggregate_status(checks: List[Dict[str, Any]]) -> Tuple[str, int]:
    """Return (overall_status, exit_code) from a list of check results."""
    has_critical = any(c["status"] == "critical" for c in checks)
    has_warning = any(c["status"] == "warning" for c in checks)
    if has_critical:
        return "critical", EXIT_CRITICAL
    if has_warning:
        return "warning", EXIT_WARNING
    return "ok", EXIT_OK


def _apply_fixes(checks: List[Dict[str, Any]], verbose: bool) -> List[Dict[str, Any]]:
    """Run ``pip install --user`` for every fixable check that's not ok.

    Returns a list of fix outcomes — one per attempted fix. Each
    outcome records whether the pip install succeeded, so doctor can
    report what was actually changed.
    """
    outcomes: List[Dict[str, Any]] = []
    pip_names: List[str] = []
    for c in checks:
        if c.get("fixable") and c["status"] in ("critical", "warning"):
            names = c.get("pip_names") or ([c["pip_name"]] if c.get("pip_name") else [])
            for n in names:
                if n and n not in pip_names:
                    pip_names.append(n)

    if not pip_names:
        return [{"action": "noop", "reason": "no fixable checks", "packages": []}]

    # One pip install invocation for all missing packages — faster
    # than per-package and gives a single dependency-resolver pass.
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--quiet"] + pip_names
    if verbose:
        # Surface pip's own output in verbose mode.
        cmd = [sys.executable, "-m", "pip", "install", "--user"] + pip_names
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # pip can be slow on cold caches
        )
        outcomes.append({
            "action": "pip_install",
            "packages": pip_names,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
            "success": proc.returncode == 0,
        })
    except (subprocess.SubprocessError, OSError) as exc:
        outcomes.append({
            "action": "pip_install",
            "packages": pip_names,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
            "success": False,
        })
    return outcomes


# ─── Output formatting ─────────────────────────────────────────


def _format_text(checks: List[Dict[str, Any]], verbose: bool) -> str:
    """Human-readable table output. ASCII-only so it pipes cleanly."""
    # Symbols: keep ASCII so the output is grep-friendly and works on
    # Windows terminals that don't render Unicode box-drawing.
    symbol = {"ok": "[OK]  ", "warning": "[WARN]", "critical": "[FAIL]"}
    lines: List[str] = []
    lines.append("CodeLens doctor — environment audit")
    lines.append("=" * 60)
    for c in checks:
        sym = symbol.get(c["status"], "[?]   ")
        lines.append(f"{sym} {c['name']:<32}  {c.get('found', '')}")
        if verbose and c.get("detail"):
            detail = c["detail"]
            if isinstance(detail, dict):
                # Pretty-print dict details (e.g., grammar versions)
                for k, v in detail.items():
                    lines.append(f"        {k}: {v}")
            else:
                lines.append(f"        {detail}")
    lines.append("=" * 60)
    overall, _ = _aggregate_status(checks)
    lines.append(f"Overall: {overall.upper()}")
    return "\n".join(lines)


# ─── CLI plumbing ──────────────────────────────────────────────


def add_args(parser):
    """Register doctor-specific arguments.

    ``workspace`` is an optional positional — if omitted, the CLI
    dispatcher auto-detects from cwd (same pattern as ``scan``,
    ``query``, etc.). doctor uses it to check ``.codelens/``
    writability.

    Issue #195: ``--check`` dispatches to absorbed sub-commands
    (env-check, lsp-status). Without --check, runs the legacy doctor audit.
    """
    parser.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to workspace root (auto-detected if omitted)",
    )
    parser.add_argument(
        "--check",
        default=None,
        help="Issue #195: comma-separated sub-analyses. "
             "Choices: doctor, env-check, lsp-status. Default: doctor.",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        default=False,
        help="doctor: auto-install missing Python deps via 'pip install --user'",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="doctor: show resolved versions and install paths for every check",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown", "ai", "sarif", "compact", "graphml"],
        default="text",
        help="doctor: output format (default: text). Any non-'text' value "
             "(json/markdown/ai/sarif/compact/graphml) is handled by the "
             "shared top-level formatter, same as every other umbrella "
             "command (issue: doctor previously only accepted "
             "text/json, rejecting --format compact with 'invalid choice').",
    )
    # env-check passthrough
    parser.add_argument(
        "--var",
        dest="var_name",
        default=None,
        help="env-check: filter to a specific environment variable name",
    )
    # The global --format flag from codelens.py also works; we honor
    # whichever the user set. The local one wins if both are present.


# Issue #195: sub-command dispatch table for the doctor umbrella.
_DOCTOR_SUBCOMMANDS = {
    "doctor": None,  # handled inline
    "env-check": "commands.env_check",
    "lsp-status": "commands.lsp_status",  # kept as utility module
}


def _dispatch_subcommands(args, workspace, check_arg):
    """Dispatch to one or more absorbed sub-commands per --check."""
    import importlib as _il
    parts = [c.strip() for c in check_arg.split(",") if c.strip()]
    invalid = [p for p in parts if p not in _DOCTOR_SUBCOMMANDS]
    if invalid:
        import sys as _sys
        print(
            f"[CodeLens] doctor: unknown --check category '{','.join(invalid)}'. "
            f"Valid: {', '.join(_DOCTOR_SUBCOMMANDS.keys())}",
            file=_sys.stderr,
        )
        _sys.exit(1)
    if not parts:
        parts = ["doctor"]

    results = []
    checks_failed = 0
    for check_name in parts:
        try:
            if check_name == "doctor":
                # Run the legacy doctor logic. Force JSON output so the
                # umbrella can merge it into the unified result shape.
                args.format = "json"
                sub_result = _run_legacy_doctor(args, workspace)
            else:
                mod = _il.import_module(_DOCTOR_SUBCOMMANDS[check_name])
                sub_args = _build_subnamespace(args, check_name)
                sub_result = mod.execute(sub_args, workspace)
            if not isinstance(sub_result, dict):
                sub_result = {"status": "ok", "result": sub_result}
            sub_result["_check"] = check_name
            results.append(sub_result)
        except Exception as exc:
            checks_failed += 1
            results.append({
                "_check": check_name,
                "s": "error",
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            import sys as _sys
            print(f"[CodeLens] doctor: --check {check_name} failed: {exc}",
                  file=_sys.stderr)

    return {
        "s": "ok" if checks_failed == 0 else "partial",
        "st": {"checks_requested": len(parts), "checks_failed": checks_failed},
        "r": results,
    }


def _build_subnamespace(base_args, check_name):
    """Build a synthetic namespace for the dispatched sub-command."""
    import argparse as _ap
    ns = _ap.Namespace()
    for attr in ("format", "top", "max_tokens", "lite", "deep", "db_path",
                 "diff_base", "diff_scope", "disable_suppression",
                 "codelens_ignore_pattern"):
        setattr(ns, attr, getattr(base_args, attr, None))
    ns.workspace = getattr(base_args, "workspace", None)
    if check_name == "env-check":
        ns.var_name = getattr(base_args, "var_name", None)
    return ns


def _run_legacy_doctor(args, workspace):
    """Run the original doctor.execute logic (issue #195: absorbed)."""
    verbose = bool(getattr(args, "verbose", False))
    do_fix = bool(getattr(args, "fix", False))
    fmt = getattr(args, "format", None)
    if fmt not in ("text", "json"):
        fmt = "text"
    checks = _run_all_checks(workspace)
    fixes = []
    if do_fix:
        fixes = _apply_fixes(checks, verbose)
        checks = _run_all_checks(workspace)
    overall, exit_code = _aggregate_status(checks)
    summary = {
        "ok": sum(1 for c in checks if c["status"] == "ok"),
        "warning": sum(1 for c in checks if c["status"] == "warning"),
        "critical": sum(1 for c in checks if c["status"] == "critical"),
        "total": len(checks),
    }
    result = {
        "status": overall,
        "exit_code": exit_code,
        "checks": checks,
        "fixes": fixes,
        "summary": summary,
        "platform": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "executable": sys.executable,
        },
        "workspace": workspace,
    }
    return result


def execute(args, workspace):
    """Run the environment audit, optionally apply fixes, return result dict.

    Issue #195: when --check is set, dispatch to absorbed sub-commands
    (env-check, lsp-status) and merge results into the umbrella shape.

    The result always includes:

    * ``status``         — "ok" | "warning" | "critical"
    * ``exit_code``      — 0 | 1 | 2 (consumed by the CLI dispatcher)
    * ``checks``         — list of per-check result dicts
    * ``fixes``          — list of fix outcomes (empty if --fix not passed)
    * ``summary``        — counts by status
    * ``platform``       — OS / arch / Python interpreter info
    """
    # Issue #195: dispatch to absorbed sub-commands when --check is set.
    check_arg = getattr(args, "check", None)
    if check_arg:
        return _dispatch_subcommands(args, workspace, check_arg)

    verbose = bool(getattr(args, "verbose", False))
    do_fix = bool(getattr(args, "fix", False))

    # The local --format argument overrides the global one.
    fmt = getattr(args, "format", None)
    if fmt not in ("text", "json", "markdown", "ai", "sarif", "compact", "graphml"):
        # Fall back to text only when nothing valid was set at all.
        fmt = "text"

    checks = _run_all_checks(workspace)
    fixes: List[Dict[str, Any]] = []
    if do_fix:
        fixes = _apply_fixes(checks, verbose)
        # Re-run checks after fix to reflect the new state. The
        # reported exit code reflects the post-fix state — that's
        # what CI cares about.
        checks = _run_all_checks(workspace)

    overall, exit_code = _aggregate_status(checks)

    summary = {
        "ok": sum(1 for c in checks if c["status"] == "ok"),
        "warning": sum(1 for c in checks if c["status"] == "warning"),
        "critical": sum(1 for c in checks if c["status"] == "critical"),
        "total": len(checks),
    }

    result: Dict[str, Any] = {
        "status": overall,
        "exit_code": exit_code,
        "checks": checks,
        "fixes": fixes,
        "summary": summary,
        "platform": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "executable": sys.executable,
        },
        "workspace": workspace,
    }

    if fmt != "text":
        # Any non-"text" format (json/markdown/ai/sarif/compact/graphml) is
        # a plain dict return — let the shared top-level formatter in
        # codelens.py handle the transformation, same as every other
        # umbrella command. Previously only "json" took this path; every
        # other global format silently fell through to the text branch
        # below (or, before this fix, argparse rejected them outright with
        # "invalid choice" since the local --format choices list didn't
        # include them).
        try:
            args.format = fmt
        except Exception:
            pass
    else:
        # Print the human-readable table to stdout here so the
        # dispatcher's JSON formatter doesn't double-encode it.
        # The CLI dispatcher checks for ``_doctor_printed_text`` to
        # know it should skip its own formatting.
        print(_format_text(checks, verbose))
        if fixes:
            print("\nFixes applied:")
            for f in fixes:
                if f.get("action") == "noop":
                    print(f"  (no fixable checks — {f.get('reason', 'noop')})")
                else:
                    status = "OK" if f.get("success") else "FAILED"
                    pkgs = ", ".join(f.get("packages", []))
                    print(f"  [{status}] pip install --user {pkgs}")
                    if verbose and f.get("stderr"):
                        print(f"        stderr: {f['stderr'][:300]}")
        result["_doctor_printed_text"] = True

    return result


register_command(
    "doctor",
    "Audit environment for CodeLens dependencies (--fix to auto-install)",
    add_args,
    execute,
)
