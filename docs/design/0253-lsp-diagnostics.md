# Design Doc: Surface LSP diagnostics as `context --check diagnostics`

> **Status:** Accepted
> **Date:** 2026-07-13
> **Author:** Claude (direct implementation, no worker — user directive)
> **Related issues:** #253
> **Related PRs:** (this PR)

---

## Problem

Gap-analysis vs Serena MCP: Serena surfaces "contextual diagnostics" —
language-server lint/errors/warnings per file/symbol — so an agent can find
and fix bugs without shelling out to a linter manually. CodeLens had all the
LSP plumbing (`lsp_client.py` even registered the `publishDiagnostics`
client capability at init, `lsp_client.py:256`) but never exposed the
diagnostics: the LSP client only issued `textDocument/definition`,
`references`, and `hover` requests, and `hybrid_engine.py` used LSP purely
to *verify* its own dead-code/reference findings. An agent asking "what
does the type-checker think is wrong in this file?" had no CodeLens answer.

## Goal

`codelens context --check diagnostics --file <path>` returns the language
server's diagnostics for that file (severity, 1-indexed line, message,
source, code), degrading gracefully to an empty result when no server is
installed.

## Changes

### New Files
- `scripts/commands/diagnostics.py` — the command. Enables LSP internally
  (diagnostics have no non-LSP fallback), transforms raw LSP diagnostics to
  the finding shape (severity 1..4 → error/warning/info/hint, 0→1-indexed
  lines), and returns `lsp_available: false` + a note when no server is
  present.

### Modified Files
- `scripts/lsp_client.py`:
  - New `LSPClient.get_diagnostics(file_path, wait_timeout)` — opens the
    file, polls `_notification_list` (which the reader loop already fills)
    for a matching `textDocument/publishDiagnostics` notification, returns
    the latest one's diagnostics. Deliberately does NOT drop
    already-collected diagnostics first: many servers only push on *change*,
    not re-open, so dropping-and-waiting would return empty for a file
    already analyzed this session.
  - Reader loop now appends notifications under `self._lock` (previously
    unlocked) so the new diagnostics reader can't race a mutation
    mid-iteration.
- `scripts/hybrid_engine.py` — `HybridEngine.get_diagnostics()` delegates to
  the per-file LSP client; returns `None` (vs `[]`) when LSP isn't active so
  the caller can distinguish "no LSP" from "LSP ran, found nothing".
- `scripts/commands/context.py` — registered `diagnostics` in `_CHECKS`,
  added `--timeout` arg + namespace branch, updated epilog.
- `tests/test_command_registry.py` — `diagnostics` added to the
  implementation-module allowlist (imported by context, not self-registering).

### Placement rationale
`context --check diagnostics` (not a new top-level command — count stays
12). `context` is "codebase & symbol context"; per-file diagnostics is
contextual info about code, alongside outline/trace, and `context` already
carries a `--file` arg. It is opt-in (`context .` default is orient only),
so it never runs unrequested — appropriate since it needs `--file` and spins
up a language server.

## Testing

`tests/test_diagnostics_command.py` (8 tests): notification-filtering (URI
match, other-file ignored, latest-wins, not-initialized), and command
transformation + graceful degradation (missing --file, file not found, LSP
unavailable, raw→finding severity/line mapping).

**End-to-end limitation (honest):** a live end-to-end test through a real
language server could not be run in the dev environment — rust-analyzer (the
only installed server) does not respond to `initialize` within 60s on this
machine (a pre-existing rust-analyzer startup issue; the `initialize()`
method is untouched by this change). The graceful-degradation path *was*
verified end-to-end via the real CLI (`.ts` file, no typescript-language-
server installed → `lsp_available: false` + note, valid JSON, no hang, exit
0). The happy path is covered by the mocked unit tests, exercising the exact
`_notification_list` capture the other LSP features already use in
production.

## Alternatives Considered

- **Place under `doctor --check diagnostics`.** Rejected — doctor is
  environment audit (is LSP installed, deps OK); per-file code diagnostics
  is about the *code*, not the environment.
- **Place under `audit --check diagnostics`.** Reasonable (audit = find
  problems) but audit's default runs all checks workspace-wide; a
  `--file`-requiring, LSP-spinning check fits awkwardly there. `context`
  (per-file, opt-in) is cleaner.
- **Require `--deep` like other LSP features.** Rejected — diagnostics have
  no non-LSP fallback at all, so requiring the flag only adds friction;
  enabling LSP internally and degrading gracefully is more useful.
