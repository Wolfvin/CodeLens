// ============================================================
// ClusterEngine Unit Tests
// ============================================================

import { clusterEngine } from '@/lib/clusterEngine'
import type { GraphNode, GraphEdge, Cluster } from '@/types/neural'

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
    type: 'imports',
    weight: 1,
    status: 'active',
    ...overrides,
  }
}

// ---- Test Suite ----

describe('ClusterEngine', () => {
  beforeEach(() => {
    // Reset cluster engine state between tests
    clusterEngine.computeClusters([], [])
  })

  // ============================================================
  // computeClusters() with empty input
  // ============================================================

  describe('computeClusters with empty input', () => {
    it('returns empty array when no nodes are provided', () => {
      const clusters = clusterEngine.computeClusters([], [])
      expect(clusters).toEqual([])
    })

    it('returns empty array when edges but no nodes are provided', () => {
      const edges = [makeEdge({ id: 'e1', source: 'a', target: 'b' })]
      const clusters = clusterEngine.computeClusters([], edges)
      expect(clusters).toEqual([])
    })
  })

  // ============================================================
  // computeClusters() with a single node
  // ============================================================

  describe('computeClusters with a single node', () => {
    it('creates a single cluster for a single node', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/utils.ts' })]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters.length).toBe(1)
      expect(clusters[0].nodeIds).toEqual(['n1'])
    })

    it('assigns a cluster id', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/utils.ts' })]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters[0].id).toMatch(/^cluster-/)
    })

    it('has zero cohesion when no edges exist', () => {
      const nodes = [makeNode({ id: 'n1', label: 'fn1', file: 'src/utils.ts' })]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters[0].cohesion).toBe(0)
    })
  })

  // ============================================================
  // computeClusters() with nodes in the same directory
  // ============================================================

  describe('computeClusters with nodes in same directory', () => {
    it('groups nodes in the same directory into one cluster', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/components/Button.tsx' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/components/Card.tsx' }),
        makeNode({ id: 'n3', label: 'fn3', file: 'src/components/Modal.tsx' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters.length).toBe(1)
      expect(clusters[0].nodeIds).toHaveLength(3)
      expect(clusters[0].nodeIds).toEqual(expect.arrayContaining(['n1', 'n2', 'n3']))
    })

    it('computes high cohesion when nodes have internal edges', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/utils/helpers.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/utils/format.ts' }),
      ]
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'imports' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, edges)

      // Internal edge → cohesion should be 1.0 (only internal, no external)
      expect(clusters[0].cohesion).toBe(1)
    })
  })

  // ============================================================
  // computeClusters() with nodes in different directories
  // ============================================================

  describe('computeClusters with nodes in different directories', () => {
    it('creates separate clusters for different directories with no cross-group imports', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/auth/login.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/api/routes.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters.length).toBe(2)
    })

    it('merges clusters when cross-group import count meets threshold', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/auth/login.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/auth/session.ts' }),
        makeNode({ id: 'n3', label: 'fn3', file: 'src/api/routes.ts' }),
        makeNode({ id: 'n4', label: 'fn4', file: 'src/api/middleware.ts' }),
      ]
      // Two imports edges crossing from auth/ to api/ → meets IMPORT_MERGE_THRESHOLD (2)
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n3', type: 'imports' }),
        makeEdge({ id: 'e2', source: 'n2', target: 'n4', type: 'imports' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, edges)

      // Should merge into a single cluster since cross-group import count >= 2
      expect(clusters.length).toBe(1)
      expect(clusters[0].nodeIds).toHaveLength(4)
    })

    it('does not merge clusters when cross-group import count is below threshold', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/auth/login.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/api/routes.ts' }),
      ]
      // Only one import edge crossing → below threshold of 2
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'imports' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, edges)

      expect(clusters.length).toBe(2)
    })
  })

  // ============================================================
  // Cohesion calculation
  // ============================================================

  describe('cohesion calculation', () => {
    it('returns 0 when no edges exist', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/a.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/b.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      // Two separate clusters, each with no edges
      for (const cluster of clusters) {
        expect(cluster.cohesion).toBe(0)
      }
    })

    it('computes cohesion as internalEdges / (internalEdges + externalEdges)', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/cluster1/a.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/cluster1/b.ts' }),
        makeNode({ id: 'n3', label: 'fn3', file: 'src/cluster2/c.ts' }),
      ]
      // 1 internal edge (n1→n2) + 1 external edge (n1→n3)
      const edges = [
        makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'imports' }),
        makeEdge({ id: 'e2', source: 'n1', target: 'n3', type: 'imports' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, edges)

      // cluster1 has: 1 internal (n1→n2) + 1 external (n1→n3) → cohesion = 1/2 = 0.5
      const cluster1 = clusters.find(c => c.nodeIds.includes('n1'))
      expect(cluster1).toBeDefined()
      expect(cluster1!.cohesion).toBeCloseTo(0.5, 5)

      // cluster2 has: 0 internal + 1 external (n1→n3) → cohesion = 0/1 = 0
      const cluster2 = clusters.find(c => c.nodeIds.includes('n3'))
      expect(cluster2).toBeDefined()
      expect(cluster2!.cohesion).toBe(0)
    })
  })

  // ============================================================
  // REGION_PATTERNS matching
  // ============================================================

  describe('REGION_PATTERNS matching', () => {
    it('assigns Auth label for nodes in auth/ directory', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'login', file: 'src/auth/login.ts' }),
        makeNode({ id: 'n2', label: 'session', file: 'src/auth/session.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters.length).toBe(1)
      // Auth pattern matches "auth" in file path
      expect(clusters[0].label).toBe('Auth')
      expect(clusters[0].icon).toBe('🔐')
    })

    it('assigns API label for nodes in api/ directory', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'getUsers', file: 'src/api/routes.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters[0].label).toBe('API')
      expect(clusters[0].icon).toBe('📡')
    })

    it('assigns UI label for nodes with component in path/label', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'Button', type: 'component', file: 'src/components/Button.tsx' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters[0].label).toBe('UI')
      expect(clusters[0].icon).toBe('🎨')
    })

    it('assigns Tests label for nodes in test files', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'testProcess', type: 'test', file: 'src/__tests__/process.test.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      expect(clusters[0].label).toBe('Tests')
      expect(clusters[0].icon).toBe('🧪')
    })

    it('uses directory name as fallback when no pattern matches', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'myCustomFn', file: 'src/myzone/process.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      // Fallback uses parent dir name "myzone"
      expect(clusters[0].label).toBe('myzone')
      expect(clusters[0].icon).toBe('📁')
    })
  })

  // ============================================================
  // updateIncremental
  // ============================================================

  describe('updateIncremental', () => {
    it('clears all clusters when edges change', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/a.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/b.ts' }),
      ]
      clusterEngine.computeClusters(nodes, [])
      expect(clusterEngine.clusters.size).toBeGreaterThan(0)

      clusterEngine.updateIncremental([], ['e1'])
      expect(clusterEngine.clusters.size).toBe(0)
    })

    it('removes clusters containing changed nodes', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/a.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/b.ts' }),
      ]
      clusterEngine.computeClusters(nodes, [])
      const initialSize = clusterEngine.clusters.size

      clusterEngine.updateIncremental(['n1'], [])
      // The cluster containing n1 should be removed
      expect(clusterEngine.clusters.size).toBeLessThan(initialSize)
    })

    it('does nothing when no changes provided', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/a.ts' }),
      ]
      clusterEngine.computeClusters(nodes, [])
      const initialSize = clusterEngine.clusters.size

      clusterEngine.updateIncremental([], [])
      expect(clusterEngine.clusters.size).toBe(initialSize)
    })
  })

  // ============================================================
  // Sorting behavior
  // ============================================================

  describe('cluster sorting', () => {
    it('sorts clusters by size descending (largest first)', () => {
      const nodes = [
        makeNode({ id: 'n1', label: 'fn1', file: 'src/alpha/a.ts' }),
        makeNode({ id: 'n2', label: 'fn2', file: 'src/alpha/b.ts' }),
        makeNode({ id: 'n3', label: 'fn3', file: 'src/alpha/c.ts' }),
        makeNode({ id: 'n4', label: 'fn4', file: 'src/beta/x.ts' }),
      ]
      const clusters = clusterEngine.computeClusters(nodes, [])

      // alpha cluster has 3 nodes, beta has 1 → alpha first
      expect(clusters[0].nodeIds.length).toBeGreaterThanOrEqual(clusters[1].nodeIds.length)
    })
  })
})
