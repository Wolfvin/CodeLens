"""CodeLens built-in YAML rule files (shipped with the package).

This module exists so that setuptools treats ``scripts/rules/`` as a
package and includes its non-Python assets (``python_security.yaml``,
``javascript_security.yaml``) in the wheel via
``include-package-data``.

Runtime code resolves the rules directory via filesystem path
(``os.path.dirname(os.path.abspath(__file__))``), so importing this
module is never required at runtime — it is a packaging marker.
"""
