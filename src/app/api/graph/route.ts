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
import { getCachedScan, setCachedScan } from '@/lib/scanCache'

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

    // Try cache first to avoid re-scanning on every request
    let scanOutput = getCachedScan(workspace)
    if (!scanOutput) {
      // Run the scan command to build the registry and get all data
      scanOutput = await commandRunner.scan(workspace)

      // Check for CLI errors
      if (scanOutput.status === 'error') {
        return NextResponse.json(
          { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
          { status: 500 }
        )
      }

      // Cache the successful scan result
      setCachedScan(workspace, scanOutput)
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
    const finalNodes = selectedNodes.map(n => ({ ...n }))
    for (const cluster of clusters) {
      for (const nodeId of cluster.nodeIds) {
        const node = finalNodes.find((n) => n.id === nodeId)
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
