// ============================================================
// GET /api/graph?workspace=/path/to/workspace
// Runs codelens scan on the workspace and returns normalized graph data
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'

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

    // Run the scan command via CLI
    const rawOutput = await commandRunner.scan(workspace)

    // Check for CLI errors
    if (rawOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${rawOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    // Normalize the scan output into a GraphEvent
    const graphEvent = normalizer.normalize('scan', rawOutput)

    // Compute clusters from the nodes and edges
    const clusters = clusterEngine.computeClusters(graphEvent.nodes, graphEvent.edges)

    // Assign clusterId to each node
    for (const cluster of clusters) {
      for (const nodeId of cluster.nodeIds) {
        const node = graphEvent.nodes.find((n) => n.id === nodeId)
        if (node) {
          node.clusterId = cluster.id
        }
      }
    }

    return NextResponse.json({
      nodes: graphEvent.nodes,
      edges: graphEvent.edges,
      clusters,
    })
  } catch (err: any) {
    console.error('[/api/graph] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
