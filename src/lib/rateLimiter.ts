// ============================================================
// CodeLens Neural Workspace — API Rate Limiter
// ============================================================
// Simple in-memory sliding window rate limiter for API routes.
// Limits requests per IP to prevent abuse.
// ============================================================

interface RateLimitEntry {
  timestamps: number[]
}

const DEFAULT_WINDOW_MS = 60_000    // 1 minute
const DEFAULT_MAX_REQUESTS = 60     // 60 requests per minute

class RateLimiter {
  private entries = new Map<string, RateLimitEntry>()
  private windowMs: number
  private maxRequests: number

  constructor(windowMs: number = DEFAULT_WINDOW_MS, maxRequests: number = DEFAULT_MAX_REQUESTS) {
    this.windowMs = windowMs
    this.maxRequests = maxRequests
  }

  /**
   * Check if a request from the given key (usually IP) is allowed.
   * Returns { allowed: true } if the request is within limits,
   * or { allowed: false, retryAfterMs } if the limit is exceeded.
   */
  check(key: string): { allowed: true } | { allowed: false; retryAfterMs: number } {
    const now = Date.now()
    const cutoff = now - this.windowMs

    let entry = this.entries.get(key)
    if (!entry) {
      entry = { timestamps: [] }
      this.entries.set(key, entry)
    }

    // Remove timestamps outside the window
    entry.timestamps = entry.timestamps.filter(ts => ts > cutoff)

    if (entry.timestamps.length >= this.maxRequests) {
      // Calculate when the oldest request in the window will expire
      const oldestInWindow = entry.timestamps[0]
      const retryAfterMs = oldestInWindow + this.windowMs - now
      return { allowed: false, retryAfterMs: Math.max(retryAfterMs, 1000) }
    }

    entry.timestamps.push(now)
    return { allowed: true }
  }

  /** Clear all rate limit entries (useful for testing) */
  clear(): void {
    this.entries.clear()
  }

  /** Clean up stale entries to prevent memory leaks */
  cleanup(): void {
    const cutoff = Date.now() - this.windowMs
    for (const [key, entry] of this.entries) {
      entry.timestamps = entry.timestamps.filter(ts => ts > cutoff)
      if (entry.timestamps.length === 0) {
        this.entries.delete(key)
      }
    }
  }
}

// Singleton rate limiters for different API tiers
export const apiRateLimiter = new RateLimiter(60_000, 60)       // 60 req/min for general API
export const scanRateLimiter = new RateLimiter(60_000, 10)      // 10 req/min for scan (expensive)
export const commandRateLimiter = new RateLimiter(60_000, 30)   // 30 req/min for commands

/**
 * Extract client IP from request headers.
 * Handles X-Forwarded-For for reverse proxy setups.
 */
export function getClientIp(request: Request): string {
  const forwarded = request.headers.get('x-forwarded-for')
  if (forwarded) {
    return forwarded.split(',')[0].trim()
  }
  const realIp = request.headers.get('x-real-ip')
  if (realIp) {
    return realIp.trim()
  }
  return 'unknown'
}

// Periodic cleanup of stale entries (every 5 minutes)
if (typeof setInterval !== 'undefined') {
  setInterval(() => {
    apiRateLimiter.cleanup()
    scanRateLimiter.cleanup()
    commandRateLimiter.cleanup()
  }, 5 * 60_000).unref?.()
}
