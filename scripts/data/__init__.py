"""CodeLens built-in data assets (shipped with the package).

This module exists so that setuptools treats ``scripts/data/`` as a
package and includes its non-Python assets (currently
``default-codelensignore``) in the wheel via ``include-package-data``.

Runtime code resolves the data directory via filesystem path
(``os.path.dirname(os.path.abspath(__file__))``), so importing this
module is never required at runtime — it is a packaging marker.
"""
