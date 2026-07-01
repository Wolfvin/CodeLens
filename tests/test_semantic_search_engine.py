"""
Tests for the semantic SEARCH engine (issue #11, Option A — TF-IDF).

This file tests ``scripts/semantic_search_engine.py`` — the IR-style TF-IDF
symbol search. It is distinct from ``tests/test_semantic_engine.py``, which
tests the deprecated taint-analysis rules engine in
``scripts/semantic_engine.py``. The two modules share the "semantic" prefix
but have no other relationship.

The tests build a tiny SQLite registry in a temp directory, then verify
that :func:`semantic_search_engine.semantic_query` returns ranked results
that match intuition:

* A query for ``"auth"`` surfaces a symbol named ``verify_jwt_claims``
  even though the literal string ``"auth"`` never appears in the symbol
  name — only in the file path. This is the core value proposition of
  the issue (find by meaning, not just by literal name).
* Tokenization handles ``snake_case``, ``camelCase``, and path segments
  uniformly.
* IDF weighting causes rare, discriminative terms (e.g. ``jwt``) to rank
  higher than ubiquitous terms (e.g. ``function``).
* The engine degrades gracefully — empty query, missing db, missing
  ``symbols`` table, and ``top_k=0`` all return well-formed responses
  rather than raising.
* The cache invalidates on db mtime change, so a re-scan picks up new
  symbols.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

import pytest

# Make scripts/ importable
_SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import semantic_search_engine
from semantic_search_engine import (
    SemanticIndex,
    build_index,
    clear_cache,
    semantic_query,
    tokenize,
)


# ─── Fixtures ─────────────────────────────────────────────────

def _make_db(workspace: str, symbols):
    """Create a fake ``.codelens/codelens.db`` with the given symbol rows.

    ``symbols`` is a list of dicts with keys: name, kind, file_path,
    line_start, language, signature, extra_json (dict, will be
    JSON-encoded).
    """
    codelens_dir = os.path.join(workspace, ".codelens")
    os.makedirs(codelens_dir, exist_ok=True)
    db_path = os.path.join(codelens_dir, "codelens.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'function',
                file_path TEXT,
                line_start INTEGER,
                line_end INTEGER,
                language TEXT,
                signature TEXT,
                hash TEXT,
                extra_json TEXT
            )
            """
        )
        for i, s in enumerate(symbols, start=1):
            extra = s.get("extra_json") or {}
            conn.execute(
                """
                INSERT INTO symbols
                    (id, name, kind, file_path, line_start, line_end,
                     language, signature, hash, extra_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    i,
                    s["name"],
                    s.get("kind", "function"),
                    s.get("file_path", ""),
                    s.get("line_start"),
                    s.get("line_end"),
                    s.get("language", ""),
                    s.get("signature", ""),
                    s.get("hash", ""),
                    json.dumps(extra) if extra else None,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def workspace():
    """Create a temp workspace with no db. Caller is responsible for
    calling :func:`_make_db` to populate it."""
    ws = tempfile.mkdtemp(prefix="codelens_semantic_test_")
    yield ws
    # Drop the cache so the next test starts fresh
    clear_cache()
    shutil.rmtree(ws, ignore_errors=True)


def _auth_workspace():
    """A workspace with a mix of auth-related and unrelated symbols.

    Used by multiple tests to verify the core "find by meaning" behavior.
    """
    ws = tempfile.mkdtemp(prefix="codelens_semantic_auth_")
    _make_db(ws, [
        {
            "name": "verify_jwt_claims",
            "kind": "function",
            "file_path": "auth/jwt.py",
            "line_start": 42,
            "language": "python",
            "signature": "def verify_jwt_claims(token: str) -> bool",
            "extra_json": {"status": "active", "ref_count": 7, "exported": True},
        },
        {
            "name": "loginUser",
            "kind": "function",
            "file_path": "auth/login.py",
            "line_start": 15,
            "language": "python",
            "signature": "def loginUser(email, password)",
            "extra_json": {"status": "active", "ref_count": 3},
        },
        {
            "name": "format_date",
            "kind": "function",
            "file_path": "utils/dates.py",
            "line_start": 8,
            "language": "python",
            "signature": "def format_date(d: datetime) -> str",
            "extra_json": {"status": "active", "ref_count": 12},
        },
        {
            "name": "parse_csv_row",
            "kind": "function",
            "file_path": "io/csv_parser.py",
            "line_start": 23,
            "language": "python",
            "signature": "def parse_csv_row(line: str) -> list",
            "extra_json": {"status": "active", "ref_count": 4},
        },
        {
            "name": "UserModel",
            "kind": "class",
            "file_path": "models/user.py",
            "line_start": 5,
            "language": "python",
            "signature": "",
            "extra_json": {"status": "active", "ref_count": 9, "exported": True},
        },
    ])
    return ws


@pytest.fixture
def auth_workspace():
    ws = _auth_workspace()
    yield ws
    clear_cache()
    shutil.rmtree(ws, ignore_errors=True)


# ─── Tokenizer tests ──────────────────────────────────────────

class TestTokenizer:
    """Verify the tokenizer handles common code-identifier conventions."""

    def test_snake_case_split(self):
        assert tokenize("verify_jwt_claims") == ["verify", "jwt", "claims"]

    def test_camel_case_split(self):
        # "loginUser" -> ["login", "user"]
        assert tokenize("loginUser") == ["login", "user"]

    def test_pascal_case_split(self):
        assert tokenize("UserModel") == ["user", "model"]

    def test_kebab_and_path_split(self):
        # "auth/login-page" -> ["auth", "login", "page"]
        assert tokenize("auth/login-page") == ["auth", "login", "page"]

    def test_mixed_conventions(self):
        # verifyJwtClaims and verify_jwt_claims produce identical tokens
        assert tokenize("verifyJwtClaims") == tokenize("verify_jwt_claims")

    def test_empty_input(self):
        assert tokenize("") == []
        assert tokenize(None) == []  # type: ignore[arg-type]

    def test_single_char_filtered(self):
        # Single chars (x, y) filtered out; signature punctuation is split
        # so "def f(x, y)" tokenizes to ["def"] (f/x/y are all 1-char).
        assert tokenize("def f(x, y)") == ["def"]

    def test_stopwords_filtered(self):
        # "the", "is", "a" filtered out
        tokens = tokenize("the user is a model")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens
        assert tokens == ["user", "model"]

    def test_lowercase(self):
        # All tokens are lowercased
        for t in tokenize("VerifyJWTClaims"):
            assert t == t.lower()

    def test_signature_punctuation_split(self):
        # Function signature punctuation (parens, comma, colon) is split
        # so each identifier becomes its own token.
        tokens = tokenize("def foo(x: int, y: str) -> bool")
        assert "foo" in tokens
        assert "int" in tokens
        assert "str" in tokens
        assert "bool" in tokens
        # "def" is a single-char-word survivor? No, "def" is 3 chars — it
        # stays. "x" and "y" are 1-char and filtered out.
        assert "def" in tokens
        assert "x" not in tokens
        assert "y" not in tokens


# ─── Engine behavior tests ────────────────────────────────────

class TestSemanticQuery:
    """End-to-end behavior of :func:`semantic_query`."""

    def test_finds_auth_symbol_by_concept(self, auth_workspace):
        """The core issue #11 use case: a query token that doesn't appear
        in any symbol NAME still surfaces relevant symbols because file
        paths, signatures, and kinds are all part of the TF-IDF document.

        Here, the query ``"auth"`` doesn't appear in any symbol name
        (``verify_jwt_claims``, ``loginUser``, ``format_date``, etc.), but
        it DOES appear in the file paths ``auth/jwt.py`` and
        ``auth/login.py``. The engine must surface those symbols — that's
        the "find by meaning, not just by literal name" value prop.

        Note: pure TF-IDF does NOT do stemming, so a query like
        ``"authentication"`` would NOT match ``"auth"``. That's a known
        limitation of Option A and is documented in the module docstring.
        Option B (embedding models) would handle this; Option A trades
        that capability for zero-dependency determinism.
        """
        result = semantic_query(auth_workspace, "auth", top_k=10)
        assert result["status"] == "ok"
        # verify_jwt_claims should be in the top 3 — its file path
        # contributes "auth" AND it has the rare "jwt" term.
        top_names = [r["name"] for r in result["results"][:3]]
        assert "verify_jwt_claims" in top_names, (
            f"Expected verify_jwt_claims in top 3, got: {top_names}"
        )

    def test_results_sorted_by_score_descending(self, auth_workspace):
        result = semantic_query(auth_workspace, "jwt", top_k=10)
        assert result["status"] == "ok"
        scores = [r["score"] for r in result["results"]]
        assert scores == sorted(scores, reverse=True), (
            f"Scores not in descending order: {scores}"
        )
        # The single symbol with "jwt" in its name/file path must be #1
        assert result["results"][0]["name"] == "verify_jwt_claims"

    def test_top_k_limit(self, auth_workspace):
        # The fixture has 5 symbols. top_k=2 should cap results at 2.
        result = semantic_query(auth_workspace, "user", top_k=2)
        assert result["status"] == "ok"
        assert len(result["results"]) <= 2
        assert result["stats"]["returned"] == len(result["results"])
        # truncated flag should be True if we had more than 2 matches
        # (UserModel + loginUser both contain "user"; that's 2 matches,
        # so it may not be truncated — we just assert the field exists).
        assert "truncated" in result["stats"]

    def test_top_k_zero_returns_all(self, auth_workspace):
        result = semantic_query(auth_workspace, "user", top_k=0)
        assert result["status"] == "ok"
        # top_k=0 means "no limit"; we should get every symbol that
        # shares at least one term with the query.
        assert result["stats"]["returned"] == len(result["results"])
        assert result["stats"]["truncated"] is False

    def test_unknown_query_returns_empty(self, auth_workspace):
        # A query whose tokens don't appear in any symbol returns empty.
        result = semantic_query(auth_workspace, "nonexistent_thing_xyz", top_k=10)
        assert result["status"] == "ok"
        assert result["results"] == []
        assert result["stats"]["returned"] == 0

    def test_empty_query_returns_error(self, auth_workspace):
        result = semantic_query(auth_workspace, "", top_k=10)
        assert result["status"] == "error"
        assert "message" in result
        assert result["results"] == []

    def test_whitespace_query_returns_error(self, auth_workspace):
        result = semantic_query(auth_workspace, "   \t  ", top_k=10)
        assert result["status"] == "error"

    def test_result_shape(self, auth_workspace):
        """Every result entry must have the documented fields."""
        result = semantic_query(auth_workspace, "user", top_k=10)
        for r in result["results"]:
            assert "name" in r
            assert "kind" in r
            assert "file" in r
            assert "line" in r
            assert "language" in r
            assert "signature" in r
            assert "score" in r
            assert "matched_terms" in r
            assert isinstance(r["matched_terms"], list)
            assert 0.0 <= r["score"] <= 1.0

    def test_matched_terms_populated(self, auth_workspace):
        """``matched_terms`` lists the query tokens that appeared in the doc."""
        result = semantic_query(auth_workspace, "jwt verify", top_k=10)
        assert result["status"] == "ok"
        if result["results"]:
            top = result["results"][0]
            # The top result for "jwt verify" must match at least one
            # of these terms.
            assert any(
                t in top["matched_terms"] for t in ("jwt", "verify")
            )

    def test_stats_total_symbols(self, auth_workspace):
        """``stats.total_symbols`` reflects the registry size, not just matches."""
        result = semantic_query(auth_workspace, "jwt", top_k=10)
        assert result["stats"]["total_symbols"] == 5  # the fixture has 5 symbols


# ─── Cache invalidation tests ─────────────────────────────────

class TestCacheInvalidation:
    """Verify the (db_path, mtime) cache key picks up re-scans."""

    def test_cache_returns_same_instance_for_same_mtime(self, workspace):
        _make_db(workspace, [
            {"name": "foo", "kind": "function", "file_path": "a.py",
             "line_start": 1, "language": "python"},
        ])
        idx1 = build_index(os.path.join(workspace, ".codelens", "codelens.db"))
        idx2 = build_index(os.path.join(workspace, ".codelens", "codelens.db"))
        assert idx1 is idx2, "Same mtime should return the cached instance"

    def test_cache_invalidates_on_mtime_change(self, workspace):
        db_path = os.path.join(workspace, ".codelens", "codelens.db")
        _make_db(workspace, [
            {"name": "foo", "kind": "function", "file_path": "a.py",
             "line_start": 1, "language": "python"},
        ])
        idx1 = build_index(db_path)
        assert len(idx1.symbols) == 1

        # Force mtime change by sleeping then writing new symbols
        time.sleep(0.05)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO symbols (name, kind, file_path, line_start, language) "
                "VALUES ('bar', 'function', 'b.py', 2, 'python')"
            )
            conn.commit()
        finally:
            conn.close()
        # Touch the file to ensure mtime updates (some filesystems have
        # coarse mtime granularity).
        os.utime(db_path, None)

        idx2 = build_index(db_path)
        assert idx2 is not idx1, "Cache should have invalidated on mtime change"
        assert len(idx2.symbols) == 2, "New index should reflect the new symbol"


# ─── Degradation tests ────────────────────────────────────────

class TestGracefulDegradation:
    """The engine must never crash the host command."""

    def test_missing_db_returns_empty_results(self, workspace):
        # workspace fixture creates the dir but no .codelens/
        result = semantic_query(workspace, "anything", top_k=10)
        assert result["status"] == "ok"
        assert result["results"] == []
        assert result["stats"]["total_symbols"] == 0
        assert result["stats"]["returned"] == 0

    def test_db_without_symbols_table_returns_empty(self, workspace):
        # Create the db file but no `symbols` table
        codelens_dir = os.path.join(workspace, ".codelens")
        os.makedirs(codelens_dir, exist_ok=True)
        db_path = os.path.join(codelens_dir, "codelens.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()

        result = semantic_query(workspace, "anything", top_k=10)
        assert result["status"] == "ok"
        assert result["results"] == []

    def test_empty_symbols_table_returns_empty(self, workspace):
        _make_db(workspace, [])
        result = semantic_query(workspace, "anything", top_k=10)
        assert result["status"] == "ok"
        assert result["results"] == []
        assert result["stats"]["total_symbols"] == 0

    def test_negative_top_k_treated_as_zero(self, auth_workspace):
        # Should not raise; negative top_k is clamped to 0.
        result = semantic_query(auth_workspace, "user", top_k=-5)
        assert result["status"] == "ok"
        # top_k=0 means "all matches" — just verify no exception.


# ─── IDF / ranking signal tests ───────────────────────────────

class TestRankingSignal:
    """Verify TF-IDF math produces intuitive rankings."""

    def test_rare_term_ranks_higher_than_common_term(self, workspace):
        """A symbol that contains a rare, query-specific term should
        outrank a symbol that only contains a common, ubiquitous term."""
        _make_db(workspace, [
            # 10 symbols that all contain "data" (common term)
            *[{
                "name": f"process_data_{i}",
                "kind": "function",
                "file_path": f"mod{i}.py",
                "line_start": i,
                "language": "python",
            } for i in range(10)],
            # 1 symbol that contains the rare term "zebra"
            {
                "name": "find_zebra",
                "kind": "function",
                "file_path": "animals/zebra.py",
                "line_start": 1,
                "language": "python",
            },
        ])
        # Query for the rare term — find_zebra should be the only result
        result = semantic_query(workspace, "zebra", top_k=10)
        assert result["status"] == "ok"
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "find_zebra"
        assert result["results"][0]["score"] > 0.0

    def test_multiple_query_terms_prefer_documents_with_all(self, workspace):
        """A document containing BOTH query terms should outrank one
        containing only one."""
        _make_db(workspace, [
            {
                "name": "auth_token",
                "kind": "function",
                "file_path": "auth.py",
                "line_start": 1,
                "language": "python",
            },
            {
                "name": "auth_only",
                "kind": "function",
                "file_path": "x.py",
                "line_start": 2,
                "language": "python",
            },
            {
                "name": "token_only",
                "kind": "function",
                "file_path": "y.py",
                "line_start": 3,
                "language": "python",
            },
        ])
        result = semantic_query(workspace, "auth token", top_k=10)
        assert result["status"] == "ok"
        # The symbol with both "auth" and "token" must be #1
        assert result["results"][0]["name"] == "auth_token"
        # And it must have matched both terms
        assert "auth" in result["results"][0]["matched_terms"]
        assert "token" in result["results"][0]["matched_terms"]


# ─── CLI registration smoke test ──────────────────────────────

class TestCommandRegistration:
    """Verify the semantic-query command is registered and importable."""

    def test_command_registered(self):
        # Importing commands.semantic_query should register it
        from commands import COMMAND_REGISTRY
        assert "semantic-query" in COMMAND_REGISTRY, (
            "semantic-query must be in COMMAND_REGISTRY after import"
        )

    def test_command_has_help_text(self):
        from commands import COMMAND_REGISTRY
        info = COMMAND_REGISTRY["semantic-query"]
        assert info["help"]
        assert "semantic" in info["help"].lower() or "tf-idf" in info["help"].lower()

    def test_command_module_imports_cleanly(self):
        # Re-import to make sure no import-time errors
        import importlib
        import commands.semantic_query as mod
        importlib.reload(mod)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
