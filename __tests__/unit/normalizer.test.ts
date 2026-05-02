// ============================================================
// Normalizer Unit Tests
// ============================================================

import { normalizer } from '@/lib/normalizer'
import type { GraphEvent, EdgeType } from '@/types/neural'

// ---- Helpers ----

function isValidGraphEvent(event: GraphEvent): boolean {
  return (
    typeof event.sourceCommand === 'string' &&
    typeof event.timestamp === 'number' &&
    Array.isArray(event.nodes) &&
    Array.isArray(event.edges) &&
    typeof event.animation === 'object' &&
    typeof event.metadata === 'object'
  )
}

// ---- Test Suite ----

describe('Normalizer', () => {
  // ============================================================
  // normalize('scan', ...)
  // ============================================================

  describe('normalize scan', () => {
    it('creates nodes and edges from frontend/backend data', () => {
      const output = {
        frontend: {
          classes: [
            {
              name: 'btn-primary',
              status: 'active',
              ref_count: 5,
              css: [{ path: 'src/styles/buttons.css', line: 10 }],
              js: [{ path: 'src/components/Button.tsx', line: 3 }],
            },
          ],
          ids: [
            {
              name: 'login-form',
              status: 'active',
              ref_count: 2,
              defined_in_html: [{ path: 'src/pages/Login.tsx', line: 8 }],
            },
          ],
        },
        backend: {
          nodes: [
            { id: 'src/api.ts:10', fn: 'processPayment', file: 'src/api.ts', line: 10, async: true, ref_count: 3 },
            { id: 'src/page.tsx:5', fn: 'CheckoutPage', file: 'src/page.tsx', line: 5, component: true, ref_count: 1 },
          ],
          edges: [
            { from: 'src/page.tsx:5', to: 'src/api.ts:10', type: 'calls' },
          ],
        },
      }

      const event = normalizer.normalize('scan', output)
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.sourceCommand).toBe('scan')
      expect(event.nodes.length).toBeGreaterThanOrEqual(3) // class + id + function(s)
      expect(event.edges.length).toBeGreaterThanOrEqual(1)

      // Check class node
      const classNode = event.nodes.find(n => n.type === 'class')
      expect(classNode).toBeDefined()
      expect(classNode!.label).toBe('.btn-primary')
      expect(classNode!.domain).toBe('frontend')

      // Check id node
      const idNode = event.nodes.find(n => n.type === 'id')
      expect(idNode).toBeDefined()
      expect(idNode!.label).toBe('#login-form')

      // Check backend function node
      const fnNode = event.nodes.find(n => n.label === 'processPayment')
      expect(fnNode).toBeDefined()
      expect(fnNode!.domain).toBe('backend')

      // Check component node
      const compNode = event.nodes.find(n => n.type === 'component')
      expect(compNode).toBeDefined()
      expect(compNode!.label).toBe('CheckoutPage')
    })

    it('scan edge types are properly mapped (not all "defines")', () => {
      const output = {
        frontend: { classes: [], ids: [] },
        backend: {
          nodes: [
            { id: 'a:1', fn: 'fnA', file: 'a.ts', line: 1 },
            { id: 'b:2', fn: 'fnB', file: 'b.ts', line: 2 },
          ],
          edges: [
            { from: 'a:1', to: 'b:2', type: 'calls' },
          ],
        },
      }

      const event = normalizer.normalize('scan', output)
      // At least one edge should be 'calls' not 'defines'
      const callsEdges = event.edges.filter(e => e.type === 'calls')
      expect(callsEdges.length).toBeGreaterThanOrEqual(1)
    })

    it('handles empty scan output gracefully', () => {
      const event = normalizer.normalize('scan', {})
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBe(0)
      expect(event.edges.length).toBe(0)
    })
  })

  // ============================================================
  // normalize('query', ...)
  // ============================================================

  describe('normalize query', () => {
    it('with found = true, creates nodes and edges', () => {
      const output = {
        found: true,
        type: 'function',
        domain: 'backend',
        name: 'processPayment',
        node: { id: 'src/api.ts:10', fn: 'processPayment', file: 'src/api.ts', line: 10, status: 'active' },
        callers: [{ fn: 'checkout', file: 'src/page.tsx', line: 5 }],
        callees: [{ fn: 'validatePayment', file: 'src/validate.ts', line: 3 }],
      }

      const event = normalizer.normalize('query', output)
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBeGreaterThanOrEqual(1)
      expect(event.edges.length).toBeGreaterThanOrEqual(2) // caller + callee edges

      const mainNode = event.nodes.find(n => n.label === 'processPayment')
      expect(mainNode).toBeDefined()
    })

    it('with found = false, returns empty event', () => {
      const output = { found: false, query: 'nonExistent' }

      const event = normalizer.normalize('query', output)
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBe(0)
      expect(event.edges.length).toBe(0)
      expect(event.metadata.summary).toContain('Not found')
    })

    it('handles class query type', () => {
      const output = {
        found: true,
        type: 'class',
        domain: 'frontend',
        name: 'btn-primary',
        status: 'active',
        ref_count: 5,
        css: [{ path: 'src/styles.css', line: 10 }],
        js: [{ path: 'src/app.tsx', line: 3 }],
      }

      const event = normalizer.normalize('query', output)
      expect(event.nodes.length).toBeGreaterThanOrEqual(1)
      const classNode = event.nodes.find(n => n.type === 'class')
      expect(classNode).toBeDefined()
      expect(classNode!.label).toBe('.btn-primary')
    })

    it('handles id query type', () => {
      const output = {
        found: true,
        type: 'id',
        domain: 'frontend',
        name: 'login-form',
        status: 'active',
        ref_count: 2,
        css: [],
        js: [],
      }

      const event = normalizer.normalize('query', output)
      const idNode = event.nodes.find(n => n.type === 'id')
      expect(idNode).toBeDefined()
      expect(idNode!.label).toBe('#login-form')
    })
  })

  // ============================================================
  // normalize('trace', ...)
  // ============================================================

  describe('normalize trace', () => {
    it('with up chain (callers)', () => {
      const output = {
        symbol: 'processPayment',
        direction: 'up',
        chains: {
          up: [
            { fn: 'processPayment', file: 'src/api.ts', line: 10, depth: 0 },
            { fn: 'checkout', file: 'src/page.tsx', line: 5, depth: 1 },
            { fn: 'main', file: 'src/index.ts', line: 1, depth: 2 },
          ],
          down: [],
        },
      }

      const event = normalizer.normalize('trace', output)
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBe(3)
      expect(event.edges.length).toBe(2) // chain links
      expect(event.animation.type).toBe('flow')
    })

    it('with down chain (callees)', () => {
      const output = {
        symbol: 'processPayment',
        direction: 'down',
        chains: {
          up: [],
          down: [
            { fn: 'processPayment', file: 'src/api.ts', line: 10, depth: 0 },
            { fn: 'validatePayment', file: 'src/validate.ts', line: 3, depth: 1 },
          ],
        },
      }

      const event = normalizer.normalize('trace', output)
      expect(event.nodes.length).toBe(2)
      expect(event.edges.length).toBe(1)
    })

    it('detects cyclic chains and sets high risk', () => {
      const output = {
        symbol: 'cyclicFn',
        direction: 'up',
        chains: {
          up: [
            { fn: 'cyclicFn', file: 'a.ts', line: 1, depth: 0 },
            { fn: 'callerA', file: 'b.ts', line: 2, depth: 1, cyclic: true },
          ],
          down: [],
        },
      }

      const event = normalizer.normalize('trace', output)
      expect(event.metadata.riskLevel).toBe('high')
    })

    it('sets low risk for non-cyclic chains', () => {
      const output = {
        symbol: 'simpleFn',
        direction: 'up',
        chains: {
          up: [{ fn: 'simpleFn', file: 'a.ts', line: 1, depth: 0 }],
          down: [],
        },
      }

      const event = normalizer.normalize('trace', output)
      expect(event.metadata.riskLevel).toBe('low')
    })
  })

  // ============================================================
  // normalize('detect', ...)
  // ============================================================

  describe('normalize detect', () => {
    it('creates package nodes for frameworks', () => {
      const output = {
        frameworks: ['Next.js', 'React', 'Tailwind CSS', 'Prisma'],
      }

      const event = normalizer.normalize('detect', output)
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBeGreaterThanOrEqual(4)

      const packageNodes = event.nodes.filter(n => n.type === 'package')
      expect(packageNodes.length).toBe(4)
      expect(packageNodes.map(n => n.label)).toEqual(expect.arrayContaining(['Next.js', 'React', 'Tailwind CSS', 'Prisma']))
    })

    it('handles empty frameworks', () => {
      const event = normalizer.normalize('detect', {})
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.nodes.length).toBe(0)
    })
  })

  // ============================================================
  // normalize('watch', ...)
  // ============================================================

  describe('normalize watch', () => {
    it('returns WebSocket suggestion event', () => {
      const event = normalizer.normalize('watch', { workspace: '/home/user/project' })
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.sourceCommand).toBe('watch')
      // Watch should reference WebSocket / file watcher
      expect(event.metadata.summary).toBeDefined()
    })
  })

  // ============================================================
  // normalize('unknown_command', ...)
  // ============================================================

  describe('normalize unknown command', () => {
    it('falls back to generic event', () => {
      const event = normalizer.normalize('nonexistent_cmd', { some: 'data' })
      expect(isValidGraphEvent(event)).toBe(true)
      expect(event.sourceCommand).toBe('nonexistent_cmd')
      expect(event.nodes.length).toBe(0)
      expect(event.metadata.summary).toContain('Unknown command')
    })
  })

  // ============================================================
  // normalize('smell', ...)
  // ============================================================

  describe('normalize smell', () => {
    it('uses "class" type when smell.class is present', () => {
      const output = {
        by_category: {
          long_class: [
            { class: 'BigComponent', file: 'src/Big.tsx', line: 1, severity: 'warning', message: 'Class too large' },
          ],
        },
        stats: { total_smells: 1, health_score: 80, by_severity: { critical: 0, warning: 1, info: 0 } },
        risk: 'medium',
      }

      const event = normalizer.normalize('smell', output)
      expect(isValidGraphEvent(event)).toBe(true)
      const classNode = event.nodes.find(n => n.type === 'class')
      expect(classNode).toBeDefined()
      expect(classNode!.label).toBe('BigComponent')
    })

    it('uses "function" type when smell.fn is present (no smell.class)', () => {
      const output = {
        by_category: {
          long_function: [
            { fn: 'processPayment', file: 'src/api.ts', line: 10, severity: 'warning', message: 'Too long' },
          ],
        },
        stats: { total_smells: 1, health_score: 80, by_severity: { critical: 0, warning: 1, info: 0 } },
        risk: 'medium',
      }

      const event = normalizer.normalize('smell', output)
      const fnNode = event.nodes.find(n => n.type === 'function')
      expect(fnNode).toBeDefined()
      expect(fnNode!.label).toBe('processPayment')
    })

    it('computes risk from health_score', () => {
      const lowRisk = normalizer.normalize('smell', {
        by_category: {},
        stats: { total_smells: 0, health_score: 90, by_severity: {} },
      })
      expect(lowRisk.metadata.riskLevel).toBe('low')

      const medRisk = normalizer.normalize('smell', {
        by_category: {},
        stats: { total_smells: 5, health_score: 60, by_severity: {} },
      })
      expect(medRisk.metadata.riskLevel).toBe('medium')

      const highRisk = normalizer.normalize('smell', {
        by_category: {},
        stats: { total_smells: 10, health_score: 30, by_severity: {} },
      })
      expect(highRisk.metadata.riskLevel).toBe('high')
    })
  })

  // ============================================================
  // General: each normalizer returns a valid GraphEvent
  // ============================================================

  describe('all normalizers return valid GraphEvent', () => {
    const commandOutputs: Array<[string, Record<string, any>]> = [
      ['scan', { frontend: { classes: [], ids: [] }, backend: { nodes: [], edges: [] } }],
      ['query', { found: true, type: 'function', domain: 'backend', name: 'fn1', node: { id: 'x:1', fn: 'fn1', file: 'x.ts', line: 1 } }],
      ['trace', { symbol: 'fn1', chains: { up: [{ fn: 'fn1', file: 'a.ts', line: 1, depth: 0 }], down: [] } }],
      ['impact', { symbol: 'fn1', affected: { direct: [], indirect: [] }, risk: 'low' }],
      ['symbols', { results: [{ name: 'fn1', type: 'function', domain: 'backend' }] }],
      ['list', { results: [{ name: 'fn1', type: 'function' }] }],
      ['search', { results: [{ file: 'src/a.ts', line: 1, match: 'fn1' }] }],
      ['circular', { cycles: [] }],
      ['dataflow', { flows: [] }],
      ['smell', { by_category: {}, stats: { total_smells: 0, health_score: 100 } }],
      ['side-effect', { fn: 'fn1', purity: 0.8, side_effects: [] }],
      ['refactor-safe', { name: 'fn1', safe: true, risks: [] }],
      ['dead-code', { results: {}, stats: { total_dead_code: 0 } }],
      ['stack-trace', { propagation: [] }],
      ['test-map', { coverage: [] }],
      ['config-drift', { drift: [] }],
      ['type-infer', { results: [] }],
      ['ownership', { owners: [] }],
      ['secrets', { findings: [] }],
      ['entrypoints', { entries: [] }],
      ['api-map', { routes: [] }],
      ['state-map', { stores: [] }],
      ['env-check', { missing: [], exposed: [] }],
      ['debug-leak', { findings: [] }],
      ['complexity', { results: [] }],
      ['regex-audit', { findings: [] }],
      ['a11y', { issues: [] }],
      ['vuln-scan', { vulnerabilities: [], risk: 'low' }],
      ['perf-hint', { hints: [] }],
      ['css-deep', { unused_vars: [], orphan_keyframes: [], specificity_wars: { important_count: 0, files: [] }, duplicate_properties: { count: 0, examples: [] }, z_index_abuse: { max: 0, count: 0, above_1000: 0 } }],
      ['validate', { valid: true, issues: [] }],
      ['diff', { changes: [], summary: { added: 0, removed: 0, modified: 0, total_changes: 0 } }],
      ['dependents', { file: 'src/a.ts', dependents: [], dependencies: [] }],
      ['context', { symbol: 'fn1', type: 'function', file: 'a.ts', line: 1, callers: [], callees: [], defined_in: [], tests: [] }],
      ['outline', { files: [] }],
      ['missing-refs', { css_no_html: [], html_no_css: [] }],
      ['init', { config: {} }],
      ['detect', { frameworks: [] }],
      ['watch', { workspace: '/tmp' }],
    ]

    for (const [cmd, output] of commandOutputs) {
      it(`normalize("${cmd}", ...) returns valid GraphEvent`, () => {
        const event = normalizer.normalize(cmd, output)
        expect(isValidGraphEvent(event)).toBe(true)
        expect(event.sourceCommand).toBe(cmd)
      })
    }
  })
})
