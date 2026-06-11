// GET /api/search?workspace=/path&q=query&semantic=true
// Search nodes by name or semantic TF-IDF search
import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { graphStore } from '@/lib/graphStore'

export async function GET(request: NextRequest) {
  try {
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

    // Run a scan to populate the graph store
    const scanOutput = await commandRunner.scan(workspace)
    if (scanOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    const graphEvent = normalizer.normalize('scan', scanOutput)
    graphStore.loadGraph(graphEvent.nodes, graphEvent.edges)

    if (semantic) {
      const results = graphStore.semanticSearch(q, 20)
      return NextResponse.json({ query: q, mode: 'semantic', results })
    } else {
      const nodes = graphStore.searchNodes(q)
      return NextResponse.json({ query: q, mode: 'text', nodes })
    }
  } catch (err: any) {
    console.error('[/api/search] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
