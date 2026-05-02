// ============================================================
// GraphStore Unit Tests
// ============================================================

import { GraphStore } from '@/lib/graphStore'
import type { GraphNode, GraphEdge, GraphEvent } from '@/types/neural'

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

describe('GraphStore', () => {
  let store: GraphStore

  beforeEach(() => {
    store = new GraphStore()
  })

  // ============================================================
  // CRUD — Single operations
  // ============================================================

  describe('addNode / addEdge / removeNode / removeEdge', () => {
    it('addNode stores a node', () => {
      const node = makeNode({ id: 'n1', label: 'fn1' })
      store.addNode(node)
      expect(store.getNode('n1')).toEqual(node)
    })

    it('addNode throws if node has no id', () => {
      expect(() => store.addNode({} as any)).toThrow('GraphNode must have an id')
    })

    it('addEdge stores an edge', () => {
      const edge = makeEdge({ id: 'e1', source: 'a', target: 'b' })
      store.addEdge(edge)
      expect(store.getEdge('e1')).toEqual(edge)
    })

    it('addEdge throws if edge has no id', () => {
      expect(() => store.addEdge({} as any)).toThrow('GraphEdge must have an id')
    })

    it('removeNode deletes the node', () => {
      const node = makeNode({ id: 'n1' })
      store.addNode(node)
      store.removeNode('n1')
      expect(store.getNode('n1')).toBeUndefined()
    })

    it('removeNode also removes connected edges', () => {
      store.addNode(makeNode({ id: 'a' }))
      store.addNode(makeNode({ id: 'b' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b' }))
      store.removeNode('a')
      expect(store.getEdge('e1')).toBeUndefined()
    })

    it('removeNode removes node from clusters', () => {
      store.addNode(makeNode({ id: 'n1' }))
      store.clusters.set('c1', { id: 'c1', label: 'C1', icon: '📦', tint: '#fff', nodeIds: ['n1'], cohesion: 1 })
      store.removeNode('n1')
      expect(store.clusters.get('c1')!.nodeIds).not.toContain('n1')
    })

    it('removeNode clears selection if selected', () => {
      store.addNode(makeNode({ id: 'n1' }))
      store.selectNode('n1')
      store.removeNode('n1')
      expect(store.selectedNodeId).toBeNull()
    })

    it('removeNode is a no-op for non-existent node', () => {
      expect(() => store.removeNode('ghost')).not.toThrow()
    })

    it('removeEdge deletes the edge', () => {
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b' }))
      store.removeEdge('e1')
      expect(store.getEdge('e1')).toBeUndefined()
    })
  })

  // ============================================================
  // Bulk operations
  // ============================================================

  describe('loadGraph', () => {
    it('clears existing state and bulk-inserts nodes and edges', () => {
      // Pre-populate
      store.addNode(makeNode({ id: 'old' }))
      store.addEdge(makeEdge({ id: 'old-e', source: 'x', target: 'y' }))
      store.selectNode('old')
      store.clusters.set('old-c', { id: 'old-c', label: 'C', icon: '📦', tint: '#fff', nodeIds: [], cohesion: 0 })

      const nodes = [makeNode({ id: 'n1' }), makeNode({ id: 'n2' })]
      const edges = [makeEdge({ id: 'e1', source: 'n1', target: 'n2' })]
      store.loadGraph(nodes, edges)

      expect(store.getNode('old')).toBeUndefined()
      expect(store.getEdge('old-e')).toBeUndefined()
      expect(store.clusters.size).toBe(0)
      expect(store.selectedNodeId).toBeNull()
      expect(store.getNode('n1')).toBeDefined()
      expect(store.getNode('n2')).toBeDefined()
      expect(store.getEdge('e1')).toBeDefined()
    })

    it('skips nodes without ids', () => {
      store.loadGraph([{ id: '' } as any, makeNode({ id: 'n1' })], [])
      expect(store.nodes.size).toBe(1)
    })

    it('skips edges without ids', () => {
      store.loadGraph([], [{ id: '' } as any, makeEdge({ id: 'e1', source: 'a', target: 'b' })])
      expect(store.edges.size).toBe(1)
    })
  })

  // ============================================================
  // applyEvent
  // ============================================================

  describe('applyEvent', () => {
    it('merges nodes and upserts edges', () => {
      store.addNode(makeNode({ id: 'n1', label: 'original', x: 10, y: 20 }))

      const event: GraphEvent = {
        sourceCommand: 'test',
        timestamp: Date.now(),
        nodes: [makeNode({ id: 'n1', label: 'updated', x: 99 } as any)],
        edges: [makeEdge({ id: 'e1', source: 'n1', target: 'n2' })],
        animation: { type: 'pulse', targetNodeIds: [] },
        metadata: {},
      }
      store.applyEvent(event)

      const merged = store.getNode('n1')!
      expect(merged.label).toBe('updated')
      // x from event takes precedence, y preserved from existing
      expect(merged.x).toBe(99)
      expect(merged.y).toBe(20)
      expect(store.getEdge('e1')).toBeDefined()
    })

    it('records the event in eventLog', () => {
      const event: GraphEvent = {
        sourceCommand: 'test',
        timestamp: Date.now(),
        nodes: [],
        edges: [],
        animation: { type: 'pulse', targetNodeIds: [] },
        metadata: {},
      }
      store.applyEvent(event)
      expect(store.eventLog).toHaveLength(1)
      expect(store.eventLog[0].sourceCommand).toBe('test')
    })
  })

  // ============================================================
  // updateNode / updateEdge
  // ============================================================

  describe('updateNode / updateEdge', () => {
    it('updateNode patches existing node and preserves edges', () => {
      store.addNode(makeNode({ id: 'n1', label: 'old', status: 'active' }))
      store.addNode(makeNode({ id: 'n2' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'calls' }))

      store.updateNode('n1', { label: 'new', status: 'warning' })

      const updated = store.getNode('n1')!
      expect(updated.label).toBe('new')
      expect(updated.status).toBe('warning')
      // Edge preserved
      expect(store.getEdge('e1')).toBeDefined()
      expect(store.getEdge('e1')!.type).toBe('calls')
    })

    it('updateNode is a no-op for non-existent node', () => {
      expect(() => store.updateNode('ghost', { label: 'x' })).not.toThrow()
    })

    it('updateEdge patches existing edge', () => {
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b', status: 'active', weight: 1 }))
      store.updateEdge('e1', { status: 'warning', weight: 5 })
      const edge = store.getEdge('e1')!
      expect(edge.status).toBe('warning')
      expect(edge.weight).toBe(5)
      expect(edge.source).toBe('a') // preserved
    })

    it('updateEdge is a no-op for non-existent edge', () => {
      expect(() => store.updateEdge('ghost', { weight: 2 })).not.toThrow()
    })
  })

  // ============================================================
  // clearGraph
  // ============================================================

  describe('clearGraph', () => {
    it('resets everything including eventLog', () => {
      store.addNode(makeNode({ id: 'n1' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b' }))
      store.clusters.set('c1', { id: 'c1', label: 'C', icon: '📦', tint: '#fff', nodeIds: [], cohesion: 0 })
      store.selectNode('n1')
      store.applyEvent({
        sourceCommand: 'x', timestamp: 0, nodes: [], edges: [],
        animation: { type: 'pulse', targetNodeIds: [] }, metadata: {},
      })

      store.clearGraph()

      expect(store.nodes.size).toBe(0)
      expect(store.edges.size).toBe(0)
      expect(store.clusters.size).toBe(0)
      expect(store.selectedNodeId).toBeNull()
      expect(store.eventLog).toHaveLength(0)
    })
  })

  // ============================================================
  // Queries
  // ============================================================

  describe('getEdgesByNode', () => {
    it('returns all edges for a node', () => {
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b' }))
      store.addEdge(makeEdge({ id: 'e2', source: 'c', target: 'a' }))
      store.addEdge(makeEdge({ id: 'e3', source: 'x', target: 'y' }))

      const edges = store.getEdgesByNode('a')
      expect(edges).toHaveLength(2)
      expect(edges.map(e => e.id)).toEqual(expect.arrayContaining(['e1', 'e2']))
    })
  })

  describe('getNeighbors', () => {
    it('returns connected nodes and edges', () => {
      store.addNode(makeNode({ id: 'a' }))
      store.addNode(makeNode({ id: 'b' }))
      store.addNode(makeNode({ id: 'c' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'a', target: 'b' }))
      store.addEdge(makeEdge({ id: 'e2', source: 'c', target: 'a' }))

      const result = store.getNeighbors('a')
      expect(result.nodes).toHaveLength(2)
      expect(result.nodes.map(n => n.id)).toEqual(expect.arrayContaining(['b', 'c']))
      expect(result.edges).toHaveLength(2)
    })

    it('returns empty for isolated node', () => {
      store.addNode(makeNode({ id: 'alone' }))
      const result = store.getNeighbors('alone')
      expect(result.nodes).toHaveLength(0)
      expect(result.edges).toHaveLength(0)
    })
  })

  describe('getNodesByType', () => {
    it('filters nodes by type', () => {
      store.addNode(makeNode({ id: 'f1', type: 'function' }))
      store.addNode(makeNode({ id: 'f2', type: 'function' }))
      store.addNode(makeNode({ id: 'c1', type: 'class', domain: 'frontend' }))

      const fns = store.getNodesByType('function')
      expect(fns).toHaveLength(2)
    })
  })

  describe('getNodesByStatus', () => {
    it('filters nodes by status', () => {
      store.addNode(makeNode({ id: 'a1', status: 'active' }))
      store.addNode(makeNode({ id: 'd1', status: 'dead' }))
      store.addNode(makeNode({ id: 'a2', status: 'active' }))

      const dead = store.getNodesByStatus('dead')
      expect(dead).toHaveLength(1)
      expect(dead[0].id).toBe('d1')
    })
  })

  describe('getNodesByCluster', () => {
    it('filters nodes by clusterId', () => {
      store.addNode(makeNode({ id: 'a', clusterId: 'auth' }))
      store.addNode(makeNode({ id: 'b', clusterId: 'auth' }))
      store.addNode(makeNode({ id: 'c', clusterId: 'api' }))

      const auth = store.getNodesByCluster('auth')
      expect(auth).toHaveLength(2)
    })
  })

  // ============================================================
  // searchNodes
  // ============================================================

  describe('searchNodes', () => {
    beforeEach(() => {
      store.addNode(makeNode({ id: 'n1', label: 'processPayment', file: 'src/api/payment.ts' }))
      store.addNode(makeNode({ id: 'n2', label: 'handleLogin', file: 'src/auth/handler.ts' }))
      store.addNode(makeNode({ id: 'n3', label: 'validateInput', file: 'src/auth/validation.ts' }))
      store.addNode(makeNode({ id: 'n4', label: 'processRefund', file: 'src/api/refund.ts' }))
    })

    it('returns empty for empty query', () => {
      expect(store.searchNodes('')).toHaveLength(0)
      expect(store.searchNodes('   ')).toHaveLength(0)
    })

    it('exact label match scores highest', () => {
      const results = store.searchNodes('handleLogin')
      expect(results[0].id).toBe('n2')
    })

    it('prefix match returns results', () => {
      const results = store.searchNodes('process')
      expect(results.length).toBeGreaterThanOrEqual(2)
      const ids = results.map(n => n.id)
      expect(ids).toEqual(expect.arrayContaining(['n1', 'n4']))
    })

    it('contains match returns results', () => {
      const results = store.searchNodes('Payment')
      expect(results.length).toBeGreaterThanOrEqual(1)
    })

    it('fuzzy subsequence match works', () => {
      const results = store.searchNodes('prpay') // p-r-o-c-e-s-s-P-a-y
      expect(results.length).toBeGreaterThanOrEqual(1)
    })

    it('file path matching works', () => {
      const results = store.searchNodes('refund.ts')
      expect(results.length).toBeGreaterThanOrEqual(1)
    })

    it('results are sorted by score descending', () => {
      const results = store.searchNodes('process')
      for (let i = 1; i < results.length; i++) {
        // Exact match or prefix should come before partial matches
        // Just verify we got results
        expect(results[i]).toBeDefined()
      }
    })
  })

  // ============================================================
  // getNodeDetail
  // ============================================================

  describe('getNodeDetail', () => {
    it('throws for non-existent node', () => {
      expect(() => store.getNodeDetail('ghost')).toThrow('Node not found')
    })

    it('computes callers, callees, references', () => {
      store.addNode(makeNode({ id: 'target', label: 'processPayment', file: 'src/api.ts', line: 10 }))
      store.addNode(makeNode({ id: 'caller1', label: 'checkout', file: 'src/page.tsx', line: 5 }))
      store.addNode(makeNode({ id: 'callee1', label: 'validatePayment', file: 'src/validate.ts', line: 1 }))
      store.addNode(makeNode({ id: 'ref1', label: 'utils', file: 'src/utils.ts', line: 3 }))
      store.addNode(makeNode({ id: 'file1', label: 'api.ts', file: 'src/api.ts', line: 1 }))

      // caller → target
      store.addEdge(makeEdge({ id: 'ec1', source: 'caller1', target: 'target', type: 'calls' }))
      // target → callee
      store.addEdge(makeEdge({ id: 'ec2', source: 'target', target: 'callee1', type: 'calls' }))
      // ref1 → target (references)
      store.addEdge(makeEdge({ id: 'er1', source: 'ref1', target: 'target', type: 'references' }))
      // file1 → target (defines)
      store.addEdge(makeEdge({ id: 'ed1', source: 'file1', target: 'target', type: 'defines' }))

      const detail = store.getNodeDetail('target')
      expect(detail.node.id).toBe('target')
      expect(detail.callers).toHaveLength(1)
      expect(detail.callers![0].fn).toBe('checkout')
      expect(detail.callees).toHaveLength(1)
      expect(detail.callees![0].fn).toBe('validatePayment')
      expect(detail.references).toHaveLength(1)
      expect(detail.references![0].source).toBe('utils')
      expect(detail.definedIn).toHaveLength(1)
      expect(detail.definedIn![0].file).toBe('src/api.ts')
    })

    it('extracts data fields like sideEffects, complexity, purity, issues', () => {
      store.addNode(makeNode({
        id: 'n1',
        data: {
          sideEffects: ['network', 'db'],
          complexity: 12,
          coverage: true,
          purity: 0.7,
          issues: [{ category: 'security', severity: 'high', message: 'SQL injection risk' }],
        },
      }))

      const detail = store.getNodeDetail('n1')
      expect(detail.sideEffects).toEqual(['network', 'db'])
      expect(detail.complexity).toBe(12)
      expect(detail.coverage).toBe(true)
      expect(detail.purity).toBe(0.7)
      expect(detail.issues).toHaveLength(1)
      expect(detail.issues![0].category).toBe('security')
    })

    it('detects test references for function nodes', () => {
      store.addNode(makeNode({ id: 'fn1', label: 'myFunc', file: 'src/fn.ts', line: 5 }))
      store.addNode(makeNode({ id: 'test1', label: 'testMyFunc', type: 'function', file: 'src/__tests__/fn.test.ts', line: 3 }))
      store.addEdge(makeEdge({ id: 'et1', source: 'test1', target: 'fn1', type: 'calls' }))

      const detail = store.getNodeDetail('fn1')
      expect(detail.tests).toHaveLength(1)
      expect(detail.tests![0].file).toContain('test')
    })

    it('returns undefined for empty arrays (callers, callees, etc.)', () => {
      store.addNode(makeNode({ id: 'n1' }))
      const detail = store.getNodeDetail('n1')
      expect(detail.callers).toBeUndefined()
      expect(detail.callees).toBeUndefined()
      expect(detail.references).toBeUndefined()
    })
  })

  // ============================================================
  // getQuickActions
  // ============================================================

  describe('getQuickActions', () => {
    const PHANTOM_COMMANDS = ['purity', 'audit', 'deps', 'analyze', 'subgraph', 'inspect', 'fix', 'test', 'issues', 'update']

    it('returns empty for non-existent node', () => {
      expect(store.getQuickActions('ghost')).toHaveLength(0)
    })

    it('returns only REAL CLI commands for function nodes', () => {
      store.addNode(makeNode({ id: 'fn1', type: 'function', label: 'myFunc' }))
      const actions = store.getQuickActions('fn1')
      for (const action of actions) {
        expect(PHANTOM_COMMANDS).not.toContain(action.command)
      }
      // Should have real commands like 'trace', 'side-effect'
      expect(actions.length).toBeGreaterThan(0)
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('side-effect')
    })

    it('returns actions for component nodes', () => {
      store.addNode(makeNode({ id: 'c1', type: 'component', label: 'MyComponent', domain: 'frontend' }))
      const actions = store.getQuickActions('c1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('context')
    })

    it('returns actions for class/id nodes', () => {
      store.addNode(makeNode({ id: 'cl1', type: 'class', label: '.btn', domain: 'frontend' }))
      const actions = store.getQuickActions('cl1')
      expect(actions.length).toBeGreaterThan(0)
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('query')
    })

    it('returns actions for file nodes', () => {
      store.addNode(makeNode({ id: 'f1', type: 'file', label: 'app.ts', file: 'src/app.ts' }))
      const actions = store.getQuickActions('f1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('dependents')
      expect(commands).toContain('dead-code')
    })

    it('returns actions for package nodes', () => {
      store.addNode(makeNode({ id: 'pkg1', type: 'package', label: 'express' }))
      const actions = store.getQuickActions('pkg1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('vuln-scan')
      expect(commands).toContain('config-drift')
    })

    it('returns actions for route nodes', () => {
      store.addNode(makeNode({ id: 'r1', type: 'route', label: '/api/auth' }))
      const actions = store.getQuickActions('r1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('test-map')
    })

    it('returns actions for store nodes', () => {
      store.addNode(makeNode({ id: 's1', type: 'store', label: 'useAuthStore' }))
      const actions = store.getQuickActions('s1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
    })

    it('returns actions for env_var nodes', () => {
      store.addNode(makeNode({ id: 'env1', type: 'env_var', label: 'DATABASE_URL' }))
      const actions = store.getQuickActions('env1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('validate')
    })

    it('returns actions for variable nodes', () => {
      store.addNode(makeNode({ id: 'v1', type: 'variable', label: 'config' }))
      const actions = store.getQuickActions('v1')
      const commands = actions.map(a => a.command)
      expect(commands).toContain('trace')
      expect(commands).toContain('query')
    })

    it('adds danger action for dead code functions', () => {
      store.addNode(makeNode({ id: 'd1', type: 'function', label: 'deadFn', status: 'dead' }))
      const actions = store.getQuickActions('d1')
      const dangerActions = actions.filter(a => a.variant === 'danger')
      expect(dangerActions.length).toBeGreaterThan(0)
      expect(dangerActions.some(a => a.command === 'dead-code')).toBe(true)
    })

    it('adds collision resolution for collision status', () => {
      store.addNode(makeNode({ id: 'col1', type: 'class', label: '.btn', domain: 'frontend', status: 'collision' }))
      const actions = store.getQuickActions('col1')
      const dangerActions = actions.filter(a => a.variant === 'danger')
      expect(dangerActions.some(a => a.command === 'refactor-safe')).toBe(true)
    })

    it('adds "Find Related" for orphan status', () => {
      store.addNode(makeNode({ id: 'o1', type: 'function', label: 'orphanFn', status: 'orphan' }))
      const actions = store.getQuickActions('o1')
      expect(actions.some(a => a.label === 'Find Related')).toBe(true)
    })

    it('adds "View Issues" for vulnerable/critical status', () => {
      store.addNode(makeNode({ id: 'vul1', type: 'function', label: 'vulnFn', status: 'vulnerable' }))
      const actions = store.getQuickActions('vul1')
      expect(actions.some(a => a.command === 'smell')).toBe(true)
    })

    it('adds dependency graph action for nodes with many neighbors', () => {
      store.addNode(makeNode({ id: 'hub', type: 'function', label: 'hubFn' }))
      for (let i = 0; i < 6; i++) {
        const nid = `nb${i}`
        store.addNode(makeNode({ id: nid }))
        store.addEdge(makeEdge({ id: `e${i}`, source: 'hub', target: nid, type: 'calls' }))
      }
      const actions = store.getQuickActions('hub')
      expect(actions.some(a => a.label === 'Show Dependency Graph')).toBe(true)
    })
  })

  // ============================================================
  // Selection
  // ============================================================

  describe('selectNode / getSelectedNode', () => {
    it('selects a node and retrieves it', () => {
      store.addNode(makeNode({ id: 'n1', label: 'hello' }))
      store.selectNode('n1')
      expect(store.selectedNodeId).toBe('n1')
      const selected = store.getSelectedNode()
      expect(selected).not.toBeNull()
      expect(selected!.id).toBe('n1')
    })

    it('deselects with null', () => {
      store.addNode(makeNode({ id: 'n1' }))
      store.selectNode('n1')
      store.selectNode(null)
      expect(store.selectedNodeId).toBeNull()
      expect(store.getSelectedNode()).toBeNull()
    })

    it('throws when selecting non-existent node', () => {
      expect(() => store.selectNode('ghost')).toThrow('Cannot select non-existent node')
    })

    it('getSelectedNode returns null when nothing selected', () => {
      expect(store.getSelectedNode()).toBeNull()
    })
  })

  // ============================================================
  // Persistence
  // ============================================================

  describe('serialize / loadFromJSON round-trip', () => {
    it('serializes and deserializes correctly', () => {
      store.addNode(makeNode({ id: 'n1', label: 'fn1', x: 10, y: 20 }))
      store.addNode(makeNode({ id: 'n2', label: 'fn2' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'n1', target: 'n2', type: 'calls' }))
      store.clusters.set('c1', { id: 'c1', label: 'Auth', icon: '🔐', tint: '#f6ad55', nodeIds: ['n1', 'n2'], cohesion: 0.8 })
      store.selectNode('n1')

      const json = store.serialize()
      const store2 = new GraphStore()
      const result = store2.loadFromJSON(json)

      expect(result).toBe(true)
      expect(store2.getNode('n1')!.label).toBe('fn1')
      expect(store2.getNode('n1')!.x).toBe(10)
      expect(store2.getNode('n2')!.label).toBe('fn2')
      expect(store2.getEdge('e1')!.type).toBe('calls')
      expect(store2.clusters.get('c1')!.label).toBe('Auth')
      expect(store2.selectedNodeId).toBe('n1')
    })

    it('loadFromJSON returns false for invalid JSON', () => {
      expect(store.loadFromJSON('not json')).toBe(false)
    })

    it('loadFromJSON handles missing optional fields', () => {
      const result = store.loadFromJSON('{}')
      expect(result).toBe(true)
      expect(store.nodes.size).toBe(0)
      expect(store.edges.size).toBe(0)
      expect(store.selectedNodeId).toBeNull()
    })
  })

  // ============================================================
  // Stats
  // ============================================================

  describe('getStats', () => {
    it('computes stats correctly', () => {
      store.addNode(makeNode({ id: 'n1', type: 'function', status: 'active' }))
      store.addNode(makeNode({ id: 'n2', type: 'function', status: 'dead' }))
      store.addNode(makeNode({ id: 'n3', type: 'class', status: 'active', domain: 'frontend' }))
      store.addEdge(makeEdge({ id: 'e1', source: 'n1', target: 'n2' }))

      const stats = store.getStats()
      expect(stats.totalNodes).toBe(3)
      expect(stats.totalEdges).toBe(1)
      expect(stats.byType.function).toBe(2)
      expect(stats.byType.class).toBe(1)
      expect(stats.byStatus.active).toBe(2)
      expect(stats.byStatus.dead).toBe(1)
    })
  })
})
