---
name: codelens
description: >
  CodeLens v4 — Live Codebase Reference Intelligence (Tree-sitter).
  Activate BEFORE creating/editing/deleting HTML class/id, CSS selector, JSX className,
  or function in Rust/JS/TS/Python. Prevents collision, overwrite, and dead code.
---

# CodeLens v4 — Quick Reference for AI Agents

## 1. Activation Rules

MUST activate CodeLens when:
- **Writing code**: Any new class/id/className/function creation or modification
- **Querying codebase**: "does X exist", "who uses Y", "find references", "trace call chain"
- **Auditing**: Security, quality, dead code, accessibility, refactoring safety checks

## 2. Priority System

| Priority | Tools | Purpose |
|----------|-------|---------|
| **P0** | `init`, `scan`, `query`, `list`, `detect`, `dataflow`, `smell`, `secrets`, `entrypoints` | Must-run. Pre-write checks, critical analysis |
| **P1** | `search`, `symbols`, `trace`, `impact`, `side-effect`, `refactor-safe`, `dead-code`, `api-map`, `state-map`, `env-check` | Search, trace, impact — run on demand |
| **P2** | `outline`, `missing-refs`, `diff`, `circular`, `stack-trace`, `test-map`, `config-drift`, `debug-leak`, `complexity` | Deep analysis, structural inspection |
| **P3** | `context`, `dependents`, `validate`, `type-infer`, `ownership`, `regex-audit`, `a11y`, `watch` | Supplemental context, niche audits |

**Invocation:** `python3 "$CODELENS_DIR/scripts/codelens.py" <tool> <args> /path/to/workspace`

## 3. State Prerequisites

```
REQUIRED ORDER: init → scan → [any tool]
```
- `init workspace` — One-time. Auto-detects frameworks, creates config
- `scan workspace` — Builds registry. Use `--incremental` for changed files only
- `query "name" workspace` — Pre-write collision check (MOST IMPORTANT TOOL)
- After any code change → `scan --incremental` to update registry

## 4. Context-Aware Hints

- **No registry found** → Auto-run `init` + `scan` before any tool
- **Registry stale (>24h old)** → Re-run `scan --incremental` before queries
- **After file edits** → Always `scan --incremental` then `list --filter dead` + `list --filter collision`
- **First session in workspace** → `init` → `scan` → `detect` to bootstrap

## 5. Quick Trigger Map

| User Intent | Tool(s) |
|-------------|---------|
| Create class/id/function | `query` → write → `scan --incremental` |
| Edit existing symbol | `query` + `context` → edit → `scan --incremental` |
| Delete code | `impact --action delete` + `dead-code` → delete → `scan --incremental` |
| "does X exist?" | `query` |
| "who uses/calls this?" | `trace --direction up` |
| "what does this call?" | `trace --direction down` |
| "search pattern" | `search` or `symbols --fuzzy` |
| "explain this codebase" | `entrypoints` + `api-map` + `state-map` |
| "is this secure?" | `secrets` → `dataflow` → `env-check` → `regex-audit` |
| "production ready?" | `smell` → `complexity` → `debug-leak` → `dead-code` → `a11y` → `secrets` |
| "safe to rename?" | `refactor-safe` → `impact` → `test-map` |
| "what endpoints exist?" | `api-map` |
| "who manages this state?" | `state-map` |
| "dead code / unused" | `dead-code` + `list --filter dead` |
| "CSS mismatch HTML" | `missing-refs` |
| "circular dependency" | `circular` |
| "what's in this file?" | `outline --file path` |
| "who imports this file?" | `dependents path` |
| "env var audit" | `env-check` |
| "before deploy" | `secrets` → `debug-leak` → `env-check` → `config-drift` → `dead-code` |

## 6. Colloquial Triggers

Non-technical phrases that MUST activate CodeLens:

| Phrase | Tool(s) |
|--------|---------|
| "kok lama ya" / "why so slow" / "code berat" | `perf-hint` + `complexity` + `circular` |
| "bikin baru" / "buat class/function" | `query` (pre-write check) |
| "ubek-ubek" / "nyari di mana" / "where is it" | `search` + `symbols --fuzzy` |
| "bisa dihapus gak" / "safe to remove" | `impact --action delete` + `dead-code` |
| "gak jalan" / "bug" / "broken" | `search` → `context` → `trace --direction up` → `missing-refs` |
| "ribet banget" / "too complex" / "spaghetti" | `complexity` + `smell` + `circular` |
| "aman gak" / "secure?" | `secrets` + `dataflow` + `env-check` + `regex-audit` |
| "siapa yang buat" / "who touched this" | `ownership` |
| "udah ditest belum" / "is it tested" | `test-map` |
| "banyak yang duplicate" | `list --filter duplicate_define` + `dead-code` |
| "ready deploy?" / "production?" | `smell` + `complexity` + `debug-leak` + `secrets` |
| "rename boleh?" / "ganti nama" | `refactor-safe` + `impact` + `test-map` |

## 7. Negative Triggers

Do NOT activate CodeLens for:
- "buat PDF" / "generate image" / "create slide" → use pdf/image/ppt skills
- "search web" / "google" / "latest news" → use web-search skill
- "translate" / "write email" / "summarize article" → use LLM skill
- "install package" / "npm install" → direct bash
- "run server" / "start dev" → direct bash
- "explain concept" / "teach me X" → general LLM response
- Pure text generation with no codebase interaction

## 8. Default Fallback Chain

When user request is vague ("review", "cek kode", "check code"):

```
1. query (if specific name mentioned) OR scan (if no registry)
2. smell — overall health
3. complexity — find hotspots
4. dead-code — find removable code
5. Report summary with prioritized findings
```

For vague security concerns ("is this safe?"):
```
secrets → dataflow --source user_input → env-check → regex-audit
```

For vague quality concerns ("is this good?"):
```
smell → complexity → debug-leak → dead-code → a11y
```

## 9. Error Recovery

| Failure | Recovery Action |
|---------|----------------|
| `init` fails | Check `setup.sh` ran. Verify workspace path. Re-run `bash "$CODELENS_DIR/setup.sh"` |
| `scan` fails | Check file permissions. Try full scan (no `--incremental`). Delete `.codelens/` and re-init |
| `query` returns error | Registry may be stale → `validate` → if issues, `scan` full → retry query |
| `validate` shows drift | Re-run `scan` (full, not incremental) to rebuild registry |
| Tool not found | Verify `$CODELENS_DIR` env var. Check `scripts/codelens.py` exists |
| Timeout on scan | Reduce workspace scope. Check for huge minified files in `.codelensignore` |
| Empty results | Registry may be empty → `scan` first. Verify file extensions are supported |
| JSON parse error | Tool output format changed → re-run `scan` to regenerate registry |

## 10. Parallel Execution Hints

**CAN run in parallel** (no data dependency between them):
- `secrets` + `env-check` + `regex-audit` (independent security audits)
- `smell` + `complexity` + `debug-leak` (independent quality checks)
- `symbols` + `search` (read-only lookups)
- `a11y` + `missing-refs` (independent frontend checks)
- `entrypoints` + `api-map` + `state-map` (independent mapping tools)

**MUST run sequentially** (output feeds next input):
- `init` → `scan` → any other tool (registry must exist)
- `query` → decision → write → `scan --incremental` (pre-write flow)
- `refactor-safe` → `impact` → `test-map` (safety chain)
- `search` → `context` → `trace` (investigation chain)
- `detect` → framework-specific tool selection (e.g., `state-map` only if React detected)

## 11. Decision Rules

### Query Result → Action

| `query` Result | Status | AI Action |
|----------------|--------|-----------|
| `found: false` | — | **CREATE**: Safe to create new symbol |
| `found: true` | `active` | **EXTEND**: Do NOT overwrite. Extend existing implementation |
| `found: true` | `dead` | **ASK**: Symbol exists but unused. Ask user: reuse or delete? |
| `found: true` | `duplicate_ref` | **LIST**: Called from many places. Show all referrers before editing |
| `found: true` | `collision` | **STOP**: Active bug. Report to user. Fix before proceeding |

### Impact Result → Action

| `impact` Risk Level | AI Action |
|---------------------|-----------|
| `critical` | **STOP**. Do not change. Report to user |
| `high` | **WARNING**. List all affected files. Require explicit user confirmation |
| `medium` | **CAUTION**. Run tests after change. Verify nothing breaks |
| `low` | **SAFE**. Proceed with change |

### Refactor-Safe Result → Action

| Safety Level | AI Action |
|-------------|-----------|
| `dangerous` | **STOP**. Report all risks. Do not proceed |
| `risky` | **WARNING**. List string refs, dynamic access, eval refs |
| `cautious` | Proceed with manual review of flagged items |
| `mostly_safe` | Proceed. Minor edge cases to watch |
| `safe` | **PROCEED**. Automated rename/move is fine |
