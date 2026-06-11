// ============================================================
// CodeLens Neural Workspace — Scan Result Cache
// ============================================================
//
// Caches the result of `codelens scan` to avoid re-running the
// CLI on every API request. The cache is invalidated after a
// configurable TTL (default 30 seconds) or when the workspace
// path changes.
//
// This dramatically reduces latency for repeated /api/graph and
// /api/health calls during active dashboard use.
// ============================================================

interface CacheEntry {
  workspace: string
  result: Record<string, any>
  timestamp: number
}

/** Cache TTL in milliseconds (default: 30 seconds) */
const CACHE_TTL = Number(process.env.SCAN_CACHE_TTL_MS) || 30_000

let cache: CacheEntry | null = null

/**
 * Get a cached scan result if it exists and is still fresh.
 * Returns null if no cache or if the cache is stale.
 */
export function getCachedScan(workspace: string): Record<string, any> | null {
  if (!cache) return null

  // Workspace must match
  if (cache.workspace !== workspace) return null

  // Cache must be fresh
  const age = Date.now() - cache.timestamp
  if (age > CACHE_TTL) return null

  return cache.result
}

/**
 * Store a scan result in the cache.
 */
export function setCachedScan(workspace: string, result: Record<string, any>): void {
  cache = {
    workspace,
    result,
    timestamp: Date.now(),
  }
}

/**
 * Invalidate the cache (e.g., after a command that modifies the registry).
 */
export function invalidateScanCache(): void {
  cache = null
}

/**
 * Get cache stats for monitoring.
 */
export function getCacheStats(): { cached: boolean; workspace: string | null; ageMs: number | null; ttlMs: number } {
  if (!cache) {
    return { cached: false, workspace: null, ageMs: null, ttlMs: CACHE_TTL }
  }
  return {
    cached: true,
    workspace: cache.workspace,
    ageMs: Date.now() - cache.timestamp,
    ttlMs: CACHE_TTL,
  }
}
