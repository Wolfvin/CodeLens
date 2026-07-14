# Agent Integration Guide — CodeLens

How to call CodeLens from an AI agent, harness, or service. For the **command
catalog and JSON output shapes**, see [SKILL.md](../SKILL.md) (full) and
[SKILL-QUICK.md](../SKILL-QUICK.md) (cheat sheet) — this guide covers the
*mechanics* of integration and deliberately does not duplicate the catalog, so
the two can't drift apart.

> **Command model (read first).** CodeLens has **12 umbrella commands**
> (`scan`, `search`, `context`, `deps`, `audit`, `security`, `summary`,
> `impact`, `api-map`, `doctor`, `history`, `graph`). Every legacy leaf command
> (`query`, `smell`, `dead-code`, `secrets`, `trace`, `circular`, `a11y`,
> `init`, `serve`, `watch`, `detect`, `refactor-safe`, …) is now either a
> `--check <sub-mode>` under an umbrella or has been removed. Invoking a dropped
> name gives argparse `invalid choice`. See the old→new map in SKILL.md.

---

## 1. Integration methods

| Method | When | Notes |
|---|---|---|
| **CLI subprocess** | Default for agents in any language | Stable JSON contract via `--format json`. Most robust. |
| **MCP server** | Agent host speaks MCP (Claude Desktop, Cursor, VS Code Copilot, Continue.dev, Cline) | 12 tools, one per umbrella, auto-discovered. Point the client at `scripts/mcp_server.py`; see [mcp_config.json](../mcp_config.json). There is no `codelens serve` — the client launches the server. |
| **Python direct import** | Same-process Python agent that wants dict results without a subprocess | Import from `scripts/`; call umbrella `execute(args, workspace)` or the `graph_model` API (see §7). Skips process overhead but couples you to internals. |

---

## 2. CLI subprocess integration

### 2.1 Basic pattern

```bash
codelens scan .                                   # build the graph once (auto-inits; no separate `init`)
codelens <umbrella> <workspace> --check <sub> --format json
```

`scan` must have run once for the workspace (it builds `.codelens/`). Any other
registry-consuming command auto-builds the graph on first use if it is missing
(capped at 3000 files on auto-setup — run `scan` manually on large repos for a
full graph).

### 2.2 Calling from agent code

**Python:**

```python
import json, subprocess

def codelens(*args, workspace="."):
    proc = subprocess.run(
        ["codelens", *args, "--format", "json"],
        cwd=workspace, capture_output=True, text=True,
        encoding="utf-8", errors="replace",   # required on Windows (cp1252 default)
        timeout=300,
    )
    # stdout is a single JSON document; warnings/logs go to stderr.
    return json.loads(proc.stdout)

dead    = codelens("audit", ".", "--check", "dead-code")
callers = codelens("context", ".", "--check", "trace", "--name", "handleAuth", "--direction", "up")
secrets = codelens("security", ".", "--check", "secrets")
```

**Node.js:**

```js
import { execFile } from "node:child_process";
import { promisify } from "node:util";
const run = promisify(execFile);

async function codelens(args, { cwd = "." } = {}) {
  const { stdout } = await run("codelens", [...args, "--format", "json"],
    { cwd, maxBuffer: 64 * 1024 * 1024, timeout: 300_000 });
  return JSON.parse(stdout);
}
```

### 2.3 Timeout guidance

| Operation | Suggested timeout |
|---|---|
| First `scan` (full graph build) | 300s (large repos: run once, out of band) |
| `scan --incremental` | 60s |
| Read/query commands (search, context, audit, security, …) | 60–120s |
| `security --check vuln-scan` (network to OSV) | 120s |

First scan is slow **by design** — it builds the SQLite graph. Subsequent scans
are incremental. "Slow first indexing" is expected, not a bug.

---

## 3. Output contract

- `--format json` — the stable machine contract. **stdout is one JSON document**;
  deprecation warnings and progress lines go to **stderr** — capture the two
  separately, or read stdout only.
- Umbrella commands return an envelope: `{"s": "ok", "st": {…}, "r": [ {…, "_check": name}, … ]}`
  (one entry in `r` per sub-check run). Single-purpose commands return their own
  top-level shape. Exact shapes: see [SKILL.md](../SKILL.md).
- Other formats: `--format compact` (single-char keys, ~50% smaller than json),
  `ai` (normalized `{stats, items[], truncated}`), `markdown`, `sarif`,
  `graphml`, plus `junit-xml`/`emacs`/`vim`/`gitlab-sast` for CI. Do **not** pass
  `-f` — the short flag is reserved to avoid an argparse conflict; use `--format`.

### Token control (for LLM consumption)

| Flag | Effect |
|---|---|
| `--lite` | Minimal, per-command-tailored output |
| `--max-tokens N` | Truncate to ~N tokens |
| `--top N` / `--limit N --offset N` | Keep/paginate list items (list-type results carry `total_count`/`count`/`offset`/`limit`/`has_more`) |
| `--detail minimal` | (summary) critical-severity only |
| `--format compact` | Single-char keys + abbreviated node/edge types (map in `scripts/formatters/compact.py`) |

---

## 4. Error handling & auto-recovery

| Symptom | Meaning | Recovery |
|---|---|---|
| `invalid choice: '<x>'` | Using a dropped/legacy top-level command | Map to the umbrella + `--check` (see SKILL.md) |
| Result `status: no_registry` / empty | No `.codelens/` graph yet | Run `codelens scan <workspace>`, retry |
| `context --check trace` returns 0 | Symbol name not found, or stale graph | `search --mode symbol` to find the exact name; `scan --incremental` if code changed |
| `security --check vuln-scan` empty | No lockfile present | Not an error — nothing to scan |
| `history --check ownership` degraded | No git repo | Falls back to mtime-based analysis |
| Non-zero exit from `check` (hidden CI gate) | Quality gate tripped on findings | Expected — inspect findings, not a crash |
| Corrupt `.codelens/` (`JSONDecodeError`) | Interrupted write | Delete `.codelens/`, re-`scan` |

**Recovery pattern:** on `no_registry`/empty → `scan` once, retry; on `invalid
choice` → translate the command, retry; a missing tree-sitter grammar degrades to
the regex parser automatically (no agent action needed).

---

## 5. Multi-agent & parallel use

- **Registry is read-shared.** Many agents can run read commands (search,
  context, audit, security, …) against the same `.codelens/` concurrently.
- **`scan` is the sole writer.** Serialize scans; never run two scans on one
  workspace at once. Run one `scan` up front, then fan out read commands.
- **Parallel-safe:** any mix of read-only sub-checks on a scanned workspace —
  e.g. `security --check secrets` ∥ `audit --check complexity` ∥ `deps --check
  circular`.
- **Sequential:** `scan` → (everything else); after code edits, `scan
  --incremental` before re-reading.

---

## 6. Edge cases

| Situation | Behaviour |
|---|---|
| Empty workspace | `scan` returns zeroed `files_scanned`; reads return empty, not errors |
| No git | History/ownership degrade to mtime; no crash |
| Monorepo (multiple package.json) | Scanned as one workspace; scope with `--diff-base <ref>` to a changed subset |
| TypeScript/TSX-only | Fully supported (tree-sitter TS/TSX). `.ts` routing follows the frontend/backend paths in `.codelens/codelens.config.json` |
| Large repo | First scan capped at 3000 files on auto-setup; run `scan` explicitly for the full graph |
| Incremental scan + empty graph | Incremental scans don't repopulate `graph_nodes`/`graph_edges` — run a full `scan` when structural graph queries return empty (issue #25) |

---

## 7. Python direct-import (in-process)

For same-process Python agents. Add `scripts/` to `sys.path`, then either call an
umbrella's `execute(args, workspace)` or query the graph directly.

### Graph API (structural traversal)

The graph tables (`graph_nodes` + `graph_edges`) live in
`.codelens/codelens.db`, rebuilt from `backend.json` on every full `scan`.
Prefer this over iterating the flat registry for callers/callees/cycles.

```python
import sys
sys.path.insert(0, "/path/to/codelens/scripts")
from graph_model import (
    find_nodes_by_name, query_callers, query_callees,
    graph_tables_populated, graph_stats, default_db_path,
)

db = default_db_path(workspace)                    # <workspace>/.codelens/codelens.db
if not graph_tables_populated(db):
    ...                                            # run a full scan first

nodes   = find_nodes_by_name("handleAuth", db)     # case-insensitive / fuzzy
callers = query_callers(nodes[0]["node_id"], db, max_depth=3)   # reverse BFS over CALLS
callees = query_callees(nodes[0]["node_id"], db, max_depth=3)   # forward BFS over CALLS
stats   = graph_stats(db)                          # node/edge counts + type distribution
```

Module-level callers use a synthetic id `"<file>:0:<module>"` — recognise them
with `graph_model.is_module_level_source_id()`.

### Reading registry files directly (no scan trigger)

```python
import json, os
def read_registry(workspace):
    d = os.path.join(workspace, ".codelens")
    out = {}
    for key, fn in (("frontend","frontend.json"), ("backend","backend.json"),
                    ("config","codelens.config.json")):
        p = os.path.join(d, fn)
        out[key] = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
    return out
```

`.codelens/` layout: `codelens.config.json` (config) · `frontend.json`
(classes+ids) · `backend.json` (nodes+edges) · `codelens.db` (SQLite:
symbols/refs/graph) · `mtimes.json` (incremental-scan cache).

---

## 8. Reading the output correctly

- `reference_count` / caller count is **popularity, not importance.** A function
  called once in a payment path can matter more than a util called 50×. Judge
  importance with `context --check trace --direction up` + the call context
  (auth, payment, entry point), cross-checked with `impact`.
- `status: dead` ≠ safe to delete. Entry points (HTTP handlers, CLI subcommands,
  exported API) often have no inbound edges yet are critical. `audit --check
  dead-code` annotates `deletion_safety` — trust that over raw edge counts.
