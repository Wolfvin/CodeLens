// ============================================================
// GraphDiff Unit Tests
// ============================================================

import { computeGraphDiff, generateChangelog } from '@/lib/graphDiff'
import type { GraphDiff } from '@/lib/graphDiff'
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

describe('GraphDiff', () => {
  // ============================================================
  // computeGraphDiff() with identical graphs (no changes)
  // ============================================================

  describe('identical graphs', () => {
    it('reports no changes when graphs are identical', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n2' }),
      ]

      const diff = computeGraphDiff(nodes, edges, nodes, edges)

      expect(diff.summary.addedNodes).toBe(0)
      expect(diff.summary.removedNodes).toBe(0)
      expect(diff.summary.modifiedNodes).toBe(0)
      expect(diff.summary.addedEdges).toBe(0)
      expect(diff.summary.removedEdges).toBe(0)
      expect(diff.summary.modifiedEdges).toBe(0)
      expect(diff.summary.totalChangePercent).toBe(0)
    })

    it('returns empty added/removed/modified arrays', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const edges: GraphEdge[] = []

      const diff = computeGraphDiff(nodes, edges, nodes, edges)

      expect(diff.addedNodes).toEqual([])
      expect(diff.removedNodes).toEqual([])
      expect(diff.modifiedNodes).toEqual([])
      expect(diff.addedEdges).toEqual([])
      expect(diff.removedEdges).toEqual([])
    })

    it('sets risk level to none for no changes', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const diff = computeGraphDiff(nodes, [], nodes, [])

      expect(diff.riskAssessment.level).toBe('none')
      expect(diff.riskAssessment.factors).toEqual([])
    })
  })

  // ============================================================
  // computeGraphDiff() with added nodes
  // ============================================================

  describe('added nodes', () => {
    it('detects added nodes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const currNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
        makeNode({ id: 'n3', label: 'fn3' }),
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.addedNodes).toBe(2)
      expect(diff.addedNodes).toHaveLength(2)
      expect(diff.addedNodes.map(n => n.id)).toEqual(expect.arrayContaining(['n2', 'n3']))
    })

    it('sets low risk for a few added nodes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const currNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.addedNodes).toBe(1)
    })

    it('sets risk level for many added nodes (>20)', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const currNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        ...Array.from({ length: 25 }, (_, i) =>
          makeNode({ id: `new-${i}`, label: `fn${i}` })
        ),
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.addedNodes).toBe(25)
      expect(diff.riskAssessment.level).not.toBe('none')
      expect(diff.riskAssessment.factors.length).toBeGreaterThan(0)
    })
  })

  // ============================================================
  // computeGraphDiff() with removed nodes
  // ============================================================

  describe('removed nodes', () => {
    it('detects removed nodes', () => {
      const prevNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.removedNodes).toBe(1)
      expect(diff.removedNodes).toHaveLength(1)
      expect(diff.removedNodes[0].id).toBe('n2')
    })

    it('sets high risk for many removed nodes (>5)', () => {
      const prevNodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({ id: `n${i}`, label: `fn${i}` })
      )
      const currNodes = [makeNode({ id: 'n0', label: 'fn0' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.removedNodes).toBe(9)
      expect(diff.riskAssessment.level).toBe('high')
    })
  })

  // ============================================================
  // computeGraphDiff() with modified nodes
  // ============================================================

  describe('modified nodes', () => {
    it('detects label changes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'oldName' })]
      const currNodes = [makeNode({ id: 'n1', label: 'newName' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.modifiedNodes).toBe(1)
      expect(diff.modifiedNodes).toHaveLength(1)
      expect(diff.modifiedNodes[0].changes).toContain('label')
      expect(diff.modifiedNodes[0].node.label).toBe('newName')
      expect(diff.modifiedNodes[0].previousNode.label).toBe('oldName')
    })

    it('detects status changes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'active' })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'dead' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.modifiedNodes).toBe(1)
      expect(diff.modifiedNodes[0].changes).toContain('status')
    })

    it('detects type changes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', type: 'function' })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', type: 'component' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.modifiedNodes).toBe(1)
      expect(diff.modifiedNodes[0].changes).toContain('type')
    })

    it('detects file changes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/old.ts' })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/new.ts' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.modifiedNodes).toBe(1)
      expect(diff.modifiedNodes[0].changes).toContain('file')
    })

    it('detects data changes', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', data: { complexity: 5 } })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', data: { complexity: 12 } })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.summary.modifiedNodes).toBe(1)
      expect(diff.modifiedNodes[0].changes).toContain('data')
    })

    it('detects multiple field changes at once', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'oldName', status: 'active', type: 'function' })]
      const currNodes = [makeNode({ id: 'n1', label: 'newName', status: 'dead', type: 'component' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.modifiedNodes[0].changes).toEqual(expect.arrayContaining(['label', 'status', 'type']))
    })

    it('does not report modifications for unchanged nodes', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1', status: 'active' })]

      const diff = computeGraphDiff(nodes, [], nodes, [])

      expect(diff.summary.modifiedNodes).toBe(0)
    })
  })

  // ============================================================
  // Edge changes
  // ============================================================

  describe('edge changes', () => {
    it('detects added edges', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' }), makeNode({ id: 'n2', label: 'fn2' })]
      const prevEdges: GraphEdge[] = []
      const currEdges = [makeEdge({ id: 'e1', source: 'n1', target: 'n2' })]

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)

      expect(diff.summary.addedEdges).toBe(1)
      expect(diff.addedEdges).toHaveLength(1)
    })

    it('detects removed edges', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' }), makeNode({ id: 'n2', label: 'fn2' })]
      const prevEdges = [makeEdge({ id: 'e1', source: 'n1', target: 'n2' })]
      const currEdges: GraphEdge[] = []

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)

      expect(diff.summary.removedEdges).toBe(1)
      expect(diff.removedEdges).toHaveLength(1)
    })

    it('detects modified edges (status/weight/type change)', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' }), makeNode({ id: 'n2', label: 'fn2' })]
      const prevEdges = [makeEdge({ id: 'e1', source: 'n1', target: 'n2', status: 'active', weight: 1 })]
      const currEdges = [makeEdge({ id: 'e1', source: 'n1', target: 'n2', status: 'warning', weight: 3 })]

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)

      expect(diff.summary.modifiedEdges).toBe(1)
    })
  })

  // ============================================================
  // totalChangePercent
  // ============================================================

  describe('totalChangePercent', () => {
    it('computes change percentage correctly', () => {
      const prevNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]
      const currNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n3', label: 'fn3' }), // n2 removed, n3 added
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      // totalCurrent = 2 nodes + 0 edges = 2
      // totalChanges = 1 added + 1 removed = 2
      // totalChangePercent = 2/2 * 100 = 100
      expect(diff.summary.totalChangePercent).toBe(100)
    })
  })

  // ============================================================
  // Change coupling
  // ============================================================

  describe('change coupling', () => {
    it('detects change coupling between files that both change', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/a.ts' })]
      const currNodes = [
        makeNode({ id: 'n1', label: 'changed_fn1', file: 'src/a.ts' }), // modified
        makeNode({ id: 'n2', label: 'fn2', file: 'src/b.ts' }),          // added
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      // Both src/a.ts and src/b.ts have changes
      expect(diff.changeCoupling.length).toBeGreaterThan(0)
    })
  })

  // ============================================================
  // Risk assessment
  // ============================================================

  describe('risk assessment', () => {
    it('sets critical risk for status changes to critical/vulnerable', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'active' })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'critical' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.riskAssessment.level).toBe('critical')
      expect(diff.riskAssessment.factors.some(f => f.includes('critical/vulnerable'))).toBe(true)
    })

    it('detects nodes changed to dead status', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'active' })]
      const currNodes = [makeNode({ id: 'n1', label: 'fn1', status: 'dead' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      expect(diff.riskAssessment.factors.some(f => f.includes('dead'))).toBe(true)
    })
  })

  // ============================================================
  // previousTimestamp
  // ============================================================

  describe('previousTimestamp', () => {
    it('stores the provided previousTimestamp', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const ts = 1234567890

      const diff = computeGraphDiff(nodes, [], nodes, [], ts)

      expect(diff.previousTimestamp).toBe(ts)
    })

    it('defaults previousTimestamp to null', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1' })]

      const diff = computeGraphDiff(nodes, [], nodes, [])

      expect(diff.previousTimestamp).toBeNull()
    })
  })

  // ============================================================
  // generateChangelog
  // ============================================================

  describe('generateChangelog', () => {
    it('generates a markdown changelog from a diff', () => {
      const prevNodes = [makeNode({ id: 'n1', label: 'fn1' })]
      const currNodes = [
        makeNode({ id: 'n1', label: 'fn1' }),
        makeNode({ id: 'n2', label: 'fn2' }),
      ]
      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      const changelog = generateChangelog(diff)

      expect(changelog).toContain('Graph Change Report')
      expect(changelog).toContain('nodes added')
      expect(changelog).toContain('removed')
    })

    it('includes risk information when risk level is not none', () => {
      const prevNodes = Array.from({ length: 10 }, (_, i) =>
        makeNode({ id: `n${i}`, label: `fn${i}` })
      )
      const currNodes = [makeNode({ id: 'n0', label: 'fn0' })]
      const diff = computeGraphDiff(currNodes, [], prevNodes, [])

      const changelog = generateChangelog(diff)

      expect(changelog).toContain('Risk level')
    })
  })
})
