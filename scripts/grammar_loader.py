"""
Grammar Loader for CodeLens
Loads tree-sitter grammars for all supported languages.
Handles lazy loading, caching, and API compatibility across tree-sitter versions.

Issue #18: the hardcoded language list is now backed by the universal
grammar loader (``scripts/universal_grammar_loader.py``). The GrammarLoader
class delegates to ``universal_grammar_loader.load_grammar()`` so any of
the 158+ languages in the tree-sitter ecosystem can be loaded as long as
the corresponding PyPI package is importable (or auto-installed when
``CODELENS_AUTO_INSTALL_GRAMMARS=1`` is set).
"""

import threading
from typing import Dict, Optional

try:
    from tree_sitter import Language, Parser
except ImportError:
    Language = None
    Parser = None

# Issue #18: universal loader backs the hardcoded language list.
try:
    from universal_grammar_loader import load_grammar as _universal_load_grammar
    from universal_grammar_loader import available_languages as _universal_available
    from universal_grammar_loader import supported_languages as _universal_supported
except ImportError:  # pragma: no cover — module lives in scripts/
    _universal_load_grammar = None
    _universal_available = None
    _universal_supported = None


class GrammarLoader:
    """Lazy-loads and caches tree-sitter grammars. Thread-safe singleton."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._languages = {}
                cls._instance._parsers = {}
                cls._instance._initialized = True
            return cls._instance

    def get_language(self, lang_name: str) -> Optional['Language']:
        """Get a tree-sitter language by name. Returns None if not available."""
        if lang_name in self._languages:
            return self._languages[lang_name]

        lang = self._load_grammar(lang_name)
        if lang:
            self._languages[lang_name] = lang
        return lang

    def get_parser(self, lang_name: str) -> Optional['Parser']:
        """Get a tree-sitter parser for a language.

        Handles API differences between tree-sitter versions:
        - v0.21.x: Parser(lang) constructor
        - v0.22+: parser.language = lang setter
        """
        if lang_name in self._parsers:
            return self._parsers[lang_name]

        lang = self.get_language(lang_name)
        if not lang or Parser is None:
            return None

        try:
            # Try modern API first (tree-sitter >= 0.22)
            parser = Parser()
            parser.language = lang
        except (TypeError, AttributeError):
            try:
                # Fallback to legacy API (tree-sitter < 0.22)
                parser = Parser(lang)
            except (TypeError, Exception):
                return None

        self._parsers[lang_name] = parser
        return parser

    def _load_grammar(self, lang_name: str) -> Optional['Language']:
        """Load a grammar by name.

        Delegates to the universal grammar loader (issue #18) so any of the
        158+ languages in the tree-sitter ecosystem can be loaded as long
        as the corresponding PyPI package is importable. Returns ``None``
        silently when the grammar is unavailable — callers must treat a
        missing grammar as "skip this file", never as a fatal error.
        """
        if Language is None:
            return None
        # Issue #18: prefer the universal loader when available.
        if _universal_load_grammar is not None:
            return _universal_load_grammar(lang_name)
        # Fallback to the legacy hardcoded list when the universal
        # loader module is unavailable (e.g. older installs).
        try:
            if lang_name == 'html':
                import tree_sitter_html as ts
                return Language(ts.language())
            elif lang_name == 'css':
                import tree_sitter_css as ts
                return Language(ts.language())
            elif lang_name == 'javascript':
                import tree_sitter_javascript as ts
                return Language(ts.language())
            elif lang_name == 'typescript':
                import tree_sitter_typescript as ts
                return Language(ts.language_typescript())
            elif lang_name == 'tsx':
                import tree_sitter_typescript as ts
                return Language(ts.language_tsx())
            elif lang_name == 'rust':
                import tree_sitter_rust as ts
                return Language(ts.language())
            elif lang_name == 'python':
                import tree_sitter_python as ts
                return Language(ts.language())
            else:
                return None
        except ImportError:
            return None

    @staticmethod
    def available_languages() -> list:
        """List all available language grammars.

        Issue #18: when the universal loader is present, return its probe
        result (which covers all 158+ ecosystem languages). Otherwise fall
        back to the legacy hardcoded list.
        """
        if _universal_available is not None:
            return list(_universal_available())
        available = []
        grammars = {
            'html': 'tree_sitter_html',
            'css': 'tree_sitter_css',
            'javascript': 'tree_sitter_javascript',
            'typescript': 'tree_sitter_typescript',
            'tsx': 'tree_sitter_typescript',
            'rust': 'tree_sitter_rust',
            'python': 'tree_sitter_python',
        }
        for name, module in grammars.items():
            try:
                __import__(module)
                available.append(name)
            except ImportError:
                pass
        return available

    @staticmethod
    def supported_languages() -> list:
        """List all languages CodeLens can detect (issue #18).

        This is the superset of all languages for which an extension,
        basename, or shebang mapping exists — whether or not a grammar
        is currently installed.
        """
        if _universal_supported is not None:
            return list(_universal_supported())
        return [
            'html', 'css', 'javascript', 'typescript', 'tsx',
            'rust', 'python',
        ]


# Convenience function
def get_grammar_loader() -> GrammarLoader:
    return GrammarLoader()
