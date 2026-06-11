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
import { scanCache } from '@/lib/scanCache'
import { validateWorkspace, MAX_GRAPH_NODES, STATUS_PRIORITY } from '@/lib/constants'
import { scanRateLimiter, getClientIp } from '@/lib/rateLimiter'
import { GraphNode, GraphEdge, Cluster } from '@/types/neural'

export async function GET(request: NextRequest) {
  try {
    // ─── Rate limiting ───────────────────────────────────
    const clientIp = getClientIp(request)
    const rateResult = scanRateLimiter.check(clientIp)
    if (!rateResult.allowed) {
      return NextResponse.json(
        { error: 'Rate limit exceeded', retryAfterMs: rateResult.retryAfterMs },
        { status: 429 }
      )
    }

    const { searchParams } = new URL(request.url)
    const workspace = searchParams.get('workspace')

    if (!workspace) {
      return NextResponse.json(
        { error: 'Missing required query parameter: workspace' },
        { status: 400 }
      )
    }

    // Validate workspace path to prevent directory traversal
    const validation = validateWorkspace(workspace)
    if (!validation.valid) {
      return NextResponse.json(
        { error: validation.error },
        { status: 400 }
      )
    }

    const resolvedWorkspace = validation.resolved

    // Check scan cache first to avoid re-running the CLI
    const cached = scanCache.getScan(resolvedWorkspace)

    let finalNodes: GraphNode[]
    let selectedEdges: GraphEdge[]
    let clusters: Cluster[]

    if (cached) {
      // Use cached scan result — skip CLI execution
      finalNodes = cached.nodes.map(n => ({ ...n }))
      selectedEdges = cached.edges
      clusters = cached.clusters
    } else {
      // Run the scan command to build the registry and get all data
      const scanOutput = await commandRunner.scan(resolvedWorkspace)

      // Check for CLI errors
      if (scanOutput.status === 'error') {
        return NextResponse.json(
          { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
          { status: 500 }
        )
      }

      // Normalize the scan output directly (it already has frontend.classes, frontend.ids, backend.nodes, backend.edges)
      const graphEvent = normalizer.normalize('scan', scanOutput)

      // Limit nodes to keep the browser responsive
      let selectedNodes = graphEvent.nodes
      if (selectedNodes.length > MAX_GRAPH_NODES) {
        // Prioritize by status then by ref_count
        selectedNodes.sort((a, b) => {
          const pa = STATUS_PRIORITY[a.status] ?? 0
          const pb = STATUS_PRIORITY[b.status] ?? 0
          if (pb !== pa) return pb - pa
          return ((b.data?.refCount as number) ?? 0) - ((a.data?.refCount as number) ?? 0)
        })
        selectedNodes = selectedNodes.slice(0, MAX_GRAPH_NODES)
      }

      // Filter edges to only include those between selected nodes
      const selectedNodeIds = new Set(selectedNodes.map(n => n.id))
      selectedEdges = graphEvent.edges.filter(e => {
        const srcId = typeof e.source === 'string' ? e.source : e.source.id
        const tgtId = typeof e.target === 'string' ? e.target : e.target.id
        return selectedNodeIds.has(srcId) && selectedNodeIds.has(tgtId)
      })

      // Compute clusters
      clusters = clusterEngine.computeClusters(selectedNodes, selectedEdges)

      // Assign clusterId to each node using efficient Map lookup (O(n) instead of O(n²))
      finalNodes = selectedNodes.map(n => ({ ...n }))
      const clusterMap = new Map<string, string>()
      for (const cluster of clusters) {
        for (const nodeId of cluster.nodeIds) {
          clusterMap.set(nodeId, cluster.id)
        }
      }
      for (const node of finalNodes) {
        const clusterId = clusterMap.get(node.id)
        if (clusterId) {
          node.clusterId = clusterId
        }
      }

      // Store in cache for subsequent requests
      scanCache.setScan(resolvedWorkspace, finalNodes, selectedEdges, clusters)
    }

    // Compute health score (inspired by Axon/Emerge)
    const healthScore = computeHealthScore(finalNodes, selectedEdges, clusters)

    // Compute coupling info (inspired by Axon)
    const coupling = computeCoupling(finalNodes, selectedEdges)

    // Compute heatmap (inspired by Emerge)
    const heatmap = computeHeatmap(finalNodes, selectedEdges, coupling)

    return NextResponse.json({
      nodes: finalNodes,
      edges: selectedEdges,
      clusters,
      healthScore,
      coupling: coupling.slice(0, 50),  // Top 50 most coupled nodes
      heatmap: heatmap.slice(0, 100),    // Top 100 hottest nodes
    })
  } catch (err: any) {
    console.error('[/api/graph] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
