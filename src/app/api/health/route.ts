// ============================================================
// GET /api/health?workspace=/path/to/workspace
// Returns codebase health score, coupling heatmap, and recommendations
// Inspired by Axon's Analysis dashboard + Emerge's heatmap
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { validateWorkspace } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'
import { computeHealthScore, computeCoupling, computeHeatmap, computeImpactRadius } from '@/lib/healthScore'

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

    // Validate workspace path to prevent command injection
    let validatedWorkspace: string
    try {
      validatedWorkspace = validateWorkspace(workspace)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Invalid workspace'
      return NextResponse.json({ error: message }, { status: 400 })
    }

    // Run the scan to get current graph state
    const scanOutput = await commandRunner.scan(validatedWorkspace)

    if (scanOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
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
  } catch (err: unknown) {
    console.error('[/api/health] Error:', err)
    const message = err instanceof Error ? err.message : 'Internal server error'
    return NextResponse.json(
      { error: message },
      { status: 500 }
    )
  }
}
