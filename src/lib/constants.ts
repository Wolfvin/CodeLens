// ============================================================
// CodeLens Neural Workspace — Shared Constants
// ============================================================
// Single source of truth for security constants, command
// whitelists, and utility functions used across API routes,
// WebSocket server, and the command runner.
// ============================================================

import path from 'path'
import fs from 'fs'

// ---- Forbidden Workspace Paths ----
// Prevents directory traversal attacks by blocking access to
// system directories that should never be treated as workspaces.
// Consolidated from workspaceValidator.ts to be the single source of truth.

export const FORBIDDEN_PATHS = [
  '/etc', '/root', '/proc', '/sys', '/dev', '/boot',
  '/sbin', '/usr/sbin', '/var/run',
] as const

/**
 * ValidationResult returned by validateWorkspace.
 * Provides both a throw-based and a return-based API for flexibility.
 */
export interface ValidationResult {
  valid: boolean
  resolved: string
  error?: string
}

/**
 * Validate and resolve a workspace path.
 * Prevents path traversal by ensuring the path:
 * 1. Is a non-empty string
 * 2. Does not contain directory traversal sequences (../)
 * 3. Is an absolute path
 * 4. Is not a system-critical directory
 * 5. Is an existing directory
 *
 * @param rawWorkspace - Raw workspace path from user input
 * @returns ValidationResult with valid/resolved/error fields
 */
export function validateWorkspace(rawWorkspace: string): ValidationResult {
  // Must be a non-empty string
  if (!rawWorkspace || typeof rawWorkspace !== 'string') {
    return { valid: false, resolved: '', error: 'Workspace path is required' }
  }

  // Reject paths with traversal sequences
  const normalized = path.normalize(rawWorkspace)
  if (normalized.includes('..')) {
    return { valid: false, resolved: '', error: 'Workspace path must not contain directory traversal sequences (../)' }
  }

  // Must be an absolute path
  if (!path.isAbsolute(normalized)) {
    return { valid: false, resolved: '', error: 'Workspace path must be absolute' }
  }

  // Block system-critical directories
  for (const prefix of FORBIDDEN_PATHS) {
    if (normalized === prefix || normalized.startsWith(prefix + '/')) {
      return { valid: false, resolved: normalized, error: `Workspace path cannot be within ${prefix}` }
    }
  }

  // Check the directory exists
  try {
    const stat = fs.statSync(normalized)
    if (!stat.isDirectory()) {
      return { valid: false, resolved: normalized, error: 'Workspace path must be a directory, not a file' }
    }
  } catch {
    return { valid: false, resolved: normalized, error: 'Workspace directory does not exist' }
  }

  return { valid: true, resolved: normalized }
}

/**
 * Validate workspace and throw on failure.
 * Convenience wrapper for routes that prefer throw-based error handling.
 *
 * @param rawWorkspace - Raw workspace path from user input
 * @throws Error if the workspace path is invalid
 */
export function validateWorkspaceOrThrow(rawWorkspace: string): string {
  const result = validateWorkspace(rawWorkspace)
  if (!result.valid) {
    throw new Error(result.error)
  }
  return result.resolved
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
