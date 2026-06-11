// GET /api/search?workspace=/path&q=query&semantic=true
// Search nodes by name or semantic TF-IDF search
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
    const q = searchParams.get('q')
    const semantic = searchParams.get('semantic') === 'true'

    if (!workspace || !q) {
      return NextResponse.json(
        { error: 'Missing required query parameters: workspace, q' },
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

    // Load into graph store for search operations
    graphStore.loadGraph(nodes, edges)

    if (semantic) {
      const results = graphStore.semanticSearch(q, 20)
      return NextResponse.json({ query: q, mode: 'semantic', results })
    } else {
      const resultNodes = graphStore.searchNodes(q)
      return NextResponse.json({ query: q, mode: 'text', nodes: resultNodes })
    }
  } catch (err: any) {
    console.error('[/api/search] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
