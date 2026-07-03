# @WHO:   scripts/languages/__init__.py
# @WHAT:  Language config package — YAML node-type registry for tree-sitter parsers (issue #43)
# @PART:  languages
# @ENTRY: -
#
# Issue #43 — Approach 2 (YAML node-type registry) stepping stone.
#
# This package externalises the hardcoded tree-sitter node-type lookups
# (``find_nodes_by_type(root, "function_definition")``) to a YAML config.
# The Python walker stays, but reads node types from config instead of
# hardcoding them. Adding a language = adding a few lines of YAML.
#
# This is the low-risk stepping stone recommended by issue #43 before
# any .scm migration. It does NOT change existing parser behaviour —
# it adds a new config-driven path (``find_nodes_by_category``) that
# future parsers and the eventual .scm engine can use.

"""Language config package — YAML node-type registry.

Public entry points::

    from languages import get_node_types, get_language_config

    types = get_node_types("python", "function_def")
    # → frozenset({"function_definition"})

The registry maps ``language → category → [tree-sitter node types]``.
Categories are semantic (``function_def``, ``call``, ``import``, etc.)
so the same category name works across languages — this is the design
property that the future .scm engine (issue #43 Phase B) will exploit.
"""

from .loader import (  # noqa: F401
    get_node_types,
    get_language_config,
    get_supported_languages,
    NodeTypeError,
)

__all__ = [
    "get_node_types",
    "get_language_config",
    "get_supported_languages",
    "NodeTypeError",
]
