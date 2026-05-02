// ============================================================
// CodeLens Neural Workspace — Cluster Engine (Brain Regions)
// ============================================================
//
// Three-layer clustering algorithm:
//   Layer 1 (50%): Group by file boundary (parent directory)
//   Layer 2 (35%): Merge clusters by import density
//   Layer 3 (15%): Apply semantic signals for labels & icons
// ============================================================

import { GraphNode, GraphEdge, Cluster, REGION_PATTERNS } from '@/types/neural'

// Minimum number of cross-group import edges required to merge two groups
const IMPORT_MERGE_THRESHOLD = 2

// Counter for generating unique cluster IDs
let clusterIdCounter = 0

function nextClusterId(): string {
  clusterIdCounter += 1
  return `cluster-${clusterIdCounter}`
}

class ClusterEngine {
  clusters: Map<string, Cluster>

  /** Cached edges from last computeClusters call, used for cohesion scoring */
  private _allEdges: GraphEdge[]

  constructor() {
    this.clusters = new Map()
    this._allEdges = []
  }

  // ============================================================
  // Main entry — compute clusters from scratch
  // ============================================================

  computeClusters(nodes: GraphNode[], edges: GraphEdge[]): Cluster[] {
    if (nodes.length === 0) return []

    // Cache edges for cohesion computation during applySemanticSignals
    this._allEdges = edges

    // Reset state
    this.clusters.clear()
    clusterIdCounter = 0

    // Layer 1: Group by file boundary
    const fileGroups = this.groupByFile(nodes)

    // Layer 2: Merge by import density
    const mergedGroups = this.mergeByImportDensity(fileGroups, edges)

    // Layer 3: Apply semantic signals → produce final Cluster[]
    const clusters = this.applySemanticSignals(mergedGroups, nodes)

    // Store in internal map
    for (const cluster of clusters) {
      this.clusters.set(cluster.id, cluster)
    }

    return clusters
  }

  // ============================================================
  // Layer 1: Group by file boundary (weight 50%)
  //
  // Extract the parent directory from each node's `file` property.
  // All nodes sharing the same parent directory are grouped together.
  // Nodes without a file go into a "no-file" bucket.
  // ============================================================

  private groupByFile(nodes: GraphNode[]): Map<string, string[]> {
    const groups = new Map<string, string[]>()
    const noFileKey = '__no_file__'

    for (const node of nodes) {
      let dirKey: string

      if (node.file) {
        // Extract parent directory from file path
        // e.g. "src/components/ui/Button.tsx" → "src/components/ui"
        const lastSlash = node.file.lastIndexOf('/')
        dirKey = lastSlash > 0 ? node.file.substring(0, lastSlash) : '__root__'
      } else {
        dirKey = noFileKey
      }

      const existing = groups.get(dirKey)
      if (existing) {
        existing.push(node.id)
      } else {
        groups.set(dirKey, [node.id])
      }
    }

    return groups
  }

  // ============================================================
  // Layer 2: Merge clusters by import density (weight 35%)
  //
  // For each pair of file-groups, count cross-group `imports` edges.
  // If count >= IMPORT_MERGE_THRESHOLD (2), merge the two groups.
  // Uses union-find for efficient merging.
  // ============================================================

  private mergeByImportDensity(
    fileGroups: Map<string, string[]>,
    edges: GraphEdge[]
  ): Map<string, string[]> {
    // Build a node-id → group-key lookup
    const nodeToGroup = new Map<string, string>()
    for (const [groupKey, nodeIds] of fileGroups) {
      for (const nodeId of nodeIds) {
        nodeToGroup.set(nodeId, groupKey)
      }
    }

    // Count cross-group import edges between every pair of groups
    const crossGroupImports = new Map<string, number>()

    for (const edge of edges) {
      if (edge.type !== 'imports') continue

      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id

      const sourceGroup = nodeToGroup.get(sourceId)
      const targetGroup = nodeToGroup.get(targetId)

      if (!sourceGroup || !targetGroup || sourceGroup === targetGroup) continue

      // Create a stable key for the pair (sorted to avoid duplicates)
      const pairKey = sourceGroup < targetGroup
        ? `${sourceGroup}||${targetGroup}`
        : `${targetGroup}||${sourceGroup}`

      crossGroupImports.set(pairKey, (crossGroupImports.get(pairKey) ?? 0) + 1)
    }

    // Union-Find to merge groups
    const parent = new Map<string, string>()
    for (const key of fileGroups.keys()) {
      parent.set(key, key)
    }

    function find(x: string): string {
      let root = x
      while (parent.get(root) !== root) {
        root = parent.get(root)!
      }
      // Path compression
      let current = x
      while (current !== root) {
        const next = parent.get(current)!
        parent.set(current, root)
        current = next
      }
      return root
    }

    function union(a: string, b: string): void {
      const ra = find(a)
      const rb = find(b)
      if (ra !== rb) {
        parent.set(ra, rb)
      }
    }

    // Merge groups with enough cross-group imports
    for (const [pairKey, count] of crossGroupImports) {
      if (count >= IMPORT_MERGE_THRESHOLD) {
        const [a, b] = pairKey.split('||')
        union(a, b)
      }
    }

    // Reconstruct merged groups
    const mergedGroups = new Map<string, string[]>()
    for (const [originalKey, nodeIds] of fileGroups) {
      const rootKey = find(originalKey)
      const existing = mergedGroups.get(rootKey)
      if (existing) {
        existing.push(...nodeIds)
      } else {
        mergedGroups.set(rootKey, [...nodeIds])
      }
    }

    return mergedGroups
  }

  // ============================================================
  // Layer 3: Apply semantic signals (weight 15%)
  //
  // For each merged group, check all node labels + file paths
  // against REGION_PATTERNS. Pick the best-matching pattern for
  // icon/label. If no match, use the directory name as label.
  // ============================================================

  private applySemanticSignals(
    groups: Map<string, string[]>,
    nodes: GraphNode[]
  ): Cluster[] {
    // Build a lookup for quick node access
    const nodeMap = new Map<string, GraphNode>()
    for (const node of nodes) {
      nodeMap.set(node.id, node)
    }

    const clusters: Cluster[] = []

    for (const [, nodeIds] of groups) {
      const groupNodes = nodeIds
        .map((id) => nodeMap.get(id))
        .filter((n): n is GraphNode => n !== undefined)

      if (groupNodes.length === 0) continue

      // Detect region label/icon/tint
      const { icon, label, tint } = this.detectRegionLabel(nodeIds, groupNodes)

      // Compute cohesion score using cached edges
      const cohesion = this.computeCohesion(nodeIds, this._allEdges)

      const cluster: Cluster = {
        id: nextClusterId(),
        label,
        icon,
        tint,
        nodeIds,
        cohesion,
      }

      clusters.push(cluster)
    }

    // Sort clusters: largest first, then by cohesion descending
    clusters.sort((a, b) => {
      if (b.nodeIds.length !== a.nodeIds.length) {
        return b.nodeIds.length - a.nodeIds.length
      }
      return b.cohesion - a.cohesion
    })

    return clusters
  }

  // ============================================================
  // Helper: detect region label/icon from node paths and names
  //
  // Score each REGION_PATTERN by the fraction of nodes that match.
  // Pick the highest-scoring pattern. Ties broken by order in
  // REGION_PATTERNS (first definition wins).
  // ============================================================

  private detectRegionLabel(
    nodeIds: string[],
    nodes: GraphNode[]
  ): { icon: string; label: string; tint: string } {
    let bestMatch: { icon: string; label: string; tint: string; score: number } | null = null

    for (const rp of REGION_PATTERNS) {
      // Count how many nodes match this pattern
      let matchCount = 0
      for (const node of nodes) {
        const text = `${node.label} ${node.file ?? ''}`
        if (rp.pattern.test(text)) {
          matchCount++
        }
      }

      if (matchCount > 0) {
        const score = matchCount / nodes.length
        if (!bestMatch || score > bestMatch.score) {
          bestMatch = { icon: rp.icon, label: rp.label, tint: rp.tint, score }
        }
      }
    }

    if (bestMatch) {
      return { icon: bestMatch.icon, label: bestMatch.label, tint: bestMatch.tint }
    }

    // Fallback: derive label from directory path of the first node
    const firstNode = nodes[0]
    if (firstNode?.file) {
      const lastSlash = firstNode.file.lastIndexOf('/')
      const secondLastSlash = firstNode.file.lastIndexOf('/', lastSlash - 1)

      if (lastSlash > 0 && secondLastSlash >= 0) {
        // Use the parent directory name, e.g. "src/components/ui/Button.tsx" → "ui"
        const parentDir = firstNode.file.substring(secondLastSlash + 1, lastSlash)
        return { icon: '📁', label: parentDir, tint: '#718096' }
      }

      if (lastSlash > 0) {
        // Only one directory level, e.g. "src/App.tsx" → "src"
        const dirName = firstNode.file.substring(0, lastSlash)
        return { icon: '📁', label: dirName, tint: '#718096' }
      }

      // No directory separator — just the filename
      return { icon: '📁', label: firstNode.file, tint: '#718096' }
    }

    // No file at all — generic region label
    return {
      icon: '🔗',
      label: `Region (${nodeIds.length})`,
      tint: '#718096',
    }
  }

  // ============================================================
  // Helper: compute cohesion score (0-1)
  //
  // Cohesion = internalEdges / (internalEdges + externalEdges)
  // where:
  //   internalEdges = edges where both source and target are in the group
  //   externalEdges = edges where exactly one endpoint is in the group
  // ============================================================

  private computeCohesion(nodeIds: string[], edges: GraphEdge[]): number {
    const nodeSet = new Set(nodeIds)

    let internalCount = 0
    let externalCount = 0

    for (const edge of edges) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id

      const sourceInGroup = nodeSet.has(sourceId)
      const targetInGroup = nodeSet.has(targetId)

      if (sourceInGroup && targetInGroup) {
        internalCount++
      } else if (sourceInGroup || targetInGroup) {
        externalCount++
      }
    }

    const total = internalCount + externalCount
    if (total === 0) return 0

    return internalCount / total
  }

  // ============================================================
  // Incremental update
  //
  // When nodes or edges change, mark affected clusters as stale.
  // The next computeClusters call will rebuild from scratch.
  //
  // For production: this is a pragmatic trade-off. A fully
  // incremental algorithm would require access to the full graph
  // (node + edge objects), which the engine doesn't own. Instead,
  // we invalidate stale clusters here and let the caller trigger
  // a full recompute when needed.
  // ============================================================

  updateIncremental(changedNodeIds: string[], changedEdgeIds: string[]): void {
    if (changedNodeIds.length === 0 && changedEdgeIds.length === 0) return

    // If any edges changed, be conservative: invalidate all clusters
    // since we can't resolve edge endpoints without the full graph.
    if (changedEdgeIds.length > 0) {
      this.clusters.clear()
      return
    }

    // Only node changes: remove clusters containing changed nodes
    const changedSet = new Set(changedNodeIds)
    const staleClusterIds: string[] = []

    for (const [clusterId, cluster] of this.clusters) {
      if (cluster.nodeIds.some((nid) => changedSet.has(nid))) {
        staleClusterIds.push(clusterId)
      }
    }

    for (const id of staleClusterIds) {
      this.clusters.delete(id)
    }
  }
}

// ============================================================
// Singleton export
// ============================================================

export const clusterEngine = new ClusterEngine()
