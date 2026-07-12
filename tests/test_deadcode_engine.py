"""
Tests for the Dead Code Detection Engine.
"""

import os
import sys
import tempfile
import shutil
import pytest

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_DIR)

from deadcode_engine import detect_dead_code


class TestDeadCodeEngine:
    """Test dead code detection across categories."""

    def _create_workspace(self, code, filename="app.js"):
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, filename), 'w') as f:
            f.write(code)
        return ws

    def test_unreachable_code_after_return(self):
        """Code after a return statement should be detected as unreachable."""
        code = """
function process(data) {
    return data;
    console.log("unreachable");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                assert len(result["results"]["unreachable"]) > 0
                item = result["results"]["unreachable"][0]
                assert "file" in item
                assert "line" in item
                assert "after" in item
                assert item["after"] == "return"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_unused_variable_detection(self):
        """Variables declared but never used should be detected."""
        code = """
function test() {
    const unusedVar = 42;
    const usedVar = 10;
    return usedVar;
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unused_vars" in result["results"]:
                unused_names = [v["variable"] for v in result["results"]["unused_vars"]]
                assert "unusedVar" in unused_names
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_return_structure(self):
        """Verify the complete return structure of detect_dead_code."""
        code = "function test() { return true; }"
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            assert "workspace" in result
            assert "stats" in result
            assert "results" in result
            assert "categories_checked" in result
            # Stats sub-keys
            stats = result["stats"]
            assert "files_scanned" in stats
            assert "total_dead_code" in stats
            assert "by_category" in stats
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_categories_filter(self):
        """Filtering by categories should only check those categories."""
        code = """
function test() {
    return 1;
    console.log("dead");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws, categories=["unreachable"])
            assert result["status"] == "ok"
            assert "unreachable" in result["categories_checked"]
            # Other categories should not be checked
            assert "unused_vars" not in result["categories_checked"]
            assert "zombie_css" not in result["categories_checked"]
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_unused_variable(self):
        """Python variables assigned but never used should be detected."""
        code = """
def process():
    unused = 42
    used = 10
    return used
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unused_vars" in result["results"]:
                unused_names = [v["variable"] for v in result["results"]["unused_vars"]]
                assert "unused" in unused_names
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_python_unreachable_after_return(self):
        """Python code after return should be detected as unreachable."""
        code = """
def process():
    return True
    print("unreachable")
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                assert len(result["results"]["unreachable"]) > 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_clean_code_no_dead_code(self):
        """Clean code should have minimal or no dead code findings."""
        code = """
function add(a, b) { return a + b; }
function multiply(a, b) { return a * b; }
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            # Clean code should have zero or very few dead code items
            assert result["stats"]["total_dead_code"] <= 2
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_unreachable_after_throw(self):
        """Code after a throw statement should be detected as unreachable."""
        code = """
function fail() {
    throw new Error("fail");
    console.log("never reached");
}
"""
        ws = self._create_workspace(code)
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            if "unreachable" in result["results"]:
                items = result["results"]["unreachable"]
                assert any(item["after"] == "throw" for item in items)
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_empty_workspace(self):
        """Workspace with no source files should return zero dead code."""
        ws = tempfile.mkdtemp()
        with open(os.path.join(ws, "data.json"), 'w') as f:
            f.write("{}")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            assert result["stats"]["total_dead_code"] == 0
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    # ─── Issue #105 regression tests ────────────────────────────────
    # These patterns must NOT be flagged as unreachable. They are the
    # PEP 8-friendly early-return pattern that workers were previously
    # forced to wrap in `else:` to satisfy the scanner.

    def test_issue_105_early_return_then_final_return(self):
        """Early return inside `if` + final return after should NOT be flagged."""
        code = """def f(condition):
    if condition:
        return None
    return {"key": "value"}
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_multiline_return_after_early_return(self):
        """Multi-line dict return after early return should NOT be flagged.

        This is the exact reproduction of issue #105. Before the fix, the
        scanner reported line 5 (the dict body) as unreachable because the
        multi-line return detection skipped the `return {` line without
        resetting the terminal flag from the previous `return None` inside
        the `if` block.
        """
        code = """def _detect_vulns(workspace, max_items):
    from vulnscan_engine import scan_vulnerabilities
    vuln = scan_vulnerabilities(workspace)
    total = vuln.get("stats", {}).get("total_vulnerabilities", 0)
    if total == 0:
        return None
    return {
        "category": "vulnerabilities",
        "total": total,
        "top_items": vuln.get("vulnerabilities", [])[:max_items],
    }
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on multi-line dict return: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_chained_early_returns(self):
        """Multiple chained early returns + final return should NOT be flagged."""
        code = """def g(x):
    if x is None:
        return None
    if x < 0:
        return -1
    if x > 100:
        return 100
    return x
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on chained early returns: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_nested_if_early_return(self):
        """Nested if/return + outer returns should NOT be flagged."""
        code = """def m(x, y):
    if x:
        if y:
            return None
        return 1
    return 2
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) == 0, \
                f"False positive on nested if early return: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_issue_105_genuinely_unreachable_still_detected(self):
        """Sanity check: genuinely unreachable code after unconditional
        return must still be detected after the fix."""
        code = """def f():
    return None
    print("unreachable")
"""
        ws = self._create_workspace(code, "app.py")
        try:
            result = detect_dead_code(ws)
            assert result["status"] == "ok"
            unreachable = result.get("results", {}).get("unreachable", [])
            assert len(unreachable) >= 1, \
                f"Regression: genuinely unreachable code not detected: {unreachable}"
        finally:
            shutil.rmtree(ws, ignore_errors=True)



# ─── Issue #220: same-file-usage tracking for non-Python languages ──────────
# Before the fix, only Python had a _collect_<lang>_same_file_usages()
# collector. For the 14 other languages, same_file_usages was always empty,
# causing _detect_unused_exports() and _detect_dead_from_registry() to
# false-positive flag any symbol that was used only within its own file
# (never imported cross-file) as dead. The most impactful case: Rust
# consts (e.g. `const RED: &str = "..."` used 10+ times via
# `println!("{}", RED)`) appeared as `registry_dead` because consts are
# "referenced" not "called", so ref_count==0 even when heavily used.
#
# These tests verify the fix for 7 languages (Rust, Go, Java, PHP, Ruby,
# C, C++). Each collector test verifies:
#   1. A symbol used 2+ times IS in the usage set (exempted from dead flagging)
#   2. A symbol appearing only in its definition (count==1) is NOT in the set
#      (remains eligible for dead-code flagging)
from deadcode_engine import (
    _collect_rust_same_file_usages,
    _collect_go_same_file_usages,
    _collect_java_same_file_usages,
    _collect_php_same_file_usages,
    _collect_ruby_same_file_usages,
    _collect_c_same_file_usages,
    _detect_dead_from_registry,
)


class TestIssue220SameFileUsageCollectors:
    """Issue #220 regression tests: same-file-usage collectors for 7 languages.

    Each test verifies that the collector correctly distinguishes between:
    - A symbol used 2+ times in the file (definition + >=1 usage) -> IN the set
    - A symbol appearing only in its definition (count==1) -> NOT in the set

    This distinction is critical: without it, every symbol would exempt
    itself (because its definition name appears in the file), and no
    dead code would ever be flagged.
    """

    def test_rust_collector_exempts_used_consts_not_unused_fns(self):
        """Rust: const RED used 10+ times -> in set. fn unused (only def) -> NOT in set."""
        code = """const RED: &str = "\\x1b[31m";
const GREEN: &str = "\\x1b[32m";

fn print_red(msg: &str) {
    println!("{}{}", RED, msg);
}

fn verify_all() {
    print_red("error 1");
    print_red("error 2");
    let _ = (RED, GREEN, RED, GREEN, RED, GREEN);
}

fn genuinely_unused() -> i32 {
    42
}
"""
        usages = {}
        _collect_rust_same_file_usages(code, "verify.rs", usages)
        used = usages["verify.rs"]
        assert "RED" in used, f"RED should be in usage set (used 5+ times). got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "print_red" in used, f"print_red should be in usage set. got: {used}"
        assert "genuinely_unused" not in used, (
            f"genuinely_unused should NOT be in usage set (only appears in "
            f"definition, count==1). got: {used}"
        )

    def test_go_collector_exempts_used_consts_not_unused_fns(self):
        """Go: const used multiple times -> in set. Unused func -> NOT in set."""
        code = """package main

const RedColor = "\\x1b[31m"
const GreenColor = "\\x1b[32m"

func printRed(msg string) {
    println(RedColor, msg)
}

func verifyAll() {
    printRed("error 1")
    printRed("error 2")
    _ = []string{RedColor, GreenColor, RedColor, GreenColor}
}

func GenuinelyUnused() int {
    return 42
}
"""
        usages = {}
        _collect_go_same_file_usages(code, "main.go", usages)
        used = usages["main.go"]
        assert "RedColor" in used, f"RedColor should be in usage set. got: {used}"
        assert "GreenColor" in used, f"GreenColor should be in usage set. got: {used}"
        assert "printRed" in used, f"printRed should be in usage set. got: {used}"
        assert "GenuinelyUnused" not in used, (
            f"GenuinelyUnused should NOT be in usage set (only definition). got: {used}"
        )

    def test_java_collector_exempts_used_consts_not_unused_fns(self):
        """Java: static final used multiple times -> in set. Unused method -> NOT in set."""
        code = """public class Config {
    static final String RED = "\\x1b[31m";
    static final String GREEN = "\\x1b[32m";

    static void printRed(String msg) {
        System.out.println(RED + msg);
    }

    static void verifyAll() {
        printRed("error 1");
        printRed("error 2");
        String[] colors = {RED, GREEN, RED, GREEN, RED};
    }

    static int genuinelyUnused() {
        return 42;
    }
}
"""
        usages = {}
        _collect_java_same_file_usages(code, "Config.java", usages)
        used = usages["Config.java"]
        assert "RED" in used, f"RED should be in usage set. got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "printRed" in used, f"printRed should be in usage set. got: {used}"
        assert "genuinelyUnused" not in used, (
            f"genuinelyUnused should NOT be in usage set. got: {used}"
        )

    def test_php_collector_exempts_used_consts_not_unused_fns(self):
        """PHP: const used multiple times -> in set. Unused method -> NOT in set."""
        code = """<?php
class Colors {
    const RED = "\\x1b[31m";
    const GREEN = "\\x1b[32m";

    public static function printRed($msg) {
        echo self::RED . $msg;
    }

    public static function verifyAll() {
        self::printRed("error 1");
        self::printRed("error 2");
        $colors = array(self::RED, self::GREEN, self::RED, self::GREEN, self::RED);
    }

    public static function genuinelyUnused() {
        return 42;
    }
}
"""
        usages = {}
        _collect_php_same_file_usages(code, "Colors.php", usages)
        used = usages["Colors.php"]
        assert "RED" in used, f"RED should be in usage set. got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "printRed" in used, f"printRed should be in usage set. got: {used}"
        assert "genuinelyUnused" not in used, (
            f"genuinelyUnused should NOT be in usage set. got: {used}"
        )

    def test_ruby_collector_exempts_used_consts_not_unused_fns(self):
        """Ruby: const used multiple times -> in set. Unused method -> NOT in set."""
        code = """RED = "\\x1b[31m"
GREEN = "\\x1b[32m"

def print_red(msg)
  puts RED + msg
end

def verify_all
  print_red("error 1")
  print_red("error 2")
  colors = [RED, GREEN, RED, GREEN, RED]
end

def genuinely_unused
  42
end
"""
        usages = {}
        _collect_ruby_same_file_usages(code, "colors.rb", usages)
        used = usages["colors.rb"]
        assert "RED" in used, f"RED should be in usage set. got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "print_red" in used, f"print_red should be in usage set. got: {used}"
        assert "genuinely_unused" not in used, (
            f"genuinely_unused should NOT be in usage set. got: {used}"
        )

    def test_c_collector_exempts_used_consts_not_unused_fns(self):
        """C: #define const used multiple times -> in set. Unused fn -> NOT in set."""
        code = """#include <stdio.h>

#define RED "\\x1b[31m"
#define GREEN "\\x1b[32m"

void print_red(const char* msg) {
    printf("%s%s\\n", RED, msg);
}

void verify_all() {
    print_red("error 1");
    print_red("error 2");
    const char* colors[] = {RED, GREEN, RED, GREEN, RED};
}

int genuinely_unused() {
    return 42;
}
"""
        usages = {}
        _collect_c_same_file_usages(code, "colors.c", usages)
        used = usages["colors.c"]
        assert "RED" in used, f"RED should be in usage set. got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "print_red" in used, f"print_red should be in usage set. got: {used}"
        assert "genuinely_unused" not in used, (
            f"genuinely_unused should NOT be in usage set. got: {used}"
        )

    def test_cpp_collector_exempts_used_consts_not_unused_fns(self):
        """C++: constexpr const used multiple times -> in set. Unused fn -> NOT in set."""
        code = """#include <iostream>

constexpr const char* RED = "\\x1b[31m";
constexpr const char* GREEN = "\\x1b[32m";

void print_red(const char* msg) {
    std::cout << RED << msg << std::endl;
}

void verify_all() {
    print_red("error 1");
    print_red("error 2");
    const char* colors[] = {RED, GREEN, RED, GREEN, RED};
}

int genuinely_unused() {
    return 42;
}
"""
        usages = {}
        _collect_c_same_file_usages(code, "colors.cpp", usages)
        used = usages["colors.cpp"]
        assert "RED" in used, f"RED should be in usage set. got: {used}"
        assert "GREEN" in used, f"GREEN should be in usage set. got: {used}"
        assert "print_red" in used, f"print_red should be in usage set. got: {used}"
        assert "genuinely_unused" not in used, (
            f"genuinely_unused should NOT be in usage set. got: {used}"
        )


class TestIssue220DetectDeadFromRegistry:
    """Issue #220: verify _detect_dead_from_registry exempts same-file usages."""

    def test_registry_dead_exempts_same_file_usage(self):
        """A symbol with ref_count==0 and status==dead BUT used in its own
        file should NOT be flagged. A genuinely unused symbol (not in
        same_file_usages) SHOULD still be flagged.
        """
        import json
        ws = tempfile.mkdtemp()
        try:
            registry = {
                "nodes": [
                    {
                        "fn": "RED", "file": "verify.rs", "line": 4,
                        "ref_count": 0, "status": "dead", "type": "const",
                        "pub": False
                    },
                    {
                        "fn": "genuinely_unused", "file": "verify.rs", "line": 27,
                        "ref_count": 0, "status": "dead", "type": "function",
                        "pub": False
                    },
                ],
                "edges": []
            }
            codelens_dir = os.path.join(ws, ".codelens")
            os.makedirs(codelens_dir, exist_ok=True)
            with open(os.path.join(codelens_dir, "backend.json"), 'w') as f:
                json.dump(registry, f)

            same_file_usages = {
                "verify.rs": {"RED", "GREEN", "print_red"}
            }

            result = _detect_dead_from_registry(ws, same_file_usages)
            names = {item["name"] for item in result}

            assert "RED" not in names, (
                f"RED should be exempted (in same_file_usages) but was flagged. "
                f"Findings: {result}"
            )
            assert "genuinely_unused" in names, (
                f"genuinely_unused should be flagged (not in same_file_usages) "
                f"but was not. Findings: {result}"
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_registry_dead_without_same_file_usages_flags_everything(self):
        """Without same_file_usages (pre-fix behavior), all dead nodes are flagged."""
        import json
        ws = tempfile.mkdtemp()
        try:
            registry = {
                "nodes": [
                    {
                        "fn": "RED", "file": "verify.rs", "line": 4,
                        "ref_count": 0, "status": "dead", "type": "const",
                        "pub": False
                    },
                ],
                "edges": []
            }
            codelens_dir = os.path.join(ws, ".codelens")
            os.makedirs(codelens_dir, exist_ok=True)
            with open(os.path.join(codelens_dir, "backend.json"), 'w') as f:
                json.dump(registry, f)

            result = _detect_dead_from_registry(ws, None)
            names = {item["name"] for item in result}
            assert "RED" in names, (
                f"Without same_file_usages, RED should be flagged. Findings: {result}"
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)

    def test_registry_dead_exempts_rust_inline_test_functions(self):
        """Rust unit tests live inline as `#[cfg(test)] mod tests { #[test]
        fn ... }` in the same file as production code — unlike JS/Python
        where tests sit in a separate tests/ directory. A #[test]-attributed
        function has ref_count==0 by design (invoked by the test harness via
        attribute discovery, not a CALLS edge) and must not be flagged, nor
        should the `mod tests` module itself. A genuinely dead production
        function in the same file must still be flagged.
        """
        import json
        ws = tempfile.mkdtemp()
        try:
            rs_content = (
                "fn genuinely_unused_prod_fn() {}\n"
                "\n"
                "#[cfg(test)]\n"
                "mod tests {\n"
                "    use super::*;\n"
                "\n"
                "    #[test]\n"
                "    fn atomic_write_creates_file() {\n"
                "        assert!(true);\n"
                "    }\n"
                "\n"
                "    #[tokio::test]\n"
                "    async fn async_test_case() {\n"
                "        assert!(true);\n"
                "    }\n"
                "}\n"
            )
            with open(os.path.join(ws, "verify.rs"), 'w') as f:
                f.write(rs_content)

            registry = {
                "nodes": [
                    {
                        "fn": "genuinely_unused_prod_fn", "file": "verify.rs", "line": 1,
                        "ref_count": 0, "status": "dead", "type": "function", "pub": False
                    },
                    {
                        "fn": "tests", "file": "verify.rs", "line": 4,
                        "ref_count": 0, "status": "dead", "type": "module", "pub": False
                    },
                    {
                        "fn": "atomic_write_creates_file", "file": "verify.rs", "line": 8,
                        "ref_count": 0, "status": "dead", "type": "function", "pub": False
                    },
                    {
                        "fn": "async_test_case", "file": "verify.rs", "line": 13,
                        "ref_count": 0, "status": "dead", "type": "function", "pub": False
                    },
                ],
                "edges": []
            }
            codelens_dir = os.path.join(ws, ".codelens")
            os.makedirs(codelens_dir, exist_ok=True)
            with open(os.path.join(codelens_dir, "backend.json"), 'w') as f:
                json.dump(registry, f)

            result = _detect_dead_from_registry(ws, None)
            names = {item["name"] for item in result}

            assert "tests" not in names, f"mod tests must be exempted. Findings: {result}"
            assert "atomic_write_creates_file" not in names, (
                f"#[test] fn must be exempted. Findings: {result}"
            )
            assert "async_test_case" not in names, (
                f"#[tokio::test] fn must be exempted. Findings: {result}"
            )
            assert "genuinely_unused_prod_fn" in names, (
                f"Genuinely dead production fn must still be flagged. Findings: {result}"
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)
