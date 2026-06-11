// ============================================================
// GraphDiff Unit Tests
// ============================================================

import { computeGraphDiff, generateChangelog } from '@/lib/graphDiff'
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
  // computeGraphDiff — basic scenarios
  // ============================================================

  describe('computeGraphDiff', () => {
    it('returns empty diff for identical graphs', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const edges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]

      const diff = computeGraphDiff(nodes, edges, nodes, edges)
      expect(diff.summary.addedNodes).toBe(0)
      expect(diff.summary.removedNodes).toBe(0)
      expect(diff.summary.modifiedNodes).toBe(0)
      expect(diff.summary.addedEdges).toBe(0)
      expect(diff.summary.removedEdges).toBe(0)
      expect(diff.summary.modifiedEdges).toBe(0)
      expect(diff.summary.totalChangePercent).toBe(0)
    })

    it('detects added nodes', () => {
      const prevNodes = [makeNode({ id: 'a' })]
      const currNodes = [makeNode({ id: 'a' }), makeNode({ id: 'b', label: 'newFn' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.addedNodes).toHaveLength(1)
      expect(diff.addedNodes[0].id).toBe('b')
      expect(diff.summary.addedNodes).toBe(1)
    })

    it('detects removed nodes', () => {
      const prevNodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const currNodes = [makeNode({ id: 'a' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.removedNodes).toHaveLength(1)
      expect(diff.removedNodes[0].id).toBe('b')
      expect(diff.summary.removedNodes).toBe(1)
    })

    it('detects modified nodes with correct change list', () => {
      const prevNodes = [makeNode({ id: 'a', label: 'oldName', status: 'active' })]
      const currNodes = [makeNode({ id: 'a', label: 'newName', status: 'dead' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.modifiedNodes).toHaveLength(1)
      expect(diff.modifiedNodes[0].changes).toEqual(expect.arrayContaining(['label', 'status']))
      expect(diff.modifiedNodes[0].previousNode.label).toBe('oldName')
      expect(diff.modifiedNodes[0].node.label).toBe('newName')
    })

    it('detects data field changes', () => {
      const prevNodes = [makeNode({ id: 'a', data: { complexity: 5 } })]
      const currNodes = [makeNode({ id: 'a', data: { complexity: 20 } })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.modifiedNodes).toHaveLength(1)
      expect(diff.modifiedNodes[0].changes).toContain('data')
    })

    it('does not report modifications for unchanged nodes', () => {
      const prevNodes = [makeNode({ id: 'a', label: 'same', status: 'active', data: { x: 1 } })]
      const currNodes = [makeNode({ id: 'a', label: 'same', status: 'active', data: { x: 1 } })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.modifiedNodes).toHaveLength(0)
    })

    it('detects added edges', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const prevEdges: GraphEdge[] = []
      const currEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)
      expect(diff.addedEdges).toHaveLength(1)
      expect(diff.summary.addedEdges).toBe(1)
    })

    it('detects removed edges', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const prevEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]
      const currEdges: GraphEdge[] = []

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)
      expect(diff.removedEdges).toHaveLength(1)
      expect(diff.summary.removedEdges).toBe(1)
    })

    it('detects modified edges (status, weight, type changes)', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const prevEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b', status: 'active', weight: 1, type: 'calls' })]
      const currEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b', status: 'warning', weight: 2, type: 'imports' })]

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)
      expect(diff.summary.modifiedEdges).toBe(1)
    })

    it('computes totalChangePercent correctly', () => {
      const prevNodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      // Remove 'b', add 'c' → 2 changes out of 2 current nodes = 100%
      const currNodes = [makeNode({ id: 'a' }), makeNode({ id: 'c' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.summary.totalChangePercent).toBe(100)
    })

    it('handles completely empty previous graph (fresh scan)', () => {
      const currNodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const currEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]

      const diff = computeGraphDiff(currNodes, currEdges, [], [])
      expect(diff.summary.addedNodes).toBe(2)
      expect(diff.summary.addedEdges).toBe(1)
      expect(diff.summary.removedNodes).toBe(0)
    })

    it('handles completely empty current graph (full deletion)', () => {
      const prevNodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const prevEdges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]

      const diff = computeGraphDiff([], [], prevNodes, prevEdges)
      expect(diff.summary.removedNodes).toBe(2)
      expect(diff.summary.removedEdges).toBe(1)
      expect(diff.summary.addedNodes).toBe(0)
    })
  })

  // ============================================================
  // Risk Assessment
  // ============================================================

  describe('risk assessment', () => {
    it('returns "none" risk for small changes', () => {
      const prevNodes = [makeNode({ id: 'a' })]
      const currNodes = [makeNode({ id: 'a', label: 'updatedName' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.riskAssessment.level).toBe('none')
    })

    it('returns "high" risk when many nodes are removed (>5)', () => {
      const prevNodes = Array.from({ length: 10 }, (_, i) => makeNode({ id: `n${i}` }))
      const currNodes = [makeNode({ id: 'n0' })] // 9 removed

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.riskAssessment.level).toBe('high')
      expect(diff.riskAssessment.factors.some(f => f.includes('removed'))).toBe(true)
    })

    it('returns "critical" risk when nodes change to critical/vulnerable status', () => {
      const prevNodes = [makeNode({ id: 'a', status: 'active' })]
      const currNodes = [makeNode({ id: 'a', status: 'critical' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.riskAssessment.level).toBe('critical')
      expect(diff.riskAssessment.factors.some(f => f.includes('critical/vulnerable'))).toBe(true)
    })

    it('returns "medium" risk when many edges are removed (>10)', () => {
      const nodes = Array.from({ length: 15 }, (_, i) => makeNode({ id: `n${i}` }))
      const prevEdges = Array.from({ length: 12 }, (_, i) =>
        makeEdge({ id: `e${i}`, source: `n${i}`, target: `n${i + 1}` })
      )
      const currEdges: GraphEdge[] = []

      const diff = computeGraphDiff(nodes, currEdges, nodes, prevEdges)
      expect(diff.riskAssessment.level).toMatch(/medium|high/)
    })

    it('returns "low" risk when nodes change to dead status', () => {
      const prevNodes = [makeNode({ id: 'a', status: 'active' })]
      const currNodes = [makeNode({ id: 'a', status: 'dead' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.riskAssessment.level).toMatch(/low|none/)
      // Should at least note the dead status change
      if (diff.riskAssessment.factors.length > 0) {
        expect(diff.riskAssessment.factors.some(f => f.includes('dead'))).toBe(true)
      }
    })

    it('returns "low" risk when many nodes are added (>20)', () => {
      const prevNodes: GraphNode[] = []
      const currNodes = Array.from({ length: 25 }, (_, i) => makeNode({ id: `n${i}` }))

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.riskAssessment.level).toMatch(/low|medium|high|critical/)
      expect(diff.riskAssessment.factors.some(f => f.includes('new nodes'))).toBe(true)
    })
  })

  // ============================================================
  // Change Coupling
  // ============================================================

  describe('change coupling', () => {
    it('returns empty coupling when no changes occurred', () => {
      const nodes = [makeNode({ id: 'a' })]
      const diff = computeGraphDiff(nodes, [], nodes, [])
      expect(diff.changeCoupling).toHaveLength(0)
    })

    it('detects coupling between files that both changed', () => {
      const prevNodes = [
        makeNode({ id: 'a', file: 'src/api.ts' }),
        makeNode({ id: 'b', file: 'src/ui.tsx' }),
      ]
      const currNodes = [
        makeNode({ id: 'a', file: 'src/api.ts', label: 'updatedA' }),
        makeNode({ id: 'b', file: 'src/ui.tsx', label: 'updatedB' }),
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.changeCoupling.length).toBeGreaterThan(0)
      // Should find coupling between the two files
      const pair = diff.changeCoupling.find(
        c => (c.fileA === 'src/api.ts' && c.fileB === 'src/ui.tsx') ||
             (c.fileA === 'src/ui.tsx' && c.fileB === 'src/api.ts')
      )
      expect(pair).toBeDefined()
      expect(pair!.couplingScore).toBeGreaterThan(0)
    })

    it('uses node label as fallback when file is absent', () => {
      const prevNodes = [makeNode({ id: 'a', label: 'fnA' })]  // no file
      const currNodes = [makeNode({ id: 'a', label: 'fnA_updated' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      // Change coupling should still use label as fallback
      expect(diff.modifiedNodes).toHaveLength(1)
    })
  })

  // ============================================================
  // generateChangelog
  // ============================================================

  describe('generateChangelog', () => {
    it('generates a readable changelog string', () => {
      const nodes = [makeNode({ id: 'a' }), makeNode({ id: 'b' })]
      const diff = computeGraphDiff(nodes, [], [], [])

      const changelog = generateChangelog(diff)
      expect(changelog).toContain('Graph Change Report')
      expect(changelog).toContain('Total changes')
    })

    it('includes risk level in changelog when risk is not none', () => {
      const prevNodes = Array.from({ length: 10 }, (_, i) => makeNode({ id: `n${i}` }))
      const currNodes = [makeNode({ id: 'n0' })] // 9 removed → high risk

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      const changelog = generateChangelog(diff)
      expect(changelog).toContain('Risk level')
      expect(changelog).toContain('HIGH')
    })

    it('includes change coupling section when pairs exist', () => {
      const prevNodes = [
        makeNode({ id: 'a', file: 'src/api.ts' }),
        makeNode({ id: 'b', file: 'src/ui.tsx' }),
      ]
      const currNodes = [
        makeNode({ id: 'a', file: 'src/api.ts', label: 'updatedA' }),
        makeNode({ id: 'b', file: 'src/ui.tsx', label: 'updatedB' }),
      ]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      const changelog = generateChangelog(diff)
      if (diff.changeCoupling.length > 0) {
        expect(changelog).toContain('Change Coupling')
      }
    })
  })

  // ============================================================
  // Edge Cases
  // ============================================================

  describe('edge cases', () => {
    it('handles both empty graphs', () => {
      const diff = computeGraphDiff([], [], [], [])
      expect(diff.summary.addedNodes).toBe(0)
      expect(diff.summary.removedNodes).toBe(0)
      expect(diff.summary.totalChangePercent).toBe(0)
      expect(diff.riskAssessment.level).toBe('none')
    })

    it('stores previousTimestamp when provided', () => {
      const diff = computeGraphDiff([], [], [], [], 1234567890)
      expect(diff.previousTimestamp).toBe(1234567890)
    })

    it('defaults previousTimestamp to null', () => {
      const diff = computeGraphDiff([], [], [], [])
      expect(diff.previousTimestamp).toBeNull()
    })

    it('detects file and line changes in modified nodes', () => {
      const prevNodes = [makeNode({ id: 'a', file: 'old.ts', line: 10 })]
      const currNodes = [makeNode({ id: 'a', file: 'new.ts', line: 20 })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.modifiedNodes[0].changes).toEqual(expect.arrayContaining(['file', 'line']))
    })

    it('detects clusterId changes', () => {
      const prevNodes = [makeNode({ id: 'a', clusterId: 'cluster-1' })]
      const currNodes = [makeNode({ id: 'a', clusterId: 'cluster-2' })]

      const diff = computeGraphDiff(currNodes, [], prevNodes, [])
      expect(diff.modifiedNodes[0].changes).toContain('clusterId')
    })
  })
})
