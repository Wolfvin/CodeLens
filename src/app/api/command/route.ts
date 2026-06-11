// ============================================================
// POST /api/command
// Body: { command: string, args: string[], workspace: string }
// Returns: GraphEvent (normalized)
// ============================================================

import { NextRequest, NextResponse } from 'next/server'
import { commandRunner } from '@/lib/commandRunner'
import { normalizer } from '@/lib/normalizer'

export async function POST(request: NextRequest) {
  try {
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

    // Execute the command via CLI
    const rawOutput = await commandRunner.execute(command, [...commandArgs, workspace])

    // Check for CLI errors
    if (rawOutput.status === 'error') {
      return NextResponse.json(
        { error: `CLI error: ${rawOutput.error ?? 'Unknown error'}` },
        { status: 500 }
      )
    }

    // Normalize the output into a GraphEvent
    const graphEvent = normalizer.normalize(command, rawOutput)

    return NextResponse.json(graphEvent)
  } catch (err: unknown) {
    console.error('[/api/command] Error:', err)
    const message = err instanceof Error ? err.message : 'Internal server error'
    return NextResponse.json(
      { error: message },
      { status: 500 }
    )
  }
}
