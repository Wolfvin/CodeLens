// ============================================================
// CodeLens Neural Workspace — Shared Constants
// ============================================================
// Single source of truth for security constants, command
// whitelists, and utility functions used across API routes,
// WebSocket server, and the command runner.
// ============================================================

import path from 'path'

// ---- Forbidden Workspace Paths ----
// Prevents directory traversal attacks by blocking access to
// system directories that should never be treated as workspaces.

export const FORBIDDEN_PATHS = ['/etc', '/root', '/proc', '/sys', '/dev', '/boot'] as const

/**
 * Validate that a workspace path does not resolve to a forbidden
 * system directory. Throws an Error if the path is not allowed.
 *
 * @param workspace - Raw workspace path from user input
 * @throws Error if the resolved path starts with a forbidden prefix
 */
export function validateWorkspace(workspace: string): void {
  const resolved = path.resolve(workspace)
  for (const prefix of FORBIDDEN_PATHS) {
    if (resolved.startsWith(prefix)) {
      throw new Error(`Workspace path '${resolved}' is not allowed.`)
    }
  }
}

// ---- Allowed CLI Commands ----
// Whitelist of CodeLens CLI commands that can be executed via the
// REST API or WebSocket interface. Any command not in this set is
// rejected to prevent command injection.

export const ALLOWED_COMMANDS = new Set([
  'init', 'scan', 'query', 'list', 'search', 'symbols', 'trace', 'impact',
  'dependents', 'outline', 'missing-refs', 'diff', 'circular', 'context',
  'validate', 'detect', 'secrets', 'vuln-scan', 'dataflow', 'env-check',
  'smell', 'complexity', 'debug-leak', 'dead-code', 'a11y', 'perf-hint',
  'css-deep', 'refactor-safe', 'side-effect', 'stack-trace', 'test-map',
  'config-drift', 'type-infer', 'ownership', 'entrypoints', 'api-map',
  'state-map', 'regex-audit', 'handbook', 'ask',
] as const)

// ---- Scan / Cache Defaults ----

/** Default TTL for scan result cache (30 seconds) */
export const DEFAULT_CACHE_TTL = 30_000

/** Maximum nodes returned by the graph API to keep browser responsive */
export const MAX_GRAPH_NODES = 500

/** Maximum execution time for a CLI command (ms) */
export const COMMAND_TIMEOUT = 60_000

/** Maximum buffer size for CLI output (10 MB) */
export const MAX_BUFFER = 10 * 1024 * 1024

/** Maximum argument length to prevent buffer overflow attempts */
export const MAX_ARG_LENGTH = 4096

// ---- Health Score Thresholds ----

export const HEALTH_GRADE_THRESHOLDS = {
  A_PLUS: 95,
  A: 85,
  B: 70,
  C: 55,
  D: 40,
} as const

// ---- Node Status Priority (for graph node sorting) ----

export const STATUS_PRIORITY: Record<string, number> = {
  critical: 4,
  vulnerable: 3,
  warning: 2,
  active: 1,
  dead: 0,
  orphan: 0,
  untested: 0,
  unused: 0,
  safe: 0,
  impure: 0,
  duplicate_define: 0,
  collision: 0,
} as const
