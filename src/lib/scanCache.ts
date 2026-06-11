// ============================================================
// CodeLens Neural Workspace — Scan Result Cache
// ============================================================
//
// Caches the result of CLI scan commands to avoid re-running
// the Python CLI on every API request. Uses an in-memory cache
// with configurable TTL (time-to-live).
// ============================================================

import { GraphNode, GraphEdge, Cluster } from '@/types/neural'
import { DEFAULT_CACHE_TTL } from '@/lib/constants'

interface CachedScanResult {
  nodes: GraphNode[]
  edges: GraphEdge[]
  clusters: Cluster[]
  timestamp: number
  workspace: string
}

interface CachedHealthResult {
  healthScore: Record<string, unknown>
  coupling: unknown[]
  heatmap: unknown[]
  impactRadius?: unknown
  timestamp: number
  workspace: string
}

class ScanCache {
  private scanCache = new Map<string, CachedScanResult>()
  private healthCache = new Map<string, CachedHealthResult>()
  private ttl: number

  constructor(ttl: number = DEFAULT_CACHE_TTL) {
    this.ttl = ttl
  }

  /** Get cached scan result if still fresh */
  getScan(workspace: string): CachedScanResult | null {
    const cached = this.scanCache.get(workspace)
    if (!cached) return null
    if (Date.now() - cached.timestamp > this.ttl) {
      this.scanCache.delete(workspace)
      return null
    }
    return cached
  }

  /** Store scan result in cache */
  setScan(workspace: string, nodes: GraphNode[], edges: GraphEdge[], clusters: Cluster[]): void {
    this.scanCache.set(workspace, {
      nodes,
      edges,
      clusters,
      timestamp: Date.now(),
      workspace,
    })
  }

  /** Get cached health result if still fresh */
  getHealth(workspace: string): CachedHealthResult | null {
    const cached = this.healthCache.get(workspace)
    if (!cached) return null
    if (Date.now() - cached.timestamp > this.ttl) {
      this.healthCache.delete(workspace)
      return null
    }
    return cached
  }

  /** Store health result in cache */
  setHealth(workspace: string, healthScore: Record<string, unknown>, coupling: unknown[], heatmap: unknown[], impactRadius?: unknown): void {
    this.healthCache.set(workspace, {
      healthScore,
      coupling,
      heatmap,
      impactRadius,
      timestamp: Date.now(),
      workspace,
    })
  }

  /** Invalidate all caches for a workspace (call after incremental scan) */
  invalidate(workspace: string): void {
    this.scanCache.delete(workspace)
    this.healthCache.delete(workspace)
  }

  /** Invalidate all caches */
  invalidateAll(): void {
    this.scanCache.clear()
    this.healthCache.clear()
  }

  /** Set TTL (useful for testing) */
  setTTL(ttl: number): void {
    this.ttl = ttl
  }
}

export const scanCache = new ScanCache()
