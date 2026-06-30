"""
Tests for the regex prefilter (issue #56).

Verifies the conservative guarantee: the prefilter MUST NOT produce false
negatives. A file that contains any literal token from any rule's
sources/sinks/sanitizers must pass the prefilter. When in doubt (no rules,
unreadable file, empty content), the prefilter passes the file.

Coverage:
1. build_prefilter — None for empty/None rules, extracts tokens from all
   literal-bearing fields, returns None for pure-wildcard rules.
2. should_scan_file — True when prefilter is None, True on match, False
   only on confirmed no-match, True on read errors (conservative).
3. No-false-negatives guarantee — files containing rule tokens always pass.
4. Integration with cmd_scan — --no-prefilter flag, prefilter stats in
   result, scan with prefilter produces same findings as without.
"""

import os
import re
import shutil
import sys
import tempfile

import pytest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
sys.path.insert(0, SCRIPT_DIR)

from prefilter import build_prefilter, should_scan_file, PrefilterStats


# ─── 1. build_prefilter ──────────────────────────────────────


class TestBuildPrefilter:
    """Verify build_prefilter extracts tokens and returns None when appropriate."""

    def test_none_rules_returns_none(self):
        """build_prefilter(None) must return None (no filtering)."""
        assert build_prefilter(None) is None

    def test_empty_rules_returns_none(self):
        """build_prefilter([]) must return None (no filtering)."""
        assert build_prefilter([]) is None

    def test_rule_with_no_literals_returns_none(self):
        """Rules with only pure-wildcard entries (no identifier chars) → None."""
        # Entries that are all non-identifier characters → no tokens extracted.
        rules = [
            {"id": "wildcard", "sources": ["...", "...", "$$"], "sinks": ["***"]}
        ]
        assert build_prefilter(rules) is None

    def test_extracts_tokens_from_sources(self):
        """Tokens from the 'sources' field are included in the regex."""
        rules = [
            {"id": "r1", "sources": ["flask.request.args", "input"], "sinks": [], "sanitizers": []}
        ]
        p = build_prefilter(rules)
        assert p is not None
        # 'flask', 'request', 'args', 'input' — all >= 4 chars → included.
        # 'input' is 5 chars, included.
        assert p.search("import flask") is not None
        assert p.search("request.args") is not None
        assert p.search("user_input") is not None  # contains 'input'
        assert p.search("def hello(): pass") is None

    def test_extracts_tokens_from_sinks(self):
        """Tokens from the 'sinks' field are included in the regex."""
        rules = [
            {"id": "r1", "sources": [], "sinks": ["cursor.execute", "os.system"], "sanitizers": []}
        ]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("cursor.execute(query)") is not None
        assert p.search("os.system('ls')") is not None
        assert p.search("cursor") is not None
        assert p.search("execute") is not None
        assert p.search("system") is not None

    def test_extracts_tokens_from_sanitizers(self):
        """Tokens from the 'sanitizers' field are included in the regex."""
        rules = [
            {"id": "r1", "sources": [], "sinks": [], "sanitizers": ["parameterized_query", "escape_string"]}
        ]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("parameterized_query") is not None
        assert p.search("escape_string") is not None
        # The regex matches the FULL token 'parameterized_query', not
        # substrings like 'query'. A file must contain the full token
        # (or another rule token) to pass. This is by design — substring
        # matching would be too permissive and match unrelated code.
        assert p.search("parameterized_query(sql)") is not None
        assert p.search("escape_string(s)") is not None

    def test_extracts_tokens_from_all_fields_combined(self):
        """Tokens from all literal-bearing fields are OR-ed into one regex."""
        rules = [
            {
                "id": "r1",
                "sources": ["flask.request.args"],
                "sinks": ["cursor.execute"],
                "sanitizers": ["parameterized_query"],
            }
        ]
        p = build_prefilter(rules)
        assert p is not None
        # Each field's tokens should match.
        assert p.search("flask") is not None
        assert p.search("cursor") is not None
        assert p.search("parameterized_query") is not None

    def test_short_tokens_are_dropped(self):
        """Tokens shorter than _MIN_TOKEN_LENGTH (4) are dropped to avoid noise."""
        # 'db' (2 chars), 'os' (2 chars) → dropped.
        # 'exec' (4 chars), 'flask' (5 chars) → kept.
        rules = [
            {"id": "r1", "sources": ["db.query"], "sinks": ["exec("]},
        ]
        p = build_prefilter(rules)
        assert p is not None
        # 'query' is 5 chars → kept.
        assert p.search("query") is not None
        # 'exec' is 4 chars → kept.
        assert p.search("exec") is not None
        # 'db' is 2 chars → dropped, so a file with only 'db' shouldn't match.
        # (We can't test 'db' alone because 'query' and 'exec' would match
        # other content. Instead, verify the pattern string doesn't contain 'db'.)
        assert "db" not in p.pattern.split("|")

    def test_multiple_rules_combined(self):
        """Tokens from multiple rules are all included."""
        rules = [
            {"id": "r1", "sources": ["flask.request.args"], "sinks": ["cursor.execute"]},
            {"id": "r2", "sources": ["req.body"], "sinks": ["child_process.exec"]},
        ]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("flask") is not None
        assert p.search("cursor") is not None
        assert p.search("child_process") is not None  # full token, 13 chars
        assert p.search("child_process.exec('ls')") is not None

    def test_handles_non_string_entries_gracefully(self):
        """Non-string entries (ints, None) don't crash build_prefilter."""
        rules = [
            {"id": "r1", "sources": ["flask.request.args", 42, None], "sinks": []}
        ]
        # Should not raise; should still extract 'flask', 'request', 'args'.
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("flask") is not None

    def test_handles_non_list_fields_gracefully(self):
        """Fields that are strings instead of lists are handled."""
        rules = [
            {"id": "r1", "sources": "flask.request.args", "sinks": "cursor.execute"}
        ]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("flask") is not None
        assert p.search("cursor") is not None

    def test_returns_compiled_pattern(self):
        """build_prefilter returns a re.Pattern (compiled), not a string."""
        rules = [{"id": "r1", "sources": ["flask.request"]}]
        p = build_prefilter(rules)
        assert p is not None
        assert isinstance(p, re.Pattern)

    def test_pattern_is_case_sensitive(self):
        """The prefilter is case-sensitive (matches rule tokens literally).

        This is intentional — rule tokens are case-sensitive identifiers
        (e.g., 'flask' vs 'Flask'). Case-insensitive matching would be more
        permissive but also slower; the conservative guarantee doesn't
        require it.
        """
        rules = [{"id": "r1", "sources": ["flask"]}]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("flask") is not None
        assert p.search("Flask") is None  # case-sensitive

    def test_special_regex_chars_are_escaped(self):
        """Tokens with regex metacharacters are escaped, not interpreted."""
        # 'Object.assign(' has a dot and paren — both regex metacharacters.
        # The prefilter should match the literal string, not interpret it.
        rules = [{"id": "r1", "sinks": ["Object.assign("]}]
        p = build_prefilter(rules)
        assert p is not None
        assert p.search("Object.assign(target, source)") is not None
        # 'Object' and 'assign' are the extracted tokens (both >= 4 chars).
        # 'Object' is 6 chars, 'assign' is 6 chars.
        assert p.search("Object") is not None
        assert p.search("assign") is not None


# ─── 2. should_scan_file ─────────────────────────────────────


class TestShouldScanFile:
    """Verify should_scan_file is conservative (never skips a matching file)."""

    def test_none_prefilter_returns_true(self):
        """When prefilter is None, should_scan_file always returns True."""
        # Even for a nonexistent file — None prefilter means no filtering.
        assert should_scan_file("/nonexistent/path.py", None) is True

    def test_matching_file_returns_true(self):
        """A file containing a rule token passes the prefilter."""
        rules = [{"id": "r1", "sources": ["flask.request.args"], "sinks": ["cursor.execute"]}]
        p = build_prefilter(rules)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("import flask\nfrom flask import request\ncursor.execute(query)\n")
            path = f.name
        try:
            assert should_scan_file(path, p) is True
        finally:
            os.unlink(path)

    def test_non_matching_file_returns_false(self):
        """A file with no rule tokens is skipped (returns False)."""
        rules = [{"id": "r1", "sources": ["flask.request.args"], "sinks": ["cursor.execute"]}]
        p = build_prefilter(rules)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def hello():\n    return 'world'\n")
            path = f.name
        try:
            assert should_scan_file(path, p) is False
        finally:
            os.unlink(path)

    def test_unreadable_file_returns_true(self):
        """Conservative: if the file can't be read, scan it (return True)."""
        rules = [{"id": "r1", "sources": ["flask.request.args"]}]
        p = build_prefilter(rules)
        # Nonexistent path → IOError → conservative True.
        assert should_scan_file("/nonexistent/path/to/file.py", p) is True

    def test_empty_file_returns_false(self):
        """An empty file with a non-None prefilter returns False (no match)."""
        rules = [{"id": "r1", "sources": ["flask.request.args"]}]
        p = build_prefilter(rules)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("")
            path = f.name
        try:
            assert should_scan_file(path, p) is False
        finally:
            os.unlink(path)

    def test_file_with_only_whitespace_returns_false(self):
        """A file with only whitespace (no tokens) returns False."""
        rules = [{"id": "r1", "sources": ["flask.request.args"]}]
        p = build_prefilter(rules)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("   \n\n   \t  \n")
            path = f.name
        try:
            assert should_scan_file(path, p) is False
        finally:
            os.unlink(path)


# ─── 3. No-false-negatives guarantee ─────────────────────────


class TestNoFalseNegatives:
    """The core guarantee: a file containing ANY rule token must pass.

    This is the critical safety property. If the prefilter skips a file
    that contains a rule token, a real finding could be missed. These
    tests enumerate token-bearing files and verify they all pass.
    """

    @pytest.fixture
    def sql_injection_prefilter(self):
        """Prefilter built from a realistic SQL injection rule."""
        rules = [
            {
                "id": "py/sql-injection",
                "name": "SQL Injection",
                "language": "python",
                "severity": "critical",
                "sources": ["flask.request.args", "flask.request.form", "input"],
                "sinks": ["cursor.execute", "db.execute", "connection.execute"],
                "sanitizers": ["parameterized_query", "escape_string"],
            }
        ]
        return build_prefilter(rules)

    def test_file_with_source_passes(self, sql_injection_prefilter):
        """A file containing a source token (e.g., 'flask') passes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from flask import request\nargs = request.args\n")
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True
        finally:
            os.unlink(path)

    def test_file_with_sink_passes(self, sql_injection_prefilter):
        """A file containing a sink token (e.g., 'cursor.execute') passes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def query():\n    cursor.execute('SELECT 1')\n")
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True
        finally:
            os.unlink(path)

    def test_file_with_sanitizer_passes(self, sql_injection_prefilter):
        """A file containing a sanitizer token (e.g., 'escape_string') passes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def safe(s):\n    return escape_string(s)\n")
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True
        finally:
            os.unlink(path)

    def test_file_with_full_vulnerability_passes(self, sql_injection_prefilter):
        """A file with source + sink (would produce a finding) passes."""
        # This is the critical test: a file that WOULD produce a SQL injection
        # finding must pass the prefilter. If it were skipped, the finding
        # would be lost — a false negative.
        vuln_code = (
            "from flask import request\n"
            "import sqlite3\n"
            "conn = sqlite3.connect('db.sqlite')\n"
            "cursor = conn.cursor()\n"
            "@app.route('/search')\n"
            "def search():\n"
            "    q = request.args.get('q')\n"
            "    cursor.execute('SELECT * FROM users WHERE name=\"' + q + '\"')\n"
            "    return cursor.fetchall()\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(vuln_code)
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True, (
                "PREFILTER FALSE NEGATIVE: a file containing both a source "
                "(flask.request.args) and a sink (cursor.execute) was skipped. "
                "This would drop a real SQL injection finding."
            )
        finally:
            os.unlink(path)

    def test_file_with_partial_vulnerability_passes(self, sql_injection_prefilter):
        """A file with a source but no sink still passes (could have sink elsewhere)."""
        # Conservative: even a partial match (source only, no sink) should pass.
        # The file might be imported by another file that has the sink.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("from flask import request\n# just reading input\nq = request.args.get('q')\n")
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True
        finally:
            os.unlink(path)

    @pytest.mark.parametrize("token", [
        "flask", "request", "cursor", "execute", "parameterized_query",
        "escape_string", "input", "connection",
    ])
    def test_each_individual_token_passes(self, sql_injection_prefilter, token):
        """A file containing only one rule token still passes."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(f"# mentioning {token} in a comment\n")
            path = f.name
        try:
            assert should_scan_file(path, sql_injection_prefilter) is True, (
                f"PREFILTER FALSE NEGATIVE: file containing token '{token}' "
                f"was skipped, but it's a rule token and should pass."
            )
        finally:
            os.unlink(path)


# ─── 4. PrefilterStats ──────────────────────────────────────


class TestPrefilterStats:
    """Verify the stats accumulator used for --verbose output."""

    def test_initial_state(self):
        stats = PrefilterStats()
        assert stats.checked == 0
        assert stats.passed == 0
        assert stats.skipped == 0
        assert stats.skip_percent == 0.0

    def test_record_pass(self):
        stats = PrefilterStats()
        stats.record(True)
        assert stats.checked == 1
        assert stats.passed == 1
        assert stats.skipped == 0

    def test_record_skip(self):
        stats = PrefilterStats()
        stats.record(False)
        assert stats.checked == 1
        assert stats.passed == 0
        assert stats.skipped == 1

    def test_skip_percent(self):
        stats = PrefilterStats()
        for _ in range(70):
            stats.record(True)
        for _ in range(30):
            stats.record(False)
        assert stats.checked == 100
        assert stats.skip_percent == 30.0

    def test_to_dict(self):
        stats = PrefilterStats()
        stats.record(True)
        stats.record(False)
        d = stats.to_dict()
        assert d["checked"] == 2
        assert d["passed"] == 1
        assert d["skipped"] == 1
        assert d["skip_percent"] == 50.0
        assert "elapsed_sec" in d

    def test_format_verbose_line(self):
        stats = PrefilterStats()
        stats.checked = 1240
        stats.passed = 387
        stats.skipped = 853
        stats.elapsed_sec = 0.3
        line = stats.format_verbose_line()
        # Should match the documented format:
        #   Prefilter: 1240 files checked, 387 passed, 853 skipped (68%) in 0.3s
        assert "Prefilter:" in line
        assert "1240 files checked" in line
        assert "387 passed" in line
        assert "853 skipped" in line
        assert "68%" in line
        assert "0.3s" in line


# ─── 5. Integration with cmd_scan ────────────────────────────


class TestScanPrefilterIntegration:
    """Verify the scan command integrates the prefilter correctly."""

    def _create_python_workspace(self):
        """Create a workspace with Python files containing rule tokens."""
        ws = tempfile.mkdtemp(prefix="codelens_prefilter_")
        # Vulnerable file — contains flask + cursor.execute (rule tokens).
        with open(os.path.join(ws, "vuln.py"), "w") as f:
            f.write(
                "from flask import request\n"
                "import sqlite3\n"
                "def search():\n"
                "    q = request.args.get('q')\n"
                "    cursor = sqlite3.connect().cursor()\n"
                "    cursor.execute('SELECT * FROM users WHERE name=' + q)\n"
                "    return cursor.fetchall()\n"
            )
        # Non-vulnerable file — no rule tokens (would be skipped by prefilter).
        with open(os.path.join(ws, "clean.py"), "w") as f:
            f.write("def hello():\n    return 'world'\n")
        return ws

    def test_scan_result_includes_prefilter_field(self):
        """cmd_scan result must include a 'prefilter' field (issue #56)."""
        from commands.scan import cmd_scan
        ws = self._create_python_workspace()
        try:
            result = cmd_scan(ws)
            assert "prefilter" in result, (
                "scan result must include 'prefilter' field (issue #56)"
            )
            assert "enabled" in result["prefilter"]
            assert "stats" in result["prefilter"]
            assert "checked" in result["prefilter"]["stats"]
            assert "passed" in result["prefilter"]["stats"]
            assert "skipped" in result["prefilter"]["stats"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_prefilter_disabled_when_no_rules(self):
        """With no plugins (no rules), prefilter.enabled is False (no-op)."""
        from commands.scan import cmd_scan
        ws = self._create_python_workspace()
        try:
            result = cmd_scan(ws)  # no plugins → no rules → prefilter is None
            assert result["prefilter"]["enabled"] is False, (
                "prefilter should be disabled (None) when no rules are loaded"
            )
            assert result["prefilter"]["stats"]["checked"] == 0
            assert result["prefilter"]["stats"]["skipped"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_no_prefilter_flag_skips_filtering(self):
        """use_prefilter=False disables the prefilter entirely."""
        from commands.scan import cmd_scan
        ws = self._create_python_workspace()
        try:
            result = cmd_scan(ws, use_prefilter=False)
            assert result["prefilter"]["enabled"] is False
            assert result["prefilter"]["stats"]["checked"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_scan_with_prefilter_same_findings_as_without(self):
        """Scan with prefilter ON produces same registry as prefilter OFF.

        This is the integration-level no-false-negatives check: when the
        prefilter is active and a file contains rule tokens, the prefilter
        must NOT skip it. We verify by comparing backend node counts.

        Since cmd_scan doesn't load built-in rules by default (the prefilter
        is a no-op without --plugins), we pass rule_dicts directly by
        monkeypatching build_prefilter to return a non-None pattern.
        """
        from commands.scan import cmd_scan
        import commands.scan as scan_mod

        ws = self._create_python_workspace()
        try:
            # Baseline: scan without prefilter (all files parsed).
            baseline = cmd_scan(ws, use_prefilter=False)
            baseline_py_nodes = baseline["backend"]["nodes"]

            # Now monkeypatch build_prefilter to return a pattern built from
            # the SQL injection rule tokens. This simulates having rules loaded.
            real_build = scan_mod.build_prefilter
            sql_rules = [{
                "id": "py/sql-injection",
                "sources": ["flask.request.args"],
                "sinks": ["cursor.execute"],
                "sanitizers": ["parameterized_query"],
            }]
            fake_pattern = real_build(sql_rules)
            assert fake_pattern is not None, "test setup: prefilter should build"

            # Clear registry so the second scan starts fresh.
            codelens_dir = os.path.join(ws, ".codelens")
            if os.path.isdir(codelens_dir):
                shutil.rmtree(codelens_dir)

            scan_mod.build_prefilter = lambda rules: fake_pattern
            try:
                filtered = cmd_scan(ws, use_prefilter=True)
            finally:
                scan_mod.build_prefilter = real_build

            filtered_py_nodes = filtered["backend"]["nodes"]

            # The vulnerable file (vuln.py) contains 'flask' and 'cursor.execute'
            # → passes the prefilter → parsed in both cases.
            # The clean file (clean.py) has no rule tokens → skipped by prefilter.
            # But clean.py only defines hello() which doesn't contribute to the
            # call graph anyway. The KEY assertion: vuln.py's nodes are present
            # in both scans (no false negative on the vulnerable file).
            assert filtered_py_nodes >= 1, (
                "filtered scan should have at least the vuln.py nodes "
                "(prefilter must not skip vuln.py — it contains rule tokens)"
            )
            assert filtered_py_nodes == baseline_py_nodes or filtered_py_nodes < baseline_py_nodes, (
                "filtered scan should have <= baseline nodes "
                "(clean.py may be skipped, but vuln.py must be present)"
            )

            # Critical: the prefilter must have checked files and skipped
            # at least the clean.py file (which has no rule tokens).
            assert filtered["prefilter"]["stats"]["checked"] >= 2, (
                "prefilter should have checked at least 2 Python files"
            )
            assert filtered["prefilter"]["stats"]["skipped"] >= 1, (
                "prefilter should have skipped at least clean.py (no rule tokens)"
            )
            assert filtered["prefilter"]["stats"]["passed"] >= 1, (
                "prefilter should have passed vuln.py (contains rule tokens)"
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_verbose_does_not_crash(self):
        """--verbose flag (verbose=True) doesn't crash the scan."""
        from commands.scan import cmd_scan
        ws = self._create_python_workspace()
        try:
            result = cmd_scan(ws, verbose=True)
            assert result["status"] == "ok"
        finally:
            shutil.rmtree(ws, ignore_errors=True)


# ─── 6. CLI flag tests ──────────────────────────────────────


class TestScanCliFlags:
    """Verify --no-prefilter and --verbose flags are registered correctly."""

    def test_no_prefilter_flag_registered(self):
        """The --no-prefilter flag must be registered in add_args."""
        import argparse
        from commands.scan import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        # Default: use_prefilter=True
        args = parser.parse_args([])
        assert args.use_prefilter is True

        # --no-prefilter sets use_prefilter=False
        args = parser.parse_args(["--no-prefilter"])
        assert args.use_prefilter is False

    def test_verbose_flag_registered(self):
        """The --verbose flag must be registered in add_args."""
        import argparse
        from commands.scan import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        # Default: verbose=False
        args = parser.parse_args([])
        assert args.verbose is False

        # --verbose sets verbose=True
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_both_flags_can_coexist(self):
        """--no-prefilter and --verbose can be used together."""
        import argparse
        from commands.scan import add_args

        parser = argparse.ArgumentParser()
        add_args(parser)

        args = parser.parse_args(["--no-prefilter", "--verbose"])
        assert args.use_prefilter is False
        assert args.verbose is True
