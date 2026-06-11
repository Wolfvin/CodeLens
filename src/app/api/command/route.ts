// ============================================================
// POST /api/command
// Body: { command: string, args: string[], workspace: string }
// Returns: GraphEvent (normalized)
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'
import { validateWorkspace } from '@/lib/constants'
import { commandRateLimiter, scanRateLimiter, getClientIp } from '@/lib/rateLimiter'
import { scanCache } from '@/lib/scanCache'

export async function POST(request: NextRequest) {
  try {
    // ─── Rate limiting ───────────────────────────────────
    const clientIp = getClientIp(request)
    const rateResult = commandRateLimiter.check(clientIp)
    if (!rateResult.allowed) {
      return NextResponse.json(
        { error: 'Rate limit exceeded', retryAfterMs: rateResult.retryAfterMs },
        { status: 429 }
      )
    }

    const body = await request.json()
    const { command, args, workspace } = body

    if (!command || typeof command !== 'string') {
      return NextResponse.json(
        { error: 'Missing or invalid required field: command' },
        { status: 400 }
      )
    }

    if (!workspace || typeof workspace !== 'string') {
      return NextResponse.json(
        { error: 'Missing or invalid required field: workspace' },
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

    const commandArgs: string[] = Array.isArray(args) ? args : []

    // Guard: watch command is not supported via REST API
    if (command === 'watch') {
      return NextResponse.json(
        {
          error: 'Watch mode is not supported via REST API. Use the WebSocket interface at port 3030 for real-time updates.',
          command: 'watch',
          suggestion: 'Connect via socket.io to /?XTransformPort=3030'
        },
        { status: 400 }
      )
    }

    // Additional rate limit for expensive scan command
    if (command === 'scan') {
      const scanRateResult = scanRateLimiter.check(clientIp)
      if (!scanRateResult.allowed) {
        return NextResponse.json(
          { error: 'Scan rate limit exceeded', retryAfterMs: scanRateResult.retryAfterMs },
          { status: 429 }
        )
      }
    }

    // Execute the command via CLI
    const rawOutput = await commandRunner.execute(command, [...commandArgs, validation.resolved])

    // Check for CLI errors
    if (rawOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${rawOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    // Normalize the output into a GraphEvent
    const graphEvent = normalizer.normalize(command, rawOutput)

    // Invalidate scan cache after scan command so subsequent graph/health requests use fresh data
    if (command === 'scan') {
      scanCache.invalidate(validation.resolved)
    }

    return NextResponse.json(graphEvent)
  } catch (err: any) {
    console.error('[/api/command] Error:', err)
    return NextResponse.json(
      { error: err.message ?? 'Internal server error' },
      { status: 500 }
    )
  }
}
