// ============================================================
// GET /api/graph?workspace=/path/to/workspace
// Runs codelens scan on the workspace and returns normalized graph data
// Also computes and returns health score, coupling, and heatmap
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'
import { computeHealthScore, computeCoupling, computeHeatmap } from '@/lib/healthScore'

// ─── In-memory cache with 5-minute TTL ──────────────────────
interface CacheEntry {
  result: Record<string, unknown>
  timestamp: number
}

const CACHE_TTL = 5 * 60 * 1000 // 5 minutes
const graphCache = new Map<string, CacheEntry>()

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const workspace = searchParams.get('workspace')

    if (!workspace) {
      return NextResponse.json(
        { error: 'Missing required query parameter: workspace' },
        { status: 400 }
      )
    }

    // Check cache
    const cached = graphCache.get(workspace)
    if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
      return NextResponse.json(cached.result)
    }

    // Run the scan command to build the registry and get all data
    const scanOutput = await commandRunner.scan(workspace)

    // Check for CLI errors
    if (scanOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    // Normalize the scan output directly (it already has frontend.classes, frontend.ids, backend.nodes, backend.edges)
    const graphEvent = normalizer.normalize('scan', scanOutput)

    // Limit nodes to keep the browser responsive (max 500 nodes for Canvas2D)
    const MAX_NODES = 500
    let selectedNodes = graphEvent.nodes
    if (selectedNodes.length > MAX_NODES) {
      // Prioritize by status (critical > warning > active > dead) then by ref_count
      const statusPriority: Record<string, number> = { critical: 4, vulnerable: 3, warning: 2, active: 1, dead: 0, orphan: 0 }
      selectedNodes.sort((a, b) => {
        const pa = statusPriority[a.status] ?? 0
        const pb = statusPriority[b.status] ?? 0
        if (pb !== pa) return pb - pa
        return ((b.data?.refCount as number) ?? 0) - ((a.data?.refCount as number) ?? 0)
      })
      selectedNodes = selectedNodes.slice(0, MAX_NODES)
    }

    // Filter edges to only include those between selected nodes
    const selectedNodeIds = new Set(selectedNodes.map(n => n.id))
    const selectedEdges = graphEvent.edges.filter(e => {
      const srcId = typeof e.source === 'string' ? e.source : e.source.id
      const tgtId = typeof e.target === 'string' ? e.target : e.target.id
      return selectedNodeIds.has(srcId) && selectedNodeIds.has(tgtId)
    })

    // Compute clusters
    const clusters = clusterEngine.computeClusters(selectedNodes, selectedEdges)

    // Assign clusterId to each node (using cloned nodes to avoid mutation)
    // O(1) Map lookup instead of O(n) find per cluster node
    const finalNodes = selectedNodes.map(n => ({ ...n }))
    const nodeMap = new Map(finalNodes.map(n => [n.id, n]))
    for (const cluster of clusters) {
      for (const nodeId of cluster.nodeIds) {
        const node = nodeMap.get(nodeId)
        if (node) {
          node.clusterId = cluster.id
        }
      }
    }

    // Compute health score (inspired by Axon/Emerge)
    const healthScore = computeHealthScore(finalNodes, selectedEdges, clusters)

    // Compute coupling info (inspired by Axon)
    const coupling = computeCoupling(finalNodes, selectedEdges)

    // Compute heatmap (inspired by Emerge)
    const heatmap = computeHeatmap(finalNodes, selectedEdges, coupling)

    const result = {
      nodes: finalNodes,
      edges: selectedEdges,
      clusters,
      healthScore,
      coupling: coupling.slice(0, 50),  // Top 50 most coupled nodes
      heatmap: heatmap.slice(0, 100),    // Top 100 hottest nodes
    }

    // Store in cache
    graphCache.set(workspace, { result, timestamp: Date.now() })

    return NextResponse.json(result)
  } catch (err: any) {
    console.error('[/api/graph] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
