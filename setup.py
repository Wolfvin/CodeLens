"""Setup script for CodeLens (issue #54 Phase 1).

pyproject.toml handles most of the build config, but we need a setup.py
to exclude ``scripts/codelens.py`` from top-level py-module discovery.
Without this exclusion, setuptools auto-discovers ``scripts/codelens.py``
as a module named ``codelens`` which shadows the ``codelens/`` package
(both have the same name). The package loads scripts/codelens.py
explicitly via importlib in ``codelens/__init__.py``.
"""

from setuptools import setup

# Collect all top-level .py files in scripts/ EXCEPT codelens.py.
# These become importable top-level modules after pip install.
import os
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")
_py_modules = []
if os.path.isdir(_SCRIPTS_DIR):
    for fname in os.listdir(_SCRIPTS_DIR):
        if fname.endswith(".py") and fname != "codelens.py" and fname != "__init__.py":
            # Strip .py extension to get module name
            _py_modules.append(fname[:-3])

setup(
    py_modules=_py_modules,
)
