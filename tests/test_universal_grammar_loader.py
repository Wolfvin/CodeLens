"""Tests for issue #18 — universal tree-sitter grammar loader.

Verifies:

1. ``detect_language(file_path)`` correctly identifies 50+ file extensions
   including the explicit contract anchors ``.go → go`` and ``.rb → ruby``.
2. ``detect_language()`` handles special basenames (Dockerfile, Makefile,
   Rakefile, mix.exs) and shebang lines.
3. ``load_grammar(language)`` returns a real ``tree_sitter.Language`` when
   the grammar package is installed, and ``None`` gracefully otherwise.
4. ``load_grammar()`` NEVER attempts auto-install unless
   ``CODELENS_AUTO_INSTALL_GRAMMARS=1`` is set.
5. ``load_grammar()`` returns ``None`` (no crash) for unknown languages,
   empty input, and broken modules.
6. Integration with ``scan`` command: unknown extensions are bucketed
   under their detected language name.
"""

import importlib
import os
import subprocess
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from universal_grammar_loader import (  # noqa: E402
    AUTO_INSTALL_ENV,
    EXTENSION_MAP,
    BASENAME_MAP,
    SHEBANG_MAP,
    detect_language,
    load_grammar,
    supported_extensions_count,
    supported_languages,
)
from grammar_loader import GrammarLoader  # noqa: E402


# ─── 1. Extension coverage contract ────────────────────────────


class TestExtensionCoverage:
    """Issue #18 contract: cover at least 50 languages / 50 extensions."""

    REQUIRED_LANGUAGES = {
        # The task explicitly names these.
        "python", "javascript", "typescript", "rust", "go", "java", "c",
        "cpp", "ruby", "php", "swift", "kotlin", "scala", "elixir",
        "haskell", "lua", "sql", "yaml", "toml", "json", "bash",
        "dockerfile", "hcl",  # terraform → hcl
        "html", "css", "scss",
    }

    def test_detects_at_least_50_extensions(self):
        n = supported_extensions_count()
        assert n >= 50, f"expected ≥50 extensions, got {n}"
        # The headline claim is 158+ languages ecosystem support; we ship
        # ≥150 extensions so the loader is genuinely universal.
        assert n >= 150, (
            f"issue #18 targets 158+ ecosystem languages; expected ≥150 "
            f"extensions covered, got {n}"
        )

    def test_detects_at_least_50_languages(self):
        langs = set(supported_languages())
        assert len(langs) >= 50, (
            f"expected ≥50 distinct languages, got {len(langs)}"
        )

    def test_required_languages_all_covered(self):
        langs = set(supported_languages())
        missing = self.REQUIRED_LANGUAGES - langs
        assert not missing, f"missing required languages: {missing}"

    def test_required_anchor_extensions(self):
        """Required anchor extensions all detect to expected language."""
        # Task spec: `.go` → go, `.rb` → ruby
        assert detect_language("foo.go") == "go"
        assert detect_language("foo.rb") == "ruby"
        # Plus the explicit list from the spec body.
        anchors = {
            "main.py": "python",
            "app.js": "javascript",
            "app.ts": "typescript",
            "main.rs": "rust",
            "main.go": "go",
            "Main.java": "java",
            "main.c": "c",
            "main.cpp": "cpp",
            "Gemfile": "ruby",
            "Dockerfile": "dockerfile",
            "Makefile": "make",
            "mix.exs": "elixir",
        }
        for fname, expected in anchors.items():
            got = detect_language(fname)
            assert got == expected, (
                f"detect_language({fname!r}) = {got!r}, expected {expected!r}"
            )

    def test_extension_map_has_no_duplicates(self):
        """All extension values are canonical language names."""
        # All values must be lowercase, non-empty strings.
        for ext, lang in EXTENSION_MAP.items():
            assert ext.startswith("."), f"extension {ext!r} must start with '.'"
            assert ext == ext.lower(), f"extension {ext!r} must be lowercase"
            assert lang and lang == lang.lower(), (
                f"language for {ext!r} must be non-empty lowercase, got {lang!r}"
            )


# ─── 2. detect_language edge cases ─────────────────────────────


class TestDetectLanguage:
    """Edge cases for ``detect_language``."""

    def test_empty_path_returns_none(self):
        assert detect_language("") is None

    def test_none_like_path_returns_none(self):
        # Path with no extension and no recognizable basename.
        assert detect_language("README") is None

    def test_extension_case_insensitive(self):
        assert detect_language("FOO.PY") == "python"
        assert detect_language("Main.GO") == "go"
        assert detect_language("App.RB") == "ruby"

    def test_dotted_filename_no_extension(self):
        # Files like `.bashrc` or `.gitignore` have no real extension.
        # We don't crash; we just return None or a detected language.
        result = detect_language(".bashrc")
        # ``.bashrc`` ends with ``bashrc`` which is not a known extension.
        # Behavior: return None (graceful).
        assert result is None

    def test_path_components_only_basename_used(self):
        # Directories named ``.py`` shouldn't influence detection.
        assert detect_language("/foo/.py/bar.go") == "go"
        assert detect_language("/.rb/x.go") == "go"

    def test_dockerfile_with_prefix(self):
        # Files like ``nginx.Dockerfile`` should still detect as dockerfile.
        assert detect_language("nginx.Dockerfile") == "dockerfile"
        assert detect_language("api.Containerfile") == "dockerfile"

    def test_makefile_lowercase(self):
        # Basename matching is case-insensitive.
        assert detect_language("makefile") == "make"
        assert detect_language("MAKEFILE") == "make"

    def test_special_basenames(self):
        assert detect_language("Rakefile") == "ruby"
        assert detect_language("Gemfile") == "ruby"
        assert detect_language("Capfile") == "ruby"
        assert detect_language("Vagrantfile") == "ruby"

    def test_tsx_vs_tsx_extension(self):
        assert detect_language("Component.tsx") == "tsx"
        assert detect_language("module.ts") == "typescript"

    def test_header_files(self):
        assert detect_language("foo.h") == "c"
        assert detect_language("foo.hpp") == "cpp"
        assert detect_language("foo.hxx") == "cpp"

    def test_shebang_python(self, tmp_path):
        f = tmp_path / "script"
        f.write_text("#!/usr/bin/env python3\nprint('hi')\n")
        assert detect_language(str(f)) == "python"

    def test_shebang_bash(self, tmp_path):
        f = tmp_path / "script"
        f.write_text("#!/bin/bash\necho hi\n")
        assert detect_language(str(f)) == "bash"

    def test_shebang_ruby(self, tmp_path):
        f = tmp_path / "script"
        f.write_text("#!/usr/bin/env ruby\nputs 'hi'\n")
        assert detect_language(str(f)) == "ruby"

    def test_shebang_node(self, tmp_path):
        f = tmp_path / "script"
        f.write_text("#!/usr/bin/env node\nconsole.log('hi')\n")
        assert detect_language(str(f)) == "javascript"

    def test_shebang_with_version_suffix(self, tmp_path):
        # ``python3.11`` should still detect as ``python``.
        f = tmp_path / "script"
        f.write_text("#!/usr/bin/python3.11\nprint('hi')\n")
        assert detect_language(str(f)) == "python"

    def test_no_shebang_extensionless_file(self, tmp_path):
        f = tmp_path / "binary"
        f.write_bytes(b"\x7fELF\x02\x01\x01\x00")
        assert detect_language(str(f)) is None

    def test_missing_file_falls_back_to_extension(self, tmp_path):
        # Path doesn't exist → extension check still works.
        assert detect_language(str(tmp_path / "ghost.py")) == "python"
        assert detect_language(str(tmp_path / "ghost.go")) == "go"

    def test_sql_yaml_toml_json(self):
        assert detect_language("schema.sql") == "sql"
        assert detect_language("config.yaml") == "yaml"
        assert detect_language("config.yml") == "yaml"
        assert detect_language("pyproject.toml") == "toml"
        assert detect_language("package.json") == "json"
        assert detect_language("tsconfig.jsonc") == "json"

    def test_terraform_hcl(self):
        assert detect_language("main.tf") == "hcl"
        assert detect_language("vars.tfvars") == "hcl"
        assert detect_language("any.hcl") == "hcl"

    def test_scala_sbt(self):
        assert detect_language("build.sbt") == "scala"

    def test_php_blade_not_in_fallback(self):
        assert detect_language("view.php") == "php"


# ─── 3. load_grammar contract ──────────────────────────────────


class TestLoadGrammar:
    """``load_grammar`` is the heart of issue #18."""

    def test_returns_none_for_empty(self):
        assert load_grammar("") is None
        assert load_grammar("   ") is None

    def test_returns_none_for_unknown_language(self):
        # Klingon isn't a real tree-sitter language.
        assert load_grammar("klingon") is None

    def test_returns_none_for_none_input(self):
        # Defensive: callers may pass None.
        assert load_grammar(None) is None  # type: ignore[arg-type]

    def test_loads_python_grammar(self):
        # tree-sitter-python is installed (it's in the dev dependencies).
        lang = load_grammar("python")
        if lang is None:
            pytest.skip("tree-sitter-python not installed in this env")
        # The Language object should expose a name attribute or be truthy.
        assert lang is not None
        # ``Language`` objects from tree-sitter 0.22+ expose ``name``.
        name = getattr(lang, "name", None)
        assert name in (None, "python")  # tolerate either form

    def test_normalizes_language_aliases(self):
        # Hyphens and spaces normalize to underscores.
        # ``c-sharp`` → ``csharp``, ``tree-sitter-c-sharp`` is the package.
        # We only check that normalization doesn't crash and returns None
        # (since c-sharp grammar isn't installed in CI).
        assert load_grammar("CSharp") is None  # case-insensitive normalization
        assert load_grammar("csharp") is None

    def test_never_auto_installs_by_default(self, monkeypatch):
        """Without the env var, ``load_grammar`` MUST NOT call pip."""
        # Ensure the env var is unset.
        monkeypatch.delenv(AUTO_INSTALL_ENV, raising=False)

        calls = []

        def fake_pip_install(package):
            calls.append(package)
            return False

        # Use monkeypatch on the module-level function.
        import universal_grammar_loader as ugl
        monkeypatch.setattr(ugl, "_pip_install", fake_pip_install)

        # Request a language whose grammar isn't installed.
        result = load_grammar("zig")
        assert result is None
        assert calls == [], (
            "load_grammar() must NOT auto-install without "
            f"{AUTO_INSTALL_ENV}=1, but called pip with: {calls}"
        )

    def test_auto_installs_when_env_var_set(self, monkeypatch):
        """With the env var, ``load_grammar`` SHOULD call pip for missing grammars."""
        monkeypatch.setenv(AUTO_INSTALL_ENV, "1")

        calls = []

        def fake_pip_install(package):
            calls.append(package)
            # Pretend install failed so we don't actually try to import.
            return False

        import universal_grammar_loader as ugl
        monkeypatch.setattr(ugl, "_pip_install", fake_pip_install)

        result = load_grammar("zig")
        assert result is None  # install failed → None
        assert calls == ["tree-sitter-zig"], (
            f"expected pip install of tree-sitter-zig, got: {calls}"
        )

    def test_auto_install_truthy_values(self, monkeypatch):
        """Various truthy env-var values enable auto-install."""
        import universal_grammar_loader as ugl

        for val in ("1", "true", "TRUE", "yes", "YES"):
            monkeypatch.setenv(AUTO_INSTALL_ENV, val)
            assert ugl._auto_install_enabled() is True, (
                f"{AUTO_INSTALL_ENV}={val!r} should enable auto-install"
            )

    def test_auto_install_falsy_values(self, monkeypatch):
        """Empty / unset / unknown values disable auto-install."""
        import universal_grammar_loader as ugl

        for val in ("", "0", "no", "false", "random"):
            monkeypatch.setenv(AUTO_INSTALL_ENV, val)
            assert ugl._auto_install_enabled() is False, (
                f"{AUTO_INSTALL_ENV}={val!r} should disable auto-install"
            )

    def test_auto_install_disabled_when_unset(self, monkeypatch):
        monkeypatch.delenv(AUTO_INSTALL_ENV, raising=False)
        import universal_grammar_loader as ugl
        assert ugl._auto_install_enabled() is False

    def test_returns_language_after_successful_install(self, monkeypatch):
        """When pip install succeeds and the import works, return Language."""
        # Use python — the package is already installed so we short-circuit
        # through the import path. We simulate a "fresh install" by:
        # 1. Forcing the env var on.
        # 2. Stubbing ``_try_import`` to first return None, then return
        #    the real tree_sitter_python module.
        # 3. Stubbing ``_pip_install`` to return True.
        monkeypatch.setenv(AUTO_INSTALL_ENV, "1")

        import universal_grammar_loader as ugl

        original_import = ugl._try_import
        call_count = {"n": 0}

        def fake_import(language):
            call_count["n"] += 1
            # First call (before install) returns None.
            if call_count["n"] == 1:
                return None
            # Second call (after install) returns the real module.
            return original_import(language)

        def fake_pip_install(package):
            return True

        monkeypatch.setattr(ugl, "_try_import", fake_import)
        monkeypatch.setattr(ugl, "_pip_install", fake_pip_install)

        lang = load_grammar("python")
        assert lang is not None, "expected Language after successful auto-install"
        assert call_count["n"] == 2, "import must be attempted twice (pre+post install)"

    def test_no_crash_on_broken_module(self, monkeypatch):
        """A grammar module that raises during import shouldn't crash."""
        import universal_grammar_loader as ugl

        def broken_import(language):
            raise RuntimeError("simulated broken wheel")

        monkeypatch.setattr(ugl, "_try_import", broken_import)
        # Should return None, not raise.
        assert load_grammar("python") is None

    def test_no_crash_on_broken_language_pointer(self, monkeypatch):
        """A grammar module whose language() raises shouldn't crash."""
        import universal_grammar_loader as ugl
        import types as _types

        # Build a fake module with a broken language() function.
        fake_module = _types.SimpleNamespace()
        def broken_language():
            raise RuntimeError("grammar corrupted")
        fake_module.language = broken_language

        monkeypatch.setattr(ugl, "_try_import", lambda lang: fake_module)
        assert load_grammar("python") is None


# ─── 4. GrammarLoader integration ──────────────────────────────


class TestGrammarLoaderIntegration:
    """The legacy ``GrammarLoader`` class should delegate to the universal loader."""

    def test_supported_languages_includes_universal_set(self):
        langs = GrammarLoader.supported_languages()
        # The universal loader covers far more than the original 7.
        assert len(langs) >= 50, (
            f"GrammarLoader.supported_languages() should reflect universal "
            f"loader (≥50 languages), got {len(langs)}"
        )
        # Original 7 must still be present.
        for lang in ("python", "javascript", "typescript", "tsx",
                     "rust", "html", "css"):
            assert lang in langs, f"missing legacy language: {lang}"

    def test_available_languages_returns_list(self):
        langs = GrammarLoader.available_languages()
        assert isinstance(langs, list)
        # tree-sitter-python is installed in dev env.
        assert "python" in langs

    def test_get_language_python(self):
        # Clear singleton cache to ensure fresh load.
        GrammarLoader._instance = None
        loader = GrammarLoader()
        lang = loader.get_language("python")
        if lang is None:
            pytest.skip("tree-sitter-python not installed in this env")
        assert lang is not None

    def test_get_language_unknown_returns_none(self):
        GrammarLoader._instance = None
        loader = GrammarLoader()
        assert loader.get_language("klingon") is None

    def test_get_parser_python(self):
        GrammarLoader._instance = None
        loader = GrammarLoader()
        parser = loader.get_parser("python")
        if parser is None:
            pytest.skip("tree-sitter-python not installed in this env")
        # Should be able to parse a simple Python snippet.
        tree = parser.parse(b"def f():\n    return 1\n")
        assert tree.root_node.type == "module"


# ─── 5. scan command integration ───────────────────────────────


class TestScanIntegration:
    """The ``scan`` command should use ``detect_language`` for unknown extensions."""

    def test_unknown_extensions_bucketed_by_language(self, tmp_path):
        """Files with unknown extensions are bucketed under detected language."""
        from commands.scan import discover_files

        # Create files whose extensions ARE in the universal loader but
        # NOT in scan's hardcoded dispatch chain.
        for fname in ("schema.sql", "config.yaml", "pyproject.toml", "main.tf"):
            (tmp_path / fname).write_text("# placeholder\n")

        config = {"ignore_dirs": [], "ignore_exts": []}
        files = discover_files(str(tmp_path), config)

        # Each detected file should land in a bucket named after its language.
        assert "sql" in files and len(files["sql"]) == 1
        assert "yaml" in files and len(files["yaml"]) == 1
        assert "toml" in files and len(files["toml"]) == 1
        assert "hcl" in files and len(files["hcl"]) == 1

    def test_known_extensions_still_use_hardcoded_buckets(self, tmp_path):
        """Files with known extensions keep using the legacy parser buckets."""
        from commands.scan import discover_files

        (tmp_path / "main.go").write_text("package main\n")
        (tmp_path / "app.rb").write_text("puts 'hi'\n")
        (tmp_path / "Dockerfile").write_text("FROM alpine\n")
        config = {"ignore_dirs": [], "ignore_exts": []}
        files = discover_files(str(tmp_path), config)

        # .go and .rb keep their legacy buckets — universal loader is
        # a *fallback*, not a replacement for the curated dispatch.
        assert len(files["go"]) == 1
        assert len(files["ruby"]) == 1
        # Dockerfile is dispatched to the shell bucket by the hardcoded
        # chain (existing behavior, preserved for backward compat).
        assert len(files["shell"]) == 1


# ─── 6. Module-level contracts ─────────────────────────────────


class TestModuleContracts:
    """Sanity checks on the public surface of the module."""

    def test_public_api_exports(self):
        import universal_grammar_loader as ugl
        for name in ("detect_language", "load_grammar",
                     "available_languages", "supported_languages",
                     "supported_extensions_count",
                     "EXTENSION_MAP", "BASENAME_MAP", "SHEBANG_MAP",
                     "AUTO_INSTALL_ENV"):
            assert hasattr(ugl, name), f"missing public symbol: {name}"

    def test_auto_install_env_constant(self):
        assert AUTO_INSTALL_ENV == "CODELENS_AUTO_INSTALL_GRAMMARS"

    def test_shebang_map_covers_common_interpreters(self):
        for interp in ("python", "python3", "ruby", "bash", "node"):
            assert interp in SHEBANG_MAP, (
                f"shebang mapping missing for {interp!r}"
            )

    def test_no_two_extensions_map_to_different_canonical_names_for_same_lang(self):
        """Sanity: extensions grouped under the same canonical language name."""
        # All extensions mapped to ``python`` should produce ``python``.
        python_exts = [e for e, l in EXTENSION_MAP.items() if l == "python"]
        assert ".py" in python_exts
        for ext in python_exts:
            assert detect_language("file" + ext) == "python"

    def test_supported_languages_returns_sorted_tuple(self):
        langs = supported_languages()
        assert isinstance(langs, tuple)
        assert langs == tuple(sorted(langs))
