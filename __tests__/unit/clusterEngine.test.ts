// ============================================================
// ClusterEngine Unit Tests
// ============================================================

import { clusterEngine } from '@/lib/clusterEngine'
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

describe('ClusterEngine', () => {
  // ============================================================
  // computeClusters — basic scenarios
  // ============================================================

  describe('computeClusters', () => {
    it('returns empty array for empty nodes', () => {
      const result = clusterEngine.computeClusters([], [])
      expect(result).toEqual([])
    })

    it('creates a single cluster for nodes in the same directory', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts', label: 'login' }),
        makeNode({ id: 'b', file: 'src/api/handler.ts', label: 'handleRequest' }),
      ]
      const edges: GraphEdge[] = []
      const result = clusterEngine.computeClusters(nodes, edges)
      expect(result.length).toBe(1)
      expect(result[0].nodeIds).toEqual(expect.arrayContaining(['a', 'b']))
    })

    it('creates separate clusters for nodes in different directories', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/ui/Button.tsx' }),
      ]
      const edges: GraphEdge[] = []
      const result = clusterEngine.computeClusters(nodes, edges)
      expect(result.length).toBe(2)
      // Each cluster should have exactly one node
      const allNodeIds = result.flatMap(c => c.nodeIds)
      expect(allNodeIds).toEqual(expect.arrayContaining(['a', 'b']))
    })

    it('merges clusters with enough cross-group import edges', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/api/handler.ts' }),
        makeNode({ id: 'c', file: 'src/ui/Button.tsx' }),
        makeNode({ id: 'd', file: 'src/ui/Modal.tsx' }),
      ]
      // 2 import edges between src/api and src/ui → should merge
      const edges = [
        makeEdge({ id: 'e1', source: 'c', target: 'a', type: 'imports' }),
        makeEdge({ id: 'e2', source: 'd', target: 'b', type: 'imports' }),
      ]
      const result = clusterEngine.computeClusters(nodes, edges)
      // Should be merged into 1 cluster
      expect(result.length).toBe(1)
      expect(result[0].nodeIds.length).toBe(4)
    })

    it('does not merge clusters with insufficient import edges', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/api/handler.ts' }),
        makeNode({ id: 'c', file: 'src/ui/Button.tsx' }),
        makeNode({ id: 'd', file: 'src/ui/Modal.tsx' }),
      ]
      // Only 1 import edge → below threshold of 2
      const edges = [
        makeEdge({ id: 'e1', source: 'c', target: 'a', type: 'imports' }),
      ]
      const result = clusterEngine.computeClusters(nodes, edges)
      expect(result.length).toBe(2)
    })

    it('groups nodes without a file into __no_file__ bucket', () => {
      const nodes = [
        makeNode({ id: 'a' }), // no file
        makeNode({ id: 'b' }), // no file
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      // Both should end up in one cluster (the no-file bucket)
      expect(result.length).toBe(1)
      expect(result[0].nodeIds).toEqual(expect.arrayContaining(['a', 'b']))
    })

    it('assigns semantic labels based on REGION_PATTERNS', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/auth/login.ts', label: 'authenticate' }),
        makeNode({ id: 'b', file: 'src/auth/session.ts', label: 'createSession' }),
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      // Should match "auth" pattern → label "Auth"
      expect(result[0].label).toBe('Auth')
      expect(result[0].icon).toBe('🔐')
    })

    it('uses directory name as fallback label when no pattern matches', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/custom/magic.ts', label: 'doMagic' }),
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      // No pattern matches → fallback to directory name
      expect(result[0].label).toBe('custom')
    })

    it('computes cohesion based on internal vs external edges', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/api/handler.ts' }),
        makeNode({ id: 'c', file: 'src/ui/Button.tsx' }),
      ]
      // 1 internal edge (a→b), 1 external edge (c→a)
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b', type: 'calls' }),
        makeEdge({ id: 'e2', source: 'c', target: 'a', type: 'calls' }),
      ]
      const result = clusterEngine.computeClusters(nodes, edges)
      // The api cluster has 1 internal, 1 external edge → cohesion = 1/(1+1) = 0.5
      const apiCluster = result.find(c => c.nodeIds.includes('a') && c.nodeIds.includes('b'))
      expect(apiCluster).toBeDefined()
      expect(apiCluster!.cohesion).toBe(0.5)
    })

    it('returns cohesion 0 for clusters with only external edges', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/ui/Button.tsx' }),
      ]
      // Only external edges (between different dirs)
      const edges = [
        makeEdge({ id: 'e1', source: 'a', target: 'b', type: 'calls' }),
      ]
      const result = clusterEngine.computeClusters(nodes, edges)
      // Each cluster has only external edges
      for (const cluster of result) {
        expect(cluster.cohesion).toBe(0)
      }
    })

    it('sorts clusters by size descending then cohesion descending', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/api/auth.ts' }),
        makeNode({ id: 'b', file: 'src/api/handler.ts' }),
        makeNode({ id: 'c', file: 'src/api/routes.ts' }),
        makeNode({ id: 'd', file: 'src/ui/Button.tsx' }),
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      // First cluster should be larger (3 nodes in api) or equal size with higher cohesion
      expect(result[0].nodeIds.length).toBeGreaterThanOrEqual(result[1]?.nodeIds.length ?? 0)
    })

    it('detects UI region for component nodes', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'src/components/Button.tsx', label: 'Button', type: 'component' }),
        makeNode({ id: 'b', file: 'src/components/Modal.tsx', label: 'Modal', type: 'component' }),
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      // Should match UI pattern
      expect(result[0].label).toBe('UI')
    })

    it('handles root-level files (no directory separator)', () => {
      const nodes = [
        makeNode({ id: 'a', file: 'App.tsx', label: 'App' }),
      ]
      const result = clusterEngine.computeClusters(nodes, [])
      expect(result.length).toBe(1)
      expect(result[0].nodeIds).toContain('a')
    })
  })
})
