# Design Doc 0002: MCP Server

> **Status:** Accepted
> **Date:** 2026-06-10 (retroactive — backfilled 2026-07-02)
> **Author:** Wolfvin
> **Related issues:** #17 (compact format), #59 (graphml format)
> **Related PRs:** original implementation, #139 (formatters), #153 (graphml)

---

## Problem

AI agents (Claude Code, Cursor, Continue.dev, Cline, VS Code Copilot) need
to query code intelligence without spawning a new process for every command.
The CLI-only model had three problems:

1. **Cold-start latency** — each `python3 codelens.py query ...` invocation
   took 200-500ms just to import modules and load the registry. An agent
   doing 20 queries paid 4-10s in pure overhead.
2. **No persistent state** — every CLI invocation re-loaded the registry
   from disk. For a 30k-node codebase, that's ~1.5s per invocation.
3. **No standard protocol** — agents had to parse CLI stdout (JSON) and
   construct shell commands, which is fragile and token-expensive.

## Goal

Provide a persistent server mode that:
- Speaks a standard protocol (MCP — Model Context Protocol) so any
  MCP-compatible agent can connect without CodeLens-specific glue code
- Keeps the registry in memory after initial scan → sub-millisecond query
  latency for subsequent calls
- Auto-discovers all CodeLens commands and exposes them as MCP tools — no
  manual tool registration when a new command is added
- Supports background file watching so the registry stays fresh without
  manual `scan` calls

## Changes

### Architecture

```
Agent (Claude/Cursor/etc.)
    │ JSON-RPC 2.0 over stdio
    ▼
CodeLens MCP Server (single long-running process)
    │
    ├── In-memory registry cache (loaded once on init)
    ├── Tool registry (auto-discovered from COMMAND_REGISTRY)
    ├── File watcher (optional, --watch flag)
    └── Format dispatcher (ai / compact / json / markdown / sarif / graphml)
```

### New Files

- `scripts/mcp_server.py` — the server (~2700 lines), implements:
  - JSON-RPC 2.0 over stdio
  - MCP `initialize` handshake with server capabilities
  - `tools/list` — returns all CodeLens commands as MCP tools
  - `tools/call` — executes a command and returns formatted result
  - `resources/list` — exposes codebase registry as resources
- `scripts/commands/serve.py` — CLI command that starts the server

### Protocol Details

- **Transport:** stdio (JSON-RPC 2.0); optional HTTP/SSE via `--port`
- **Default format:** `ai` (normalized schema: `{status, stats, items, truncated, recommendations, metadata}`)
- **Token-efficient format:** `compact` (single-char keys, ~50% smaller than `json`)
- **Tool naming:** `codelens_<command>` (e.g., `codelens_query`, `codelens_taint`)
- **Tool count:** 68 tools (50 statically-defined + 14 dynamically-discovered;
  `watch` and `serve` excluded because they're long-running)

### Format Enum

Every tool accepts a `format` parameter with the enum:
`[json, markdown, ai, sarif, compact, graphml]`

- `ai` (default) — normalized schema for agent consumption
- `compact` — token-efficient single-char keys (issue #17)
- `graphml` — GraphML XML for graph-producing commands (issue #59 Phase 3)
- `json`/`markdown`/`sarif` — legacy verbose forms

### Auto-Discovery

New CLI commands auto-appear as MCP tools — no manual registration. The
server's `_handle_tools_list` iterates `COMMAND_REGISTRY` at request time
and infers a JSON Schema from each command's argparse definition. This
means adding a new command (e.g., `commands/yourfeature.py`) immediately
makes `codelens_yourfeature` available to every connected agent.

## Trade-offs

### Alternative A: HTTP REST API

- **Pros:** Language-agnostic, curl-testable, standard tooling
- **Cons:** Agents need to manage a server lifecycle (start/stop/port),
  no standard schema for "what tools exist", every agent writes custom glue
- **Why rejected:** MCP is becoming the standard for agent-tool integration.
  Building a custom REST API would mean every agent needs CodeLens-specific
  integration code, defeating the "standard protocol" goal.

### Alternative B: gRPC

- **Pros:** Strongly-typed, binary protocol, bidirectional streaming
- **Cons:** Heavy dependency (protobuf compiler), overkill for the request/
  response pattern of code queries, no agent ecosystem support
- **Why rejected:** Over-engineering. The payload is JSON-shaped anyway
  (command results are dicts); gRPC adds complexity without benefit.

### Alternative C: CLI-only with shell wrapper

- **Pros:** No server lifecycle to manage, simplest implementation
- **Cons:** Cold-start latency per invocation, no persistent state, agents
  must parse stdout
- **Why rejected:** This is the status quo ante. The 200-500ms cold start
  per query is unacceptable for interactive agent workflows.

### Chosen approach: MCP over stdio

- **Why:** Standard protocol (any MCP-compatible agent connects without
  CodeLens-specific code), persistent process (no cold start), stdio
  transport (no port management, works in sandboxed environments). The
  optional `--port` flag adds HTTP/SSE for non-stdio consumers.

## Open Questions

- [x] Q1: How to handle long-running commands (`watch`, `serve` itself)?
  — **Resolved**: exclude them from `tools/list`.
- [x] Q2: Should the server re-scan on file changes? — **Resolved**: yes,
  via `--watch` flag (uses `watchdog` library).
- [ ] Q3: How to handle concurrent tool calls from multiple agents sharing
  one server? — **Open**. Current implementation serializes calls; parallel
  execution would need registry locking.

## Migration / Rollout

The MCP server is additive — the CLI continues to work unchanged. Users who
don't want a persistent server can keep using `python3 codelens.py <cmd>`
per invocation. The `mcp_config.json` file at repo root provides
configuration templates for Claude Desktop, Cursor, VS Code Copilot,
Continue.dev, and Cline.

No database migration — the server uses the same `.codelens/codelens.db`
SQLite database as the CLI.

## References

- MCP specification: https://modelcontextprotocol.io/
- Issue: #17 (compact format for token efficiency)
- Issue: #59 (graphml format for graph-producing commands)
- Related design docs: [0004-graph-model](0004-graph-model.md) (the graph
  the server queries)
