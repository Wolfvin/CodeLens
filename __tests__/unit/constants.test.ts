// ============================================================
// Shared Constants Unit Tests
// ============================================================

import {
  FORBIDDEN_PATHS,
  validateWorkspace,
  validateWorkspaceOrThrow,
  ALLOWED_COMMANDS,
  DEFAULT_CACHE_TTL,
  MAX_GRAPH_NODES,
  COMMAND_TIMEOUT,
  MAX_ARG_LENGTH,
  STATUS_PRIORITY,
  HEALTH_GRADE_THRESHOLDS,
} from '@/lib/constants'

describe('Constants', () => {
  describe('FORBIDDEN_PATHS', () => {
    it('contains system directories', () => {
      expect(FORBIDDEN_PATHS).toContain('/etc')
      expect(FORBIDDEN_PATHS).toContain('/root')
      expect(FORBIDDEN_PATHS).toContain('/proc')
      expect(FORBIDDEN_PATHS).toContain('/sys')
      expect(FORBIDDEN_PATHS).toContain('/dev')
      expect(FORBIDDEN_PATHS).toContain('/boot')
      expect(FORBIDDEN_PATHS).toContain('/sbin')
      expect(FORBIDDEN_PATHS).toContain('/usr/sbin')
      expect(FORBIDDEN_PATHS).toContain('/var/run')
    })
  })

  describe('validateWorkspace', () => {
    it('returns valid for existing directories', () => {
      // /tmp always exists
      const result = validateWorkspace('/tmp')
      expect(result.valid).toBe(true)
      expect(result.resolved).toBe('/tmp')
      expect(result.error).toBeUndefined()
    })

    it('rejects empty workspace path', () => {
      const result = validateWorkspace('')
      expect(result.valid).toBe(false)
      expect(result.error).toBeTruthy()
    })

    it('rejects non-string workspace path', () => {
      const result = validateWorkspace(null as any)
      expect(result.valid).toBe(false)
      expect(result.error).toBeTruthy()
    })

    it('rejects paths with directory traversal', () => {
      const result = validateWorkspace('/home/user/../etc/passwd')
      expect(result.valid).toBe(false)
      expect(result.error).toContain('traversal')
    })

    it('rejects relative paths', () => {
      const result = validateWorkspace('my-project')
      expect(result.valid).toBe(false)
      expect(result.error).toContain('absolute')
    })

    it('rejects forbidden system paths', () => {
      for (const forbidden of FORBIDDEN_PATHS) {
        const result = validateWorkspace(forbidden)
        expect(result.valid).toBe(false)
        expect(result.error).toBeTruthy()
      }
    })

    it('rejects subdirectories of forbidden paths', () => {
      expect(validateWorkspace('/etc/passwd').valid).toBe(false)
      expect(validateWorkspace('/root/.ssh').valid).toBe(false)
      expect(validateWorkspace('/proc/self').valid).toBe(false)
    })

    it('rejects non-existent directories', () => {
      const result = validateWorkspace('/nonexistent/directory/that/does/not/exist')
      expect(result.valid).toBe(false)
      expect(result.error).toContain('does not exist')
    })
  })

  describe('validateWorkspaceOrThrow', () => {
    it('returns resolved path for valid directories', () => {
      const resolved = validateWorkspaceOrThrow('/tmp')
      expect(resolved).toBe('/tmp')
    })

    it('throws for forbidden paths', () => {
      expect(() => validateWorkspaceOrThrow('/etc')).toThrow()
    })

    it('throws for non-existent paths', () => {
      expect(() => validateWorkspaceOrThrow('/nonexistent/directory/that/does/not/exist')).toThrow()
    })
  })

  describe('ALLOWED_COMMANDS', () => {
    it('contains core commands', () => {
      expect(ALLOWED_COMMANDS.has('init')).toBe(true)
      expect(ALLOWED_COMMANDS.has('scan')).toBe(true)
      expect(ALLOWED_COMMANDS.has('query')).toBe(true)
    })

    it('contains security commands', () => {
      expect(ALLOWED_COMMANDS.has('secrets')).toBe(true)
      expect(ALLOWED_COMMANDS.has('vuln-scan')).toBe(true)
      expect(ALLOWED_COMMANDS.has('dataflow')).toBe(true)
    })

    it('contains quality commands', () => {
      expect(ALLOWED_COMMANDS.has('smell')).toBe(true)
      expect(ALLOWED_COMMANDS.has('complexity')).toBe(true)
      expect(ALLOWED_COMMANDS.has('dead-code')).toBe(true)
    })

    it('does not contain dangerous commands', () => {
      expect(ALLOWED_COMMANDS.has('rm')).toBe(false)
      expect(ALLOWED_COMMANDS.has('exec')).toBe(false)
      expect(ALLOWED_COMMANDS.has('eval')).toBe(false)
      expect(ALLOWED_COMMANDS.has('watch')).toBe(true) // watch IS allowed (blocked at API level)
    })
  })

  describe('numeric constants', () => {
    it('has reasonable default values', () => {
      expect(DEFAULT_CACHE_TTL).toBe(30_000)
      expect(MAX_GRAPH_NODES).toBe(500)
      expect(COMMAND_TIMEOUT).toBe(60_000)
      expect(MAX_ARG_LENGTH).toBe(4096)
    })
  })

  describe('STATUS_PRIORITY', () => {
    it('prioritizes critical over other statuses', () => {
      expect(STATUS_PRIORITY.critical).toBeGreaterThan(STATUS_PRIORITY.vulnerable)
      expect(STATUS_PRIORITY.vulnerable).toBeGreaterThan(STATUS_PRIORITY.warning)
      expect(STATUS_PRIORITY.warning).toBeGreaterThan(STATUS_PRIORITY.active)
      expect(STATUS_PRIORITY.active).toBeGreaterThanOrEqual(STATUS_PRIORITY.dead)
    })
  })

  describe('HEALTH_GRADE_THRESHOLDS', () => {
    it('has thresholds in descending order', () => {
      expect(HEALTH_GRADE_THRESHOLDS.A_PLUS).toBeGreaterThan(HEALTH_GRADE_THRESHOLDS.A)
      expect(HEALTH_GRADE_THRESHOLDS.A).toBeGreaterThan(HEALTH_GRADE_THRESHOLDS.B)
      expect(HEALTH_GRADE_THRESHOLDS.B).toBeGreaterThan(HEALTH_GRADE_THRESHOLDS.C)
      expect(HEALTH_GRADE_THRESHOLDS.C).toBeGreaterThan(HEALTH_GRADE_THRESHOLDS.D)
    })
  })
})
