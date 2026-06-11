// ============================================================
// GET /api/health?workspace=/path/to/workspace
// Returns codebase health score, coupling heatmap, and recommendations
// Inspired by Axon's Analysis dashboard + Emerge's heatmap
// Supports TTL-based caching (30s) with ?refresh=true to bypass
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { clusterEngine } from '@/lib/clusterEngine'
import { computeHealthScore, computeCoupling, computeHeatmap, computeImpactRadius } from '@/lib/healthScore'

// ─── Simple TTL Cache ──────────────────────────────────────
const CACHE_TTL_MS = 30_000 // 30 seconds
const healthCache = new Map<string, { data: any; timestamp: number }>()

function getCached(key: string): any | null {
  const entry = healthCache.get(key)
  if (!entry) return null
  if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
    healthCache.delete(key)
    return null
  }
  return entry.data
}

function setCache(key: string, data: any): void {
  healthCache.set(key, { data, timestamp: Date.now() })
  if (healthCache.size > 100) {
    const now = Date.now()
    for (const [k, v] of healthCache) {
      if (now - v.timestamp > CACHE_TTL_MS) healthCache.delete(k)
    }
  }
}

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

    // Check cache (skip if refresh=true, or if nodeId is specified since that's a specific query)
    const cacheKey = nodeId ? `${workspace}__${nodeId}` : workspace
    if (!nodeId && searchParams.get('refresh') !== 'true') {
      const cached = getCached(cacheKey)
      if (cached) {
        return NextResponse.json(cached)
      }
    }

    // Run the scan to get current graph state
    const scanOutput = await commandRunner.scan(workspace)

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

    const result = {
      healthScore,
      coupling: coupling.slice(0, 50),
      heatmap: heatmap.slice(0, 100),
      impactRadius,
      timestamp: Date.now(),
    }

    // Cache the result (only for non-nodeId queries)
    if (!nodeId) {
      setCache(cacheKey, result)
    }

    return NextResponse.json(result)
  } catch (err: any) {
    console.error('[/api/health] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
