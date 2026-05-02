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

    // Run the scan command first to build the registry
    const scanOutput = await commandRunner.scan(workspace)

    // Check for CLI errors
    if (scanOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${scanOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    // Now use the list command to get actual node data from the registry
    const allNodes: any[] = []
    const allEdges: any[] = []

    // Fetch frontend classes
    try {
      const feClasses = await commandRunner.list(workspace, 'frontend', 'class')
      if (feClasses.results && Array.isArray(feClasses.results)) {
        for (const item of feClasses.results) {
          allNodes.push({
            name: item.name,
            type: 'class',
            status: item.status,
            ref_count: item.ref_count ?? 0,
            css: item.css ?? [],
            js: item.js ?? [],
            defined_in: item.defined_in,
          })
        }
      }
    } catch { /* continue */ }

    // Fetch frontend IDs
    try {
      const feIds = await commandRunner.list(workspace, 'frontend', 'id')
      if (feIds.results && Array.isArray(feIds.results)) {
        for (const item of feIds.results) {
          allNodes.push({
            name: item.name,
            type: 'id',
            status: item.status,
            ref_count: item.ref_count ?? 0,
            defined_in_html: item.defined_in_html ?? [],
            defined_in: item.defined_in,
          })
        }
      }
    } catch { /* continue */ }

    // Fetch backend nodes (functions, components)
    try {
      const beNodes = await commandRunner.list(workspace, 'backend')
      if (beNodes.results && Array.isArray(beNodes.results)) {
        for (const item of beNodes.results) {
          allNodes.push({
            fn: item.name ?? item.fn,
            id: item.id,
            type: item.type,
            status: item.status,
            file: item.file,
            line: item.line,
            component: item.component,
            impl_for: item.impl_for,
            ref_count: item.ref_count ?? 0,
            defined_in: item.defined_in,
          })
        }
      }
    } catch { /* continue */ }

    // Limit nodes to keep the browser responsive (max 300 nodes for Canvas2D)
    const MAX_NODES = 300
    const classNodes = allNodes.filter(n => n.type === 'class')
    const idNodes = allNodes.filter(n => n.type === 'id')
    const backendNodes = allNodes.filter(n => n.type !== 'class' && n.type !== 'id')

    // Prioritize: sort by ref_count descending, take top N
    const sortByRefCount = (a: any, b: any) => (b.ref_count ?? 0) - (a.ref_count ?? 0)
    const selectedClasses = classNodes.sort(sortByRefCount).slice(0, 50)
    const selectedIds = idNodes.sort(sortByRefCount).slice(0, 30)
    const remaining = MAX_NODES - selectedClasses.length - selectedIds.length
    const selectedBackend = backendNodes.sort(sortByRefCount).slice(0, Math.max(0, remaining))

    // Construct the combined output for the normalizer
    const combinedOutput = {
      frontend: {
        classes: selectedClasses,
        ids: selectedIds,
      },
      backend: {
        nodes: selectedBackend,
        edges: allEdges,
      },
    }

    // Normalize the combined output into a GraphEvent
    const graphEvent = normalizer.normalize('scan', combinedOutput)

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
