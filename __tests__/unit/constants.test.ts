// ============================================================
// Shared Constants Unit Tests
// ============================================================

import {
  FORBIDDEN_PATHS,
  validateWorkspace,
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
    })
  })

  describe('validateWorkspace', () => {
    it('allows normal workspace paths', () => {
      expect(() => validateWorkspace('/home/user/project')).not.toThrow()
      expect(() => validateWorkspace('/workspace/code')).not.toThrow()
      expect(() => validateWorkspace('./my-project')).not.toThrow()
    })

    it('rejects forbidden system paths', () => {
      for (const forbidden of FORBIDDEN_PATHS) {
        expect(() => validateWorkspace(forbidden)).toThrow('is not allowed')
      }
    })

    it('rejects subdirectories of forbidden paths', () => {
      expect(() => validateWorkspace('/etc/passwd')).toThrow('is not allowed')
      expect(() => validateWorkspace('/root/.ssh')).toThrow('is not allowed')
      expect(() => validateWorkspace('/proc/self')).toThrow('is not allowed')
    })

    it('handles relative paths by resolving them', () => {
      // Relative paths resolve to current working directory, which is allowed
      expect(() => validateWorkspace('.')).not.toThrow()
      expect(() => validateWorkspace('..')).not.toThrow()
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
      expect(ALLOWED_COMMANDS.has('watch')).toBe(false)
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
