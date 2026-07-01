"""
Smoke tests for packaging metadata (issue #54 Phase 1).

These tests guard the Phase 1 distribution scope:

  - ``[project.scripts] codelens = "codelens:main"`` entry point must be
    declared so that ``pip install codelens`` exposes a ``codelens``
    console script.
  - ``[tool.setuptools] package-dir = {"" = "scripts"}`` must map the
    source root so that top-level .py modules in ``scripts/`` install
    as importable top-level modules (``import codelens`` /
    ``import utils`` / ``import <engine>`` continue to work).
  - ``[tool.setuptools.py-modules]`` must list **every** top-level
    .py file in ``scripts/`` — a new engine added without updating
    this list would silently drop out of the wheel.
  - ``[tool.setuptools.packages.find]`` must list every subpackage of
    ``scripts/`` (including the new ``data`` / ``rules`` / ``plugins``
    markers added in this PR so that the bundled YAML rule packs and
    plugin manifests are included in the wheel).
  - Non-Python data files (``default-codelensignore``, the security
    rule YAMLs, the plugin manifests + rule pack YAMLs) must be
    present in the wheel — these are loaded at runtime via filesystem
    paths relative to ``__file__``.

These tests do NOT install the package (that's the CI workflow's job
in ``.github/workflows/publish-pypi.yml``). They just refuse to let
the packaging metadata regress.
"""

from __future__ import annotations

import os
import sys
import zipfile
import subprocess
from pathlib import Path

import pytest

# ─── Path constants ────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Subpackages that must be listed under [tool.setuptools.packages.find]
# so their files (including non-Python data) make it into the wheel.
# `plugins.*` is included implicitly via the glob.
EXPECTED_SUBPACKAGES = {
    "commands",
    "formatters",
    "parsers",
    "security",
    "memories",
    "sca_parsers",
    "mcp_hooks",
    "data",
    "rules",
    "plugins",
}

# Non-Python data files that the runtime resolves via
# ``os.path.dirname(os.path.abspath(__file__))``. If any of these
# silently disappear from the wheel, ``codelens taint``, ``plugin list``,
# and the builtin ignore patterns all silently fall back to empty.
REQUIRED_DATA_FILES = [
    "data/default-codelensignore",
    "rules/python_security.yaml",
    "rules/javascript_security.yaml",
    "plugins/owasp_top10/plugin.yaml",
    "plugins/owasp_top10/rules/owasp_top10.yaml",
    "plugins/compliance/plugin.yaml",
    "plugins/compliance/rules/hipaa.yaml",
    "plugins/compliance/rules/pci_dss.yaml",
]


# ─── TOML loader (3.11+ stdlib, 3.8-3.10 fallback) ────────────────────────

def _load_pyproject() -> dict:
    """Parse ``pyproject.toml`` using stdlib ``tomllib`` when available.

    Falls back to a minimal regex parse for Python 3.8-3.10 where
    ``tomllib`` is not in the stdlib. We don't want to add ``tomli`` as
    a test-only dependency for the same reason cited by
    ``tests/test_version_consistency.py``.
    """
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        # Minimal fallback: split on top-level [section] headers and
        # parse only the keys we care about. Sufficient for the tests
        # in this file because the keys we assert on are simple
        # strings / arrays.
        text = PYPROJECT_PATH.read_text(encoding="utf-8")
        return _toml_regex_fallback(text)
    with PYPROJECT_PATH.open("rb") as fh:
        return tomllib.load(fh)


def _toml_regex_fallback(text: str) -> dict:
    """Very small TOML reader for the subset this test file queries.

    This is NOT a general TOML parser — only the keys we assert on are
    handled. If pyproject.toml grows more complex structures that the
    tests need to assert on, ``tomli`` should be added as a test dep
    instead of extending this.
    """
    import re
    sections: dict = {"": {}}
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^\[([^\]]+)\]$", stripped)
        if m:
            current = m.group(1)
            sections.setdefault(current, {})
            continue
        # key = value
        m = re.match(r"^([A-Za-z0-9_-]+)\s*=\s*(.*)$", stripped)
        if not m:
            continue
        key, raw = m.group(1), m.group(2)
        sections.setdefault(current, {})[key] = _toml_value(raw)
    # Flatten dotted section names into nested dicts to mimic tomllib.
    out: dict = {}
    for sec, vals in sections.items():
        if not sec:
            out.update({k: v for k, v in vals.items() if not isinstance(v, dict)})
            continue
        parts = sec.split(".")
        node = out
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node.setdefault(parts[-1], {}).update(vals)
    return out


def _toml_value(raw: str):
    import re
    raw = raw.strip().rstrip(",")
    if raw.startswith("[") and raw.endswith("]"):
        # array — extract string items only (sufficient for our use case)
        return [s for s in re.findall(r'"([^"]+)"', raw)]
    if raw.startswith("{") and raw.endswith("}"):
        # inline table — return as dict of string→string
        out = {}
        for k, v in re.findall(r'([A-Za-z0-9_-]+)\s*=\s*"([^"]+)"', raw):
            out[k] = v
        return out
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


# ─── Tests ────────────────────────────────────────────────────────────────

class TestPyprojectScripts:
    """``[project.scripts]`` must declare the ``codelens`` entry point."""

    def test_entry_point_declared(self) -> None:
        cfg = _load_pyproject()
        scripts = cfg.get("project", {}).get("scripts", {})
        assert "codelens" in scripts, (
            "pyproject.toml [project.scripts] must declare `codelens = ...` "
            "so `pip install codelens` exposes a console script. "
            f"Found: {scripts!r}"
        )

    def test_entry_point_target_is_codelens_main(self) -> None:
        cfg = _load_pyproject()
        target = cfg.get("project", {}).get("scripts", {}).get("codelens")
        assert target == "codelens:main", (
            "Entry point must be `codelens:main` — pointing to the existing "
            "`main()` function in `scripts/codelens.py`. The `package-dir = "
            "{'' = 'scripts'}` mapping installs `scripts/codelens.py` as a "
            f"top-level module, so `codelens:main` resolves correctly. Got: {target!r}"
        )

    def test_main_callable_in_scripts(self) -> None:
        """`codelens.main` must be importable + callable from source tree.

        Sanity-checks that the entry point target actually exists. The
        test injects ``scripts/`` into ``sys.path`` using the same
        convention as the rest of the test suite.
        """
        sys.path.insert(0, str(SCRIPTS_DIR))
        try:
            import codelens as codelens_mod  # type: ignore[import-not-found]
            assert callable(getattr(codelens_mod, "main", None)), (
                "scripts/codelens.py must define a top-level `main()` callable "
                "for the `[project.scripts] codelens = codelens:main` entry "
                "point to work."
            )
        finally:
            sys.path.pop(0)


class TestPyprojectLayout:
    """``[tool.setuptools]`` must map ``scripts/`` to the source root."""

    def test_package_dir_maps_scripts_to_root(self) -> None:
        cfg = _load_pyproject()
        pkg_dir = cfg.get("tool", {}).get("setuptools", {}).get("package-dir", {})
        assert pkg_dir.get("") == "scripts", (
            "[tool.setuptools.package-dir] must map `'' = 'scripts'` so that "
            "top-level .py files in scripts/ install as top-level modules "
            f"and subdirs install as top-level packages. Got: {pkg_dir!r}"
        )

    def test_include_package_data_enabled(self) -> None:
        cfg = _load_pyproject()
        flag = cfg.get("tool", {}).get("setuptools", {}).get("include-package-data")
        assert flag is True, (
            "[tool.setuptools.include-package-data] must be true so that the "
            "non-Python data files (rule YAMLs, plugin manifests, builtin "
            "ignore file) declared in MANIFEST.in are bundled into the wheel."
        )

    def test_py_modules_list_matches_scripts_dir(self) -> None:
        """Every top-level .py file in scripts/ must appear in py-modules.

        This is the guard rail called out in the pyproject.toml comment:
        when a new top-level engine or helper script is added to
        ``scripts/`` without updating the explicit ``py-modules`` list,
        the file silently drops out of the wheel and the engine fails
        to import at runtime from an installed install.
        """
        cfg = _load_pyproject()
        listed = set(cfg.get("tool", {}).get("setuptools", {}).get("py-modules", []))

        actual = {
            p.stem
            for p in SCRIPTS_DIR.glob("*.py")
            if p.is_file()
        }

        missing = actual - listed
        extra = listed - actual

        assert not missing, (
            f"{len(missing)} top-level .py file(s) in scripts/ not declared in "
            f"[tool.setuptools.py-modules]: {sorted(missing)}. Add them to the "
            f"list — otherwise `pip install codelens` silently drops them from "
            f"the wheel."
        )
        assert not extra, (
            f"{len(extra)} entry/entries in [tool.setuptools.py-modules] do "
            f"not correspond to any .py file in scripts/: {sorted(extra)}. "
            f"Stale entries should be removed."
        )

    def test_subpackages_listed(self) -> None:
        """Every required subpackage must appear in packages.find.include."""
        cfg = _load_pyproject()
        find_cfg = cfg.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        listed = set(find_cfg.get("include", []))

        missing = EXPECTED_SUBPACKAGES - listed
        assert not missing, (
            f"{len(missing)} required subpackage(s) missing from "
            f"[tool.setuptools.packages.find].include: {sorted(missing)}. "
            f"Without them, the subpackage's files (including data files) "
            f"are not bundled into the wheel."
        )

    def test_plugins_glob_included(self) -> None:
        """`plugins.*` glob must be present so plugin subdirs are packages."""
        cfg = _load_pyproject()
        find_cfg = cfg.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        listed = find_cfg.get("include", [])
        assert "plugins.*" in listed, (
            "`plugins.*` glob must be in packages.find.include so that "
            "plugins/owasp_top10 and plugins/compliance are discovered as "
            "packages and their plugin.yaml + rule YAMLs are bundled. "
            f"Got: {listed!r}"
        )


class TestManifestIn:
    """``MANIFEST.in`` must list the non-Python data globs."""

    def test_manifest_in_exists(self) -> None:
        assert (REPO_ROOT / "MANIFEST.in").is_file(), (
            "MANIFEST.in must exist at the repo root to declare the non-Python "
            "data files (rule YAMLs, plugin manifests, builtin ignore file) "
            "that `include-package-data = true` should bundle into the wheel."
        )

    @pytest.mark.parametrize("required_glob", [
        "recursive-include scripts/data",
        "recursive-include scripts/rules",
        "recursive-include scripts/plugins",
    ])
    def test_manifest_in_lists_data_globs(self, required_glob: str) -> None:
        text = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert required_glob in text, (
            f"MANIFEST.in must contain `{required_glob}` so that the "
            f"corresponding data files are bundled into the wheel. Without "
            f"it, the rule packs / plugin manifests / builtin ignore file "
            f"would silently drop from `pip install codelens`."
        )


class TestInitPyMarkers:
    """Data subdirs must have ``__init__.py`` to be discovered as packages."""

    @pytest.mark.parametrize("subpkg", [
        "data",
        "rules",
        "plugins",
        "plugins/owasp_top10",
        "plugins/compliance",
    ])
    def test_init_py_present(self, subpkg: str) -> None:
        init_path = SCRIPTS_DIR / subpkg / "__init__.py"
        assert init_path.is_file(), (
            f"{init_path} must exist so that setuptools treats "
            f"`scripts/{subpkg}` as a package and bundles its non-Python "
            f"contents (YAML rule packs, plugin manifests, builtin ignore "
            f"file) into the wheel via `include-package-data = true`. "
            f"This is a packaging marker only — runtime code resolves the "
            f"directory via filesystem paths, never via import."
        )


class TestWheelContents:
    """Build the wheel on the fly and inspect its contents.

    This is the highest-signal test in the file: it actually invokes
    ``python -m build --wheel`` and asserts that the resulting wheel
    contains the entry point, every required data file, and every
    top-level module.

    Skipped when ``build`` is not importable (e.g. minimal CI envs
    without the ``dev`` extra installed) to avoid forcing a hard dep
    on the build toolchain in every test run.
    """

    @pytest.fixture(scope="class")
    def built_wheel(self) -> Path:
        # Skip cleanly if `build` is not available.
        pytest.importorskip("build", reason="`build` package not installed")
        import tempfile
        import shutil

        outdir = Path(tempfile.mkdtemp(prefix="codelens-wheel-"))
        try:
            subprocess.run(
                [sys.executable, "-m", "build", "--wheel", "--outdir", str(outdir)],
                cwd=str(REPO_ROOT),
                check=True,
                capture_output=True,
                timeout=180,
            )
        except subprocess.CalledProcessError as e:
            pytest.fail(
                "python -m build --wheel failed:\n"
                f"stdout: {e.stdout.decode()}\n"
                f"stderr: {e.stderr.decode()}"
            )

        wheels = list(outdir.glob("codelens-*.whl"))
        assert len(wheels) == 1, f"Expected exactly 1 wheel, got: {wheels}"
        yield wheels[0]
        shutil.rmtree(outdir, ignore_errors=True)

    def test_entry_point_in_wheel(self, built_wheel: Path) -> None:
        import re
        entry_re = re.compile(r"^codelens\s*=\s*codelens:main\s*$", re.M)
        with zipfile.ZipFile(built_wheel) as z:
            for name in z.namelist():
                if name.endswith("entry_points.txt"):
                    txt = z.read(name).decode("utf-8")
                    assert entry_re.search(txt), (
                        f"entry_points.txt in {built_wheel.name} does not "
                        f"contain `codelens = codelens:main`. Content:\n{txt}"
                    )
                    return
        pytest.fail("entry_points.txt not found in wheel")

    def test_required_data_files_in_wheel(self, built_wheel: Path) -> None:
        with zipfile.ZipFile(built_wheel) as z:
            names = set(z.namelist())
        missing = [f for f in REQUIRED_DATA_FILES if f not in names]
        assert not missing, (
            f"{len(missing)} required data file(s) missing from wheel "
            f"{built_wheel.name}: {missing}. Check MANIFEST.in + the "
            f"`include-package-data` flag in pyproject.toml."
        )

    def test_all_top_level_modules_in_wheel(self, built_wheel: Path) -> None:
        cfg = _load_pyproject()
        py_modules = cfg.get("tool", {}).get("setuptools", {}).get("py-modules", [])
        with zipfile.ZipFile(built_wheel) as z:
            names = set(z.namelist())
        missing = [f"{m}.py" for m in py_modules if f"{m}.py" not in names]
        assert not missing, (
            f"{len(missing)} py-module(s) declared in pyproject.toml but "
            f"missing from wheel {built_wheel.name}: {missing[:5]}... "
            f"(total {len(missing)} missing of {len(py_modules)} declared)"
        )
