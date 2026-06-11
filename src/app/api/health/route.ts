// ============================================================
// GET /api/health?workspace=/path/to/workspace
// Returns codebase health score, coupling heatmap, and recommendations
// Inspired by Axon's Analysis dashboard + Emerge's heatmap
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'
import { computeHealthScore, computeCoupling, computeHeatmap, computeImpactRadius } from '@/lib/healthScore'
import { getCachedScan, setCachedScan } from '@/lib/scanCache'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const workspace = searchParams.get('workspace')
    const nodeId = searchParams.get('nodeId')  // Optional: compute impact radius for specific node

    if (!workspace) {
      return NextResponse.json(
        { error: 'Missing required query parameter: workspace' },
        { status: 400 }
      )
    }

    // Try cache first to avoid re-scanning on every request
    let scanOutput = getCachedScan(workspace)
    if (!scanOutput) {
      // Run the scan to get current graph state
      scanOutput = await commandRunner.scan(workspace)

      if (scanOutput.status === 'error') {
        return NextResponse.json(
          { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
          { status: 500 }
        )
      }

      // Cache the successful scan result
      setCachedScan(workspace, scanOutput)
    }

    const graphEvent = normalizer.normalize('scan', scanOutput)
    const nodes = graphEvent.nodes
    const edges = graphEvent.edges
    const clusters = clusterEngine.computeClusters(nodes, edges)

    // Compute health score
    const healthScore = computeHealthScore(nodes, edges, clusters)

    // Compute coupling info
    const coupling = computeCoupling(nodes, edges)

    // Compute heatmap
    const heatmap = computeHeatmap(nodes, edges, coupling)

    // Compute impact radius for specific node if requested
    let impactRadius = null
    if (nodeId) {
      impactRadius = computeImpactRadius(nodeId, nodes, edges)
    }

    return NextResponse.json({
      healthScore,
      coupling: coupling.slice(0, 50),
      heatmap: heatmap.slice(0, 100),
      impactRadius,
      timestamp: Date.now(),
    })
  } catch (err: any) {
    console.error('[/api/health] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
