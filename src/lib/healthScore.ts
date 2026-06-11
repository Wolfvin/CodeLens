// ============================================================
// CodeLens Neural Workspace — Codebase Health Score Engine
// ============================================================
//
// Computes a composite health score (0-100) inspired by:
//   - Axon: Health score + coupling heatmap + dead code report
//   - Emerge: SLOC/Fan-Out heatmap + modularity (Louvain)
//   - CodeLandscapeViewer: Impact radius + dependency depth
//   - codebase-health-score: Complexity, docs, tests, deps, collaboration
//
// Score composition:
//   25% — Code quality (smells, complexity, dead code)
//   20% — Security (vulnerabilities, secrets, taint flows)
//   20% — Test coverage (untested functions, test-to-code ratio)
//   15% — Dependency health (drift, circular deps, outdated packages)
//   10% — Architecture (coupling, cohesion, modularity)
//   10% — Maintainability (ownership concentration, file size variance)
// ============================================================

import { GraphNode, GraphEdge, NodeStatus, EdgeType } from '@/types/neural'

export interface HealthScoreBreakdown {
  overall: number                    // 0-100
  grade: 'A+' | 'A' | 'B' | 'C' | 'D' | 'F'
  quality: number                    // 0-100
  security: number                   // 0-100
  coverage: number                   // 0-100
  dependency: number                 // 0-100
  architecture: number               // 0-100
  maintainability: number            // 0-100
  metrics: {
    totalNodes: number
    totalEdges: number
    deadCodeCount: number
    deadCodePercent: number
    vulnerableCount: number
    criticalCount: number
    secretCount: number
    untestedCount: number
    untestedPercent: number
    circularDepCount: number
    avgCoupling: number
    avgCohesion: number
    ownershipConcentration: number    // 0-1 (higher = worse)
    avgComplexity: number
    highComplexityCount: number
  }
  recommendations: Array<{
    category: string
    priority: 'critical' | 'high' | 'medium' | 'low'
    message: string
    impact: number                    // estimated score improvement if fixed
  }>
}

// ---- Coupling computation ----
// Fan-Out: number of modules this module depends on
// Fan-In: number of modules that depend on this module
// Instability = Fan-Out / (Fan-In + Fan-Out) — higher = more unstable

export interface CouplingInfo {
  nodeId: string
  label: string
  fanIn: number
  fanOut: number
  instability: number       // 0-1
  coupledWith: string[]     // IDs of most-coupled neighbors
}

export function computeCoupling(
  nodes: GraphNode[],
  edges: GraphEdge[]
): CouplingInfo[] {
  const fanIn = new Map<string, Set<string>>()
  const fanOut = new Map<string, Set<string>>()

  // Initialize for all nodes
  for (const node of nodes) {
    fanIn.set(node.id, new Set())
    fanOut.set(node.id, new Set())
  }

  for (const edge of edges) {
    const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
    const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id

    // source → target: source depends on target
    const outSet = fanOut.get(sourceId)
    if (outSet) outSet.add(targetId)

    const inSet = fanIn.get(targetId)
    if (inSet) inSet.add(sourceId)
  }

  const result: CouplingInfo[] = []
  for (const node of nodes) {
    const fi = fanIn.get(node.id)?.size ?? 0
    const fo = fanOut.get(node.id)?.size ?? 0
    const total = fi + fo
    const instability = total > 0 ? fo / total : 0

    // Get top 3 coupled neighbors
    const allNeighbors = new Map<string, number>()
    for (const edge of edges) {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
      if (sourceId === node.id) {
        allNeighbors.set(targetId, (allNeighbors.get(targetId) ?? 0) + 1)
      } else if (targetId === node.id) {
        allNeighbors.set(sourceId, (allNeighbors.get(sourceId) ?? 0) + 1)
      }
    }

    const coupledWith = [...allNeighbors.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([id]) => id)

    result.push({
      nodeId: node.id,
      label: node.label,
      fanIn: fi,
      fanOut: fo,
      instability,
      coupledWith,
    })
  }

  return result.sort((a, b) => (b.fanIn + b.fanOut) - (a.fanIn + a.fanOut))
}

// ---- Impact Radius computation ----
// BFS from a node to compute how many nodes are affected at each depth level

export interface ImpactRadius {
  nodeId: string
  label: string
  totalImpacted: number
  byDepth: Record<number, { count: number; nodeIds: string[] }>
  deepestPath: number
}

export function computeImpactRadius(
  nodeId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
  maxDepth: number = 5
): ImpactRadius {
  const nodeMap = new Map<string, GraphNode>()
  for (const n of nodes) nodeMap.set(n.id, n)

  // Build adjacency: for impact analysis, follow "depends_on" direction
  // If A depends_on B, changing B impacts A
  const reverseDeps = new Map<string, string[]>()  // target → sources that depend on it
  for (const edge of edges) {
    const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
    const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
    if (!reverseDeps.has(targetId)) reverseDeps.set(targetId, [])
    reverseDeps.get(targetId)!.push(sourceId)
  }

  const visited = new Set<string>([nodeId])
  const byDepth: Record<number, { count: number; nodeIds: string[] }> = {}
  let currentLevel = [nodeId]
  let deepestPath = 0

  for (let depth = 1; depth <= maxDepth; depth++) {
    const nextLevel: string[] = []
    for (const id of currentLevel) {
      const dependents = reverseDeps.get(id) ?? []
      for (const depId of dependents) {
        if (!visited.has(depId)) {
          visited.add(depId)
          nextLevel.push(depId)
        }
      }
    }

    if (nextLevel.length === 0) break

    byDepth[depth] = {
      count: nextLevel.length,
      nodeIds: nextLevel.slice(0, 20), // Cap at 20 for memory
    }
    deepestPath = depth
    currentLevel = nextLevel
  }

  const node = nodeMap.get(nodeId)

  return {
    nodeId,
    label: node?.label ?? 'unknown',
    totalImpacted: visited.size - 1, // Exclude self
    byDepth,
    deepestPath,
  }
}

// ---- Dependency Depth computation ----
// Longest chain from this node to a leaf (no further dependencies)

export function computeDependencyDepth(
  nodeId: string,
  edges: GraphEdge[],
  maxDepth: number = 20
): number {
  const forwardDeps = new Map<string, string[]>()  // source → targets
  for (const edge of edges) {
    const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
    const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
    if (!forwardDeps.has(sourceId)) forwardDeps.set(sourceId, [])
    forwardDeps.get(sourceId)!.push(targetId)
  }

  const visited = new Set<string>()
  let maxFound = 0

  function dfs(current: string, depth: number) {
    if (depth > maxDepth || visited.has(current)) return
    visited.add(current)
    maxFound = Math.max(maxFound, depth)
    const deps = forwardDeps.get(current) ?? []
    for (const dep of deps) {
      dfs(dep, depth + 1)
    }
    visited.delete(current)
  }

  dfs(nodeId, 0)
  return maxFound
}

// ---- Heatmap Data ----
// For each node, compute a heat score based on SLOC/Fan-Out ratio
// (similar to Emerge's heatmap visualization)

export interface HeatmapEntry {
  nodeId: string
  label: string
  heat: number        // 0-1 (higher = hotter/more concerning)
  factors: {
    fanOut: number
    complexity: number
    deadCode: boolean
    vulnerable: boolean
    untested: boolean
  }
}

export function computeHeatmap(
  nodes: GraphNode[],
  edges: GraphEdge[],
  couplingInfo: CouplingInfo[]
): HeatmapEntry[] {
  const couplingMap = new Map<string, CouplingInfo>()
  for (const c of couplingInfo) couplingMap.set(c.nodeId, c)

  return nodes.map(node => {
    const coupling = couplingMap.get(node.id)
    const fanOut = coupling?.fanOut ?? 0
    const complexity = typeof node.data.complexity === 'number' ? node.data.complexity as number : 1
    const isDead = node.status === 'dead' || node.status === 'unused'
    const isVulnerable = node.status === 'vulnerable' || node.status === 'critical'
    const isUntested = node.status === 'untested'

    // Heat = weighted combination of concerning factors
    let heat = 0
    heat += Math.min(fanOut / 10, 1) * 0.25       // High fan-out
    heat += Math.min(complexity / 20, 1) * 0.25     // High complexity
    heat += isDead ? 0.15 : 0                        // Dead code
    heat += isVulnerable ? 0.2 : 0                    // Vulnerability
    heat += isUntested ? 0.15 : 0                     // Untested

    return {
      nodeId: node.id,
      label: node.label,
      heat: Math.min(heat, 1),
      factors: {
        fanOut,
        complexity,
        deadCode: isDead,
        vulnerable: isVulnerable,
        untested: isUntested,
      },
    }
  }).sort((a, b) => b.heat - a.heat)
}

// ---- Main Health Score Computation ----

export function computeHealthScore(
  nodes: GraphNode[],
  edges: GraphEdge[],
  clusters: Array<{ nodeIds: string[]; cohesion: number }>
): HealthScoreBreakdown {
  const totalNodes = nodes.length
  const totalEdges = edges.length

  if (totalNodes === 0) {
    return {
      overall: 100,
      grade: 'A+',
      quality: 100,
      security: 100,
      coverage: 100,
      dependency: 100,
      architecture: 100,
      maintainability: 100,
      metrics: {
        totalNodes: 0, totalEdges: 0,
        deadCodeCount: 0, deadCodePercent: 0,
        vulnerableCount: 0, criticalCount: 0, secretCount: 0,
        untestedCount: 0, untestedPercent: 0,
        circularDepCount: 0,
        avgCoupling: 0, avgCohesion: 0,
        ownershipConcentration: 0,
        avgComplexity: 0, highComplexityCount: 0,
      },
      recommendations: [],
    }
  }

  // ---- Compute raw metrics ----
  const deadCodeCount = nodes.filter(n => n.status === 'dead' || n.status === 'unused').length
  const deadCodePercent = (deadCodeCount / totalNodes) * 100

  const vulnerableCount = nodes.filter(n => n.status === 'vulnerable').length
  const criticalCount = nodes.filter(n => n.status === 'critical').length
  const secretCount = nodes.filter(n => n.type === 'secret').length
  const untestedCount = nodes.filter(n => n.status === 'untested').length
  const untestedPercent = (untestedCount / totalNodes) * 100

  // Detect circular dependencies (edges that form cycles)
  const circularDepCount = detectCircularDeps(nodes, edges)

  // Coupling
  const coupling = computeCoupling(nodes, edges)
  const avgCoupling = coupling.length > 0
    ? coupling.reduce((sum, c) => sum + c.fanIn + c.fanOut, 0) / coupling.length / 2
    : 0

  // Cohesion
  const avgCohesion = clusters.length > 0
    ? clusters.reduce((sum, c) => sum + c.cohesion, 0) / clusters.length
    : 0.5

  // Ownership concentration (Gini-like coefficient)
  const ownershipMap = new Map<string, number>()
  for (const node of nodes) {
    const owner = (node.data.owner as string) ?? 'unknown'
    ownershipMap.set(owner, (ownershipMap.get(owner) ?? 0) + 1)
  }
  const ownerCounts = [...ownershipMap.values()].sort((a, b) => a - b)
  const ownershipConcentration = computeGini(ownerCounts)

  // Complexity
  const complexities = nodes
    .map(n => typeof n.data.complexity === 'number' ? n.data.complexity as number : null)
    .filter((c): c is number => c !== null)
  const avgComplexity = complexities.length > 0
    ? complexities.reduce((s, c) => s + c, 0) / complexities.length
    : 5
  const highComplexityCount = complexities.filter(c => c > 15).length

  // ---- Score each dimension ----

  // Quality (25%): penalize dead code, high complexity, code smells
  let qualityScore = 100
  qualityScore -= deadCodePercent * 2          // Each % dead = -2 points
  qualityScore -= highComplexityCount * 3      // Each high-complexity = -3
  qualityScore -= (avgComplexity - 5) * 2      // Above baseline avg 5 = penalty
  qualityScore = Math.max(0, Math.min(100, qualityScore))

  // Security (20%): penalize vulnerabilities, secrets, taint flows
  let securityScore = 100
  securityScore -= criticalCount * 15          // Each critical = -15
  securityScore -= vulnerableCount * 8         // Each vulnerability = -8
  securityScore -= secretCount * 10            // Each hardcoded secret = -10
  securityScore = Math.max(0, Math.min(100, securityScore))

  // Coverage (20%): penalize untested code
  let coverageScore = 100
  coverageScore -= untestedPercent * 2.5       // Each % untested = -2.5
  coverageScore = Math.max(0, Math.min(100, coverageScore))

  // Dependency (15%): penalize drift, circular deps
  let dependencyScore = 100
  dependencyScore -= circularDepCount * 10     // Each circular dep = -10
  const driftCount = nodes.filter(n => n.type === 'package' && (n.status === 'warning' || n.status === 'critical')).length
  dependencyScore -= driftCount * 5            // Each drifted package = -5
  dependencyScore = Math.max(0, Math.min(100, dependencyScore))

  // Architecture (10%): coupling and cohesion
  let architectureScore = 100
  architectureScore -= Math.max(0, (avgCoupling - 3) * 5)   // Above 3 avg coupling = penalty
  architectureScore += (avgCohesion - 0.5) * 20              // Above 0.5 cohesion = bonus
  architectureScore = Math.max(0, Math.min(100, architectureScore))

  // Maintainability (10%): ownership concentration
  let maintainabilityScore = 100
  maintainabilityScore -= ownershipConcentration * 40         // Higher concentration = worse
  maintainabilityScore = Math.max(0, Math.min(100, maintainabilityScore))

  // ---- Weighted overall ----
  const overall = Math.round(
    qualityScore * 0.25 +
    securityScore * 0.20 +
    coverageScore * 0.20 +
    dependencyScore * 0.15 +
    architectureScore * 0.10 +
    maintainabilityScore * 0.10
  )

  // ---- Grade ----
  let grade: HealthScoreBreakdown['grade']
  if (overall >= 95) grade = 'A+'
  else if (overall >= 85) grade = 'A'
  else if (overall >= 70) grade = 'B'
  else if (overall >= 55) grade = 'C'
  else if (overall >= 40) grade = 'D'
  else grade = 'F'

  // ---- Recommendations ----
  const recommendations: HealthScoreBreakdown['recommendations'] = []

  if (deadCodeCount > 5) {
    recommendations.push({
      category: 'Quality',
      priority: deadCodePercent > 20 ? 'critical' : 'high',
      message: `Remove ${deadCodeCount} dead code items (${deadCodePercent.toFixed(1)}% of codebase)`,
      impact: Math.min(deadCodePercent * 2, 20),
    })
  }

  if (criticalCount > 0) {
    recommendations.push({
      category: 'Security',
      priority: 'critical',
      message: `Fix ${criticalCount} critical vulnerabilities immediately`,
      impact: criticalCount * 15,
    })
  }

  if (secretCount > 0) {
    recommendations.push({
      category: 'Security',
      priority: 'critical',
      message: `Move ${secretCount} hardcoded secrets to environment variables`,
      impact: secretCount * 10,
    })
  }

  if (untestedPercent > 30) {
    recommendations.push({
      category: 'Coverage',
      priority: 'high',
      message: `Add tests for ${untestedCount} untested functions (${untestedPercent.toFixed(1)}%)`,
      impact: Math.min(untestedPercent * 2.5, 25),
    })
  }

  if (circularDepCount > 0) {
    recommendations.push({
      category: 'Dependency',
      priority: circularDepCount > 3 ? 'high' : 'medium',
      message: `Break ${circularDepCount} circular dependency chain(s)`,
      impact: circularDepCount * 10,
    })
  }

  if (avgCohesion < 0.4) {
    recommendations.push({
      category: 'Architecture',
      priority: 'medium',
      message: `Low cohesion (${avgCohesion.toFixed(2)}) — consider restructuring clusters`,
      impact: 10,
    })
  }

  if (highComplexityCount > 3) {
    recommendations.push({
      category: 'Quality',
      priority: 'medium',
      message: `Simplify ${highComplexityCount} high-complexity functions`,
      impact: highComplexityCount * 3,
    })
  }

  // Sort by priority then impact
  const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 }
  recommendations.sort((a, b) => {
    const pd = priorityOrder[a.priority] - priorityOrder[b.priority]
    if (pd !== 0) return pd
    return b.impact - a.impact
  })

  return {
    overall,
    grade,
    quality: Math.round(qualityScore),
    security: Math.round(securityScore),
    coverage: Math.round(coverageScore),
    dependency: Math.round(dependencyScore),
    architecture: Math.round(architectureScore),
    maintainability: Math.round(maintainabilityScore),
    metrics: {
      totalNodes,
      totalEdges,
      deadCodeCount,
      deadCodePercent: Math.round(deadCodePercent * 10) / 10,
      vulnerableCount,
      criticalCount,
      secretCount,
      untestedCount,
      untestedPercent: Math.round(untestedPercent * 10) / 10,
      circularDepCount,
      avgCoupling: Math.round(avgCoupling * 100) / 100,
      avgCohesion: Math.round(avgCohesion * 100) / 100,
      ownershipConcentration: Math.round(ownershipConcentration * 100) / 100,
      avgComplexity: Math.round(avgComplexity * 10) / 10,
      highComplexityCount,
    },
    recommendations,
  }
}

// ---- Circular dependency detection (simple DFS cycle detection) ----

function detectCircularDeps(nodes: GraphNode[], edges: GraphEdge[]): number {
  const adjList = new Map<string, string[]>()

  for (const node of nodes) {
    adjList.set(node.id, [])
  }

  for (const edge of edges) {
    if (edge.type === 'imports' || edge.type === 'depends_on') {
      const sourceId = typeof edge.source === 'string' ? edge.source : edge.source.id
      const targetId = typeof edge.target === 'string' ? edge.target : edge.target.id
      const list = adjList.get(sourceId)
      if (list) list.push(targetId)
    }
  }

  const WHITE = 0, GRAY = 1, BLACK = 2
  const color = new Map<string, number>()
  for (const node of nodes) color.set(node.id, WHITE)

  let cycleCount = 0

  function dfs(nodeId: string): boolean {
    color.set(nodeId, GRAY)
    const neighbors = adjList.get(nodeId) ?? []
    for (const neighbor of neighbors) {
      const c = color.get(neighbor)
      if (c === GRAY) {
        cycleCount++
        return true
      }
      if (c === WHITE && dfs(neighbor)) {
        // Continue to find more cycles
      }
    }
    color.set(nodeId, BLACK)
    return false
  }

  for (const node of nodes) {
    if (color.get(node.id) === WHITE) {
      dfs(node.id)
    }
  }

  return cycleCount
}

// ---- Gini coefficient (measures inequality) ----

function computeGini(values: number[]): number {
  if (values.length === 0) return 0
  const n = values.length
  const mean = values.reduce((s, v) => s + v, 0) / n
  if (mean === 0) return 0

  // O(n) Gini using sorted-array formula:
  // G = (2 * sum(i * x_i)) / (n * sum(x_i)) - (n + 1) / n
  // where x_i are sorted ascending
  const sorted = [...values].sort((a, b) => a - b)
  let weightedSum = 0
  let totalSum = 0
  for (let i = 0; i < n; i++) {
    weightedSum += (i + 1) * sorted[i]
    totalSum += sorted[i]
  }
  if (totalSum === 0) return 0
  return (2 * weightedSum) / (n * totalSum) - (n + 1) / n
}
