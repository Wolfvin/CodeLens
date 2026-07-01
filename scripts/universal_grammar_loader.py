"""
Universal Tree-Sitter Grammar Loader for CodeLens (issue #18)
=============================================================

Auto-detects and loads tree-sitter grammars for 100+ languages from PyPI
``tree-sitter-<lang>`` packages. The number of supported languages is
determined by the entries in :data:`EXTENSION_MAP`; call
:func:`supported_languages` for the exact count at runtime.

Public API
----------
- ``detect_language(file_path)`` — detect language from extension or shebang.
- ``load_grammar(language)``    — return a ``tree_sitter.Language`` object,
  optionally auto-installing the PyPI grammar package when the
  ``CODELENS_AUTO_INSTALL_GRAMMARS=1`` environment variable is set.

Design notes
------------
- Auto-install is **opt-in only**. Without ``CODELENS_AUTO_INSTALL_GRAMMARS=1``
  the loader never touches the network or the filesystem outside of normal
  Python import machinery.
- All failures are logged at ``info``/``warning`` level and the loader returns
  ``None`` — callers must treat a missing grammar as "skip this file", never
  as a fatal error.
- The module degrades gracefully when ``tree_sitter`` itself is unavailable
  (``load_grammar`` always returns ``None`` in that case).
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
import subprocess
import sys
from typing import Optional, Tuple

# ─── Optional tree-sitter dependency ────────────────────────────
# ``tree_sitter`` may be absent (minimal install). We degrade to
# ``Language = None`` and ``load_grammar`` short-circuits to ``None``.
try:
    from tree_sitter import Language  # type: ignore
except ImportError:  # pragma: no cover — tree-sitter is in dependencies
    Language = None  # type: ignore[assignment,misc]

logger = logging.getLogger("codelens.grammar_loader")

# ─── Configuration ──────────────────────────────────────────────
AUTO_INSTALL_ENV = "CODELENS_AUTO_INSTALL_GRAMMARS"

# ─── Extension → language mapping ───────────────────────────────
# Covers 50+ languages spanning the tree-sitter ecosystem. Each
# entry is canonical: lowercase extension (with leading dot) →
# lowercase language identifier used by the corresponding
# ``tree-sitter-<lang>`` PyPI package.
EXTENSION_MAP: dict = {
    # ── Web / frontend ──────────────────────────────────────────
    ".html": "html",
    ".htm": "html",
    ".xhtml": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "scss",
    ".less": "less",
    ".vue": "vue",
    ".svelte": "svelte",
    # ── JavaScript family ───────────────────────────────────────
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    # ── Systems / native ────────────────────────────────────────
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cppm": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".hh": "cpp",
    ".inl": "cpp",
    ".rs": "rust",
    ".go": "go",
    ".zig": "zig",
    ".nim": "nim",
    ".nims": "nim",
    ".d": "d",
    ".di": "d",
    ".asm": "asm",
    ".s": "asm",
    ".cr": "crystal",
    # ── JVM ─────────────────────────────────────────────────────
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".scala": "scala",
    ".sc": "scala",
    ".sbt": "scala",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".clj": "clojure",
    ".cljs": "clojure",
    ".cljc": "clojure",
    ".edn": "clojure",
    ".clj_rl": "clojure",
    # ── .NET ────────────────────────────────────────────────────
    ".cs": "csharp",
    ".csx": "csharp",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".fsx": "fsharp",
    # ── Scripting ───────────────────────────────────────────────
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    ".rb": "ruby",
    ".rbs": "ruby",
    ".php": "php",
    ".phtml": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".t": "perl",
    ".pod": "perl",
    ".lua": "lua",
    ".tcl": "tcl",
    ".r": "r",
    ".jl": "julia",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".psd1": "powershell",
    ".vim": "vim",
    ".viml": "vim",
    ".el": "elisp",
    ".elc": "elisp",
    ".scm": "scheme",
    ".ss": "scheme",
    ".lisp": "lisp",
    ".lsp": "lisp",
    ".cl": "lisp",
    # ── Functional / type-driven ────────────────────────────────
    ".hs": "haskell",
    ".lhs": "haskell",
    ".cabal": "cabal",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".elm": "elm",
    ".purs": "purescript",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".ex": "elixir",
    ".exs": "elixir",
    ".gleam": "gleam",
    # ── Mobile ──────────────────────────────────────────────────
    ".swift": "swift",
    ".dart": "dart",
    ".m": "objc",
    ".mm": "objc",
    # ── Shell / config ──────────────────────────────────────────
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ksh": "bash",
    ".bats": "bash",
    ".fish": "fish",
    ".sql": "sql",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "proto",
    ".thrift": "thrift",
    ".tf": "hcl",
    ".tfvars": "hcl",
    ".hcl": "hcl",
    ".makefile": "make",
    ".mk": "make",
    ".mak": "make",
    ".cmake": "cmake",
    # ── Data / serialization ────────────────────────────────────
    ".json": "json",
    ".jsonc": "json",
    ".json5": "json5",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".xml": "xml",
    ".svg": "xml",
    ".rss": "xml",
    ".atom": "xml",
    ".xsd": "xml",
    ".xsl": "xml",
    ".xslt": "xml",
    # ── Documentation ───────────────────────────────────────────
    ".md": "markdown",
    ".markdown": "markdown",
    ".mdx": "markdown",
    ".tex": "latex",
    ".ltx": "latex",
    ".sty": "latex",
    ".cls": "latex",
    ".rst": "rst",
    ".org": "org",
    # ── Build / container ───────────────────────────────────────
    ".dockerfile": "dockerfile",
    ".containerfile": "dockerfile",
    ".gemspec": "ruby",
    ".rake": "ruby",
    # ── Blockchain / DSL ────────────────────────────────────────
    ".sol": "solidity",
    ".move": "move",
    # ── Misc / niche ────────────────────────────────────────────
    ".gd": "gdscript",
    ".gql_schema": "graphql",
    ".dot": "dot",
    ".graphqls": "graphql",
    ".wat": "wat",
    ".wast": "wat",
    ".sn": "snakemake",
    ".bzl": "starlark",
    ".bazel": "starlark",
    ".star": "starlark",
    ".glsl": "glsl",
    ".frag": "glsl",
    ".vert": "glsl",
    ".hack": "hack",
    ".d2": "d2",
    ".hocon": "hocon",
    ".jinja": "jinja",
    ".jinja2": "jinja",
    ".snippets": "snippets",
    ".pest": "pest",
    ".pyraml": "yaml",
    ".raml": "raml",
    ".agda": "agda",
    ".idr": "idris",
    ".carp": "carp",
    ".wren": "wren",
    ".janet": "janet",
    ".fennel": "fennel",
    ".vala": "vala",
    ".v": "verilog",
    ".sv": "verilog",
    ".vh": "verilog",
    ".svh": "verilog",
    ".ecl": "ecl",
    ".kusto": "kusto",
    ".kql": "kusto",
    ".cue": "cue",
    ".dhall": "dhall",
    ".nickel": "nickel",
    ".nu": "nu",
    ".roc": "roc",
    ".xy": "xy",
    ".tact": "tact",
    ".gnu": "gnuplot",
    ".plt": "gnuplot",
}

# ── Special filenames (basename → language) ─────────────────────
# These have no extension or a non-standard one; we match the exact
# basename (case-sensitive where it matters) and a few well-known
# suffix patterns.
BASENAME_MAP: dict = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "make",
    "gnumakefile": "make",
    "rakefile": "ruby",
    "gemfile": "ruby",
    "capfile": "ruby",
    "vagrantfile": "ruby",
    "guardfile": "ruby",
    "appraisals": "ruby",
    "berksfile": "ruby",
    "thorfile": "ruby",
    "podfile": "ruby",
    "fastfile": "ruby",
    "appfile": "ruby",
    "deliverfile": "ruby",
    "snapfile": "ruby",
    "matchfile": "ruby",
    "scanfile": "ruby",
    "gymfile": "ruby",
    "workspace": "bzl",  # Buck/Tulsi workspace file
    "build": "bzl",      # Buck/Pants build file (could also be Bazel BUILD)
    "build.bazel": "bzl",
    "workspace.bazel": "bzl",
    "cmakelists.txt": "cmake",
    "mix.exs": "elixir",
    "rebar.config": "erlang",
    "jakefile": "javascript",
    "brewfile": "ruby",
    "csproj": "xml",     # MSBuild project (XML-based)
    "fsproj": "xml",
    "vbproj": "xml",
    "vcxproj": "xml",
    "props": "xml",
    "targets": "xml",
}

# Files whose name *ends with* one of these suffixes map to a language.
# Used for files like ``nginx.Dockerfile`` or ``php.dockerfile``.
BASENAME_SUFFIX_MAP: dict = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
}

# ── Shebang → language mapping ──────────────────────────────────
# The shebang interpreter (last path component, stripped of version
# digits) is mapped to a language. Examples:
#   ``#!/usr/bin/env python3``  → ``python``
#   ``#!/usr/bin/env ruby``     → ``ruby``
#   ``#!/bin/bash``             → ``bash``
SHEBANG_MAP: dict = {
    "python": "python",
    "python2": "python",
    "python3": "python",
    "ruby": "ruby",
    "rbx": "ruby",
    "jruby": "ruby",
    "node": "javascript",
    "nodejs": "javascript",
    "deno": "typescript",
    "bun": "javascript",
    "bash": "bash",
    "sh": "bash",
    "dash": "bash",
    "zsh": "bash",
    "ksh": "bash",
    "fish": "fish",
    "perl": "perl",
    "perl5": "perl",
    "php": "php",
    "lua": "lua",
    "tcl": "tcl",
    "tclsh": "tcl",
    "wish": "tcl",
    "awk": "awk",
    "gawk": "awk",
    "mawk": "awk",
    "nushell": "nu",
    "nu": "nu",
    "elixir": "elixir",
    "escript": "erlang",
    "guile": "scheme",
    "rscript": "r",
    "r": "r",
    "julia": "julia",
    "ocaml": "ocaml",
    "ocamlrun": "ocaml",
    "pwsh": "powershell",
    "pwsh-preview": "powershell",
}

# ── Language → PyPI package name (kebab-case) overrides ─────────
# Most tree-sitter packages are simply ``tree-sitter-<lang>`` where
# ``<lang>`` is the lowercase language identifier with underscores
# replaced by hyphens. A handful of languages ship under a different
# PyPI name; we keep an explicit override table for those.
PACKAGE_NAME_OVERRIDES: dict = {
    "csharp": "tree-sitter-c-sharp",
    "fsharp": "tree-sitter-fsharp",
    "objc": "tree-sitter-objc",
    "elisp": "tree-sitter-elisp",
    "vim": "tree-sitter-vim",
    "tsx": "tree-sitter-typescript",  # same package as typescript
    "typescript": "tree-sitter-typescript",
    "c": "tree-sitter-c",
    "cpp": "tree-sitter-cpp",
    "asm": "tree-sitter-asm",
    "make": "tree-sitter-make",
    "scheme": "tree-sitter-scheme",
    "lisp": "tree-sitter-clojure",  # rough fallback; clojure covers most lisp
    "less": "tree-sitter-css",       # closest existing grammar
    "ini": "tree-sitter-ini",
    "xml": "tree-sitter-xml",
    "latex": "tree-sitter-latex",
    "bzl": "tree-sitter-starlark",
    "starlark": "tree-sitter-starlark",
    "nu": "tree-sitter-nu",
    "wat": "tree-sitter-wat",
    "hocon": "tree-sitter-hocon",
    "jinja": "tree-sitter-jinja",
    "cue": "tree-sitter-cue",
    "dhall": "tree-sitter-dhall",
    "glsl": "tree-sitter-glsl",
    "graphql": "tree-sitter-graphql",
    "hcl": "tree-sitter-hcl",
    "verilog": "tree-sitter-verilog",
    "pest": "tree-sitter-pest",
    "elm": "tree-sitter-elm",
    "purescript": "tree-sitter-purescript",
    "gleam": "tree-sitter-gleam",
    "move": "tree-sitter-move",
    "tact": "tree-sitter-tact",
    "d2": "tree-sitter-d2",
    "snakemake": "tree-sitter-snakemake",
    "snippets": "tree-sitter-snippets",
    "kusto": "tree-sitter-kusto",
    "nickel": "tree-sitter-nickel",
    "roc": "tree-sitter-roc",
    "hack": "tree-sitter-hack",
    "agda": "tree-sitter-agda",
    "idris": "tree-sitter-idris",
    "carp": "tree-sitter-carp",
    "wren": "tree-sitter-wren",
    "janet": "tree-sitter-janet",
    "fennel": "tree-sitter-fennel",
    "vala": "tree-sitter-vala",
    "ecl": "tree-sitter-ecl",
    "dot": "tree-sitter-dot",
    "raml": "tree-sitter-raml",
    "cabal": "tree-sitter-cabal",
    "rst": "tree-sitter-rst",
    "org": "tree-sitter-org",
    "solidity": "tree-sitter-solidity",
    "powershell": "tree-sitter-powershell",
    "dockerfile": "tree-sitter-dockerfile",
    "cmake": "tree-sitter-cmake",
    "yaml": "tree-sitter-yaml",
    "toml": "tree-sitter-toml",
    "json": "tree-sitter-json",
    "json5": "tree-sitter-json5",
    "markdown": "tree-sitter-markdown",
    "ruby": "tree-sitter-ruby",
    "go": "tree-sitter-go",
    "rust": "tree-sitter-rust",
    "python": "tree-sitter-python",
    "javascript": "tree-sitter-javascript",
    "html": "tree-sitter-html",
    "css": "tree-sitter-css",
    "scss": "tree-sitter-scss",
    "vue": "tree-sitter-vue",
    "svelte": "tree-sitter-svelte",
    "java": "tree-sitter-java",
    "kotlin": "tree-sitter-kotlin",
    "scala": "tree-sitter-scala",
    "groovy": "tree-sitter-groovy",
    "clojure": "tree-sitter-clojure",
    "erlang": "tree-sitter-erlang",
    "elixir": "tree-sitter-elixir",
    "haskell": "tree-sitter-haskell",
    "ocaml": "tree-sitter-ocaml",
    "lua": "tree-sitter-lua",
    "swift": "tree-sitter-swift",
    "dart": "tree-sitter-dart",
    "perl": "tree-sitter-perl",
    "r": "tree-sitter-r",
    "julia": "tree-sitter-julia",
    "php": "tree-sitter-php",
    "sql": "tree-sitter-sql",
    "proto": "tree-sitter-proto",
    "thrift": "tree-sitter-thrift",
    "crystal": "tree-sitter-crystal",
    "zig": "tree-sitter-zig",
    "nim": "tree-sitter-nim",
    "d": "tree-sitter-d",
    "fish": "tree-sitter-fish",
    "gdscript": "tree-sitter-gdscript",
    "tcl": "tree-sitter-tcl",
    "awk": "tree-sitter-awk",
    "gnuplot": "tree-sitter-gnuplot",
    "xy": "tree-sitter-xy",
}

# ── Module entry-function overrides ─────────────────────────────
# Most ``tree_sitter_<lang>`` modules expose a single ``language()``
# function returning the language pointer. A few ship multiple
# languages in one wheel (notably typescript/tsx); for those we map
# the canonical language name to the exact entry function name.
ENTRY_FUNCTION_OVERRIDES: dict = {
    "typescript": "language_typescript",
    "tsx": "language_tsx",
}


def _normalize_language_name(language: str) -> str:
    """Normalize a user-supplied language identifier to canonical form."""
    if not language:
        return ""
    return language.strip().lower().replace("-", "_").replace(" ", "_")


# ── Module name overrides ────────────────────────────────────────
# Some languages share a single Python wheel with another language and
# therefore expose a non-default module name. Notably ``tsx`` and
# ``typescript`` both ship in the ``tree-sitter-typescript`` wheel whose
# import name is ``tree_sitter_typescript`` (there is no
# ``tree_sitter_tsx`` module on PyPI).
MODULE_NAME_OVERRIDES: dict = {
    "tsx": "tree_sitter_typescript",
}


def _import_module_name(language: str) -> str:
    """Return the Python module name to import for a given language.

    Almost all tree-sitter packages use ``tree_sitter_<lang>`` (snake_case).
    Languages listed in :data:`MODULE_NAME_OVERRIDES` ship under a different
    module name (e.g. ``tsx`` → ``tree_sitter_typescript``).
    """
    norm = _normalize_language_name(language)
    if norm in MODULE_NAME_OVERRIDES:
        return MODULE_NAME_OVERRIDES[norm]
    return "tree_sitter_" + norm


def _package_name(language: str) -> str:
    """Return the PyPI distribution name (kebab-case) for a language."""
    norm = _normalize_language_name(language)
    if norm in PACKAGE_NAME_OVERRIDES:
        return PACKAGE_NAME_OVERRIDES[norm]
    # Default: hyphenate underscores.
    return "tree-sitter-" + norm.replace("_", "-")


def _read_shebang(file_path: str, max_bytes: int = 256) -> Optional[str]:
    """Read the first line of ``file_path`` if it is a shebang line.

    Returns the shebang line (without trailing newline) or ``None``.
    Never raises — file access errors are swallowed.
    """
    try:
        with open(file_path, "rb") as fh:
            head = fh.read(max_bytes)
    except (OSError, UnicodeDecodeError):  # pragma: no cover — defensive
        return None
    if not head.startswith(b"#!"):
        return None
    # Only consider the first line.
    nl = head.find(b"\n")
    if nl == -1:
        line = head
    else:
        line = head[:nl]
    try:
        return line.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover — defensive
        return None


def _interpreter_from_shebang(shebang: str) -> Optional[str]:
    """Extract the interpreter name from a shebang line.

    Handles ``#!/usr/bin/env <interp>`` and ``#!/path/to/<interp>`` forms,
    stripping common version suffixes (e.g. ``python3.11`` → ``python3``).
    """
    if not shebang or not shebang.startswith("#!"):
        return None
    # Strip leading ``#!`` and whitespace.
    rest = shebang[2:].strip()
    if not rest:
        return None
    # Handle ``env`` form: ``/usr/bin/env python3``.
    parts = rest.split()
    if not parts:
        return None
    if parts[0].endswith("/env") and len(parts) >= 2:
        interp = parts[1]
    else:
        interp = parts[0]
    # Strip directories: ``/usr/bin/python3`` → ``python3``.
    interp = interp.rsplit("/", 1)[-1]
    # Strip common version suffixes for Python/Ruby: ``python3.11`` → ``python3``.
    # We only do this for known multi-version interpreters.
    if interp.startswith(("python", "ruby", "perl", "php", "node")):
        # Drop trailing ``.NN`` style versions, but keep the major digit
        # so we still distinguish ``python2`` from ``python3``.
        dot = interp.find(".")
        if dot > 0:
            interp = interp[:dot]
    return interp.lower() if interp else None


def detect_language(file_path: str) -> Optional[str]:
    """Detect the programming language for ``file_path``.

    Detection strategy (in priority order):
      1. Special basename match (``Dockerfile``, ``Makefile``, ``Rakefile`` …).
      2. File extension (case-insensitive).
      3. Shebang line interpreter (for extensionless scripts).

    Returns ``None`` when no language can be identified.

    The function is safe to call on any path — it never raises and
    tolerates missing files (extension-only detection is used when the
    file cannot be opened).
    """
    if not file_path:
        return None

    filename = os.path.basename(file_path)
    if not filename:
        return None

    # 1. Exact basename (case-insensitive) → language.
    base_lower = filename.lower()
    if base_lower in BASENAME_MAP:
        return BASENAME_MAP[base_lower]

    # 2. Filename-suffix match (e.g. ``nginx.Dockerfile`` → ``dockerfile``).
    for suffix, lang in BASENAME_SUFFIX_MAP.items():
        if base_lower.endswith("." + suffix) or base_lower == suffix:
            return lang

    # 3. Extension match.
    _, ext = os.path.splitext(filename)
    if ext:
        ext_lower = ext.lower()
        if ext_lower in EXTENSION_MAP:
            return EXTENSION_MAP[ext_lower]

    # 4. Shebang line (for extensionless scripts).
    shebang = _read_shebang(file_path)
    if shebang:
        interp = _interpreter_from_shebang(shebang)
        if interp and interp in SHEBANG_MAP:
            return SHEBANG_MAP[interp]

    return None


def _extract_language_pointer(module, language: str) -> Optional[object]:
    """Return the language pointer from an imported grammar module.

    Most modules expose ``language()``; typescript and tsx ship two
    functions (``language_typescript`` and ``language_tsx``) in a single
    wheel.
    """
    # 1. Explicit override (typescript/tsx).
    override = ENTRY_FUNCTION_OVERRIDES.get(_normalize_language_name(language))
    if override:
        fn = getattr(module, override, None)
        if callable(fn):
            try:
                return fn()
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("entry function %s() raised %s", override, exc)

    # 2. Common ``language()`` entry point.
    fn = getattr(module, "language", None)
    if callable(fn):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("language() raised %s", exc)

    # 3. ``language_<lang>()`` fallback (some packages use this form).
    norm = _normalize_language_name(language)
    fn = getattr(module, "language_" + norm, None)
    if callable(fn):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("language_%s() raised %s", norm, exc)

    return None


def _try_import(language: str) -> Optional[object]:
    """Attempt to import the grammar module for ``language``.

    Returns the imported module object or ``None``.
    """
    module_name = _import_module_name(language)
    try:
        return importlib.import_module(module_name)
    except ImportError:
        return None
    except Exception as exc:  # pragma: no cover — defensive
        # A broken grammar wheel shouldn't crash the whole scan.
        logger.debug("import %s raised %s", module_name, exc)
        return None


def _auto_install_enabled() -> bool:
    """Return True iff the user opted into grammar auto-install."""
    return os.environ.get(AUTO_INSTALL_ENV, "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _pip_install(package: str) -> bool:
    """Install a PyPI grammar package via ``pip install``.

    Uses the current Python interpreter so the grammar lands in the
    right ``site-packages``. Returns True on success, False otherwise.
    """
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", package]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("pip install %s failed: %s", package, exc)
        return False
    if proc.returncode != 0:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace").strip()
        logger.warning("pip install %s exited %s: %s", package, proc.returncode, stderr[:300])
        return False
    return True


def _invalidate_import_cache(module_name: str) -> None:
    """Remove a (possibly failed) module entry from sys.modules so a
    re-import after install actually picks up the new package."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    # Also invalidate any finder caches so importlib sees the new package.
    try:
        importlib.invalidate_caches()
    except Exception:  # pragma: no cover — defensive
        pass


def load_grammar(language: str) -> Optional["Language"]:
    """Load a tree-sitter ``Language`` object for ``language``.

    Algorithm
    ---------
    1. Try ``import tree_sitter_<language>`` (snake_case).
    2. If not found *and* ``CODELENS_AUTO_INSTALL_GRAMMARS=1`` is set,
       run ``pip install tree-sitter-<language>`` (kebab-case) and retry.
    3. Extract the language pointer (handles ``language()``,
       ``language_typescript()``, ``language_tsx()`` entry points).
    4. Return ``Language(ptr)`` or ``None`` if anything failed.

    Returns ``None`` silently (with an info-level log message) when:
    - ``tree_sitter`` itself is not importable.
    - The grammar package is not installed and auto-install is disabled.
    - The grammar package is installed but broken.
    - Auto-install was attempted but failed.

    This function **never** raises — callers can rely on a clean
    ``Optional[Language]`` contract.
    """
    norm = _normalize_language_name(language)
    if not norm:
        return None

    if Language is None:
        logger.info("tree_sitter not available — cannot load grammar for %s", norm)
        return None

    module = _safe_try_import(norm)
    if module is None and _auto_install_enabled():
        package = _package_name(norm)
        logger.info("auto-installing grammar %s (package %s)", norm, package)
        if _pip_install(package):
            _invalidate_import_cache(_import_module_name(norm))
            module = _safe_try_import(norm)
        else:
            logger.warning("auto-install failed for %s — skipping", norm)
            return None

    if module is None:
        logger.info("grammar for %s not installed (set %s=1 to enable auto-install)",
                    norm, AUTO_INSTALL_ENV)
        return None

    ptr = _extract_language_pointer(module, norm)
    if ptr is None:
        logger.info("grammar module for %s did not expose a language entry point", norm)
        return None

    try:
        return Language(ptr)
    except Exception as exc:  # pragma: no cover — defensive
        logger.info("failed to construct Language for %s: %s", norm, exc)
        return None


def _safe_try_import(language: str) -> Optional[object]:
    """Wrapper around ``_try_import`` that swallows unexpected exceptions.

    A broken grammar wheel may raise from deep inside CFFI/ctypes — we never
    want that to crash a scan. ``_try_import`` already handles ``ImportError``
    and common ``Exception`` subclasses from the import call itself, but we
    add an outer safety net so a buggy monkey-patch or a corrupted module
    can't take the whole scan down.
    """
    try:
        return _try_import(language)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("_try_import(%s) raised %s", language, exc)
        return None


def available_languages() -> Tuple[str, ...]:
    """Return the tuple of languages for which a grammar is importable right now.

    This is a quick, side-effect-free probe — it does not auto-install.
    Used by the ``scan`` command for stats and the ``list`` command for
    capability reporting.
    """
    out = []
    seen = set()
    for lang in EXTENSION_MAP.values():
        if lang in seen:
            continue
        seen.add(lang)
        if _try_import(lang) is not None:
            out.append(lang)
    for lang in BASENAME_MAP.values():
        if lang in seen:
            continue
        seen.add(lang)
        if _try_import(lang) is not None:
            out.append(lang)
    return tuple(sorted(out))


def supported_languages() -> Tuple[str, ...]:
    """Return the tuple of language identifiers CodeLens can *detect*
    (whether or not a grammar is currently installed)."""
    seen = set()
    for lang in EXTENSION_MAP.values():
        seen.add(lang)
    for lang in BASENAME_MAP.values():
        seen.add(lang)
    for lang in SHEBANG_MAP.values():
        seen.add(lang)
    return tuple(sorted(seen))


def supported_extensions_count() -> int:
    """Return the number of distinct file extensions CodeLens can detect."""
    return len(EXTENSION_MAP)


__all__ = [
    "detect_language",
    "load_grammar",
    "available_languages",
    "supported_languages",
    "supported_extensions_count",
    "EXTENSION_MAP",
    "BASENAME_MAP",
    "SHEBANG_MAP",
    "AUTO_INSTALL_ENV",
]
