---
name: codelens
description: >
  CodeLens v6 Quick Reference — concise trigger map, core commands, and decision rules
  for AI agents. For complete documentation, see SKILL.md.
---

# CodeLens v6.0 — Quick Reference

**MUST activate before writing/editing/deleting any class, id, or function.**

## State Prerequisites

1. No `.codelens/` → auto-run `init` → `scan` first
2. Registry stale (>24h) → auto-run `scan --incremental`
3. After code changes → always `scan --incremental` before re-query

## Trigger Map — User Intent → Tool

### Core (P0 — Always Trigger)

| User Intent | Tool | Command |
|-------------|------|---------|
| **Analyze entire repo** | `analyze` | `codelens analyze ws` |
| Create new class/id/function | `query` | `codelens query "name" ws` |
| Edit existing code | `query` + `context` | Query first, then context |
| **Anti-overload summary** | `summary` | `codelens summary ws` |
| Quick overview | `summary --detail minimal` | `codelens summary --detail minimal ws` |
| Delete code | `impact` + `dead-code` | Impact check, then delete |
| "does this exist?" | `query` | `codelens query "name" ws` |
| "who calls this?" | `trace --direction up` | `codelens trace "name" ws` |
| Security audit | `secrets` → `dataflow` → `env-check` → `vuln-scan` | Full chain |
| Vulnerability scan | `vuln-scan` | `codelens vuln-scan ws` |

### Search & Understanding (P1)

| User Intent | Tool | Command |
|-------------|------|---------|
| Search pattern | `search` | `codelens search "pattern" ws` |
| Find symbol | `symbols` | `codelens symbols "name" ws` |
| Symbol detail | `context` | `codelens context "name" ws` |
| File structure | `outline` | `codelens outline ws --file path` |
| API routes | `api-map` | `codelens api-map ws` |
| Global state | `state-map` | `codelens state-map ws` |
| Performance issues | `perf-hint` | `codelens perf-hint ws` |

### Quality & Production (P1-P2)

| User Intent | Tool | Command |
|-------------|------|---------|
| "production ready?" | `smell` → `complexity` → `debug-leak` → `dead-code` → `a11y` → `secrets` | Quality gate |
| "what to refactor?" | `smell` | `codelens smell ws` |
| "too complex" | `complexity` | `codelens complexity ws` |
| "cleanup before deploy" | `debug-leak` | `codelens debug-leak ws` |
| "dead code?" | `dead-code` + `list --filter dead` | Full dead code |
| "accessible?" | `a11y` | `codelens a11y ws` |
| "CSS issues?" | `css-deep` | `codelens css-deep ws` |

### Refactoring (P1-P2)

| User Intent | Tool | Command |
|-------------|------|---------|
| "safe to rename?" | `refactor-safe` → `impact` → `test-map` | Full chain |
| "safe to delete?" | `impact` → `dead-code` | Impact then delete |
| "pure function?" | `side-effect` | `codelens side-effect ws` |
| "is it tested?" | `test-map` | `codelens test-map ws` |

## Query Decision Rules

| Query Result | Action |
|-------------|--------|
| `found: false` | SAFE — create new |
| `found: true` + `status: active` | EXTEND — don't overwrite |
| `found: true` + `status: dead` | ASK user — reuse or delete? |
| `found: true` + `status: duplicate_ref` | LIST all referrers first |
| `found: true` + `status: collision` | STOP — active bug, fix first |

## Negative Triggers — SKIP CodeLens

- Document generation (PDF, reports, docs)
- Image/media generation
- Web search queries
- Non-codebase knowledge questions
- Non-code file editing (config, markdown)

## Default Fallback Chains (Vague Requests)

| Pattern | Default Chain |
|---------|---------------|
| General "check/review" | `smell` → `dead-code` → `secrets` |
| "safe/secure?" | `secrets` → `dataflow` → `env-check` → `vuln-scan` |
| "good/clean/ready?" | `complexity` → `debug-leak` → `a11y` → `smell` |
| "slow/fast/optimize" | `perf-hint` → `complexity` → `circular` |
| "CSS/style/layout" | `css-deep` → `missing-refs` → `list --filter duplicate_define` |
| "deploy/ship/release" | `secrets` → `debug-leak` → `env-check` → `vuln-scan` → `dead-code` |

## Colloquial Triggers

| Phrase (EN/ID) | Tool Chain |
|-----------------|------------|
| "this is slow" / "kok lama ya" | `perf-hint` → `complexity` → `circular` |
| "something's weird" / "aneh nih" | `search` → `context` → `trace` → `missing-refs` |
| "help me check" / "bantu cek" | `smell` → `dead-code` → `secrets` |
| "clean up" / "bersihkan" | `debug-leak` → `dead-code` → `smell` |
| "is this safe?" / "aman ga" | `secrets` → `vuln-scan` → `debug-leak` → `env-check` |

## Workspace Auto-Detect (v5.1)

The `workspace` argument is now **optional** for ALL 41 commands.
If omitted, CodeLens auto-detects via:
1. Current directory (if has project markers: package.json, pyproject.toml, etc.)
2. Parent directories (walk up to find project root)
3. Source files in current directory
4. Last used workspace (cached at `~/.codelens/.codelens_last_workspace`)
5. Fallback: current working directory

```bash
$CLI scan              # Auto-detect → works!
$CLI query "myFunc"    # Auto-detect → works!
$CLI smell             # Auto-detect → works!
```

## All 45 Commands Quick Reference

| # | Command | Priority | One-liner |
|---|---------|----------|-----------|
| 1 | `analyze` | P0 | **Full repo analysis: init+scan+all engines in one command** |
| 2 | `init` | P0 | Initialize workspace |
| 3 | `scan` | P0 | Scan & build registry |
| 4 | `query` | P0 | Check if name exists |
| 5 | `list` | P3 | List with filter |
| 6 | `detect` | P3 | Detect frameworks |
| 7 | `watch` | P3 | File watcher |
| 8 | `handbook` | P0 | Project handbook for AI agents |
| 9 | `ask` | P1 | Natural language query router |
| 10 | `search` | P1 | Regex search |
| 11 | `symbols` | P1 | Registry symbol search |
| 12 | `trace` | P1 | Call chain trace |
| 13 | `impact` | P1 | Change impact analysis |
| 14 | `outline` | P2 | File structure outline |
| 15 | `missing-refs` | P2 | CSS/HTML mismatch |
| 16 | `diff` | P2 | Registry diff |
| 17 | `circular` | P2 | Circular dependency |
| 18 | `context` | P1 | Rich symbol context (+quality) |
| 19 | `dependents` | P2 | Module import tracking |
| 20 | `validate` | P3 | Registry sanity check |
| 21 | `dataflow` | P0 | Source→sink analysis |
| 22 | `smell` | P0 | Code smell detection |
| 23 | `side-effect` | P1 | Pure vs impure |
| 24 | `refactor-safe` | P1 | Rename/move safety |
| 25 | `dead-code` | P1 | Enhanced dead code |
| 26 | `stack-trace` | P2 | Error propagation |
| 27 | `test-map` | P2 | Test coverage |
| 28 | `config-drift` | P2 | Dependency drift |
| 29 | `type-infer` | P3 | Type inference |
| 30 | `ownership` | P3 | Code ownership |
| 31 | `secrets` | P0 | Hardcoded secret scan |
| 32 | `entrypoints` | P0 | Entry point mapping |
| 33 | `api-map` | P1 | Route→handler mapping |
| 34 | `state-map` | P1 | State management |
| 35 | `env-check` | P1 | Environment audit |
| 36 | `debug-leak` | P2 | Debug code detection |
| 37 | `complexity` | P2 | Complexity scoring |
| 38 | `regex-audit` | P3 | Regex safety audit |
| 39 | `a11y` | P3 | Accessibility audit |
| 40 | `vuln-scan` | P0 | CVE vulnerability scan |
| 41 | `perf-hint` | P1 | Performance hints |
| 42 | `css-deep` | P2 | Deep CSS analysis |
| 43 | `summary` | P0 | **Anti-overload condensed view** |
| 44 | `binary-scan` | P1 | **Binary/Tauri/Electron RE analysis** |
| 45 | `artifact-scan` | P1 | **Compiled artifact reverse engineering** |

## CLI Usage Pattern

```bash
CODELENS_DIR="{project_path}/skills/codelens"
CLI="python3 $CODELENS_DIR/scripts/codelens.py"

# Workspace is AUTO-DETECTED if omitted (NEW in v5.1)
# Fallback: cwd → parent dirs → last workspace → cwd

# ═══ ONE-SHOT FULL ANALYSIS (NEW v6.0) ═══
$CLI analyze /path/to/repo              # Everything in one command
$CLI analyze /path/to/repo --focus security  # Security-focused only
$CLI analyze /path/to/repo --detail full     # All findings, no filtering

# Setup (manual, if not using analyze)
$CLI init
$CLI scan

# Pre-write check (MOST IMPORTANT)
$CLI query "newName"

# With explicit workspace
$CLI init /workspace
$CLI scan /workspace

# Post-write update
$CLI scan --incremental

# Analysis
$CLI smell
$CLI secrets
$CLI vuln-scan
$CLI perf-hint
$CLI css-deep

# Agent-first commands
$CLI analyze /repo         # One-shot full repo analysis (NEW v6.0)
$CLI handbook              # One-shot project orientation
$CLI ask "dead code?"      # Natural language query
$CLI context "fn" -f markdown  # Markdown output
```
