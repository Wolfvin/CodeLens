// ============================================================
// Workspace Path Validator
// Prevents path traversal attacks on API endpoints
// ============================================================

import path from 'path'
import fs from 'fs'

/**
 * Validate and resolve a workspace path.
 * Prevents path traversal by ensuring the path:
 * 1. Is absolute
 * 2. Does not contain directory traversal sequences (../)
 * 3. Is an existing directory
 * 4. Is not a system-critical directory
 */
export function validateWorkspace(rawWorkspace: string): { valid: boolean; resolved: string; error?: string } {
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
  const blockedPrefixes = ['/etc', '/proc', '/sys', '/dev', '/boot', '/root', '/sbin', '/usr/sbin', '/var/run']
  for (const prefix of blockedPrefixes) {
    if (normalized === prefix || normalized.startsWith(prefix + '/')) {
      return { valid: false, resolved: '', error: `Workspace path cannot be within ${prefix}` }
    }
  }

  // Check the directory exists
  try {
    const stat = fs.statSync(normalized)
    if (!stat.isDirectory()) {
      return { valid: false, resolved: '', error: 'Workspace path must be a directory, not a file' }
    }
  } catch {
    return { valid: false, resolved: '', error: 'Workspace directory does not exist' }
  }

  return { valid: true, resolved: normalized }
}
