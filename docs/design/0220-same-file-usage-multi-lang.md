# Design Doc: Same-File-Usage Tracking for Non-Python Languages (Issue #220)

> **Status:** Proposed
> **Date:** 2026-07-12
> **Author:** Wolfvin
> **Related issues:** #220
> **Related PRs:** (this PR)

---

## Problem

CodeLens `audit --check dead-code` was producing severe false positives for
non-Python languages. In a real Rust codebase (rekening-dev-mode, 109 .rs
files), 100 of 108 dead-code findings were `registry_dead` — a ratio too
extreme to be real.

Concrete example from the issue: `const RED: &str = ""` at
`regrets/verify.rs:22` was flagged as `registry_dead` ("zero references"),
but grep confirmed `RED` is used 10+ times in the same file (lines
78, 87, 101, 134, 164, 178, 186, 199, 343, ...).

Root cause: `scripts/deadcode_engine.py` has two dead-code detection paths
that need same-file-usage data:

1. `_detect_unused_exports()` — already checks `same_file_usages` (line ~1873)
   to exempt exports used within their own file. But only Python had a
   collector (`_collect_py_same_file_usages()`, line ~1004) that populated
   this dict. For the 14 other languages, `same_file_usages` was always
   empty, so any export not imported cross-file was flagged — even if used
   10+ times in its own file.

2. `_detect_dead_from_registry()` — reads `.codelens/backend.json` (populated
   by `scan`) and flags nodes with `ref_count == 0 && status == "dead"`.
   The `ref_count` is computed from CALLS edges, which only capture function
   calls — not const references, type usages, or macro invocations. A const
   used 10+ times in its own file has 0 CALLS edges (consts are "referenced",
   not "called"), so `ref_count == 0` and it's flagged. This path did NOT
   check `same_file_usages` at all.

## Goal

`audit --check dead-code` should not false-positive flag symbols that are
used within their own file, for the 7 most common non-Python languages
(Rust, Go, Java, PHP, Ruby, C, C++). Genuinely dead symbols (defined but
never referenced anywhere) should still be flagged.

## Changes

### Architecture / Data Model

Add `_collect_<lang>_same_file_usages()` collector functions for 7
languages, following the Python reference pattern but with a key
improvement: **occurrence counting**. Each collector uses `collections.Counter`
to count how many times each identifier appears in the file, and only adds
names with `count >= 2` to the usage set.

The `count >= 2` threshold is critical: a symbol's own definition (e.g.
`const RED` or `fn foo`) causes the name to appear at least once. Without
the threshold, every symbol would exempt itself and no dead code would
ever be flagged. With `count >= 2`, a symbol must appear in its definition
PLUS at least one actual usage to be exempted.

This differs from the Python collector, which uses a broad Set (count
includes definition). The Python collector works despite this because
Python's `unused_exports` check is about cross-file API — exempting
everything is acceptable for Python modules that are imported as a whole.
For non-Python languages and the `registry_dead` path, the `count >= 2`
threshold is necessary to preserve dead-code detection capability.

### Modified Files

- `scripts/deadcode_engine.py`:
  - Add 6 new collector functions: `_collect_rust_same_file_usages`,
    `_collect_go_same_file_usages`, `_collect_java_same_file_usages`,
    `_collect_php_same_file_usages`, `_collect_ruby_same_file_usages`,
    `_collect_c_same_file_usages` (handles both C and C++).
  - Add 6 language-specific keyword sets (`_RUST_KW`, `_GO_KW`, etc.)
    reused from `_collect_name_references()` to avoid exempting keywords.
  - Wire collectors into `detect_dead_code()` main loop at the same point
    as Python (line ~135).
  - Modify `_detect_dead_from_registry()` to accept `same_file_usages`
    parameter and exempt symbols that appear in their own file's usage set.
  - Add `Counter` import from `collections`.

- `tests/test_deadcode_engine.py`:
  - Add `TestIssue220SameFileUsageCollectors` — 7 tests (one per language)
    verifying each collector correctly distinguishes used (count>=2) from
    unused (count==1) symbols.
  - Add `TestIssue220DetectDeadFromRegistry` — 2 tests verifying
    `_detect_dead_from_registry()` exempts same-file usages and still flags
    genuinely dead symbols.

### Tests

- `tests/test_deadcode_engine.py::TestIssue220SameFileUsageCollectors` — 7
  tests, one per language (Rust, Go, Java, PHP, Ruby, C, C++). Each creates
  a fixture with a used const (10+ references) and a genuinely unused fn,
  then verifies the collector output set contains the used name but NOT the
  unused name.
- `tests/test_deadcode_engine.py::TestIssue220DetectDeadFromRegistry` — 2
  tests verifying the registry-dead path exempts same-file usages and still
  flags genuinely dead symbols.

## Trade-offs

### Alternative A: Broad Set (include definition name, like Python)

- **Pros:** Simpler code — no Counter needed, just a Set.
- **Cons:** Every symbol exempts itself (its definition name appears in the
  file). This would make `registry_dead` return 0 findings always — no dead
  code ever detected for non-Python languages. Unacceptable.
- **Why rejected:** Destroys dead-code detection capability.

### Alternative B: Strip definition lines before matching

- **Pros:** More precise — only counts actual usages, not definitions.
- **Cons:** Requires language-specific definition-line patterns for each of
  7 languages. Complex to maintain. Fragile — misses edge cases like
  multi-line definitions, attributes, etc.
- **Why rejected:** High complexity, high maintenance burden, fragile.

### Alternative C: Count occurrences (chosen approach)

- **Pros:** Simple — one regex (`\b\w+\b`) per language, plus a Counter.
  The `count >= 2` threshold naturally distinguishes definition-only
  (count==1) from definition+usage (count>=2). Works for all languages
  with minimal per-language customization (just keyword sets).
- **Cons:** Counts string/comment occurrences as "usages" (false negatives
  for genuinely dead symbols whose name appears in a comment). Acceptable
  per issue constraint: "False negative lebih baik daripada false positive".
- **Why chosen:** Best balance of simplicity, correctness, and
  maintainability. Follows the issue's design principle.

### Alternative D: Make Rust/Go parsers register const references as CALLS edges

- **Pros:** Fixes the root cause — `ref_count` would correctly reflect
  const references. No need for `same_file_usages` in `_detect_dead_from_registry`.
- **Cons:** Changes call-graph semantics — consts aren't "called", they're
  "referenced". Mixing CALLS edges with REFERENCES edges would break other
  consumers (trace, impact, dataflow). Huge blast radius across the codebase.
- **Why rejected:** Violates the issue constraint "Jangan ubah
  `_detect_unused_exports()` inti" (and by extension, the call-graph model).
  Out of scope for this issue.

## Open Questions

- [ ] Should the remaining 7 languages (Lua, Elixir, Nim, C#, Swift, Scala,
  Dart, Shell) get same-file-usage collectors too? The issue says they can
  follow in a separate PR. Owner: BOS, decide if follow-up issue is wanted.
- [ ] Should `_collect_py_same_file_usages()` be updated to use the
  `count >= 2` threshold for consistency? Currently Python uses a broad Set.
  This would be a behavior change for Python `unused_exports` — out of scope
  for this issue. Owner: BOS.

## Migration / Rollout

No migration impact — additive change. Existing dead-code findings will
decrease for non-Python languages (false positives removed). Genuinely dead
symbols remain flagged. This is a correctness improvement, not a breaking
change.

## References

- Issue: #220
- Prior art: `_collect_py_same_file_usages()` in `scripts/deadcode_engine.py`
  (line ~1004) — Python reference implementation.
- Related design docs: none
