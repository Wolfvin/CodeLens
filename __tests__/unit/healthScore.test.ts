// ============================================================
// HealthScore Unit Tests
// ============================================================

import {
  computeHealthScore,
  computeCoupling,
  computeHeatmap,
  computeImpactRadius,
  computeDependencyDepth,
} from '@/lib/healthScore'
import type { GraphNode, GraphEdge } from '@/types/neural'

// ---- Helpers ----

function makeNode(overrides: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    label: overrides.id,
    type: 'function',
    domain: 'backend',
    status: 'active',
    radius: 10,
    color: '#63b3ed',
    data: {},
    ...overrides,
  }
}

function makeEdge(overrides: Partial<GraphEdge> & { id: string; source: string; target: string }): GraphEdge {
  return {
    type: 'calls',
    weight: 1,
    status: 'active',
    ...overrides,
  }
}

// ---- Test Suite ----

describe('HealthScore', () => {
  // ============================================================
  // computeCoupling
  // ============================================================

  describe('computeCoupling', () => {
    it('returns empty array for empty nodes', () => {
      const result = computeCoupling([], [])
      expect(result).toEqual([])
    })

    it('returns zero fanIn/fanOut for isolated nodes with no edges', () => {
      const nodes = [
        makeNode({ id: 'a' }),
        makeNode({ id: 'b' }),
      ]
      const result = computeCoupling(nodes, [])
      expect(result).toHaveLength(2)
      expect(result.every(c => c.fanIn === 0 && c.fanOut === 0)).toBe(true)
      expect(result.every(c => c.instability === 0)).toBe(true)
    })

    it('computes correct fanIn and fanOut for a simple chain A→B→C', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'fnA' }),
        makeNode({ id: 'b', label: 'fnB' }),
        makeNode({ id: 'c', label: 'fnC' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'b', target: 'c' }),
      ]
      const result = computeCoupling(nodes, edges)
      const resultMap = new Map(result.map(c => [c.nodeId, c]))

      // A depends on B → fanOut=1, fanIn=0
      expect(resultMap.get('a')!.fanOut).toBe(1)
      expect(resultMap.get('a')!.fanIn).toBe(0)
      expect(resultMap.get('a')!.instability).toBe(1) // fo/(fi+fo) = 1/1 = 1

      // B is depended on by A and depends on C → fanIn=1, fanOut=1
      expect(resultMap.get('b')!.fanIn).toBe(1)
      expect(resultMap.get('b')!.fanOut).toBe(1)
      expect(resultMap.get('b')!.instability).toBeCloseTo(0.5)

      // C is depended on by B → fanIn=1, fanOut=0
      expect(resultMap.get('c')!.fanIn).toBe(1)
      expect(resultMap.get('c')!.fanOut).toBe(0)
      expect(resultMap.get('c')!.instability).toBe(0)
    })

    it('sorts results by total coupling descending', () => {
      const nodes = [
        makeNode({ id: 'hub', label: 'hub' }),
        makeNode({ id: 'spoke1', label: 'spoke1' }),
        makeNode({ id: 'spoke2', label: 'spoke2' }),
        makeNode({ id: 'spoke3', label: 'spoke3' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'hub', target: 'spoke1' }),
        makeEdge({ id: 'e2', source: 'hub', target: 'spoke2' }),
        makeEdge({ id: 'e3', source: 'hub', target: 'spoke3' }),
      ]
      const result = computeCoupling(nodes, edges)
      // hub has fanIn=0, fanOut=3 → total=3, should be first
      expect(result[0].nodeId).toBe('hub')
      expect(result[0].fanOut).toBe(3)
    })

    it('populates coupledWith with top 3 most-connected neighbors', () => {
      const nodes = [
        makeNode({ id: 'center' }),
        makeNode({ id: 'n1' }),
        makeNode({ id: 'n2' }),
        makeNode({ id: 'n3' }),
        makeNode({ id: 'n4' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'center', target: 'n1' }),
        makeEdge({ id: 'e2', source: 'center', target: 'n2' }),
        makeEdge({ id: 'e3', source: 'center', target: 'n3' }),
        makeEdge({ id: 'e4', source: 'center', target: 'n4' }),
      ]
      const result = computeCoupling(nodes, edges)
      const center = result.find(c => c.nodeId === 'center')!
      // Should cap at 3 neighbors
      expect(center.coupledWith.length).toBeLessThanOrEqual(3)
    })

    it('ignores edges referencing nodes not in the node list', () => {
      const nodes = [makeNode({ id: 'a' })]
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'nonexistent' }),
      ]
      const result = computeCoupling(nodes, edges)
      // fanOut should increment (a depends on nonexistent), but nonexistent has no entry
      expect(result).toHaveLength(1)
      expect(result[0].fanOut).toBe(1)
    })
  })

  // ============================================================
  // computeHeatmap
  // ============================================================

  describe('computeHeatmap', () => {
    it('returns empty array for empty nodes', () => {
      const result = computeHeatmap([], [], [])
      expect(result).toEqual([])
    })

    it('computes near-zero heat for simple active nodes with default complexity', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      // Default complexity=1 contributes a tiny amount: Math.min(1/20,1)*0.25 = 0.0125
      expect(result.every(h => h.heat < 0.02)).toBe(true)
    })

    it('computes exactly zero heat when complexity is explicitly 0', () => {
      const nodes = [makeNode({ id: 'a', data: { complexity: 0 } }), makeNode({ id: 'b', data: { complexity: 0 } })]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      expect(result.every(h => h.heat === 0)).toBe(true)
    })

    it('increases heat for high fanOut nodes', () => {
      const nodes = [
        makeNode({ id: 'hub' }),
        ...Array.from({ length: 12 }, (_, i) => makeNode({ id: `spoke${i}` })),
      ]
      const edges = Array.from({ length: 12 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: 'hub', target: `spoke${i}` })
      )
      const coupling = computeCoupling(nodes, edges)
      const result = computeHeatmap(nodes, edges, coupling)
      const hub = result.find(h => h.nodeId === 'hub')!
      expect(hub.factors.fanOut).toBe(12)
      expect(hub.heat).toBeGreaterThan(0)
    })

    it('increases heat for dead/unused code', () => {
      const nodes = [
        makeNode({ id: 'dead', status: 'dead' }),
        makeNode({ id: 'unused', status: 'unused' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      const deadEntry = result.find(h => h.nodeId === 'dead')!
      const unusedEntry = result.find(h => h.nodeId === 'unused')!
      expect(deadEntry.factors.deadCode).toBe(true)
      expect(deadEntry.heat).toBeGreaterThan(0)
      expect(unusedEntry.factors.deadCode).toBe(true)
    })

    it('increases heat for vulnerable/critical status', () => {
      const nodes = [
        makeNode({ id: 'vuln', status: 'vulnerable' }),
        makeNode({ id: 'crit', status: 'critical' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      const vulnEntry = result.find(h => h.nodeId === 'vuln')!
      const critEntry = result.find(h => h.nodeId === 'crit')!
      expect(vulnEntry.factors.vulnerable).toBe(true)
      expect(critEntry.factors.vulnerable).toBe(true)
      expect(vulnEntry.heat).toBeGreaterThanOrEqual(0.2)
    })

    it('increases heat for untested status', () => {
      const nodes = [makeNode({ id: 'untested', status: 'untested' })]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      expect(result[0].factors.untested).toBe(true)
      expect(result[0].heat).toBeGreaterThanOrEqual(0.15)
    })

    it('sorts results by heat descending (hottest first)', () => {
      const nodes = [
        makeNode({ id: 'cool', status: 'active' }),
        makeNode({ id: 'hot', status: 'critical' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const result = computeHeatmap(nodes, [], coupling)
      expect(result[0].nodeId).toBe('hot')
    })

    it('caps heat at 1.0 maximum', () => {
      const nodes = [
        makeNode({ id: 'inferno', status: 'critical', data: { complexity: 50 } }),
      ]
      // Add many edges for high fanOut
      const edges = Array.from({ length: 15 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: 'inferno', target: `t${i}` })
      )
      // Need the target nodes too
      const allNodes = [
        ...nodes,
        ...Array.from({ length: 15 }, (_, i) => makeNode({ id: `t${i}` })),
      ]
      const coupling = computeCoupling(allNodes, edges)
      const result = computeHeatmap(allNodes, edges, coupling)
      const inferno = result.find(h => h.nodeId === 'inferno')!
      expect(inferno.heat).toBeLessThanOrEqual(1.0)
    })
  })

  // ============================================================
  // computeImpactRadius
  // ============================================================

  describe('computeImpactRadius', () => {
    it('returns zero impact for isolated node', () => {
      const nodes = [makeNode({ id: 'a', label: 'fnA' })]
      const result = computeImpactRadius('a', nodes, [])
      expect(result.totalImpacted).toBe(0)
      expect(result.deepestPath).toBe(0)
    })

    it('computes single-level impact correctly', () => {
      const nodes = [
        makeNode({ id: 'b', label: 'fnB' }),
        makeNode({ id: 'a', label: 'fnA' }),
      ]
      // a depends_on b → changing b impacts a
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b', type: 'depends_on' }),
      ]
      const result = computeImpactRadius('b', nodes, edges)
      expect(result.totalImpacted).toBe(1) // a is impacted
      expect(result.deepestPath).toBe(1)
      expect(result.byDepth[1]?.nodeIds).toContain('a')
    })

    it('computes multi-level impact via BFS', () => {
      const nodes = [
        makeNode({ id: 'c', label: 'fnC' }),
        makeNode({ id: 'b', label: 'fnB' }),
        makeNode({ id: 'a', label: 'fnA' }),
      ]
      // c → b, b → a  (a depends_on b, b depends_on c)
      const edges = [
        makeEdge({ id: 'e1', source: 'b', target: 'c' }),
        makeEdge({ id: 'e2', source: 'a', target: 'b' }),
      ]
      // Changing c: c impacts b (depth 1), b impacts a (depth 2)
      const result = computeImpactRadius('c', nodes, edges)
      expect(result.totalImpacted).toBe(2)
      expect(result.deepestPath).toBe(2)
      expect(result.byDepth[1]?.nodeIds).toContain('b')
      expect(result.byDepth[2]?.nodeIds).toContain('a')
    })

    it('respects maxDepth parameter', () => {
      const nodes = Array.from({ length: 5 }, (_, i) =>
        makeNode({ id: `n${i}`, label: `fn${i}` })
      )
      // Chain: n4→n3→n2→n1→n0 (each depends on the next)
      const edges = Array.from({ length: 4 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: `n${i}`, target: `n${i + 1}` })
      )
      // Changing n4 with maxDepth=2 should only reach n3 and n2
      const result = computeImpactRadius('n4', nodes, edges, 2)
      expect(result.deepestPath).toBe(2)
    })

    it('returns "unknown" label for nonexistent nodeId', () => {
      const result = computeImpactRadius('nonexistent', [], [])
      expect(result.label).toBe('unknown')
      expect(result.totalImpacted).toBe(0)
    })

    it('does not count the starting node in totalImpacted', () => {
      const nodes = [
        makeNode({ id: 'root', label: 'root' }),
        makeNode({ id: 'child', label: 'child' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'child', target: 'root' }),
      ]
      const result = computeImpactRadius('root', nodes, edges)
      // Only child is impacted, root itself is excluded
      expect(result.totalImpacted).toBe(1)
    })
  })

  // ============================================================
  // computeDependencyDepth
  // ============================================================

  describe('computeDependencyDepth', () => {
    it('returns 0 for node with no outgoing dependencies', () => {
      const edges: GraphEdge[] = []
      expect(computeDependencyDepth('a', edges)).toBe(0)
    })

    it('computes depth for a linear chain', () => {
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'b', target: 'c' }),
        makeEdge({ id: 'e3', source: 'c', target: 'd' }),
      ]
      expect(computeDependencyDepth('a', edges)).toBe(3)
    })

    it('respects maxDepth parameter', () => {
      const edges = Array.from({ length: 30 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: `n${i}`, target: `n${i + 1}` })
      )
      expect(computeDependencyDepth('n0', edges, 5)).toBe(5)
    })
  })

  // ============================================================
  // computeHealthScore
  // ============================================================

  describe('computeHealthScore', () => {
    it('returns perfect score for empty graph', () => {
      const result = computeHealthScore([], [], [])
      expect(result.overall).toBe(100)
      expect(result.grade).toBe('A+')
      expect(result.metrics.totalNodes).toBe(0)
      expect(result.recommendations).toHaveLength(0)
    })

    it('returns high score for clean healthy codebase', () => {
      const nodes = [
        makeNode({ id: 'a', status: 'active' }),
        makeNode({ id: 'b', status: 'active' }),
      ]
      const edges: GraphEdge[] = []
      const clusters = [{ nodeIds: ['a', 'b'], cohesion: 0.9 }]
      const result = computeHealthScore(nodes, edges, clusters)
      expect(result.overall).toBeGreaterThanOrEqual(85)
      expect(result.grade).toMatch(/A\+|A/)
      expect(result.metrics.deadCodeCount).toBe(0)
      expect(result.metrics.untestedCount).toBe(0)
    })

    it('penalizes dead code in quality score', () => {
      const nodes = [
        makeNode({ id: 'a', status: 'active' }),
        makeNode({ id: 'b', status: 'dead' }),
        makeNode({ id: 'c', status: 'unused' }),
        makeNode({ id: 'd', status: 'active' }),
        makeNode({ id: 'e', status: 'active' }),
        makeNode({ id: 'f', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      expect(result.metrics.deadCodeCount).toBe(2)
      expect(result.metrics.deadCodePercent).toBeCloseTo(33.3, 0)
      expect(result.quality).toBeLessThan(100)
    })

    it('penalizes critical vulnerabilities in security score', () => {
      const nodes = [
        makeNode({ id: 'a', status: 'critical' }),
        makeNode({ id: 'b', status: 'vulnerable' }),
        makeNode({ id: 'c', type: 'secret', status: 'active' }),
        makeNode({ id: 'd', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      expect(result.metrics.criticalCount).toBe(1)
      expect(result.metrics.vulnerableCount).toBe(1)
      expect(result.metrics.secretCount).toBe(1)
      expect(result.security).toBeLessThan(100)
    })

    it('penalizes untested code in coverage score', () => {
      const nodes = [
        makeNode({ id: 'a', status: 'untested' }),
        makeNode({ id: 'b', status: 'untested' }),
        makeNode({ id: 'c', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      expect(result.metrics.untestedCount).toBe(2)
      expect(result.metrics.untestedPercent).toBeCloseTo(66.7, 0)
      expect(result.coverage).toBeLessThan(100)
    })

    it('generates critical recommendation for critical vulnerabilities', () => {
      const nodes = [
        makeNode({ id: 'a', status: 'critical' }),
        makeNode({ id: 'b', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      const rec = result.recommendations.find(r => r.category === 'Security' && r.priority === 'critical')
      expect(rec).toBeDefined()
      expect(rec!.message).toContain('critical')
    })

    it('generates recommendation for hardcoded secrets', () => {
      const nodes = [
        makeNode({ id: 'a', type: 'secret', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      const rec = result.recommendations.find(r => r.message.includes('secrets'))
      expect(rec).toBeDefined()
      expect(rec!.priority).toBe('critical')
    })

    it('generates recommendation for untested code above threshold', () => {
      const nodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({ id: `n${i}`, status: i < 5 ? 'untested' : 'active' })
      )
      const result = computeHealthScore(nodes, [], [])
      const rec = result.recommendations.find(r => r.category === 'Coverage')
      expect(rec).toBeDefined()
      expect(rec!.priority).toBe('high')
    })

    it('computes correct grade boundaries for severely unhealthy codebase', () => {
      // Create a severely unhealthy codebase: lots of dead code, criticals, untested
      const nodes = [
        ...Array.from({ length: 10 }, (_, i) => makeNode({ id: `dead${i}`, status: 'dead' })),
        ...Array.from({ length: 5 }, (_, i) => makeNode({ id: `crit${i}`, status: 'critical' })),
        ...Array.from({ length: 5 }, (_, i) => makeNode({ id: `vuln${i}`, status: 'vulnerable' })),
        ...Array.from({ length: 10 }, (_, i) => makeNode({ id: `untested${i}`, status: 'untested' })),
      ]
      const result = computeHealthScore(nodes, [], [])
      // Quality and Security heavily penalized → overall significantly below 100
      expect(result.overall).toBeLessThan(55)
      expect(result.grade).toMatch(/C|D|F/)
    })

    it('uses cluster cohesion for architecture scoring', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const lowCohesionResult = computeHealthScore(nodes, [], [{ nodeIds: ['a', 'b'], cohesion: 0.1 }])
      const highCohesionResult = computeHealthScore(nodes, [], [{ nodeIds: ['a', 'b'], cohesion: 0.9 }])
      expect(highCohesionResult.architecture).toBeGreaterThan(lowCohesionResult.architecture)
    })

    it('sorts recommendations by priority then impact', () => {
      const nodes = [
        ...Array.from({ length: 10 }, (_, i) => makeNode({ id: `dead${i}`, status: 'dead' })),
        makeNode({ id: 'crit', status: 'critical' }),
        makeNode({ id: 'secret', type: 'secret', status: 'active' }),
      ]
      const result = computeHealthScore(nodes, [], [])
      // All critical items should come before high/medium
      const priorities = result.recommendations.map(r => r.priority)
      const firstNonCritical = priorities.findIndex(p => p !== 'critical')
      if (firstNonCritical > 0) {
        // All items before firstNonCritical should be critical
        expect(priorities.slice(0, firstNonCritical).every(p => p === 'critical')).toBe(true)
      }
    })

    it('computes ownership concentration (Gini) correctly', () => {
      const nodes = [
        makeNode({ id: 'a', data: { owner: 'alice' } }),
        makeNode({ id: 'b', data: { owner: 'alice' } }),
        makeNode({ id: 'c', data: { owner: 'alice' } }),
        makeNode({ id: 'd', data: { owner: 'bob' } }),
      ]
      const result = computeHealthScore(nodes, [], [])
      // 3/4 owned by alice → some concentration
      expect(result.metrics.ownershipConcentration).toBeGreaterThan(0)
    })

    it('penalizes high complexity functions', () => {
      const nodes = [
        makeNode({ id: 'simple', data: { complexity: 3 } }),
        makeNode({ id: 'complex', data: { complexity: 25 } }),
      ]
      const result = computeHealthScore(nodes, [], [])
      expect(result.metrics.highComplexityCount).toBe(1)
      expect(result.metrics.avgComplexity).toBe(14)
    })
  })
})
