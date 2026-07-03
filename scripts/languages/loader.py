# @WHO:   scripts/languages/loader.py
# @WHAT:  YAML node-type registry loader — cached access to language node-type config (issue #43)
# @PART:  languages
# @ENTRY: get_node_types(), get_language_config()
#
# @FLOW:    NODE_TYPE_LOOKUP
# @CALLS:   yaml.safe_load() -> dict, internal _load_registry() -> cached dict
# @MUTATES: none (pure read; cache is module-level but effectively immutable after first load)
#
# Issue #43 — Approach 2 (YAML node-type registry) loader.
#
# Design:
# - The YAML file is loaded once on first access and cached in a module-level
#   dict. Subsequent calls are O(1) dict lookups — no file I/O.
# - The cache is intentionally NOT thread-safe with a lock. The worst case
#   under concurrent first-access is that two threads both load the YAML
#   (idempotent — same data) and one overwrites the other's cache entry
#   (same data again). No corruption, no race condition that matters.
# - ``get_node_types`` returns a ``frozenset`` (not a list) so callers can
#   do ``if node.type in types`` without worrying about duplicates or order.
# - Unknown language or category raises ``NodeTypeError`` — fail loud, not
#   silent. Silent fallback to an empty set would hide config typos and
#   produce empty parse results that are hard to debug.

"""YAML node-type registry loader.

Public API::

    from languages import get_node_types

    types = get_node_types("python", "function_def")
    # → frozenset({"function_definition"})

    types = get_node_types("rust", "call")
    # → frozenset({"call_expression"})

    config = get_language_config("python")
    # → {"function_def": [...], "class_def": [...], ...}

    langs = get_supported_languages()
    # → ["css", "html", "javascript", "python", "rust", "tsx", "typescript"]
"""

from __future__ import annotations

import os
from typing import Any, Dict, FrozenSet, List, Optional

# Lazy import — PyYAML is an optional dep in minimal installs. The import
# error surfaces as a clear ``NodeTypeError`` on first use rather than at
# module import time, so ``from languages import ...`` never crashes the
# CLI even when PyYAML is missing.
try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


class NodeTypeError(KeyError):
    """Raised when a language or category is not in the registry.

    Subclasses ``KeyError`` so ``except KeyError`` still catches it, but
    the explicit subclass lets callers distinguish "config typo" from
    "genuine missing key" if they need to.
    """


# ─── Module-level cache ────────────────────────────────────────────────────

# Cached registry: ``{language: {category: [node_types]}}``.
# ``None`` means "not yet loaded". After first load, always a dict.
_registry: Optional[Dict[str, Dict[str, List[str]]]] = None

# Cached frozensets per (language, category) pair. ``get_node_types``
# returns these directly so callers don't recreate frozensets on every
# call. Keyed by ``f"{language}:{category}"``.
_frozenset_cache: Dict[str, FrozenSet[str]] = {}

# Path to the YAML file, resolved relative to this module.
_YAML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_types.yaml")


def _load_registry() -> Dict[str, Dict[str, List[str]]]:
    """Load the YAML registry from disk (cached after first call).

    Returns the full registry dict. On first call, reads the YAML file;
    subsequent calls return the cached dict.

    Raises:
        NodeTypeError: If PyYAML is not installed or the YAML file
            cannot be read/parsed. The error message includes the
            file path and the underlying cause for debugging.
    """
    global _registry
    if _registry is not None:
        return _registry

    if not _YAML_AVAILABLE:
        raise NodeTypeError(
            "[languages.loader] PyYAML not installed — cannot load node-type registry. "
            "Install with: pip install pyyaml"
        )

    try:
        with open(_YAML_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except OSError as exc:
        raise NodeTypeError(
            f"[languages.loader] cannot read node-type registry at {_YAML_PATH}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise NodeTypeError(
            f"[languages.loader] YAML parse error in {_YAML_PATH}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise NodeTypeError(
            f"[languages.loader] expected top-level dict in {_YAML_PATH}, got {type(data).__name__}"
        )

    # Validate structure: each language must map to a dict of category → list.
    validated: Dict[str, Dict[str, List[str]]] = {}
    for lang, categories in data.items():
        if not isinstance(categories, dict):
            raise NodeTypeError(
                f"[languages.loader] language {lang!r} must map to a dict of "
                f"category → [node_types], got {type(categories).__name__}"
            )
        validated[lang] = {}
        for cat, types in categories.items():
            if not isinstance(types, list):
                raise NodeTypeError(
                    f"[languages.loader] language {lang!r} category {cat!r} must be a "
                    f"list of node-type strings, got {type(types).__name__}"
                )
            for t in types:
                if not isinstance(t, str):
                    raise NodeTypeError(
                        f"[languages.loader] language {lang!r} category {cat!r} contains "
                        f"non-string node type: {t!r}"
                    )
            validated[lang][cat] = types

    _registry = validated
    return _registry


def _invalidate_cache() -> None:
    """Drop the cached registry and frozenset cache. Used by tests."""
    global _registry
    _registry = None
    _frozenset_cache.clear()


# ─── Public API ────────────────────────────────────────────────────────────


def get_node_types(language: str, category: str) -> FrozenSet[str]:
    """Return the set of tree-sitter node types for ``language`` + ``category``.

    Args:
        language: Language key in the YAML (e.g. ``"python"``, ``"rust"``,
            ``"javascript"``, ``"typescript"``, ``"tsx"``, ``"css"``,
            ``"html"``). Case-sensitive — must match the YAML key exactly.
        category: Semantic category (e.g. ``"function_def"``, ``"call"``,
            ``"import"``, ``"class_def"``). Case-sensitive.

    Returns:
        ``frozenset`` of node-type strings. The set is frozen so callers
        can't accidentally mutate the cached data.

    Raises:
        NodeTypeError: If ``language`` or ``category`` is not in the
            registry. Fail loud — a config typo should surface immediately,
            not silently produce empty parse results.

    Example::

        >>> get_node_types("python", "function_def")
        frozenset({'function_definition'})
        >>> get_node_types("rust", "call")
        frozenset({'call_expression'})
        >>> get_node_types("javascript", "call")
        frozenset({'call_expression', 'new_expression'})
    """
    registry = _load_registry()
    cache_key = f"{language}:{category}"
    cached = _frozenset_cache.get(cache_key)
    if cached is not None:
        return cached

    lang_config = registry.get(language)
    if lang_config is None:
        raise NodeTypeError(
            f"[languages.loader] language {language!r} not in registry. "
            f"Supported: {sorted(registry.keys())}"
        )
    types = lang_config.get(category)
    if types is None:
        raise NodeTypeError(
            f"[languages.loader] category {category!r} not defined for language "
            f"{language!r}. Available categories: {sorted(lang_config.keys())}"
        )
    result = frozenset(types)
    _frozenset_cache[cache_key] = result
    return result


def get_language_config(language: str) -> Dict[str, List[str]]:
    """Return the full category → node-types mapping for one language.

    Returns a shallow copy so callers can't mutate the cached registry.

    Raises:
        NodeTypeError: If ``language`` is not in the registry.
    """
    registry = _load_registry()
    lang_config = registry.get(language)
    if lang_config is None:
        raise NodeTypeError(
            f"[languages.loader] language {language!r} not in registry. "
            f"Supported: {sorted(registry.keys())}"
        )
    # Shallow copy — the lists inside are also copied so callers can't
    # mutate the cached lists either.
    return {cat: list(types) for cat, types in lang_config.items()}


def get_supported_languages() -> List[str]:
    """Return a sorted list of all languages in the registry."""
    registry = _load_registry()
    return sorted(registry.keys())


__all__ = [
    "get_node_types",
    "get_language_config",
    "get_supported_languages",
    "NodeTypeError",
    "_invalidate_cache",
]
