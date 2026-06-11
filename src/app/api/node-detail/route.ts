// GET /api/node-detail?workspace=/path&nodeId=some_id
// Returns detailed info about a specific node
import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { graphStore } from '@/lib/graphStore'

export async function GET(request: NextRequest) {
  try {
    const { searchParams } = new URL(request.url)
    const workspace = searchParams.get('workspace')
    const nodeId = searchParams.get('nodeId')

    if (!workspace || !nodeId) {
      return NextResponse.json(
        { error: 'Missing required query parameters: workspace, nodeId' },
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
