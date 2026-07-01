"""CodeLens built-in plugin manifests and rule packs.

This module exists so that setuptools treats ``scripts/plugins/`` as a
package (and its sub-packages ``plugins.owasp_top10`` /
``plugins.compliance`` as packages) so that the ``plugin.yaml`` and
``rules/*.yaml`` files are included in the wheel via
``include-package-data``.

Runtime code resolves the plugins directory via filesystem path
(``os.path.dirname(os.path.abspath(__file__))``), so importing this
module is never required at runtime — it is a packaging marker.
"""
