// GET /api/node-detail?workspace=/path&nodeId=some_id
// Returns detailed info about a specific node
// Uses scanCache to avoid re-running CLI on every request
import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { graphStore } from '@/lib/graphStore'
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
    const nodeId = searchParams.get('nodeId')

    if (!workspace || !nodeId) {
      return NextResponse.json(
        { error: 'Missing required query parameters: workspace, nodeId' },
        { status: 400 }
      )
    }

    // Validate workspace path
    const validation = validateWorkspace(workspace)
    if (!validation.valid) {
      return NextResponse.json(
        { error: validation.error },
        { status: 400 }
      )
    }

    const resolvedWorkspace = validation.resolved

    // Try to use cached scan data first to avoid re-running CLI
    const cached = scanCache.getScan(resolvedWorkspace)
    let nodes: GraphNode[]
    let edges: GraphEdge[]

    if (cached) {
      nodes = cached.nodes
      edges = cached.edges
    } else {
      // No cache — run a scan to populate the graph store
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

    // Load into graph store for detail computation
    graphStore.loadGraph(nodes, edges)

    try {
      const detail = graphStore.getNodeDetail(nodeId)
      return NextResponse.json({ nodeId, detail })
    } catch (err: any) {
      return NextResponse.json(
        { error: err.message ?? 'Node not found' },
        { status: 404 }
      )
    }
  } catch (err: any) {
    console.error('[/api/node-detail] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
