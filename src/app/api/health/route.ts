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
import { scanCache } from '@/lib/scanCache'
import { validateWorkspace } from '@/lib/constants'
import { apiRateLimiter, getClientIp } from '@/lib/rateLimiter'
import { GraphNode, GraphEdge } from '@/types/neural'

export async function GET(request: NextRequest) {
  try {
    // ─── Rate limiting ───────────────────────────────────
    const clientIp = getClientIp(request)
    const rateResult = apiRateLimiter.check(clientIp)
    if (!rateResult.allowed) {
      return NextResponse.json(
        { error: 'Rate limit exceeded', retryAfterMs: rateResult.retryAfterMs },
        { status: 429 }
      )
    }

    const { searchParams } = new URL(request.url)
    const workspace = searchParams.get('workspace')
    const nodeId = searchParams.get('nodeId')  // Optional: compute impact radius for specific node

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

    // Check health cache first to avoid re-running the CLI
    const cached = scanCache.getHealth(resolvedWorkspace)

    if (cached && !nodeId) {
      // Return cached health result — skip CLI execution
      return NextResponse.json({
        healthScore: cached.healthScore,
        coupling: cached.coupling,
        heatmap: cached.heatmap,
        impactRadius: cached.impactRadius ?? null,
        timestamp: cached.timestamp,
      })
    }

    // If nodeId is requested, we need graph data for impact radius
    // Check scan cache for the graph data first
    const cachedScan = scanCache.getScan(resolvedWorkspace)

    let nodes: GraphNode[]
    let edges: GraphEdge[]

    if (cachedScan) {
      // Use cached scan data — skip CLI execution
      nodes = cachedScan.nodes
      edges = cachedScan.edges
    } else {
      // Run the scan to get current graph state
      const scanOutput = await commandRunner.scan(resolvedWorkspace)

      if (scanOutput.status === 'error') {
        return NextResponse.json(
          { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
          { status: 500 }
        )
      }

      const graphEvent = normalizer.normalize('scan', scanOutput)
      nodes = graphEvent.nodes
      edges = graphEvent.edges
    }

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

    // Store in cache for subsequent requests (cache the base health data)
    scanCache.setHealth(resolvedWorkspace, healthScore as unknown as Record<string, unknown>, coupling, heatmap, impactRadius)

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
