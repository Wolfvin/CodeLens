"""
Semantic Search Engine for CodeLens (issue #11, Option A — TF-IDF).

Provides semantic symbol search over the indexed codebase so AI agents can
locate "authentication logic" even when the actual function is named
``verify_jwt_claims``. Implements the zero-dependency Option A from the issue:
TF-IDF over symbol names + signatures + kinds + file paths, ranked by cosine
similarity.

Design choices
--------------
* **Pure Python, no model files.** Avoids bundling ``sentence-transformers``
  or any ~80 MB embedding model. Fast to import, deterministic, no native
  deps. Good enough for the majority of agent "find the right file" queries.
* **Reads from the existing SQLite registry.** Symbol text is built from
  fields already populated by ``persistent_registry`` — ``name``,
  ``signature``, ``kind``, ``file_path``, ``language`` — so the index is
  always in sync with the last ``scan`` result. No separate index file to
  keep consistent.
* **In-memory index, cached per (db_path, mtime).** Building the vocabulary
  is O(N_symbols) — for CodeLens's own 3000-node graph this is <100 ms.
  Cached so repeated ``semantic_query`` calls within a session are ~1 ms.
* **Robust tokenization.** Splits ``snake_case``, ``camelCase``, ``kebab-case``
  and path segments so ``verifyJwtClaims`` and ``verify_jwt_claims`` produce
  the same token stream.

Naming note
-----------
This module is named ``semantic_search_engine`` to avoid colliding with the
pre-existing ``scripts/semantic_engine.py`` (a taint-analysis rules engine
that is itself deprecated as of PR #140 / issue #49 phase-1). The two
modules have no relationship — one is IR-style semantic search, the other
is taint-flow semantic rules. The naming overlap is unfortunate but
unavoidable without renaming the older module.

Public surface
--------------
- :func:`semantic_query` — main entry point used by the CLI command and the
  ``codelens_semantic_query`` MCP tool.
- :func:`build_index` — exposed for tests and callers that want to inspect
  the vocabulary / IDF weights directly.
- :func:`clear_cache` — used by tests to force a rebuild between cases.

The non-breaking nature of this module is what makes it a safe MVP: it adds
a new engine + command without touching any existing scan flow, schema, or
output shape. Existing commands and tests continue to work unchanged.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import threading
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from utils import default_db_path, logger


# ─── Stopwords ────────────────────────────────────────────────

# Small, conservative English stopword list. We intentionally do NOT pull in
# NLTK or any external dependency for this — the goal is zero-dep TF-IDF.
# These are tokens that carry almost no discriminative signal across a
# codebase (e.g. ``the``, ``a``, ``of``) and would otherwise inflate
# document vectors with noise.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "not", "is", "are", "was", "were",
    "be", "been", "being", "to", "of", "in", "on", "at", "by", "for",
    "with", "from", "as", "this", "that", "these", "those", "it", "its",
    "into", "than", "then", "so", "if", "but", "do", "does", "did",
    "has", "have", "had", "can", "could", "should", "would", "will",
    "shall", "may", "might", "must", "i", "you", "he", "she", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "our", "their",
})

# Minimum token length. Single-character tokens are almost never meaningful
# for code search (``x``, ``y``, ``i``, ``j``) and just add noise.
_MIN_TOKEN_LEN = 2

# Maximum tokens per document. Guards against pathological inputs (e.g. an
# enormous generated file with thousands of symbols in one path). 4096 is
# well above any realistic CodeLens symbol entry.
_MAX_TOKENS_PER_DOC = 4096


# ─── Tokenization ─────────────────────────────────────────────

# CamelCase boundary: split "verifyJwtClaims" -> ["verify", "Jwt", "Claims"]
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Split on any run of non-alphanumeric characters. This catches whitespace,
# underscores, hyphens, slashes, dots, AND signature punctuation like
# ``()``, ``,``, ``:``, ``[]``, ``<>``, ``=``, etc. — so ``def f(x, y)``
# tokenizes to ``["def", "f", "x", "y"]`` instead of leaking ``"f(x"`` as
# a single token.
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
# Strip leading/trailing non-alphanumerics from a token. With the split
# pattern above this is mostly a no-op, but kept as a defensive measure
# in case a caller feeds in a string that begins/ends with a symbol.
_TRIM_RE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")


def tokenize(text: str) -> List[str]:
    """Tokenize a string into normalized lowercase terms.

    Splits on whitespace, underscores, hyphens, slashes, dots, signature
    punctuation (``()``, ``,``, ``:``), AND camelCase boundaries — so both
    ``verify_jwt_claims`` and ``verifyJwtClaims`` produce the same token
    list ``["verify", "jwt", "claims"]``, and ``def f(x, y)`` produces
    ``["def", "f", "x", "y"]``. Single-character tokens and stopwords are
    filtered out.

    Args:
        text: Input string (symbol name, signature, file path, etc.).

    Returns:
        List of lowercase tokens, in their original order. Empty list if
        the input is empty or all-stopword.
    """
    if not text:
        return []

    tokens: List[str] = []
    # First split on any non-alphanumeric run
    for raw in _SPLIT_RE.split(text):
        if not raw:
            continue
        # Then split camelCase boundaries within each segment
        for sub in _CAMEL_BOUNDARY_RE.split(raw):
            sub = _TRIM_RE.sub("", sub)
            if not sub:
                continue
            # Lowercase for case-insensitive matching
            low = sub.lower()
            if len(low) < _MIN_TOKEN_LEN:
                continue
            if low in _STOPWORDS:
                continue
            tokens.append(low)
            if len(tokens) >= _MAX_TOKENS_PER_DOC:
                break
    return tokens


# ─── Symbol Document Building ─────────────────────────────────

def _build_symbol_text(symbol: Dict[str, Any]) -> str:
    """Build a text blob from a symbol row for TF-IDF tokenization.

    Concatenates the symbol name (highest signal), signature (function
    parameter and return type info), kind (function/class/id), language,
    and file path components (so directory names like ``auth/`` contribute
    signal). The relative weights are handled downstream by TF-IDF — the
    name field naturally gets higher weight because it's a short string
    where each token has a large TF contribution.

    Args:
        symbol: Dict from ``persistent_registry.get_all_symbols()``.
            Required keys: ``name``, ``kind``. Optional: ``signature``,
            ``file_path``, ``language``, ``extra_json``.

    Returns:
        Space-joined text blob. Never empty — at minimum contains the
        symbol name and kind.
    """
    parts: List[str] = []
    # Name — highest signal
    name = symbol.get("name") or ""
    if name:
        parts.append(name)
    # Signature — function parameter/return types
    sig = symbol.get("signature") or ""
    if sig:
        parts.append(sig)
    # Kind — function / class / id / etc.
    kind = symbol.get("kind") or ""
    if kind:
        parts.append(kind)
    # Language — "python", "js", "rust", ...
    lang = symbol.get("language") or ""
    if lang:
        parts.append(lang)
    # File path — directory names + filename carry semantic signal
    # (e.g. "auth/login.py" -> "auth login py")
    fp = symbol.get("file_path") or ""
    if fp:
        parts.append(fp)
    # Extra JSON — may contain status, exported flag, etc. We only extract
    # scalar string values; list/dict values are skipped to avoid
    # bloating the document with reference locations.
    extra_raw = symbol.get("extra_json")
    if extra_raw:
        try:
            import json
            extra = json.loads(extra_raw)
            if isinstance(extra, dict):
                for v in extra.values():
                    if isinstance(v, str) and v:
                        parts.append(v)
        except (ValueError, TypeError):
            # Malformed JSON — ignore, the text blob already has the
            # primary fields.
            pass
    return " ".join(parts)


# ─── Index ────────────────────────────────────────────────────

class SemanticIndex:
    """In-memory TF-IDF index over the CodeLens symbol registry.

    A new index is built by :func:`build_index` and cached per
    ``(db_path, db_mtime)``. Each instance is immutable after construction
    and safe to share across threads (read-only).

    Attributes:
        db_path: Absolute path to the SQLite database the index was built
            from.
        symbols: The raw symbol rows (dicts) the index covers. Used by
            :meth:`query` to populate result entries.
        vocabulary: Mapping ``term -> index`` into the IDF vector.
        idf: List of inverse-document-frequency weights, parallel to
            ``vocabulary`` values. ``idf[vocabulary[term]]`` is the IDF
            of ``term``.
        doc_vectors: List of TF-IDF vectors, one per symbol. Each vector
            is a ``{term_index: weight}`` dict (sparse representation).
        doc_norms: L2 norm of each document vector (precomputed for
            cosine similarity).
    """

    def __init__(
        self,
        db_path: str,
        symbols: List[Dict[str, Any]],
        vocabulary: Dict[str, int],
        idf: List[float],
        doc_vectors: List[Dict[int, float]],
        doc_norms: List[float],
    ) -> None:
        self.db_path = db_path
        self.symbols = symbols
        self.vocabulary = vocabulary
        self.idf = idf
        self.doc_vectors = doc_vectors
        self.doc_norms = doc_norms

    # ─── Query ──────────────────────────────────────────────

    def query(self, query_text: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Rank symbols by cosine similarity to ``query_text``.

        Args:
            query_text: Natural-language or code-fragment query
                (e.g. ``"user authentication flow"``).
            top_k: Maximum number of results to return. ``0`` returns all
                symbols sorted by similarity (still bounded by the index
                size).

        Returns:
            List of result dicts, sorted by descending similarity. Each
            dict has:

            * ``symbol``: the original symbol row (name, kind, file_path,
              line_start, language, signature, ...).
            * ``score``: cosine similarity in ``[0.0, 1.0]``. ``0.0`` means
              no shared terms with the query.
            * ``matched_terms``: list of query terms that appeared in the
              document (useful for explaining the ranking to a user).

            Symbols with zero similarity are excluded from the results.
        """
        if not self.symbols:
            return []
        if top_k < 0:
            top_k = 0

        # Tokenize the query and build a sparse query vector.
        q_tokens = tokenize(query_text)
        if not q_tokens:
            return []

        # Term frequency in the query
        q_tf = Counter(q_tokens)
        total_q = sum(q_tf.values())
        # Build sparse query vector: {term_index: tf * idf}
        q_vec: Dict[int, float] = {}
        q_matched_terms: List[str] = []
        for term, count in q_tf.items():
            idx = self.vocabulary.get(term)
            if idx is None:
                # Term not in any document — skip; contributes nothing to
                # cosine similarity because the document side is 0.
                continue
            tf = count / total_q
            q_vec[idx] = tf * self.idf[idx]
            q_matched_terms.append(term)

        if not q_vec:
            # Query had tokens but none appeared in any document
            return []

        # L2 norm of the query vector
        q_norm = math.sqrt(sum(w * w for w in q_vec.values()))
        if q_norm == 0.0:
            return []

        # Score every document. With ~3000 symbols this loop is <1 ms.
        results: List[Tuple[int, float, List[str]]] = []
        # Build a term -> index map view so we can list which query terms
        # matched in each document.
        for doc_idx, doc_vec in enumerate(self.doc_vectors):
            if not doc_vec:
                continue
            doc_norm = self.doc_norms[doc_idx]
            if doc_norm == 0.0:
                continue
            # Dot product over the smaller vector
            if len(q_vec) < len(doc_vec):
                small, large = q_vec, doc_vec
            else:
                small, large = doc_vec, q_vec
            dot = 0.0
            for term_idx, w in small.items():
                other = large.get(term_idx)
                if other is not None:
                    dot += w * other
            if dot == 0.0:
                continue
            sim = dot / (q_norm * doc_norm)
            # Sanity: cosine similarity should be in [-1, 1]; for TF-IDF
            # vectors (non-negative weights) it's in [0, 1]. Clamp to
            # guard against floating-point drift just above 1.0.
            if sim > 1.0:
                sim = 1.0
            elif sim < 0.0:
                sim = 0.0
            # Determine which query terms actually appeared in this doc
            matched_here = [
                t for t in q_matched_terms
                if self.vocabulary[t] in doc_vec
            ]
            results.append((doc_idx, sim, matched_here))

        # Sort by similarity descending, then by name for stable ordering
        results.sort(key=lambda r: (-r[1], self.symbols[r[0]].get("name", "")))

        if top_k > 0:
            results = results[:top_k]

        return [
            {
                "symbol": self.symbols[doc_idx],
                "score": round(sim, 4),
                "matched_terms": matched,
            }
            for doc_idx, sim, matched in results
        ]


# ─── Index Cache ──────────────────────────────────────────────

# Module-level cache: {(db_path, mtime): SemanticIndex}.
# The cache key includes the db file's mtime so a re-scan automatically
# invalidates the cached index. This is the same pattern used by
# ``persistent_registry`` for its connection cache.
_INDEX_CACHE: Dict[Tuple[str, float], SemanticIndex] = {}
_INDEX_CACHE_LOCK = threading.Lock()


def clear_cache() -> None:
    """Drop all cached indices. Primarily for tests."""
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def _load_symbols_from_db(db_path: str) -> List[Dict[str, Any]]:
    """Load all symbols from the SQLite registry at ``db_path``.

    Returns an empty list if the database doesn't exist, the ``symbols``
    table is missing, or SQLite is unavailable. Never raises — semantic
    search is a non-breaking add-on and should degrade gracefully to
    "no results" rather than crash the host command.

    Args:
        db_path: Absolute path to ``.codelens/codelens.db``.

    Returns:
        List of symbol dicts. Each dict has keys: ``id``, ``name``,
        ``kind``, ``file_path``, ``line_start``, ``line_end``,
        ``language``, ``signature``, ``hash``, ``extra_json``.
    """
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            # Sanity-check that the symbols table exists. If the workspace
            # has been initialized but never scanned, the db file exists
            # but has no tables.
            table = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='symbols'"
            ).fetchone()
            if table is None:
                return []
            rows = conn.execute("SELECT * FROM symbols").fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.debug(f"semantic_search_engine: failed to read symbols from {db_path}: {e}")
        return []


def build_index(db_path: str) -> SemanticIndex:
    """Build a TF-IDF index over all symbols in ``db_path``.

    The result is cached per ``(db_path, mtime)`` — calling this function
    twice with the same db file returns the same :class:`SemanticIndex`
    instance. Re-scanning the workspace (which writes a new mtime on the
    db file) automatically invalidates the cache.

    Args:
        db_path: Absolute path to ``.codelens/codelens.db``.

    Returns:
        A :class:`SemanticIndex`. If the db doesn't exist or has no
        symbols, returns an empty index (``len(symbols) == 0``) whose
        :meth:`SemanticIndex.query` always returns ``[]``.
    """
    if not os.path.exists(db_path):
        # Return an empty index — never raise. Callers should fall back
        # to "no results" rather than crash.
        return SemanticIndex(db_path, [], {}, [], [], [])

    try:
        mtime = os.path.getmtime(db_path)
    except OSError:
        mtime = 0.0

    cache_key = (db_path, mtime)
    with _INDEX_CACHE_LOCK:
        cached = _INDEX_CACHE.get(cache_key)
        if cached is not None:
            return cached

    symbols = _load_symbols_from_db(db_path)

    if not symbols:
        index = SemanticIndex(db_path, [], {}, [], [], [])
        with _INDEX_CACHE_LOCK:
            _INDEX_CACHE[cache_key] = index
        return index

    # ── Build document term-frequency vectors ──
    doc_tf_vectors: List[Counter] = []
    doc_freq: Counter = Counter()  # how many docs contain each term
    for sym in symbols:
        text = _build_symbol_text(sym)
        toks = tokenize(text)
        tf = Counter(toks)
        doc_tf_vectors.append(tf)
        # Document frequency: increment once per term per doc
        for term in tf.keys():
            doc_freq[term] += 1

    # ── Build vocabulary ──
    # Sort terms for deterministic indexing (so the same db always produces
    # the same vocabulary order, which makes debugging easier).
    sorted_terms = sorted(doc_freq.keys())
    vocabulary: Dict[str, int] = {term: i for i, term in enumerate(sorted_terms)}

    # ── IDF (smoothed) ──
    # idf(t) = ln((N + 1) / (df(t) + 1)) + 1
    # The +1 in numerator and denominator is the standard "add-one"
    # smoothing that prevents division by zero and dampens the IDF of
    # terms that appear in every document. The trailing +1 ensures
    # IDF is always > 0 (so a term that appears in every doc still
    # contributes a small amount, rather than being zeroed out).
    n_docs = len(symbols)
    idf: List[float] = []
    for term in sorted_terms:
        df = doc_freq[term]
        weight = math.log((n_docs + 1) / (df + 1)) + 1.0
        idf.append(weight)

    # ── TF-IDF document vectors + L2 norms ──
    doc_vectors: List[Dict[int, float]] = []
    doc_norms: List[float] = []
    for tf in doc_tf_vectors:
        total = sum(tf.values())
        if total == 0:
            doc_vectors.append({})
            doc_norms.append(0.0)
            continue
        vec: Dict[int, float] = {}
        for term, count in tf.items():
            idx = vocabulary[term]
            tf_val = count / total
            vec[idx] = tf_val * idf[idx]
        norm = math.sqrt(sum(w * w for w in vec.values()))
        doc_vectors.append(vec)
        doc_norms.append(norm)

    index = SemanticIndex(
        db_path=db_path,
        symbols=symbols,
        vocabulary=vocabulary,
        idf=idf,
        doc_vectors=doc_vectors,
        doc_norms=doc_norms,
    )
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE[cache_key] = index
    return index


# ─── Public API ───────────────────────────────────────────────

def semantic_query(
    workspace: str,
    query: str,
    top_k: int = 10,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a semantic search query against the workspace symbol registry.

    This is the main entry point used by the ``semantic-query`` CLI command
    and the ``codelens_semantic_query`` MCP tool. It builds (or retrieves
    a cached) TF-IDF index over the workspace's SQLite symbol registry
    and returns the top-k symbols ranked by cosine similarity to the
    query.

    Args:
        workspace: Absolute or relative path to the workspace root. The
            registry database is read from
            ``<workspace>/.codelens/codelens.db`` unless ``db_path`` is
            given.
        query: Natural-language or code-fragment query (e.g.
            ``"user authentication flow"``, ``"parse jwt"``,
            ``"error handler"``).
        top_k: Maximum number of results to return. ``0`` returns all
            matching symbols (still bounded by index size). Negative
            values are treated as ``0``. Default: ``10``.
        db_path: Override the database path. Mainly for tests; callers
            should let the default resolve via :func:`utils.default_db_path`.

    Returns:
        Dict with the following shape::

            {
                "status": "ok",
                "query": "<original query>",
                "workspace": "<absolute workspace path>",
                "top_k": <int>,
                "stats": {
                    "total_symbols": <int>,    # symbols in the registry
                    "returned": <int>,          # results in this response
                    "truncated": <bool>,        # True if more than top_k matched
                    "index_size": <int>,        # vocabulary size
                },
                "results": [
                    {
                        "name": "<symbol name>",
                        "kind": "<function|class|id|...>",
                        "file": "<relative file path>",
                        "line": <int>,
                        "language": "<python|js|rust|...>",
                        "signature": "<function signature or null>",
                        "score": <float in [0, 1]>,
                        "matched_terms": ["<term>", ...],
                    },
                    ...
                ],
            }

        On error (e.g. empty query), ``status`` is ``"error"`` with a
        ``message`` field and empty ``results``. A workspace that has
        never been scanned returns ``status="ok"`` with
        ``total_symbols=0`` and empty ``results`` — this is not an error,
        just a "nothing to search" state.
    """
    workspace = os.path.abspath(workspace)
    if db_path is None:
        db_path = default_db_path(workspace)

    if not query or not query.strip():
        return {
            "status": "error",
            "message": "Query must be a non-empty string.",
            "query": query,
            "workspace": workspace,
            "top_k": top_k,
            "stats": {
                "total_symbols": 0,
                "returned": 0,
                "truncated": False,
                "index_size": 0,
            },
            "results": [],
        }

    try:
        index = build_index(db_path)
    except Exception as e:
        # build_index is designed to never raise (it catches its own
        # sqlite errors), but we add a defensive try here so the host
        # command never crashes from a semantic-search failure.
        logger.warning(f"semantic_search_engine: build_index failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"Failed to build search index: {e}",
            "query": query,
            "workspace": workspace,
            "top_k": top_k,
            "stats": {
                "total_symbols": 0,
                "returned": 0,
                "truncated": False,
                "index_size": 0,
            },
            "results": [],
        }

    # Top-K clamp
    if top_k < 0:
        top_k = 0

    ranked = index.query(query, top_k=top_k)

    # Build the response
    results: List[Dict[str, Any]] = []
    for r in ranked:
        sym = r["symbol"]
        results.append({
            "name": sym.get("name", ""),
            "kind": sym.get("kind", ""),
            "file": sym.get("file_path", ""),
            "line": sym.get("line_start") or 0,
            "language": sym.get("language", ""),
            "signature": sym.get("signature"),
            "score": r["score"],
            "matched_terms": r["matched_terms"],
        })

    # Truncation flag: True iff there were more than top_k matching
    # symbols. We need to query with top_k=0 to count total matches.
    total_matches = len(index.query(query, top_k=0)) if results else 0
    truncated = bool(top_k > 0 and total_matches > top_k)

    return {
        "status": "ok",
        "query": query,
        "workspace": workspace,
        "top_k": top_k,
        "stats": {
            "total_symbols": len(index.symbols),
            "returned": len(results),
            "truncated": truncated,
            "index_size": len(index.vocabulary),
        },
        "results": results,
    }
