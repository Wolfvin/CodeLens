"""
Tests for inline suppression detection and application.

Covers 12 languages × 3 cases each = 36 cases minimum, plus
additional tests for custom keywords, disable-suppression mode,
and count pipeline auditing (UBS bug #51 pattern).
"""

import os
import sys
import tempfile
import pytest

# Add scripts to path
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from suppression import (
    SuppressionInfo,
    detect_suppression,
    apply_suppressions,
    update_stats_with_suppressions,
    DEFAULT_KEYWORD_PATTERN,
    _detect_language_from_extension,
    _extract_comments_from_line,
)


# ═══════════════════════════════════════════════════════════════════════════
# Part 1: detect_suppression() unit tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDetectSuppression:
    """Tests for detect_suppression() function."""

    def test_basic_keyword(self):
        """codelens-ignore with no rules or reason."""
        result = detect_suppression("# codelens-ignore")
        assert result is not None
        assert result.rule_ids == []
        assert result.reason == ""
        assert result.is_next_line is False

    def test_with_rule_ids(self):
        """codelens-ignore with specific rule IDs."""
        result = detect_suppression("// codelens-ignore: rule-1, rule-2")
        assert result is not None
        assert result.rule_ids == ["rule-1", "rule-2"]
        assert result.reason == ""

    def test_with_reason(self):
        """codelens-ignore with reason."""
        result = detect_suppression("# codelens-ignore: rule-1 -- false positive")
        assert result is not None
        assert result.rule_ids == ["rule-1"]
        assert result.reason == "false positive"

    def test_with_rules_and_reason(self):
        """codelens-ignore with multiple rules and reason."""
        result = detect_suppression("// codelens-ignore: rule-a, rule-b -- known issue")
        assert result is not None
        assert result.rule_ids == ["rule-a", "rule-b"]
        assert result.reason == "known issue"

    def test_next_line(self):
        """codelens-ignore-next variant."""
        result = detect_suppression("// codelens-ignore-next: rule-1")
        assert result is not None
        assert result.is_next_line is True
        assert result.rule_ids == ["rule-1"]

    def test_nolens_alias(self):
        """nolens keyword alias."""
        result = detect_suppression("# nolens")
        assert result is not None
        assert result.keyword == "nolens"

    def test_nosemgrep_alias(self):
        """nosemgrep keyword alias."""
        result = detect_suppression("// nosemgrep: rule-1 -- semgrep compat")
        assert result is not None
        assert result.keyword == "nosemgrep"
        assert result.rule_ids == ["rule-1"]

    def test_no_keyword(self):
        """No suppression keyword present → None."""
        result = detect_suppression("# this is a regular comment")
        assert result is None

    def test_empty_string(self):
        """Empty string → None."""
        result = detect_suppression("")
        assert result is None

    def test_css_comment(self):
        """CSS-style comment with suppression."""
        result = detect_suppression("/* codelens-ignore: rule-1 */")
        assert result is not None
        assert result.rule_ids == ["rule-1"]

    def test_html_comment(self):
        """HTML-style comment with suppression."""
        result = detect_suppression("<!-- codelens-ignore -->")
        assert result is not None
        assert result.rule_ids == []

    def test_custom_keyword_pattern(self):
        """Custom keyword pattern."""
        result = detect_suppression(
            "# my-ignore: rule-1",
            keyword_pattern=r"my-ignore",
        )
        assert result is not None
        assert result.rule_ids == ["rule-1"]

    def test_case_insensitive(self):
        """Keyword matching is case-insensitive."""
        result = detect_suppression("# CODELENS-IGNORE: rule-1")
        assert result is not None
        assert result.rule_ids == ["rule-1"]


# ═══════════════════════════════════════════════════════════════════════════
# Part 2: Per-language suppression tests (12 languages × 3 cases = 36)
# ═══════════════════════════════════════════════════════════════════════════

def _make_finding(file_path: str, line: int, rule_id: str = "", category: str = "") -> dict:
    """Create a minimal finding dict for testing."""
    f = {"file": file_path, "line": line, "severity": "high", "message": "test finding"}
    if rule_id:
        f["rule_id"] = rule_id
    if category:
        f["category"] = category
    return f


class TestPythonSuppression:
    """Python: # codelens-ignore"""

    def test_suppress_all(self):
        code = "x = eval(input())  # codelens-ignore\n"
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific_rule(self):
        code = "x = eval(input())  # codelens-ignore: eval-injection -- safe in tests\n"
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True
        assert result[0]["suppressed_reason"] == "safe in tests"

    def test_next_line_suppression(self):
        code = "# codelens-ignore-next: eval-injection\nx = eval(input())\n"
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestJavaScriptSuppression:
    """JavaScript: // codelens-ignore"""

    def test_suppress_all(self):
        code = "eval(userInput);  // codelens-ignore\n"
        fp = "/tmp/test.js"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific_rule(self):
        code = "eval(userInput);  // codelens-ignore: eval-injection\n"
        fp = "/tmp/test.js"
        findings = [_make_finding(fp, 1, "other-rule")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False

    def test_next_line_suppression(self):
        code = "// codelens-ignore-next\neval(userInput);\n"
        fp = "/tmp/test.js"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestTypeScriptSuppression:
    """TypeScript: // codelens-ignore"""

    def test_suppress_all(self):
        code = "const x: any = eval(input);  // codelens-ignore\n"
        fp = "/tmp/test.ts"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_with_reason(self):
        code = "const x: any = eval(input);  // codelens-ignore: eval-injection -- test only\n"
        fp = "/tmp/test.ts"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True
        assert result[0]["suppressed_reason"] == "test only"

    def test_next_line_suppression(self):
        code = "// codelens-ignore-next: eval-injection\nconst x: any = eval(input);\n"
        fp = "/tmp/test.ts"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestRustSuppression:
    """Rust: // codelens-ignore"""

    def test_suppress_all(self):
        code = "unsafe { std::ptr::null_mut(); }  // codelens-ignore\n"
        fp = "/tmp/test.rs"
        findings = [_make_finding(fp, 1, "unsafe-block")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific_rule(self):
        code = "unsafe { std::ptr::null_mut(); }  // codelens-ignore: unsafe-block\n"
        fp = "/tmp/test.rs"
        findings = [_make_finding(fp, 1, "unsafe-block")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_no_suppression(self):
        code = "unsafe { std::ptr::null_mut(); }\n"
        fp = "/tmp/test.rs"
        findings = [_make_finding(fp, 1, "unsafe-block")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False


class TestGoSuppression:
    """Go: // codelens-ignore"""

    def test_suppress_all(self):
        code = 'fmt.Sprintf(userInput)  // codelens-ignore\n'
        fp = "/tmp/test.go"
        findings = [_make_finding(fp, 1, "fmt-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_next_line(self):
        code = '// codelens-ignore-next: fmt-injection\nfmt.Sprintf(userInput)\n'
        fp = "/tmp/test.go"
        findings = [_make_finding(fp, 2, "fmt-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_non_matching_rule(self):
        code = '// codelens-ignore: other-rule\nfmt.Sprintf(userInput)\n'
        fp = "/tmp/test.go"
        findings = [_make_finding(fp, 2, "fmt-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False


class TestJavaSuppression:
    """Java: // codelens-ignore"""

    def test_suppress_all(self):
        code = 'Runtime.exec(userInput);  // codelens-ignore\n'
        fp = "/tmp/test.java"
        findings = [_make_finding(fp, 1, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific(self):
        code = 'Runtime.exec(userInput);  // codelens-ignore: command-injection -- safe\n'
        fp = "/tmp/test.java"
        findings = [_make_finding(fp, 1, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True
        assert result[0]["suppressed_reason"] == "safe"

    def test_next_line(self):
        code = '// codelens-ignore-next\nRuntime.exec(userInput);\n'
        fp = "/tmp/test.java"
        findings = [_make_finding(fp, 2, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestCSuppression:
    """C: // codelens-ignore"""

    def test_suppress_all(self):
        code = 'strcpy(dst, userInput);  // codelens-ignore\n'
        fp = "/tmp/test.c"
        findings = [_make_finding(fp, 1, "buffer-overflow")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_block_comment(self):
        code = 'strcpy(dst, userInput);  /* codelens-ignore: buffer-overflow */\n'
        fp = "/tmp/test.c"
        findings = [_make_finding(fp, 1, "buffer-overflow")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_next_line(self):
        code = '// codelens-ignore-next: buffer-overflow\nstrcpy(dst, userInput);\n'
        fp = "/tmp/test.c"
        findings = [_make_finding(fp, 2, "buffer-overflow")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestCppSuppression:
    """C++: // codelens-ignore"""

    def test_suppress_all(self):
        code = 'system(userInput);  // codelens-ignore\n'
        fp = "/tmp/test.cpp"
        findings = [_make_finding(fp, 1, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_specific_rule(self):
        code = 'system(userInput);  // codelens-ignore: command-injection\n'
        fp = "/tmp/test.cpp"
        findings = [_make_finding(fp, 1, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_non_matching(self):
        code = 'system(userInput);  // codelens-ignore: other-rule\n'
        fp = "/tmp/test.cpp"
        findings = [_make_finding(fp, 1, "command-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False


class TestRubySuppression:
    """Ruby: # codelens-ignore"""

    def test_suppress_all(self):
        code = 'eval(user_input)  # codelens-ignore\n'
        fp = "/tmp/test.rb"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_specific_rule(self):
        code = 'eval(user_input)  # codelens-ignore: eval-injection -- safe\n'
        fp = "/tmp/test.rb"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True
        assert result[0]["suppressed_reason"] == "safe"

    def test_next_line(self):
        code = '# codelens-ignore-next: eval-injection\neval(user_input)\n'
        fp = "/tmp/test.rb"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestPHPSuppression:
    """PHP: # codelens-ignore or // codelens-ignore"""

    def test_hash_comment(self):
        code = '<?php eval($input);  # codelens-ignore\n'
        fp = "/tmp/test.php"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_slash_comment(self):
        code = '<?php eval($input);  // codelens-ignore: eval-injection\n'
        fp = "/tmp/test.php"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_block_comment(self):
        code = '<?php eval($input);  /* codelens-ignore */\n'
        fp = "/tmp/test.php"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestHTMLSuppression:
    """HTML: <!-- codelens-ignore -->"""

    def test_suppress_all(self):
        code = '<script>eval(userInput);</script>  <!-- codelens-ignore -->\n'
        fp = "/tmp/test.html"
        findings = [_make_finding(fp, 1, "xss")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific(self):
        code = '<script>eval(userInput);</script>  <!-- codelens-ignore: xss -->\n'
        fp = "/tmp/test.html"
        findings = [_make_finding(fp, 1, "xss")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_next_line(self):
        code = '<!-- codelens-ignore-next: xss -->\n<script>eval(userInput);</script>\n'
        fp = "/tmp/test.html"
        findings = [_make_finding(fp, 2, "xss")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestCSSSuppression:
    """CSS: /* codelens-ignore */"""

    def test_suppress_all(self):
        code = '.hidden { display: none; }  /* codelens-ignore */\n'
        fp = "/tmp/test.css"
        findings = [_make_finding(fp, 1, "display-none")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_suppress_specific(self):
        code = '.hidden { display: none; }  /* codelens-ignore: display-none */\n'
        fp = "/tmp/test.css"
        findings = [_make_finding(fp, 1, "display-none")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_next_line(self):
        code = '/* codelens-ignore-next: display-none */\n.hidden { display: none; }\n'
        fp = "/tmp/test.css"
        findings = [_make_finding(fp, 2, "display-none")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


# ═══════════════════════════════════════════════════════════════════════════
# Part 3: Multi-rule, custom keyword, disable-suppression mode
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiRuleSuppression:
    """Tests for multi-rule suppression on a single line."""

    def test_multi_rule_suppress_matching(self):
        code = 'x = eval(input)  # codelens-ignore: rule-a, rule-b, eval-injection\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_multi_rule_suppress_non_matching(self):
        code = 'x = eval(input)  # codelens-ignore: rule-a, rule-b\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False

    def test_suffix_match(self):
        """Rule ID suffix matching: 'long-function' matches 'codelens/smell/long-function'."""
        code = 'def very_long_function():  # codelens-ignore: long-function\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "codelens/smell/long-function")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True


class TestCustomKeyword:
    """Tests for custom keyword pattern."""

    def test_custom_keyword_suppress(self):
        code = 'eval(input)  # mycustom-ignore: eval-injection\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(
            findings, {fp: code},
            keyword_pattern=r"mycustom-ignore",
        )
        assert result[0]["suppressed"] is True

    def test_custom_keyword_not_default(self):
        """Default keyword should not match when custom is set."""
        code = 'eval(input)  # codelens-ignore\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        result = apply_suppressions(
            findings, {fp: code},
            keyword_pattern=r"mycustom-ignore",
        )
        assert result[0]["suppressed"] is False


class TestCountPipeline:
    """Tests for count pipeline — UBS bug #51 pattern audit."""

    def test_suppressed_count_in_stats(self):
        """Suppressed findings are counted as suppressed, not active."""
        code = 'eval(input)  # codelens-ignore\n'
        fp = "/tmp/test.py"
        findings = [
            _make_finding(fp, 1, "eval-injection"),
            _make_finding(fp, 2, "other-rule"),  # line 2 has no suppression
        ]
        apply_suppressions(findings, {fp: code})
        result = {"findings": findings, "stats": {"total_findings": 2}}
        update_stats_with_suppressions(result)
        assert result["stats"]["suppressed_count"] == 1
        assert result["stats"]["total_findings"] == 2  # Total includes suppressed

    def test_all_suppressed(self):
        """All findings suppressed — suppressed_count equals total."""
        code = 'eval(input)  # codelens-ignore\neval(input2)  # codelens-ignore\n'
        fp = "/tmp/test.py"
        findings = [
            _make_finding(fp, 1, "eval-injection"),
            _make_finding(fp, 2, "eval-injection"),
        ]
        apply_suppressions(findings, {fp: code})
        result = {"findings": findings, "stats": {"total_findings": 2}}
        update_stats_with_suppressions(result)
        assert result["stats"]["suppressed_count"] == 2

    def test_none_suppressed(self):
        """No findings suppressed — suppressed_count is 0."""
        code = 'eval(input)\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        apply_suppressions(findings, {fp: code})
        result = {"findings": findings, "stats": {"total_findings": 1}}
        update_stats_with_suppressions(result)
        assert result["stats"]["suppressed_count"] == 0

    def test_by_category_findings(self):
        """Findings in by_category dict are properly counted."""
        code = 'eval(input)  # codelens-ignore\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "eval-injection")]
        apply_suppressions(findings, {fp: code})
        result = {"by_category": {"security": findings}, "stats": {"total_findings": 1}}
        update_stats_with_suppressions(result)
        assert result["stats"]["suppressed_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# Part 4: Edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge case tests."""

    def test_finding_on_wrong_line_not_suppressed(self):
        """Suppression on line 1 does not affect finding on line 3."""
        code = 'eval(input)  # codelens-ignore\nx = 1\ny = 2\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 3, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False

    def test_multiple_findings_same_line(self):
        """Multiple findings on the same suppressed line are all suppressed."""
        code = 'eval(input)  # codelens-ignore\n'
        fp = "/tmp/test.py"
        findings = [
            _make_finding(fp, 1, "eval-injection"),
            _make_finding(fp, 1, "other-rule"),
        ]
        result = apply_suppressions(findings, {fp: code})
        assert all(f["suppressed"] for f in result)

    def test_suppression_in_string_not_detected(self):
        """Comment-like text inside a string is not a suppression."""
        code = 'x = "# codelens-ignore"\neval(input)\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False

    def test_nolens_next_line(self):
        """nolens-next variant works."""
        code = '# nolens-next: eval-injection\neval(input)\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 2, "eval-injection")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is True

    def test_language_detection(self):
        """Language detection from file extension."""
        assert _detect_language_from_extension("/tmp/test.py") == "python"
        assert _detect_language_from_extension("/tmp/test.js") == "javascript"
        assert _detect_language_from_extension("/tmp/test.rs") == "rust"
        assert _detect_language_from_extension("/tmp/test.go") == "go"
        assert _detect_language_from_extension("/tmp/test.java") == "java"
        assert _detect_language_from_extension("/tmp/test.cpp") == "cpp"
        assert _detect_language_from_extension("/tmp/test.css") == "css"
        assert _detect_language_from_extension("/tmp/test.html") == "html"
        assert _detect_language_from_extension("/tmp/test.rb") == "ruby"
        assert _detect_language_from_extension("/tmp/test.php") == "php"
        assert _detect_language_from_extension("/tmp/test.ts") == "typescript"
        assert _detect_language_from_extension("/tmp/test.c") == "c"

    def test_comment_extraction_python(self):
        """Python comment extraction."""
        comments = _extract_comments_from_line("x = 1  # codelens-ignore", "python")
        assert len(comments) >= 1
        assert "codelens-ignore" in comments[0]

    def test_comment_extraction_javascript(self):
        """JavaScript comment extraction."""
        comments = _extract_comments_from_line("x = 1;  // codelens-ignore", "javascript")
        assert len(comments) >= 1
        assert "codelens-ignore" in comments[0]

    def test_comment_extraction_css(self):
        """CSS comment extraction."""
        comments = _extract_comments_from_line("x { }  /* codelens-ignore */", "css")
        assert len(comments) >= 1
        assert "codelens-ignore" in comments[0]

    def test_no_suppression_fields_initialized(self):
        """Findings without suppression get default fields."""
        code = 'x = 1\n'
        fp = "/tmp/test.py"
        findings = [_make_finding(fp, 1, "some-rule")]
        result = apply_suppressions(findings, {fp: code})
        assert result[0]["suppressed"] is False
        assert result[0]["suppressed_rules"] == []
        assert result[0]["suppressed_reason"] == ""
