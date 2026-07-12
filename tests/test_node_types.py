"""Tests for the YAML node-type registry (issue #43 — Approach 2 stepping stone).

Scope:

* :mod:`languages.loader` — :func:`get_node_types`, :func:`get_language_config`,
  :func:`get_supported_languages`, :class:`NodeTypeError`.
* :mod:`languages.node_types` (YAML) — validates that all 7 tree-sitter
  languages are present with sensible categories.
* :class:`base_parser.BaseParser.find_nodes_by_category` — verifies the
  config-driven lookup path (without needing tree-sitter installed; the
  test mocks the tree walk).

All tests are network-free and filesystem-light — they read the bundled
``node_types.yaml`` directly. No tree-sitter installation is required.
"""

from __future__ import annotations

import os
import sys
from typing import Any, List
from unittest import mock

import pytest

# ─── Path setup (mirror other tests) ───────────────────────────────────────

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from languages import (  # noqa: E402
    get_node_types,
    get_language_config,
    get_supported_languages,
    NodeTypeError,
)
from languages import loader as loader_mod  # noqa: E402


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_cache():
    """Drop the loader's module-level cache before and after each test.

    Without this, a test that mocks ``yaml.safe_load`` would be ignored
    because the cache already holds the real data from a prior test.
    """
    loader_mod._invalidate_cache()
    yield
    loader_mod._invalidate_cache()


# ─── get_node_types ────────────────────────────────────────────────────────


class TestGetNodeTypes:
    """``get_node_types(language, category)`` returns the right frozenset."""

    def test_python_function_def(self):
        result = get_node_types("python", "function_def")
        assert result == frozenset({"function_definition"})

    def test_python_call(self):
        result = get_node_types("python", "call")
        assert result == frozenset({"call"})

    def test_rust_call(self):
        result = get_node_types("rust", "call")
        assert result == frozenset({"call_expression"})

    def test_javascript_call_has_multiple_types(self):
        """JS calls include both ``call_expression`` and ``new_expression``."""
        result = get_node_types("javascript", "call")
        assert "call_expression" in result
        assert "new_expression" in result
        assert len(result) == 2

    def test_rust_const_has_multiple_types(self):
        """Rust const category includes both ``const_item`` and ``static_item``."""
        result = get_node_types("rust", "const")
        assert "const_item" in result
        assert "static_item" in result

    def test_returns_frozenset(self):
        """Result must be a frozenset so callers can't mutate the cache."""
        result = get_node_types("python", "function_def")
        assert isinstance(result, frozenset)

    def test_unknown_language_raises(self):
        with pytest.raises(NodeTypeError, match="not in registry"):
            get_node_types("cobol", "function_def")

    def test_unknown_category_raises(self):
        with pytest.raises(NodeTypeError, match="not defined for language"):
            get_node_types("python", "nonexistent_category")

    def test_error_message_lists_supported_languages(self):
        """The error message should list supported languages for discoverability."""
        try:
            get_node_types("cobol", "function_def")
        except NodeTypeError as e:
            msg = str(e)
            assert "python" in msg.lower()
            assert "rust" in msg.lower()

    def test_error_message_lists_available_categories(self):
        """The error message should list available categories for the language."""
        try:
            get_node_types("python", "nonexistent")
        except NodeTypeError as e:
            msg = str(e)
            assert "function_def" in msg
            assert "class_def" in msg


# ─── get_language_config ──────────────────────────────────────────────────


class TestGetLanguageConfig:
    """``get_language_config(language)`` returns the full category mapping."""

    def test_python_config_has_expected_categories(self):
        config = get_language_config("python")
        assert "function_def" in config
        assert "class_def" in config
        assert "call" in config
        assert "import" in config

    def test_rust_config_has_expected_categories(self):
        config = get_language_config("rust")
        for cat in ("function_def", "struct", "enum", "trait", "impl",
                     "call", "import", "macro"):
            assert cat in config, f"rust config missing category: {cat}"

    def test_config_values_are_lists(self):
        config = get_language_config("python")
        for cat, types in config.items():
            assert isinstance(types, list), f"{cat} value is not a list"
            assert all(isinstance(t, str) for t in types), \
                f"{cat} contains non-string type"

    def test_config_is_a_copy(self):
        """Modifying the returned config must not affect the cached registry."""
        config1 = get_language_config("python")
        config1["function_def"].append("FAKE_TYPE")
        config1["injected"] = ["bad"]

        config2 = get_language_config("python")
        assert "FAKE_TYPE" not in config2["function_def"]
        assert "injected" not in config2

    def test_unknown_language_raises(self):
        with pytest.raises(NodeTypeError):
            get_language_config("cobol")


# ─── get_supported_languages ──────────────────────────────────────────────


class TestGetSupportedLanguages:
    """``get_supported_languages()`` lists all 13 tree-sitter languages."""

    # Issue #198 added go/java/php/ruby/c/cpp (6 languages) alongside the
    # original 7 (python/rust/javascript/typescript/tsx/css/html) -> 13 total.
    EXPECTED_LANGUAGES = {
        "python", "rust", "javascript", "typescript", "tsx", "css", "html",
        "go", "java", "php", "ruby", "c", "cpp",
    }

    def test_all_expected_languages_present(self):
        langs = set(get_supported_languages())
        missing = self.EXPECTED_LANGUAGES - langs
        assert not missing, f"missing languages in registry: {missing}"

    def test_returns_sorted_list(self):
        langs = get_supported_languages()
        assert langs == sorted(langs)

    def test_no_extra_languages_beyond_expected(self):
        """The registry should only contain the 7 tree-sitter languages.

        If a new language is added, this test will flag it so the test
        suite stays in sync with the config.
        """
        langs = set(get_supported_languages())
        extra = langs - self.EXPECTED_LANGUAGES
        # Allow extra languages but warn — this is a soft assertion.
        # If you add a language, update EXPECTED_LANGUAGES.
        if extra:
            pytest.fail(
                f"Unexpected languages in registry: {extra}. "
                f"Update EXPECTED_LANGUAGES in this test."
            )


# ─── YAML config validity ─────────────────────────────────────────────────


class TestYamlConfigValidity:
    """Validate the structure and content of node_types.yaml."""

    def test_every_language_has_function_def_or_equivalent(self):
        """Every language that has functions should have a function_def category.

        CSS and HTML don't have functions, so they're excluded.
        """
        langs_with_functions = {"python", "rust", "javascript", "typescript", "tsx"}
        for lang in langs_with_functions:
            config = get_language_config(lang)
            assert "function_def" in config, \
                f"{lang} should have a function_def category"

    def test_every_language_has_call_or_equivalent(self):
        """Languages with function calls should have a call category."""
        langs_with_calls = {"python", "rust", "javascript", "typescript", "tsx"}
        for lang in langs_with_calls:
            config = get_language_config(lang)
            assert "call" in config, \
                f"{lang} should have a call category"

    def test_no_empty_category_lists(self):
        """No category should have an empty node-type list."""
        for lang in get_supported_languages():
            config = get_language_config(lang)
            for cat, types in config.items():
                assert len(types) > 0, \
                    f"{lang}.{cat} has an empty node-type list"

    def test_no_duplicate_node_types_within_category(self):
        """No category should list the same node type twice."""
        for lang in get_supported_languages():
            config = get_language_config(lang)
            for cat, types in config.items():
                assert len(types) == len(set(types)), \
                    f"{lang}.{cat} has duplicate node types: {types}"

    def test_all_node_types_are_nonempty_strings(self):
        """Every node type must be a non-empty string."""
        for lang in get_supported_languages():
            config = get_language_config(lang)
            for cat, types in config.items():
                for t in types:
                    assert isinstance(t, str) and len(t) > 0, \
                        f"{lang}.{cat} has invalid node type: {t!r}"


# ─── Cache behaviour ───────────────────────────────────────────────────────


class TestCacheBehaviour:
    """The module-level cache should prevent repeated file reads."""

    def test_cache_returns_same_object_for_same_language(self):
        """Two calls for the same language should return the same cached frozenset.

        This is an implementation detail, but it verifies that the cache
        is working (no repeated YAML parsing).
        """
        result1 = get_node_types("python", "function_def")
        result2 = get_node_types("python", "function_def")
        assert result1 is result2

    def test_invalidate_cache_forces_reload(self):
        """``_invalidate_cache`` forces the next call to re-read the YAML."""
        result1 = get_node_types("python", "function_def")
        loader_mod._invalidate_cache()
        result2 = get_node_types("python", "function_def")
        # Same value, but the cache was rebuilt — can't assert identity
        # because frozenset() creates a new object. Just verify equality.
        assert result1 == result2


# ─── Error handling: missing PyYAML ────────────────────────────────────────


class TestMissingPyYAML:
    """When PyYAML is not installed, the loader should fail clearly."""

    def test_missing_yaml_raises_nodetypeerror(self, monkeypatch):
        """Simulate PyYAML not being installed."""
        monkeypatch.setattr(loader_mod, "_YAML_AVAILABLE", False)
        loader_mod._invalidate_cache()
        with pytest.raises(NodeTypeError, match="PyYAML not installed"):
            get_node_types("python", "function_def")


# ─── BaseParser.find_nodes_by_category integration ────────────────────────


# tree_sitter is an optional dependency. The BaseParser tests below need
# it because base_parser.py imports from tree_sitter at module level.
# Tests for the loader itself (above) don't need tree_sitter and always run.
_tree_sitter_available = True
try:
    import tree_sitter  # noqa: F401
except ImportError:
    _tree_sitter_available = False

_BASEPARSER_SKIP_REASON = "tree_sitter not installed — BaseParser tests require it"


@pytest.mark.skipif(not _tree_sitter_available, reason=_BASEPARSER_SKIP_REASON)
class TestBaseParserFindByCategory:
    """Verify ``BaseParser.find_nodes_by_category`` wires the YAML lookup
    into the existing ``find_nodes_by_types`` tree walk.

    These tests mock ``find_nodes_by_types`` so they don't need a real
    tree-sitter AST — they verify the wiring, not the walk.
    """

    def test_find_nodes_by_category_calls_find_nodes_by_types(self):
        """``find_nodes_by_category`` should delegate to ``find_nodes_by_types``
        with the YAML-resolved node-type set."""
        # We can't construct a real BaseParser without a tree-sitter Language,
        # so we create a bare instance via __new__ and mock the methods.
        from base_parser import BaseParser

        parser = BaseParser.__new__(BaseParser)

        # Mock find_nodes_by_types to capture what it's called with.
        captured_types = None

        def mock_find(root, node_types):
            nonlocal captured_types
            captured_types = node_types
            return ["mock_node"]

        parser.find_nodes_by_types = mock_find

        result = parser.find_nodes_by_category(
            root="fake_root",
            language="python",
            category="function_def",
        )

        assert result == ["mock_node"]
        assert captured_types == frozenset({"function_definition"})

    def test_find_nodes_by_category_multi_type(self):
        """Categories with multiple node types pass the full set through."""
        from base_parser import BaseParser

        parser = BaseParser.__new__(BaseParser)
        captured_types = None

        def mock_find(root, node_types):
            nonlocal captured_types
            captured_types = node_types
            return []

        parser.find_nodes_by_types = mock_find

        parser.find_nodes_by_category(
            root="fake_root",
            language="javascript",
            category="call",
        )

        assert captured_types == frozenset({"call_expression", "new_expression"})

    def test_find_nodes_by_category_unknown_language_propagates(self):
        """An unknown language should raise NodeTypeError, not silently return []."""
        from base_parser import BaseParser

        parser = BaseParser.__new__(BaseParser)
        parser.find_nodes_by_types = lambda root, types: []

        with pytest.raises(NodeTypeError):
            parser.find_nodes_by_category(
                root="fake_root",
                language="cobol",
                category="function_def",
            )

    def test_find_nodes_by_category_unknown_category_propagates(self):
        """An unknown category should raise NodeTypeError, not silently return []."""
        from base_parser import BaseParser

        parser = BaseParser.__new__(BaseParser)
        parser.find_nodes_by_types = lambda root, types: []

        with pytest.raises(NodeTypeError):
            parser.find_nodes_by_category(
                root="fake_root",
                language="python",
                category="nonexistent",
            )


# ─── YAML file location ────────────────────────────────────────────────────


class TestYamlFileLocation:
    """Verify the loader finds the YAML file relative to itself."""

    def test_yaml_file_exists(self):
        """The YAML file should exist next to the loader module."""
        yaml_path = loader_mod._YAML_PATH
        assert os.path.exists(yaml_path), f"node_types.yaml not found at {yaml_path}"

    def test_yaml_path_is_absolute(self):
        """The path should be absolute so it works regardless of CWD."""
        assert os.path.isabs(loader_mod._YAML_PATH)
