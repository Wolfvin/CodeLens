// ============================================================
// CodeLens Neural Workspace — Graph Diff Engine
// ============================================================
//
// Tracks changes between graph snapshots, inspired by:
//   - CodeGraph: Neo4j graph diff between scan snapshots
//   - Emerge: Git-based metrics + change coupling detection
//   - Axon: Branch diff analysis
//
// Use cases:
//   1. Show what changed between two scans (added/removed/modified nodes)
//   2. Detect change coupling (files that change together frequently)
//   3. Generate changelog from graph diffs
// ============================================================

import { GraphNode, GraphEdge } from '@/types/neural'

export interface GraphDiff {
  timestamp: number
  previousTimestamp: number | null
  summary: {
    addedNodes: number
    removedNodes: number
    modifiedNodes: number
    addedEdges: number
    removedEdges: number
    modifiedEdges: number
    totalChangePercent: number
  }
  addedNodes: GraphNode[]
  removedNodes: GraphNode[]
  modifiedNodes: Array<{
    node: GraphNode
    previousNode: GraphNode
    changes: string[]   // field names that changed
  }>
  addedEdges: GraphEdge[]
  removedEdges: GraphEdge[]
  changeCoupling: ChangeCouplingPair[]
  riskAssessment: {
    level: 'none' | 'low' | 'medium' | 'high' | 'critical'
    factors: string[]
  }
}

export interface ChangeCouplingPair {
  fileA: string
  fileB: string
  couplingScore: number    // 0-1 (how often they change together)
  coChanges: number        // number of times changed together
}

/**
 * Compare two graph snapshots and compute the diff.
 */
export function computeGraphDiff(
  currentNodes: GraphNode[],
  currentEdges: GraphEdge[],
  previousNodes: GraphNode[],
  previousEdges: GraphEdge[],
  previousTimestamp: number | null = null
): GraphDiff {
  const currentNodeMap = new Map<string, GraphNode>()
  const prevNodeMap = new Map<string, GraphNode>()
  const currentEdgeMap = new Map<string, GraphEdge>()
  const prevEdgeMap = new Map<string, GraphEdge>()

  for (const n of currentNodes) currentNodeMap.set(n.id, n)
  for (const n of previousNodes) prevNodeMap.set(n.id, n)
  for (const e of currentEdges) currentEdgeMap.set(e.id, e)
  for (const e of previousEdges) prevEdgeMap.set(e.id, e)

  // Added nodes: in current but not in previous
  const addedNodes: GraphNode[] = []
  for (const [id, node] of currentNodeMap) {
    if (!prevNodeMap.has(id)) addedNodes.push(node)
  }

  // Removed nodes: in previous but not in current
  const removedNodes: GraphNode[] = []
  for (const [id, node] of prevNodeMap) {
    if (!currentNodeMap.has(id)) removedNodes.push(node)
  }

  // Modified nodes: in both but with changes
  const modifiedNodes: Array<{ node: GraphNode; previousNode: GraphNode; changes: string[] }> = []
  for (const [id, current] of currentNodeMap) {
    const prev = prevNodeMap.get(id)
    if (!prev) continue

    const changes: string[] = []
    if (current.label !== prev.label) changes.push('label')
    if (current.status !== prev.status) changes.push('status')
    if (current.type !== prev.type) changes.push('type')
    if (current.file !== prev.file) changes.push('file')
    if (current.line !== prev.line) changes.push('line')
    if (current.radius !== prev.radius) changes.push('radius')
    if (current.color !== prev.color) changes.push('color')
    if (current.clusterId !== prev.clusterId) changes.push('clusterId')

    // Check data changes
    const currentData = JSON.stringify(current.data)
    const prevData = JSON.stringify(prev.data)
    if (currentData !== prevData) changes.push('data')

    if (changes.length > 0) {
      modifiedNodes.push({ node: current, previousNode: prev, changes })
    }
  }

  // Added edges
  const addedEdges: GraphEdge[] = []
  for (const [id, edge] of currentEdgeMap) {
    if (!prevEdgeMap.has(id)) addedEdges.push(edge)
  }

  // Removed edges
  const removedEdges: GraphEdge[] = []
  for (const [id, edge] of prevEdgeMap) {
    if (!currentEdgeMap.has(id)) removedEdges.push(edge)
  }

  // Modified edges
  const modifiedEdges: GraphEdge[] = []
  for (const [id, current] of currentEdgeMap) {
    const prev = prevEdgeMap.get(id)
    if (!prev) continue
    if (current.status !== prev.status || current.weight !== prev.weight || current.type !== prev.type) {
      modifiedEdges.push(current)
    }
  }

  // Total change percent
  const totalCurrent = currentNodes.length + currentEdges.length
  const totalChanges = addedNodes.length + removedNodes.length + modifiedNodes.length +
                       addedEdges.length + removedEdges.length + modifiedEdges.length
  const totalChangePercent = totalCurrent > 0 ? (totalChanges / totalCurrent) * 100 : 0

  // Change coupling detection
  const changeCoupling = detectChangeCoupling(addedNodes, removedNodes, modifiedNodes)

  // Risk assessment
  const riskFactors: string[] = []
  let riskLevel: GraphDiff['riskAssessment']['level'] = 'none'

  if (removedNodes.length > 5) {
    riskFactors.push(`${removedNodes.length} nodes removed — possible breaking changes`)
    riskLevel = 'high'
  }
  if (removedEdges.length > 10) {
    riskFactors.push(`${removedEdges.length} edges removed — dependency chain broken`)
    riskLevel = riskLevel === 'none' ? 'medium' : riskLevel
  }
  if (modifiedNodes.some(m => m.changes.includes('status') && m.node.status === 'dead')) {
    riskFactors.push('Nodes changed to dead status — code may have become unreachable')
    riskLevel = riskLevel === 'none' ? 'low' : riskLevel
  }
  if (addedNodes.length > 20) {
    riskFactors.push(`${addedNodes.length} new nodes — significant codebase growth`)
    riskLevel = riskLevel === 'none' ? 'low' : riskLevel
  }

  // Check for critical status changes
  const criticalChanges = modifiedNodes.filter(
    m => m.changes.includes('status') &&
    (m.node.status === 'critical' || m.node.status === 'vulnerable')
  )
  if (criticalChanges.length > 0) {
    riskFactors.push(`${criticalChanges.length} nodes changed to critical/vulnerable status`)
    riskLevel = 'critical'
  }

  return {
    timestamp: Date.now(),
    previousTimestamp,
    summary: {
      addedNodes: addedNodes.length,
      removedNodes: removedNodes.length,
      modifiedNodes: modifiedNodes.length,
      addedEdges: addedEdges.length,
      removedEdges: removedEdges.length,
      modifiedEdges: modifiedEdges.length,
      totalChangePercent: Math.round(totalChangePercent * 10) / 10,
    },
    addedNodes,
    removedNodes,
    modifiedNodes,
    addedEdges,
    removedEdges,
    changeCoupling,
    riskAssessment: {
      level: riskLevel,
      factors: riskFactors,
    },
  }
}

/**
 * Detect change coupling — files that change together.
 * Inspired by Emerge's git-based change coupling metric.
 */
function detectChangeCoupling(
  addedNodes: GraphNode[],
  removedNodes: GraphNode[],
  modifiedNodes: Array<{ node: GraphNode }>
): ChangeCouplingPair[] {
  // Collect all files that changed
  const changedFiles = new Map<string, number>()

  const allChanged = [...addedNodes, ...removedNodes, ...modifiedNodes.map(m => m.node)]
  for (const node of allChanged) {
    const file = node.file ?? node.label
    changedFiles.set(file, (changedFiles.get(file) ?? 0) + 1)
  }

  // For change coupling, we look at files that both have changes
  const files = [...changedFiles.keys()]
  const pairs: ChangeCouplingPair[] = []

  for (let i = 0; i < files.length; i++) {
    for (let j = i + 1; j < files.length; j++) {
      const fileA = files[i]
      const fileB = files[j]

      // Both files changed in this diff → coupling score based on ratio of changes
      const changesA = changedFiles.get(fileA) ?? 0
      const changesB = changedFiles.get(fileB) ?? 0
      const minChanges = Math.min(changesA, changesB)
      const maxChanges = Math.max(changesA, changesB)

      if (minChanges > 0) {
        const couplingScore = maxChanges > 0 ? minChanges / maxChanges : 0
        pairs.push({
          fileA,
          fileB,
          couplingScore: Math.round(couplingScore * 100) / 100,
          coChanges: minChanges,
        })
      }
    }
  }

  // Sort by coupling score descending
  return pairs.sort((a, b) => b.couplingScore - a.couplingScore).slice(0, 20)
}

/**
 * Generate a human-readable changelog from a GraphDiff.
 */
export function generateChangelog(diff: GraphDiff): string {
  const lines: string[] = []
  const s = diff.summary

  lines.push(`## Graph Change Report`)
  lines.push(``)
  lines.push(`**Total changes**: ${s.totalChangePercent.toFixed(1)}% of graph modified`)
  lines.push(`- **+${s.addedNodes}** nodes added, **-${s.removedNodes}** removed, **~${s.modifiedNodes}** modified`)
  lines.push(`- **+${s.addedEdges}** edges added, **-${s.removedEdges}** removed, **~${s.modifiedEdges}** modified`)

  if (diff.riskAssessment.level !== 'none') {
    lines.push(``)
    lines.push(`**Risk level**: ${diff.riskAssessment.level.toUpperCase()}`)
    for (const factor of diff.riskAssessment.factors) {
      lines.push(`- ${factor}`)
    }
  }

  if (diff.changeCoupling.length > 0) {
    lines.push(``)
    lines.push(`### Change Coupling (files that change together)`)
    for (const pair of diff.changeCoupling.slice(0, 5)) {
      lines.push(`- \`${pair.fileA}\` ↔ \`${pair.fileB}\` (coupling: ${(pair.couplingScore * 100).toFixed(0)}%)`)
    }
  }

  return lines.join('\n')
}
