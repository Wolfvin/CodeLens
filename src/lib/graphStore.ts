// ============================================================
// CodeLens Neural Workspace — In-Memory Graph Store
// ============================================================

import {
  GraphNode,
  GraphEdge,
  Cluster,
  GraphEvent,
  NodeDetail,
  QuickAction,
  NodeType,
  NodeStatus,
} from '@/types/neural'

class GraphStore {
  // ---- State ----
  nodes: Map<string, GraphNode>
  edges: Map<string, GraphEdge>
  clusters: Map<string, Cluster>
  selectedNodeId: string | null
  eventLog: GraphEvent[]

  constructor() {
    this.nodes = new Map()
    this.edges = new Map()
    this.clusters = new Map()
    this.selectedNodeId = null
    this.eventLog = []
  }

  // ============================================================
  // CRUD — Single operations
  // ============================================================

  addNode(node: GraphNode): void {
    if (!node.id) {
      throw new Error('GraphNode must have an id')
    }
    this.nodes.set(node.id, node)
  }

  addEdge(edge: GraphEdge): void {
    if (!edge.id) {
      throw new Error('GraphEdge must have an id')
    }
    this.edges.set(edge.id, edge)
  }

  updateNode(id: string, updates: Partial<GraphNode>): void {
    const existing = this.nodes.get(id)
    if (existing) {
      this.nodes.set(id, { ...existing, ...updates })
    }
  }

  updateEdge(id: string, updates: Partial<GraphEdge>): void {
    const existing = this.edges.get(id)
    if (existing) {
      this.edges.set(id, { ...existing, ...updates })
    }
  }

  removeNode(id: string): void {
    if (!this.nodes.has(id)) return

    // Remove all edges connected to this node
    const edgesToRemove: string[] = []
    for (const [edgeId, edge] of this.edges) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
      if (sourceId === id || targetId === id) {
        edgesToRemove.push(edgeId)
      }
    }
    edgesToRemove.forEach((edgeId) => this.edges.delete(edgeId))

    // Remove node from any cluster
    for (const cluster of this.clusters.values()) {
      const idx = cluster.nodeIds.indexOf(id)
      if (idx !== -1) {
        cluster.nodeIds.splice(idx, 1)
      }
    }

    // Clear selection if this node was selected
    if (this.selectedNodeId === id) {
      this.selectedNodeId = null
    }

    this.nodes.delete(id)
  }

  removeEdge(id: string): void {
    this.edges.delete(id)
  }

  // ============================================================
  // Bulk operations
  // ============================================================

  loadGraph(nodes: GraphNode[], edges: GraphEdge[]): void {
    // Clear existing state
    this.nodes.clear()
    this.edges.clear()
    this.clusters.clear()
    this.selectedNodeId = null
    this.invalidateTfidfCache()

    // Bulk insert
    for (const node of nodes) {
      if (!node.id) continue
      this.nodes.set(node.id, node)
    }
    for (const edge of edges) {
      if (!edge.id) continue
      this.edges.set(edge.id, edge)
    }
  }

  clearGraph(): void {
    this.nodes.clear()
    this.edges.clear()
    this.clusters.clear()
    this.selectedNodeId = null
    this.eventLog = []
    this.invalidateTfidfCache()
  }

  applyEvent(event: GraphEvent): void {
    // Record the event
    this.eventLog.push(event)

    // Cap eventLog at 1000 entries to prevent unbounded memory growth
    if (this.eventLog.length > 1000) {
      this.eventLog = this.eventLog.slice(-800)
    }

    // Upsert nodes from event
    for (const node of event.nodes) {
      if (!node.id) continue
      const existing = this.nodes.get(node.id)
      if (existing) {
        // Merge: event data takes precedence, but preserve position if not in event
        this.nodes.set(node.id, {
          ...existing,
          ...node,
          x: node.x ?? existing.x,
          y: node.y ?? existing.y,
        })
      } else {
        this.nodes.set(node.id, node)
      }
    }

    // Upsert edges from event
    for (const edge of event.edges) {
      if (!edge.id) continue
      this.edges.set(edge.id, edge)
    }
  }

  // ============================================================
  // Queries
  // ============================================================

  getNode(id: string): GraphNode | undefined {
    return this.nodes.get(id)
  }

  getEdge(id: string): GraphEdge | undefined {
    return this.edges.get(id)
  }

  getNeighbors(nodeId: string): { nodes: GraphNode[]; edges: GraphEdge[] } {
    const neighborNodes: GraphNode[] = []
    const neighborEdges: GraphEdge[] = []

    for (const edge of this.edges.values()) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id

      if (sourceId === nodeId) {
        const neighbor = this.nodes.get(targetId)
        if (neighbor) {
          neighborNodes.push(neighbor)
          neighborEdges.push(edge)
        }
      } else if (targetId === nodeId) {
        const neighbor = this.nodes.get(sourceId)
        if (neighbor) {
          neighborNodes.push(neighbor)
          neighborEdges.push(edge)
        }
      }
    }

    return { nodes: neighborNodes, edges: neighborEdges }
  }

  getEdgesByNode(nodeId: string): GraphEdge[] {
    const result: GraphEdge[] = []
    for (const edge of this.edges.values()) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
      if (sourceId === nodeId || targetId === nodeId) {
        result.push(edge)
      }
    }
    return result
  }

  getNodesByType(type: NodeType): GraphNode[] {
    const result: GraphNode[] = []
    for (const node of this.nodes.values()) {
      if (node.type === type) {
        result.push(node)
      }
    }
    return result
  }

  getNodesByStatus(status: NodeStatus): GraphNode[] {
    const result: GraphNode[] = []
    for (const node of this.nodes.values()) {
      if (node.status === status) {
        result.push(node)
      }
    }
    return result
  }

  getNodesByCluster(clusterId: string): GraphNode[] {
    const result: GraphNode[] = []
    for (const node of this.nodes.values()) {
      if (node.clusterId === clusterId) {
        result.push(node)
      }
    }
    return result
  }

  searchNodes(query: string): GraphNode[] {
    if (!query.trim()) return []

    const lowerQuery = query.toLowerCase()
    const terms = lowerQuery.split(/\s+/).filter(Boolean)

    const scored: Array<{ node: GraphNode; score: number }> = []

    for (const node of this.nodes.values()) {
      const label = node.label.toLowerCase()
      const file = (node.file ?? '').toLowerCase()

      let score = 0

      for (const term of terms) {
        // Exact label match — highest score
        if (label === term) {
          score += 100
        }
        // Label starts with term
        else if (label.startsWith(term)) {
          score += 60
        }
        // Label contains term
        else if (label.includes(term)) {
          score += 40
        }
        // File path contains term
        else if (file.includes(term)) {
          score += 20
        }
        // Fuzzy: check if characters appear in order
        else if (isFuzzyMatch(label, term)) {
          score += 10
        }
      }

      if (score > 0) {
        scored.push({ node, score })
      }
    }

    // Sort by score descending
    scored.sort((a, b) => b.score - a.score)
    return scored.map((s) => s.node)
  }

  // ============================================================
  // Semantic Search (TF-IDF inspired, from Emerge)
  //
  // Goes beyond string matching by considering:
  //   - Term frequency in node labels/data
  //   - Inverse document frequency (rare terms score higher)
  //   - Semantic keyword extraction from REGION_PATTERNS
  //   - Node type and status as relevance signals
  // ============================================================

  private _tfidfCache: { docCount: number; idf: Map<string, number> } | null = null

  /** Invalidate the TF-IDF cache when nodes change */
  private invalidateTfidfCache(): void {
    this._tfidfCache = null
  }

  /** Build IDF (Inverse Document Frequency) from all node labels */
  private buildIdf(): { docCount: number; idf: Map<string, number> } {
    const docCount = this.nodes.size
    const docFreq = new Map<string, number>()

    for (const node of this.nodes.values()) {
      const tokens = tokenize(node.label + ' ' + (node.file ?? '') + ' ' + (node.data?.category ?? ''))
      const uniqueTokens = new Set(tokens)
      for (const token of uniqueTokens) {
        docFreq.set(token, (docFreq.get(token) ?? 0) + 1)
      }
    }

    const idf = new Map<string, number>()
    for (const [token, freq] of docFreq) {
      idf.set(token, Math.log((docCount + 1) / (freq + 1)) + 1) // smoothed IDF
    }

    return { docCount, idf }
  }

  /** Semantic search using TF-IDF scoring */
  semanticSearch(query: string, maxResults: number = 20): Array<{ node: GraphNode; score: number; matchedTerms: string[] }> {
    if (!query.trim()) return []

    // Build or use cached IDF
    if (!this._tfidfCache) {
      this._tfidfCache = this.buildIdf()
    }
    const { idf } = this._tfidfCache

    const queryTerms = tokenize(query)
    const queryLower = query.toLowerCase()

    const scored: Array<{ node: GraphNode; score: number; matchedTerms: string[] }> = []

    for (const node of this.nodes.values()) {
      const docText = node.label + ' ' + (node.file ?? '') + ' ' + (node.data?.category ?? '') + ' ' + (node.data?.message ?? '')
      const docTokens = tokenize(docText)
      const matchedTerms: string[] = []
      let score = 0

      for (const qTerm of queryTerms) {
        // Check for exact and partial matches in document tokens
        for (const dToken of docTokens) {
          if (dToken === qTerm) {
            // Exact term match: TF-IDF score
            const termIdf = idf.get(qTerm) ?? 1
            score += 10 * termIdf
            if (!matchedTerms.includes(qTerm)) matchedTerms.push(qTerm)
          } else if (dToken.startsWith(qTerm) || qTerm.startsWith(dToken)) {
            // Partial match (prefix)
            const termIdf = idf.get(qTerm) ?? 1
            score += 5 * termIdf
            if (!matchedTerms.includes(qTerm)) matchedTerms.push(qTerm)
          } else if (isFuzzyMatch(dToken, qTerm)) {
            // Fuzzy match
            score += 2
            if (!matchedTerms.includes(qTerm)) matchedTerms.push(qTerm)
          }
        }
      }

      // Boost by node type relevance
      const nodeLabel = node.label.toLowerCase()
      if (nodeLabel === queryLower) score *= 3        // Exact label = 3x boost
      else if (nodeLabel.startsWith(queryLower)) score *= 2  // Prefix = 2x boost

      // Boost by status relevance (critical/vulnerable nodes are more "important")
      if (node.status === 'critical' || node.status === 'vulnerable') score *= 1.2
      if (node.status === 'dead' || node.status === 'unused') score *= 0.8  // Down-rank dead code

      if (score > 0) {
        scored.push({ node, score: Math.round(score * 100) / 100, matchedTerms })
      }
    }

    // Sort by score descending
    scored.sort((a, b) => b.score - a.score)
    return scored.slice(0, maxResults)
  }

  getNodeDetail(nodeId: string): NodeDetail {
    const node = this.nodes.get(nodeId)
    if (!node) {
      throw new Error(`Node not found: ${nodeId}`)
    }

    // Compute callers: nodes that call this node
    const callers: NodeDetail['callers'] = []
    // Compute callees: nodes this node calls
    const callees: NodeDetail['callees'] = []
    // Compute references: nodes that reference this node
    const references: NodeDetail['references'] = []
    // Compute definedIn: files that define/contain this node
    const definedIn: NodeDetail['definedIn'] = []
    // Tests referencing this node
    const tests: NodeDetail['tests'] = []

    for (const edge of this.edges.values()) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
      const sourceNode = this.nodes.get(sourceId)
      const targetNode = this.nodes.get(targetId)

      if (!sourceNode || !targetNode) continue

      // This node is the target of a call → caller
      if (targetId === nodeId && edge.type === 'calls') {
        callers.push({
          fn: sourceNode.label,
          file: sourceNode.file ?? '',
          line: sourceNode.line ?? 0,
        })
      }

      // This node is the source of a call → callee
      if (sourceId === nodeId && edge.type === 'calls') {
        callees.push({
          fn: targetNode.label,
          file: targetNode.file ?? '',
          line: targetNode.line ?? 0,
        })
      }

      // This node is referenced
      if (targetId === nodeId && edge.type === 'references') {
        references.push({
          file: sourceNode.file ?? '',
          line: sourceNode.line ?? 0,
          source: sourceNode.label,
        })
      }

      // Taints edge — this node is tainted by source
      if (targetId === nodeId && edge.type === 'taints') {
        references.push({ file: sourceNode.file ?? '', line: sourceNode.line ?? 0, source: sourceNode.label })
      }

      // Sanitizes edge — this node sanitizes the source
      if (targetId === nodeId && edge.type === 'sanitizes') {
        references.push({ file: sourceNode.file ?? '', line: sourceNode.line ?? 0, source: sourceNode.label })
      }

      // This node is defined in / contained in a file
      if (
        targetId === nodeId &&
        (edge.type === 'defines' || edge.type === 'contains')
      ) {
        definedIn.push({
          file: sourceNode.file ?? sourceNode.label,
          line: sourceNode.line ?? 0,
        })
      }

      // Test references — edge from a test-like node to this node
      if (targetId === nodeId && sourceNode.type === 'function') {
        const srcFile = sourceNode.file ?? ''
        if (/(test|spec|__test__)/i.test(srcFile)) {
          tests.push({
            file: srcFile,
            line: sourceNode.line ?? 0,
          })
        }
      }
    }

    // Extract extra data fields with safe defaults
    const data = node.data ?? {}
    const sideEffects = Array.isArray(data.sideEffects)
      ? (data.sideEffects as string[])
      : undefined
    const complexity =
      typeof data.complexity === 'number' ? data.complexity : undefined
    const coverage = typeof data.coverage === 'boolean' ? data.coverage : undefined
    const purity = typeof data.purity === 'number' ? data.purity : undefined
    const issues = Array.isArray(data.issues)
      ? (data.issues as Array<{ category: string; severity: string; message: string }>)
      : undefined
    const code = typeof data.code === 'string' ? data.code : undefined

    return {
      node,
      code,
      callers: callers.length > 0 ? callers : undefined,
      callees: callees.length > 0 ? callees : undefined,
      references: references.length > 0 ? references : undefined,
      definedIn: definedIn.length > 0 ? definedIn : undefined,
      tests: tests.length > 0 ? tests : undefined,
      sideEffects,
      complexity,
      coverage,
      purity,
      issues,
    }
  }

  getQuickActions(nodeId: string): QuickAction[] {
    const node = this.nodes.get(nodeId)
    if (!node) return []

    const base: QuickAction[] = []
    const neighbors = this.getNeighbors(nodeId)

    switch (node.type) {
      case 'function':
        base.push(
          { label: 'Find Callers', command: 'trace', args: ['callers', node.label], icon: '📞', variant: 'default' },
          { label: 'Trace Execution', command: 'trace', args: ['execution', node.label], icon: '🔍', variant: 'default' },
          { label: 'Check Purity', command: 'side-effect', args: ['--name', node.label], icon: '✨', variant: 'default' },
        )
        if (node.status === 'dead') {
          base.push({ label: 'Remove Dead Code', command: 'dead-code', args: ['remove', node.label], icon: '🗑️', variant: 'danger' })
        }
        break

      case 'component':
        base.push(
          { label: 'Find Usage', command: 'trace', args: ['references', node.label], icon: '🔎', variant: 'default' },
          { label: 'Check Props', command: 'context', args: [node.label], icon: '📋', variant: 'default' },
          { label: 'Trace Render', command: 'trace', args: ['render', node.label], icon: '🎯', variant: 'default' },
        )
        break

      case 'class':
      case 'id':
        base.push(
          { label: 'Find References', command: 'trace', args: ['references', node.label], icon: '🔗', variant: 'default' },
          { label: 'Check Collisions', command: 'query', args: [node.label], icon: '💥', variant: 'warning' },
        )
        if (node.status === 'collision' || node.status === 'duplicate_define') {
          base.push({ label: 'Resolve Collision', command: 'refactor-safe', args: [node.label], icon: '🛠️', variant: 'danger' })
        }
        break

      case 'file':
        base.push(
          { label: 'Analyze Dependencies', command: 'dependents', args: [node.file ?? ''], icon: '📊', variant: 'default' },
          { label: 'Check Dead Code', command: 'dead-code', args: ['check', node.label], icon: '🧹', variant: 'default' },
        )
        break

      case 'package':
        base.push(
          { label: 'Check Vulnerabilities', command: 'vuln-scan', args: [], icon: '🛡️', variant: 'warning' },
          { label: 'Check Updates', command: 'config-drift', args: [], icon: '📦', variant: 'default' },
        )
        if (node.status === 'vulnerable' || node.status === 'critical') {
          base.push({ label: 'Update Package', command: 'config-drift', args: [], icon: '⬆️', variant: 'danger' })
        }
        break

      case 'route':
        base.push(
          { label: 'Trace Handler', command: 'trace', args: ['handler', node.label], icon: '📡', variant: 'default' },
          { label: 'Test Endpoint', command: 'test-map', args: [], icon: '🧪', variant: 'default' },
        )
        break

      case 'store':
        base.push(
          { label: 'Trace Reads', command: 'trace', args: ['reads', node.label], icon: '👁️', variant: 'default' },
          { label: 'Trace Writes', command: 'trace', args: ['writes', node.label], icon: '✏️', variant: 'default' },
        )
        break

      case 'env_var':
        base.push(
          { label: 'Check Usage', command: 'trace', args: ['usage', node.label], icon: '🔍', variant: 'default' },
          { label: 'Validate Value', command: 'validate', args: ['env', node.label], icon: '✅', variant: 'default' },
        )
        break

      case 'variable':
        base.push(
          { label: 'Find References', command: 'trace', args: ['references', node.label], icon: '🔗', variant: 'default' },
          { label: 'Check Overrides', command: 'query', args: [node.label], icon: '🔄', variant: 'default' },
        )
        break

      default:
        base.push(
          { label: 'Inspect', command: 'context', args: [node.label], icon: '🔎', variant: 'default' },
        )
    }

    // Add status-based actions
    if (node.status === 'orphan') {
      base.push({ label: 'Find Related', command: 'trace', args: ['related', node.label], icon: '🔗', variant: 'warning' })
    }
    if (node.status === 'vulnerable' || node.status === 'critical') {
      base.push({ label: 'View Issues', command: 'smell', args: [], icon: '⚠️', variant: 'danger' })
    }

    // Add neighbor-based actions
    if (neighbors.nodes.length > 5) {
      base.push({ label: 'Show Dependency Graph', command: 'trace', args: ['--direction', 'both', '--depth', '3'], icon: '🕸️', variant: 'default' })
    }

    return base
  }

  // ============================================================
  // Selection
  // ============================================================

  selectNode(id: string | null): void {
    if (id !== null && !this.nodes.has(id)) {
      throw new Error(`Cannot select non-existent node: ${id}`)
    }
    this.selectedNodeId = id
  }

  getSelectedNode(): GraphNode | null {
    if (this.selectedNodeId === null) return null
    return this.nodes.get(this.selectedNodeId) ?? null
  }

  // ============================================================
  // Persistence
  // ============================================================

  serialize(): string {
    return JSON.stringify({
      nodes: Array.from(this.nodes.values()),
      edges: Array.from(this.edges.values()),
      clusters: Array.from(this.clusters.values()),
      selectedNodeId: this.selectedNodeId,
    })
  }

  loadFromJSON(json: string): boolean {
    try {
      const data = JSON.parse(json)
      this.nodes.clear()
      this.edges.clear()
      this.clusters.clear()
      for (const node of data.nodes ?? []) {
        if (node.id) this.nodes.set(node.id, node)
      }
      for (const edge of data.edges ?? []) {
        if (edge.id) this.edges.set(edge.id, edge)
      }
      for (const cluster of data.clusters ?? []) {
        if (cluster.id) this.clusters.set(cluster.id, cluster)
      }
      this.selectedNodeId = data.selectedNodeId ?? null
      return true
    } catch (err: any) {
      console.warn('[GraphStore] loadFromJSON failed:', err?.message ?? err)
      return false
    }
  }

  // ============================================================
  // Stats
  // ============================================================

  getStats(): {
    totalNodes: number
    totalEdges: number
    byType: Record<string, number>
    byStatus: Record<string, number>
  } {
    const byType: Record<string, number> = {}
    const byStatus: Record<string, number> = {}

    for (const node of this.nodes.values()) {
      byType[node.type] = (byType[node.type] ?? 0) + 1
      byStatus[node.status] = (byStatus[node.status] ?? 0) + 1
    }

    return {
      totalNodes: this.nodes.size,
      totalEdges: this.edges.size,
      byType,
      byStatus,
    }
  }
}

// ============================================================
// Fuzzy match helper — checks if all chars of `query` appear
// in `text` in order (subsequence match)
// ============================================================

function isFuzzyMatch(text: string, query: string): boolean {
  let ti = 0
  let qi = 0
  while (ti < text.length && qi < query.length) {
    if (text[ti] === query[qi]) {
      qi++
    }
    ti++
  }
  return qi === query.length
}

// ============================================================
// Tokenize helper — splits text into searchable tokens
// Handles camelCase, snake_case, kebab-case, paths
// ============================================================

function tokenize(text: string): string[] {
  if (!text) return []

  // Split on: camelCase boundaries, underscores, hyphens, dots, slashes, whitespace
  const parts = text
    .replace(/([a-z])([A-Z])/g, '$1 $2')   // camelCase → camel Case
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2') // XMLParser → XML Parser
    .replace(/[_\-./\\]/g, ' ')               // snake/kebab/dot/slash → space
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .split(' ')
    .filter(t => t.length > 1)   // Skip single-char tokens

  return parts
}

// ============================================================
// Singleton export
// ============================================================

export const graphStore = new GraphStore()
