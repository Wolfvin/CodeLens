"""CodeLens — AI-native code intelligence CLI + MCP server.

This is the top-level package for the ``codelens`` distribution. It
provides a thin entry-point wrapper that delegates to the legacy
``scripts/codelens.py`` implementation so that ``pip install codelens``
exposes a ``codelens`` console script.

The actual implementation lives under ``scripts/`` (which is also the
``codelens`` import root via ``pyproject.toml``'s ``packages.find``).
This ``codelens/`` package only contains the ``__main__`` shim and
re-exports the ``main`` function for programmatic use.

Issue #54 Phase 1 — Python package + PyPI distribution.
"""

from __future__ import annotations

import os
import sys
import warnings
from typing import Optional, List


__version__ = "8.2.0"

# Path to the bundled scripts/ directory (legacy implementation).
# When installed as a package, scripts/ is shipped inside the codelens
# distribution and we add it to sys.path so the legacy imports keep
# working. When running from a source checkout, scripts/ is already
# accessible relative to the repo root.
_SCRIPTS_DIR: Optional[str] = None


def _resolve_scripts_dir() -> str:
    """Locate the bundled ``scripts/`` directory.

    Search order:
    1. ``<package_dir>/../scripts`` — source checkout (repo root)
    2. ``<package_dir>/scripts`` — installed package (scripts bundled inside)
    3. Fall back to the legacy ``python3 scripts/codelens.py`` path

    Returns the absolute path to the scripts directory.
    """
    global _SCRIPTS_DIR
    if _SCRIPTS_DIR is not None:
        return _SCRIPTS_DIR

    here = os.path.dirname(os.path.abspath(__file__))

    # 1. Source checkout: <repo_root>/scripts/
    candidate = os.path.join(here, "..", "scripts")
    if os.path.isfile(os.path.join(candidate, "codelens.py")):
        _SCRIPTS_DIR = os.path.abspath(candidate)
        return _SCRIPTS_DIR

    # 2. Installed package: <site-packages>/codelens/scripts/
    candidate = os.path.join(here, "scripts")
    if os.path.isfile(os.path.join(candidate, "codelens.py")):
        _SCRIPTS_DIR = os.path.abspath(candidate)
        return _SCRIPTS_DIR

    # 3. Fall back: try importlib.resources or just leave it to the
    # caller's sys.path (legacy ``python3 scripts/codelens.py`` mode).
    _SCRIPTS_DIR = ""
    return _SCRIPTS_DIR


def _ensure_scripts_on_path() -> str:
    """Add the bundled scripts/ directory to sys.path if not present.

    Returns the scripts directory path (empty string if not found).
    """
    scripts_dir = _resolve_scripts_dir()
    if scripts_dir and scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    return scripts_dir


def main(argv: Optional[List[str]] = None) -> int:
    """Run the CodeLens CLI.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success, 1 on error).
    """
    _ensure_scripts_on_path()

    # Import the legacy entry point. The scripts/codelens.py module uses
    # sys.path-based imports relative to scripts/, so it must be on the
    # path (handled above).
    try:
        # ``import codelens`` would be ambiguous here (this package is
        # also named codelens), so import the module by file path.
        import importlib.util
        scripts_dir = _resolve_scripts_dir()
        if not scripts_dir:
            print(
                "[codelens] ERROR: could not locate the scripts/ directory. "
                "If you installed from source, run from the repo root or "
                "install with 'pip install .'.",
                file=sys.stderr,
            )
            return 1

        codelens_py = os.path.join(scripts_dir, "codelens.py")
        spec = importlib.util.spec_from_file_location(
            "_codelens_cli", codelens_py
        )
        if spec is None or spec.loader is None:
            print(
                f"[codelens] ERROR: could not load {codelens_py}",
                file=sys.stderr,
            )
            return 1
        module = importlib.util.module_from_spec(spec)
        # The module needs to be in sys.modules for its relative imports
        # (e.g. ``from commands import ...``) to resolve correctly when
        # scripts/ is on sys.path.
        sys.modules["_codelens_cli"] = module
        spec.loader.exec_module(module)

        # Temporarily replace sys.argv so the legacy main() picks up the
        # caller's arguments.
        old_argv = sys.argv
        try:
            sys.argv = ["codelens"] + (list(argv) if argv is not None else sys.argv[1:])
            module.main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0
        finally:
            sys.argv = old_argv
    except Exception as e:
        print(f"[codelens] ERROR: {e}", file=sys.stderr)
        return 1


__all__ = ["main", "__version__"]
