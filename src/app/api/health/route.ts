// ============================================================
// GET /api/health?workspace=/path/to/workspace
// Returns codebase health score, coupling heatmap, and recommendations
// Inspired by Axon's Analysis dashboard + Emerge's heatmap
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner, sanitizeWorkspace } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'
import { computeHealthScore, computeCoupling, computeHeatmap, computeImpactRadius } from '@/lib/healthScore'

// ─── Health Result Cache ──────────────────────────────────────
const healthCache = new Map<string, { data: any; timestamp: number }>()
const CACHE_TTL_MS = 30_000 // 30 seconds

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

    // Validate workspace path to prevent path traversal
    const safeWorkspace = sanitizeWorkspace(workspace)

    // Check cache (include nodeId in cache key if present)
    const cacheKey = nodeId ? `${safeWorkspace}:${nodeId}` : safeWorkspace
    const cached = healthCache.get(cacheKey)
    if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
      return NextResponse.json(cached.data)
    }

    // Run the scan to get current graph state
    const scanOutput = await commandRunner.scan(safeWorkspace)

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

    const responseData = {
      healthScore,
      coupling: coupling.slice(0, 50),
      heatmap: heatmap.slice(0, 100),
      impactRadius,
      timestamp: Date.now(),
    }

    // Cache the result
    healthCache.set(cacheKey, { data: responseData, timestamp: Date.now() })

    return NextResponse.json(responseData)
  } catch (err: any) {
    console.error('[/api/health] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
