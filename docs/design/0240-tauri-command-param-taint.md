# Design Doc: Rust `#[tauri::command]` parameter-to-sink taint (MVP)

> **Status:** Accepted (scope narrowed from original issue during design)
> **Date:** 2026-07-12
> **Author:** Claude (direct implementation, no worker — user directive)
> **Related issues:** #240

---

## Problem

`security --check taint` (`ast_taint_engine.get_supported_languages()`) only
covers Python/JS/TS/TSX — zero taint coverage for Rust. Verified on a real
Tauri workspace this session: genuine `Command::new(...)` sinks in `.rs`
files fed by `std::env::var()` sources, invisible to the taint scanner
entirely.

## Goal (narrowed from the original issue)

Issue #240 originally scoped this as full cross-language taint: track a
value from `invoke("cmd", {arg: userInput})` on the TypeScript side, across
the IPC boundary, into the matching `#[tauri::command] fn cmd(arg: ...)` on
the Rust side, to a dangerous sink inside that function.

**That full cross-language correlation is out of scope for this MVP** —
matching a TS `invoke()` call site to its Rust command implementation
requires resolving the string literal command name against the
`#[tauri::command]` function name across files/languages, which the current
parser/graph architecture doesn't do (graph edges are same-language call
edges, not cross-language string-literal-to-attribute correlations). Doing
that correctly is a separate, larger effort.

**What ships in this MVP instead**, and why it still delivers most of the
real-world value: every parameter of a `#[tauri::command]`-annotated Rust
function is, by construction, untrusted input from the frontend — Tauri's
own IPC dispatch is exactly how that data arrives. So the source doesn't
need to be traced from the TS side at all; **the `#[tauri::command]`
attribute itself marks the function's parameters as taint sources**. From
there it's an intra-procedural (single-file) taint problem — the same
class of analysis the existing Python/JS engine already does, just applied
to Rust with a smaller, hand-picked sink list.

This catches the exact pattern found on the real workspace this session
(env var / parameter flowing into `Command::new()`), without requiring
cross-language correlation.

## Changes

### Approach: regex-based, not full tree-sitter AST

Given the scope and time budget, this ships as a **regex-based pattern
matcher** (consistent with how several other CodeLens engines — e.g.
`regexaudit_engine.py` — already work), not a full tree-sitter AST walker
matching the precision of `ast_taint_engine.py`'s Python/JS engine. This is
an explicit, documented trade-off: fewer false negatives on obfuscated code
paths, more false positives possible on parameters that are actually
sanitized before reaching a sink in ways the regex can't see. Full
AST-based Rust taint (matching JS/Python precision) is future work, not
attempted here.

### Detection logic

1. Find every `#[tauri::command]` attribute immediately followed by `fn
   name(params...) ... { body }` (brace-matched to find the function body
   boundary).
2. Extract parameter names from the signature.
3. Within the function body, flag any line where a parameter name appears
   as a direct argument (or in a format!/concatenation immediately feeding)
   one of a small, high-confidence Rust sink list:
   - `Command::new(...)` / `.arg(...)` chains (command injection)
   - `std::fs::` path operations (`read`, `write`, `remove_file`,
     `create_dir`, ...) (path traversal)
   - `std::process::Command`
4. No sanitizer-detection in v1 (unlike the Python/JS engine's
   `PYTHON_SANITIZERS`/`JS_SANITIZERS`) — every match is reported as a
   finding for human/agent review, not auto-suppressed. Adding a
   Rust sanitizer allowlist is straightforward follow-up once this MVP is
   validated against real findings.

### New Files

- `scripts/rust_command_taint.py` — the regex-based detector described above.

### Modified Files

- `scripts/commands/security.py` (or wherever `--check taint` dispatches) —
  when scanning a workspace with `.rs` files, additionally run the new
  detector and merge findings into the same `taint` output shape
  (`by_rule`, `findings[]`) the Python/JS engine already produces.
- `docs/agent-usage-guide.md` — update the "no Rust taint" known limitation
  to describe the narrower actual gap (cross-language IPC correlation,
  not all Rust taint).

## Testing

Unit tests with synthetic `#[tauri::command]` functions (parameter reaching
a sink vs. not), plus verification against the real workspace pattern found
this session (`std::env::var()` → `Command::new()` inside a
`#[tauri::command]` function).

## Alternatives Considered

- **Full cross-language IPC correlation (the original issue scope).**
  Rejected for this MVP — requires new cross-file/cross-language graph
  edges the current architecture doesn't build; a legitimately separate,
  larger effort if pursued later.
- **Full tree-sitter AST-based Rust taint matching JS/Python precision.**
  Rejected for this MVP on time/scope grounds — regex-based detection with
  documented trade-offs ships real value now; upgrading to full AST
  precision is compatible future work that doesn't require redesigning the
  finding shape.
