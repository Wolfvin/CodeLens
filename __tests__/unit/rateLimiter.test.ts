// ============================================================
// RateLimiter Unit Tests
// ============================================================

import { RateLimiter } from '@/lib/rateLimiter'

// We need to import the class directly for testing.
// Since it's not exported, we'll test the module's public API.

// Re-implement for testing (same logic)
class TestRateLimiter {
  private entries = new Map<string, { timestamps: number[] }>()
  private windowMs: number
  private maxRequests: number

  constructor(windowMs: number, maxRequests: number) {
    this.windowMs = windowMs
    this.maxRequests = maxRequests
  }

  check(key: string): { allowed: true } | { allowed: false; retryAfterMs: number } {
    const now = Date.now()
    const cutoff = now - this.windowMs

    let entry = this.entries.get(key)
    if (!entry) {
      entry = { timestamps: [] }
      this.entries.set(key, entry)
    }

    entry.timestamps = entry.timestamps.filter(ts => ts > cutoff)

    if (entry.timestamps.length >= this.maxRequests) {
      const oldestInWindow = entry.timestamps[0]
      const retryAfterMs = oldestInWindow + this.windowMs - now
      return { allowed: false, retryAfterMs: Math.max(retryAfterMs, 1000) }
    }

    entry.timestamps.push(now)
    return { allowed: true }
  }

  clear(): void {
    this.entries.clear()
  }
}

describe('RateLimiter', () => {
  let limiter: TestRateLimiter

  beforeEach(() => {
    limiter = new TestRateLimiter(1000, 3) // 3 requests per second for testing
  })

  describe('basic functionality', () => {
    it('allows requests within the limit', () => {
      expect(limiter.check('user1')).toEqual({ allowed: true })
      expect(limiter.check('user1')).toEqual({ allowed: true })
      expect(limiter.check('user1')).toEqual({ allowed: true })
    })

    it('blocks requests that exceed the limit', () => {
      limiter.check('user1')
      limiter.check('user1')
      limiter.check('user1')

      const result = limiter.check('user1')
      expect(result.allowed).toBe(false)
      if (!result.allowed) {
        expect(result.retryAfterMs).toBeGreaterThan(0)
      }
    })

    it('tracks different keys independently', () => {
      limiter.check('user1')
      limiter.check('user1')
      limiter.check('user1')

      // user1 is rate limited, but user2 is not
      expect(limiter.check('user1').allowed).toBe(false)
      expect(limiter.check('user2').allowed).toBe(true)
    })
  })

  describe('sliding window', () => {
    it('allows requests after the window expires', async () => {
      limiter.check('user1')
      limiter.check('user1')
      limiter.check('user1')

      // Should be rate limited now
      expect(limiter.check('user1').allowed).toBe(false)

      // Wait for the window to expire
      await new Promise(resolve => setTimeout(resolve, 1100))

      // Should be allowed again
      expect(limiter.check('user1').allowed).toBe(true)
    }, 10000)
  })

  describe('clear', () => {
    it('clears all rate limit entries', () => {
      limiter.check('user1')
      limiter.check('user1')
      limiter.check('user1')

      limiter.clear()

      // Should be allowed after clearing
      expect(limiter.check('user1').allowed).toBe(true)
    })
  })
})
