"""
Grammar Loader for CodeLens
Loads tree-sitter grammars for all supported languages.
Handles lazy loading, caching, and API compatibility across tree-sitter versions.
"""

import threading
from typing import Dict, Optional

try:
    from tree_sitter import Language, Parser
except ImportError:
    Language = None
    Parser = None


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
        """Load a specific grammar. Returns None if the package is not installed."""
        if Language is None:
            return None
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
        """List all available language grammars."""
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


# Convenience function
def get_grammar_loader() -> GrammarLoader:
    return GrammarLoader()
