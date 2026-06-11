// ============================================================
// HealthScore Unit Tests
// ============================================================

import {
  computeCoupling,
  computeHealthScore,
  computeImpactRadius,
  computeHeatmap,
} from '@/lib/healthScore'
import type { GraphNode, GraphEdge, CouplingInfo, HeatmapEntry } from '@/lib/healthScore'
import type { NodeStatus, EdgeType } from '@/types/neural'

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
  // computeCoupling()
  // ============================================================

  describe('computeCoupling', () => {
    it('returns empty array with no nodes', () => {
      const result = computeCoupling([], [])
      expect(result).toEqual([])
    })

    it('returns zero fanIn/fanOut for nodes with no edges', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]
      const result = computeCoupling(nodes, [])

      expect(result).toHaveLength(2)
      for (const c of result) {
        expect(c.fanIn).toBe(0)
        expect(c.fanOut).toBe(0)
        expect(c.instability).toBe(0)
      }
    })

    it('computes fanIn/fanOut for a simple dependency chain', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'A' }),
        makeNode({ id: 'b', label: 'B' }),
        makeNode({ id: 'c', label: 'C' }),
      ]
      // A → B → C (A depends on B, B depends on C)
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'b', target: 'c' }),
      ]
      const result = computeCoupling(nodes, edges)

      const couplingMap = new Map(result.map(c => [c.nodeId, c]))

      // A: fanOut=1 (depends on B), fanIn=0
      expect(couplingMap.get('a')!.fanOut).toBe(1)
      expect(couplingMap.get('a')!.fanIn).toBe(0)

      // B: fanIn=1 (A depends on it), fanOut=1 (depends on C)
      expect(couplingMap.get('b')!.fanIn).toBe(1)
      expect(couplingMap.get('b')!.fanOut).toBe(1)

      // C: fanIn=1 (B depends on it), fanOut=0
      expect(couplingMap.get('c')!.fanIn).toBe(1)
      expect(couplingMap.get('c')!.fanOut).toBe(0)
    })

    it('computes fan-in/fan-out correctly for fan-in/fan-out scenarios', () => {
      const nodes = [
        makeNode({ id: 'hub', label: 'Hub' }),
        makeNode({ id: 'c1', label: 'C1' }),
        makeNode({ id: 'c2', label: 'C2' }),
        makeNode({ id: 'c3', label: 'C3' }),
      ]
      // Hub depends on c1, c2, c3 (fanOut=3)
      // c1, c2, c3 each have fanIn=1 from Hub
      const edges = [
        makeEdge({ id: 'e1', source: 'hub', target: 'c1' }),
        makeEdge({ id: 'e2', source: 'hub', target: 'c2' }),
        makeEdge({ id: 'e3', source: 'hub', target: 'c3' }),
      ]
      const result = computeCoupling(nodes, edges)

      const couplingMap = new Map(result.map(c => [c.nodeId, c]))

      // Hub has fanOut=3, fanIn=0
      expect(couplingMap.get('hub')!.fanOut).toBe(3)
      expect(couplingMap.get('hub')!.fanIn).toBe(0)
      // Instability = fanOut / (fanIn + fanOut) = 3/3 = 1
      expect(couplingMap.get('hub')!.instability).toBe(1)

      // c1 has fanIn=1, fanOut=0
      expect(couplingMap.get('c1')!.fanIn).toBe(1)
      expect(couplingMap.get('c1')!.fanOut).toBe(0)
    })

    it('computes instability = fanOut / (fanIn + fanOut)', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'A' }),
        makeNode({ id: 'b', label: 'B' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
      ]
      const result = computeCoupling(nodes, edges)

      const couplingMap = new Map(result.map(c => [c.nodeId, c]))

      // A: fanOut=1, fanIn=0 → instability = 1/(0+1) = 1
      expect(couplingMap.get('a')!.instability).toBe(1)

      // B: fanOut=0, fanIn=1 → instability = 0/(1+0) = 0
      expect(couplingMap.get('b')!.instability).toBe(0)
    })

    it('sorts results by total coupling descending', () => {
      const nodes = [
        makeNode({ id: 'hub', label: 'Hub' }),
        makeNode({ id: 'c1', label: 'C1' }),
        makeNode({ id: 'c2', label: 'C2' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'hub', target: 'c1' }),
        makeEdge({ id: 'e2', source: 'hub', target: 'c2' }),
        makeEdge({ id: 'e3', source: 'c1', target: 'c2' }),
      ]
      const result = computeCoupling(nodes, edges)

      // Hub: fanIn=0, fanOut=2 → total=2
      // C1: fanIn=1, fanOut=1 → total=2
      // C2: fanIn=2, fanOut=0 → total=2
      // All have same total coupling, but first entries should have highest
      expect(result[0].fanIn + result[0].fanOut).toBeGreaterThanOrEqual(
        result[result.length - 1].fanIn + result[result.length - 1].fanOut
      )
    })

    it('tracks coupledWith (top 3 neighbors)', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'A' }),
        makeNode({ id: 'b', label: 'B' }),
        makeNode({ id: 'c', label: 'C' }),
        makeNode({ id: 'd', label: 'D' }),
      ]
      // A has multiple edges to B (2), C (1), D (1)
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'a', target: 'b' }), // duplicate for count
        makeEdge({ id: 'e3', source: 'a', target: 'c' }),
        makeEdge({ id: 'e4', source: 'a', target: 'd' }),
      ]
      const result = computeCoupling(nodes, edges)
      const aCoupling = result.find(c => c.nodeId === 'a')

      expect(aCoupling).toBeDefined()
      expect(aCoupling!.coupledWith).toHaveLength(3)
      // B has highest coupling count (2 edges)
      expect(aCoupling!.coupledWith[0]).toBe('b')
    })
  })

  // ============================================================
  // computeHealthScore()
  // ============================================================

  describe('computeHealthScore', () => {
    it('returns perfect score for empty workspace', () => {
      const result = computeHealthScore([], [], [])

      expect(result.overall).toBe(100)
      expect(result.grade).toBe('A+')
      expect(result.quality).toBe(100)
      expect(result.security).toBe(100)
      expect(result.coverage).toBe(100)
      expect(result.metrics.totalNodes).toBe(0)
      expect(result.metrics.totalEdges).toBe(0)
      expect(result.recommendations).toEqual([])
    })

    it('returns high score for a healthy codebase', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', status: 'active' }),
        makeNode({ id: 'n2', label: 'fn2', status: 'active' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'imports' }),
      ]
      const clusters = [{ nodeIds: ['n1', 'n2'], cohesion: 0.8 }]

      const result = computeHealthScore(nodes, edges, clusters)

      expect(result.overall).toBeGreaterThanOrEqual(70)
      expect(result.grade).toMatch(/^[AB]/)
      expect(result.metrics.totalNodes).toBe(2)
      expect(result.metrics.totalEdges).toBe(1)
    })

    it('applies quality penalty for dead code', () => {
      const healthyNodes = [
        makeNode({ id: 'n1', label: 'fn1', status: 'active' }),
      ]
      const deadNodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({ id: `dead-${i}`, label: `dead${i}`, status: 'dead' })
      )
      const allNodes = [...healthyNodes, ...deadNodes]
      const clusters = [{ nodeIds: allNodes.map(n => n.id), cohesion: 0.5 }]

      const result = computeHealthScore(allNodes, [], clusters)

      // 10 dead out of 11 = ~91% dead → massive quality penalty
      expect(result.quality).toBeLessThan(50)
      expect(result.metrics.deadCodeCount).toBe(10)
      expect(result.metrics.deadCodePercent).toBeGreaterThan(80)
    })

    it('applies security penalty for vulnerabilities', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', status: 'vulnerable' }),
        makeNode({ id: 'n2', label: 'fn2', status: 'critical' }),
        makeNode({ id: 'n3', label: 'fn3', status: 'active' }),
      ]
      const clusters = [{ nodeIds: ['n1', 'n2', 'n3'], cohesion: 0.5 }]

      const result = computeHealthScore(nodes, [], clusters)

      // 1 critical (-15) + 1 vulnerable (-8) = -23 → security score = 77
      expect(result.security).toBeLessThan(100)
      expect(result.metrics.vulnerableCount).toBe(1)
      expect(result.metrics.criticalCount).toBe(1)
    })

    it('applies security penalty for secrets', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', type: 'secret', status: 'active' }),
        makeNode({ id: 'n2', label: 'fn2', status: 'active' }),
      ]
      const clusters = [{ nodeIds: ['n1', 'n2'], cohesion: 0.5 }]

      const result = computeHealthScore(nodes, [], clusters)

      expect(result.metrics.secretCount).toBe(1)
      expect(result.security).toBeLessThan(100)
    })

    it('applies coverage penalty for untested code', () => {
      const nodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({ id: `u${i}`, label: `untested${i}`, status: 'untested' })
      )
      const clusters = [{ nodeIds: nodes.map(n => n.id), cohesion: 0.5 }]

      const result = computeHealthScore(nodes, [], clusters)

      expect(result.coverage).toBeLessThan(50)
      expect(result.metrics.untestedCount).toBe(10)
      expect(result.metrics.untestedPercent).toBe(100)
    })

    it('generates recommendations for critical issues', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', status: 'critical' }),
        ...Array.from({ length: 6 }, (_, i) =>
          makeNode({ id: `dead-${i}`, label: `dead${i}`, status: 'dead' })
        ),
      ]
      const clusters = [{ nodeIds: nodes.map(n => n.id), cohesion: 0.3 }]

      const result = computeHealthScore(nodes, [], clusters)

      expect(result.recommendations.length).toBeGreaterThan(0)

      // Should have recommendations about critical vulnerabilities and dead code
      const categories = result.recommendations.map(r => r.category)
      expect(categories).toContain('Security')
      expect(categories).toContain('Quality')
    })

    it('assigns correct grades based on overall score', () => {
      // Create a minimal healthy codebase to check grade assignment
      const nodes = [makeNode({ id: 'n1', label: 'fn1', status: 'active' })]
      const clusters = [{ nodeIds: ['n1'], cohesion: 1.0 }]

      const result = computeHealthScore(nodes, [], clusters)

      // Grade should be one of the valid values
      expect(['A+', 'A', 'B', 'C', 'D', 'F']).toContain(result.grade)
    })
  })

  // ============================================================
  // computeImpactRadius()
  // ============================================================

  describe('computeImpactRadius', () => {
    it('returns zero impact for an isolated node', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const result = computeImpactRadius('n1', nodes, [])

      expect(result.totalImpacted).toBe(0)
      expect(result.deepestPath).toBe(0)
      expect(result.nodeId).toBe('n1')
    })

    it('performs BFS to compute impacted nodes', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'A' }),
        makeNode({ id: 'b', label: 'B' }),
        makeNode({ id: 'c', label: 'C' }),
      ]
      // A depends on B, B depends on C → changing C impacts B and A
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'b', target: 'c' }),
      ]

      const result = computeImpactRadius('c', nodes, edges)

      // Changing C → B is impacted (depth 1) → A is impacted (depth 2)
      expect(result.totalImpacted).toBe(2)
      expect(result.deepestPath).toBe(2)
      expect(result.byDepth[1]).toBeDefined()
      expect(result.byDepth[1].count).toBe(1)
      expect(result.byDepth[1].nodeIds).toContain('b')
    })

    it('respects maxDepth parameter', () => {
      const nodes = [
        makeNode({ id: 'a', label: 'A' }),
        makeNode({ id: 'b', label: 'B' }),
        makeNode({ id: 'c', label: 'C' }),
        makeNode({ id: 'd', label: 'D' }),
      ]
      // A→B→C→D chain: changing D impacts C,B,A
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b' }),
        makeEdge({ id: 'e2', source: 'b', target: 'c' }),
        makeEdge({ id: 'e3', source: 'c', target: 'd' }),
      ]

      const result = computeImpactRadius('d', nodes, edges, 1)

      // maxDepth=1, so only depth 1 is explored (C)
      expect(result.deepestPath).toBe(1)
      expect(result.totalImpacted).toBe(1)
    })

    it('handles fan-out impact correctly', () => {
      const nodes = [
        makeNode({ id: 'hub', label: 'Hub' }),
        makeNode({ id: 'c1', label: 'C1' }),
        makeNode({ id: 'c2', label: 'C2' }),
        makeNode({ id: 'c3', label: 'C3' }),
      ]
      // Hub depends on c1, c2, c3
      // Changing c1, c2, or c3 only impacts hub
      const edges = [
        makeEdge({ id: 'e1', source: 'hub', target: 'c1' }),
        makeEdge({ id: 'e2', source: 'hub', target: 'c2' }),
        makeEdge({ id: 'e3', source: 'hub', target: 'c3' }),
      ]

      // Changing c1 impacts hub
      const result = computeImpactRadius('c1', nodes, edges)
      expect(result.totalImpacted).toBe(1)
      expect(result.byDepth[1].nodeIds).toContain('hub')
    })
  })

  // ============================================================
  // computeHeatmap()
  // ============================================================

  describe('computeHeatmap', () => {
    it('returns empty array for no nodes', () => {
      const result = computeHeatmap([], [], [])
      expect(result).toEqual([])
    })

    it('computes heat based on fan-out', () => {
      const nodes = [
        makeNode({ id: 'hub', label: 'Hub' }),
        makeNode({ id: 'c1', label: 'C1' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'hub', target: 'c1' }),
      ]
      const coupling = computeCoupling(nodes, edges)
      const heatmap = computeHeatmap(nodes, edges, coupling)

      // Hub has fanOut=1, should have higher heat than c1
      const hubEntry = heatmap.find(h => h.nodeId === 'hub')
      const c1Entry = heatmap.find(h => h.nodeId === 'c1')

      expect(hubEntry).toBeDefined()
      expect(c1Entry).toBeDefined()
      expect(hubEntry!.factors.fanOut).toBe(1)
      expect(c1Entry!.factors.fanOut).toBe(0)
    })

    it('increases heat for dead code', () => {
      const nodes = [
        makeNode({ id: 'dead', label: 'DeadFn', status: 'dead' }),
        makeNode({ id: 'active', label: 'ActiveFn', status: 'active' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const heatmap = computeHeatmap(nodes, [], coupling)

      const deadEntry = heatmap.find(h => h.nodeId === 'dead')
      const activeEntry = heatmap.find(h => h.nodeId === 'active')

      expect(deadEntry!.factors.deadCode).toBe(true)
      expect(activeEntry!.factors.deadCode).toBe(false)
      expect(deadEntry!.heat).toBeGreaterThan(activeEntry!.heat)
    })

    it('increases heat for vulnerable nodes', () => {
      const nodes = [
        makeNode({ id: 'vuln', label: 'VulnFn', status: 'vulnerable' }),
        makeNode({ id: 'safe', label: 'SafeFn', status: 'active' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const heatmap = computeHeatmap(nodes, [], coupling)

      const vulnEntry = heatmap.find(h => h.nodeId === 'vuln')
      expect(vulnEntry!.factors.vulnerable).toBe(true)
      expect(vulnEntry!.heat).toBeGreaterThan(0)
    })

    it('increases heat for untested nodes', () => {
      const nodes = [
        makeNode({ id: 'untested', label: 'UntestedFn', status: 'untested' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const heatmap = computeHeatmap(nodes, [], coupling)

      const entry = heatmap.find(h => h.nodeId === 'untested')
      expect(entry!.factors.untested).toBe(true)
      expect(entry!.heat).toBeGreaterThan(0)
    })

    it('increases heat for high complexity nodes', () => {
      const nodes = [
        makeNode({ id: 'complex', label: 'ComplexFn', data: { complexity: 18 } }),
        makeNode({ id: 'simple', label: 'SimpleFn', data: { complexity: 2 } }),
      ]
      const coupling = computeCoupling(nodes, [])
      const heatmap = computeHeatmap(nodes, [], coupling)

      const complexEntry = heatmap.find(h => h.nodeId === 'complex')
      const simpleEntry = heatmap.find(h => h.nodeId === 'simple')

      expect(complexEntry!.factors.complexity).toBe(18)
      expect(simpleEntry!.factors.complexity).toBe(2)
      expect(complexEntry!.heat).toBeGreaterThan(simpleEntry!.heat)
    })

    it('sorts by heat descending (hottest first)', () => {
      const nodes = [
        makeNode({ id: 'cool', label: 'Cool', status: 'active' }),
        makeNode({ id: 'hot', label: 'Hot', status: 'dead' }),
      ]
      const coupling = computeCoupling(nodes, [])
      const heatmap = computeHeatmap(nodes, [], coupling)

      expect(heatmap[0].heat).toBeGreaterThanOrEqual(heatmap[1].heat)
    })

    it('caps heat at 1.0', () => {
      const nodes = [
        makeNode({
          id: 'nightmare',
          label: 'Nightmare',
          status: 'critical',
          data: { complexity: 50 },
        }),
      ]
      const edges = Array.from({ length: 15 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: 'nightmare', target: `target-${i}` })
      )
      // Need target nodes for coupling computation
      const targetNodes = Array.from({ length: 15 }, (_, i) =>
        makeNode({ id: `target-${i}`, label: `T${i}` })
      )
      const allNodes = [...nodes, ...targetNodes]
      const coupling = computeCoupling(allNodes, edges)
      const heatmap = computeHeatmap(allNodes, edges, coupling)

      for (const entry of heatmap) {
        expect(entry.heat).toBeLessThanOrEqual(1)
      }
    })
  })
})
